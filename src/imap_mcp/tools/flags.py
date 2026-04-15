"""Flag tools: set_flags, mark_read/unread, star/unstar."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from ..errors import StaleRefError

if TYPE_CHECKING:
    from ..context import Context


async def set_flags(
    ctx: "Context",
    id: str,
    add: list[str],
    remove: list[str],
    account: Optional[str] = None,
) -> dict:
    """Add and/or remove IMAP flags on a message."""
    ref = ctx.resolver.resolve(id, ctx.pool, account)

    with ctx.pool.acquire(account or ref.account, ref.folder, readonly=False) as conn:
        if conn.uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        if add:
            conn.client.add_flags([ref.uid], add)
        if remove:
            conn.client.remove_flags([ref.uid], remove)

    ctx.audit.log(ref.account, "set_flags", {"id": id, "add": add, "remove": remove}, "ok")
    return {"success": True, "id": id}


async def mark_read(
    ctx: "Context",
    id: str,
    account: Optional[str] = None,
) -> dict:
    return await set_flags(ctx, id, add=["\\Seen"], remove=[], account=account)


async def mark_unread(
    ctx: "Context",
    id: str,
    account: Optional[str] = None,
) -> dict:
    return await set_flags(ctx, id, add=[], remove=["\\Seen"], account=account)


async def star(
    ctx: "Context",
    id: str,
    account: Optional[str] = None,
) -> dict:
    return await set_flags(ctx, id, add=["\\Flagged"], remove=[], account=account)


async def unstar(
    ctx: "Context",
    id: str,
    account: Optional[str] = None,
) -> dict:
    return await set_flags(ctx, id, add=[], remove=["\\Flagged"], account=account)
