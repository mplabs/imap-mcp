"""IMAP connection manager.

Each tool call acquires a fresh connection, selects the requested folder,
and yields a `Connection` dataclass with the client, UIDVALIDITY, account
name, and folder name — eliminating the need for callers to re-select.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator, Optional

from imapclient import IMAPClient

from .accounts import AccountRegistry
from .config import resolve_secret

if TYPE_CHECKING:
    from .rate_limit import RateLimiter


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

    def __init__(
        self,
        registry: AccountRegistry,
        rate_limiter: Optional["RateLimiter"] = None,
    ):
        self._registry = registry
        self._rate_limiter = rate_limiter

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

        Consumes one rate-limit token before connecting.  Raises
        RateLimitedError if the account bucket is exhausted.
        """
        name, acc = self._registry.resolve(account)

        if self._rate_limiter is not None:
            self._rate_limiter.consume(name)

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
