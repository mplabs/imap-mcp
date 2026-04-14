"""Structured error types for imap-mcp."""

from __future__ import annotations

from enum import Enum


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
    def __init__(self, code: ErrorCode, message: str, retriable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retriable = retriable

    def to_dict(self) -> dict:
        return {
            "code": self.code.value,
            "message": self.message,
            "retriable": self.retriable,
        }


class AuthFailedError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.AUTH_FAILED, f"Authentication failed: {detail}", retriable=False)


class ConnectionFailedError(ImapMcpError):
    def __init__(self, host: str = ""):
        super().__init__(ErrorCode.CONNECTION_FAILED, f"Connection failed: {host}", retriable=True)


class FolderNotFoundError(ImapMcpError):
    def __init__(self, folder: str):
        super().__init__(ErrorCode.FOLDER_NOT_FOUND, f"Folder not found: {folder}", retriable=False)


class MessageNotFoundError(ImapMcpError):
    def __init__(self, msg_id: str):
        super().__init__(ErrorCode.MESSAGE_NOT_FOUND, f"Message not found: {msg_id}", retriable=False)


class StaleRefError(ImapMcpError):
    def __init__(self, folder: str):
        super().__init__(ErrorCode.STALE_REF, f"UIDVALIDITY changed for {folder}", retriable=True)


class PermissionDeniedError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.PERMISSION_DENIED, f"Permission denied: {detail}", retriable=False)


class ConfirmationRequiredError(ImapMcpError):
    def __init__(self, count: int):
        super().__init__(
            ErrorCode.CONFIRMATION_REQUIRED,
            f"Batch operation on {count} messages requires confirm=true",
            retriable=False,
        )


class NotConfiguredError(ImapMcpError):
    def __init__(self, feature: str):
        super().__init__(ErrorCode.NOT_CONFIGURED, f"Feature not configured: {feature}", retriable=False)


class ProtocolError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.PROTOCOL_ERROR, f"Protocol error: {detail}", retriable=False)


class TimeoutError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.TIMEOUT, f"Timeout: {detail}", retriable=True)


class RateLimitedError(ImapMcpError):
    def __init__(self, detail: str = ""):
        super().__init__(ErrorCode.RATE_LIMITED, f"Rate limited: {detail}", retriable=True)
