"""What became of a message is said by its receiver, never by its sender or someone watching."""

from frontdesk import wire
from tests.conftest import until


async def _forge(desk, room, event_id, state):
    await desk.matrix.send(room, wire.EV_STATUS, f"forged-{desk.me}-{state}", {
        "state": state, "m.relates_to": {"rel_type": "m.reference", "event_id": event_id}})


async def _member(person, room):
    try:
        return person.me in await person.matrix.members(room)
    except Exception:
        return False


async def test_a_watcher_or_the_sender_can_not_say_a_message_was_taken_in(people):
    will = await people("will", kind="person")
    wren, ash = await people("wren"), await people("ash")
    handle = await ash.list_channel("a1")
    sent = await wren.send(ash.me, "status?", conversation="w1", channel=handle, arrive=wire.WAIT)
    attempt = wren.ledger.attempt(sent.id)
    line, event_id = attempt["room_id"], attempt["event_id"]
    await until(lambda: _member(will, line), wren, ash)
    await until(lambda: ash.ledger.pending(handle), ash)

    await _forge(will, line, event_id, wire.TAKEN_IN)      # the person watching the line
    await _forge(wren, line, event_id, wire.TAKEN_IN)      # the sender itself
    assert (await wren.trace(sent.id)).state == wire.ARRIVED

    await ash.take("a1")
    await ash.commit("a1")                                 # the receiver really takes it in
    assert (await wren.trace(sent.id)).state == wire.TAKEN_IN
