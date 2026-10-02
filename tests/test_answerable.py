"""An agent may name a person answerable for it (who then watches its lines), or nobody."""

from tests.conftest import until


async def _in_room(desk, room: str) -> set[str]:
    """Everyone joined to or invited into ``room``, read from its member state."""
    return {event["state_key"] for event in await desk.matrix.state(room)
            if event["type"] == "m.room.member" and event["content"].get("membership") in ("join", "invite")}


async def _exchange(wren, ash):
    """Wren writes to Ash and Ash answers. Returns the room."""
    sent = await wren.send(ash.me, "status?", conversation="w1")
    await until(lambda: ash.host.woken, ash)
    [arrival] = await ash.take("fresh-1")
    await ash.commit("fresh-1")
    assert arrival.text == "status?" and arrival.sender == wren.me
    answer = await ash.send(wren.me, "all fine", answers=arrival.ref, conversation="fresh-1")
    await until(lambda: wren.host.woken, wren, ash)
    [back] = await wren.take("w1")
    assert back.text == "all fine" and back.sender == ash.me
    assert answer.state == "accepted"
    return wren.ledger.attempt(sent.id)["room_id"]


async def test_an_agent_that_names_nobody_can_send_and_receive_and_nobody_else_is_invited(people):
    will = await people("will", kind="person")       # a person IS listed, and still nobody invites them
    wren = await people("wren", answerable=False)
    ash = await people("ash", answerable=False)
    assert wren.profile["answerable"] is None and ash.profile["answerable"] is None
    [listed] = await will.find("wren")
    assert listed.answerable is None

    room = await _exchange(wren, ash)
    for _ in range(3):
        await wren.pump()
        await ash.pump()
    assert await _in_room(wren, room) == {wren.me, ash.me}


async def test_the_person_an_agent_names_watches_its_lines_whichever_side_opens_them(people):
    will = await people("will", kind="person")
    wren = await people("wren")                     # answerable to Will
    ash = await people("ash", answerable=False)

    opened_by_wren = await _exchange(wren, ash)
    assert await _in_room(wren, opened_by_wren) == {wren.me, ash.me, will.me}

    sent = await ash.send(wren.me, "a fresh one", conversation="a1")
    await until(lambda: wren.ledger.inbox_by_msg(sent.id), wren, ash)
    opened_by_ash = ash.ledger.attempt(sent.id)["room_id"]
    await until(lambda: _has(wren, opened_by_ash, will.me), wren)   # Wren's host invites Wren's watcher
    assert await _in_room(ash, opened_by_ash) == {wren.me, ash.me, will.me}


async def _has(desk, room, who):
    return who in await _in_room(desk, room)
