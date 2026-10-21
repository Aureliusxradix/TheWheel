#!/bin/sh
# A real in-browser proof: a throwaway member service (8793) and app (8791), headless Firefox, a screenshot to read.
set -eu
cd "$(dirname "$0")/../.."
T=$(mktemp -d); mkdir -p "$T/zk"
podman rm -f wheel-zk-selftest >/dev/null 2>&1 || true
podman run -d --init --name wheel-zk-selftest --userns=keep-id --user "$(id -u):$(id -g)" --read-only --cap-drop=all \
  -p 127.0.0.1:8793:8792 -e WHEEL_ZK_HOST=0.0.0.0 -e WHEEL_ZK_STATE=/state -e WHEEL_ADMIN_TOKEN="$(cat data/zk-admin.token)" \
  -v "$PWD/zk":/app:ro,Z -v "$T/zk":/state:Z -w /app \
  registry.access.redhat.com/ubi9/nodejs-22-minimal@sha256:254080e3c058143c592f708e4ca78691449349fc79f03ee678c717aa4b6222b6 node server.mjs >/dev/null
EVENTHUB_DB="$T/hub.db" WHEEL_JOIN_WORK_BITS="${WHEEL_JOIN_WORK_BITS:-18}" WHEEL_ZK_URL=http://127.0.0.1:8793 WHEEL_SELFTEST=1 /usr/bin/python3 -E -s hub/server.py --port 8791 > "$T/server.log" 2>&1 &
HUB=$!
sleep 1.5
CODE=$(EVENTHUB_DB="$T/hub.db" /usr/bin/python3 -E -s hub/wheelctl.py codes 1 1 selftest)
P=$HOME/Downloads/hubshots; mkdir -p "$P/prof-selftest"
timeout 120 flatpak run org.mozilla.firefox --headless --no-remote --new-instance --profile "$P/prof-selftest" --screenshot "$P/selftest.png" --window-size=900,1400 "http://localhost:8791/selftest.html?code=$CODE" >/dev/null 2>&1 || true
kill "$HUB"; podman rm -f wheel-zk-selftest >/dev/null; rm -rf "$T" "$P/prof-selftest"
echo "screenshot: $P/selftest.png"
