"""Configuration loading for imap-mcp."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

import keyring
import yaml


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------

def resolve_secret(secret_ref: str) -> str:
    """Resolve a secret_ref string to its plain-text value.

    Schemes:
      env:<VAR>                   — read from environment variable
      keyring:<service>/<username> — read from OS keyring
      <bare string>               — returned as-is (dev convenience)
    """
    if ":" not in secret_ref:
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
            raise ValueError(f"No keyring entry for service='{service}', username='{username}'")
        return value

    raise ValueError(f"Unsupported secret_ref scheme '{scheme}' in '{secret_ref}'")


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuthConfig:
    method: str  # password | app_password | xoauth2 (v1.1 stub)
    secret_ref: str


@dataclass
class MailServerConfig:
    """Shared fields for IMAP and SMTP server configuration."""
    host: str
    port: int
    tls: bool
    username: str
    auth: AuthConfig
    starttls: bool = False


@dataclass
class ImapConfig(MailServerConfig):
    pass


@dataclass
class SmtpConfig(MailServerConfig):
    pass


@dataclass
class SieveConfig:
    host: str
    port: int
    username: str
    auth: AuthConfig
    tls: bool = False


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
class RateLimitConfig:
    max_ops_per_minute: int = 60


@dataclass
class ResolverConfig:
    max_search_folders: int = 10


@dataclass
class AttachmentConfig:
    max_size_mb: int = 50


@dataclass
class AccountConfig:
    imap: ImapConfig
    smtp: SmtpConfig
    identity: IdentityConfig
    folders: FolderMappingConfig = field(default_factory=FolderMappingConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    resolver: ResolverConfig = field(default_factory=ResolverConfig)
    attachment: AttachmentConfig = field(default_factory=AttachmentConfig)
    sieve: Optional[SieveConfig] = None


@dataclass
class Config:
    default_account: str
    accounts: dict[str, AccountConfig]


# ---------------------------------------------------------------------------
# YAML → dataclass helpers
# ---------------------------------------------------------------------------

def _parse_auth(d: dict) -> AuthConfig:
    return AuthConfig(method=d["method"], secret_ref=d["secret_ref"])


def _parse_mail_server(d: dict, cls: type) -> MailServerConfig:
    return cls(
        host=d["host"],
        port=int(d["port"]),
        tls=bool(d.get("tls", True)),
        username=d["username"],
        auth=_parse_auth(d["auth"]),
        starttls=bool(d.get("starttls", False)),
    )


def _parse_folders(d: Optional[dict]) -> FolderMappingConfig:
    if not d:
        return FolderMappingConfig()
    # Only forward keys that exist in the dataclass; unknown keys are ignored.
    valid = {f.name for f in fields(FolderMappingConfig)}
    return FolderMappingConfig(**{k: v for k, v in d.items() if k in valid and v is not None})


def _parse_sieve(d: Optional[dict]) -> Optional[SieveConfig]:
    if not d:
        return None
    return SieveConfig(
        host=d["host"],
        port=int(d["port"]),
        username=d["username"],
        auth=_parse_auth(d["auth"]),
        tls=bool(d.get("tls", False)),
    )


def _parse_simple(d: Optional[dict], cls: type):
    """Parse a flat YAML dict into a dataclass, using class defaults for missing keys."""
    if not d:
        return cls()
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in valid and v is not None})


def _parse_account(name: str, d: dict) -> AccountConfig:
    return AccountConfig(
        imap=_parse_mail_server(d["imap"], ImapConfig),
        smtp=_parse_mail_server(d["smtp"], SmtpConfig),
        identity=IdentityConfig(
            from_addr=d["identity"]["from"],
            reply_to=d["identity"].get("reply_to"),
        ),
        folders=_parse_folders(d.get("folders")),
        safety=_parse_simple(d.get("safety"), SafetyConfig),
        rate_limit=_parse_simple(d.get("rate_limit"), RateLimitConfig),
        resolver=_parse_simple(d.get("resolver"), ResolverConfig),
        attachment=_parse_simple(d.get("attachment"), AttachmentConfig),
        sieve=_parse_sieve(d.get("sieve")),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "imap-mcp" / "config.yaml"


def load_config(path: Optional[str] = None) -> Config:
    """Load and validate the config file."""
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
