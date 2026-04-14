"""Tests for folder listing and status tools."""

import pytest
from unittest.mock import patch, MagicMock

from imap_mcp.tools.folders import list_folders, folder_status
from imap_mcp.imap_pool import ImapPool


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 1000})
    return client


@pytest.fixture
def pool(base_registry):
    return ImapPool(base_registry)


class TestListFolders:
    @pytest.mark.asyncio
    async def test_returns_folder_list(self, pool, mock_client):
        # imapclient list_folders returns list of (flags, delimiter, name)
        mock_client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
            ((b"\\HasNoChildren", b"\\Sent"), b".", "Sent"),
            ((b"\\HasNoChildren", b"\\Drafts"), b".", "Drafts"),
        ]
        mock_client.list_sub_folders = MagicMock(return_value=[])

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await list_folders(pool, account="personal")

        assert "folders" in result
        names = [f["name"] for f in result["folders"]]
        assert "INBOX" in names
        assert "Sent" in names

    @pytest.mark.asyncio
    async def test_folder_has_expected_fields(self, pool, mock_client):
        mock_client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
        ]

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await list_folders(pool, account="personal")

        folder = result["folders"][0]
        assert "name" in folder
        assert "flags" in folder
        assert "delimiter" in folder


class TestFolderStatus:
    @pytest.mark.asyncio
    async def test_returns_counts(self, pool, mock_client):
        mock_client.folder_status.return_value = {
            b"MESSAGES": 100,
            b"UNSEEN": 5,
            b"RECENT": 2,
        }

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await folder_status(pool, name="INBOX", account="personal")

        assert result["exists"] == 100
        assert result["unseen"] == 5
        assert result["recent"] == 2
        assert result["name"] == "INBOX"
