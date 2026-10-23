"""Rep v1 for The Wheel: tiers, review weight, and the certainty a listing shows.

Rules from a study of community reputation systems (2026-10-20), under two rulings: rep is earned, never bought;
a ban resets rank. PROVISIONAL: four questions are still open (show-ups toward tiers, steward sleep, mistakes vs
cheating, paid promotion).

- Rep comes only from outcomes others confirm: a deposit that passes review, a review that agrees with how the
  listing settled, and (2026-10-24, Day's "thanks that count") a shift the organiser holding the listing thanked you
  for. Weekly caps. Thanks count toward Regular and never toward Reviewer, so no organiser can raise review weight. Show-ups are not counted here: by design a show-up cannot be tied to a pen name.
- A review's weight is fixed when it is cast (the reviewer's tier then), so a listing's certainty never
  depends on rep earned afterwards.
- Certainty that a listing is right: 1 - (1 - w1)(1 - w2)... over the approving reviews; the same for rejecting.
  A listing settles at SETTLE either way.
- New members' reviews together count up to NEW_CAP, below SETTLE, so settling needs at least one Regular or above
  (his "Do A-F", 2026-10-22: six fresh accounts held by one person could settle a listing and farm rep).
"""

from datetime import date, timedelta

WEIGHT = {0: 0.2, 1: 0.4, 2: 0.7, 3: 0.9}
TIER_NAME = {0: "New", 1: "Regular", 2: "Reviewer", 3: "Steward"}
SETTLE = 0.7
NEW_CAP = 0.5  # all New reviews on one side together; below SETTLE on purpose
# Reports (2026-10-22, the Roadmap's "Report a listing"; PROVISIONAL, his to set): a checked listing goes back to review
# once its open reports, weighted like reviews, reach REOPEN: one Regular, or three New members together.
REOPEN = 0.4
DEPOSIT_POINTS, DEPOSIT_PENALTY, DEPOSIT_WEEK_CAP = 2, -2, 5
REVIEW_POINTS, REVIEW_PENALTY, REVIEW_WEEK_CAP = 1, -1, 5
DAILY_DEPOSITS = {0: 3, 1: 10, 2: 10, 3: 50}  # the study's day one: 3 a day for a new member


def certainty(weights_for: list[float], weights_against: list[float]) -> tuple[float, float]:
    def combine(ws):
        miss = 1.0
        for w in ws:
            miss *= (1 - w)
        return 1 - miss

    def side(ws):
        new = min(combine([w for w in ws if w <= WEIGHT[0]]), NEW_CAP)  # a review's weight is its tier's when cast
        return combine([new] + [w for w in ws if w > WEIGHT[0]])
    return round(side(weights_for), 3), round(side(weights_against), 3)


def settled_state(cert_for: float, cert_against: float) -> str:
    if cert_for >= SETTLE and cert_for > cert_against:
        return "approved"
    if cert_against >= SETTLE and cert_against > cert_for:
        return "rejected"
    return "pending"


def _week(day: str) -> str:
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-{w}"


THANKS_POINTS, THANKS_WEEK_CAP = 2, 3


def points(db, account: str, thanks: bool = True) -> int:
    """Rep from confirmed outcomes, capped per week. thanks=False leaves out thanked shifts (the Reviewer part)."""
    total = 0
    by_week: dict[tuple[str, str], int] = {}

    def add(kind: str, day: str, n: int, cap: int):
        nonlocal total
        key = (kind, _week(day))
        if n > 0:
            if by_week.get(key, 0) >= cap:
                return
            by_week[key] = by_week.get(key, 0) + 1
        total += n

    acc = db.execute("SELECT reset_day FROM accounts WHERE account=?", (account,)).fetchone()
    since = (acc["reset_day"] if acc and acc["reset_day"] else "0000-00-00")  # a ban resets rank; history stays
    for row in db.execute("SELECT state, deposit_day FROM events WHERE deposited_account=? AND deposit_day > ?", (account, since)):
        if row["state"] == "approved":
            add("deposit", row["deposit_day"], DEPOSIT_POINTS, DEPOSIT_WEEK_CAP)
        elif row["state"] == "rejected":
            add("deposit", row["deposit_day"], DEPOSIT_PENALTY, DEPOSIT_WEEK_CAP)
    for row in db.execute(
            "SELECT r.verdict, r.day, e.state FROM reviews r JOIN events e ON e.id = r.listing_id WHERE r.account=? AND r.day > ?",
            (account, since)):
        if row["state"] not in ("approved", "rejected"):
            continue  # unsettled: no rep either way yet
        agreed = (row["verdict"] == "approve") == (row["state"] == "approved")
        add("review", row["day"], REVIEW_POINTS if agreed else REVIEW_PENALTY, REVIEW_WEEK_CAP)
    if thanks:
        for row in db.execute("SELECT thanked_day FROM shift_claims WHERE account=? AND thanked=1 AND thanked_day > ?", (account, since)):
            add("thanks", row["thanked_day"], THANKS_POINTS, THANKS_WEEK_CAP)
    return total


def tier(db, account: str) -> int:
    row = db.execute("SELECT first_day, steward, reset_day, granted_tier FROM accounts WHERE account=?", (account,)).fetchone()
    if row is None:
        return 0
    if row["steward"]:
        return 3
    p = points(db, account)
    age = (date.today() - date.fromisoformat(row["first_day"])).days
    review_part = points(db, account, thanks=False)  # listings and reviews only: thanks never raise review weight
    earned = 2 if p >= 30 and review_part >= 20 else 1 if p >= 10 and age >= 14 else 0
    return max(earned, row["granted_tier"] or 0)  # a tier given by hand (his ask 2026-10-21) is a floor; a ban clears it


def active(db) -> int:
    """Members in good standing (Regular and up): the people a check-in can count on hiding among. Every joined key
    counts in the members list; a spare account adds a name there and a person here only once others confirm its work."""
    return sum(1 for r in db.execute("SELECT account FROM accounts") if tier(db, r["account"]) >= 1)


def summary(db, account: str) -> dict:
    t = tier(db, account)
    p = points(db, account)
    today = date.today().isoformat()
    used = db.execute("SELECT n FROM deposit_counts WHERE account=? AND day=?", (account, today)).fetchone()
    nxt = {0: "Regular at 10 points and 14 days", 1: "Reviewer at 30 points", 2: "Steward: named by two stewards", 3: None}[t]
    return {"account": account, "tier": t, "tier_name": TIER_NAME[t], "points": p, "next": nxt,
            "deposits_today": used["n"] if used else 0, "deposit_limit": DAILY_DEPOSITS[t]}
