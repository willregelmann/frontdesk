"""Claude Code as a host: the real MCP server process and the real hook command, driven the way
Claude Code drives them (JSON-RPC over stdio, hook JSON on stdin). This test process stands in for
Claude Code itself: it is the parent of both, which is how they find each other's session."""

import asyncio
import json
import os
import sys

from frontdesk import tools, wire
from tests.conftest import until


class Session:
    """One Claude Code session's MCP connection to the Front Desk server."""

    def __init__(self, process):
        self.process, self._next, self.notifications = process, 1, []

    @classmethod
    async def open(cls, home):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "frontdesk.hosts.claude_code", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, env={**os.environ, "FRONTDESK_HOME": str(home)})
        session = cls(process)
        session.hello = await session.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "claude-code", "version": "0"}})
        await session._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return session

    async def _write(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        await self.process.stdin.drain()

    async def _read(self, timeout=15):
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
        return json.loads(line)

    async def request(self, method, params):
        ident, self._next = self._next, self._next + 1
        await self._write({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        while True:
            message = await self._read()
            if message.get("id") == ident:
                return message["result"]
            self.notifications.append(message)

    async def tool(self, tool_name, **arguments):
        result = await self.request("tools/call", {"name": tool_name, "arguments": arguments})
        return json.loads(result["content"][0]["text"])

    async def channel_event(self, timeout=15):
        for message in self.notifications:
            if message.get("method") == "notifications/claude/channel":
                self.notifications.remove(message)
                return message["params"]
        while True:
            message = await self._read(timeout)
            if message.get("method") == "notifications/claude/channel":
                return message["params"]
            self.notifications.append(message)

    async def close(self):
        self.process.stdin.close()
        await self.process.wait()


async def hook(home, event, session="s1", **fields):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "frontdesk.cli", "hook", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        env={**os.environ, "FRONTDESK_HOME": str(home)})
    out, _ = await process.communicate(json.dumps({"hook_event_name": event, "session_id": session, **fields}).encode())
    assert process.returncode == 0
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""


async def state(desk, receipt):
    return (await desk.trace(receipt.id)).state


async def test_session_gets_the_same_tools_and_is_told_about_the_desk(people):
    ash = await people("ash")
    await hook(ash.state_dir, "SessionStart")
    session = await Session.open(ash.state_dir)
    try:
        listed = await session.request("tools/list", {})
        assert [t["name"] for t in listed["tools"]] == [t["name"] for t in tools.TOOLS]
        assert "claude/channel" in session.hello["capabilities"]["experimental"]
        assert "Front Desk" in session.hello["instructions"]
        [me] = (await session.tool("find", name=ash.me))["listed"]
        assert me["identity"] == ash.me
    finally:
        await session.close()


async def test_waking_message_is_pushed_into_the_open_session_and_taken_in_when_the_turn_ends(people, tmp_path):
    wren, ash = await people("wren"), await people("ash")
    await hook(ash.state_dir, "SessionStart")
    session = await Session.open(ash.state_dir)
    try:
        handle = (await session.tool("list", description="Ash pairing with Will"))["channel"]
        sent = await wren.send(ash.me, "is the build green?", conversation="w1", channel=handle)
        event = await session.channel_event()

        assert "is the build green?" in event["content"] and wren.profile["name"] in event["content"]
        assert await state(wren, sent) == wire.ARRIVED          # pushed is not yet taken in

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "user", "content": event["content"]}) + "\n")
        await hook(ash.state_dir, "Stop", transcript_path=str(transcript))
        assert await state(wren, sent) == wire.TAKEN_IN

        ref = event["content"].split('ref="')[1].split('"')[0]
        answered = await session.tool("send", text="green as of five minutes ago", answers=ref)
        assert answered["state"] == wire.ACCEPTED
        await until(lambda: wren.host.woken, wren)
        assert [a.text for a in await wren.take("w1")] == ["green as of five minutes ago"]
    finally:
        await session.close()


async def test_a_push_the_session_never_saw_is_not_taken_in_and_is_shown_at_the_next_prompt(people, tmp_path):
    wren, ash = await people("wren"), await people("ash")
    await hook(ash.state_dir, "SessionStart")
    session = await Session.open(ash.state_dir)
    try:
        handle = (await session.tool("list"))["channel"]
        sent = await wren.send(ash.me, "did you see this?", conversation="w1", channel=handle)
        await session.channel_event()                    # pushed, but say Claude Code dropped it

        empty = tmp_path / "transcript.jsonl"
        empty.write_text("")
        await hook(ash.state_dir, "Stop", transcript_path=str(empty))
        assert await state(wren, sent) == wire.ARRIVED

        shown = await hook(ash.state_dir, "UserPromptSubmit", transcript_path=str(empty))
        assert "did you see this?" in shown
        await hook(ash.state_dir, "Stop", transcript_path=str(empty))
        assert await state(wren, sent) == wire.TAKEN_IN
        assert await hook(ash.state_dir, "UserPromptSubmit", transcript_path=str(empty)) == ""
    finally:
        await session.close()


async def test_waiting_message_pushes_nothing_and_is_shown_with_the_next_prompt(people, tmp_path):
    wren, ash = await people("wren"), await people("ash")
    await hook(ash.state_dir, "SessionStart")
    session = await Session.open(ash.state_dir)
    try:
        handle = (await session.tool("list"))["channel"]
        sent = await wren.send(ash.me, "whenever you get to it", conversation="w1", channel=handle, arrive=wire.WAIT)
        await until(lambda: _arrived(wren, sent))
        try:
            pushed = await session.channel_event(timeout=1.5)
        except asyncio.TimeoutError:
            pushed = None

        assert pushed is None
        assert "whenever you get to it" in await hook(ash.state_dir, "UserPromptSubmit", transcript_path="")
    finally:
        await session.close()


async def _arrived(desk, receipt):
    return await state(desk, receipt) == wire.ARRIVED


async def test_default_channel_message_waits_for_a_session_to_adopt_it(people):
    wren, ash = await people("wren"), await people("ash")
    sent = await wren.send(ash.me, "anyone home?", conversation="w1")     # no session is open

    await hook(ash.state_dir, "SessionStart")
    session = await Session.open(ash.state_dir)
    try:
        await until(lambda: _waiting(session))
        assert await state(wren, sent) == wire.ACCEPTED                   # never reported as arrived
        assert "anyone home?" in await hook(ash.state_dir, "SessionStart")
        [waiting] = (await session.tool("listings"))["waiting_on_default_channel"]

        adopted = await session.tool("adopt", ref=waiting["ref"])

        assert "anyone home?" in adopted["adopted"][0]
        assert await state(wren, sent) == wire.ARRIVED
    finally:
        await session.close()


async def _waiting(session):
    return (await session.tool("listings"))["waiting_on_default_channel"]


async def test_clearing_the_session_ends_its_channel_but_closing_it_does_not(people):
    wren, ash = await people("wren"), await people("ash")
    await hook(ash.state_dir, "SessionStart")
    session = await Session.open(ash.state_dir)
    try:
        handle = (await session.tool("list"))["channel"]
    finally:
        await session.close()

    await hook(ash.state_dir, "SessionEnd", reason="prompt_input_exit")
    assert handle in (await wren.find(ash.me))[0].channels
    kept = await wren.send(ash.me, "for when you're back", conversation="w1", channel=handle)
    assert kept.state == wire.ACCEPTED

    await hook(ash.state_dir, "SessionEnd", reason="clear")
    assert handle not in (await wren.find(ash.me))[0].channels
