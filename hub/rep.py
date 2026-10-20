"""Rep v1 for The Wheel: tiers, review weight, and the certainty a listing shows.

Rules from a study of community reputation systems (2026-10-20), under two rulings: rep is earned, never bought;
a ban resets rank. PROVISIONAL: four questions are still open (show-ups toward tiers, steward sleep, mistakes vs
cheating, paid promotion).

- Rep comes only from outcomes others confirm: a deposit that passes review, a review that agrees with how the
  listing settled. Weekly caps. Show-ups are not counted here: by design a show-up cannot be tied to a pen name.
- A review's weight is fixed when it is cast (the reviewer's tier then), so a listing's certainty never
  depends on rep earned afterwards.
- Certainty that a listing is right: 1 - (1 - w1)(1 - w2)... over the approving reviews; the same for rejecting.
  A listing settles at SETTLE either way.
"""

from datetime import date, timedelta

WEIGHT = {0: 0.2, 1: 0.4, 2: 0.7, 3: 0.9}
TIER_NAME = {0: "New", 1: "Regular", 2: "Reviewer", 3: "Steward"}
SETTLE = 0.7
DEPOSIT_POINTS, DEPOSIT_PENALTY, DEPOSIT_WEEK_CAP = 2, -2, 5
REVIEW_POINTS, REVIEW_PENALTY, REVIEW_WEEK_CAP = 1, -1, 5
DAILY_DEPOSITS = {0: 3, 1: 10, 2: 10, 3: 50}  # the study's day one: 3 a day for a new member


def certainty(weights_for: list[float], weights_against: list[float]) -> tuple[float, float]:
    def combine(ws):
        miss = 1.0
        for w in ws:
            miss *= (1 - w)
        return 1 - miss
    return round(combine(weights_for), 3), round(combine(weights_against), 3)


def settled_state(cert_for: float, cert_against: float) -> str:
    if cert_for >= SETTLE and cert_for > cert_against:
        return "approved"
    if cert_against >= SETTLE and cert_against > cert_for:
        return "rejected"
    return "pending"


def _week(day: str) -> str:
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-{w}"


def points(db, account: str) -> int:
    """Rep from confirmed outcomes, capped per week."""
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
    return total


def tier(db, account: str) -> int:
    row = db.execute("SELECT first_day, steward, reset_day FROM accounts WHERE account=?", (account,)).fetchone()
    if row is None:
        return 0
    if row["steward"]:
        return 3
    p = points(db, account)
    age = (date.today() - date.fromisoformat(row["first_day"])).days
    review_part = p  # v1: listings and reviews are the only sources, so all of p counts toward Reviewer
    if p >= 30 and review_part >= 20:
        return 2
    if p >= 10 and age >= 14:
        return 1
    return 0


def summary(db, account: str) -> dict:
    t = tier(db, account)
    p = points(db, account)
    today = date.today().isoformat()
    used = db.execute("SELECT n FROM deposit_counts WHERE account=? AND day=?", (account, today)).fetchone()
    nxt = {0: "Regular at 10 points and 14 days", 1: "Reviewer at 30 points", 2: "Steward: named by two stewards", 3: None}[t]
    return {"account": account, "tier": t, "tier_name": TIER_NAME[t], "points": p, "next": nxt,
            "deposits_today": used["n"] if used else 0, "deposit_limit": DAILY_DEPOSITS[t]}
