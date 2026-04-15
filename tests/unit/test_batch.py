"""Tests for batch operations and get_or_create_folder."""

import pytest
from contextlib import contextmanager
from unittest.mock import patch

from imap_mcp.tools.batch import batch_set_flags, batch_move, batch_delete
from imap_mcp.tools.folders import get_or_create_folder
from imap_mcp.errors import ConfirmationRequiredError


def _patch_acquire(ctx, mock_conn):
    @contextmanager
    def fake_acquire(account, folder, readonly=True):
        yield mock_conn

    return patch.object(ctx.pool, "acquire", side_effect=fake_acquire)


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
    async def test_adds_flags_to_all(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await batch_set_flags(
                ctx,
                ids=IDS_SMALL,
                add=["\\Seen"],
                remove=[],
                account="personal",
            )

        assert result["success"] is True
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_dry_run_no_mutation(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await batch_set_flags(
                ctx,
                ids=IDS_SMALL,
                add=["\\Seen"],
                remove=[],
                account="personal",
                dry_run=True,
            )

        mock_conn.client.add_flags.assert_not_called()
        assert result["dry_run"] is True
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_large_batch_requires_confirm(self, ctx, mock_conn):
        with pytest.raises(ConfirmationRequiredError):
            await batch_set_flags(
                ctx,
                ids=IDS_LARGE,
                add=["\\Seen"],
                remove=[],
                account="personal",
                confirm=False,
            )

    @pytest.mark.asyncio
    async def test_large_batch_with_confirm(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await batch_set_flags(
                ctx,
                ids=IDS_LARGE,
                add=["\\Seen"],
                remove=[],
                account="personal",
                confirm=True,
            )

        assert result["success"] is True
        assert result["count"] == 26


class TestBatchMove:
    @pytest.mark.asyncio
    async def test_moves_all(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await batch_move(
                ctx,
                ids=IDS_SMALL,
                to_folder="Archive",
                account="personal",
            )

        assert result["success"] is True
        assert result["count"] == 3


class TestBatchDelete:
    @pytest.mark.asyncio
    async def test_soft_deletes_all(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await batch_delete(
                ctx,
                ids=IDS_SMALL,
                hard=False,
                account="personal",
            )

        assert result["success"] is True
        assert result["count"] == 3


class TestGetOrCreateFolder:
    @pytest.mark.asyncio
    async def test_returns_existing(self, ctx, mock_conn):
        mock_conn.client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
            ((b"\\HasNoChildren",), b".", "Projects"),
        ]

        with _patch_acquire(ctx, mock_conn):
            result = await get_or_create_folder(
                ctx, name="Projects", account="personal"
            )

        mock_conn.client.create_folder.assert_not_called()
        assert result["name"] == "Projects"
        assert result["created"] is False

    @pytest.mark.asyncio
    async def test_creates_missing(self, ctx, mock_conn):
        mock_conn.client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
        ]

        with _patch_acquire(ctx, mock_conn):
            result = await get_or_create_folder(
                ctx, name="NewFolder", account="personal"
            )

        mock_conn.client.create_folder.assert_called_once_with("NewFolder")
        assert result["name"] == "NewFolder"
        assert result["created"] is True
