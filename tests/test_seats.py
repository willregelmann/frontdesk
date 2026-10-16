"""Two seats of one identity pumping at once (two Claude Code sessions, or a session and a harness
host). A message for one seat's channel must reach that seat whichever seat sees it first."""

import json

from frontdesk import Desk
from tests.conftest import until


async def test_a_message_another_seat_sees_first_still_reaches_its_own_seat(people):
    ember = await people("ember")
    home = ember.state_dir
    owner, other = Desk(home, seat="session-A"), Desk(home, seat="session-B")
    for desk in (owner, other):
        desk.host = ember.host
    try:
        handle = await owner.list_channel("session-A", "the owner's conversation")
        await owner.pump()
        await other.pump()   # both are caught up before the message is sent
        sender = Desk(home, seat="session-C")
        receipt = await sender.send("ember", "for A", channel=handle, arrive="wake")
        await sender.close()

        # The other seat sees it first, and the owner looks while the other is still deciding
        # (between its claim and its release, which _route does). That is the interleaving two live
        # seats produce. A fixed desk never claims, so never routes, and the owner's look is its own.
        real_route, owner_looked, other_saw = other._route, [], []

        async def slow_route(*args, **kwargs):
            if not owner_looked:
                owner_looked.append(True)
                await owner.pump()
            return await real_route(*args, **kwargs)

        real_note = other.ledger.note_event

        def note(room_id, event_id, mine, ts):
            other_saw.append(event_id)
            return real_note(room_id, event_id, mine, ts)

        other._route, other.ledger.note_event = slow_route, note
        await until(lambda: other_saw, other)
        other._route, other.ledger.note_event = real_route, real_note

        def arrived():
            for row in owner.ledger._all("SELECT state, arrival FROM inbox"):
                if json.loads(row["arrival"] or "{}").get("id") == receipt.id:
                    return row["state"] == "arrived"
            return False

        await until(arrived, owner, other, timeout=10)
        assert ember.host.woken.count("session-A") == 1
    finally:
        await owner.close()
        await other.close()
