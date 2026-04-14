"""Folder management tools."""

from __future__ import annotations

from typing import Optional

from ..imap_pool import ImapPool


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


async def create_folder(*args, **kwargs):
    raise NotImplementedError("create_folder — M2")


async def rename_folder(*args, **kwargs):
    raise NotImplementedError("rename_folder — M2")


async def delete_folder(*args, **kwargs):
    raise NotImplementedError("delete_folder — M2")


async def get_or_create_folder(*args, **kwargs):
    raise NotImplementedError("get_or_create_folder — M4")


async def subscribe_folder(*args, **kwargs):
    raise NotImplementedError("subscribe_folder — M2")


async def unsubscribe_folder(*args, **kwargs):
    raise NotImplementedError("unsubscribe_folder — M2")
