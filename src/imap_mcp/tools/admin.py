"""Admin tools: list_accounts, test_connection."""

from __future__ import annotations

from typing import Optional

from imapclient import IMAPClient

from ..accounts import AccountRegistry
from ..config import resolve_secret
from ..errors import AuthFailedError, ConnectionFailedError


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
    """Perform a LOGIN / NOOP / LOGOUT round-trip to verify connectivity.

    Returns a dict with keys: success (bool), account (str), and on failure: error (str).
    """
    name, acc = registry.resolve(account)
    try:
        password = resolve_secret(acc.imap.auth.secret_ref)
        with IMAPClient(
            host=acc.imap.host,
            port=acc.imap.port,
            ssl=acc.imap.tls,
        ) as client:
            client.login(acc.imap.username, password)
            client.noop()
            client.logout()
        return {"success": True, "account": name}
    except Exception as exc:
        return {"success": False, "account": name, "error": str(exc)}
