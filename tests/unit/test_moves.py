"""Tests for move, copy, delete, and empty_trash tools."""

import pytest
from contextlib import contextmanager
from unittest.mock import patch

from imap_mcp.tools.moves import move_email, copy_email, delete_email, empty_trash
from imap_mcp.errors import PermissionDeniedError, StaleRefError


def _patch_acquire(ctx, mock_conn):
    @contextmanager
    def fake_acquire(account, folder, readonly=True):
        yield mock_conn

    return patch.object(ctx.pool, "acquire", side_effect=fake_acquire)


class TestMoveEmail:
    @pytest.mark.asyncio
    async def test_move_copies_then_deletes(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await move_email(
                ctx,
                id="personal:INBOX:1000:42",
                to_folder="Archive",
                account="personal",
            )

        mock_conn.client.copy.assert_called_once_with([42], "Archive")
        mock_conn.client.add_flags.assert_called_once_with([42], ["\\Deleted"])
        mock_conn.client.expunge.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_stale_ref_raises(self, ctx, mock_conn):
        mock_conn.uidvalidity = 9999

        with _patch_acquire(ctx, mock_conn):
            with pytest.raises(StaleRefError):
                await move_email(
                    ctx,
                    id="personal:INBOX:1000:42",
                    to_folder="Archive",
                    account="personal",
                )


class TestCopyEmail:
    @pytest.mark.asyncio
    async def test_copy_leaves_source(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await copy_email(
                ctx,
                id="personal:INBOX:1000:42",
                to_folder="Archive",
                account="personal",
            )

        mock_conn.client.copy.assert_called_once_with([42], "Archive")
        mock_conn.client.add_flags.assert_not_called()
        mock_conn.client.expunge.assert_not_called()
        assert result["success"] is True


class TestDeleteEmail:
    @pytest.mark.asyncio
    async def test_soft_delete_moves_to_trash(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await delete_email(
                ctx,
                id="personal:INBOX:1000:42",
                hard=False,
                account="personal",
            )

        # Soft delete = move to Trash (copy + add_flags + expunge)
        mock_conn.client.copy.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_hard_delete_blocked_by_safety(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            with pytest.raises(PermissionDeniedError, match="allow_delete"):
                await delete_email(
                    ctx,
                    id="personal:INBOX:1000:42",
                    hard=True,
                    account="personal",
                )


class TestEmptyTrash:
    @pytest.mark.asyncio
    async def test_blocked_without_safety_config(self, ctx, mock_conn):
        with pytest.raises(PermissionDeniedError, match="allow_empty_trash"):
            await empty_trash(ctx, account="personal", confirm=True)

    @pytest.mark.asyncio
    async def test_blocked_without_confirm(self, ctx, mock_conn):
        with pytest.raises(PermissionDeniedError):
            await empty_trash(ctx, account="personal", confirm=False)
