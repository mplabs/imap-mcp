"""Tests for the account registry."""

import os
import textwrap
from unittest.mock import patch

import pytest

from imap_mcp.config import load_config
from imap_mcp.accounts import AccountRegistry


YAML = textwrap.dedent("""\
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
      work:
        imap:
          host: imap.work.com
          port: 993
          tls: true
          username: me@work.com
          auth:
            method: password
            secret_ref: "env:IMAP_WORK_PASS"
        smtp:
          host: smtp.work.com
          port: 465
          tls: true
          username: me@work.com
          auth:
            method: password
            secret_ref: "env:IMAP_WORK_PASS"
        identity:
          from: "Work Me <me@work.com>"
""")


@pytest.fixture
def registry(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(YAML)
    with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "p1", "IMAP_WORK_PASS": "p2"}):
        cfg = load_config(str(p))
    return AccountRegistry(cfg)


class TestAccountRegistry:
    def test_get_default(self, registry):
        acc = registry.get()
        assert acc.imap.host == "imap.fastmail.com"

    def test_get_named(self, registry):
        acc = registry.get("work")
        assert acc.imap.host == "imap.work.com"

    def test_get_unknown_raises(self, registry):
        with pytest.raises(KeyError, match="ghost"):
            registry.get("ghost")

    def test_list_names(self, registry):
        names = registry.list_names()
        assert set(names) == {"personal", "work"}

    def test_default_name(self, registry):
        assert registry.default_name == "personal"

    def test_resolve_account_none_returns_default(self, registry):
        name, acc = registry.resolve(None)
        assert name == "personal"

    def test_resolve_account_explicit(self, registry):
        name, acc = registry.resolve("work")
        assert name == "work"
        assert acc.imap.host == "imap.work.com"
