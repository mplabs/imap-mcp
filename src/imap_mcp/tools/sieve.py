"""Sieve/ManageSieve tools (optional — requires managesieve package and sieve: config block)."""

from __future__ import annotations

from typing import Optional

from ..errors import NotConfiguredError

try:
    import managesieve
    _HAS_MANAGESIEVE = True
except ImportError:
    managesieve = None  # type: ignore[assignment]
    _HAS_MANAGESIEVE = False

try:
    from ..config import resolve_secret
except ImportError:
    resolve_secret = None  # type: ignore[assignment]


def _get_sieve_connection(registry, account: Optional[str]):
    """Return a (name, acc, conn) tuple or raise NotConfiguredError."""
    if managesieve is None:
        raise NotConfiguredError("sieve")

    if registry is None:
        raise NotConfiguredError("sieve")

    name, acc = registry.resolve(account)

    if not hasattr(acc, "sieve") or acc.sieve is None:
        raise NotConfiguredError("sieve")

    password = resolve_secret(acc.sieve.auth.secret_ref)
    conn = managesieve.MANAGESIEVE(acc.sieve.host, acc.sieve.port)
    conn.login("PLAIN", acc.sieve.username, password)
    return name, acc, conn


async def list_sieve_scripts(
    registry=None,
    account: Optional[str] = None,
) -> dict:
    """List all Sieve scripts on the server."""
    _name, _acc, conn = _get_sieve_connection(registry, account)
    scripts, active = conn.listscripts()
    return {"scripts": scripts, "active": active}


async def get_sieve_script(
    registry=None,
    name: str = "",
    account: Optional[str] = None,
) -> dict:
    """Fetch the content of a named Sieve script."""
    _name, _acc, conn = _get_sieve_connection(registry, account)
    script = conn.getscript(name)
    return {"name": name, "script": script}


async def put_sieve_script(
    registry=None,
    name: str = "",
    script: str = "",
    account: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Create or update a Sieve script. Validates via CHECKSCRIPT first."""
    _name, _acc, conn = _get_sieve_connection(registry, account)

    ok, err = conn.checkscript(script)
    if not ok:
        return {"success": False, "error": err}

    if dry_run:
        return {"success": True, "dry_run": True}

    conn.putscript(name, script)
    return {"success": True, "name": name}


async def activate_sieve_script(
    registry=None,
    name: str = "",
    account: Optional[str] = None,
) -> dict:
    """Set a script as the active one (at most one active at a time)."""
    _name, _acc, conn = _get_sieve_connection(registry, account)
    conn.setactive(name)
    return {"success": True, "active": name}


async def delete_sieve_script(
    registry=None,
    name: str = "",
    account: Optional[str] = None,
) -> dict:
    """Delete a named Sieve script."""
    _name, _acc, conn = _get_sieve_connection(registry, account)
    conn.deletescript(name)
    return {"success": True, "name": name}
