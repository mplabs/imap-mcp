"""Tests for folder CRUD tools (create, rename, delete)."""

import pytest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

from imap_mcp.tools.folders import create_folder, rename_folder, delete_folder
from imap_mcp.errors import PermissionDeniedError


def _patch_acquire(ctx, mock_conn):
    @contextmanager
    def fake_acquire(account, folder, readonly=True):
        yield mock_conn

    return patch.object(ctx.pool, "acquire", side_effect=fake_acquire)


@pytest.fixture
def mock_conn_with_folders(mock_conn):
    mock_conn.client.list_folders.return_value = [
        ((b"\\HasNoChildren",), b".", "INBOX"),
        ((b"\\HasNoChildren", b"\\Sent"), b".", "Sent"),
    ]
    return mock_conn


class TestCreateFolder:
    @pytest.mark.asyncio
    async def test_creates_on_server(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await create_folder(ctx, name="Projects", account="personal")

        mock_conn.client.create_folder.assert_called_once_with("Projects")
        assert result["success"] is True
        assert result["name"] == "Projects"


class TestRenameFolder:
    @pytest.mark.asyncio
    async def test_renames_on_server(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await rename_folder(
                ctx, from_name="OldName", to_name="NewName", account="personal"
            )

        mock_conn.client.rename_folder.assert_called_once_with("OldName", "NewName")
        assert result["success"] is True


class TestDeleteFolder:
    @pytest.mark.asyncio
    async def test_deletes_ordinary_folder(self, ctx, mock_conn_with_folders):
        with _patch_acquire(ctx, mock_conn_with_folders):
            result = await delete_folder(
                ctx, name="OldProjects", account="personal"
            )

        mock_conn_with_folders.client.delete_folder.assert_called_once_with("OldProjects")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_refuses_protected_name(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            with pytest.raises(PermissionDeniedError):
                await delete_folder(ctx, name="INBOX", account="personal")

    @pytest.mark.asyncio
    async def test_force_deletes_protected(self, ctx, mock_conn):
        with _patch_acquire(ctx, mock_conn):
            result = await delete_folder(
                ctx, name="INBOX", account="personal", force=True
            )

        mock_conn.client.delete_folder.assert_called_once_with("INBOX")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_refuses_special_use_flag(self, ctx, mock_conn):
        # Sent has \\Sent special-use flag
        mock_conn.client.list_folders.return_value = [
            ((b"\\HasNoChildren", b"\\Sent"), b".", "Sent"),
        ]

        with _patch_acquire(ctx, mock_conn):
            with pytest.raises(PermissionDeniedError):
                await delete_folder(ctx, name="Sent", account="personal")
