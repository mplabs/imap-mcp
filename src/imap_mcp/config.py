"""Configuration loading for imap-mcp.

Reads a YAML config file (path from IMAP_MCP_CONFIG env var or
~/.config/imap-mcp/config.yaml) and resolves secrets from the OS keyring
or environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import keyring
import yaml


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------

def resolve_secret(secret_ref: str) -> str:
    """Resolve a secret_ref string to its plain-text value.

    Supported schemes:
      env:<VAR>            — read from environment variable
      keyring:<service>/<username>  — read from OS keyring
      <bare string>        — returned as-is (development convenience)
    """
    if ":" not in secret_ref:
        # Bare string — no scheme; return as-is.
        return secret_ref

    scheme, rest = secret_ref.split(":", 1)

    if scheme == "env":
        value = os.environ.get(rest)
        if value is None:
            raise ValueError(f"Environment variable '{rest}' not set (from secret_ref '{secret_ref}')")
        return value

    if scheme == "keyring":
        if "/" not in rest:
            raise ValueError(f"keyring secret_ref must be '<service>/<username>', got: {rest}")
        service, username = rest.split("/", 1)
        value = keyring.get_password(service, username)
        if value is None:
            raise ValueError(
                f"No keyring entry for service='{service}', username='{username}'"
            )
        return value

    raise ValueError(f"Unsupported secret_ref scheme '{scheme}' in '{secret_ref}'")


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuthConfig:
    method: str  # password | app_password | xoauth2
    secret_ref: str


@dataclass
class ImapConfig:
    host: str
    port: int
    tls: bool
    username: str
    auth: AuthConfig
    starttls: bool = False


@dataclass
class SmtpConfig:
    host: str
    port: int
    tls: bool
    username: str
    auth: AuthConfig
    starttls: bool = False


@dataclass
class IdentityConfig:
    from_addr: str
    reply_to: Optional[str] = None


@dataclass
class FolderMappingConfig:
    inbox: str = "INBOX"
    sent: str = "Sent"
    drafts: str = "Drafts"
    trash: str = "Trash"
    spam: str = "Junk"
    archive: str = "Archive"


@dataclass
class SafetyConfig:
    allow_delete: bool = False
    allow_empty_trash: bool = False
    confirm_batch_threshold: int = 25


@dataclass
class AccountConfig:
    imap: ImapConfig
    smtp: SmtpConfig
    identity: IdentityConfig
    folders: FolderMappingConfig = field(default_factory=FolderMappingConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)


@dataclass
class Config:
    default_account: str
    accounts: dict[str, AccountConfig]


# ---------------------------------------------------------------------------
# YAML → dataclass conversion
# ---------------------------------------------------------------------------

def _parse_auth(d: dict) -> AuthConfig:
    return AuthConfig(
        method=d["method"],
        secret_ref=d["secret_ref"],
    )


def _parse_imap(d: dict) -> ImapConfig:
    return ImapConfig(
        host=d["host"],
        port=int(d["port"]),
        tls=bool(d.get("tls", True)),
        username=d["username"],
        auth=_parse_auth(d["auth"]),
        starttls=bool(d.get("starttls", False)),
    )


def _parse_smtp(d: dict) -> SmtpConfig:
    return SmtpConfig(
        host=d["host"],
        port=int(d["port"]),
        tls=bool(d.get("tls", True)),
        username=d["username"],
        auth=_parse_auth(d["auth"]),
        starttls=bool(d.get("starttls", False)),
    )


def _parse_identity(d: dict) -> IdentityConfig:
    return IdentityConfig(
        from_addr=d["from"],
        reply_to=d.get("reply_to"),
    )


def _parse_folders(d: Optional[dict]) -> FolderMappingConfig:
    if not d:
        return FolderMappingConfig()
    return FolderMappingConfig(
        inbox=d.get("inbox", "INBOX"),
        sent=d.get("sent", "Sent"),
        drafts=d.get("drafts", "Drafts"),
        trash=d.get("trash", "Trash"),
        spam=d.get("spam", "Junk"),
        archive=d.get("archive", "Archive"),
    )


def _parse_safety(d: Optional[dict]) -> SafetyConfig:
    if not d:
        return SafetyConfig()
    return SafetyConfig(
        allow_delete=bool(d.get("allow_delete", False)),
        allow_empty_trash=bool(d.get("allow_empty_trash", False)),
        confirm_batch_threshold=int(d.get("confirm_batch_threshold", 25)),
    )


def _parse_account(name: str, d: dict) -> AccountConfig:
    return AccountConfig(
        imap=_parse_imap(d["imap"]),
        smtp=_parse_smtp(d["smtp"]),
        identity=_parse_identity(d["identity"]),
        folders=_parse_folders(d.get("folders")),
        safety=_parse_safety(d.get("safety")),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "imap-mcp" / "config.yaml"


def load_config(path: Optional[str] = None) -> Config:
    """Load and validate the config file.

    Args:
        path: Explicit path to the YAML file. If None, reads IMAP_MCP_CONFIG
              env var; if that is also unset, uses the default location.

    Returns:
        A parsed Config instance.

    Raises:
        FileNotFoundError: if the config file does not exist.
        ValueError: if the config is invalid (e.g. default_account not found).
    """
    if path is None:
        path = os.environ.get("IMAP_MCP_CONFIG", str(_DEFAULT_CONFIG_PATH))

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open() as fh:
        raw = yaml.safe_load(fh)

    accounts: dict[str, AccountConfig] = {}
    for name, acc_data in raw.get("accounts", {}).items():
        accounts[name] = _parse_account(name, acc_data)

    default_account = raw.get("default_account", "")
    if default_account not in accounts:
        raise ValueError(
            f"default_account '{default_account}' not found in accounts: {list(accounts.keys())}"
        )

    return Config(default_account=default_account, accounts=accounts)
