"""IMAP connection pool.

Provides a simple context-manager-based acquire() that creates a fresh
IMAPClient, logs in, and selects the requested folder.  In a future
milestone this can be upgraded to a real LRU pool.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from imapclient import IMAPClient

from .accounts import AccountRegistry
from .config import resolve_secret


class ImapPool:
    """Thin wrapper that acquires IMAP connections on demand."""

    def __init__(self, registry: AccountRegistry):
        self._registry = registry

    @contextmanager
    def acquire(
        self,
        account: Optional[str],
        folder: str,
        readonly: bool = True,
    ) -> Generator[IMAPClient, None, None]:
        """Yield a logged-in IMAPClient with *folder* selected."""
        name, acc = self._registry.resolve(account)
        password = resolve_secret(acc.imap.auth.secret_ref)

        client = IMAPClient(
            host=acc.imap.host,
            port=acc.imap.port,
            ssl=acc.imap.tls,
        )
        try:
            client.login(acc.imap.username, password)
            client.select_folder(folder, readonly=readonly)
            yield client
        finally:
            try:
                client.logout()
            except Exception:
                pass
