"""Admin tools: list_accounts, test_connection."""

from __future__ import annotations

from typing import Optional

import aiosmtplib
from imapclient import IMAPClient

from ..accounts import AccountRegistry
from ..config import resolve_secret


def list_accounts(registry: AccountRegistry) -> dict:
    """Return a summary of all configured accounts (no secrets)."""
    accounts_info = []
    for name in registry.list_names():
        acc = registry.get(name)
        accounts_info.append({
            "name": name,
            "imap_host": acc.imap.host,
            "imap_port": acc.imap.port,
            "smtp_host": acc.smtp.host,
            "smtp_port": acc.smtp.port,
            "identity_from": acc.identity.from_addr,
            "auth_method": acc.imap.auth.method,
        })
    return {
        "default_account": registry.default_name,
        "accounts": accounts_info,
    }


async def test_connection(registry: AccountRegistry, account: Optional[str] = None) -> dict:
    """Verify IMAP and SMTP connectivity independently.

    Returns:
        {
            "success": bool,       # True only when both IMAP and SMTP are ok
            "account": str,
            "imap": "ok" | "<error message>",
            "smtp": "ok" | "<error message>",
        }
    """
    name, acc = registry.resolve(account)

    # --- IMAP ---
    try:
        password = resolve_secret(acc.imap.auth.secret_ref)
        with IMAPClient(
            host=acc.imap.host,
            port=acc.imap.port,
            ssl=acc.imap.tls,
        ) as client:
            client.login(acc.imap.username, password)
            client.noop()
        imap_result = "ok"
    except Exception as exc:
        imap_result = str(exc)

    # --- SMTP ---
    try:
        smtp_password = resolve_secret(acc.smtp.auth.secret_ref)
        smtp = aiosmtplib.SMTP(
            hostname=acc.smtp.host,
            port=acc.smtp.port,
            use_tls=acc.smtp.tls,
            start_tls=acc.smtp.starttls,
        )
        await smtp.connect()
        await smtp.login(acc.smtp.username, smtp_password)
        await smtp.quit()
        smtp_result = "ok"
    except Exception as exc:
        smtp_result = str(exc)

    success = imap_result == "ok" and smtp_result == "ok"
    return {
        "success": success,
        "account": name,
        "imap": imap_result,
        "smtp": smtp_result,
    }
