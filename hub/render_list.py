"""Hub records (JSON lines) -> one readable HTML list, grouped by month.

    python3 hub/render_list.py runs/x.jsonl --title "..." --today 2026-10-18 > out.html

First draft of the hub's list view. Output is an artifact page (no <html>/<head>).
"""

import argparse
import html
import json
from collections import defaultdict
from datetime import date

CSS = """
:root{--bg:#f3f1ec;--panel:#fffdf8;--ink:#1d1b18;--muted:#5d574e;--line:#d9d3c7;--accent:#0f6b5c;--accent-soft:#d7ece6;--flag:#8a5200;--flag-bg:#f6e6c8;
--display:"Fraunces",Georgia,serif;--body:"Atkinson Hyperlegible",Verdana,system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15130f;--panel:#1e1b16;--ink:#ece6da;--muted:#a79f91;--line:#352f27;--accent:#6fd0bc;--accent-soft:#183a33;--flag:#f0c46a;--flag-bg:#3a2e14;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#15130f;--panel:#1e1b16;--ink:#ece6da;--muted:#a79f91;--line:#352f27;--accent:#6fd0bc;--accent-soft:#183a33;--flag:#f0c46a;--flag-bg:#3a2e14;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:16px;line-height:1.5}
.wrap{max-width:820px;margin:0 auto;padding-block:36px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1{font-family:var(--display);font-size:clamp(1.9rem,5vw,2.6rem);margin:0 0 6px;text-wrap:balance}
.sub{color:var(--muted);margin:0 0 6px;max-width:65ch}
h2{font-family:var(--display);font-size:1.3rem;margin:36px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.ev{display:grid;grid-template-columns:64px 1fr;gap:14px;padding:12px 0;border-bottom:1px solid var(--line)}
.day{text-align:center;font-variant-numeric:tabular-nums}
.day b{display:block;font-family:var(--display);font-size:1.6rem;line-height:1}
.day span{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.body{min-width:0;display:grid;gap:4px}
.name{font-weight:700;font-size:1.05rem}
.name a{color:var(--ink);text-decoration-color:var(--line);text-underline-offset:3px}
.name a:hover{text-decoration-color:var(--accent)}
.meta{display:flex;flex-wrap:wrap;gap:4px 12px;color:var(--muted);font-size:.92rem}
.price{color:var(--muted);font-size:.88rem;overflow-wrap:anywhere}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-family:var(--mono);font-size:.72rem;padding:2px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}
.chip.flag{background:var(--flag-bg);color:var(--flag)}
.past{opacity:.75}
footer{margin-top:40px;color:var(--muted);font-size:.9rem;max-width:65ch}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
"""


def esc(s):
    return html.escape(str(s or ""))


def card(r, today, notes):
    d = date.fromisoformat(r["start_date"])
    t = r.get("start_time")
    when = f"{t}–{r['end_time']}" if t and r.get("end_time") else (t or "time not given")
    if r.get("end_date") and r["end_date"] != r["start_date"]:
        when += f" · until {date.fromisoformat(r['end_date']).strftime('%-d %b')}"
    url = (r.get("source") or {}).get("url") or r.get("website")
    name = f'<a href="{esc(url)}">{esc(r["name"])}</a>' if url else esc(r["name"])
    chips = []
    if r.get("recurrence"):
        chips.append(f'<span class="chip">↻ {esc(r["recurrence"][:60])}</span>')
    if r.get("status") != "confirmed":
        chips.append(f'<span class="chip flag">{esc(r["status"])}</span>')
    if not r.get("time_known"):
        chips.append('<span class="chip flag">no time on the page</span>')
    for n in notes.get(r["id"], []):
        chips.append(f'<span class="chip flag">{esc(n)}</span>')
    chips += [f'<span class="chip">{esc(t)}</span>' for t in r.get("tags", [])[:4]]
    place = r.get("location_name") or ""
    return f"""<article class="ev"><div class="day"><b>{d.day}</b><span>{d.strftime('%a')}</span></div>
<div class="body"><div class="name">{name}</div><div class="meta"><span>{esc(when)}</span><span>{esc(place)}</span></div>
{f'<div class="price">{esc(r["price"])}</div>' if r.get("price") else ''}<div class="chips">{''.join(chips)}</div></div></article>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--title", default="Events")
    ap.add_argument("--sub", default="")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--notes", help="JSON {record id: [flag text]} for hand-added review flags")
    ap.add_argument("--footer", default="")
    a = ap.parse_args()
    today = date.fromisoformat(a.today)
    recs = [json.loads(l) for l in open(a.records) if l.strip()]
    notes = json.load(open(a.notes)) if a.notes else {}

    def ongoing(r):
        end = date.fromisoformat(r.get("end_date") or r["start_date"])
        return r.get("recurrence") or end >= today

    upcoming = sorted((r for r in recs if ongoing(r)), key=lambda r: (r["start_date"], r.get("start_time") or ""))
    past = sorted((r for r in recs if not ongoing(r)), key=lambda r: r["start_date"], reverse=True)
    months = defaultdict(list)
    for r in upcoming:
        months[date.fromisoformat(r["start_date"]).strftime("%B %Y")].append(r)
    out = [f"<title>{esc(a.title)}</title>", '<meta name="claude:viewport-fit-sides" content="cover">',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=Atkinson+Hyperlegible:wght@400;700&family=JetBrains+Mono:wght@500&display=swap">',
           f"<style>{CSS}</style>", '<div class="wrap">', f"<h1>{esc(a.title)}</h1>", f'<p class="sub">{esc(a.sub)}</p>']
    for m, rs in months.items():
        out.append(f"<h2>{m}</h2>")
        out += [card(r, today, notes) for r in rs]
    if past:
        out.append("<h2>Already happened</h2>")
        out += [f'<div class="past">{card(r, today, notes)}</div>' for r in past]
    out.append(f"<footer>{a.footer}</footer></div>")
    print("\n".join(out))


if __name__ == "__main__":
    main()
