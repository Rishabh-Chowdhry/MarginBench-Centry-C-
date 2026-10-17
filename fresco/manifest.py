"""Run manifests: everything needed to reproduce or audit a result row."""

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict, is_dataclass

import numpy as np


def canonical(obj):
    if is_dataclass(obj):
        obj = asdict(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def config_hash(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def git_revision():
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
        return rev + ("-dirty" if dirty.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def manifest(config, seed, extra=None):
    m = {
        "config_hash": config_hash(config),
        "config": json.loads(canonical(config)),
        "seed": seed,
        "code_revision": git_revision(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "platform": platform.platform(),
    }
    if extra:
        m.update(extra)
    return m
