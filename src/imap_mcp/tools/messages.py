"""Message reading, searching, and listing tools."""

from __future__ import annotations

import email as emaillib
from email.header import decode_header, make_header
from typing import Optional, Union

from ..errors import MessageNotFoundError, StaleRefError
from ..imap_pool import ImapPool
from ..ref import Ref, encode_ref, is_ref, is_message_id, parse_ref


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_header(value: str) -> str:
    if not value:
        return ""
    return str(make_header(decode_header(value)))


def _get_text_body(msg: emaillib.Message) -> str:
    """Extract the plain-text body from a (possibly multipart) message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                if payload:
                    return payload.decode(charset, errors="replace")
        return ""
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        if payload:
            return payload.decode(charset, errors="replace")
        return ""


def _get_html_body(msg: emaillib.Message) -> Optional[str]:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                if payload:
                    return payload.decode(charset, errors="replace")
    return None


def _list_attachments(msg: emaillib.Message) -> list[dict]:
    attachments = []
    if msg.is_multipart():
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
    """Parse an imapclient fetch result into a MessageSummary dict."""
    raw = data.get(b"RFC822", b"")
    msg = emaillib.message_from_bytes(raw)

    flags = [f.decode() if isinstance(f, bytes) else f for f in data.get(b"FLAGS", [])]
    size = data.get(b"RFC822.SIZE", 0)

    body_text = _get_text_body(msg)
    snippet = body_text[:200].replace("\n", " ").replace("\r", "")

    ref = encode_ref(Ref(account=account, folder=folder, uidvalidity=uidvalidity, uid=uid))
    message_id = msg.get("Message-ID", "")

    return {
        "ref": ref,
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


def _build_imap_search_criteria(structured: dict) -> list:
    """Convert a structured query dict to an IMAP SEARCH criteria list."""
    criteria = []

    if structured.get("unseen"):
        criteria.append("UNSEEN")
    if structured.get("flagged"):
        criteria.append("FLAGGED")
    if structured.get("from"):
        criteria.extend(["FROM", structured["from"]])
    if structured.get("to"):
        criteria.extend(["TO", structured["to"]])
    if structured.get("subject"):
        criteria.extend(["SUBJECT", structured["subject"]])
    if structured.get("body"):
        criteria.extend(["BODY", structured["body"]])
    if structured.get("since"):
        criteria.extend(["SINCE", structured["since"]])
    if structured.get("before"):
        criteria.extend(["BEFORE", structured["before"]])
    if structured.get("keyword"):
        criteria.extend(["KEYWORD", structured["keyword"]])
    if structured.get("not_keyword"):
        criteria.extend(["UNKEYWORD", structured["not_keyword"]])
    if structured.get("size_gt"):
        criteria.extend(["LARGER", str(structured["size_gt"])])
    if structured.get("size_lt"):
        criteria.extend(["SMALLER", str(structured["size_lt"])])

    if not criteria:
        criteria = ["ALL"]

    return criteria


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

async def list_messages(
    pool: ImapPool,
    account: Optional[str] = None,
    folder: str = "INBOX",
    limit: int = 50,
    cursor: Optional[str] = None,
    order: str = "newest",
) -> dict:
    """List messages in a folder.  Returns MessageSummary list + pagination."""
    with pool.acquire(account, folder) as client:
        folder_info = client.select_folder(folder, readonly=True)
        uidvalidity = int(folder_info.get(b"UIDVALIDITY", 0))

        uids = client.search(["ALL"])

        if order == "newest":
            uids = sorted(uids, reverse=True)
        else:
            uids = sorted(uids)

        # Apply cursor (simple offset-based for now)
        offset = 0
        if cursor:
            try:
                offset = int(cursor)
            except ValueError:
                offset = 0

        page_uids = uids[offset : offset + limit]

        if not page_uids:
            return {"results": [], "next_cursor": None}

        fetch_data = client.fetch(page_uids, ["FLAGS", "RFC822", "RFC822.SIZE"])

        name, _ = pool._registry.resolve(account)
        results = [
            _parse_message(uid, fetch_data[uid], name, folder, uidvalidity)
            for uid in page_uids
            if uid in fetch_data
        ]

        next_cursor = str(offset + limit) if offset + limit < len(uids) else None
        return {"results": results, "next_cursor": next_cursor}


async def search_emails(
    pool: ImapPool,
    query: dict,
    account: Optional[str] = None,
    folder: str = "INBOX",
    limit: int = 50,
    cursor: Optional[str] = None,
    order: str = "newest",
) -> dict:
    """Search messages using raw IMAP, structured criteria, or gmail_raw."""
    with pool.acquire(account, folder) as client:
        folder_info = client.select_folder(folder, readonly=True)
        uidvalidity = int(folder_info.get(b"UIDVALIDITY", 0))

        if "raw" in query:
            criteria = [query["raw"]]
        elif "structured" in query:
            criteria = _build_imap_search_criteria(query["structured"])
        elif "gmail_raw" in query:
            # X-GM-RAW extension — passed through verbatim
            criteria = [f"X-GM-RAW {query['gmail_raw']}"]
        else:
            criteria = ["ALL"]

        uids = client.search(criteria)

        if order == "newest":
            uids = sorted(uids, reverse=True)
        else:
            uids = sorted(uids)

        offset = 0
        if cursor:
            try:
                offset = int(cursor)
            except ValueError:
                offset = 0

        page_uids = uids[offset : offset + limit]

        if not page_uids:
            return {"results": [], "next_cursor": None}

        fetch_data = client.fetch(page_uids, ["FLAGS", "RFC822", "RFC822.SIZE"])

        name, _ = pool._registry.resolve(account)
        results = [
            _parse_message(uid, fetch_data[uid], name, folder, uidvalidity)
            for uid in page_uids
            if uid in fetch_data
        ]

        next_cursor = str(offset + limit) if offset + limit < len(uids) else None
        return {"results": results, "next_cursor": next_cursor}


async def read_email(
    pool: ImapPool,
    id: str,
    account: Optional[str] = None,
    include_raw: bool = False,
) -> dict:
    """Fetch full message details by ref or message_id."""
    ref = parse_ref(id)

    with pool.acquire(account or ref.account, ref.folder) as client:
        folder_info = client.select_folder(ref.folder, readonly=True)
        server_uidvalidity = int(folder_info.get(b"UIDVALIDITY", 0))

        if server_uidvalidity != ref.uidvalidity:
            raise StaleRefError(ref.folder)

        fetch_data = client.fetch([ref.uid], ["FLAGS", "RFC822", "RFC822.SIZE"])

        if ref.uid not in fetch_data:
            raise MessageNotFoundError(id)

        data = fetch_data[ref.uid]
        raw = data.get(b"RFC822", b"")
        msg = emaillib.message_from_bytes(raw)

        flags = [f.decode() if isinstance(f, bytes) else f for f in data.get(b"FLAGS", [])]
        body_text = _get_text_body(msg)
        body_html = _get_html_body(msg)
        attachments = _list_attachments(msg)

        name, _ = pool._registry.resolve(account)
        result = {
            "ref": encode_ref(ref),
            "message_id": msg.get("Message-ID", ""),
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

        return result


async def download_attachment(*args, **kwargs):
    raise NotImplementedError("download_attachment — M1 (requires part fetching)")
