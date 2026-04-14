"""Tests for structured error types."""

import pytest

from imap_mcp.errors import (
    ImapMcpError,
    ErrorCode,
    AuthFailedError,
    ConnectionFailedError,
    FolderNotFoundError,
    MessageNotFoundError,
    StaleRefError,
    PermissionDeniedError,
    ConfirmationRequiredError,
    NotConfiguredError,
    ProtocolError,
    TimeoutError as ImapTimeoutError,
    RateLimitedError,
)


class TestErrorCodes:
    def test_all_codes_defined(self):
        expected = {
            "AUTH_FAILED",
            "CONNECTION_FAILED",
            "FOLDER_NOT_FOUND",
            "MESSAGE_NOT_FOUND",
            "STALE_REF",
            "PERMISSION_DENIED",
            "CONFIRMATION_REQUIRED",
            "NOT_CONFIGURED",
            "PROTOCOL_ERROR",
            "TIMEOUT",
            "RATE_LIMITED",
        }
        actual = {c.value for c in ErrorCode}
        assert expected == actual


class TestImapMcpError:
    def test_to_dict(self):
        err = ImapMcpError(ErrorCode.AUTH_FAILED, "bad credentials", retriable=False)
        d = err.to_dict()
        assert d == {
            "code": "AUTH_FAILED",
            "message": "bad credentials",
            "retriable": False,
        }

    def test_retriable_default_false(self):
        err = ImapMcpError(ErrorCode.PROTOCOL_ERROR, "oops")
        assert err.retriable is False

    def test_stale_ref_retriable(self):
        err = StaleRefError("INBOX")
        assert err.retriable is True
        assert "INBOX" in err.message

    def test_connection_failed_retriable(self):
        err = ConnectionFailedError("imap.example.com")
        assert err.retriable is True

    def test_confirmation_required(self):
        err = ConfirmationRequiredError(42)
        assert err.code == ErrorCode.CONFIRMATION_REQUIRED
        assert "42" in err.message

    def test_not_configured(self):
        err = NotConfiguredError("sieve")
        assert err.code == ErrorCode.NOT_CONFIGURED

    def test_permission_denied(self):
        err = PermissionDeniedError("hard delete is disabled")
        assert err.code == ErrorCode.PERMISSION_DENIED
