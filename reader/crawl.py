"""A venue's events listing -> every event page under it -> hub records.

    python3 -m reader.crawl https://venue.example/events/ [--model ID] [--jobs N] [--out FILE]

Pages are fetched one at a time with a pause (a small venue's site is not ours
to load); the AI reads them in parallel afterwards. Only links below the
listing's own path are followed, one level deep.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests
from lxml import html as lxml_html

from . import core, llm

PAUSE_S = 1.5


def event_links(listing: str, page: bytes) -> list[str]:
    base = urlsplit(listing)
    tree = lxml_html.fromstring(page)
    out = []
    for href in tree.xpath("//a/@href"):
        u = urlsplit(urljoin(listing, href))
        if u.netloc == base.netloc and u.path.startswith(base.path) and u.path.rstrip("/") != base.path.rstrip("/"):
            url = f"{u.scheme}://{u.netloc}{u.path}"
            if url not in out:
                out.append(url)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="reader.crawl")
    ap.add_argument("listing")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", help="write all records as JSON lines here")
    a = ap.parse_args()
    llm.DEFAULT_MODEL = a.model
    received = datetime.now(timezone.utc)
    r = requests.get(a.listing, headers={"User-Agent": core.UA}, timeout=30)
    r.raise_for_status()
    links = event_links(a.listing, r.content)
    print(f"{len(links)} event pages under {a.listing}", file=sys.stderr)
    for i, url in enumerate(links, 1):
        page = requests.get(url, headers={"User-Agent": core.UA}, timeout=30)
        core.PREFETCHED[url] = (page.content, page.headers.get("content-type", "")) if page.ok else (b"", "")
        print(f"  fetched {i}/{len(links)} {page.status_code} {url}", file=sys.stderr)
        time.sleep(PAUSE_S)

    def one(url):
        try:
            return url, core.read(url, received), None
        except Exception as exc:
            return url, None, repr(exc)[:200]

    with ThreadPoolExecutor(a.jobs) as pool:
        results = list(pool.map(one, links))
    records, cost = [], 0.0
    for url, out, err in results:
        if err:
            print(f"✗ {url}: {err}")
            continue
        cost += out["cost_usd"]
        if not out["records"]:
            print(f"· {url}: no event ({'; '.join(out['notes'])[:120]})")
        for rec in out["records"]:
            records.append(rec)
            when = f"{rec['start_date']} {rec.get('start_time') or '--:--'}"
            rep = f"  ↻ {rec['recurrence']}" if rec.get("recurrence") else ""
            print(f"✓ {when}  {rec['name'][:48]:48}  {rec.get('price') or '':12}{rep}")
    print(f"\n{len(records)} events from {len(links)} pages · {a.model} · AI cost ${cost:.4f}")
    if a.out:
        with open(a.out, "w") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
