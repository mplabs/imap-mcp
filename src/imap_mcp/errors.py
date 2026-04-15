"""Structured error types for imap-mcp."""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    AUTH_FAILED = "AUTH_FAILED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    FOLDER_NOT_FOUND = "FOLDER_NOT_FOUND"
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"
    STALE_REF = "STALE_REF"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"


class ImapMcpError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        retriable: bool = False,
        recovery: Optional[str] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retriable = retriable
        self.recovery = recovery

    def to_dict(self) -> dict:
        d: dict = {
            "code": self.code.value,
            "message": self.message,
            "retriable": self.retriable,
        }
        if self.recovery:
            d["recovery"] = self.recovery
        return d


class AuthFailedError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.AUTH_FAILED, f"Authentication failed: {detail}", retriable=False)


class ConnectionFailedError(ImapMcpError):
    def __init__(self, host: str = ""):
        super().__init__(
            ErrorCode.CONNECTION_FAILED,
            f"Connection failed: {host}",
            retriable=True,
            recovery="Check network connectivity and server settings.",
        )


class FolderNotFoundError(ImapMcpError):
    def __init__(self, folder: str):
        super().__init__(ErrorCode.FOLDER_NOT_FOUND, f"Folder not found: {folder}", retriable=False)


class MessageNotFoundError(ImapMcpError):
    def __init__(self, msg_id: str):
        super().__init__(
            ErrorCode.MESSAGE_NOT_FOUND,
            f"Message not found: {msg_id}",
            retriable=False,
            recovery=(
                "If searching by message_id, try specifying folder= to narrow the scan. "
                "If using a ref, it may have been moved or deleted."
            ),
        )


class StaleRefError(ImapMcpError):
    def __init__(self, folder: str):
        super().__init__(
            ErrorCode.STALE_REF,
            f"UIDVALIDITY changed for {folder}",
            retriable=True,
            recovery=(
                "Re-call list_messages or search_emails on this folder to obtain fresh refs. "
                "The original Message-ID header value remains valid as an id parameter."
            ),
        )


class PermissionDeniedError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.PERMISSION_DENIED, f"Permission denied: {detail}", retriable=False)


class ConfirmationRequiredError(ImapMcpError):
    def __init__(self, count: int):
        super().__init__(
            ErrorCode.CONFIRMATION_REQUIRED,
            f"Batch operation on {count} messages requires confirm=true",
            retriable=False,
            recovery="Re-call with confirm=true to proceed, or use dry_run=true to preview.",
        )


class NotConfiguredError(ImapMcpError):
    def __init__(self, feature: str):
        super().__init__(
            ErrorCode.NOT_CONFIGURED,
            f"Feature not configured: {feature}",
            retriable=False,
        )


class ProtocolError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.PROTOCOL_ERROR, f"Protocol error: {detail}", retriable=False)


class TimeoutError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.TIMEOUT, f"Timeout: {detail}", retriable=True)


class RateLimitedError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(
            ErrorCode.RATE_LIMITED,
            f"Rate limited: {detail}",
            retriable=True,
            recovery="Wait a moment before retrying.",
        )
