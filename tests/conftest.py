"""Shared pytest fixtures."""

import os
import textwrap
from unittest.mock import patch

import pytest

from imap_mcp.config import load_config
from imap_mcp.accounts import AccountRegistry


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
