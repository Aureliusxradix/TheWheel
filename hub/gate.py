"""The identity gate: nothing The Wheel says, or ships, may carry a trace of the private world it runs beside.

Threat profile controls F3 (deploy) and F4 (runtime). The lesson both come from: a deploy gate greps the files that
ship and cannot see what a running service says, so a service on the domain carries its own gate.

The words it looks for are private and are NOT in this repo: they name the people and places this project must
never lead to, and the repo may go public. They come from a file named by WHEEL_GATE_PATTERNS (one regular
expression per line, # for notes). Without that file the gate refuses to load, and so does anything that needs it.
A few generic marks (machine paths, private keys, tracebacks) are built in, so the gate is never empty.

    /usr/bin/python3 -E -s hub/gate.py <tree>              check a built tree (the deploy gate)
    /usr/bin/python3 -E -s hub/gate.py --selftest <tree>   plant a leak, prove the gate bites, remove it
    /usr/bin/python3 -E -s hub/gate.py --source <tree>     a source tree: the private list only (the built-in marks
                                                           are for answers, and this code itself contains them)
"""

import os
import re
import sys
from pathlib import Path

DEFAULT = Path.home() / ".config" / "the-wheel" / "gate-patterns.txt"  # on the build machine, a link to the private copy
BUILT_IN = [  # generic marks; anything naming a person, place or home folder belongs in the private list
    r"/root/",
    r"BEGIN [A-Z ]*PRIVATE KEY",
    r"Traceback \(most recent call last\)",
    r"File \"/",
    r"x-wheel-admin",
]
MIN_PRIVATE = 10  # a private list shorter than this was cut short somewhere: refuse it
FORBIDDEN_NAMES = re.compile(r".*\.(pem|key|token|db|sqlite|map|env|bak)$|^\.env.*$", re.I)


class GateMissing(RuntimeError):
    pass


def load(path: str | os.PathLike | None = None, builtin: bool = True) -> re.Pattern:
    f = Path(path or os.environ.get("WHEEL_GATE_PATTERNS") or DEFAULT)
    try:
        lines = f.read_text().splitlines()
    except OSError as exc:
        raise GateMissing(f"the identity gate's word list is missing ({exc.__class__.__name__}); set WHEEL_GATE_PATTERNS") from None
    private = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if len(private) < MIN_PRIVATE:
        raise GateMissing(f"the identity gate's word list has {len(private)} entries, fewer than {MIN_PRIVATE}; refusing it")
    for p in private:
        re.compile(p)  # a broken line fails here, loudly, not as a silent miss later
    return re.compile("|".join(f"(?:{p})" for p in (BUILT_IN if builtin else []) + private), re.I)


def hit(rx: re.Pattern, text: str | bytes) -> str | None:
    """The first private mark in text, or None. Callers log it privately and never send it on."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    m = rx.search(text)
    return m.group(0) if m else None


def scan_tree(rx: re.Pattern, tree: Path) -> list[str]:
    problems = []
    for f in sorted(p for p in tree.rglob("*") if p.is_file() and ".git" not in p.parts):
        rel = f.relative_to(tree)
        if FORBIDDEN_NAMES.match(f.name):
            problems.append(f"{rel}: a file of this kind never ships")
            continue
        if f.suffix in (".wasm", ".zkey", ".png", ".jpg", ".webp", ".gif", ".ico"):
            continue  # binary: names in them would be a build fault the text gate cannot read; size-checked elsewhere
        h = hit(rx, f.read_bytes())
        if h:
            problems.append(f"{rel}: carries /{h}/")
    return problems


def main(argv: list[str]) -> int:
    selftest = argv[:1] == ["--selftest"]
    source = argv[:1] == ["--source"]
    args = argv[1:] if selftest or source else argv
    if len(args) != 1 or not Path(args[0]).is_dir():
        print(__doc__.strip().splitlines()[-2].strip(), file=sys.stderr)
        return 2
    tree = Path(args[0])
    try:
        rx = load(builtin=not source)
    except GateMissing as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    plant = tree / ".gate-selftest"
    if selftest:
        plant.write_text("this line comes from /root/notes\n")
    try:
        problems = scan_tree(rx, tree)
    finally:
        if selftest:
            plant.unlink(missing_ok=True)
    if selftest:
        if any(p.startswith(".gate-selftest") for p in problems):
            print("✓ selftest: the gate bit on a planted leak")
            return 0
        print("✗ selftest: the gate did NOT see a planted leak. Do not trust it.", file=sys.stderr)
        return 9
    files = sum(1 for p in tree.rglob("*") if p.is_file())
    if problems:
        print(f"REFUSED: {len(problems)} of {files} files:", file=sys.stderr)
        for p in problems[:20]:
            print("  " + p, file=sys.stderr)
        return 1
    print(f"✓ clean: {files} files, no trace of the private world")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
