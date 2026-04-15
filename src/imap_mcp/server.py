"""imap-mcp MCP server — stdio (Claude Code) and HTTP (Claude Cowork) transports."""

from __future__ import annotations

import json
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from .accounts import AccountRegistry
from .audit import AuditLog
from .config import load_config, Config
from .context import Context
from .errors import ImapMcpError
from .imap_pool import ImapPool
from .rate_limit import RateLimiter
from .resolver import MessageResolver
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
# Tool catalogue
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
                "cursor": {"type": "string", "description": "Pagination cursor (opaque uid: string)."},
                "order": {"type": "string", "enum": ["newest", "oldest"]},
                "account": {"type": "string"},
            }},
        ),
        types.Tool(
            name="search_emails",
            description=(
                "Search messages. query must be {raw: string} (IMAP SEARCH string) "
                "or {gmail_raw: string} (Gmail IMAP only). "
                "Omit folder to fan out across all subscribed folders (capped at resolver.max_search_folders)."
            ),
            inputSchema={"type": "object", "required": ["query"], "properties": {
                "query": {"type": "object"},
                "folder": {"type": "string", "description": "Omit to search all folders."},
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
                "id": {"type": "string", "description": "message_id (<…>) or ref string (account:folder:uidvalidity:uid)."},
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
                "save_to": {"type": "string", "description": "Absolute path; supports {filename} token."},
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
            description="Delete an IMAP folder. Refuses special-use folders unless force=true.",
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
                "attachments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string", "description": "Absolute path to file."},
                            "filename": {"type": "string"},
                            "mime": {"type": "string"},
                        },
                    },
                },
                "in_reply_to": {"type": "string"},
                "references": {"type": "string"},
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
                "attachments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string", "description": "Absolute path to file."},
                            "filename": {"type": "string"},
                            "mime": {"type": "string"},
                        },
                    },
                },
                "in_reply_to": {"type": "string"},
                "references": {"type": "string"},
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
    """Return the static accounts resource; dynamic per-account resources are
    registered at server startup and served via handle_read_resource."""
    accounts_info = list_accounts(registry)
    resources = [
        types.EmbeddedResource(
            type="resource",
            resource=types.TextResourceContents(
                uri="imap-mcp://accounts",
                text=json.dumps(accounts_info, indent=2),
                mimeType="application/json",
            ),
        ),
    ]
    # Add placeholder entries for per-account resources so they appear in
    # list_resources even though their content is fetched dynamically.
    for name in registry.list_names():
        for suffix in ("folders", "capabilities"):
            resources.append(
                types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(
                        uri=f"imap-mcp://{name}/{suffix}",
                        text="",  # populated on read_resource
                        mimeType="application/json",
                    ),
                )
            )
    return resources


def _fetch_folders_resource(ctx: Context, account: str) -> str:
    """Return a JSON snapshot of the folder tree for one account."""
    import asyncio
    from .tools.folders import list_folders as _list_folders

    async def _get():
        return await _list_folders(ctx, account=account)

    data = asyncio.get_event_loop().run_until_complete(_get())
    return json.dumps(data, indent=2)


def _fetch_capabilities_resource(ctx: Context, account: str) -> str:
    """Return raw IMAP CAPABILITY and SMTP EHLO tokens for one account."""
    from imapclient import IMAPClient as _IMAPClient
    from .config import resolve_secret as _resolve_secret

    _, acc = ctx.registry.resolve(account)

    imap_caps: list[str] = []
    try:
        password = _resolve_secret(acc.imap.auth.secret_ref)
        with _IMAPClient(host=acc.imap.host, port=acc.imap.port, ssl=acc.imap.tls) as client:
            client.login(acc.imap.username, password)
            raw = client.capabilities()
            imap_caps = [c.decode() if isinstance(c, bytes) else c for c in raw]
    except Exception:
        pass

    return json.dumps({"account": account, "imap": imap_caps}, indent=2)


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
# Dispatch table
# ---------------------------------------------------------------------------

def _build_dispatch(ctx: Context, registry: AccountRegistry):
    """Return a dict mapping tool name → async callable(args) → dict."""

    async def _list_accounts(args):
        return list_accounts(registry)

    async def _test_connection(args):
        return await test_connection(registry, account=args.get("account"))

    async def _list_messages(args):
        return await list_messages(
            ctx,
            folder=args.get("folder", "INBOX"),
            limit=args.get("limit", 50),
            cursor=args.get("cursor"),
            order=args.get("order", "newest"),
            account=args.get("account"),
        )

    async def _search_emails(args):
        return await search_emails(
            ctx,
            query=args["query"],
            folder=args.get("folder", "INBOX"),
            limit=args.get("limit", 50),
            cursor=args.get("cursor"),
            order=args.get("order", "newest"),
            account=args.get("account"),
        )

    async def _read_email(args):
        return await read_email(
            ctx,
            id=args["id"],
            include_raw=args.get("include_raw", False),
            account=args.get("account"),
        )

    async def _download_attachment(args):
        return await download_attachment(
            ctx,
            id=args["id"],
            part_id=args["part_id"],
            save_to=args["save_to"],
            account=args.get("account"),
        )

    async def _list_folders(args):
        return await list_folders(ctx, account=args.get("account"))

    async def _folder_status(args):
        return await folder_status(ctx, name=args["name"], account=args.get("account"))

    async def _set_flags(args):
        return await set_flags(
            ctx,
            id=args["id"],
            add=args.get("add", []),
            remove=args.get("remove", []),
            account=args.get("account"),
        )

    async def _mark_read(args):
        return await mark_read(ctx, id=args["id"], account=args.get("account"))

    async def _mark_unread(args):
        return await mark_unread(ctx, id=args["id"], account=args.get("account"))

    async def _star(args):
        return await star(ctx, id=args["id"], account=args.get("account"))

    async def _unstar(args):
        return await unstar(ctx, id=args["id"], account=args.get("account"))

    async def _move_email(args):
        return await move_email(
            ctx, id=args["id"], to_folder=args["to_folder"],
            account=args.get("account"),
        )

    async def _copy_email(args):
        return await copy_email(
            ctx, id=args["id"], to_folder=args["to_folder"],
            account=args.get("account"),
        )

    async def _delete_email(args):
        return await delete_email(
            ctx, id=args["id"], hard=args.get("hard", False),
            account=args.get("account"),
        )

    async def _empty_trash(args):
        return await empty_trash(
            ctx, account=args.get("account"), confirm=args.get("confirm", False),
        )

    async def _create_folder(args):
        return await create_folder(ctx, name=args["name"], account=args.get("account"))

    async def _rename_folder(args):
        return await rename_folder(
            ctx, from_name=args["from_name"], to_name=args["to_name"],
            account=args.get("account"),
        )

    async def _delete_folder(args):
        return await delete_folder(
            ctx, name=args["name"], account=args.get("account"),
            force=args.get("force", False),
        )

    async def _subscribe_folder(args):
        return await subscribe_folder(ctx, name=args["name"], account=args.get("account"))

    async def _unsubscribe_folder(args):
        return await unsubscribe_folder(ctx, name=args["name"], account=args.get("account"))

    async def _send_email(args):
        return await send_email(
            ctx,
            to=args["to"], subject=args["subject"], body=args["body"],
            cc=args.get("cc"), bcc=args.get("bcc"), html=args.get("html"),
            attachments=args.get("attachments"),
            in_reply_to=args.get("in_reply_to"), references=args.get("references"),
            headers=args.get("headers"), account=args.get("account"),
        )

    async def _save_draft(args):
        return await save_draft(
            ctx,
            to=args["to"], subject=args["subject"], body=args["body"],
            cc=args.get("cc"), bcc=args.get("bcc"), html=args.get("html"),
            attachments=args.get("attachments"),
            in_reply_to=args.get("in_reply_to"), references=args.get("references"),
            headers=args.get("headers"), account=args.get("account"),
        )

    async def _batch_set_flags(args):
        return await batch_set_flags(
            ctx, ids=args["ids"],
            add=args.get("add", []), remove=args.get("remove", []),
            account=args.get("account"),
            confirm=args.get("confirm", False), dry_run=args.get("dry_run", False),
        )

    async def _batch_move(args):
        return await batch_move(
            ctx, ids=args["ids"], to_folder=args["to_folder"],
            account=args.get("account"),
            confirm=args.get("confirm", False), dry_run=args.get("dry_run", False),
        )

    async def _batch_delete(args):
        return await batch_delete(
            ctx, ids=args["ids"], hard=args.get("hard", False),
            account=args.get("account"),
            confirm=args.get("confirm", False), dry_run=args.get("dry_run", False),
        )

    async def _get_or_create_folder(args):
        return await get_or_create_folder(ctx, name=args["name"], account=args.get("account"))

    return {
        "list_accounts": _list_accounts,
        "test_connection": _test_connection,
        "list_messages": _list_messages,
        "search_emails": _search_emails,
        "read_email": _read_email,
        "download_attachment": _download_attachment,
        "list_folders": _list_folders,
        "folder_status": _folder_status,
        "set_flags": _set_flags,
        "mark_read": _mark_read,
        "mark_unread": _mark_unread,
        "star": _star,
        "unstar": _unstar,
        "move_email": _move_email,
        "copy_email": _copy_email,
        "delete_email": _delete_email,
        "empty_trash": _empty_trash,
        "create_folder": _create_folder,
        "rename_folder": _rename_folder,
        "delete_folder": _delete_folder,
        "subscribe_folder": _subscribe_folder,
        "unsubscribe_folder": _unsubscribe_folder,
        "send_email": _send_email,
        "save_draft": _save_draft,
        "batch_set_flags": _batch_set_flags,
        "batch_move": _batch_move,
        "batch_delete": _batch_delete,
        "get_or_create_folder": _get_or_create_folder,
    }


# ---------------------------------------------------------------------------
# Per-session resolver isolation
# ---------------------------------------------------------------------------

class _ResolverProxy(MessageResolver):
    """Proxy that delegates to the active session's resolver via a ContextVar.

    Under stdio there is exactly one session so the ContextVar is set once.
    Under HTTP each MCP session gets its own MessageResolver instance; this
    proxy makes the switch transparent to all tool code.
    """

    def __init__(self, var: ContextVar[MessageResolver], default: MessageResolver) -> None:
        # Intentionally skip MessageResolver.__init__ — we forward all calls.
        self._var = var
        self._default = default

    def _active(self) -> MessageResolver:
        try:
            return self._var.get()
        except LookupError:
            return self._default

    def register(self, message_id: str, folder: str, uid: int, uidvalidity: int) -> None:
        self._active().register(message_id, folder, uid, uidvalidity)

    def register_many(self, results: list[dict]) -> None:
        self._active().register_many(results)

    def resolve(self, id: str, pool, account: Optional[str] = None):  # type: ignore[override]
        return self._active().resolve(id, pool, account)


class _SessionServer(Server):
    """Server subclass that creates a fresh MessageResolver per session run."""

    def _init_session_isolation(
        self,
        var: ContextVar[MessageResolver],
        factory: Callable[[], MessageResolver],
    ) -> None:
        self._resolver_var = var
        self._resolver_factory = factory

    async def run(self, read_stream, write_stream, initialization_options):  # type: ignore[override]
        tok = self._resolver_var.set(self._resolver_factory())
        try:
            await super().run(read_stream, write_stream, initialization_options)
        finally:
            self._resolver_var.reset(tok)


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def build_server(registry: AccountRegistry) -> _SessionServer:
    rate_limiter = RateLimiter()
    for acc_name in registry.list_names():
        acc = registry.get(acc_name)
        rate_limiter.configure(acc_name, acc.rate_limit.max_ops_per_minute)

    pool = ImapPool(registry, rate_limiter=rate_limiter)
    audit = AuditLog()
    _, default_acc = registry.resolve(None)
    max_sf = default_acc.resolver.max_search_folders

    resolver_var: ContextVar[MessageResolver] = ContextVar("_session_resolver")

    def resolver_factory() -> MessageResolver:
        return MessageResolver(max_search_folders=max_sf)
    resolver_proxy = _ResolverProxy(resolver_var, resolver_factory())
    ctx = Context(pool=pool, registry=registry, audit=audit, resolver=resolver_proxy)
    dispatch = _build_dispatch(ctx, registry)

    server = _SessionServer("imap-mcp")
    server._init_session_isolation(resolver_var, resolver_factory)

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

        # Static resources
        for emb in _list_resources(registry):
            if str(emb.resource.uri) == uri_str and emb.resource.text:
                return emb.resource.text

        # Dynamic per-account resources: imap-mcp://{account}/{folders|capabilities}
        prefix = "imap-mcp://"
        if uri_str.startswith(prefix):
            path = uri_str[len(prefix):]
            parts = path.split("/", 1)
            if len(parts) == 2:
                acc_name, resource_name = parts
                if resource_name == "folders":
                    return _fetch_folders_resource(ctx, acc_name)
                if resource_name == "capabilities":
                    return _fetch_capabilities_resource(ctx, acc_name)

        raise ValueError(f"Resource not found: {uri}")

    @server.list_prompts()
    async def handle_list_prompts() -> list[types.Prompt]:
        return _list_prompts()

    @server.get_prompt()
    async def handle_get_prompt(
        name: str, arguments: Optional[dict] = None
    ) -> types.GetPromptResult:
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
        handler = dispatch.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")
        try:
            result = await handler(arguments)
        except ImapMcpError as exc:
            result = exc.to_dict()
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def run_stdio(cfg: Config) -> None:
    """Run the server over stdio (for Claude Code and local tooling)."""
    registry = AccountRegistry(cfg)
    server = build_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_http(
    cfg: Optional[Config],
    config_path: str,
    host: str = "0.0.0.0",
    port: int = 8000,
    issuer_url: Optional[str] = None,
) -> None:
    """Run the server over streamable HTTP with OAuth setup wizard.

    If cfg is None (no config file yet), the MCP tools return a helpful
    "not configured" error. The setup wizard at /setup is always accessible
    and does not require authentication.
    """
    import contextlib
    import logging

    import uvicorn
    from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
    from mcp.server.auth.provider import ProviderTokenVerifier
    from mcp.server.auth.routes import create_auth_routes
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from pydantic import AnyHttpUrl
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.authentication import AuthenticationMiddleware
    from starlette.routing import Mount

    from .oauth_provider import JsonFileOAuthProvider
    from .setup_wizard import create_setup_routes, load_or_create_setup_key

    logger = logging.getLogger(__name__)

    # Build MCP server (works even without a config — tools fail gracefully)
    if cfg is not None:
        registry = AccountRegistry(cfg)
        mcp_server = build_server(registry)
    else:
        # No config yet: start a bare server so OAuth + setup wizard work.
        # All tool calls return NOT_CONFIGURED until setup completes.
        mcp_server = _SessionServer("imap-mcp")
        _noop_var: ContextVar[MessageResolver] = ContextVar("_noop_resolver")

        def _noop_factory() -> MessageResolver:
            return MessageResolver()

        mcp_server._init_session_isolation(_noop_var, _noop_factory)

        @mcp_server.list_tools()
        async def _no_tools() -> list[types.Tool]:
            return []

        @mcp_server.call_tool()
        async def _no_call(name: str, arguments: dict) -> list[types.TextContent]:
            from .errors import NotConfiguredError
            err = NotConfiguredError(
                "imap-mcp has not been configured yet. "
                "Complete setup at /setup to add your mail account."
            )
            return [types.TextContent(type="text", text=json.dumps(err.to_dict()))]

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        session_idle_timeout=1800,
    )

    # OAuth provider + setup wizard
    auth_provider = JsonFileOAuthProvider()
    token_verifier = ProviderTokenVerifier(auth_provider)
    setup_key = load_or_create_setup_key()

    # Determine issuer URL
    effective_issuer = issuer_url or (cfg.server.issuer_url if cfg else "") or f"http://{host}:{port}"
    issuer = AnyHttpUrl(effective_issuer)

    auth_routes = create_auth_routes(
        provider=auth_provider,
        issuer_url=issuer,
    )
    wizard_routes = create_setup_routes(
        auth_provider=auth_provider,
        config_path=Path(config_path),
        setup_key=setup_key,
    )

    async def mcp_asgi(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    mcp_with_auth = RequireAuthMiddleware(mcp_asgi, required_scopes=[])

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    app = Starlette(
        lifespan=lifespan,
        routes=[
            *auth_routes,
            *wizard_routes,
            Mount("/mcp", app=mcp_with_auth),
        ],
        middleware=[
            Middleware(
                AuthenticationMiddleware,
                backend=BearerAuthBackend(token_verifier),
            ),
        ],
    )

    timeout = cfg.server.request_timeout_s if cfg else 60
    uv_config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        timeout_keep_alive=timeout,
        log_level="info",
    )
    uv_server = uvicorn.Server(uv_config)

    logger.info("imap-mcp HTTP server starting on %s:%d", host, port)
    logger.info("Setup wizard: http://%s:%d/setup", host, port)
    logger.info("Setup key: %s", setup_key)
    # Also print to stdout so it's visible even without log config
    print(f"\n  imap-mcp setup key: {setup_key}\n", flush=True)

    await uv_server.serve()


def main() -> None:
    import argparse
    import asyncio
    import os

    parser = argparse.ArgumentParser(description="imap-mcp MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport to use (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind host for HTTP transport (overrides config)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port for HTTP transport (overrides config)",
    )
    parser.add_argument(
        "--issuer-url",
        default=None,
        dest="issuer_url",
        help="OAuth issuer URL for HTTP transport (e.g. https://your-server.example.com)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config file (overrides IMAP_MCP_CONFIG env var)",
    )
    args = parser.parse_args()

    if args.transport == "http":
        # HTTP mode: config is optional (setup wizard creates it if missing)
        cfg = load_config(args.config, optional=True)

        config_path = (
            args.config
            or os.environ.get("IMAP_MCP_CONFIG")
            or str(Path.home() / ".config" / "imap-mcp" / "config.yaml")
        )

        server_cfg = cfg.server if cfg else None
        host = args.host or (server_cfg.host if server_cfg else "0.0.0.0")
        port = args.port or (server_cfg.port if server_cfg else 8000)
        issuer_url = args.issuer_url or (server_cfg.issuer_url if server_cfg else None)

        asyncio.run(run_http(cfg, config_path, host=host, port=port, issuer_url=issuer_url or None))
    else:
        cfg = load_config(args.config)
        asyncio.run(run_stdio(cfg))
