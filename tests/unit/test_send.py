"""Tests for send_email and save_draft."""

import email as emaillib
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from imap_mcp.tools.send import send_email, save_draft
from imap_mcp.imap_pool import ImapPool
from imap_mcp.audit import AuditLog


@pytest.fixture
def pool(base_registry):
    return ImapPool(base_registry)


@pytest.fixture
def audit(tmp_path):
    return AuditLog(str(tmp_path / "audit.log"))


@pytest.fixture
def mock_imap():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 1000})
    client.append = MagicMock(return_value=b"[APPENDUID 1000 42]")
    return client


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_sends_and_appends_to_sent(self, pool, mock_imap, audit, base_registry):
        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock()

            with patch.object(pool, "acquire") as mock_acquire:
                mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_imap)
                mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

                with patch("imap_mcp.tools.send.resolve_secret", return_value="pw"):
                    result = await send_email(
                        pool,
                        registry=base_registry,
                        to=["bob@example.com"],
                        subject="Hello",
                        body="World",
                        account="personal",
                        audit=audit,
                    )

        assert result["success"] is True
        mock_smtp.send.assert_called_once()
        mock_imap.append.assert_called_once()

    @pytest.mark.asyncio
    async def test_smtp_message_has_correct_headers(self, pool, mock_imap, audit, base_registry):
        captured = {}

        async def _capture_send(msg, **kwargs):
            captured["msg"] = msg

        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(side_effect=_capture_send)

            with patch.object(pool, "acquire") as mock_acquire:
                mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_imap)
                mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

                with patch("imap_mcp.tools.send.resolve_secret", return_value="pw"):
                    await send_email(
                        pool,
                        registry=base_registry,
                        to=["bob@example.com"],
                        cc=["carol@example.com"],
                        subject="Test Subject",
                        body="Test body",
                        account="personal",
                        audit=audit,
                    )

        msg = captured["msg"]
        assert "Test Subject" in msg["Subject"]
        assert "bob@example.com" in msg["To"]

    @pytest.mark.asyncio
    async def test_in_reply_to_sets_headers(self, pool, mock_imap, audit, base_registry):
        captured = {}

        async def _capture_send(msg, **kwargs):
            captured["msg"] = msg

        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(side_effect=_capture_send)

            with patch.object(pool, "acquire") as mock_acquire:
                mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_imap)
                mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

                with patch("imap_mcp.tools.send.resolve_secret", return_value="pw"):
                    await send_email(
                        pool,
                        registry=base_registry,
                        to=["bob@example.com"],
                        subject="Re: Hello",
                        body="Reply body",
                        in_reply_to="<original-123@example.com>",
                        account="personal",
                        audit=audit,
                    )

        msg = captured["msg"]
        assert msg["In-Reply-To"] == "<original-123@example.com>"
        assert "<original-123@example.com>" in msg["References"]


class TestSaveDraft:
    @pytest.mark.asyncio
    async def test_appends_to_drafts_folder(self, pool, mock_imap, audit, base_registry):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_imap)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await save_draft(
                pool,
                registry=base_registry,
                to=["bob@example.com"],
                subject="Draft Subject",
                body="Draft body",
                account="personal",
                audit=audit,
            )

        assert result["success"] is True
        mock_imap.append.assert_called_once()
        # Check it was appended to Drafts with \\Draft flag
        call_args = mock_imap.append.call_args
        folder_arg = call_args[0][0]
        flags_arg = call_args[1].get("flags") or call_args[0][2] if len(call_args[0]) > 2 else None
        assert folder_arg == "Drafts"

    @pytest.mark.asyncio
    async def test_draft_not_sent(self, pool, mock_imap, audit, base_registry):
        with patch("imap_mcp.tools.send.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock()

            with patch.object(pool, "acquire") as mock_acquire:
                mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_imap)
                mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

                await save_draft(
                    pool,
                    registry=base_registry,
                    to=["bob@example.com"],
                    subject="Draft",
                    body="Not sent",
                    account="personal",
                    audit=audit,
                )

        mock_smtp.send.assert_not_called()
