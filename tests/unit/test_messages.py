"""Tests for message reading, searching, and listing tools."""

import email as emaillib
import os
import textwrap
from email.mime.text import MIMEText
from unittest.mock import patch, MagicMock

import pytest

from imap_mcp.tools.messages import (
    list_messages,
    search_emails,
    read_email,
)
from imap_mcp.imap_pool import ImapPool


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


def _fake_fetch_response(uid: int, raw: bytes, flags=(b"\\Seen",)):
    """Return an imapclient-style fetch dict for a single message."""
    return {
        uid: {
            b"FLAGS": flags,
            b"RFC822": raw,
            b"RFC822.SIZE": len(raw),
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------

class TestListMessages:
    @pytest.mark.asyncio
    async def test_basic_list(self, pool, mock_client):
        raw = _make_raw_message()
        mock_client.search.return_value = [1, 2]
        mock_client.fetch.return_value = {
            1: {b"FLAGS": (b"\\Seen",), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
            2: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await list_messages(pool, account="personal", folder="INBOX", limit=10)

        assert "results" in result
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_result_contains_expected_fields(self, pool, mock_client):
        raw = _make_raw_message(subject="Hello", from_addr="alice@example.com")
        mock_client.search.return_value = [42]
        mock_client.fetch.return_value = {
            42: {b"FLAGS": (b"\\Seen",), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await list_messages(pool, account="personal", folder="INBOX", limit=10)

        msg = result["results"][0]
        assert msg["subject"] == "Hello"
        assert msg["from"] == "alice@example.com"
        assert "ref" in msg
        assert "message_id" in msg
        assert "flags" in msg
        assert "snippet" in msg

    @pytest.mark.asyncio
    async def test_empty_folder(self, pool, mock_client):
        mock_client.search.return_value = []
        mock_client.fetch.return_value = {}

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await list_messages(pool, account="personal", folder="INBOX", limit=10)

        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_limit_respected(self, pool, mock_client):
        raw = _make_raw_message()
        # Server returns 20 UIDs
        mock_client.search.return_value = list(range(1, 21))
        fetch_data = {
            i: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)}
            for i in range(1, 21)
        }
        mock_client.fetch.return_value = fetch_data

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await list_messages(pool, account="personal", folder="INBOX", limit=5)

        assert len(result["results"]) <= 5


# ---------------------------------------------------------------------------
# search_emails
# ---------------------------------------------------------------------------

class TestSearchEmails:
    @pytest.mark.asyncio
    async def test_raw_query(self, pool, mock_client):
        raw = _make_raw_message()
        mock_client.search.return_value = [7]
        mock_client.fetch.return_value = {
            7: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await search_emails(
                pool,
                query={"raw": "UNSEEN FROM alice@example.com"},
                account="personal",
                folder="INBOX",
                limit=50,
            )

        mock_client.search.assert_called_once_with(["UNSEEN FROM alice@example.com"])
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_structured_query_from(self, pool, mock_client):
        raw = _make_raw_message()
        mock_client.search.return_value = [3]
        mock_client.fetch.return_value = {
            3: {b"FLAGS": (), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await search_emails(
                pool,
                query={"structured": {"from": "alice@example.com", "unseen": True}},
                account="personal",
                folder="INBOX",
                limit=50,
            )

        # Should build an IMAP search with FROM and UNSEEN criteria
        call_args = mock_client.search.call_args[0][0]
        criteria_str = " ".join(str(c) for c in call_args)
        assert "FROM" in criteria_str
        assert "UNSEEN" in criteria_str


# ---------------------------------------------------------------------------
# read_email
# ---------------------------------------------------------------------------

class TestReadEmail:
    @pytest.mark.asyncio
    async def test_read_by_ref(self, pool, mock_client):
        raw = _make_raw_message(subject="Read Me", body="Full body text")
        mock_client.fetch.return_value = {
            99: {b"FLAGS": (b"\\Seen",), b"RFC822": raw, b"RFC822.SIZE": len(raw)},
        }
        mock_client.select_folder.return_value = {b"UIDVALIDITY": 1000}

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await read_email(
                pool,
                id="personal:INBOX:1000:99",
                account="personal",
            )

        assert result["subject"] == "Read Me"
        assert "Full body text" in result["body_text"]
        assert "flags" in result
        assert "attachments" in result

    @pytest.mark.asyncio
    async def test_stale_ref_raises(self, pool, mock_client):
        from imap_mcp.errors import StaleRefError
        # UIDVALIDITY in ref is 999, but server says 1000
        mock_client.select_folder.return_value = {b"UIDVALIDITY": 1000}

        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(StaleRefError):
                await read_email(
                    pool,
                    id="personal:INBOX:999:42",
                    account="personal",
                )
