"""Origin signatures for evidence records (TWGR-S).

Every piece of evidence that statistics consume originates at an executor device
(worker): its registration request (Candidate) and its slot outcomes (Result). The
device signs them with its own Ed25519 key. The public keys are listed in a run
manifest that the evaluator publishes before the run, outside every coordinator
domain (like the run-key commitment of rule R1). A coordinator, or all five together,
can store, order, delete or withhold such records, but cannot forge or alter one.

The only evidence that may exist without a device signature is a crash result
(Y = 0), written when a slot expires. It can only make confirmation harder, and TWGR-S
treats its true value as unknown when re-deriving a confirmation.

Experiments derive device keys deterministically from a campaign seed for
reproducibility; a production deployment generates them on the device.
"""

import hashlib
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from fresco.hkg.graph import canon, sha

REQ_FIELDS = ("lease", "level", "content", "worker", "nonce", "i")   # i: the device's index within its own lease
CANDIDATE_KEYS = frozenset(REQ_FIELDS + ("sig",))
RESULT_KEYS = (frozenset(("y", "worker", "sig")), frozenset(("crashed", "worker", "sig")))


def device_key(secret):
    """Ed25519 key from a device secret (bytes or str)."""
    s = secret.encode() if isinstance(secret, str) else secret
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"quintet-device|" + s).digest())


def pub_hex(sk):
    return sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def sign(sk, msg):
    return sk.sign(canon(msg)).hex()


@lru_cache(maxsize=1 << 18)
def _verify(pub, sig, msg_bytes):
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(bytes.fromhex(sig), msg_bytes)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


_HEX = frozenset("0123456789abcdef")


def verify(pub, sig, msg):
    """Strict encoding (lower-case hex of the exact length) so one signature has exactly
    one stored form: a re-encoded copy is not a second admissible value."""
    if not (isinstance(pub, str) and isinstance(sig, str) and len(pub) == 64 and len(sig) == 128
            and set(pub) <= _HEX and set(sig) <= _HEX):
        return False
    return _verify(pub, sig, canon(msg))


def make_manifest(run_id, devices):
    """devices: {name: secret}. Returns the published manifest {run_id, devices: {name: pubkey}}."""
    return {"run_id": run_id, "devices": {w: pub_hex(device_key(s)) for w, s in devices.items()}}


def request_msg(run_id, req):
    return ["Candidate-request", run_id] + [req.get(f) for f in REQ_FIELDS]


def request_hash(payload):
    return sha(canon([payload.get(f) for f in REQ_FIELDS]))


def result_msg(run_id, j, k, outcome, req_hash, key):
    """outcome: 0/1, or "crashed" when the device itself reports an executor crash."""
    return ["Result", run_id, str(j), int(k), outcome, req_hash, int(key)]


def sign_request(sk, run_id, req):
    return sign(sk, request_msg(run_id, req))


def sign_result(sk, run_id, j, k, outcome, req_hash, key):
    return sign(sk, result_msg(run_id, j, k, outcome, req_hash, key))
