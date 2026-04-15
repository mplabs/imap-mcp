"""Message reading, searching, listing, and attachment download tools."""

from __future__ import annotations

import email as emaillib
from email.header import decode_header, make_header
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ..errors import MessageNotFoundError, StaleRefError, PermissionDeniedError
from ..ref import Ref, encode_ref, parse_ref  # noqa: F401 (parse_ref used in fan-out)

if TYPE_CHECKING:
    from ..context import Context


# ---------------------------------------------------------------------------
# MIME parsing helpers
# ---------------------------------------------------------------------------

def _decode_header(value: str) -> str:
    if not value:
        return ""
    return str(make_header(decode_header(value)))


def _get_text_body(msg: emaillib.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return ""


def _get_html_body(msg: emaillib.Message) -> Optional[str]:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    return None


def _list_attachments(msg: emaillib.Message) -> list[dict]:
    attachments = []
    if not msg.is_multipart():
        return attachments
    for i, part in enumerate(msg.walk()):
        disposition = part.get("Content-Disposition", "")
        if "attachment" in disposition or "inline" in disposition:
            filename = part.get_filename() or ""
            attachments.append({
                "part_id": str(i),
                "filename": _decode_header(filename),
                "mime": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b""),
            })
    return attachments


def _parse_message(
    uid: int,
    data: dict,
    account: str,
    folder: str,
    uidvalidity: int,
) -> dict:
    raw = data.get(b"RFC822", b"")
    msg = emaillib.message_from_bytes(raw)
    flags = [f.decode() if isinstance(f, bytes) else f for f in data.get(b"FLAGS", [])]
    size = data.get(b"RFC822.SIZE", 0)
    body_text = _get_text_body(msg)
    snippet = body_text[:200].replace("\n", " ").replace("\r", "")
    ref_str = encode_ref(Ref(account=account, folder=folder, uidvalidity=uidvalidity, uid=uid))
    message_id = msg.get("Message-ID", "")
    return {
        "ref": ref_str,
        "message_id": message_id,
        "folder": folder,
        "from": _decode_header(msg.get("From", "")),
        "to": _decode_header(msg.get("To", "")),
        "subject": _decode_header(msg.get("Subject", "")),
        "date": msg.get("Date", ""),
        "flags": flags,
        "size": size,
        "snippet": snippet,
    }


def _decode_cursor(cursor: Optional[str]) -> Optional[int]:
    """Decode an opaque UID cursor string → UID integer."""
    if not cursor:
        return None
    if cursor.startswith("uid:"):
        try:
            return int(cursor[4:])
        except ValueError:
            return None
    return None


def _encode_cursor(uid: int) -> str:
    return f"uid:{uid}"


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

async def list_messages(
    ctx: "Context",
    folder: str = "INBOX",
    limit: int = 50,
    cursor: Optional[str] = None,
    order: str = "newest",
    account: Optional[str] = None,
) -> dict:
    """List messages in a folder with UID-based pagination."""
    limit = min(limit, 500)
    with ctx.pool.acquire(account, folder) as conn:
        uids = conn.client.search(["ALL"])

        if order == "newest":
            uids = sorted(uids, reverse=True)
        else:
            uids = sorted(uids)

        # UID-based cursor filtering
        cursor_uid = _decode_cursor(cursor)
        if cursor_uid is not None:
            if order == "newest":
                uids = [u for u in uids if u < cursor_uid]
            else:
                uids = [u for u in uids if u > cursor_uid]

        page_uids = uids[:limit]

        if not page_uids:
            return {"results": [], "next_cursor": None}

        fetch_data = conn.client.fetch(page_uids, ["FLAGS", "RFC822", "RFC822.SIZE"])
        results = [
            _parse_message(uid, fetch_data[uid], conn.account_name, folder, conn.uidvalidity)
            for uid in page_uids
            if uid in fetch_data
        ]

    ctx.resolver.register_many(results)

    next_cursor = _encode_cursor(page_uids[-1]) if len(uids) > limit else None
    return {"results": results, "next_cursor": next_cursor}


async def search_emails(
    ctx: "Context",
    query: dict,
    folder: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    order: str = "newest",
    account: Optional[str] = None,
) -> dict:
    """Search messages using a raw IMAP SEARCH string or gmail_raw.

    When folder is None, fans out across subscribed folders (capped at
    resolver.max_search_folders). Results are merged and re-sorted.
    """
    limit = min(limit, 500)

    if "raw" in query:
        criteria = [query["raw"]]
    elif "gmail_raw" in query:
        criteria = [f"X-GM-RAW {query['gmail_raw']}"]
    else:
        criteria = ["ALL"]

    if folder is not None:
        return await _search_single_folder(
            ctx, criteria, folder, limit, cursor, order, account
        )

    # Fan-out: collect selectable folders up to the resolver cap
    _, default_acc = ctx.registry.resolve(account)
    max_folders = default_acc.resolver.max_search_folders

    with ctx.pool.acquire(account, "INBOX") as conn:
        all_folders = conn.client.list_folders()

    selectable = [
        name for flags, _, name in all_folders
        if "\\Noselect" not in {
            f.decode() if isinstance(f, bytes) else f for f in flags
        }
    ][:max_folders]

    all_results: list[dict] = []
    for folder_name in selectable:
        try:
            res = await _search_single_folder(
                ctx, criteria, folder_name, limit, None, order, account
            )
            all_results.extend(res["results"])
        except Exception:
            continue

    if not all_results:
        return {"results": [], "next_cursor": None}

    # Re-sort merged results and apply cursor + limit
    reverse = (order == "newest")
    all_results.sort(key=lambda r: parse_ref(r["ref"]).uid, reverse=reverse)

    cursor_uid = _decode_cursor(cursor)
    if cursor_uid is not None:
        if order == "newest":
            all_results = [r for r in all_results if parse_ref(r["ref"]).uid < cursor_uid]
        else:
            all_results = [r for r in all_results if parse_ref(r["ref"]).uid > cursor_uid]

    page = all_results[:limit]
    next_cursor = _encode_cursor(parse_ref(page[-1]["ref"]).uid) if len(all_results) > limit else None
    return {"results": page, "next_cursor": next_cursor}


async def _search_single_folder(
    ctx: "Context",
    criteria: list,
    folder: str,
    limit: int,
    cursor: Optional[str],
    order: str,
    account: Optional[str],
) -> dict:
    """Search within a single folder and return paged results."""
    with ctx.pool.acquire(account, folder) as conn:
        uids = conn.client.search(criteria)

        if order == "newest":
            uids = sorted(uids, reverse=True)
        else:
            uids = sorted(uids)

        cursor_uid = _decode_cursor(cursor)
        if cursor_uid is not None:
            if order == "newest":
                uids = [u for u in uids if u < cursor_uid]
            else:
                uids = [u for u in uids if u > cursor_uid]

        page_uids = uids[:limit]

        if not page_uids:
            return {"results": [], "next_cursor": None}

        fetch_data = conn.client.fetch(page_uids, ["FLAGS", "RFC822", "RFC822.SIZE"])
        results = [
            _parse_message(uid, fetch_data[uid], conn.account_name, folder, conn.uidvalidity)
            for uid in page_uids
            if uid in fetch_data
        ]

    ctx.resolver.register_many(results)

    next_cursor = _encode_cursor(page_uids[-1]) if len(uids) > limit else None
    return {"results": results, "next_cursor": next_cursor}


async def read_email(
    ctx: "Context",
    id: str,
    include_raw: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Fetch full message content by ref or message_id."""
    ref = ctx.resolver.resolve(id, ctx.pool, account)

    with ctx.pool.acquire(account or ref.account, ref.folder) as conn:
        if conn.uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        fetch_data = conn.client.fetch([ref.uid], ["FLAGS", "RFC822", "RFC822.SIZE"])
        if ref.uid not in fetch_data:
            raise MessageNotFoundError(id)

        data = fetch_data[ref.uid]
        raw = data.get(b"RFC822", b"")
        msg = emaillib.message_from_bytes(raw)

        flags = [f.decode() if isinstance(f, bytes) else f for f in data.get(b"FLAGS", [])]
        body_text = _get_text_body(msg)
        body_html = _get_html_body(msg)
        attachments = _list_attachments(msg)

        message_id = msg.get("Message-ID", "")
        result = {
            "ref": encode_ref(ref),
            "message_id": message_id,
            "folder": ref.folder,
            "from": _decode_header(msg.get("From", "")),
            "to": _decode_header(msg.get("To", "")),
            "cc": _decode_header(msg.get("Cc", "")),
            "bcc": _decode_header(msg.get("Bcc", "")),
            "subject": _decode_header(msg.get("Subject", "")),
            "date": msg.get("Date", ""),
            "flags": flags,
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
            "size": data.get(b"RFC822.SIZE", 0),
        }
        if include_raw:
            result["raw"] = raw.decode("utf-8", errors="replace")

    if message_id:
        ctx.resolver.register(message_id, ref.folder, ref.uid, ref.uidvalidity)

    return result


async def download_attachment(
    ctx: "Context",
    id: str,
    part_id: str,
    save_to: str,
    account: Optional[str] = None,
) -> dict:
    """Download an attachment MIME part to disk.

    Validates that save_to is an absolute path and that the attachment
    does not exceed attachment.max_size_mb.
    """
    save_path = Path(save_to)
    if not save_path.is_absolute():
        raise PermissionDeniedError(f"save_to must be an absolute path, got: {save_to}")

    ref = ctx.resolver.resolve(id, ctx.pool, account)
    _, acc_config = ctx.registry.resolve(account or ref.account)
    max_bytes = acc_config.attachment.max_size_mb * 1024 * 1024

    with ctx.pool.acquire(account or ref.account, ref.folder) as conn:
        if conn.uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        # Fetch the full message to walk MIME parts
        fetch_data = conn.client.fetch([ref.uid], ["RFC822"])
        if ref.uid not in fetch_data:
            raise MessageNotFoundError(id)

        raw = fetch_data[ref.uid].get(b"RFC822", b"")
        msg = emaillib.message_from_bytes(raw)

        # Find the requested part by index
        target_part = None
        for i, part in enumerate(msg.walk()):
            if str(i) == part_id:
                target_part = part
                break

        if target_part is None:
            raise MessageNotFoundError(f"Part {part_id} not found in message {id}")

        payload = target_part.get_payload(decode=True) or b""
        if len(payload) > max_bytes:
            raise PermissionDeniedError(
                f"Attachment size {len(payload)} bytes exceeds limit of "
                f"{acc_config.attachment.max_size_mb} MB"
            )

        filename = target_part.get_filename() or f"attachment_{part_id}"
        # Resolve {filename} token
        final_path = Path(str(save_path).replace("{filename}", filename))

        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(payload)

    ctx.audit.log(
        ref.account, "download_attachment",
        {"id": id, "part_id": part_id, "save_to": str(final_path)}, "ok"
    )
    return {"success": True, "path": str(final_path), "size": len(payload)}
