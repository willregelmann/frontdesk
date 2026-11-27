"""A host that is polled (docs/interfaces/HOST.md): something outside the agent asks the desk
what is waiting and starts the turns. It reports each waking message once per conversation, as a
label and never as the message, leaves a seat with a running session to that session, and never
reads an unreachable desk as "nothing waiting"."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time

from frontdesk import Desk
from frontdesk.hosts import poll
from frontdesk.hosts.claude_code import sessions


async def look(home, until, timeout: float = 15.0) -> list:
    """Poll the way a gateway does, until ``until(entries)`` holds."""
    deadline = time.monotonic() + timeout
    while True:
        entries = await poll.pending(home)
        if until(entries):
            return entries
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out; last saw {entries}")
        await asyncio.sleep(0.2)


async def _seat(home, conversation: str) -> tuple:
    desk = Desk(home, seat=conversation)
    handle = await desk.list_channel(conversation, "a conversation no session has open")
    await desk.pump()
    await desk.close()
    return handle


async def test_a_waking_message_for_a_conversation_with_no_session_is_reported_for_that_conversation(people):
    ember, wren = await people("ember"), await people("wren")
    handle = await _seat(ember.state_dir, "session-1")
    receipt = await wren.send("ember", "the build went red: SECRET DETAIL", channel=handle, arrive="wake")
    [entry] = await look(ember.state_dir, bool)
    assert entry["conversation"] == "session-1"
    assert entry["key"].endswith("@session-1")
    assert "wren" in entry["note"] and "SECRET DETAIL" not in json.dumps(entry), "the message itself was printed"
    assert await poll.pending(ember.state_dir) == [entry], "a second look reported it differently"
    assert receipt.id


async def test_a_message_a_turn_has_taken_in_is_no_longer_reported(people):
    ember, wren = await people("ember"), await people("wren")
    handle = await _seat(ember.state_dir, "session-1")
    await wren.send("ember", "please look", channel=handle, arrive="wake")
    await look(ember.state_dir, lambda e: len(e) == 1)
    turn = Desk(ember.state_dir, seat="session-1")
    try:
        assert len(await turn.take("session-1")) == 1
        await turn.commit("session-1")
    finally:
        await turn.close()
    assert await poll.pending(ember.state_dir) == []


async def test_a_message_that_waits_rather_than_wakes_is_not_reported(people):
    ember, wren = await people("ember"), await people("wren")
    handle = await _seat(ember.state_dir, "session-1")
    await wren.send("ember", "no hurry", channel=handle, arrive="wait")
    await wren.send("ember", "but this one wakes", channel=handle, arrive="wake")
    entries = await look(ember.state_dir, bool)
    await asyncio.sleep(0.5)
    assert len(await poll.pending(ember.state_dir)) == 1 == len(entries), "a waiting message was reported as a wake"


async def test_a_message_to_the_default_channel_names_a_conversation_for_its_sender(people):
    ember, wren = await people("ember"), await people("wren")
    await wren.send("ember", "hello, are you there?")
    [entry] = await look(ember.state_dir, bool)
    assert entry["conversation"] == "desk:wren" and entry["key"].endswith("@default")
    assert "default channel" in entry["note"]


async def test_a_seat_with_a_running_session_is_left_to_that_session(people):
    ember, wren = await people("ember"), await people("wren")
    home = ember.state_dir
    handle = await _seat(home, "session-1")
    sessions.record(home, "session-1")      # this test's own process tree stands for the running session
    assert "session-1" in sessions.live(home)
    await wren.send("ember", "for the open session", channel=handle, arrive="wake")
    for _ in range(10):
        assert await poll.pending(home) == []
        await asyncio.sleep(0.2)
    claimed = Desk(home, seat="x").ledger._all("SELECT event_id FROM inbox")
    assert claimed == [], "the polled host claimed a message a running session should have"

    shutil.rmtree(home / "claude-sessions")      # the session ends; now the polled host looks for it
    [entry] = await look(home, bool)
    assert entry["conversation"] == "session-1"


async def test_an_unreachable_desk_is_a_failure_never_nothing_waiting(people, tmp_path):
    ember = await people("ember")
    away = tmp_path / "away"
    shutil.copytree(ember.state_dir, away)
    creds = json.loads((away / "credentials.json").read_text())
    creds["homeserver"] = "http://127.0.0.1:9"
    (away / "credentials.json").write_text(json.dumps(creds))
    done = subprocess.run([sys.executable, "-m", "frontdesk.cli", "pending"], capture_output=True, text=True,
                          env=dict(os.environ, FRONTDESK_HOME=str(away)), timeout=60)
    assert done.returncode != 0 and done.stdout == ""
    assert "can't be reached" in done.stderr


async def test_a_message_shown_to_a_turn_that_never_finished_is_still_reported(people):
    ember, wren = await people("ember"), await people("wren")
    handle = await _seat(ember.state_dir, "session-1")
    await wren.send("ember", "please look", channel=handle, arrive="wake")
    await look(ember.state_dir, bool)
    crashed = Desk(ember.state_dir, seat="session-1")
    try:
        assert len(await crashed.take("session-1")) == 1     # shown, and then the turn died before commit
    finally:
        await crashed.close()
    assert len(await poll.pending(ember.state_dir)) == 1
