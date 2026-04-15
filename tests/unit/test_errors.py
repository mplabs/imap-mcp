"""Tests for structured error types."""


from imap_mcp.errors import (
    ImapMcpError, ErrorCode, ConnectionFailedError,
    MessageNotFoundError, StaleRefError,
    ConfirmationRequiredError, RateLimitedError,
)


class TestErrorCodes:
    def test_all_codes_defined(self):
        expected = {
            "AUTH_FAILED", "CONNECTION_FAILED", "FOLDER_NOT_FOUND",
            "MESSAGE_NOT_FOUND", "STALE_REF", "PERMISSION_DENIED",
            "CONFIRMATION_REQUIRED", "NOT_CONFIGURED", "PROTOCOL_ERROR",
            "TIMEOUT", "RATE_LIMITED",
        }
        assert {c.value for c in ErrorCode} == expected


class TestImapMcpError:
    def test_to_dict_minimal(self):
        err = ImapMcpError(ErrorCode.AUTH_FAILED, "bad credentials", retriable=False)
        d = err.to_dict()
        assert d == {"code": "AUTH_FAILED", "message": "bad credentials", "retriable": False}

    def test_to_dict_with_recovery(self):
        err = ImapMcpError(ErrorCode.STALE_REF, "stale", retriable=True, recovery="re-list")
        d = err.to_dict()
        assert d["recovery"] == "re-list"

    def test_to_dict_no_recovery_key_when_absent(self):
        err = ImapMcpError(ErrorCode.AUTH_FAILED, "bad")
        assert "recovery" not in err.to_dict()

    def test_retriable_default_false(self):
        assert ImapMcpError(ErrorCode.PROTOCOL_ERROR, "oops").retriable is False

    def test_stale_ref_retriable_with_recovery(self):
        err = StaleRefError("INBOX")
        assert err.retriable is True
        assert "INBOX" in err.message
        assert err.recovery is not None
        assert "list_messages" in err.recovery

    def test_connection_failed_retriable(self):
        assert ConnectionFailedError("imap.example.com").retriable is True

    def test_message_not_found_has_recovery(self):
        err = MessageNotFoundError("<x@y>")
        assert err.recovery is not None

    def test_confirmation_required(self):
        err = ConfirmationRequiredError(42)
        assert err.code == ErrorCode.CONFIRMATION_REQUIRED
        assert "42" in err.message
        assert err.recovery is not None

    def test_rate_limited_retriable_with_recovery(self):
        err = RateLimitedError()
        assert err.retriable is True
        assert err.recovery is not None
