#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--root", default=".")
args = parser.parse_args()
root = Path(args.root).resolve()

env_path = root / ".env.example"
if not env_path.is_file():
    print("RELEASE_CONTRACT=FAIL")
    print("MISSING_REQUIRED_FILES=.env.example")
    raise SystemExit(2)

def is_secret_key(key: str) -> bool:
    k = key.upper()
    exact = {
        "PASSWORD", "SECRET", "TOKEN", "PRIVATE_KEY", "API_KEY",
        "ACCESS_KEY_ID", "SECRET_ACCESS_KEY",
    }
    if k in exact:
        return True
    suffixes = (
        "_SECRET", "_TOKEN", "_PASSWORD", "_PRIVATE_KEY", "_API_KEY",
        "_ACCESS_KEY_ID", "_SECRET_ACCESS_KEY",
    )
    return k.endswith(suffixes)

safe_markers = ("change-me", "changeme", "placeholder", "example", "dummy", "test")
findings = []

for idx, line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
    raw = line.strip()
    if not raw or raw.startswith("#") or "=" not in raw:
        continue
    key, value = raw.split("=", 1)
    value = value.strip().strip('"').strip("'")
    if is_secret_key(key.strip()):
        if value and not any(marker in value.lower() for marker in safe_markers):
            findings.append((idx, key.strip()))

if findings:
    print("RELEASE_CONTRACT=FAIL")
    print("SECRET_BEARING_ENV_VALUES=" + ",".join(f"{line}:{key}" for line, key in findings))
    raise SystemExit(3)

print("RELEASE_CONTRACT=PASS")
