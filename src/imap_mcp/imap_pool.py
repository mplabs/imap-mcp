"""IMAP connection manager.

Each tool call acquires a fresh connection, selects the requested folder,
and yields a `Connection` dataclass with the client, UIDVALIDITY, account
name, and folder name — eliminating the need for callers to re-select.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator, Optional

from imapclient import IMAPClient

from .accounts import AccountRegistry
from .config import resolve_secret


@dataclass
class Connection:
    """Live IMAP connection with folder already selected."""
    client: IMAPClient
    uidvalidity: int
    account_name: str
    folder: str


class ImapPool:
    """Creates IMAP connections on demand. The name 'Pool' is historical;
    there is currently no connection reuse — each acquire() call creates
    and destroys one connection."""

    def __init__(self, registry: AccountRegistry):
        self._registry = registry

    def resolve(self, account: Optional[str]) -> tuple[str, object]:
        """Expose registry.resolve so callers don't reach into _registry."""
        return self._registry.resolve(account)

    @contextmanager
    def acquire(
        self,
        account: Optional[str],
        folder: str,
        readonly: bool = True,
    ) -> Generator[Connection, None, None]:
        """Yield a Connection with *folder* selected.

        The UIDVALIDITY from the SELECT response is captured once here;
        tools must NOT call select_folder again on the returned client.
        """
        name, acc = self._registry.resolve(account)
        password = resolve_secret(acc.imap.auth.secret_ref)

        client = IMAPClient(
            host=acc.imap.host,
            port=acc.imap.port,
            ssl=acc.imap.tls,
        )
        try:
            client.login(acc.imap.username, password)
            folder_data = client.select_folder(folder, readonly=readonly)
            uidvalidity = int(folder_data.get(b"UIDVALIDITY", 0))
            yield Connection(
                client=client,
                uidvalidity=uidvalidity,
                account_name=name,
                folder=folder,
            )
        finally:
            try:
                client.logout()
            except Exception:
                pass
