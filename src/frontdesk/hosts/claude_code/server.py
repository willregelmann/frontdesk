"""The MCP channel server Claude Code spawns for a session."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage

from frontdesk import Desk, DeskError, tools, wire
from frontdesk.hosts.claude_code import sessions
from frontdesk.offers import attach, load_catalog
from frontdesk.wire import Arrival

logger = logging.getLogger("frontdesk.claude_code")

CHANNEL_METHOD = "notifications/claude/channel"
INSTRUCTIONS = tools.INSTRUCTIONS + """
In Claude Code you can be reached only while a session is open. Messages sent to you while it is
closed wait, and are shown when the conversation is next active. Messages to your default channel
wait until you bring one into a conversation with `adopt`.
"""


class ClaudeCodeHost:
    """Wakes the open session by pushing a channel event. It cannot start a conversation."""

    def __init__(self, desk: Desk, home: Path):
        self.desk, self.home = desk, home
        self.session: Optional[ServerSession] = None

    async def wake(self, conversation: str) -> None:
        if self.session is None or conversation != sessions.current(self.home):
            return   # that conversation is not the open one: its messages wait for it
        arrivals = await self.desk.take(conversation, mark=False)
        if not arrivals:
            return
        params = {"content": "\n\n".join(wire.render(a) for a in arrivals),
                  "meta": {"count": str(len(arrivals)), "from": arrivals[0].sender_name}}
        notification = types.JSONRPCNotification(jsonrpc="2.0", method=CHANNEL_METHOD, params=params)
        await self.session._write_stream.send(SessionMessage(message=types.JSONRPCMessage(notification)))

    async def start(self, arrival: Arrival) -> Optional[str]:
        return None


def build(desk: Optional[Desk], home: Path, catalog: tools.Catalog) -> Server:
    server: Server = Server("frontdesk", instructions=INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name=t["name"], description=t["description"], inputSchema=t["input"]) for t in tools.TOOLS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if desk is None:
            result = {"error": f"no identity has joined the desk from {home}. Run: frontdesk join <name> "
                               "--answerable <person>"}
        else:
            result = await tools.call(desk, sessions.current(home), name, arguments, catalog)
        return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    return server


async def _attend(desk: Desk, host: ClaudeCodeHost, home: Path, catalog: tools.Catalog) -> None:
    """Stay at the desk for whichever session this process currently serves."""
    attached = False
    while True:
        session = sessions.current(home)
        if session is None:
            await asyncio.sleep(0.5)   # the SessionStart hook has not run yet
            continue
        try:
            if desk.seat != session:
                desk.seat = session
                await desk._recover()
            if not attached:
                await attach(desk, catalog)
                attached = True
            await desk.pump(timeout_ms=5000)
        except Exception as exc:   # the desk being away must not end the session's server
            logger.warning("front desk: %s", exc)
            await asyncio.sleep(2)


async def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    home = Path(os.environ.get("FRONTDESK_HOME") or Path.home() / ".frontdesk" / "default").expanduser()
    try:
        desk: Optional[Desk] = Desk(home, seat="")
    except DeskError:
        desk = None
    catalog = load_catalog(home)
    server = build(desk, home, catalog)
    options = server.create_initialization_options(experimental_capabilities={"claude/channel": {}})
    async with stdio_server() as (read, write):
        async with ServerSession(read, write, options) as session:
            async with anyio.create_task_group() as group:
                if desk is not None:
                    host = ClaudeCodeHost(desk, home)
                    host.session, desk.host = session, host
                    group.start_soon(_attend, desk, host, home, catalog)
                async for message in session.incoming_messages:
                    group.start_soon(server._handle_message, message, session, None, False)
                group.cancel_scope.cancel()
    if desk is not None:
        await desk.close()
