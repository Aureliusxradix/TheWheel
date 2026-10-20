#!/usr/bin/env bash
# Fetch the Semaphore proving files once, from their publisher (PSE), check them against the pinned hashes in
# artifacts.sha256, and copy them where the page loads them from (hub/static/zk/). Members' browsers load these
# from your own host, never from a CDN.   Usage: bash zk/fetch-artifacts.sh
set -euo pipefail
cd "$(dirname "$0")"
VER=4.13.0          # the version @semaphore-protocol/proof 4.14.3 asks for
MAXD=${MAXD:-10}    # depths 1..10 = groups up to 1024 members
mkdir -p artifacts
for d in $(seq 1 "$MAXD"); do
  for ext in wasm zkey; do
    f="artifacts/semaphore-$d.$ext"
    [ -s "$f" ] || curl -fsS --retry 3 -o "$f" "https://snark-artifacts.pse.dev/semaphore/$VER/semaphore-$d.$ext"
  done
done
(cd artifacts && sha256sum -c --quiet ../artifacts.sha256) && echo "proving files match the pins"
mkdir -p ../hub/static/zk && cp artifacts/semaphore-*.wasm artifacts/semaphore-*.zkey ../hub/static/zk/
echo "copied to hub/static/zk/"
