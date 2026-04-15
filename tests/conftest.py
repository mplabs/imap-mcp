"""Shared pytest fixtures."""

import os
import textwrap
from unittest.mock import patch, MagicMock

import pytest

from imap_mcp.config import load_config
from imap_mcp.accounts import AccountRegistry
from imap_mcp.audit import AuditLog
from imap_mcp.imap_pool import ImapPool, Connection
from imap_mcp.resolver import MessageResolver
from imap_mcp.context import Context


BASE_YAML = textwrap.dedent("""\
    default_account: personal

    accounts:
      personal:
        imap:
          host: imap.fastmail.com
          port: 993
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        smtp:
          host: smtp.fastmail.com
          port: 465
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        identity:
          from: "Me <me@example.com>"
""")


@pytest.fixture
def base_config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE_YAML)
    with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "testpassword"}):
        cfg = load_config(str(p))
    return cfg


@pytest.fixture
def base_registry(base_config):
    return AccountRegistry(base_config)


@pytest.fixture
def mock_conn():
    """A mock Connection with sensible defaults."""
    conn = MagicMock(spec=Connection)
    conn.client = MagicMock()
    conn.uidvalidity = 1000
    conn.account_name = "personal"
    conn.folder = "INBOX"
    conn.client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 1000})
    return conn


@pytest.fixture
def pool(base_registry):
    return ImapPool(base_registry)


@pytest.fixture
def audit(tmp_path):
    return AuditLog(str(tmp_path / "audit.log"))


@pytest.fixture
def resolver():
    return MessageResolver()


@pytest.fixture
def ctx(pool, base_registry, audit, resolver):
    return Context(pool=pool, registry=base_registry, audit=audit, resolver=resolver)
