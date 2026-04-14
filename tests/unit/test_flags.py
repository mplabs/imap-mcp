"""Tests for flag tools: set_flags, mark_read/unread, star/unstar."""

import pytest
from unittest.mock import patch, MagicMock

from imap_mcp.tools.flags import set_flags, mark_read, mark_unread, star, unstar
from imap_mcp.imap_pool import ImapPool
from imap_mcp.audit import AuditLog


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 1000})
    client.add_flags = MagicMock()
    client.remove_flags = MagicMock()
    return client


@pytest.fixture
def pool(base_registry):
    return ImapPool(base_registry)


@pytest.fixture
def audit(tmp_path):
    return AuditLog(str(tmp_path / "audit.log"))


class TestSetFlags:
    @pytest.mark.asyncio
    async def test_add_seen(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await set_flags(
                pool,
                id="personal:INBOX:1000:42",
                add=["\\Seen"],
                remove=[],
                account="personal",
                audit=audit,
            )

        mock_client.add_flags.assert_called_once_with([42], ["\\Seen"])
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_remove_flag(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            await set_flags(
                pool,
                id="personal:INBOX:1000:42",
                add=[],
                remove=["\\Seen"],
                account="personal",
                audit=audit,
            )

        mock_client.remove_flags.assert_called_once_with([42], ["\\Seen"])

    @pytest.mark.asyncio
    async def test_stale_ref_raises(self, pool, mock_client, audit):
        from imap_mcp.errors import StaleRefError
        mock_client.select_folder.return_value = {b"UIDVALIDITY": 9999}

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(StaleRefError):
                await set_flags(
                    pool,
                    id="personal:INBOX:1000:42",
                    add=["\\Seen"],
                    remove=[],
                    account="personal",
                    audit=audit,
                )


class TestMarkReadUnread:
    @pytest.mark.asyncio
    async def test_mark_read(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            await mark_read(pool, id="personal:INBOX:1000:1", account="personal", audit=audit)

        mock_client.add_flags.assert_called_once_with([1], ["\\Seen"])

    @pytest.mark.asyncio
    async def test_mark_unread(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            await mark_unread(pool, id="personal:INBOX:1000:1", account="personal", audit=audit)

        mock_client.remove_flags.assert_called_once_with([1], ["\\Seen"])

    @pytest.mark.asyncio
    async def test_star(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            await star(pool, id="personal:INBOX:1000:1", account="personal", audit=audit)

        mock_client.add_flags.assert_called_once_with([1], ["\\Flagged"])

    @pytest.mark.asyncio
    async def test_unstar(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            await unstar(pool, id="personal:INBOX:1000:1", account="personal", audit=audit)

        mock_client.remove_flags.assert_called_once_with([1], ["\\Flagged"])
