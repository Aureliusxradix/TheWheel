"""Load reader output (JSON lines) into the hub store as unreviewed events.

    python3 hub/import_jsonl.py runs/x.jsonl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub import store  # noqa: E402

db = store.connect()
n = 0
for line in open(sys.argv[1]):
    if line.strip():
        rec = json.loads(line)
        if store.get(db, rec["id"]) is None:  # never overwrite a reviewed copy
            store.put(db, rec, "pending")
            n += 1
print(f"{n} events added as unreviewed")
