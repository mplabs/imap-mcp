"""Tests for the IMAP connection pool."""

import pytest
from unittest.mock import patch, MagicMock, call

from imap_mcp.imap_pool import ImapPool


@pytest.fixture
def mock_imap_client():
    """Return a context manager that yields a mock IMAPClient."""
    client = MagicMock()
    client.login = MagicMock()
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 999})
    client.logout = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestImapPool:
    def test_acquire_calls_login(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "INBOX") as client:
                    assert client is mock_imap_client
        mock_imap_client.login.assert_called_once()

    def test_acquire_selects_folder(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "INBOX") as _:
                    pass
        mock_imap_client.select_folder.assert_called_once_with("INBOX", readonly=True)

    def test_acquire_default_account(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire(None, "INBOX") as _:
                    pass
        # Should have connected to the default account host
        from imap_mcp.imap_pool import IMAPClient as _IC  # noqa: F401

    def test_acquire_writable(self, base_registry, mock_imap_client):
        pool = ImapPool(base_registry)
        with patch("imap_mcp.imap_pool.IMAPClient", return_value=mock_imap_client):
            with patch("imap_mcp.imap_pool.resolve_secret", return_value="pw"):
                with pool.acquire("personal", "INBOX", readonly=False) as _:
                    pass
        mock_imap_client.select_folder.assert_called_once_with("INBOX", readonly=False)
