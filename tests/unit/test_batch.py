"""Tests for batch operations and get_or_create_folder."""

import pytest
from unittest.mock import patch, MagicMock

from imap_mcp.tools.batch import batch_set_flags, batch_move, batch_delete
from imap_mcp.tools.folders import get_or_create_folder
from imap_mcp.imap_pool import ImapPool
from imap_mcp.audit import AuditLog
from imap_mcp.errors import ConfirmationRequiredError, PermissionDeniedError


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 1000})
    client.add_flags = MagicMock()
    client.remove_flags = MagicMock()
    client.copy = MagicMock()
    client.expunge = MagicMock()
    client.create_folder = MagicMock()
    client.list_folders = MagicMock(return_value=[
        ((b"\\HasNoChildren",), b".", "INBOX"),
    ])
    return client


@pytest.fixture
def pool(base_registry):
    return ImapPool(base_registry)


@pytest.fixture
def audit(tmp_path):
    return AuditLog(str(tmp_path / "audit.log"))


# Refs for 3 messages in same folder
IDS_SMALL = [
    "personal:INBOX:1000:1",
    "personal:INBOX:1000:2",
    "personal:INBOX:1000:3",
]

# 26 refs — over the default confirm_batch_threshold of 25
IDS_LARGE = [f"personal:INBOX:1000:{i}" for i in range(1, 27)]


class TestBatchSetFlags:
    @pytest.mark.asyncio
    async def test_adds_flags_to_all(self, pool, mock_client, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await batch_set_flags(
                pool,
                ids=IDS_SMALL,
                add=["\\Seen"],
                remove=[],
                account="personal",
                audit=audit,
                registry=base_registry,
            )

        assert result["success"] is True
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_dry_run_no_mutation(self, pool, mock_client, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await batch_set_flags(
                pool,
                ids=IDS_SMALL,
                add=["\\Seen"],
                remove=[],
                account="personal",
                audit=audit,
                registry=base_registry,
                dry_run=True,
            )

        mock_client.add_flags.assert_not_called()
        assert result["dry_run"] is True
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_large_batch_requires_confirm(self, pool, mock_client, audit, base_registry):
        with pytest.raises(ConfirmationRequiredError):
            await batch_set_flags(
                pool,
                ids=IDS_LARGE,
                add=["\\Seen"],
                remove=[],
                account="personal",
                audit=audit,
                registry=base_registry,
                confirm=False,
            )

    @pytest.mark.asyncio
    async def test_large_batch_with_confirm(self, pool, mock_client, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await batch_set_flags(
                pool,
                ids=IDS_LARGE,
                add=["\\Seen"],
                remove=[],
                account="personal",
                audit=audit,
                registry=base_registry,
                confirm=True,
            )

        assert result["success"] is True
        assert result["count"] == 26


class TestBatchMove:
    @pytest.mark.asyncio
    async def test_moves_all(self, pool, mock_client, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await batch_move(
                pool,
                ids=IDS_SMALL,
                to_folder="Archive",
                account="personal",
                audit=audit,
                registry=base_registry,
            )

        assert result["success"] is True
        assert result["count"] == 3


class TestBatchDelete:
    @pytest.mark.asyncio
    async def test_soft_deletes_all(self, pool, mock_client, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await batch_delete(
                pool,
                ids=IDS_SMALL,
                hard=False,
                account="personal",
                audit=audit,
                registry=base_registry,
            )

        assert result["success"] is True
        assert result["count"] == 3


class TestGetOrCreateFolder:
    @pytest.mark.asyncio
    async def test_returns_existing(self, pool, mock_client, audit):
        mock_client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
            ((b"\\HasNoChildren",), b".", "Projects"),
        ]

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await get_or_create_folder(
                pool, name="Projects", account="personal", audit=audit
            )

        mock_client.create_folder.assert_not_called()
        assert result["name"] == "Projects"
        assert result["created"] is False

    @pytest.mark.asyncio
    async def test_creates_missing(self, pool, mock_client, audit):
        mock_client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
        ]

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await get_or_create_folder(
                pool, name="NewFolder", account="personal", audit=audit
            )

        mock_client.create_folder.assert_called_once_with("NewFolder")
        assert result["name"] == "NewFolder"
        assert result["created"] is True
