"""The AI step: one post (text, image, or both) -> candidate events.

Backends are swappable; the choice of hosted or local model is still open.
Only `claude-cli` exists today: it runs the Claude Code
CLI headless (`claude -p`) with structured output, so it needs no API key on
the box. A backend gets (system_prompt, text, image_path) and returns the
parsed structured output plus a cost note.
"""

import base64
import json
import mimetypes
import os
import subprocess
from datetime import datetime
from pathlib import Path

PROMPT_VERSION = "extract-v4"  # v4 (2026-10-20): a flyer's visible text, for the identity gate; printed web addresses
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / f"{PROMPT_VERSION}.md"
DEFAULT_MODEL = os.environ.get("EVENTHUB_MODEL", "claude-opus-5-5")

_S = {"type": "string"}
_NS = {"type": ["string", "null"]}

EVENT_FIELDS = {
    "name": _S,
    "summary": _NS,
    "description": _NS,
    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
    "start_time": {"type": ["string", "null"], "description": "HH:MM, 24-hour"},
    "end_date": _NS,
    "end_time": _NS,
    "time_known": {"type": "boolean"},
    "recurrence": _NS,
    "status": {"type": "string", "enum": ["confirmed", "tentative", "postponed", "cancelled"]},
    "location_name": _NS,
    "location_address": _NS,
    "location_locality": _NS,
    "online": {"type": "boolean"},
    "organiser": _NS,
    "price": _NS,
    "website": _NS,
    "tickets_url": _NS,
    "kind_tags": {"type": "array", "items": _S},
    "listing_kind": {"type": "string", "enum": ["event", "volunteer"]},
    "modes": {"type": "array", "items": {"type": "string", "enum": ["day", "night", "recovery"]}},
    "slots": {"type": "array", "items": {
        "type": "object",
        "properties": {"date": _S, "start": _NS, "end": _NS, "needed": {"type": ["integer", "null"]}, "task": _NS},
        "required": ["date", "start", "end", "needed", "task"],
        "additionalProperties": False}},
    "requirements": {"type": "array", "items": _S},
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_event_post": {"type": "boolean"},
        "rejected_reason": _NS,
        "visible_text": {"type": ["string", "null"], "description": "an image post: all text visible in it, word for word"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": EVENT_FIELDS,
                "required": list(EVENT_FIELDS),
                "additionalProperties": False,
            },
        },
    },
    "required": ["is_event_post", "rejected_reason", "visible_text", "events"],
    "additionalProperties": False,
}


def system_prompt(received: datetime) -> str:
    return PROMPT_FILE.read_text().format(
        received=received.strftime("%Y-%m-%d %H:%M"), weekday=received.strftime("%A")
    )


def claude_cli(system: str, text: str | None, image: Path | None, model: str) -> dict:
    content = []
    if image is not None:
        media = mimetypes.guess_type(image.name)[0] or "image/png"
        data = base64.b64encode(image.read_bytes()).decode()
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    content.append({"type": "text", "text": text or "(The post is the image above.)"})
    message = {"type": "user", "message": {"role": "user", "content": content}}
    cmd = [
        "claude", "-p",
        "--model", model,
        "--no-session-persistence",
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--system-prompt", system,
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--json-schema", json.dumps(OUTPUT_SCHEMA),
    ]
    run = subprocess.run(cmd, input=json.dumps(message) + "\n", capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        raise RuntimeError(f"claude -p exited {run.returncode}: {run.stderr.strip()[:500]}")
    # stream-json in requires stream-json out; the run's outcome is the "result" line
    lines = [json.loads(l) for l in run.stdout.splitlines() if l.startswith("{")]
    result = next((l for l in reversed(lines) if l.get("type") == "result"), {})
    if result.get("is_error") or "structured_output" not in result:
        raise RuntimeError(f"no structured output: {str(result.get('result'))[:500]}")
    return {"output": result["structured_output"], "cost_usd": result.get("total_cost_usd"), "model": model}


BACKENDS = {"claude-cli": claude_cli}


def extract(text: str | None, image: Path | None, received: datetime,
            backend: str = "claude-cli", model: str = DEFAULT_MODEL) -> dict:
    return BACKENDS[backend](system_prompt(received), text, image, model)
