"""Move, copy, and delete tools."""

from __future__ import annotations

from typing import Optional

from ..accounts import AccountRegistry
from ..audit import AuditLog
from ..errors import PermissionDeniedError, StaleRefError
from ..imap_pool import ImapPool
from ..ref import parse_ref


async def move_email(
    pool: ImapPool,
    id: str,
    to_folder: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Move a message: COPY to target, set \\Deleted on source, EXPUNGE."""
    ref = parse_ref(id)
    target_account = account or ref.account

    with pool.acquire(target_account, ref.folder, readonly=False) as client:
        folder_info = client.select_folder(ref.folder, readonly=False)
        server_uidvalidity = int(folder_info.get(b"UIDVALIDITY", 0))

        if server_uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        client.copy([ref.uid], to_folder)
        client.add_flags([ref.uid], ["\\Deleted"])
        client.expunge()

    if audit:
        audit.log(target_account, "move_email", {"id": id, "to_folder": to_folder}, "ok")

    return {"success": True, "id": id, "to_folder": to_folder}


async def copy_email(
    pool: ImapPool,
    id: str,
    to_folder: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Copy a message to another folder (source untouched)."""
    ref = parse_ref(id)
    target_account = account or ref.account

    with pool.acquire(target_account, ref.folder, readonly=False) as client:
        folder_info = client.select_folder(ref.folder, readonly=False)
        server_uidvalidity = int(folder_info.get(b"UIDVALIDITY", 0))

        if server_uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        client.copy([ref.uid], to_folder)

    if audit:
        audit.log(target_account, "copy_email", {"id": id, "to_folder": to_folder}, "ok")

    return {"success": True, "id": id, "to_folder": to_folder}


async def delete_email(
    pool: ImapPool,
    id: str,
    hard: bool = False,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
    registry: Optional[AccountRegistry] = None,
) -> dict:
    """Delete a message.

    - hard=False (default): move to configured trash folder.
    - hard=True: requires safety.allow_delete=True in account config.
    """
    ref = parse_ref(id)
    target_account = account or ref.account

    if hard:
        if registry is None:
            raise PermissionDeniedError("allow_delete requires registry")
        acc = registry.get(target_account)
        if not acc.safety.allow_delete:
            raise PermissionDeniedError(
                "hard delete blocked: set safety.allow_delete=true in config"
            )

        with pool.acquire(target_account, ref.folder, readonly=False) as client:
            folder_info = client.select_folder(ref.folder, readonly=False)
            server_uidvalidity = int(folder_info.get(b"UIDVALIDITY", 0))

            if server_uidvalidity != ref.uidvalidity:
                raise StaleRefError(ref.folder)

            client.add_flags([ref.uid], ["\\Deleted"])
            client.expunge()
    else:
        # Soft delete: move to trash
        trash_folder = "Trash"
        if registry:
            acc = registry.get(target_account)
            trash_folder = acc.folders.trash

        await move_email(pool, id=id, to_folder=trash_folder, account=target_account, audit=None)

    if audit:
        audit.log(target_account, "delete_email", {"id": id, "hard": hard}, "ok")

    return {"success": True, "id": id}


async def empty_trash(
    pool: ImapPool,
    account: Optional[str] = None,
    confirm: bool = False,
    audit: Optional[AuditLog] = None,
    registry: Optional[AccountRegistry] = None,
) -> dict:
    """Permanently delete all messages in the trash folder.

    Requires both safety.allow_empty_trash=true in config and confirm=True
    in the call.
    """
    if not confirm:
        raise PermissionDeniedError("empty_trash requires confirm=true")

    if registry is None:
        raise PermissionDeniedError("allow_empty_trash requires registry")

    _, acc_config = registry.resolve(account)
    if not acc_config.safety.allow_empty_trash:
        raise PermissionDeniedError(
            "empty_trash blocked: set safety.allow_empty_trash=true in config"
        )

    name, acc = registry.resolve(account)
    trash_folder = acc.folders.trash

    with pool.acquire(name, trash_folder, readonly=False) as client:
        client.select_folder(trash_folder, readonly=False)
        uids = client.search(["ALL"])
        if uids:
            client.add_flags(uids, ["\\Deleted"])
            client.expunge()

    if audit:
        audit.log(name, "empty_trash", {}, "ok")

    return {"success": True, "account": name, "folder": trash_folder}
