"""Batch operation tools."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ..accounts import AccountRegistry
from ..audit import AuditLog
from ..errors import ConfirmationRequiredError
from ..imap_pool import ImapPool
from ..ref import parse_ref


def _check_confirm(ids: list[str], registry: AccountRegistry, account: str, confirm: bool) -> None:
    """Raise ConfirmationRequiredError if batch is too large and confirm is False."""
    _, acc = registry.resolve(account)
    threshold = acc.safety.confirm_batch_threshold
    if len(ids) > threshold and not confirm:
        raise ConfirmationRequiredError(len(ids))


def _group_by_folder(ids: list[str]) -> dict[str, list[int]]:
    """Group UIDs by (account, folder) key for efficient UID-set operations."""
    groups: dict[str, list[int]] = defaultdict(list)
    for id_str in ids:
        ref = parse_ref(id_str)
        key = f"{ref.account}:{ref.folder}:{ref.uidvalidity}"
        groups[key].append(ref.uid)
    return groups


async def batch_set_flags(
    pool: ImapPool,
    ids: list[str],
    add: list[str],
    remove: list[str],
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
    registry: Optional[AccountRegistry] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Add/remove flags on a list of messages. Uses UID STORE sets where possible."""
    if registry:
        _check_confirm(ids, registry, account or parse_ref(ids[0]).account, confirm)

    if dry_run:
        return {"success": True, "count": len(ids), "dry_run": True}

    groups = _group_by_folder(ids)
    for key, uids in groups.items():
        acc_name, folder, _ = key.split(":", 2)
        target = account or acc_name
        with pool.acquire(target, folder, readonly=False) as client:
            if add:
                client.add_flags(uids, add)
            if remove:
                client.remove_flags(uids, remove)

    if audit and not dry_run:
        audit.log(account or "default", "batch_set_flags", {"count": len(ids)}, "ok")

    return {"success": True, "count": len(ids), "dry_run": False}


async def batch_move(
    pool: ImapPool,
    ids: list[str],
    to_folder: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
    registry: Optional[AccountRegistry] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Move a list of messages to a target folder."""
    if registry:
        _check_confirm(ids, registry, account or parse_ref(ids[0]).account, confirm)

    if dry_run:
        return {"success": True, "count": len(ids), "dry_run": True, "to_folder": to_folder}

    groups = _group_by_folder(ids)
    for key, uids in groups.items():
        acc_name, folder, _ = key.split(":", 2)
        target = account or acc_name
        with pool.acquire(target, folder, readonly=False) as client:
            client.copy(uids, to_folder)
            client.add_flags(uids, ["\\Deleted"])
            client.expunge()

    if audit and not dry_run:
        audit.log(account or "default", "batch_move", {"count": len(ids), "to_folder": to_folder}, "ok")

    return {"success": True, "count": len(ids), "dry_run": False, "to_folder": to_folder}


async def batch_delete(
    pool: ImapPool,
    ids: list[str],
    hard: bool = False,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
    registry: Optional[AccountRegistry] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Delete a list of messages (soft → Trash, or hard if permitted)."""
    if registry:
        _check_confirm(ids, registry, account or parse_ref(ids[0]).account, confirm)

    if dry_run:
        return {"success": True, "count": len(ids), "dry_run": True}

    if hard:
        groups = _group_by_folder(ids)
        for key, uids in groups.items():
            acc_name, folder, _ = key.split(":", 2)
            target = account or acc_name
            with pool.acquire(target, folder, readonly=False) as client:
                client.add_flags(uids, ["\\Deleted"])
                client.expunge()
    else:
        # Soft delete: move each to trash folder
        trash_folder = "Trash"
        if registry:
            _, acc_config = registry.resolve(account)
            trash_folder = acc_config.folders.trash

        await batch_move(
            pool,
            ids=ids,
            to_folder=trash_folder,
            account=account,
            audit=None,
            registry=registry,
            confirm=confirm,
        )

    if audit and not dry_run:
        audit.log(account or "default", "batch_delete", {"count": len(ids), "hard": hard}, "ok")

    return {"success": True, "count": len(ids), "dry_run": False}
