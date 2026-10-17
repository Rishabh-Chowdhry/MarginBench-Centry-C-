"""FRESCO protocol messages (schema version 1).

Every request carries (src, req_id). The ledger caches the response per
(src, req_id), so retransmissions and network duplicates are idempotent at the
request level; slot results are additionally fenced by their lease token
(write-once, R3). Messages are plain JSON on the wire.
"""

import json
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1

# kind -> {field: type}; the body of each request/response kind
SCHEMAS = {
    # worker -> ledger requests (op name == kind)
    "grant": {"amount": float},
    "close_lease": {"lease_id": int},
    "register": {"lease_id": int, "content": int, "level": int},
    "abandon": {"j": int},
    "lease_slots": {"j": int, "count": int},
    "record": {"j": int, "k": int, "y": int, "token": str, "trace_hash": str},
    "lease_audit": {"level": int},
    "record_audit": {"level": int, "i": int, "z": int, "token": str},
    # ledger -> worker
    "response": {"of": str, "result": dict},
    "frontier": {"b_hat": int, "witness": int, "seq": int},
    "status": {"j": int, "status": str, "seq": int},
}

REQUEST_KINDS = {"grant", "close_lease", "register", "abandon", "lease_slots", "record",
                 "lease_audit", "record_audit"}


@dataclass
class Message:
    kind: str
    src: str
    dst: str
    req_id: int
    body: dict = field(default_factory=dict)
    v: int = SCHEMA_VERSION

    def validate(self):
        if self.v != SCHEMA_VERSION:
            raise ValueError(f"schema version {self.v} unsupported")
        spec = SCHEMAS.get(self.kind)
        if spec is None:
            raise ValueError(f"unknown kind {self.kind}")
        for name, typ in spec.items():
            if name not in self.body:
                raise ValueError(f"{self.kind}: missing {name}")
            val = self.body[name]
            if typ is float and isinstance(val, int):
                continue
            if not isinstance(val, typ):
                raise ValueError(f"{self.kind}.{name}: expected {typ.__name__}")
        return self

    def to_json(self):
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, s):
        return cls(**json.loads(s)).validate()
