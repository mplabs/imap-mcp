"""Tests for message reading, searching, and listing tools."""

from contextlib import contextmanager
from email.mime.text import MIMEText
from unittest.mock import patch, MagicMock

import pytest

from imap_mcp.tools.messages import list_messages, search_emails, read_email
from imap_mcp.errors import StaleRefError


# ---------------------------------------------------------------------------
# Helpers — build fake IMAP fetch responses
# ---------------------------------------------------------------------------

def _make_raw_message(
    subject="Test Subject",
    from_addr="alice@example.com",
    to_addr="bob@example.com",
    body="Hello world",
    message_id="<test-123@example.com>",
) -> bytes:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Message-ID"] = message_id
    msg["Date"] = "Mon, 14 Apr 2026 10:00:00 +0000"
    return msg.as_bytes()


def _patch_acquire(ctx, mock_conn):
    @contextmanager
    def fake_acquire(account, folder, readonly=True):
        yield mock_conn

    return patch.object(ctx.pool, "acquire", side_effect=fake_acquire)


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------

class TestListMessages:
    @pytest.mark.asyncio
    async def test_basic_list(self, ctx, mock_conn):
        raw = _make_raw_message()
        mock_conn.client.search.return_value = [1, 2]
        mock_conn.client.fetch.return_value = {
            1: {b"FLAGS": (b"\\Seen",), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
            2: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with _patch_acquire(ctx, mock_conn):
            result = await list_messages(ctx, account="personal", folder="INBOX", limit=10)

        assert "results" in result
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_result_contains_expected_fields(self, ctx, mock_conn):
        raw = _make_raw_message(subject="Hello", from_addr="alice@example.com")
        mock_conn.client.search.return_value = [42]
        mock_conn.client.fetch.return_value = {
            42: {b"FLAGS": (b"\\Seen",), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with _patch_acquire(ctx, mock_conn):
            result = await list_messages(ctx, account="personal", folder="INBOX", limit=10)

        msg = result["results"][0]
        assert msg["subject"] == "Hello"
        assert msg["from"] == "alice@example.com"
        assert "ref" in msg
        assert "message_id" in msg
        assert "flags" in msg
        assert "snippet" in msg

    @pytest.mark.asyncio
    async def test_empty_folder(self, ctx, mock_conn):
        mock_conn.client.search.return_value = []

        with _patch_acquire(ctx, mock_conn):
            result = await list_messages(ctx, account="personal", folder="INBOX", limit=10)

        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_limit_respected(self, ctx, mock_conn):
        raw = _make_raw_message()
        mock_conn.client.search.return_value = list(range(1, 21))
        mock_conn.client.fetch.return_value = {
            i: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)}
            for i in range(1, 21)
        }

        with _patch_acquire(ctx, mock_conn):
            result = await list_messages(ctx, account="personal", folder="INBOX", limit=5)

        assert len(result["results"]) <= 5

    @pytest.mark.asyncio
    async def test_next_cursor_set_when_more_available(self, ctx, mock_conn):
        raw = _make_raw_message()
        mock_conn.client.search.return_value = list(range(1, 12))  # 11 items
        mock_conn.client.fetch.return_value = {
            i: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)}
            for i in range(1, 12)
        }

        with _patch_acquire(ctx, mock_conn):
            result = await list_messages(ctx, account="personal", folder="INBOX", limit=10)

        assert result["next_cursor"] is not None
        assert result["next_cursor"].startswith("uid:")

    @pytest.mark.asyncio
    async def test_no_cursor_when_all_fit(self, ctx, mock_conn):
        raw = _make_raw_message()
        mock_conn.client.search.return_value = [1, 2, 3]
        mock_conn.client.fetch.return_value = {
            i: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)}
            for i in [1, 2, 3]
        }

        with _patch_acquire(ctx, mock_conn):
            result = await list_messages(ctx, account="personal", folder="INBOX", limit=50)

        assert result["next_cursor"] is None


# ---------------------------------------------------------------------------
# search_emails
# ---------------------------------------------------------------------------

class TestSearchEmails:
    @pytest.mark.asyncio
    async def test_raw_query(self, ctx, mock_conn):
        raw = _make_raw_message()
        mock_conn.client.search.return_value = [7]
        mock_conn.client.fetch.return_value = {
            7: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with _patch_acquire(ctx, mock_conn):
            result = await search_emails(
                ctx,
                query={"raw": "UNSEEN FROM alice@example.com"},
                account="personal",
                folder="INBOX",
                limit=50,
            )

        mock_conn.client.search.assert_called_once_with(["UNSEEN FROM alice@example.com"])
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_gmail_raw_query(self, ctx, mock_conn):
        raw = _make_raw_message()
        mock_conn.client.search.return_value = [3]
        mock_conn.client.fetch.return_value = {
            3: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with _patch_acquire(ctx, mock_conn):
            result = await search_emails(
                ctx,
                query={"gmail_raw": "from:alice label:unread"},
                account="personal",
                folder="INBOX",
                limit=50,
            )

        mock_conn.client.search.assert_called_once_with(
            ["X-GM-RAW from:alice label:unread"]
        )

    @pytest.mark.asyncio
    async def test_unknown_query_falls_back_to_all(self, ctx, mock_conn):
        raw = _make_raw_message()
        mock_conn.client.search.return_value = [1]
        mock_conn.client.fetch.return_value = {
            1: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with _patch_acquire(ctx, mock_conn):
            await search_emails(ctx, query={}, account="personal", folder="INBOX")

        mock_conn.client.search.assert_called_once_with(["ALL"])


# ---------------------------------------------------------------------------
# read_email
# ---------------------------------------------------------------------------

class TestReadEmail:
    @pytest.mark.asyncio
    async def test_read_by_ref(self, ctx, mock_conn):
        raw = _make_raw_message(subject="Read Me", body="Full body text")
        mock_conn.client.fetch.return_value = {
            99: {b"FLAGS": (b"\\Seen",), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with _patch_acquire(ctx, mock_conn):
            result = await read_email(
                ctx,
                id="personal:INBOX:1000:99",
                account="personal",
            )

        assert result["subject"] == "Read Me"
        assert "Full body text" in result["body_text"]
        assert "flags" in result
        assert "attachments" in result

    @pytest.mark.asyncio
    async def test_stale_ref_raises(self, ctx, mock_conn):
        # ref has uidvalidity=999, but mock_conn.uidvalidity=1000 → mismatch
        mock_conn.uidvalidity = 1000

        with _patch_acquire(ctx, mock_conn):
            with pytest.raises(StaleRefError):
                await read_email(
                    ctx,
                    id="personal:INBOX:999:42",
                    account="personal",
                )
