"""Kinds kept tidy: near-twin kinds suggested for merging, a steward says yes or keeps them apart.

His ruling (decision sheet, 2026-10-19): "a person for now, algorithmic pattern dev in the background for suggesting".
A merge changes how kinds are shown and counted, never a listing's own words, so it can be undone at any time.

Suggestions, strongest first:
  same    the same words once spaces, hyphens, case and a plural are set aside (breath work / breathwork)
  close   one letter apart, five letters or more (typos)
  inside  one kind's words all sit inside the other's (dj / dj sets, new moon / new moon ritual)
The suggested name to keep is the one used more; on a tie, the shorter.
"""
import re


def norm(tag: str) -> str:
    t = re.sub(r"[\s\-_]+", "", tag.lower())
    return t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t


def words(tag: str) -> set[str]:
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in re.findall(r"[a-z0-9']+", tag.lower())}


def one_apart(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 5 or a == b:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def suggest(counts: dict[str, int], kept: set[tuple[str, str]], limit: int = 40) -> list[dict]:
    tags = sorted(counts)
    out = []
    for i, a in enumerate(tags):
        for b in tags[i + 1:]:
            if tuple(sorted((a, b))) in kept:
                continue
            na, nb, wa, wb = norm(a), norm(b), words(a), words(b)
            why = ("same" if na == nb else "close" if one_apart(na, nb)
                   else "inside" if (wa < wb or wb < wa) else None)
            if not why:
                continue
            keep, merge = sorted((a, b), key=lambda t: (-counts[t], len(t), t))
            out.append({"keep": keep, "merge": merge, "why": why, "n_keep": counts[keep], "n_merge": counts[merge]})
    rank = {"same": 0, "close": 1, "inside": 2}
    out.sort(key=lambda s: (rank[s["why"]], -(s["n_keep"] + s["n_merge"]), s["merge"]))
    return out[:limit]


def apply(tags: list[str], merges: dict[str, str]) -> list[str]:
    """A listing's kinds as shown: each merged name replaced by the one kept, no repeats, order kept."""
    seen, out = set(), []
    for t in tags:
        t = merges.get(t, t)
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
