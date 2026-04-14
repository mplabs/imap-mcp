"""Folder management tools."""

from __future__ import annotations

from typing import Optional

from ..audit import AuditLog
from ..errors import PermissionDeniedError
from ..imap_pool import ImapPool

# IMAP SPECIAL-USE flags (RFC 6154) and well-known folder names that are
# protected by default.
_SPECIAL_USE_FLAGS = frozenset({
    b"\\Inbox", b"\\Sent", b"\\Drafts", b"\\Trash", b"\\Junk", b"\\Archive",
    "\\Inbox", "\\Sent", "\\Drafts", "\\Trash", "\\Junk", "\\Archive",
})

_PROTECTED_NAMES = frozenset({"INBOX"})


async def list_folders(
    pool: ImapPool,
    account: Optional[str] = None,
) -> dict:
    """List all folders on the IMAP server."""
    with pool.acquire(account, "INBOX") as client:
        raw_folders = client.list_folders()

    folders = []
    for flags, delimiter, name in raw_folders:
        flag_strs = [f.decode() if isinstance(f, bytes) else f for f in flags]
        delim_str = delimiter.decode() if isinstance(delimiter, bytes) else delimiter
        folders.append({
            "name": name,
            "flags": flag_strs,
            "delimiter": delim_str,
        })

    return {"folders": folders}


async def folder_status(
    pool: ImapPool,
    name: str,
    account: Optional[str] = None,
) -> dict:
    """Return message counts and quota info for a folder."""
    with pool.acquire(account, name) as client:
        status = client.folder_status(name, ["MESSAGES", "UNSEEN", "RECENT"])

    return {
        "name": name,
        "exists": status.get(b"MESSAGES", 0),
        "unseen": status.get(b"UNSEEN", 0),
        "recent": status.get(b"RECENT", 0),
    }


async def create_folder(
    pool: ImapPool,
    name: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Create a new folder."""
    with pool.acquire(account, "INBOX") as client:
        client.create_folder(name)

    if audit:
        audit.log(account or "default", "create_folder", {"name": name}, "ok")

    return {"success": True, "name": name}


async def rename_folder(
    pool: ImapPool,
    from_name: str,
    to_name: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Rename a folder."""
    with pool.acquire(account, "INBOX") as client:
        client.rename_folder(from_name, to_name)

    if audit:
        audit.log(account or "default", "rename_folder", {"from": from_name, "to": to_name}, "ok")

    return {"success": True, "from_name": from_name, "to_name": to_name}


async def delete_folder(
    pool: ImapPool,
    name: str,
    account: Optional[str] = None,
    force: bool = False,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Delete a folder. Refuses to delete special-use folders unless force=True."""
    if not force and name in _PROTECTED_NAMES:
        raise PermissionDeniedError(
            f"Cannot delete protected folder '{name}'. Pass force=True to override."
        )

    with pool.acquire(account, "INBOX") as client:
        if not force:
            # Check IMAP flags for SPECIAL-USE markers
            raw_folders = client.list_folders()
            for flags, _, folder_name in raw_folders:
                if folder_name == name:
                    flag_set = set(f.decode() if isinstance(f, bytes) else f for f in flags)
                    if flag_set & {f for f in _SPECIAL_USE_FLAGS if isinstance(f, str)}:
                        raise PermissionDeniedError(
                            f"Cannot delete special-use folder '{name}'. Pass force=True to override."
                        )
                    break

        client.delete_folder(name)

    if audit:
        audit.log(account or "default", "delete_folder", {"name": name, "force": force}, "ok")

    return {"success": True, "name": name}


async def get_or_create_folder(
    pool: ImapPool,
    name: str,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Return a folder, creating it if it does not exist."""
    with pool.acquire(account, "INBOX") as client:
        raw_folders = client.list_folders()
        existing_names = {folder_name for _, _, folder_name in raw_folders}

        if name in existing_names:
            return {"name": name, "created": False}

        client.create_folder(name)

    if audit:
        audit.log(account or "default", "get_or_create_folder", {"name": name}, "created")

    return {"name": name, "created": True}


async def subscribe_folder(*args, **kwargs):
    raise NotImplementedError("subscribe_folder — M2")


async def unsubscribe_folder(*args, **kwargs):
    raise NotImplementedError("unsubscribe_folder — M2")
