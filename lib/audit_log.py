"""Appends one JSON record per agent decision to audit/log.jsonl, committed
back to this agent's own repo after each run. This is the governance trail:
every triage classification, every governance approve/block (with reasoning),
and every notifier action, in order, forever.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_PATH = Path(__file__).resolve().parent.parent / "audit" / "log.jsonl"


def record(event: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with open(AUDIT_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
