"""Session-local message resolver.

Translates `message_id` strings (e.g. `<abc@example.com>`) to `Ref` objects
by maintaining a session cache populated as messages are fetched. On a cache
miss, it searches subscribed folders up to a configurable cap.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from .errors import MessageNotFoundError
from .ref import Ref, encode_ref, is_ref, is_message_id, parse_ref

if TYPE_CHECKING:
    from .imap_pool import ImapPool


class MessageResolver:
    """Session-local cache: message_id → (folder, uid, uidvalidity)."""

    def __init__(self, max_search_folders: int = 10):
        self._max_search_folders = max_search_folders
        # message_id → (folder, uid, uidvalidity)
        self._cache: dict[str, tuple[str, int, int]] = {}

    def register(self, message_id: str, folder: str, uid: int, uidvalidity: int) -> None:
        """Add a message to the session cache."""
        if message_id:
            self._cache[message_id] = (folder, uid, uidvalidity)

    def register_many(self, results: list[dict]) -> None:
        """Bulk-register message summaries returned by list/search."""
        for r in results:
            msg_id = r.get("message_id", "")
            ref_str = r.get("ref", "")
            if msg_id and ref_str:
                try:
                    ref = parse_ref(ref_str)
                    self.register(msg_id, ref.folder, ref.uid, ref.uidvalidity)
                except ValueError:
                    pass

    def resolve(
        self,
        id: str,
        pool: "ImapPool",
        account: Optional[str] = None,
    ) -> Ref:
        """Return a Ref for a ref string or a message_id.

        1. If id looks like a ref: parse and return immediately.
        2. If id looks like a message_id: check session cache; on miss,
           search subscribed folders (capped at max_search_folders).
        """
        if is_ref(id):
            return parse_ref(id)

        if not is_message_id(id):
            raise ValueError(
                f"Cannot resolve '{id}': expected a ref string "
                f"(account:folder:uidvalidity:uid) or a Message-ID (<...>)"
            )

        # Check session cache first
        if id in self._cache:
            folder, uid, uidvalidity = self._cache[id]
            account_name = pool.resolve(account)[0]
            return Ref(account=account_name, folder=folder, uidvalidity=uidvalidity, uid=uid)

        # Fall back to searching subscribed folders
        return self._search_folders(id, pool, account)

    def _search_folders(
        self,
        message_id: str,
        pool: "ImapPool",
        account: Optional[str],
    ) -> Ref:
        account_name, _ = pool.resolve(account)

        # List all selectable folders
        with pool.acquire(account, "INBOX") as conn:
            all_folders = conn.client.list_folders()

        searched = 0
        for flags, _, folder_name in all_folders:
            if searched >= self._max_search_folders:
                break
            flag_strs = {f.decode() if isinstance(f, bytes) else f for f in flags}
            if "\\Noselect" in flag_strs:
                continue

            try:
                with pool.acquire(account, folder_name) as conn:
                    uids = conn.client.search(["HEADER", "Message-ID", message_id])
                    if uids:
                        uid = uids[0]
                        self.register(message_id, folder_name, uid, conn.uidvalidity)
                        return Ref(
                            account=account_name,
                            folder=folder_name,
                            uidvalidity=conn.uidvalidity,
                            uid=uid,
                        )
            except Exception:
                pass

            searched += 1

        raise MessageNotFoundError(message_id)
