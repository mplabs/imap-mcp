"""Tests for MessageResolver — session-local message_id lookup."""

import pytest
from unittest.mock import patch, MagicMock

from imap_mcp.resolver import MessageResolver
from imap_mcp.imap_pool import ImapPool, Connection
from imap_mcp.ref import Ref
from imap_mcp.errors import MessageNotFoundError


def _make_conn(client=None, uidvalidity=1000, account_name="personal", folder="INBOX"):
    conn = MagicMock(spec=Connection)
    conn.client = client or MagicMock()
    conn.uidvalidity = uidvalidity
    conn.account_name = account_name
    conn.folder = folder
    return conn


class TestMessageResolver:
    def test_resolve_ref_string(self, base_registry):
        pool = ImapPool(base_registry)
        r = MessageResolver()
        ref = r.resolve("personal:INBOX:1000:42", pool)
        assert ref.uid == 42
        assert ref.folder == "INBOX"

    def test_resolve_cached_message_id(self, base_registry):
        pool = ImapPool(base_registry)
        r = MessageResolver()
        r.register("<msg@example.com>", "INBOX", 99, 1000)

        with patch.object(pool, "resolve", return_value=("personal", None)):
            ref = r.resolve("<msg@example.com>", pool, account="personal")

        assert ref.uid == 99
        assert ref.folder == "INBOX"
        assert ref.uidvalidity == 1000

    def test_resolve_searches_folders_on_miss(self, base_registry):
        pool = ImapPool(base_registry)
        r = MessageResolver()

        # list_folders returns one folder
        list_conn = _make_conn()
        list_conn.client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
        ]

        # search in INBOX finds uid 7
        search_conn = _make_conn(uidvalidity=2000)
        search_conn.client.search.return_value = [7]

        call_count = [0]

        from contextlib import contextmanager

        @contextmanager
        def fake_acquire(account, folder, readonly=True):
            call_count[0] += 1
            if folder == "INBOX" and call_count[0] == 1:
                yield list_conn
            else:
                yield search_conn

        with patch.object(pool, "acquire", side_effect=fake_acquire):
            with patch.object(pool, "resolve", return_value=("personal", None)):
                ref = r.resolve("<find@example.com>", pool, account="personal")

        assert ref.uid == 7
        assert ref.uidvalidity == 2000

    def test_message_not_found_after_cap(self, base_registry):
        pool = ImapPool(base_registry)
        r = MessageResolver(max_search_folders=2)

        list_conn = _make_conn()
        list_conn.client.list_folders.return_value = [
            ((b"\\HasNoChildren",), b".", "INBOX"),
            ((b"\\HasNoChildren",), b".", "Sent"),
            ((b"\\HasNoChildren",), b".", "Archive"),
        ]

        search_conn = _make_conn()
        search_conn.client.search.return_value = []

        from contextlib import contextmanager

        call_count = [0]

        @contextmanager
        def fake_acquire(account, folder, readonly=True):
            call_count[0] += 1
            if call_count[0] == 1:
                yield list_conn
            else:
                yield search_conn

        with patch.object(pool, "acquire", side_effect=fake_acquire):
            with patch.object(pool, "resolve", return_value=("personal", None)):
                with pytest.raises(MessageNotFoundError):
                    r.resolve("<missing@example.com>", pool)

    def test_noselect_folders_skipped(self, base_registry):
        pool = ImapPool(base_registry)
        r = MessageResolver()

        list_conn = _make_conn()
        list_conn.client.list_folders.return_value = [
            ((b"\\Noselect", b"\\HasChildren"), b".", "INBOX"),
        ]

        from contextlib import contextmanager

        call_count = [0]

        @contextmanager
        def fake_acquire(account, folder, readonly=True):
            call_count[0] += 1
            yield list_conn

        with patch.object(pool, "acquire", side_effect=fake_acquire):
            with patch.object(pool, "resolve", return_value=("personal", None)):
                with pytest.raises(MessageNotFoundError):
                    r.resolve("<x@y.com>", pool)

        # Only one acquire call (for list_folders); the Noselect folder was skipped
        assert call_count[0] == 1

    def test_invalid_id_raises_value_error(self, base_registry):
        pool = ImapPool(base_registry)
        r = MessageResolver()
        with pytest.raises(ValueError, match="Cannot resolve"):
            r.resolve("not-a-ref-or-msgid", pool)

    def test_register_many(self, base_registry):
        pool = ImapPool(base_registry)
        r = MessageResolver()
        r.register_many([
            {"message_id": "<a@b.com>", "ref": "personal:INBOX:1000:1"},
            {"message_id": "<c@d.com>", "ref": "personal:INBOX:1000:2"},
        ])
        assert "<a@b.com>" in r._cache
        assert "<c@d.com>" in r._cache
