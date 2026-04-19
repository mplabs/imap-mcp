"""Folder management tools."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from ..errors import PermissionDeniedError

if TYPE_CHECKING:
    from ..context import Context

# IMAP SPECIAL-USE flags (RFC 6154) — normalised to str for set membership.
_SPECIAL_USE_FLAGS = frozenset({
    "\\Inbox", "\\Sent", "\\Drafts", "\\Trash", "\\Junk", "\\Archive",
})

_PROTECTED_NAMES = frozenset({"INBOX"})


async def list_folders(
    ctx: "Context",
    account: Optional[str] = None,
) -> dict:
    """List all folders on the IMAP server, including subscribed state."""
    with ctx.pool.acquire(account, "INBOX") as conn:
        raw_folders = conn.client.list_folders()
        try:
            # lsub() returns the set of subscribed folders (IMAP4rev1).
            # Some servers (e.g. Exchange, Fastmail) don't implement LSUB;
            # fall back to treating every folder as subscribed.
            subscribed_raw = conn.client.lsub()
            subscribed_names = {name for _, _, name in subscribed_raw}
        except Exception:
            subscribed_names = {name for _, _, name in raw_folders}

    folders = []
    for flags, delimiter, name in raw_folders:
        flag_strs = [f.decode() if isinstance(f, bytes) else f for f in flags]
        delim_str = delimiter.decode() if isinstance(delimiter, bytes) else delimiter
        folders.append({
            "name": name,
            "flags": flag_strs,
            "delimiter": delim_str,
            "subscribed": name in subscribed_names,
        })

    return {"folders": folders}


async def folder_status(
    ctx: "Context",
    name: str,
    account: Optional[str] = None,
) -> dict:
    """Return message counts and quota info for a folder."""
    with ctx.pool.acquire(account, name) as conn:
        status = conn.client.folder_status(name, ["MESSAGES", "UNSEEN", "RECENT"])

    return {
        "name": name,
        "exists": status.get(b"MESSAGES", 0),
        "unseen": status.get(b"UNSEEN", 0),
        "recent": status.get(b"RECENT", 0),
    }


async def create_folder(
    ctx: "Context",
    name: str,
    account: Optional[str] = None,
) -> dict:
    """Create a new folder."""
    with ctx.pool.acquire(account, "INBOX") as conn:
        conn.client.create_folder(name)

    ctx.audit.log(account or "default", "create_folder", {"name": name}, "ok")
    return {"success": True, "name": name}


async def rename_folder(
    ctx: "Context",
    from_name: str,
    to_name: str,
    account: Optional[str] = None,
) -> dict:
    """Rename a folder."""
    with ctx.pool.acquire(account, "INBOX") as conn:
        conn.client.rename_folder(from_name, to_name)

    ctx.audit.log(
        account or "default", "rename_folder",
        {"from": from_name, "to": to_name}, "ok",
    )
    return {"success": True, "from_name": from_name, "to_name": to_name}


async def delete_folder(
    ctx: "Context",
    name: str,
    account: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Delete a folder. Refuses to delete special-use folders unless force=True."""
    if not force and name in _PROTECTED_NAMES:
        raise PermissionDeniedError(
            f"Cannot delete protected folder '{name}'. Pass force=True to override."
        )

    with ctx.pool.acquire(account, "INBOX") as conn:
        if not force:
            raw_folders = conn.client.list_folders()
            for flags, _, folder_name in raw_folders:
                if folder_name == name:
                    flag_set = {
                        f.decode() if isinstance(f, bytes) else f for f in flags
                    }
                    if flag_set & _SPECIAL_USE_FLAGS:
                        raise PermissionDeniedError(
                            f"Cannot delete special-use folder '{name}'. "
                            "Pass force=True to override."
                        )
                    break

        conn.client.delete_folder(name)

    ctx.audit.log(
        account or "default", "delete_folder",
        {"name": name, "force": force}, "ok",
    )
    return {"success": True, "name": name}


async def get_or_create_folder(
    ctx: "Context",
    name: str,
    account: Optional[str] = None,
) -> dict:
    """Return a folder, creating it if it does not exist."""
    with ctx.pool.acquire(account, "INBOX") as conn:
        raw_folders = conn.client.list_folders()
        existing_names = {folder_name for _, _, folder_name in raw_folders}

        if name in existing_names:
            return {"name": name, "created": False}

        conn.client.create_folder(name)

    ctx.audit.log(account or "default", "get_or_create_folder", {"name": name}, "created")
    return {"name": name, "created": True}


async def subscribe_folder(
    ctx: "Context",
    name: str,
    account: Optional[str] = None,
) -> dict:
    """Subscribe to a folder."""
    with ctx.pool.acquire(account, "INBOX") as conn:
        conn.client.subscribe_folder(name)

    return {"success": True, "name": name}


async def unsubscribe_folder(
    ctx: "Context",
    name: str,
    account: Optional[str] = None,
) -> dict:
    """Unsubscribe from a folder."""
    with ctx.pool.acquire(account, "INBOX") as conn:
        conn.client.unsubscribe_folder(name)

    return {"success": True, "name": name}
