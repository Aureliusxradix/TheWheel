"""Give stored listings that lack them their modes (day / night / recovery), in one AI pass.

    python3 hub/assign_modes.py [--model ID]

Uses the reader's own mode rules (prompts/extract-v2.md) on each listing's name, times
and the organiser's words. Marks each touched record `extraction.modes_by = "batch-v2"`;
a reviewer can change any of them.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from hub import store  # noqa: E402

RULES = [l for l in (ROOT / "prompts" / "extract-v3.md").read_text().splitlines() if l.startswith("- `modes`")][0]
SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "modes": {"type": "array", "items": {"type": "string", "enum": ["day", "night", "recovery"]}}},
    "required": ["id", "modes"], "additionalProperties": False}}}, "required": ["items"], "additionalProperties": False}

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="claude-opus-5-5")
a = ap.parse_args()
db = store.connect()
todo = [r for r in store.events(db, ("pending", "approved")) if not r.get("modes") or r.get("extraction", {}).get("modes_guessed")]
if not todo:
    print("nothing to do")
    sys.exit(0)
lines = [json.dumps({"id": r["id"], "name": r["name"], "start": f"{r['start_date']} {r.get('start_time') or ''}",
                     "end": f"{r.get('end_date') or ''} {r.get('end_time') or ''}", "repeats": r.get("recurrence"),
                     "words": (r.get("description") or r.get("summary") or "")[:400]}, ensure_ascii=False) for r in todo]
system = "Give each listing its modes by this rule, and return every id once.\n" + RULES
cmd = ["claude", "-p", "--model", a.model, "--no-session-persistence", "--tools", "", "--strict-mcp-config",
       "--setting-sources", "", "--system-prompt", system, "--output-format", "json", "--json-schema", json.dumps(SCHEMA)]
run = subprocess.run(cmd, input="\n".join(lines), capture_output=True, text=True, timeout=600)
out = json.loads(run.stdout)
got = {i["id"]: i["modes"] for i in out["structured_output"]["items"]}
n = 0
for r in todo:
    if got.get(r["id"]):
        r["modes"] = got[r["id"]]
        r.setdefault("extraction", {})["modes_by"] = "batch-v2"
        r["extraction"].pop("modes_guessed", None)
        store.put(db, r, r["review"]["state"])
        n += 1
print(f"{n} of {len(todo)} listings given modes · cost ${out.get('total_cost_usd', 0):.4f}")
for r in todo:
    print(f"  {'/'.join(got.get(r['id'], ['?'])):22} {r['name'][:60]}")
