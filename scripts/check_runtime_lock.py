#!/usr/bin/env python3
from pathlib import Path
import re, tomllib

root=Path(__file__).resolve().parents[1]
project=tomllib.loads((root/"pyproject.toml").read_text())["project"]
lock={}
for line in (root/"requirements.lock.txt").read_text().splitlines():
    line=line.strip()
    if not line or line.startswith("#"): continue
    name,version=line.split("==",1)
    lock[name.lower().replace("_","-")]=version

missing=[]
for raw in project["dependencies"]:
    name=re.split(r"[<>=!~;\[]",raw,maxsplit=1)[0].strip().lower().replace("_","-")
    if name not in lock:
        missing.append(name)
if missing:
    raise SystemExit("runtime_lock_missing_direct_dependencies:"+",".join(missing))
print(f"RUNTIME_LOCK_PASS entries={len(lock)}")
