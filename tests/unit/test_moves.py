"""Tests for move, copy, delete, and empty_trash tools."""

import pytest
from unittest.mock import patch, MagicMock, call

from imap_mcp.tools.moves import move_email, copy_email, delete_email, empty_trash
from imap_mcp.imap_pool import ImapPool
from imap_mcp.audit import AuditLog
from imap_mcp.errors import PermissionDeniedError


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 1000})
    client.copy = MagicMock()
    client.add_flags = MagicMock()
    client.expunge = MagicMock()
    client.delete_messages = MagicMock()
    return client


@pytest.fixture
def pool(base_registry):
    return ImapPool(base_registry)


@pytest.fixture
def audit(tmp_path):
    return AuditLog(str(tmp_path / "audit.log"))


class TestMoveEmail:
    @pytest.mark.asyncio
    async def test_move_copies_then_deletes(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await move_email(
                pool,
                id="personal:INBOX:1000:42",
                to_folder="Archive",
                account="personal",
                audit=audit,
            )

        mock_client.copy.assert_called_once_with([42], "Archive")
        mock_client.add_flags.assert_called_once_with([42], ["\\Deleted"])
        mock_client.expunge.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_stale_ref_raises(self, pool, mock_client, audit):
        from imap_mcp.errors import StaleRefError
        mock_client.select_folder.return_value = {b"UIDVALIDITY": 9999}

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(StaleRefError):
                await move_email(
                    pool,
                    id="personal:INBOX:1000:42",
                    to_folder="Archive",
                    account="personal",
                    audit=audit,
                )


class TestCopyEmail:
    @pytest.mark.asyncio
    async def test_copy_leaves_source(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await copy_email(
                pool,
                id="personal:INBOX:1000:42",
                to_folder="Archive",
                account="personal",
                audit=audit,
            )

        mock_client.copy.assert_called_once_with([42], "Archive")
        mock_client.add_flags.assert_not_called()
        mock_client.expunge.assert_not_called()
        assert result["success"] is True


class TestDeleteEmail:
    @pytest.mark.asyncio
    async def test_soft_delete_moves_to_trash(self, pool, mock_client, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await delete_email(
                pool,
                id="personal:INBOX:1000:42",
                hard=False,
                account="personal",
                audit=audit,
                registry=base_registry,
            )

        # Default: allow_delete=False → soft delete = move to Trash
        mock_client.copy.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_hard_delete_blocked_by_safety(self, pool, mock_client, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(PermissionDeniedError, match="allow_delete"):
                await delete_email(
                    pool,
                    id="personal:INBOX:1000:42",
                    hard=True,
                    account="personal",
                    audit=audit,
                    registry=base_registry,
                )


class TestEmptyTrash:
    @pytest.mark.asyncio
    async def test_blocked_without_safety_config(self, pool, mock_client, audit, base_registry):
        with pytest.raises(PermissionDeniedError, match="allow_empty_trash"):
            await empty_trash(
                pool,
                account="personal",
                confirm=True,
                audit=audit,
                registry=base_registry,
            )

    @pytest.mark.asyncio
    async def test_blocked_without_confirm(self, pool, mock_client, audit, base_registry):
        with pytest.raises(PermissionDeniedError):
            await empty_trash(
                pool,
                account="personal",
                confirm=False,
                audit=audit,
                registry=base_registry,
            )
