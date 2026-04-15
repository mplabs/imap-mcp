"""Tests for Sieve/ManageSieve tools.

When managesieve is not installed (or not configured), every tool must
raise NotConfiguredError. When configured, the tools delegate to a
ManageSieve client.
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


def _make_sieve_ctx():
    """Build a minimal mock Context whose registry has a sieve block."""
    acc = MagicMock()
    acc.sieve = MagicMock()
    acc.sieve.host = "imap.example.com"
    acc.sieve.port = 4190
    acc.sieve.username = "me@example.com"
    acc.sieve.auth = MagicMock()
    acc.sieve.auth.secret_ref = "env:SIEVE_PASS"

    ctx = MagicMock()
    ctx.registry.resolve.return_value = ("personal", acc)
    return ctx


class TestSieveNotConfigured:
    """All tools raise NotConfiguredError when no sieve block / package missing."""

    @pytest.mark.asyncio
    async def test_list_not_configured(self, ctx):
        # ctx fixture has no sieve config → NotConfiguredError
        with pytest.raises(NotConfiguredError):
            await list_sieve_scripts(ctx, account="personal")

    @pytest.mark.asyncio
    async def test_get_not_configured(self, ctx):
        with pytest.raises(NotConfiguredError):
            await get_sieve_script(ctx, name="spam", account="personal")

    @pytest.mark.asyncio
    async def test_put_not_configured(self, ctx):
        with pytest.raises(NotConfiguredError):
            await put_sieve_script(
                ctx, name="spam", script="require [];", account="personal"
            )

    @pytest.mark.asyncio
    async def test_activate_not_configured(self, ctx):
        with pytest.raises(NotConfiguredError):
            await activate_sieve_script(ctx, name="spam", account="personal")

    @pytest.mark.asyncio
    async def test_delete_not_configured(self, ctx):
        with pytest.raises(NotConfiguredError):
            await delete_sieve_script(ctx, name="spam", account="personal")


class TestSieveWithConfig:
    """When a sieve block is present the tools delegate to ManageSieve."""

    @pytest.mark.asyncio
    async def test_list_scripts(self):
        ctx = _make_sieve_ctx()
        mock_sieve = MagicMock()
        mock_sieve.listscripts.return_value = (["spam", "vacation"], "spam")

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_sieve
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await list_sieve_scripts(ctx, account="personal")

        assert "scripts" in result
        assert "spam" in result["scripts"]

    @pytest.mark.asyncio
    async def test_get_script(self):
        ctx = _make_sieve_ctx()
        mock_sieve = MagicMock()
        mock_sieve.getscript.return_value = "require []; stop;"

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_sieve
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await get_sieve_script(ctx, name="spam", account="personal")

        assert result["name"] == "spam"
        assert "require" in result["script"]

    @pytest.mark.asyncio
    async def test_put_script_validates_first(self):
        ctx = _make_sieve_ctx()
        mock_sieve = MagicMock()
        mock_sieve.checkscript.return_value = (True, None)
        mock_sieve.putscript.return_value = True

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_sieve
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await put_sieve_script(
                    ctx,
                    name="spam",
                    script="require [];",
                    account="personal",
                )

        mock_sieve.checkscript.assert_called_once()
        mock_sieve.putscript.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_script(self):
        ctx = _make_sieve_ctx()
        mock_sieve = MagicMock()
        mock_sieve.deletescript.return_value = True

        with patch("imap_mcp.tools.sieve.managesieve") as mock_ms:
            mock_ms.MANAGESIEVE.return_value = mock_sieve
            with patch("imap_mcp.tools.sieve.resolve_secret", return_value="pw"):
                result = await delete_sieve_script(ctx, name="spam", account="personal")

        assert result["success"] is True
