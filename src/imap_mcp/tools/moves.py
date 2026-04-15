"""Move, copy, and delete tools."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from ..errors import PermissionDeniedError, StaleRefError

if TYPE_CHECKING:
    from ..context import Context


async def move_email(
    ctx: "Context",
    id: str,
    to_folder: str,
    account: Optional[str] = None,
) -> dict:
    """Move a message: COPY to target, set \\Deleted on source, EXPUNGE."""
    ref = ctx.resolver.resolve(id, ctx.pool, account)
    target_account = account or ref.account

    with ctx.pool.acquire(target_account, ref.folder, readonly=False) as conn:
        if conn.uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        conn.client.copy([ref.uid], to_folder)
        conn.client.add_flags([ref.uid], ["\\Deleted"])
        conn.client.expunge()

    ctx.audit.log(target_account, "move_email", {"id": id, "to_folder": to_folder}, "ok")
    return {"success": True, "id": id, "to_folder": to_folder}


async def copy_email(
    ctx: "Context",
    id: str,
    to_folder: str,
    account: Optional[str] = None,
) -> dict:
    """Copy a message to another folder (source untouched)."""
    ref = ctx.resolver.resolve(id, ctx.pool, account)
    target_account = account or ref.account

    with ctx.pool.acquire(target_account, ref.folder, readonly=False) as conn:
        if conn.uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        conn.client.copy([ref.uid], to_folder)

    ctx.audit.log(target_account, "copy_email", {"id": id, "to_folder": to_folder}, "ok")
    return {"success": True, "id": id, "to_folder": to_folder}


async def delete_email(
    ctx: "Context",
    id: str,
    hard: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Delete a message.

    - hard=False (default): move to configured trash folder.
    - hard=True: requires safety.allow_delete=True in account config.
    """
    ref = ctx.resolver.resolve(id, ctx.pool, account)
    target_account = account or ref.account
    _, acc_config = ctx.registry.resolve(target_account)

    if hard:
        if not acc_config.safety.allow_delete:
            raise PermissionDeniedError(
                "hard delete blocked: set safety.allow_delete=true in config"
            )

        with ctx.pool.acquire(target_account, ref.folder, readonly=False) as conn:
            if conn.uidvalidity != ref.uidvalidity:
                raise StaleRefError(ref.folder)

            conn.client.add_flags([ref.uid], ["\\Deleted"])
            conn.client.expunge()

        ctx.audit.log(target_account, "delete_email", {"id": id, "hard": True}, "ok")
    else:
        trash_folder = acc_config.folders.trash
        await move_email(ctx, id=id, to_folder=trash_folder, account=target_account)
        # move_email already logged; emit a delete audit entry too
        ctx.audit.log(target_account, "delete_email", {"id": id, "hard": False}, "ok")

    return {"success": True, "id": id}


async def empty_trash(
    ctx: "Context",
    account: Optional[str] = None,
    confirm: bool = False,
) -> dict:
    """Permanently delete all messages in the trash folder.

    Requires both safety.allow_empty_trash=true in config and confirm=True.
    """
    if not confirm:
        raise PermissionDeniedError("empty_trash requires confirm=true")

    name, acc_config = ctx.registry.resolve(account)
    if not acc_config.safety.allow_empty_trash:
        raise PermissionDeniedError(
            "empty_trash blocked: set safety.allow_empty_trash=true in config"
        )

    trash_folder = acc_config.folders.trash

    with ctx.pool.acquire(name, trash_folder, readonly=False) as conn:
        uids = conn.client.search(["ALL"])
        if uids:
            conn.client.add_flags(uids, ["\\Deleted"])
            conn.client.expunge()

    ctx.audit.log(name, "empty_trash", {}, "ok")
    return {"success": True, "account": name, "folder": trash_folder}
