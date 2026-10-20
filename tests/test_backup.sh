#!/bin/sh
# A1 round trip with a throwaway key: copy, no-change skip, change, restore equal, tampered copy refused.
set -eu
cd "$(dirname "$0")/.."
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-384 -nodes -keyout "$T/key.pem" -out "$T/cert.pem" -days 2 -subj "/CN=wheel-backup-test" 2>/dev/null
mkdir -p "$T/store/zk-state"
/usr/bin/python3 -E -s -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('create table t(x)'); c.execute(\"insert into t values('kava')\"); c.commit()" "$T/store/hub.db"
echo '["123"]' > "$T/store/zk-state/members.json"
B="/usr/bin/python3 -E -s ops/backup.py --store $T/store --out $T/out --to $T/cert.pem"
$B | grep -q '^wrote' && echo "ok 1 first copy written"
$B | grep -q '^no change' && echo "ok 2 unchanged store: nothing written"
/usr/bin/python3 -E -s -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"insert into t values('sound bath')\"); c.commit()" "$T/store/hub.db"
$B | grep -q '^wrote' && echo "ok 3 changed store: a new copy"
[ "$(ls "$T/out"/wheel-*.cms | wc -l)" = 2 ] && echo "ok 4 two copies kept"
NEW=$(ls -t "$T/out"/wheel-*.cms | head -1)
grep -q -a kava "$NEW" && { echo "not ok 5 plain text visible in the sealed copy"; exit 1; } || echo "ok 5 sealed copy carries no plain text"
/usr/bin/python3 -E -s ops/backup.py --restore "$NEW" --key "$T/key.pem" --cert "$T/cert.pem" --into "$T/back" >/dev/null
[ "$(/usr/bin/python3 -E -s -c "import sqlite3,sys; print(','.join(r[0] for r in sqlite3.connect(sys.argv[1]).execute('select x from t')))" "$T/back/hub.db")" = "kava,sound bath" ] && echo "ok 6 restore gives the rows back"
cmp -s "$T/back/zk-state/members.json" "$T/store/zk-state/members.json" && echo "ok 7 member state restored equal"
cp "$NEW" "$T/bad.cms"; printf 'X' | dd of="$T/bad.cms" bs=1 seek=400 conv=notrunc 2>/dev/null
if /usr/bin/python3 -E -s ops/backup.py --restore "$T/bad.cms" --key "$T/key.pem" --cert "$T/cert.pem" --into "$T/bad" 2>/dev/null; then
  echo "not ok 8 a tampered copy restored"; exit 1; else echo "ok 8 a tampered copy is refused"; fi
