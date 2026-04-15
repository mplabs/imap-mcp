"""Tests for folder listing and status tools."""

import pytest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

from imap_mcp.tools.folders import list_folders, folder_status


def _patch_acquire(ctx, mock_conn):
    @contextmanager
    def fake_acquire(account, folder, readonly=True):
        yield mock_conn

    return patch.object(ctx.pool, "acquire", side_effect=fake_acquire)


class TestListFolders:
    @pytest.mark.asyncio
    async def test_returns_folder_list(self, ctx, mock_conn):
        mock_conn.client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
            ((b"\\HasNoChildren", b"\\Sent"), b".", "Sent"),
            ((b"\\HasNoChildren", b"\\Drafts"), b".", "Drafts"),
        ]

        with _patch_acquire(ctx, mock_conn):
            result = await list_folders(ctx, account="personal")

        assert "folders" in result
        names = [f["name"] for f in result["folders"]]
        assert "INBOX" in names
        assert "Sent" in names

    @pytest.mark.asyncio
    async def test_folder_has_expected_fields(self, ctx, mock_conn):
        mock_conn.client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
        ]

        with _patch_acquire(ctx, mock_conn):
            result = await list_folders(ctx, account="personal")

        folder = result["folders"][0]
        assert "name" in folder
        assert "flags" in folder
        assert "delimiter" in folder


class TestFolderStatus:
    @pytest.mark.asyncio
    async def test_returns_counts(self, ctx, mock_conn):
        mock_conn.client.folder_status.return_value = {
            b"MESSAGES": 100,
            b"UNSEEN": 5,
            b"RECENT": 2,
        }

        with _patch_acquire(ctx, mock_conn):
            result = await folder_status(ctx, name="INBOX", account="personal")

        assert result["exists"] == 100
        assert result["unseen"] == 5
        assert result["recent"] == 2
        assert result["name"] == "INBOX"
