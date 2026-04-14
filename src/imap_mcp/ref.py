"""Message reference encoding and detection.

A *ref* is a compact tuple string:
    "<account>:<folder>:<uidvalidity>:<uid>"
e.g. "personal:INBOX:1699999999:12345"

A *message_id* is the RFC 5322 Message-ID header value, e.g.
    "<abc123@example.com>"
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ref:
    account: str
    folder: str
    uidvalidity: int
    uid: int


def encode_ref(ref: Ref) -> str:
    return f"{ref.account}:{ref.folder}:{ref.uidvalidity}:{ref.uid}"


def parse_ref(s: str) -> Ref:
    """Parse a ref string into a Ref dataclass.

    The format is "<account>:<folder>:<uidvalidity>:<uid>".
    Folder names may contain the delimiter character (. or /), so we split
    on the first colon, then the last two colons.
    """
    parts = s.split(":")
    if len(parts) < 4:
        raise ValueError(f"Invalid ref '{s}': expected at least 4 colon-separated fields")

    # Split: account is first, uid is last, uidvalidity is second-to-last,
    # folder is everything in between.
    account = parts[0]
    uid = int(parts[-1])
    uidvalidity = int(parts[-2])
    folder = ":".join(parts[1:-2])
    return Ref(account=account, folder=folder, uidvalidity=uidvalidity, uid=uid)


def is_ref(s: str) -> bool:
    """Return True if *s* looks like a ref string."""
    parts = s.split(":")
    if len(parts) < 4:
        return False
    try:
        int(parts[-1])
        int(parts[-2])
        return True
    except ValueError:
        return False


def is_message_id(s: str) -> bool:
    """Return True if *s* looks like an RFC 5322 Message-ID (wrapped in angle brackets)."""
    return s.startswith("<") and s.endswith(">")
