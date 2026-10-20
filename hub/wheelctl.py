"""The Wheel's steward tool, run on the box that holds the store.

    python3 hub/wheelctl.py steward add <pen-name>     make an account a steward
    python3 hub/wheelctl.py steward list
    python3 hub/wheelctl.py reset <pen-name>           a ban: rank back to zero (history stays)
    python3 hub/wheelctl.py held                       listings the identity gate keeps out of every answer, and why
    python3 hub/wheelctl.py reject <listing-id>        take a listing out for good (a held one, say)
    python3 hub/wheelctl.py flyer <listing-id> <image> show this flyer on the listing (cleaned first; look at it first:
                                                       its words go out with it, and only a person checks them here)

A pen name is shown on the Me page. He is the steward until two stewards exist (rep study).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub import flyer, gate, store  # noqa: E402
from hub.server import FLYERS, public  # noqa: E402

db = store.connect()
a = sys.argv[1:]
if a[:2] == ["steward", "add"] and len(a) == 3:
    store.ensure_account(db, a[2])
    db.execute("UPDATE accounts SET steward=1 WHERE account=?", (a[2],)); db.commit()
    print(f"{a[2]} is a steward")
elif a[:2] == ["steward", "list"]:
    print("\n".join(r["account"] for r in db.execute("SELECT account FROM accounts WHERE steward=1")) or "no stewards yet")
elif a[:1] == ["reset"] and len(a) == 2:
    # rank back to zero; their past reviews stay, so other listings' certainty does not shift
    db.execute("UPDATE accounts SET steward=0, reset_day=date('now','localtime') WHERE account=?", (a[1],)); db.commit()
    print(f"{a[1]}: rank reset to zero")
elif a == ["held"]:
    # a held listing is never deleted: it waits here for a steward, who rejects it (below) or lets it stay held
    rx, n = gate.load(), 0
    for r in store.events(db, ("approved", "pending")):
        h = gate.hit(rx, json.dumps(public(r), ensure_ascii=False))
        if h:
            n += 1
            print(f"{r['id']}  {r.get('start_date')}  {r.get('name', '')[:50]}  carries /{h}/")
    print(f"{n} held" if n else "nothing held")
elif a[:1] == ["flyer"] and len(a) == 3:
    r = store.get(db, a[1])
    if r is None:
        sys.exit(f"no listing {a[1]}")
    name = flyer.keep(FLYERS, flyer.clean(Path(a[2]).read_bytes()))
    r.setdefault("source", {})["flyer"] = name
    store.put(db, r, r["review"].get("state", "pending"))
    print(f"{a[1]}: flyer {name} attached ({(FLYERS / name).stat().st_size} bytes, cleaned)")
elif a[:1] == ["reject"] and len(a) == 2:
    r = store.get(db, a[1])
    if r is None:
        sys.exit(f"no listing {a[1]}")
    r["review"] = {"state": "rejected", "by": "steward", "at": store.now()}
    store.put(db, r, "rejected")
    print(f"{a[1]} rejected")
else:
    print(__doc__)
