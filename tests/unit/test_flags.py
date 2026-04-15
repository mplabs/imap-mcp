"""Tests for flag tools: set_flags, mark_read/unread, star/unstar."""

import pytest
from contextlib import contextmanager
from unittest.mock import patch

from imap_mcp.tools.flags import set_flags, mark_read, mark_unread, star, unstar
from imap_mcp.errors import StaleRefError


def _patch_acquire(ctx, mock_conn):
    """Context manager that patches ctx.pool.acquire to yield mock_conn."""
    @contextmanager
    def fake_acquire(account, folder, readonly=True):
        yield mock_conn

    return patch.object(ctx.pool, "acquire", side_effect=fake_acquire)


class TestSetFlags:
    @pytest.mark.asyncio
    async def test_add_seen(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await set_flags(
                ctx,
                id="personal:INBOX:1000:42",
                add=["\\Seen"],
                remove=[],
                account="personal",
            )

        mock_conn.client.add_flags.assert_called_once_with([42], ["\\Seen"])
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_remove_flag(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            await set_flags(
                ctx,
                id="personal:INBOX:1000:42",
                add=[],
                remove=["\\Seen"],
                account="personal",
            )

        mock_conn.client.remove_flags.assert_called_once_with([42], ["\\Seen"])

    @pytest.mark.asyncio
    async def test_stale_ref_raises(self, ctx, mock_conn):
        mock_conn.uidvalidity = 9999  # mismatch with ref's 1000

        with _patch_acquire(ctx, mock_conn):
            with pytest.raises(StaleRefError):
                await set_flags(
                    ctx,
                    id="personal:INBOX:1000:42",
                    add=["\\Seen"],
                    remove=[],
                    account="personal",
                )


class TestMarkReadUnread:
    @pytest.mark.asyncio
    async def test_mark_read(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            await mark_read(ctx, id="personal:INBOX:1000:1", account="personal")

        mock_conn.client.add_flags.assert_called_once_with([1], ["\\Seen"])

    @pytest.mark.asyncio
    async def test_mark_unread(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            await mark_unread(ctx, id="personal:INBOX:1000:1", account="personal")

        mock_conn.client.remove_flags.assert_called_once_with([1], ["\\Seen"])

    @pytest.mark.asyncio
    async def test_star(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            await star(ctx, id="personal:INBOX:1000:1", account="personal")

        mock_conn.client.add_flags.assert_called_once_with([1], ["\\Flagged"])

    @pytest.mark.asyncio
    async def test_unstar(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            await unstar(ctx, id="personal:INBOX:1000:1", account="personal")

        mock_conn.client.remove_flags.assert_called_once_with([1], ["\\Flagged"])
