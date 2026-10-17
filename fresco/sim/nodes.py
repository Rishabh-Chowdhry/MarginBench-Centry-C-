"""Simulated ledger node and worker nodes speaking the fresco.messages protocol."""

from dataclasses import dataclass

from fresco.ledger import Ledger
from fresco.messages import REQUEST_KINDS, Message

LEDGER = "ledger"


class LedgerNode:
    """Hosts the Ledger state machine. A crash loses volatile state; recovery
    replays the durable journal (write-ahead: an op is journaled before it runs)."""

    def __init__(self, engine, net, cfg, run_key, worker_names, tick=5.0):
        self.engine, self.net, self.cfg, self.run_key = engine, net, cfg, run_key
        self.ledger = Ledger(cfg, run_key)
        self.workers = worker_names
        self.up = True
        self.tick_interval = tick
        self.seq = 0
        self.recoveries = []          # (crash_time, recover_time, digest_equal)
        net.attach(LEDGER, self.on_message)
        engine.after(tick, self._tick)

    def on_message(self, msg):
        if not self.up:
            return
        msg.validate()
        if msg.kind not in REQUEST_KINDS:
            return
        result = self.ledger.apply(msg.kind, sender=msg.src, req_id=msg.req_id,
                                   now=self.engine.now, **msg.body)
        self.engine.trace("L", msg.kind, msg.src, msg.req_id, sorted(result.items()) if isinstance(result, dict) else result)
        self.net.send(Message("response", LEDGER, msg.src, msg.req_id, {"of": msg.kind, "result": result}))
        self._publish()

    def _publish(self):
        events, self.ledger.events = self.ledger.events, []
        for ev in events:
            self.seq += 1
            if ev[0] == "frontier":
                body, kind = {"b_hat": ev[1], "witness": ev[2], "seq": self.seq}, "frontier"
            else:
                body, kind = {"j": ev[1], "status": ev[2], "seq": self.seq}, "status"
            for w in self.workers:
                self.net.send(Message(kind, LEDGER, w, -self.seq, body))
        if self.ledger.b_hat == 1:
            self.engine.stopped = True

    def _tick(self):
        if self.up:
            self.ledger.apply("tick", sender=LEDGER, now=self.engine.now)
            self._publish()
            if self._exhausted():
                self.engine.stopped = True
        self.engine.after(self.tick_interval, self._tick)

    def _exhausted(self):
        led = self.ledger
        if led.slots_leased < self.cfg.max_slots:
            return False
        return not any(s["state"] == "LEASED" for s in led.slots.values()) and \
            not any(a["state"] == "LEASED" for a in led.audits.values())

    def crash(self, downtime):
        if not self.up:
            return
        self.up = False
        before = self.ledger.digest()
        journal = self.ledger.journal       # durable
        t_crash = self.engine.now
        self.ledger = None                  # volatile state lost

        self._durable = (journal, before, t_crash)
        self.engine.after(downtime, self.recover_now)

    def recover_now(self):
        if self.up:
            return
        journal, before, t_crash = self._durable
        self.ledger = Ledger.recover(self.cfg, self.run_key, journal)
        self.up = True
        self.recoveries.append((t_crash, self.engine.now, self.ledger.digest() == before))


@dataclass(frozen=True)
class WorkerConfig:
    executors: int = 4            # concurrent slots per worker
    inflight_per_candidate: int = 2
    pool: int = 2                 # active candidates per worker
    audit_share: float = 0.1
    lease_fraction: float = 1 / 16
    rotate_after: int = 8         # registrations per budget lease before closing it
    rpc_timeout: float = 2.0
    poll: float = 1.0


class Worker:
    def __init__(self, engine, net, name, wcfg, lcfg, scenario):
        self.engine, self.net, self.name, self.w, self.l, self.sc = engine, net, name, wcfg, lcfg, scenario
        self.inc = 0
        self.alive = False
        self.executions = 0
        self.crashes = 0
        net.attach(name, self.on_message)
        self.start()

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        self.inc += 1
        self.alive = True
        self.ident = f"{self.name}.{self.inc}"
        self.rng = self.engine.rng("gen", self.ident)
        self.req = 0
        self.pending = {}            # req_id -> (msg, callback)
        self.lease = None
        self.lease_requested = False
        self.cands = {}              # j -> {"level", "content", "inflight"}
        self.busy = 0
        self._registering = 0
        self.registered_on_lease = 0
        self.view = float("inf")
        self.engine.after(0.0, self._schedule, self.inc)

    def crash(self, downtime):
        if not self.alive:
            return
        self.alive = False
        self.crashes += 1
        self.engine.after(downtime, self.start)

    # ---------------------------------------------------------------- rpc
    def _call(self, kind, body, cb):
        self.req += 1
        msg = Message(kind, self.ident, LEDGER, self.req, body).validate()
        self.pending[self.req] = (msg, cb)
        self._send(self.req, self.inc)

    def _send(self, rid, inc):
        if inc != self.inc or not self.alive or rid not in self.pending:
            return
        self.net.send(self.pending[rid][0])
        self.engine.after(self.w.rpc_timeout, self._send, rid, inc)    # retry until answered

    def on_message(self, msg):
        if not self.alive:
            return
        if msg.kind == "frontier":
            self.view = min(self.view, msg.body["b_hat"])
            for j in [j for j, c in self.cands.items() if c["level"] >= self.view]:
                self.cands.pop(j)
            return
        if msg.kind == "status":
            if msg.body["status"] != "ACTIVE":
                self.cands.pop(msg.body["j"], None)
            return
        if msg.kind == "response" and msg.dst == self.ident and msg.req_id in self.pending:
            _, cb = self.pending.pop(msg.req_id)
            cb(msg.body["result"])

    # Workers are addressed by base name; responses carry the incarnation id.
    # A response to a previous incarnation is dropped (dst mismatch).

    # ---------------------------------------------------------------- scheduling
    def _schedule(self, inc):
        if inc != self.inc or not self.alive:
            return
        if self.lease is None and not self.lease_requested:
            self.lease_requested = True
            self._call("grant", {"amount": self.l.eps * self.w.lease_fraction}, self._on_grant)
        while self.busy < self.w.executors and self._one_action():
            pass
        self.engine.after(self.w.poll, self._schedule, inc)

    def _active_levels(self):
        return [k for k in range(1, self.l.levels + 1) if k < self.view]

    def _one_action(self):
        levels = self._active_levels()
        if not levels:
            return False
        if self.rng.random() < self.w.audit_share:
            self.busy += 1
            self._call("lease_audit", {"level": int(self.rng.choice(levels))}, self._on_audit_lease)
            return True
        ready = [j for j, c in self.cands.items() if c["inflight"] < self.w.inflight_per_candidate]
        if ready:
            j = ready[int(self.rng.integers(len(ready)))]
            n = min(self.w.inflight_per_candidate - self.cands[j]["inflight"], self.w.executors - self.busy)
            self.cands[j]["inflight"] += n
            self.busy += n
            self._call("lease_slots", {"j": j, "count": n}, lambda r, j=j, n=n: self._on_slots(j, n, r))
            return True
        if self.lease is not None and len(self.cands) + self._registering < self.w.pool:
            level = int(self.rng.choice(levels))
            content = int(self.rng.integers(self.sc.levels[level - 1].space))
            self._registering += 1
            self._call("register", {"lease_id": self.lease, "content": content, "level": level},
                       lambda r, lv=level, ct=content: self._on_register(lv, ct, r))
            return True
        return False

    def _on_grant(self, r):
        self.lease_requested = False
        if r.get("ok"):
            self.lease = r["lease_id"]
            self.registered_on_lease = 0

    def _on_register(self, level, content, r):
        self._registering = max(0, self._registering - 1)
        if r.get("ok"):
            self.cands[r["j"]] = {"level": level, "content": content, "inflight": 0}
            self.registered_on_lease += 1
            if self.registered_on_lease >= self.w.rotate_after and self.lease is not None:
                # rotate: fence this lease and reclaim its unspent tail (R5)
                self._call("close_lease", {"lease_id": self.lease}, lambda r: None)
                self.lease = None
        elif r.get("reason") in ("LEASE_CLOSED", "UNKNOWN_LEASE"):
            self.lease = None

    def _on_slots(self, j, n, r):
        c = self.cands.get(j)
        grants = r.get("grants", []) if r.get("ok") else []
        unused = n - len(grants)
        self.busy -= unused
        if c is not None:
            c["inflight"] -= unused
            if not r.get("ok"):
                self.cands.pop(j, None)
        for g in grants:
            self._execute(j, c, g)

    def _execute(self, j, c, g):
        level, content = (c["level"], c["content"]) if c else (None, None)
        if level is None:
            self.busy -= 1
            return
        attempt = int(g["token"].rsplit(":", 1)[1])
        y, latency, crashed = self.sc.execution(level, content, g["key"], attempt)
        self.executions += 1
        self.engine.after(latency, self._done, j, g, y, crashed, self.inc)

    def _done(self, j, g, y, crashed, inc):
        if inc != self.inc or not self.alive:
            return
        self.busy -= 1
        c = self.cands.get(j)
        if c is not None:
            c["inflight"] -= 1
        if not crashed:                                   # crashed executor: no report, ledger expires slot
            self._call("record", {"j": j, "k": g["k"], "y": int(y), "token": g["token"],
                                  "trace_hash": f"{g['key']:x}"}, lambda r: None)

    def _on_audit_lease(self, r):
        if not r.get("ok"):
            self.busy -= 1
            return
        level = r["level"]
        content = self.sc.audit_content(level, r["seed"])
        total, hits, crashed = 0.0, 0, False
        for key in r["keys"]:
            y, lat, cr = self.sc.execution(level, content, key, 0)
            total += lat
            hits += y
            crashed |= cr
        z = int(hits >= self.l.audit_threshold)
        self.executions += len(r["keys"])
        self.engine.after(total, self._audit_done, level, r["i"], z, crashed, r["token"], self.inc)

    def _audit_done(self, level, i, z, crashed, token, inc):
        if inc != self.inc or not self.alive:
            return
        self.busy -= 1
        if not crashed:
            self._call("record_audit", {"level": level, "i": i, "z": int(z), "token": token}, lambda r: None)
