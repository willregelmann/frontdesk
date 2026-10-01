"""The moments Claude Code provides, as ``frontdesk hook`` reads them from a hook's stdin."""

from __future__ import annotations

import json
from pathlib import Path

from frontdesk import Desk, DeskError, wire
from frontdesk.hosts.claude_code import sessions


def _transcript(payload: dict) -> str:
    try:
        return Path(payload.get("transcript_path") or "").read_text(errors="replace")
    except OSError:
        return ""


def _context(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


async def run(payload: dict, home: Path) -> int:
    event, session = payload.get("hook_event_name"), payload.get("session_id")
    if not session:
        return 0
    if event == "SessionStart":
        sessions.record(home, session)
    try:
        desk = Desk(home, seat=session)
    except DeskError:
        return 0   # no identity joined here: the desk stays out of the way
    try:
        if event == "SessionStart":
            waiting = desk.waiting()
            if waiting:
                lines = [f"- ref {a.ref} from {a.sender_name}: {a.text[:80]}" for a in waiting]
                _context(event, "Front Desk: messages are waiting on your default channel. Bring one into this "
                                "conversation with the adopt tool.\n" + "\n".join(lines))
        elif event == "UserPromptSubmit":
            try:
                await desk.pump()   # look now, so what arrived while the session was closed is in this turn
            except Exception:
                pass                # the desk is away: show what is already here
            # Anything pushed into the session as a channel event is already in the transcript.
            seen = _transcript(payload)
            fresh = [a for a in await desk.take(session, mark=False) if a.ref not in seen]
            if fresh:
                desk.mark_shown([a.ref for a in fresh])
                _context(event, "\n\n".join(wire.render(a) for a in fresh))
        elif event == "Stop":
            # The turn finished: what it was shown, by hook or by channel event, is now taken in.
            seen = _transcript(payload)
            await desk.commit(session, also=[a.ref for a in await desk.take(session, mark=False) if a.ref in seen])
        elif event == "SessionEnd" and payload.get("reason") == "clear":
            await desk.end(session)   # /clear ends the conversation; closing the window does not
    finally:
        await desk.close()
    return 0
