"""Batch operation tools."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional, TYPE_CHECKING

from ..errors import ConfirmationRequiredError
from ..ref import parse_ref

if TYPE_CHECKING:
    from ..context import Context


def _check_confirm(
    ids: list[str],
    ctx: "Context",
    account: Optional[str],
    confirm: bool,
) -> None:
    """Raise ConfirmationRequiredError if batch is too large and confirm is False."""
    _, acc = ctx.registry.resolve(account)
    threshold = acc.safety.confirm_batch_threshold
    if len(ids) > threshold and not confirm:
        raise ConfirmationRequiredError(len(ids))


def _group_by_folder(ids: list[str]) -> dict[tuple, list[int]]:
    """Group UIDs by (account, folder, uidvalidity) key for efficient UID-set operations."""
    groups: dict[tuple, list[int]] = defaultdict(list)
    for id_str in ids:
        ref = parse_ref(id_str)
        key = (ref.account, ref.folder, ref.uidvalidity)
        groups[key].append(ref.uid)
    return groups


async def batch_set_flags(
    ctx: "Context",
    ids: list[str],
    add: list[str],
    remove: list[str],
    account: Optional[str] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Add/remove flags on a list of messages. Uses UID STORE sets where possible."""
    resolved_account = account or parse_ref(ids[0]).account
    _check_confirm(ids, ctx, resolved_account, confirm)

    if dry_run:
        return {"success": True, "count": len(ids), "dry_run": True}

    groups = _group_by_folder(ids)
    for (acc_name, folder, _uidvalidity), uids in groups.items():
        target = account or acc_name
        with ctx.pool.acquire(target, folder, readonly=False) as conn:
            if add:
                conn.client.add_flags(uids, add)
            if remove:
                conn.client.remove_flags(uids, remove)

    ctx.audit.log(resolved_account, "batch_set_flags", {"count": len(ids)}, "ok")
    return {"success": True, "count": len(ids), "dry_run": False}


async def batch_move(
    ctx: "Context",
    ids: list[str],
    to_folder: str,
    account: Optional[str] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Move a list of messages to a target folder."""
    resolved_account = account or parse_ref(ids[0]).account
    _check_confirm(ids, ctx, resolved_account, confirm)

    if dry_run:
        return {"success": True, "count": len(ids), "dry_run": True, "to_folder": to_folder}

    groups = _group_by_folder(ids)
    for (acc_name, folder, _uidvalidity), uids in groups.items():
        target = account or acc_name
        with ctx.pool.acquire(target, folder, readonly=False) as conn:
            conn.client.copy(uids, to_folder)
            conn.client.add_flags(uids, ["\\Deleted"])
            conn.client.expunge()

    ctx.audit.log(
        resolved_account, "batch_move",
        {"count": len(ids), "to_folder": to_folder}, "ok",
    )
    return {"success": True, "count": len(ids), "dry_run": False, "to_folder": to_folder}


async def batch_delete(
    ctx: "Context",
    ids: list[str],
    hard: bool = False,
    account: Optional[str] = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Delete a list of messages (soft → Trash, or hard if permitted)."""
    resolved_account = account or parse_ref(ids[0]).account
    _check_confirm(ids, ctx, resolved_account, confirm)

    if dry_run:
        return {"success": True, "count": len(ids), "dry_run": True}

    if hard:
        groups = _group_by_folder(ids)
        for (acc_name, folder, _uidvalidity), uids in groups.items():
            target = account or acc_name
            with ctx.pool.acquire(target, folder, readonly=False) as conn:
                conn.client.add_flags(uids, ["\\Deleted"])
                conn.client.expunge()
    else:
        _, acc_config = ctx.registry.resolve(resolved_account)
        trash_folder = acc_config.folders.trash
        await batch_move(
            ctx,
            ids=ids,
            to_folder=trash_folder,
            account=account,
            confirm=confirm,
        )
        ctx.audit.log(
            resolved_account, "batch_delete",
            {"count": len(ids), "hard": False}, "ok",
        )
        return {"success": True, "count": len(ids), "dry_run": False}

    ctx.audit.log(
        resolved_account, "batch_delete",
        {"count": len(ids), "hard": hard}, "ok",
    )
    return {"success": True, "count": len(ids), "dry_run": False}
