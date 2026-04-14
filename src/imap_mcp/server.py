"""imap-mcp MCP server — stdio transport."""

from __future__ import annotations

import os
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from .config import load_config
from .accounts import AccountRegistry
from .tools.admin import list_accounts, test_connection


def build_server(registry: AccountRegistry) -> Server:
    server = Server("imap-mcp")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="list_accounts",
                description="List all configured IMAP accounts and their server details (no secrets).",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            types.Tool(
                name="test_connection",
                description="Test IMAP connectivity for an account by performing LOGIN/NOOP/LOGOUT.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account": {
                            "type": "string",
                            "description": "Account name (defaults to default_account if omitted).",
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name == "list_accounts":
            result = list_accounts(registry)
        elif name == "test_connection":
            result = await test_connection(registry, account=arguments.get("account"))
        else:
            raise ValueError(f"Unknown tool: {name}")

        import json
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def run():
    cfg = load_config()
    registry = AccountRegistry(cfg)
    server = build_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    import asyncio
    asyncio.run(run())
