"""python3 -m reader <text | file | url> [--received ISO] [--by NAME]

Prints the hub records for one deposit as JSON. Nothing is stored yet.
"""

import argparse
import json
import sys
from datetime import datetime

from .core import read


def main() -> int:
    ap = argparse.ArgumentParser(prog="reader", description="Read one deposit into hub event records.")
    ap.add_argument("deposit", nargs="?", help="post text, a file path (.txt .ics .html .png .jpg), or a URL; '-' or nothing reads stdin")
    ap.add_argument("--received", help="when it was deposited, ISO 8601 (default: now)")
    ap.add_argument("--by", help="who deposited it")
    a = ap.parse_args()
    raw = sys.stdin.read() if a.deposit in (None, "-") else a.deposit
    received = datetime.fromisoformat(a.received) if a.received else None
    print(json.dumps(read(raw, received, a.by), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
