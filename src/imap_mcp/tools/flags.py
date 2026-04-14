"""Flag tools: set_flags, mark_read/unread, star/unstar."""

from __future__ import annotations

from typing import Optional

from ..audit import AuditLog
from ..errors import StaleRefError
from ..imap_pool import ImapPool
from ..ref import parse_ref


async def set_flags(
    pool: ImapPool,
    id: str,
    add: list[str],
    remove: list[str],
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Add and/or remove IMAP flags on a message."""
    ref = parse_ref(id)
    target_account = account or ref.account

    with pool.acquire(target_account, ref.folder, readonly=False) as client:
        folder_info = client.select_folder(ref.folder, readonly=False)
        server_uidvalidity = int(folder_info.get(b"UIDVALIDITY", 0))

        if server_uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        if add:
            client.add_flags([ref.uid], add)
        if remove:
            client.remove_flags([ref.uid], remove)

    if audit:
        audit.log(target_account, "set_flags", {"id": id, "add": add, "remove": remove}, "ok")

    return {"success": True, "id": id}


async def mark_read(
    pool: ImapPool,
    id: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    return await set_flags(pool, id, add=["\\Seen"], remove=[], account=account, audit=audit)


async def mark_unread(
    pool: ImapPool,
    id: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    return await set_flags(pool, id, add=[], remove=["\\Seen"], account=account, audit=audit)


async def star(
    pool: ImapPool,
    id: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    return await set_flags(pool, id, add=["\\Flagged"], remove=[], account=account, audit=audit)


async def unstar(
    pool: ImapPool,
    id: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    return await set_flags(pool, id, add=[], remove=["\\Flagged"], account=account, audit=audit)
