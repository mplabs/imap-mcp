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


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_success(self, registry):
        mock_client = MagicMock()
        mock_client.login = MagicMock()
        mock_client.noop = MagicMock()
        mock_client.logout = MagicMock()

        with patch("imap_mcp.tools.admin.IMAPClient") as MockIMAPClient:
            MockIMAPClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockIMAPClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)

            with patch("imap_mcp.tools.admin.resolve_secret", return_value="secret"):
                result = await test_connection(registry, account=None)

        assert result["success"] is True
        assert result["account"] == "personal"

    @pytest.mark.asyncio
    async def test_auth_failure(self, registry):
        from imapclient import IMAPClient as _IMAPClient
        with patch("imap_mcp.tools.admin.IMAPClient") as MockIMAPClient:
            instance = MagicMock()
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            instance.login.side_effect = Exception("LOGIN failed")
            MockIMAPClient.return_value = instance

            with patch("imap_mcp.tools.admin.resolve_secret", return_value="bad"):
                result = await test_connection(registry, account=None)

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_explicit_account(self, registry):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("imap_mcp.tools.admin.IMAPClient") as MockIMAPClient:
            MockIMAPClient.return_value = mock_client
            with patch("imap_mcp.tools.admin.resolve_secret", return_value="s"):
                result = await test_connection(registry, account="personal")

        assert result["account"] == "personal"
