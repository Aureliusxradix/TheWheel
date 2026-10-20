"""A1 for The Wheel: an encrypted copy of the store, made when it changes, for the off-site leg to carry away.

    /usr/bin/python3 -E -s ops/backup.py --store data --out /var/srv/backup/wheel --to recipient.pem [--keep 14]
    /usr/bin/python3 -E -s ops/backup.py --restore <file.cms> --key key.pem --cert recipient.pem --into <dir>

What goes in: the listings store (hub.db, copied with SQLite's own backup, so a write in progress cannot tear it)
and the member service's state (zk-state/: commitments, check-in hashes, show-up nullifiers; no names exist to copy).
It is encrypted on the box to a public certificate (OpenSSL CMS, AES-256-GCM: a changed byte fails the restore).
The private key never lives on the box that makes the copies, so a stolen box gives up nothing from its backups.

Run every 15 minutes by a timer. When nothing changed since the last copy it writes nothing and says so; that is
what "event-triggered" means here: a change is the event, the timer is how it is noticed.
"""
import argparse
import hashlib
import io
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def snapshot(store: Path) -> bytes:
    """hub.db and zk-state/ as one tar, made the same way every time so unchanged data gives unchanged bytes."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "hub.db"
        src = sqlite3.connect(f"file:{store / 'hub.db'}?mode=ro", uri=True)
        dst = sqlite3.connect(db)
        src.backup(dst)
        dst.execute("VACUUM")  # same rows, same bytes: free pages and page order no longer differ between copies
        dst.close(); src.close()
        files = [("hub.db", db)] + [(f"zk-state/{p.name}", p) for p in sorted((store / "zk-state").glob("*.json"))]
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name, path in files:
                data = path.read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mtime, info.mode = len(data), 0, 0o600
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def openssl(*args, stdin: bytes | None = None) -> bytes:
    r = subprocess.run(["openssl", *args], input=stdin, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"openssl {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.decode()[:300]}")
    return r.stdout


def backup(store: Path, out: Path, cert: Path, keep: int) -> str:
    out.mkdir(parents=True, exist_ok=True)
    plain = snapshot(store)
    digest = hashlib.sha256(plain).hexdigest()
    last = out / ".last-sha256"
    if last.exists() and last.read_text().strip() == digest:
        return "no change since the last copy; nothing written"
    sealed = openssl("cms", "-encrypt", "-binary", "-aes-256-gcm", "-outform", "DER", str(cert), stdin=plain)
    openssl("cms", "-cmsout", "-inform", "DER", "-noout", stdin=sealed)  # the sealed copy parses as CMS before it counts
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = out / f"wheel-{stamp}-{digest[:8]}.cms"  # two copies in one second never share a name
    tmp = out / f".{final.name}.part"
    tmp.write_bytes(sealed)
    os.chmod(tmp, 0o640)
    tmp.rename(final)  # the off-site leg only ever sees whole files
    last.write_text(digest + "\n")
    for old in sorted(out.glob("wheel-*.cms"))[:-keep]:
        old.unlink()
    return f"wrote {final.name} ({len(sealed)} bytes, {len(plain)} before sealing)"


def restore(sealed: Path, key: Path, cert: Path, into: Path) -> str:
    plain = openssl("cms", "-decrypt", "-binary", "-inform", "DER", "-in", str(sealed), "-inkey", str(key), "-recip", str(cert))
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(plain)) as tar:
        tar.extractall(into, filter="data")
    return f"restored {len(plain)} bytes into {into}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--to", type=Path, help="the recipient's public certificate")
    ap.add_argument("--keep", type=int, default=14)
    ap.add_argument("--restore", type=Path)
    ap.add_argument("--key", type=Path)
    ap.add_argument("--cert", type=Path)
    ap.add_argument("--into", type=Path)
    a = ap.parse_args()
    try:
        if a.restore:
            print(restore(a.restore, a.key, a.cert, a.into))
        else:
            print(backup(a.store, a.out, a.to, a.keep))
    except Exception as exc:  # the timer's failure hook alarms on a non-zero exit
        sys.exit(f"wheel backup FAILED: {exc}")


if __name__ == "__main__":
    main()
