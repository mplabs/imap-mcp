"""imap-mcp MCP server — stdio transport."""

from __future__ import annotations

import json
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from .accounts import AccountRegistry
from .audit import AuditLog
from .config import load_config, resolve_secret
from .imap_pool import ImapPool
from .tools.admin import list_accounts, test_connection
from .tools.batch import batch_set_flags, batch_move, batch_delete
from .tools.flags import set_flags, mark_read, mark_unread, star, unstar
from .tools.folders import (
    list_folders, folder_status, create_folder, rename_folder,
    delete_folder, get_or_create_folder, subscribe_folder, unsubscribe_folder,
)
from .tools.messages import list_messages, search_emails, read_email, download_attachment
from .tools.moves import move_email, copy_email, delete_email, empty_trash
from .tools.send import send_email, save_draft


# ---------------------------------------------------------------------------
# Tool catalogue — used both for list_tools and call_tool dispatch
# ---------------------------------------------------------------------------

def _list_tools(registry: AccountRegistry) -> list[types.Tool]:
    """Return the full list of MCP Tool definitions."""
    return [
        # M0 admin
        types.Tool(
            name="list_accounts",
            description="List all configured IMAP accounts and their server details (no secrets).",
            inputSchema={"type": "object", "properties": {
                "account": {"type": "string", "description": "Unused; included for API uniformity."},
            }},
        ),
        types.Tool(
            name="test_connection",
            description="Test IMAP connectivity for an account (LOGIN/NOOP/LOGOUT round-trip).",
            inputSchema={"type": "object", "properties": {
                "account": {"type": "string", "description": "Account name (default: default_account)."},
            }},
        ),
        # M1 read path
        types.Tool(
            name="list_messages",
            description="List the most-recent messages in a folder.",
            inputSchema={"type": "object", "properties": {
                "folder": {"type": "string", "description": "Folder name (default: INBOX)."},
                "limit": {"type": "integer", "description": "Max results (default 50, max 500)."},
                "cursor": {"type": "string", "description": "Pagination cursor."},
                "order": {"type": "string", "enum": ["newest", "oldest"]},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="search_emails",
            description=(
                "Search messages. query may be {raw: string} (IMAP SEARCH string), "
                "{structured: {from,to,subject,body,since,before,unseen,flagged,...}}, "
                "or {gmail_raw: string} (Gmail IMAP only)."
            ),
            inputSchema={"type": "object", "required": ["query"], "properties": {
                "query": {"type": "object"},
                "folder": {"type": "string"},
                "limit": {"type": "integer"},
                "cursor": {"type": "string"},
                "order": {"type": "string", "enum": ["newest", "oldest"]},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="read_email",
            description="Fetch full message content (headers, text/html body, attachment manifest).",
            inputSchema={"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string", "description": "message_id or ref string."},
                "include_raw": {"type": "boolean"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="download_attachment",
            description="Download a specific MIME part from a message to disk.",
            inputSchema={"type": "object", "required": ["id", "part_id", "save_to"], "properties": {
                "id": {"type": "string"},
                "part_id": {"type": "string"},
                "save_to": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="list_folders",
            description="List all IMAP folders on the server (name, flags, delimiter).",
            inputSchema={"type": "object", "properties": {
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="folder_status",
            description="Return message counts (exists, unseen, recent) for a folder.",
            inputSchema={"type": "object", "required": ["name"], "properties": {
                "name": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        # M2 write path — flags
        types.Tool(
            name="set_flags",
            description="Add and/or remove IMAP flags on a message.",
            inputSchema={"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string"},
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="mark_read",
            description="Mark a message as read (sets \\Seen flag).",
            inputSchema={"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="mark_unread",
            description="Mark a message as unread (removes \\Seen flag).",
            inputSchema={"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="star",
            description="Star a message (sets \\Flagged flag).",
            inputSchema={"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="unstar",
            description="Unstar a message (removes \\Flagged flag).",
            inputSchema={"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        # M2 write path — moves
        types.Tool(
            name="move_email",
            description="Move a message to another folder (COPY + DELETE source).",
            inputSchema={"type": "object", "required": ["id", "to_folder"], "properties": {
                "id": {"type": "string"},
                "to_folder": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="copy_email",
            description="Copy a message to another folder (source untouched).",
            inputSchema={"type": "object", "required": ["id", "to_folder"], "properties": {
                "id": {"type": "string"},
                "to_folder": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="delete_email",
            description=(
                "Delete a message. By default moves to Trash (soft delete). "
                "Pass hard=true to permanently expunge (requires safety.allow_delete=true)."
            ),
            inputSchema={"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string"},
                "hard": {"type": "boolean"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="empty_trash",
            description=(
                "Permanently delete all messages in the Trash folder. "
                "Requires safety.allow_empty_trash=true in config and confirm=true."
            ),
            inputSchema={"type": "object", "required": ["confirm"], "properties": {
                "confirm": {"type": "boolean"},
                "account": {"type": "string"},
            }},
        ),
        # M2 folder CRUD
        types.Tool(
            name="create_folder",
            description="Create a new IMAP folder.",
            inputSchema={"type": "object", "required": ["name"], "properties": {
                "name": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="rename_folder",
            description="Rename an IMAP folder.",
            inputSchema={"type": "object", "required": ["from_name", "to_name"], "properties": {
                "from_name": {"type": "string"},
                "to_name": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="delete_folder",
            description=(
                "Delete an IMAP folder. Refuses special-use folders unless force=true."
            ),
            inputSchema={"type": "object", "required": ["name"], "properties": {
                "name": {"type": "string"},
                "force": {"type": "boolean"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="subscribe_folder",
            description="Subscribe to an IMAP folder.",
            inputSchema={"type": "object", "required": ["name"], "properties": {
                "name": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="unsubscribe_folder",
            description="Unsubscribe from an IMAP folder.",
            inputSchema={"type": "object", "required": ["name"], "properties": {
                "name": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
        # M3 outbound
        types.Tool(
            name="send_email",
            description="Send an email via SMTP and append a copy to the Sent folder.",
            inputSchema={"type": "object", "required": ["to", "subject", "body"], "properties": {
                "to": {"type": "array", "items": {"type": "string"}},
                "cc": {"type": "array", "items": {"type": "string"}},
                "bcc": {"type": "array", "items": {"type": "string"}},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "html": {"type": "string"},
                "in_reply_to": {"type": "string"},
                "headers": {"type": "object"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="save_draft",
            description="Save a draft message to the Drafts folder without sending.",
            inputSchema={"type": "object", "required": ["to", "subject", "body"], "properties": {
                "to": {"type": "array", "items": {"type": "string"}},
                "cc": {"type": "array", "items": {"type": "string"}},
                "bcc": {"type": "array", "items": {"type": "string"}},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "html": {"type": "string"},
                "in_reply_to": {"type": "string"},
                "headers": {"type": "object"},
                "account": {"type": "string"},
            }},
        ),
        # M4 batch
        types.Tool(
            name="batch_set_flags",
            description=(
                "Add/remove flags on multiple messages. Batches over the confirm_batch_threshold "
                "require confirm=true."
            ),
            inputSchema={"type": "object", "required": ["ids"], "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
                "confirm": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="batch_move",
            description="Move multiple messages to a target folder.",
            inputSchema={"type": "object", "required": ["ids", "to_folder"], "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "to_folder": {"type": "string"},
                "confirm": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="batch_delete",
            description="Delete multiple messages (soft or hard).",
            inputSchema={"type": "object", "required": ["ids"], "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "hard": {"type": "boolean"},
                "confirm": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="get_or_create_folder",
            description="Return a folder by name, creating it if it does not exist.",
            inputSchema={"type": "object", "required": ["name"], "properties": {
                "name": {"type": "string"},
                "account": {"type": "string"},
            }},
        ),
    ]


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

def _list_resources(registry: AccountRegistry) -> list[types.EmbeddedResource]:
    """Return static MCP resources for agent reference."""
    accounts_info = list_accounts(registry)
    return [
        types.EmbeddedResource(
            type="resource",
            resource=types.TextResourceContents(
                uri="imap-mcp://accounts",
                text=json.dumps(accounts_info, indent=2),
                mimeType="application/json",
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="triage_inbox",
            description=(
                "Walk the inbox, summarize each message, propose moves/flags, "
                "then await confirmation before any write operation."
            ),
            arguments=[
                types.PromptArgument(
                    name="account",
                    description="Account to triage (default: default_account)",
                    required=False,
                ),
            ],
        ),
        types.Prompt(
            name="compose_reply",
            description=(
                "Given a message_id, read the original message and save a reply draft."
            ),
            arguments=[
                types.PromptArgument(
                    name="message_id",
                    description="The Message-ID of the message to reply to.",
                    required=True,
                ),
                types.PromptArgument(
                    name="account",
                    description="Account name",
                    required=False,
                ),
            ],
        ),
        types.Prompt(
            name="unsubscribe_sweep",
            description=(
                "Find list/newsletter mail, extract List-Unsubscribe headers, "
                "and report them. Never auto-clicks or auto-unsubscribes."
            ),
            arguments=[
                types.PromptArgument(
                    name="account",
                    description="Account name",
                    required=False,
                ),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def build_server(registry: AccountRegistry) -> Server:
    pool = ImapPool(registry)
    audit = AuditLog()
    server = Server("imap-mcp")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return _list_tools(registry)

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        out = []
        for emb in _list_resources(registry):
            out.append(types.Resource(
                uri=emb.resource.uri,
                name=str(emb.resource.uri),
                mimeType=emb.resource.mimeType,
            ))
        return out

    @server.read_resource()
    async def handle_read_resource(uri) -> str:
        uri_str = str(uri)
        for emb in _list_resources(registry):
            if str(emb.resource.uri) == uri_str:
                return emb.resource.text
        raise ValueError(f"Resource not found: {uri}")

    @server.list_prompts()
    async def handle_list_prompts() -> list[types.Prompt]:
        return _list_prompts()

    @server.get_prompt()
    async def handle_get_prompt(name: str, arguments: Optional[dict] = None) -> types.GetPromptResult:
        prompts = {p.name: p for p in _list_prompts()}
        if name not in prompts:
            raise ValueError(f"Prompt not found: {name}")
        args = arguments or {}

        if name == "triage_inbox":
            account = args.get("account", registry.default_name)
            messages = [types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=(
                        f"Please triage my inbox for account '{account}'.\n"
                        "1. Use list_messages to fetch the 20 most recent messages.\n"
                        "2. For each, use read_email to get the full content.\n"
                        "3. Summarize each message and propose an action (move, flag, delete).\n"
                        "4. List your proposals and wait for my confirmation before writing anything."
                    ),
                ),
            )]
        elif name == "compose_reply":
            message_id = args.get("message_id", "")
            account = args.get("account", registry.default_name)
            messages = [types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=(
                        f"Please compose a reply to message '{message_id}' on account '{account}'.\n"
                        "1. Use read_email to fetch the original message.\n"
                        "2. Draft a reply and use save_draft to save it to Drafts.\n"
                        "3. Report the draft ref so I can review it."
                    ),
                ),
            )]
        elif name == "unsubscribe_sweep":
            account = args.get("account", registry.default_name)
            messages = [types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=(
                        f"Please find newsletter/list mail for account '{account}'.\n"
                        "1. Use search_emails with criteria like 'FROM list OR HEADER List-Unsubscribe'.\n"
                        "2. For each match, extract the List-Unsubscribe header value.\n"
                        "3. Report a table of senders + unsubscribe links.\n"
                        "Do NOT click any links or take any action without my explicit instruction."
                    ),
                ),
            )]
        else:
            messages = []

        return types.GetPromptResult(messages=messages)

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        acc = arguments.get("account")
        result = await _dispatch_tool(name, arguments, registry, pool, audit)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def _dispatch_tool(
    name: str,
    args: dict,
    registry: AccountRegistry,
    pool: ImapPool,
    audit: AuditLog,
) -> dict:
    """Dispatch a tool call to the appropriate handler."""
    # M0 admin
    if name == "list_accounts":
        return list_accounts(registry)
    if name == "test_connection":
        return await test_connection(registry, account=args.get("account"))

    # M1 read
    if name == "list_messages":
        return await list_messages(
            pool,
            account=args.get("account"),
            folder=args.get("folder", "INBOX"),
            limit=args.get("limit", 50),
            cursor=args.get("cursor"),
            order=args.get("order", "newest"),
        )
    if name == "search_emails":
        return await search_emails(
            pool,
            query=args["query"],
            account=args.get("account"),
            folder=args.get("folder", "INBOX"),
            limit=args.get("limit", 50),
            cursor=args.get("cursor"),
            order=args.get("order", "newest"),
        )
    if name == "read_email":
        return await read_email(
            pool,
            id=args["id"],
            account=args.get("account"),
            include_raw=args.get("include_raw", False),
        )
    if name == "download_attachment":
        return await download_attachment(
            pool,
            id=args["id"],
            part_id=args["part_id"],
            save_to=args["save_to"],
            account=args.get("account"),
        )
    if name == "list_folders":
        return await list_folders(pool, account=args.get("account"))
    if name == "folder_status":
        return await folder_status(pool, name=args["name"], account=args.get("account"))

    # M2 flags
    if name == "set_flags":
        return await set_flags(
            pool,
            id=args["id"],
            add=args.get("add", []),
            remove=args.get("remove", []),
            account=args.get("account"),
            audit=audit,
        )
    if name == "mark_read":
        return await mark_read(pool, id=args["id"], account=args.get("account"), audit=audit)
    if name == "mark_unread":
        return await mark_unread(pool, id=args["id"], account=args.get("account"), audit=audit)
    if name == "star":
        return await star(pool, id=args["id"], account=args.get("account"), audit=audit)
    if name == "unstar":
        return await unstar(pool, id=args["id"], account=args.get("account"), audit=audit)

    # M2 moves
    if name == "move_email":
        return await move_email(
            pool, id=args["id"], to_folder=args["to_folder"],
            account=args.get("account"), audit=audit,
        )
    if name == "copy_email":
        return await copy_email(
            pool, id=args["id"], to_folder=args["to_folder"],
            account=args.get("account"), audit=audit,
        )
    if name == "delete_email":
        return await delete_email(
            pool, id=args["id"], hard=args.get("hard", False),
            account=args.get("account"), audit=audit, registry=registry,
        )
    if name == "empty_trash":
        return await empty_trash(
            pool, account=args.get("account"), confirm=args.get("confirm", False),
            audit=audit, registry=registry,
        )

    # M2 folder CRUD
    if name == "create_folder":
        return await create_folder(
            pool, name=args["name"], account=args.get("account"), audit=audit
        )
    if name == "rename_folder":
        return await rename_folder(
            pool, from_name=args["from_name"], to_name=args["to_name"],
            account=args.get("account"), audit=audit,
        )
    if name == "delete_folder":
        return await delete_folder(
            pool, name=args["name"], account=args.get("account"),
            force=args.get("force", False), audit=audit,
        )
    if name == "get_or_create_folder":
        return await get_or_create_folder(
            pool, name=args["name"], account=args.get("account"), audit=audit
        )
    if name == "subscribe_folder":
        return await subscribe_folder(pool, name=args["name"], account=args.get("account"))
    if name == "unsubscribe_folder":
        return await unsubscribe_folder(pool, name=args["name"], account=args.get("account"))

    # M3 outbound
    if name == "send_email":
        return await send_email(
            pool, registry=registry,
            to=args["to"], subject=args["subject"], body=args["body"],
            cc=args.get("cc"), bcc=args.get("bcc"), html=args.get("html"),
            in_reply_to=args.get("in_reply_to"), headers=args.get("headers"),
            account=args.get("account"), audit=audit,
        )
    if name == "save_draft":
        return await save_draft(
            pool, registry=registry,
            to=args["to"], subject=args["subject"], body=args["body"],
            cc=args.get("cc"), bcc=args.get("bcc"), html=args.get("html"),
            in_reply_to=args.get("in_reply_to"), headers=args.get("headers"),
            account=args.get("account"), audit=audit,
        )

    # M4 batch
    if name == "batch_set_flags":
        return await batch_set_flags(
            pool, ids=args["ids"],
            add=args.get("add", []), remove=args.get("remove", []),
            account=args.get("account"), audit=audit, registry=registry,
            confirm=args.get("confirm", False), dry_run=args.get("dry_run", False),
        )
    if name == "batch_move":
        return await batch_move(
            pool, ids=args["ids"], to_folder=args["to_folder"],
            account=args.get("account"), audit=audit, registry=registry,
            confirm=args.get("confirm", False), dry_run=args.get("dry_run", False),
        )
    if name == "batch_delete":
        return await batch_delete(
            pool, ids=args["ids"], hard=args.get("hard", False),
            account=args.get("account"), audit=audit, registry=registry,
            confirm=args.get("confirm", False), dry_run=args.get("dry_run", False),
        )

    raise ValueError(f"Unknown tool: {name}")


async def run():
    cfg = load_config()
    registry = AccountRegistry(cfg)
    server = build_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    import asyncio
    asyncio.run(run())
