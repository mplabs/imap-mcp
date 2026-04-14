"""Outbound mail tools: send_email, save_draft."""

from __future__ import annotations

import email.policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from ..accounts import AccountRegistry
from ..audit import AuditLog
from ..config import resolve_secret
from ..imap_pool import ImapPool


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
    in_reply_to: Optional[str] = None,
    headers: Optional[dict] = None,
) -> MIMEMultipart:
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))

    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    if headers:
        for k, v in headers.items():
            msg[k] = v

    return msg


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

async def send_email(
    pool: ImapPool,
    registry: AccountRegistry,
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    html: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    headers: Optional[dict] = None,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Build a MIME message, send via SMTP, and APPEND a copy to Sent."""
    name, acc = registry.resolve(account)
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
        in_reply_to=in_reply_to,
        headers=headers,
    )

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

    # Append to Sent folder with \Seen
    raw_bytes = msg.as_bytes()
    with pool.acquire(name, sent_folder, readonly=False) as client:
        client.append(sent_folder, raw_bytes, flags=["\\Seen"])

    if audit:
        audit.log(name, "send_email", {"to": to, "subject": subject}, "ok")

    return {"success": True, "account": name}


async def save_draft(
    pool: ImapPool,
    registry: AccountRegistry,
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    html: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    headers: Optional[dict] = None,
    account: Optional[str] = None,
    audit: Optional[AuditLog] = None,
) -> dict:
    """Build a MIME message and APPEND it to the Drafts folder with \\Draft flag."""
    name, acc = registry.resolve(account)
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
        in_reply_to=in_reply_to,
        headers=headers,
    )

    raw_bytes = msg.as_bytes()
    with pool.acquire(name, drafts_folder, readonly=False) as client:
        client.append(drafts_folder, raw_bytes, flags=["\\Draft"])

    if audit:
        audit.log(name, "save_draft", {"to": to, "subject": subject}, "ok")

    return {"success": True, "account": name, "folder": drafts_folder}
