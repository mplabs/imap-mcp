"""Tests for the MCP server wiring: tools, resources, and prompts."""

import json
import os
import textwrap
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from mcp import types

from imap_mcp.config import load_config
from imap_mcp.accounts import AccountRegistry
from imap_mcp.server import build_server, _list_tools, _list_resources, _list_prompts


YAML = textwrap.dedent("""\
    default_account: personal

    accounts:
      personal:
        imap:
          host: imap.fastmail.com
          port: 993
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        smtp:
          host: smtp.fastmail.com
          port: 465
          tls: true
          username: me@example.com
          auth:
            method: password
            secret_ref: "env:IMAP_PERSONAL_PASS"
        identity:
          from: "Me <me@example.com>"
""")


@pytest.fixture
def registry(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(YAML)
    with patch.dict(os.environ, {"IMAP_PERSONAL_PASS": "secret"}):
        cfg = load_config(str(p))
    return AccountRegistry(cfg)


class TestToolList:
    """Test the list of tools registered in the server."""

    def _names(self, registry):
        tools = _list_tools(registry)
        return {t.name for t in tools}

    def test_m0_tools(self, registry):
        names = self._names(registry)
        assert "list_accounts" in names
        assert "test_connection" in names

    def test_m1_tools(self, registry):
        names = self._names(registry)
        assert "list_messages" in names
        assert "search_emails" in names
        assert "read_email" in names
        assert "list_folders" in names
        assert "folder_status" in names

    def test_m2_tools(self, registry):
        names = self._names(registry)
        assert "set_flags" in names
        assert "mark_read" in names
        assert "mark_unread" in names
        assert "star" in names
        assert "unstar" in names
        assert "move_email" in names
        assert "copy_email" in names
        assert "delete_email" in names
        assert "empty_trash" in names
        assert "create_folder" in names
        assert "rename_folder" in names
        assert "delete_folder" in names

    def test_m3_tools(self, registry):
        names = self._names(registry)
        assert "send_email" in names
        assert "save_draft" in names

    def test_m4_tools(self, registry):
        names = self._names(registry)
        assert "batch_set_flags" in names
        assert "batch_move" in names
        assert "batch_delete" in names
        assert "get_or_create_folder" in names

    def test_all_tools_have_descriptions(self, registry):
        tools = _list_tools(registry)
        for tool in tools:
            assert tool.description, f"Tool '{tool.name}' has no description"

    def test_all_tools_have_input_schema(self, registry):
        tools = _list_tools(registry)
        for tool in tools:
            assert tool.inputSchema, f"Tool '{tool.name}' has no inputSchema"


class TestResources:
    def test_accounts_resource_present(self, registry):
        resources = _list_resources(registry)
        uris = {str(r.resource.uri) for r in resources}
        assert "imap-mcp://accounts" in uris

    def test_accounts_resource_content(self, registry):
        resources = _list_resources(registry)
        accounts_res = next(r for r in resources if str(r.resource.uri) == "imap-mcp://accounts")
        data = json.loads(accounts_res.resource.text)
        assert "accounts" in data
        assert data["accounts"][0]["name"] == "personal"

    def test_no_secrets_in_resources(self, registry):
        resources = _list_resources(registry)
        for res in resources:
            if hasattr(res.resource, "text") and res.resource.text:
                assert "secret" not in res.resource.text.lower()


class TestPrompts:
    def test_all_starter_prompts_present(self, registry):
        prompts = _list_prompts()
        prompt_names = {p.name for p in prompts}
        assert "triage_inbox" in prompt_names
        assert "compose_reply" in prompt_names
        assert "unsubscribe_sweep" in prompt_names

    def test_prompts_have_descriptions(self):
        prompts = _list_prompts()
        for p in prompts:
            assert p.description, f"Prompt '{p.name}' has no description"


class TestServerBuilds:
    def test_build_server_returns_server(self, registry):
        server = build_server(registry)
        assert server is not None
        assert server.name == "imap-mcp"
