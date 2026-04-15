"""Tests for send_email and save_draft."""

import email as emaillib
import pytest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock, AsyncMock

from imap_mcp.tools.send import send_email, save_draft


def _patch_acquire(ctx, mock_conn):
    @contextmanager
    def fake_acquire(account, folder, readonly=True):
        yield mock_conn

    return patch.object(ctx.pool, "acquire", side_effect=fake_acquire)


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_sends_and_appends_to_sent(self, ctx, mock_conn):
        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock()
            with patch("imap_mcp.tools.send.resolve_secret", return_value="pw"):
                with _patch_acquire(ctx, mock_conn):
                    result = await send_email(
                        ctx,
                        to=["bob@example.com"],
                        subject="Hello",
                        body="World",
                        account="personal",
                    )

        assert result["success"] is True
        mock_smtp.send.assert_called_once()
        mock_conn.client.append.assert_called_once()

    @pytest.mark.asyncio
    async def test_message_has_correct_headers(self, ctx, mock_conn):
        captured = {}

        async def _capture_send(msg, **kwargs):
            captured["msg"] = msg

        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(side_effect=_capture_send)
            with patch("imap_mcp.tools.send.resolve_secret", return_value="pw"):
                with _patch_acquire(ctx, mock_conn):
                    await send_email(
                        ctx,
                        to=["bob@example.com"],
                        cc=["carol@example.com"],
                        subject="Test Subject",
                        body="Test body",
                        account="personal",
                    )

        msg = captured["msg"]
        assert "Test Subject" in msg["Subject"]
        assert "bob@example.com" in msg["To"]

    @pytest.mark.asyncio
    async def test_message_id_and_date_generated(self, ctx, mock_conn):
        captured = {}

        async def _capture_send(msg, **kwargs):
            captured["msg"] = msg

        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(side_effect=_capture_send)
            with patch("imap_mcp.tools.send.resolve_secret", return_value="pw"):
                with _patch_acquire(ctx, mock_conn):
                    await send_email(
                        ctx,
                        to=["bob@example.com"],
                        subject="Headers test",
                        body="body",
                        account="personal",
                    )

        msg = captured["msg"]
        assert msg["Message-ID"] is not None
        assert msg["Date"] is not None

    @pytest.mark.asyncio
    async def test_in_reply_to_sets_headers(self, ctx, mock_conn):
        captured = {}

        async def _capture_send(msg, **kwargs):
            captured["msg"] = msg

        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(side_effect=_capture_send)
            with patch("imap_mcp.tools.send.resolve_secret", return_value="pw"):
                with _patch_acquire(ctx, mock_conn):
                    await send_email(
                        ctx,
                        to=["bob@example.com"],
                        subject="Re: Hello",
                        body="Reply body",
                        in_reply_to="<original-123@example.com>",
                        account="personal",
                    )

        msg = captured["msg"]
        assert msg["In-Reply-To"] == "<original-123@example.com>"
        assert "<original-123@example.com>" in msg["References"]


class TestSaveDraft:
    @pytest.mark.asyncio
    async def test_appends_to_drafts_folder(self, ctx, mock_conn):
        mock_conn.client.search.return_value = [42]

        with _patch_acquire(ctx, mock_conn):
            result = await save_draft(
                ctx,
                to=["bob@example.com"],
                subject="Draft Subject",
                body="Draft body",
                account="personal",
            )

        assert result["success"] is True
        mock_conn.client.append.assert_called_once()
        call_args = mock_conn.client.append.call_args
        assert call_args[0][0] == "Drafts"

    @pytest.mark.asyncio
    async def test_draft_returns_message_id_and_ref(self, ctx, mock_conn):
        mock_conn.client.search.return_value = [42]

        with _patch_acquire(ctx, mock_conn):
            result = await save_draft(
                ctx,
                to=["bob@example.com"],
                subject="Draft",
                body="body",
                account="personal",
            )

        assert "message_id" in result
        assert result["message_id"].startswith("<")
        assert result["ref"] is not None
        assert "Drafts" in result["ref"]

    @pytest.mark.asyncio
    async def test_draft_not_sent(self, ctx, mock_conn):
        mock_conn.client.search.return_value = []

        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock()
            with _patch_acquire(ctx, mock_conn):
                await save_draft(
                    ctx,
                    to=["bob@example.com"],
                    subject="Draft",
                    body="Not sent",
                    account="personal",
                )

        mock_smtp.send.assert_not_called()
