#!/bin/sh
# The live shape on this machine: the page on one address (8794, like the site), the data on another (8791, API only,
# like wheel.aureliusxradix.com), a throwaway member service (8793). Real proofs in headless Firefox, two screenshots:
# the self-test across origins, and the built shell (site/build.sh) showing the list.
set -eu
cd "$(dirname "$0")/../.."
T=$(mktemp -d); mkdir -p "$T/zk" "$T/web/vendor" "$T/web/assets"
podman rm -f wheel-zk-selftest >/dev/null 2>&1 || true
podman run -d --init --name wheel-zk-selftest --userns=keep-id --user "$(id -u):$(id -g)" --read-only --cap-drop=all \
  -p 127.0.0.1:8793:8792 -e WHEEL_ZK_HOST=0.0.0.0 -e WHEEL_ZK_STATE=/state -e WHEEL_ADMIN_TOKEN="$(cat data/zk-admin.token)" \
  -v "$PWD/zk":/app:ro,Z -v "$T/zk":/state:Z -w /app \
  registry.access.redhat.com/ubi9/nodejs-22-minimal@sha256:254080e3c058143c592f708e4ca78691449349fc79f03ee678c717aa4b6222b6 node server.mjs >/dev/null
cp data/hub.db "$T/hub.db"   # a copy of the real listings, so the shell has something to show; the copy is deleted after
EVENTHUB_DB="$T/hub.db" WHEEL_ZK_URL=http://127.0.0.1:8793 WHEEL_API_ONLY=1 WHEEL_ORIGINS=http://localhost:8794 \
  /usr/bin/python3 -E -s hub/server.py --port 8791 > "$T/api.log" 2>&1 &
API=$!
site/build.sh >/dev/null
cp -r dist/thewheel "$T/web/thewheel"
sed -i 's#data-api="https://wheel.aureliusxradix.com"#data-api="http://localhost:8791"#' "$T/web/thewheel/index.html"
sed -i "s#</body>#<img src=\"/__wait\" hidden></body>#" "$T/web/thewheel/index.html"   # test copy only: holds the load for the screenshot
cp tests/browser/selftest.html "$T/web/"; cp hub/static/vendor/wheel-zk.js "$T/web/vendor/"
ln -s "$PWD/hub/static/zk" "$T/web/zk"; ln -s "$PWD/hub/static/zk" "$T/web/assets/zk"
/usr/bin/python3 -E -s tests/browser/static_wait.py "$T/web" 8794 &
WEB=$!
sleep 1.5
P=$HOME/Downloads/hubshots; mkdir -p "$P"
shot() { mkdir -p "$P/prof-x"; timeout 120 flatpak run org.mozilla.firefox --headless --no-remote --new-instance --profile "$P/prof-x" \
  --screenshot "$P/$1" --window-size=900,1400 "$2" >/dev/null 2>&1 || true; rm -rf "$P/prof-x"; }
shot cross-selftest.png "http://localhost:8794/selftest.html?api=http://localhost:8791"
shot cross-shell.png "http://localhost:8794/thewheel/?shot=1#recovery"
kill "$API" "$WEB"; podman rm -f wheel-zk-selftest >/dev/null
grep -E 'gate:|error' "$T/api.log" || echo "api log: no gate holds, no errors"
rm -rf "$T"
echo "screenshots: $P/cross-selftest.png $P/cross-shell.png"
