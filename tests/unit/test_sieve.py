"""Tests for Sieve/ManageSieve tools.

When managesieve is not installed (or not configured), every tool must
return a NOT_CONFIGURED error. When configured, the tools delegate to
a ManageSieve client.
"""

import pytest
from unittest.mock import patch, MagicMock

from imap_mcp.errors import NotConfiguredError
from imap_mcp.tools.sieve import (
    list_sieve_scripts,
    get_sieve_script,
    put_sieve_script,
    activate_sieve_script,
    delete_sieve_script,
)


class TestSieveNotConfigured:
    """All tools raise NotConfiguredError when no sieve block is present."""

    @pytest.mark.asyncio
    async def test_list_not_configured(self):
        with pytest.raises(NotConfiguredError):
            await list_sieve_scripts(registry=None, account="personal")

    @pytest.mark.asyncio
    async def test_get_not_configured(self):
        with pytest.raises(NotConfiguredError):
            await get_sieve_script(registry=None, name="spam", account="personal")

    @pytest.mark.asyncio
    async def test_put_not_configured(self):
        with pytest.raises(NotConfiguredError):
            await put_sieve_script(
                registry=None, name="spam", script="require [];", account="personal"
            )

    @pytest.mark.asyncio
    async def test_activate_not_configured(self):
        with pytest.raises(NotConfiguredError):
            await activate_sieve_script(registry=None, name="spam", account="personal")

    @pytest.mark.asyncio
    async def test_delete_not_configured(self):
        with pytest.raises(NotConfiguredError):
            await delete_sieve_script(registry=None, name="spam", account="personal")


class TestSieveWithConfig:
    """When a sieve block is present the tools delegate to ManageSieve."""

    def _make_registry_with_sieve(self):
        registry = MagicMock()
        acc = MagicMock()
        acc.sieve = MagicMock()
        acc.sieve.host = "imap.example.com"
        acc.sieve.port = 4190
        acc.sieve.username = "me@example.com"
        acc.sieve.auth = MagicMock()
        acc.sieve.auth.secret_ref = "env:SIEVE_PASS"
        registry.resolve.return_value = ("personal", acc)
        return registry

    @pytest.mark.asyncio
    async def test_list_scripts(self):
        registry = self._make_registry_with_sieve()
        mock_conn = MagicMock()
        mock_conn.listscripts.return_value = (["spam", "vacation"], "spam")

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_conn
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await list_sieve_scripts(registry=registry, account="personal")

        assert "scripts" in result
        assert "spam" in result["scripts"]

    @pytest.mark.asyncio
    async def test_get_script(self):
        registry = self._make_registry_with_sieve()
        mock_conn = MagicMock()
        mock_conn.getscript.return_value = "require []; stop;"

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_conn
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await get_sieve_script(
                    registry=registry, name="spam", account="personal"
                )

        assert result["name"] == "spam"
        assert "require" in result["script"]

    @pytest.mark.asyncio
    async def test_put_script_validates_first(self):
        registry = self._make_registry_with_sieve()
        mock_conn = MagicMock()
        mock_conn.checkscript.return_value = (True, None)
        mock_conn.putscript.return_value = True

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_conn
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await put_sieve_script(
                    registry=registry,
                    name="spam",
                    script="require [];",
                    account="personal",
                )

        mock_conn.checkscript.assert_called_once()
        mock_conn.putscript.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_script(self):
        registry = self._make_registry_with_sieve()
        mock_conn = MagicMock()
        mock_conn.deletescript.return_value = True

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_conn
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await delete_sieve_script(
                    registry=registry, name="spam", account="personal"
                )

        assert result["success"] is True
