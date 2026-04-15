"""Outbound mail tools: send_email, save_draft."""

from __future__ import annotations

import mimetypes
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import aiosmtplib

from ..config import resolve_secret
from ..errors import PermissionDeniedError
from ..ref import Ref, encode_ref

if TYPE_CHECKING:
    from ..context import Context


# ---------------------------------------------------------------------------
# MIME building
# ---------------------------------------------------------------------------

def _build_mime(
    from_addr: str,
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    html: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    headers: Optional[dict] = None,
):
    """Build a MIME message with required Message-ID and Date headers.

    attachments is a list of dicts: { path: str, filename?: str, mime?: str }
    """
    has_attachments = bool(attachments)

    if has_attachments:
        # multipart/mixed envelope; body goes in a nested alternative or plain part
        outer = MIMEMultipart("mixed")
        if html:
            body_part = MIMEMultipart("alternative")
            body_part.attach(MIMEText(body, "plain", "utf-8"))
            body_part.attach(MIMEText(html, "html", "utf-8"))
        else:
            body_part = MIMEText(body, "plain", "utf-8")
        outer.attach(body_part)
        for att in attachments:
            _attach_file(outer, att)
        msg = outer
    elif html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")

    msg["Message-ID"] = make_msgid()
    msg["Date"] = formatdate(localtime=False)
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = f"{references} {in_reply_to}"
        else:
            msg["References"] = in_reply_to

    if headers:
        for k, v in headers.items():
            msg[k] = v

    return msg


def _attach_file(outer: MIMEMultipart, att: dict) -> None:
    """Read a file from disk and attach it to the outer MIME message."""
    path = Path(att["path"])
    if not path.is_absolute():
        raise PermissionDeniedError(f"attachment path must be absolute, got: {att['path']}")
    filename = att.get("filename") or path.name
    mime_type = att.get("mime") or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    maintype, subtype = mime_type.split("/", 1)

    data = path.read_bytes()
    if maintype == "application":
        part = MIMEApplication(data, Name=filename)
    else:
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        from email import encoders
        encoders.encode_base64(part)

    part["Content-Disposition"] = f'attachment; filename="{filename}"'
    outer.attach(part)


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

async def send_email(
    ctx: "Context",
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    html: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    headers: Optional[dict] = None,
    account: Optional[str] = None,
) -> dict:
    """Build a MIME message, send via SMTP, and APPEND a copy to Sent."""
    name, acc = ctx.registry.resolve(account)
    from_addr = acc.identity.from_addr
    sent_folder = acc.folders.sent

    msg = _build_mime(
        from_addr=from_addr,
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        html=html,
        attachments=attachments,
        in_reply_to=in_reply_to,
        references=references,
        headers=headers,
    )
    message_id = msg["Message-ID"]

    smtp_password = resolve_secret(acc.smtp.auth.secret_ref)

    await aiosmtplib.send(
        msg,
        hostname=acc.smtp.host,
        port=acc.smtp.port,
        username=acc.smtp.username,
        password=smtp_password,
        use_tls=acc.smtp.tls,
        start_tls=acc.smtp.starttls,
    )

    raw_bytes = msg.as_bytes()
    with ctx.pool.acquire(name, sent_folder, readonly=False) as conn:
        conn.client.append(sent_folder, raw_bytes, flags=["\\Seen"])

    ctx.audit.log(name, "send_email", {"to": to, "subject": subject}, "ok")
    return {"success": True, "account": name, "message_id": message_id}


async def save_draft(
    ctx: "Context",
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    html: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    headers: Optional[dict] = None,
    account: Optional[str] = None,
) -> dict:
    """Build a MIME message and APPEND it to the Drafts folder with \\Draft flag."""
    name, acc = ctx.registry.resolve(account)
    from_addr = acc.identity.from_addr
    drafts_folder = acc.folders.drafts

    msg = _build_mime(
        from_addr=from_addr,
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        html=html,
        attachments=attachments,
        in_reply_to=in_reply_to,
        references=references,
        headers=headers,
    )
    message_id = msg["Message-ID"]
    raw_bytes = msg.as_bytes()

    ref_str = None
    with ctx.pool.acquire(name, drafts_folder, readonly=False) as conn:
        conn.client.append(drafts_folder, raw_bytes, flags=["\\Draft"])
        # Search for the newly appended message to get its UID
        uids = conn.client.search(["HEADER", "Message-ID", message_id])
        if uids:
            uid = uids[-1]
            ref = Ref(
                account=name,
                folder=drafts_folder,
                uidvalidity=conn.uidvalidity,
                uid=uid,
            )
            ref_str = encode_ref(ref)
            ctx.resolver.register(message_id, drafts_folder, uid, conn.uidvalidity)

    ctx.audit.log(name, "save_draft", {"to": to, "subject": subject}, "ok")
    return {
        "success": True,
        "account": name,
        "folder": drafts_folder,
        "message_id": message_id,
        "ref": ref_str,
    }
