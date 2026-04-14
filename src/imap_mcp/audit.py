"""Append-only JSONL audit log for write operations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SECRET_KEYS = frozenset({
    "password", "secret", "token", "auth_token", "access_token",
    "refresh_token", "credential", "api_key", "private_key",
})

def _default_log_path() -> Path:
    return Path.home() / ".local" / "state" / "imap-mcp" / "audit.log"


def _redact(args: dict) -> dict:
    """Return a copy of *args* with secret-looking keys replaced with REDACTED."""
    out = {}
    for k, v in args.items():
        if any(s in k.lower() for s in _SECRET_KEYS):
            out[k] = "REDACTED"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


class AuditLog:
    def __init__(self, path: Optional[str] = None):
        self._path = Path(path) if path else _default_log_path()

    def log(
        self,
        account: str,
        tool: str,
        args: dict,
        result: str,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "tool": tool,
            "args": _redact(args),
            "result": result,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
