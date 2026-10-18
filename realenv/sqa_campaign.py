"""E12: SQA campaign for the networked QUINTET deployment on simulated devices
(Docker containers) with real network, process and storage faults. Test cases and
pass criteria are fixed in realenv/TEST_PLAN.md.

Requires: a running Docker daemon, the image quintet-device:1 (realenv/build_image.sh)
and a Toxiproxy server binary (path in TOXIPROXY_BIN; it is bind-mounted into a
device container).

Run: python3 -I realenv/sqa_campaign.py <work dir> [TC ...]
"""

import copy
import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.e11_adversary import anchor_domains, control  # noqa: E402
from fresco.hkg.corrupt import tamper_node  # noqa: E402
from fresco.hkg.graph import DOMAINS, DomainStore, Fabric, Node  # noqa: E402
from fresco.hkg import sign  # noqa: E402
from fresco.hkg.repair import QUARANTINED, RunParams, TWGRConfig, derive_confirmation, report, twgr  # noqa: E402
from realenv.disk_corrupt import corrupt_file  # noqa: E402

IMAGE = "quintet-device:1"
NET = "qnet"
PARAMS = {"eps": 0.05, "lease_size": 8, "alpha": 0.2, "cap": 40, "run_key": "sqa-run-key"}
# executor devices sign their evidence; the manifest of their public keys is published
# before the run and given to every coordinator (TWGR-S). Secrets go only to the devices.
DEVICE_SECRETS = {f"w{i}": f"sqa-device-secret-{i}" for i in range(1, 7)}
MANIFEST = sign.make_manifest("sqa-run-1", DEVICE_SECRETS)
RP = RunParams(eps=0.05, lease_size=8, run_key=b"sqa-run-key", alpha=0.2, cap=40, manifest=MANIFEST)
TWGR_S = TWGRConfig(authenticate=True)
HOST_PORT = {r: 18101 + i for i, r in enumerate(DOMAINS)}
TOXI_PORT = {r: 9201 + i for i, r in enumerate(DOMAINS)}
SLOT_TTL = 8
K_STAR = 3
TOXI_BIN = None


def sh(*args, check=True, timeout=600):
    r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def http(port, path, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


# ------------------------------------------------------------------ cluster control
class Cluster:
    def __init__(self, work, scenario="S1-dense"):
        self.work, self.scenario = pathlib.Path(work), scenario
        self.data = self.work / "data"

    def env(self, peers):
        return ["-e", "QUINTET_PEERS=" + json.dumps(peers), "-e", "QUINTET_PARAMS=" + json.dumps(PARAMS),
                "-e", "QUINTET_SCENARIO=" + self.scenario, "-e", "QUINTET_MANIFEST=" + json.dumps(MANIFEST)]

    def down(self):
        ids = sh("docker", "ps", "-aq", "--filter", "name=^q-", check=False).split()
        if ids:
            sh("docker", "rm", "-f", *ids, check=False)

    def up(self, fresh=True):
        self.down()
        if fresh and self.data.exists():
            shutil.rmtree(self.data)
        for r in DOMAINS:
            (self.data / r).mkdir(parents=True, exist_ok=True)
        if NET not in sh("docker", "network", "ls", "--format", "{{.Name}}").split():
            sh("docker", "network", "create", NET)
        sh("docker", "run", "-d", "--name", "q-toxi", "--network", NET, "-p", "18474:8474",
           "-v", f"{TOXI_BIN}:/usr/local/bin/toxiproxy-server:ro", IMAGE,
           "toxiproxy-server", "-host", "0.0.0.0")
        for r in DOMAINS:
            self.start_coordinator(r)
        self.wait_healthy()
        for r in DOMAINS:
            self.toxi("/proxies", {"name": f"p-{r}", "listen": f"0.0.0.0:{TOXI_PORT[r]}",
                                   "upstream": f"q-{r}:8000", "enabled": True})

    def start_coordinator(self, r):
        sh("docker", "rm", "-f", f"q-{r}", check=False)
        peers = {d: f"http://q-{d}:8000" for d in DOMAINS}
        sh("docker", "run", "-d", "--name", f"q-{r}", "--network", NET, "-p", f"{HOST_PORT[r]}:8000",
           "-v", f"{ROOT}:/app:ro", "-v", f"{self.data / r}:/data", *self.env(peers), IMAGE,
           "python", "-m", "fresco.quintet.service", "coordinator", "--role", r, "--port", "8000",
           "--data", "/data", "--slot-ttl", str(SLOT_TTL))

    def stop_coordinators(self):
        sh("docker", "rm", "-f", *[f"q-{r}" for r in DOMAINS], check=False)

    def start_coordinators(self):
        for r in ("archivist",) + tuple(d for d in DOMAINS if d != "archivist"):
            self.start_coordinator(r)
            if r == "archivist":
                self.wait_healthy(["archivist"])
        self.wait_healthy()

    def wait_healthy(self, roles=DOMAINS, limit=60):
        t0 = time.time()
        while time.time() - t0 < limit:
            try:
                for r in roles:
                    http(HOST_PORT[r], "/health", timeout=2)
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("cluster not healthy")

    def toxi(self, path, body=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:18474{path}", data=data,
                                     method=method or ("POST" if body is not None else "GET"),
                                     headers={"Content-Type": "application/json"})
        for _ in range(40):
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.read()
            except urllib.error.URLError:
                time.sleep(0.25)
        raise RuntimeError("toxiproxy unreachable")

    def add_toxic(self, role, name, typ, attrs, toxicity=1.0, stream="downstream"):
        self.toxi(f"/proxies/p-{role}/toxics", {"name": name, "type": typ, "stream": stream,
                                                 "toxicity": toxicity, "attributes": attrs})

    def start_workers(self, n, budget, seed0=0, prefix="w"):
        peers = {d: f"http://q-toxi:{TOXI_PORT[d]}" for d in DOMAINS}
        names = []
        for i in range(n):
            name = f"q-{prefix}{i + 1}"
            sh("docker", "rm", "-f", name, check=False)
            sh("docker", "run", "-d", "--name", name, "--network", NET, "--cpus", "0.5", "--memory", "192m",
               "-v", f"{ROOT}:/app:ro", *self.env(peers),
               "-e", "QUINTET_DEVICE_SECRET=" + DEVICE_SECRETS[f"{prefix}{i + 1}"], IMAGE,
               "python", "-m", "fresco.quintet.service",
               "worker", "--name", f"{prefix}{i + 1}", "--budget", str(budget), "--seed", str(seed0 + i))
            names.append(name)
        return names

    def wait_workers(self, names, limit=900):
        out = []
        t0 = time.time()
        for n in names:
            sh("docker", "wait", n, check=False, timeout=max(5, limit - (time.time() - t0)))
            logs = sh("docker", "logs", n, check=False).splitlines()
            try:
                out.append(json.loads(logs[-1]))
            except (IndexError, ValueError):
                out.append({"worker": n, "killed": True})
        return out

    def quiesce(self, limit=180):
        """Replication queues empty and every open slot past its expiry."""
        time.sleep(SLOT_TTL + 3)
        t0 = time.time()
        while time.time() - t0 < limit:
            try:
                if all(http(HOST_PORT[r], "/health")["pending"] == 0 for r in DOMAINS):
                    time.sleep(1.0)
                    if all(http(HOST_PORT[r], "/health")["pending"] == 0 for r in DOMAINS):
                        return time.time() - t0
            except Exception:
                pass
            time.sleep(1.0)
        return None

    def snapshot(self):
        fab = Fabric()
        for r in DOMAINS:
            d = http(HOST_PORT[r], "/dump", timeout=60)
            st = DomainStore(r)
            st.blobs = {tuple(i.split(":", 1)): __import__("base64").b64decode(b) for i, b in d["blobs"].items()}
            st.log = d["log"]
            fab.stores[r] = st
        return fab

    def scan(self):
        r = http(HOST_PORT["archivist"], "/scan", {}, timeout=600)
        r.pop("accepted", None)
        return r


# ------------------------------------------------------------------ invariants
def invariants(fab, check_write_once=True, scope=None):
    """scope: ids for which I1, I4 and I5 are checked (default all). After storage faults,
    quarantined records keep their unverifiable copies by design, so TC12 checks the
    records written after the repair."""
    status, acc = twgr(copy.deepcopy(fab), RP, TWGR_S, heal=False)
    inscope = (lambda i: True) if scope is None else (lambda i: i in scope)  # noqa: E731
    out = {"records": len(status), "status": {}}
    for s in status.values():
        out["status"][s] = out["status"].get(s, 0) + 1
    if check_write_once:
        conflicts = 0
        ids = set().union(*[set(st.blobs) for st in fab.stores.values()])
        for nid in filter(inscope, ids):
            vals = set()
            for st in fab.stores.values():
                b = st.blobs.get(nid)
                try:
                    if b is not None and Node.decode(b).id == nid:
                        vals.add(b)
                except ValueError:
                    pass
            conflicts += len(vals) > 1
        out["I1_conflicts"] = conflicts
    allocs = [n for i, n in acc.items() if i[0] == "Allocation"]
    per_lease = {}
    for a in allocs:
        per_lease[a.payload["lease"]] = per_lease.get(a.payload["lease"], 0) + 1
    out["I2_sum_a"] = sum(a.payload["a"] for a in allocs)
    out["I2_ok"] = out["I2_sum_a"] <= RP.eps + 1e-12 and max(per_lease.values(), default=0) <= RP.lease_size
    out["I3_open_slots"] = sum(1 for i in acc if i[0] == "SlotLease" and ("Result", i[1]) not in acc
                               and status.get(("Result", i[1])) != QUARANTINED)
    mism = 0
    for i, n in acc.items():
        if i[0] == "Confirmation" and inscope(i):
            d = derive_confirmation(i, acc, RP)
            mism += d is None or d.encode() != n.encode()
    out["I4_conf_mismatch"] = mism
    under = 0
    for i, n in filter(lambda kv: inscope(kv[0]), acc.items()):
        under += any(fab.stores[d].blobs.get(i) != n.encode() for d in fab.placement(n))
    out["I5_underreplicated"] = under
    rep = report(acc)
    out["b_hat"], out["confirmed"] = rep["b_hat"], len(rep["confirmed"])
    out["crash_results"] = sum(1 for i, n in acc.items() if i[0] == "Result" and n.payload.get("crashed"))
    return out, acc


def passes(inv, tc):
    ok = inv.get("I1_conflicts", 0) == 0 and inv["I2_ok"] and inv["I3_open_slots"] == 0 \
        and inv["I4_conf_mismatch"] == 0 and inv["I5_underreplicated"] == 0
    return bool(ok)


def compare(acc, golden):
    gconf = {i for i, n in golden.items() if i[0] == "Confirmation" and n.payload["confirmed"]}
    conf = {i for i, n in acc.items() if i[0] == "Confirmation" and n.payload["confirmed"]}
    wrong = sum(1 for i, n in acc.items() if i[0] != "Confirmation" and (i not in golden or golden[i].payload != n.payload))
    links = sum(1 for i, n in acc.items() if i[0] != "Confirmation" and i in golden
                and golden[i].payload == n.payload and golden[i].encode() != n.encode())
    correct = sum(1 for i, n in acc.items() if i in golden and golden[i].encode() == n.encode())
    return {"golden": len(golden), "recovered": correct, "recovery": correct / len(golden), "wrong_nonconf": wrong,
            "content_right_links_differ": links,
            "added_conf": len(conf - gconf), "lost_conf": len(gconf - conf)}


# ------------------------------------------------------------------ test cases
def run_load(cl, n=6, budget=120, fault=None, fault_at=2.0, seed0=0):
    names = cl.start_workers(n, budget, seed0)
    t0 = time.time()
    if fault:
        time.sleep(fault_at)
        fault(names)
    ws = cl.wait_workers(names)
    wall = time.time() - t0
    q = cl.quiesce()
    return {"workers": ws, "wall_s": round(wall, 1), "quiesce_s": None if q is None else round(q, 1),
            "calls": sum(w.get("calls", 0) for w in ws)}


def tc_load(cl, name, fault=None, setup=None, budget=120, n=6):
    cl.up()
    if setup:
        setup(cl)
    load = run_load(cl, n=n, budget=budget, fault=fault)
    scan = cl.scan()
    inv, _ = invariants(cl.snapshot())
    inv["k_star_found"] = inv["b_hat"] == K_STAR
    ok = passes(inv, name) and set(scan["status"]) <= {"VERIFIED"} | ({"REPAIRED"} if fault else set())
    if name.startswith("TC1 "):
        ok = ok and inv["k_star_found"]
    return {"tc": name, "load": load, "scan_status": scan["status"], "inv": inv, "pass": ok}


def f_kill_recorder(names):
    sh("docker", "kill", "q-recorder")
    time.sleep(10)
    CL.start_coordinator("recorder")


def f_pause_arbiter(names):
    sh("docker", "pause", "q-arbiter")
    time.sleep(15)
    sh("docker", "unpause", "q-arbiter")


def f_partition_treasurer(names):
    sh("docker", "network", "disconnect", NET, "q-treasurer")
    time.sleep(15)
    sh("docker", "network", "connect", NET, "q-treasurer")


def f_kill_workers(names):
    sh("docker", "kill", names[0], names[1])


def latency(cl):
    for r in DOMAINS:
        cl.add_toxic(r, "lat", "latency", {"latency": 150, "jitter": 100})


def flaky(cl):
    for r in ("recorder", "registrar"):
        cl.add_toxic(r, "to", "timeout", {"timeout": 500}, toxicity=0.15)
        cl.add_toxic(r, "rst", "reset_peer", {"timeout": 50}, toxicity=0.15, stream="upstream")


def tc_storage(cl, rows):
    """TC8-TC10 and TC12 from one golden run."""
    cl.up()
    load = run_load(cl, budget=120)
    cl.scan()
    golden_inv, golden = invariants(cl.snapshot())
    rows.append({"tc": "TC8-golden", "load": load, "inv": golden_inv, "pass": passes(golden_inv, "golden")})
    cl.stop_coordinators()
    gold_dir = cl.work / "golden"
    if gold_dir.exists():
        shutil.rmtree(gold_dir)
    shutil.copytree(cl.data, gold_dir)

    def restore():
        cl.stop_coordinators()
        shutil.rmtree(cl.data)
        shutil.copytree(gold_dir, cl.data)

    for rho in (0.05, 0.2, 0.4):
        restore()
        rng = np.random.default_rng(int(rho * 1000))
        stats = {r: corrupt_file(cl.data / r / f"{r}.jsonl", rho, rng) for r in DOMAINS}
        cl.start_coordinators()
        t0 = time.time()
        scan1 = cl.scan()
        scan_s = time.time() - t0
        cl.quiesce(limit=60)
        _, acc = invariants(cl.snapshot(), check_write_once=False)
        cmp = compare(acc, golden)
        scan2 = cl.scan()
        ok = cmp["wrong_nonconf"] == 0 and cmp["added_conf"] == 0 and "REPAIRED" not in scan2["status"] \
            and (rho > 0.05 or cmp["recovery"] >= 0.99)
        rows.append({"tc": f"TC8 rho={rho}", "corruption": stats, "scan1": scan1["status"], "scan_s": round(scan_s, 2),
                     "healed_copies": scan1["healed_copies"], "scan2": scan2["status"], "vs_golden": cmp, "pass": ok})
        if rho == 0.2:
            pre = cl.snapshot()
            resume = run_load(cl, budget=40, seed0=100)
            after = cl.snapshot()
            # records written or changed after the repair (a reused id shows up as changed bytes)
            new = {i for d, st in after.stores.items() for i, b in st.blobs.items()
                   if pre.stores[d].blobs.get(i) != b}
            inv, _ = invariants(after, scope=new)
            inv["new_records"] = len(new)
            errors = sum(w.get("codes", {}).get("500", 0) for w in resume["workers"])
            rows.append({"tc": "TC12 resume after storage repair", "load": resume, "inv": inv,
                         "worker_server_errors": errors,
                         "pass": passes(inv, "TC12") and errors == 0 and len(new) > 0})

    for lost in (("registrar", "archivist"), ("recorder", "arbiter")):
        restore()
        for r in lost:
            shutil.rmtree(cl.data / r)
            (cl.data / r).mkdir()
        cl.start_coordinators()
        scan1 = cl.scan()
        cl.quiesce(limit=60)
        _, acc = invariants(cl.snapshot(), check_write_once=False)
        cmp = compare(acc, golden)
        rows.append({"tc": f"TC9 lose {'+'.join(lost)}", "scan1": scan1["status"], "vs_golden": cmp,
                     "pass": cmp["wrong_nonconf"] == 0 and cmp["added_conf"] == 0})

    # TC10: an adversary controlling k of the five domains rewrites Results (0 -> 1) and
    # Confirmations (unconfirmed -> confirmed) consistently everywhere it can, up to k = 5.
    # Since the loophole fix (TWGR-S) the criterion is: no added confirmation and no
    # non-conservative wrong record for every k, including a majority and all five.
    rng = np.random.default_rng(7)
    gconf = {i[1] for i, n in golden.items() if i[0] == "Confirmation" and n.payload["confirmed"]}
    res0 = sorted(i for i, n in golden.items() if i[0] == "Result" and n.payload.get("y") == 0)
    conf0 = sorted(i for i, n in golden.items() if i[0] == "Confirmation" and not n.payload["confirmed"])
    for k in range(1, 6):
        restore()
        fab = Fabric()
        for r in DOMAINS:
            fab.stores[r] = DomainStore.load(r, cl.data / r / f"{r}.jsonl")
        targets = [res0[int(t)] for t in rng.choice(len(res0), size=6, replace=False)]
        targets += [conf0[int(t)] for t in rng.choice(len(conf0), size=min(4, len(conf0)), replace=False)]
        majority = 0
        for nid in targets:
            B = [str(d) for d in rng.choice(DOMAINS, size=k, replace=False)]
            A = anchor_domains(fab, nid)
            majority += 2 * len(set(B) & A) > len(A)
            control(fab, nid, tamper_node(golden[nid]), B)
        for r in DOMAINS:
            fab.stores[r].save(cl.data / r / f"{r}.jsonl")
        cl.start_coordinators()
        cl.scan()
        _, acc = invariants(cl.snapshot(), check_write_once=False)
        # wrong = accepted content (signed or derived payload) differs from the original; a record whose
        # content is right but whose evidence links omit a destroyed record is counted separately
        wrong = sum(1 for t in targets if t in acc and acc[t].payload != golden[t].payload)
        corr = sum(1 for t in targets if t in acc and acc[t].encode() == golden[t].encode())
        links = sum(1 for t in targets if t in acc and acc[t].payload == golden[t].payload
                    and acc[t].encode() != golden[t].encode())
        added = {i[1] for i, n in acc.items() if i[0] == "Confirmation" and n.payload["confirmed"]} - gconf
        rows.append({"tc": f"TC10 adversary k={k}", "targets": len(targets), "majority_targets": majority,
                     "wrong": wrong, "correct": corr, "content_right_links_missing": links, "added_conf": len(added),
                     "quarantined": len(targets) - wrong - corr - links, "pass": wrong == 0 and not added})
    cl.stop_coordinators()


def tc_validity(cl, rows, reps=5):
    cl.scenario = "boundary-null"
    for rep in range(reps):
        cl.up()
        load = run_load(cl, budget=150, seed0=1000 * (rep + 1))
        inv, _ = invariants(cl.snapshot())
        rows.append({"tc": f"TC11 boundary-null run {rep + 1}", "load": load, "inv": inv,
                     "false_confirmations": inv["confirmed"], "pass": passes(inv, "TC11")})
    cl.scenario = "S1-dense"


CL = None


def main():
    global CL, TOXI_BIN
    work = pathlib.Path(sys.argv[1])
    only = set(sys.argv[2:])
    TOXI_BIN = __import__("os").environ["TOXIPROXY_BIN"]
    CL = Cluster(work)
    rows = []
    out = ROOT / "results" / "raw" / "e12_sqa.jsonl"
    plan = [("TC1 baseline", {}), ("TC2 latency", {"setup": latency, "budget": 60}),
            ("TC3 timeouts+resets", {"setup": flaky}), ("TC4 kill recorder", {"fault": f_kill_recorder}),
            ("TC5 pause arbiter", {"fault": f_pause_arbiter}),
            ("TC6 partition treasurer", {"fault": f_partition_treasurer}),
            ("TC7 kill 2 workers", {"fault": f_kill_workers, "budget": 300})]
    try:
        for name, kw in plan:
            if only and name.split()[0] not in only:
                continue
            t0 = time.time()
            r = tc_load(CL, name, **kw)
            r["tc_wall_s"] = round(time.time() - t0, 1)
            rows.append(r)
            print(json.dumps(r), flush=True)
        if not only or {"TC8", "TC9", "TC10", "TC12"} & only:
            n0 = len(rows)
            tc_storage(CL, rows)
            for r in rows[n0:]:
                print(json.dumps(r), flush=True)
        if not only or "TC11" in only:
            n0 = len(rows)
            tc_validity(CL, rows)
            for r in rows[n0:]:
                print(json.dumps(r), flush=True)
    finally:
        CL.down()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a" if only else "w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")


if __name__ == "__main__":
    main()
