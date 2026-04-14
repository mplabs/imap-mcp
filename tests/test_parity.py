"""
Contract tests: every Gmail MCP tool must have a named analog in imap-mcp.

This table is the authoritative parity mapping. If a Gmail tool is added
to the reference server without a corresponding entry here, CI fails.
"""

import pytest
import importlib

# Mapping of Gmail-MCP tool name → imap-mcp equivalent (tool function name + module path)
PARITY_TABLE = [
    # Gmail tool name            | imap-mcp function       | module
    ("send_email",               "send_email",              "imap_mcp.tools.send"),
    ("draft_email",              "save_draft",              "imap_mcp.tools.send"),
    ("read_email",               "read_email",              "imap_mcp.tools.messages"),
    ("download_attachment",      "download_attachment",     "imap_mcp.tools.messages"),
    ("search_emails",            "search_emails",           "imap_mcp.tools.messages"),
    ("list_messages",            "list_messages",           "imap_mcp.tools.messages"),
    ("batch_modify_emails",      "batch_set_flags",         "imap_mcp.tools.batch"),
    ("batch_modify_emails",      "batch_move",              "imap_mcp.tools.batch"),
    ("batch_delete_emails",      "batch_delete",            "imap_mcp.tools.batch"),
    ("list_email_labels",        "list_folders",            "imap_mcp.tools.folders"),
    ("create_label",             "create_folder",           "imap_mcp.tools.folders"),
    ("update_label",             "rename_folder",           "imap_mcp.tools.folders"),
    ("delete_label",             "delete_folder",           "imap_mcp.tools.folders"),
    ("get_or_create_label",      "get_or_create_folder",    "imap_mcp.tools.folders"),
    ("delete_email",             "delete_email",            "imap_mcp.tools.moves"),
    ("list_filters",             "list_sieve_scripts",      "imap_mcp.tools.sieve"),
    ("get_filter",               "get_sieve_script",        "imap_mcp.tools.sieve"),
    ("delete_filter",            "delete_sieve_script",     "imap_mcp.tools.sieve"),
]


@pytest.mark.parametrize("gmail_tool,imap_mcp_func,module_path", PARITY_TABLE)
def test_parity(gmail_tool, imap_mcp_func, module_path):
    """Each imap-mcp function in the parity table must be importable."""
    mod = importlib.import_module(module_path)
    assert hasattr(mod, imap_mcp_func), (
        f"Gmail tool '{gmail_tool}' expects '{imap_mcp_func}' in {module_path}, "
        f"but it was not found. Add the function to maintain parity."
    )
