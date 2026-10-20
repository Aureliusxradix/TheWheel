#!/bin/sh
# Start The Wheel's member service on this machine: a locked-down container, reachable only from 127.0.0.1:8792.
# The image is Red Hat's signed Node 22 (the build machine's container policy runs signed images only), pinned by digest.
set -eu
cd "$(dirname "$0")/.."
mkdir -p data/zk-state
[ -s data/zk-admin.token ] || { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > data/zk-admin.token; chmod 600 data/zk-admin.token; }
podman container exists wheel-zk && podman rm -f wheel-zk >/dev/null
exec podman run -d --init --name wheel-zk --userns=keep-id --user "$(id -u):$(id -g)" --read-only --cap-drop=all --security-opt no-new-privileges \
  --memory 256m -p 127.0.0.1:8792:8792 \
  -e WHEEL_ZK_HOST=0.0.0.0 -e WHEEL_ZK_STATE=/state -e WHEEL_ADMIN_TOKEN="$(cat data/zk-admin.token)" \
  -v "$PWD/zk":/app:ro,Z -v "$PWD/data/zk-state":/state:Z -w /app \
  registry.access.redhat.com/ubi9/nodejs-22-minimal@sha256:254080e3c058143c592f708e4ca78691449349fc79f03ee678c717aa4b6222b6 node server.mjs
