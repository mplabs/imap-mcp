"""Tests for the IMAP connection pool and Connection type."""

import pytest
from unittest.mock import patch, MagicMock

from imap_mcp.imap_pool import ImapPool, Connection


@pytest.fixture
def mock_imap_client():
    client = MagicMock()
    client.login = MagicMock()
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 999})
    client.logout = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestImapPool:
    def test_acquire_yields_connection(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "INBOX") as conn:
                    assert isinstance(conn, Connection)
                    assert conn.client is mock_imap_client
                    assert conn.uidvalidity == 999
                    assert conn.account_name == "personal"
                    assert conn.folder == "INBOX"

    def test_acquire_calls_login(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "INBOX"):
                    pass
        mock_imap_client.login.assert_called_once()

    def test_acquire_selects_folder_once(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "Sent"):
                    pass
        mock_imap_client.select_folder.assert_called_once_with("Sent", readonly=True)

    def test_acquire_writable(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "INBOX", readonly=False):
                    pass
        mock_imap_client.select_folder.assert_called_once_with("INBOX", readonly=False)

    def test_acquire_default_account(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire(None, "INBOX") as conn:
                    assert conn.account_name == "personal"

    def test_resolve_exposes_registry(self, base_registry):
        pool = ImapPool(base_registry)
        name, acc = pool.resolve(None)
        assert name == "personal"
        name2, acc2 = pool.resolve("personal")
        assert name2 == "personal"

    def test_uidvalidity_captured_from_select(self, base_registry, mock_imap_client):
        mock_imap_client.select_folder.return_value = {b"UIDVALIDITY": 12345}
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "INBOX") as conn:
                    assert conn.uidvalidity == 12345
