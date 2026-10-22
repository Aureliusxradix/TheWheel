"""The Wheel's steward tool, run on the box that holds the store.

    python3 hub/wheelctl.py steward add <pen-name>     make an account a steward
    python3 hub/wheelctl.py steward list
    python3 hub/wheelctl.py tier <pen-name> reviewer   give a tier by hand (regular, reviewer; none takes it back)
    python3 hub/wheelctl.py reset <pen-name>           a ban: rank back to zero (history stays)
    python3 hub/wheelctl.py held                       listings the identity gate keeps out of every answer, and why
    python3 hub/wheelctl.py reject <listing-id>        take a listing out for good (a held one, say)
    python3 hub/wheelctl.py flyer <listing-id> <image> show this flyer on the listing (cleaned first; look at it first:
                                                       its words go out with it, and only a person checks them here)
    python3 hub/wheelctl.py codes <months> <n> [note]  make supporter codes (months 1, 6 or 12; note: cash, paypal,
                                                       gift...), printed once: the store keeps only their fingerprints
    python3 hub/wheelctl.py codes count                codes made and used, by months and note
    python3 hub/wheelctl.py supporters                 how many accounts hold supporter months today
    python3 hub/wheelctl.py fund add <nzd> [how]       a gift toward The Wheel's own AI (how: cash, monero, paypal...)
    python3 hub/wheelctl.py fund                       the fund's total and count

Steward actions here go in the public moderation log by role, never by pen name (2026-10-22).

A pen name is shown on the Me page. He is the steward until two stewards exist (rep study).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub import flyer, gate, rep, store, support  # noqa: E402
from hub.server import FLYERS, public  # noqa: E402

db = store.connect()
a = sys.argv[1:]
if a[:2] == ["steward", "add"] and len(a) == 3:
    store.ensure_account(db, a[2])
    db.execute("UPDATE accounts SET steward=1 WHERE account=?", (a[2],)); db.commit()
    store.log(db, "steward_named")  # every steward action goes in the public log, by role only (2026-10-22)
    print(f"{a[2]} is a steward")
elif a[:2] == ["steward", "list"]:
    print("\n".join(r["account"] for r in db.execute("SELECT account FROM accounts WHERE steward=1")) or "no stewards yet")
elif a[:1] == ["reset"] and len(a) == 2:
    # rank back to zero; their past reviews stay, so other listings' certainty does not shift
    db.execute("UPDATE accounts SET steward=0, granted_tier=NULL, reset_day=date('now','localtime') WHERE account=?", (a[1],)); db.commit()
    store.log(db, "rank_reset")
    print(f"{a[1]}: rank reset to zero")
elif a[:1] == ["tier"] and len(a) == 3 and a[2] in ("none", "regular", "reviewer"):
    # a floor under the earned tier; Steward stays its own step (steward add)
    if db.execute("SELECT 1 FROM accounts WHERE account=?", (a[1],)).fetchone() is None:
        sys.exit(f"no account {a[1]}")
    db.execute("UPDATE accounts SET granted_tier=? WHERE account=?", ({"none": None, "regular": 1, "reviewer": 2}[a[2]], a[1])); db.commit()
    store.log(db, "tier_given", tier={"none": "back to earned", "regular": "Regular", "reviewer": "Reviewer"}[a[2]])
    print(f"{a[1]}: {a[2]} given by hand, tier now {rep.TIER_NAME[rep.tier(db, a[1])]}")
elif a[:1] == ["codes"] and len(a) in (3, 4) and a[1].isdigit() and a[2].isdigit():
    for c in support.make_codes(db, int(a[1]), int(a[2]), a[3] if len(a) == 4 else ""):
        print(c)
elif a == ["codes", "count"]:
    for r in db.execute("SELECT months, COALESCE(note,'') note, COUNT(*) made, COUNT(used_day) used FROM codes GROUP BY 1, 2"):
        print(f"{r['months']:>2} months  {r['note'] or '-':<8} made {r['made']:>4}  used {r['used']:>4}")
elif a[:2] == ["fund", "add"] and len(a) in (3, 4):
    # a gift toward The Wheel's own AI; the page shows only the total and the count
    from datetime import date
    store.fund_add(db, float(a[2]), a[3] if len(a) == 4 else None, date.today().isoformat())
    t = store.fund_total(db)
    print(f"added NZ${float(a[2]):.2f}; the fund stands at NZ${t['raised']:.2f} from {t['gifts']} gifts")
elif a == ["fund"]:
    t = store.fund_total(db)
    print(f"NZ${t['raised']:.2f} from {t['gifts']} gifts, last {t['updated'] or 'never'}")
elif a == ["supporters"]:
    print(f"{support.count(db)} accounts hold supporter months today")
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
    store.log(db, "flyer", a[1])
    print(f"{a[1]}: flyer {name} attached ({(FLYERS / name).stat().st_size} bytes, cleaned)")
elif a[:1] == ["reject"] and len(a) == 2:
    r = store.get(db, a[1])
    if r is None:
        sys.exit(f"no listing {a[1]}")
    r["review"] = {"state": "rejected", "by": "steward", "at": store.now()}
    store.put(db, r, "rejected")
    store.log(db, "taken_out", a[1])
    print(f"{a[1]} rejected")
else:
    print(__doc__)
