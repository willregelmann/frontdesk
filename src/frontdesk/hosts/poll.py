"""A host that is polled: something outside the agent, such as a gateway that runs it, asks the desk
what is waiting and starts the turns itself (docs/interfaces/HOST.md).

It looks at the desk as each seat of the identity that holds a live channel and has no session
running, so a message is claimed by the seat whose conversation it is for, exactly as that seat's own
session would claim it. A seat whose session is running is left to that session, which pushes what
arrives into it. It also looks as a seat of its own, which is how messages to the default channel are
seen while no session is open. It never takes a message in: that stays the job of the turn that is
shown it.
"""

from __future__ import annotations

import json
from pathlib import Path

from frontdesk import Desk, wire
from frontdesk.hosts.claude_code import sessions
from frontdesk.wire import Arrival

SEAT = "poll"


def _wake(conversation: str, key: str, arrival: Arrival, where: str) -> dict:
    # A label and a note, never the message: the turn reads the message with the desk's own tools.
    return {"conversation": conversation, "key": key,
            "note": f"a {arrival.kind} from {arrival.sender_name} on Front Desk{where}"}


async def pending(home: Path) -> list[dict]:
    """One entry for each waking message no turn has taken in yet: the conversation it is for, a key
    that changes if it moves to another conversation, and a note. A message to the default channel
    names a conversation for its sender, where the session-start hook shows it and asks for ``adopt``.
    Raises when the desk can't be reached: an unreachable desk is never "nothing waiting"."""
    desk = Desk(home, seat=SEAT)
    try:
        seats = {row["seat"] for row in desk.ledger._all("SELECT DISTINCT seat FROM channels WHERE ended=0")}
        for seat in sorted(seats - {SEAT} - sessions.live(home)) + [SEAT]:
            desk.seat = seat
            await desk._recover()
            await desk.pump()
        found = []
        for row in desk.ledger._all(
                "SELECT i.event_id, i.arrival, c.conversation FROM inbox i JOIN channels c ON c.handle = i.channel "
                "WHERE i.state IN ('arrived', 'shown') AND c.ended = 0 ORDER BY i.seq"):
            arrival = Arrival(**json.loads(row["arrival"]))
            if arrival.arrive == wire.WAKE:
                found.append(_wake(row["conversation"], f"{row['event_id']}@{row['conversation']}", arrival, ""))
        for arrival in desk.waiting():
            if arrival.arrive == wire.WAKE:
                found.append(_wake(f"desk:{arrival.sender_name}", f"{arrival.ref}@default", arrival,
                                   ", to your default channel"))
        return found
    finally:
        await desk.close()
