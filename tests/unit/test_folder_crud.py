"""Tests for folder CRUD tools (create, rename, delete)."""

import pytest
from unittest.mock import patch, MagicMock

from imap_mcp.tools.folders import create_folder, rename_folder, delete_folder
from imap_mcp.imap_pool import ImapPool
from imap_mcp.audit import AuditLog


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.select_folder = MagicMock(return_value={b"UIDVALIDITY": 1000})
    client.create_folder = MagicMock()
    client.rename_folder = MagicMock()
    client.delete_folder = MagicMock()
    client.list_folders = MagicMock(return_value=[
        ((b"\\HasNoChildren",), b".", "INBOX"),
        ((b"\\HasNoChildren", b"\\Sent"), b".", "Sent"),
    ])
    return client


@pytest.fixture
def pool(base_registry):
    return ImapPool(base_registry)


@pytest.fixture
def audit(tmp_path):
    return AuditLog(str(tmp_path / "audit.log"))


class TestCreateFolder:
    @pytest.mark.asyncio
    async def test_creates_on_server(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await create_folder(
                pool, name="Projects", account="personal", audit=audit
            )

        mock_client.create_folder.assert_called_once_with("Projects")
        assert result["success"] is True
        assert result["name"] == "Projects"


class TestRenameFolder:
    @pytest.mark.asyncio
    async def test_renames_on_server(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await rename_folder(
                pool, from_name="OldName", to_name="NewName",
                account="personal", audit=audit
            )

        mock_client.rename_folder.assert_called_once_with("OldName", "NewName")
        assert result["success"] is True


class TestDeleteFolder:
    @pytest.mark.asyncio
    async def test_deletes_ordinary_folder(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await delete_folder(
                pool, name="OldProjects", account="personal", audit=audit
            )

        mock_client.delete_folder.assert_called_once_with("OldProjects")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_refuses_special_use_folder(self, pool, mock_client, audit):
        from imap_mcp.errors import PermissionDeniedError
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(PermissionDeniedError):
                await delete_folder(
                    pool, name="INBOX", account="personal", audit=audit
                )

    @pytest.mark.asyncio
    async def test_force_deletes_special_use(self, pool, mock_client, audit):
        with patch.object(pool, "acquire") as mock_acquire:
            mock_acquire.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_acquire.return_value.__exit__ = MagicMock(return_value=False)

            result = await delete_folder(
                pool, name="INBOX", account="personal", force=True, audit=audit
            )

        mock_client.delete_folder.assert_called_once_with("INBOX")
        assert result["success"] is True
