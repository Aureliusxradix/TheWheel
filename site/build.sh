#!/bin/sh
# Build The Wheel's page as a static shell for the site (aureliusxradix.com/thewheel/), then gate it.
#
#   site/build.sh                      → dist/thewheel/ , gated
#   WHEEL_API=https://... site/build.sh  another data address (default: the live one)
#
# The shell is hub/static as it is, with two settings written into <body>: where the data comes from (data-api)
# and where the proving files are (data-zk; the site already serves the same pinned files for its members page at
# /assets/zk/, checked equal by sha256, so the shell ships none). Nothing is published from here: copying the
# shell into the site repo is a separate, deliberate step, and the site's own eight deploy gates run on it again.
set -eu
cd "$(dirname "$0")/.."
API="${WHEEL_API:-https://wheel.aureliusxradix.com}"
ZK="${WHEEL_ZK_PATH:-/assets/zk/}"
OUT=dist/thewheel
rm -rf "$OUT"; mkdir -p "$OUT/vendor"
cp hub/static/index.html hub/static/app.js hub/static/style.css hub/static/sw.js hub/static/manifest.webmanifest "$OUT/"
cp -r hub/static/icons "$OUT/icons"
cp -r hub/static/vendor/leaflet "$OUT/vendor/leaflet"
cp hub/static/vendor/wheel-zk.js "$OUT/vendor/"
sed -i "s#<body data-api=\"\" data-zk=\"zk/\">#<body data-api=\"$API\" data-zk=\"$ZK\">#" "$OUT/index.html"
grep -q "data-api=\"$API\"" "$OUT/index.html" || { echo "REFUSED: the data address did not land in index.html" >&2; exit 4; }
sed -i '/__wait/d' "$OUT/app.js"   # the local screenshot aid; the live page has no use for it
# Each script and stylesheet is linked with its own content hash (?v=), so a browser holding last build's copy for its
# cache time (the host says 4 h) fetches the new one at once. 2026-10-20: a published Me page did not show until then.
/usr/bin/python3 -E -s - "$OUT" <<'PY'
import hashlib, re, sys
from pathlib import Path
out = Path(sys.argv[1]); page = out / "index.html"; html = page.read_text()
def bust(m):
    ref = m.group(2)
    v = hashlib.sha256((out / ref).read_bytes()).hexdigest()[:10]
    return f'{m.group(1)}="{ref}?v={v}"'
html, n = re.subn(r'(src|href)="((?:vendor/[^"?]+|app\.js|style\.css))"', bust, html)
assert n == 5, f"expected 5 versioned links, made {n}"
page.write_text(html)
PY

echo "== shell checks =="
if grep -rnE 'localhost|127\.0\.0\.1|__wait|selftest' "$OUT"; then
  echo "REFUSED: the shell points at this machine or carries a test aid" >&2; exit 5
fi
echo "  no local addresses, no test aids ✓"
echo "== identity gate (F3) =="
/usr/bin/python3 -E -s hub/gate.py --selftest "$OUT"
/usr/bin/python3 -E -s hub/gate.py "$OUT"
echo "built: $OUT ($(du -sh "$OUT" | cut -f1)), data from $API"
