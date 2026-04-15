"""Tests for the admin tools: list_accounts, test_connection."""

import os
import textwrap
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from imap_mcp.config import load_config
from imap_mcp.accounts import AccountRegistry
from imap_mcp.tools.admin import list_accounts, test_connection


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
""")


@pytest.fixture
def registry(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(YAML)
    with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "secret"}):
        cfg = load_config(str(p))
    return AccountRegistry(cfg)


class TestListAccounts:
    def test_returns_account_names(self, registry):
        result = list_accounts(registry)
        assert result["default_account"] == "personal"
        accounts = result["accounts"]
        assert len(accounts) == 1
        assert accounts[0]["name"] == "personal"

    def test_no_secrets_in_output(self, registry):
        result = list_accounts(registry)
        import json
        dumped = json.dumps(result)
        assert "secret" not in dumped.lower()

    def test_includes_imap_host(self, registry):
        result = list_accounts(registry)
        acc = result["accounts"][0]
        assert acc["imap_host"] == "imap.fastmail.com"
        assert acc["smtp_host"] == "smtp.fastmail.com"


def _mock_smtp():
    smtp = AsyncMock()
    smtp.connect = AsyncMock()
    smtp.login = AsyncMock()
    smtp.quit = AsyncMock()
    return smtp


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_success_both(self, registry):
        mock_imap = MagicMock()
        mock_imap.__enter__ = MagicMock(return_value=mock_imap)
        mock_imap.__exit__ = MagicMock(return_value=False)

        with patch("imap_mcp.tools.admin.IMAPClient") as MockIMAPClient:
            MockIMAPClient.return_value = mock_imap
            with patch("imap_mcp.tools.admin.aiosmtplib.SMTP", return_value=_mock_smtp()):
                with patch("imap_mcp.tools.admin.resolve_secret", return_value="secret"):
                    result = await test_connection(registry, account=None)

        assert result["success"] is True
        assert result["account"] == "personal"
        assert result["imap"] == "ok"
        assert result["smtp"] == "ok"

    @pytest.mark.asyncio
    async def test_imap_failure_surfaced_independently(self, registry):
        mock_imap = MagicMock()
        mock_imap.__enter__ = MagicMock(return_value=mock_imap)
        mock_imap.__exit__ = MagicMock(return_value=False)
        mock_imap.login.side_effect = Exception("LOGIN failed")

        with patch("imap_mcp.tools.admin.IMAPClient") as MockIMAPClient:
            MockIMAPClient.return_value = mock_imap
            with patch("imap_mcp.tools.admin.aiosmtplib.SMTP", return_value=_mock_smtp()):
                with patch("imap_mcp.tools.admin.resolve_secret", return_value="bad"):
                    result = await test_connection(registry, account=None)

        assert result["success"] is False
        assert "LOGIN failed" in result["imap"]
        assert result["smtp"] == "ok"

    @pytest.mark.asyncio
    async def test_smtp_failure_surfaced_independently(self, registry):
        mock_imap = MagicMock()
        mock_imap.__enter__ = MagicMock(return_value=mock_imap)
        mock_imap.__exit__ = MagicMock(return_value=False)

        bad_smtp = _mock_smtp()
        bad_smtp.connect.side_effect = Exception("Connection refused")

        with patch("imap_mcp.tools.admin.IMAPClient") as MockIMAPClient:
            MockIMAPClient.return_value = mock_imap
            with patch("imap_mcp.tools.admin.aiosmtplib.SMTP", return_value=bad_smtp):
                with patch("imap_mcp.tools.admin.resolve_secret", return_value="pw"):
                    result = await test_connection(registry, account=None)

        assert result["success"] is False
        assert result["imap"] == "ok"
        assert "Connection refused" in result["smtp"]

    @pytest.mark.asyncio
    async def test_explicit_account(self, registry):
        mock_imap = MagicMock()
        mock_imap.__enter__ = MagicMock(return_value=mock_imap)
        mock_imap.__exit__ = MagicMock(return_value=False)

        with patch("imap_mcp.tools.admin.IMAPClient") as MockIMAPClient:
            MockIMAPClient.return_value = mock_imap
            with patch("imap_mcp.tools.admin.aiosmtplib.SMTP", return_value=_mock_smtp()):
                with patch("imap_mcp.tools.admin.resolve_secret", return_value="s"):
                    result = await test_connection(registry, account="personal")

        assert result["account"] == "personal"
