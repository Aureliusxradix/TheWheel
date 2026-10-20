"""Score the reader against fixture cases.

    /usr/bin/python3 -E -s tests/score.py [tests/fixtures | tests/posts] [--model ID] [--jobs N] [--only PREFIX] [--repeat N]

--repeat reads each case N times, to see how steady the reader is on it.

Each case dir holds input.*, meta.json (received) and expected.json. Only the
fields named in expected.json are scored. Results land in tests/results/.
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXACT = ("start_date", "start_time", "end_time", "time_known", "status")
LOOSE = ("location_name", "location_locality", "price")


def words(s: str) -> set[str]:
    return set(re.findall(r"[a-zāēīōū0-9]+", (s or "").lower()))


def field_ok(f: str, want, got) -> bool:
    if f == "name":
        w = words(want)
        return bool(w) and len(w & words(got)) / len(w) >= 0.5
    if f == "recurrence":
        return bool(got) == bool(want)
    if f == "modes":
        return sorted(got or []) == sorted(want)
    if f == "slots":
        return len(got or []) == want
    if f == "requirements":
        return any(want.lower() in str(r).lower() for r in (got or []))
    if f == "listing_kind":
        return (got or "event") == want
    if f in EXACT:
        return (got if got not in ("",) else None) == want
    if f in LOOSE:
        a, b = (want or "").lower(), (got or "").lower()
        return bool(a) and bool(b) and (a in b or b in a)
    return got == want


def match(expected: list[dict], records: list[dict]) -> list[tuple[dict, dict | None]]:
    left = list(records)
    pairs = []
    for e in expected:
        same_day = [r for r in left if r.get("start_date") == e.get("start_date")] or left
        if "listing_kind" in e:  # an event and a volunteer call from one post: each paired with its own kind
            same_day = [r for r in same_day if (r.get("listing_kind") or "event") == e["listing_kind"]] or same_day
        best = max(same_day, key=lambda r: len(words(e.get("name")) & words(r.get("name"))), default=None)
        if best is not None:
            left.remove(best)
        pairs.append((e, best))
    return pairs


def run_case(case: Path, model: str) -> dict:
    from reader import llm
    from reader.core import read
    llm.DEFAULT_MODEL = model
    inp = next(case.glob("input.*"))
    meta = json.loads((case / "meta.json").read_text())
    expected = json.loads((case / "expected.json").read_text())
    raw = str(inp) if inp.suffix != ".txt" else inp.read_text()
    try:
        out = read(raw, datetime.fromisoformat(meta["received"]))
    except Exception as exc:  # a crash scores zero and says why
        return {"case": case.name, "error": repr(exc)[:300], "passed": 0, "total": 1 + sum(len(e) for e in expected)}
    recs = out["records"]
    fails, passed, total = [], 0, 1
    if len(recs) == len(expected):
        passed += 1
    else:
        fails.append(f"count: want {len(expected)}, got {len(recs)}")
    for e, r in match(expected, recs):
        for f, want in e.items():
            total += 1
            got = (r or {}).get(f)
            if r is not None and field_ok(f, want, got):
                passed += 1
            else:
                fails.append(f"{e.get('start_date')} {f}: want {want!r}, got {got!r}")
    cost = out.get("cost_usd") or 0
    method = recs[0]["extraction"]["method"] if recs else "-"
    return {"case": case.name, "method": method, "passed": passed, "total": total, "fails": fails,
            "notes": out["notes"], "problems": out["problems"], "cost_usd": cost, "records": recs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("set", nargs="?", default=str(ROOT / "tests" / "fixtures"))
    ap.add_argument("--model", default=os.environ.get("EVENTHUB_MODEL", "claude-opus-5-5"))
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--only", default="", help="only the cases whose name starts with this")
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    cases = sorted(p for p in Path(a.set).iterdir() if p.is_dir() and (p / "expected.json").exists() and p.name.startswith(a.only))
    cases = [c for c in cases for _ in range(a.repeat)]
    with ThreadPoolExecutor(a.jobs) as pool:
        results = list(pool.map(lambda c: run_case(c, a.model), cases))
    P = sum(r["passed"] for r in results)
    T = sum(r["total"] for r in results)
    cost = sum(r.get("cost_usd") or 0 for r in results)
    print(f"{'case':20} {'path':7} score")
    for r in results:
        print(f"{r['case']:20} {r.get('method', 'ERR'):7} {r['passed']}/{r['total']}")
        for line in r.get("fails", []) + ([r["error"]] if "error" in r else []):
            print(f"    ✗ {line}")
        for p in (r.get("problems") or {}).values():
            print(f"    ⚠ schema: {p}")
    print(f"\n{a.set.rstrip('/').rsplit('/', 1)[-1]} · {a.model} · {P}/{T} fields ({100 * P / T:.0f}%) · AI cost ${cost:.4f}")
    outdir = ROOT / "tests" / "results"
    outdir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (outdir / f"{stamp}-{Path(a.set).name}-{a.model}.json").write_text(
        json.dumps({"model": a.model, "passed": P, "total": T, "cost_usd": cost, "results": results}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
