"""Context object — single carrier for per-session infrastructure."""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import AccountRegistry
from .audit import AuditLog
from .imap_pool import ImapPool
from .resolver import MessageResolver


@dataclass(frozen=True)
class Context:
    """Immutable carrier for the four per-session infrastructure objects.

    Constructed once at server startup and threaded through every tool call.
    Tools access pool, registry, audit, and resolver via this object instead
    of receiving four separate parameters.
    """
    pool: ImapPool
    registry: AccountRegistry
    audit: AuditLog
    resolver: MessageResolver
