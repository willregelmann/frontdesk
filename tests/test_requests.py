"""Requests: every one ends in exactly one outcome, and an offer is done at most once."""

import asyncio

import pytest

from frontdesk import Desk, DeskError, wire
from tests.conftest import RecordingHost, until


class Counter:
    def __init__(self, result="pong"):
        self.calls, self.result = [], result

    async def __call__(self, args):
        self.calls.append(args)
        return self.result


async def outcome_in(desk, conversation):
    """The outcome that arrived in ``conversation``, once it has."""
    await until(lambda: desk.ledger.pending(desk.ledger.channel_of(conversation)["handle"]), desk)
    [arrival] = await desk.take(conversation)
    await desk.commit(conversation)
    return arrival


async def test_offer_needing_nobody_is_done_once_and_the_outcome_returns_to_the_asker(people):
    wren, ash = await people("wren"), await people("ash")
    ping = Counter()
    await ash.offer("ping", "Answers pong", ping, needs={"type": "object"})

    asked = await wren.ask(ash.me, "ping", {"n": 1}, conversation="w1")
    assert asked.state == wire.ACCEPTED
    await until(lambda: ping.calls, ash)
    outcome = await outcome_in(wren, "w1")

    assert outcome.kind == wire.OUTCOME and outcome.sender == ash.me
    assert outcome.outcome["result"] == wire.DONE and outcome.outcome["detail"] == "pong"
    assert outcome.outcome["asked"] == wren.me and outcome.outcome["agreed"] == wire.AGREE_NOBODY
    for _ in range(3):
        await ash.pump()
        await wren.pump()
    assert ping.calls == [{"n": 1}]
    assert await wren.take("w1") == []      # exactly one outcome


async def test_listing_an_offer_never_does_it_and_an_unlisted_one_is_refused(people):
    wren, ash = await people("wren"), await people("ash")
    ping = Counter()
    await ash.offer("ping", "Answers pong", ping)
    [listing] = await wren.find(ash.me)

    refused = await wren.ask(ash.me, "format-disk", conversation="w1")

    assert "ping" in listing.offers and ping.calls == []
    assert refused.state == wire.REFUSED and "format-disk" in refused.reason


async def test_offer_withdrawn_after_the_asker_looked_is_refused_out_loud(people):
    wren, ash = await people("wren"), await people("ash")
    ping = Counter()
    await ash.offer("ping", "Answers pong", ping)
    await wren.find(ash.me)
    ash.ledger.drop_offer("ping")           # withdrawn on Ash's side; the register hasn't caught up

    await wren.ask(ash.me, "ping", conversation="w1")
    await until(lambda: ash.ledger.requests_in(wire.REFUSED), ash)
    outcome = await outcome_in(wren, "w1")

    assert outcome.outcome["result"] == wire.REFUSED and ping.calls == []


async def test_nothing_is_done_before_the_agent_agrees_and_a_refusal_is_an_outcome(people):
    wren, ash = await people("wren"), await people("ash")
    restart = Counter("restarting")
    await ash.offer("restart", "Restarts Ash's gateway", restart, agree=wire.AGREE_SELF)

    await wren.ask(ash.me, "restart", conversation="w1")
    await until(lambda: ash.host.woken, ash)
    [request] = await ash.take("fresh-1")
    assert request.kind == wire.REQUEST and request.request["offer"] == "restart" and restart.calls == []
    await ash.settle(request.ref, False, "in the middle of a deploy")
    refusal = await outcome_in(wren, "w1")

    await wren.ask(ash.me, "restart", conversation="w2")
    await until(lambda: len(ash.host.started) == 2, ash)
    [second] = await ash.take("fresh-2")
    await ash.settle(second.ref, True)
    done = await outcome_in(wren, "w2")

    assert refusal.outcome["result"] == wire.REFUSED and "deploy" in refusal.outcome["detail"]
    assert done.outcome["result"] == wire.DONE and done.outcome["agreed"] == ash.me
    assert len(restart.calls) == 1
    with pytest.raises(DeskError):
        await ash.settle(second.ref, True)      # one answer settles it


async def test_agreement_from_a_named_person_is_asked_by_message_and_settled_by_one_answer(people):
    will = await people("will", kind="person")
    wren, ash = await people("wren"), await people("ash")
    restart = Counter("restarting")
    await ash.offer("restart", "Restarts Ash's gateway", restart, agree=will.me)

    await wren.ask(ash.me, "restart", conversation="w1")
    await until(lambda: ash.ledger.requests_in("awaiting") and ash.ledger.requests_in("awaiting")[0]["agreement_room"], ash)
    room = ash.ledger.requests_in("awaiting")[0]["agreement_room"]
    assert restart.calls == []

    # Will answers from an ordinary chat client: first something that isn't an answer, then yes.
    await until(lambda: _joined(will, room), ash)
    await will.matrix.send(room, "m.room.message", "t1", {"msgtype": "m.text", "body": "hmm, why?"})
    await ash.pump()
    assert restart.calls == []
    await will.matrix.send(room, "m.room.message", "t2", {"msgtype": "m.text", "body": "Yes, go ahead"})
    await until(lambda: restart.calls, ash)
    outcome = await outcome_in(wren, "w1")

    assert outcome.outcome["result"] == wire.DONE and outcome.outcome["agreed"] == will.me
    await will.matrix.send(room, "m.room.message", "t3", {"msgtype": "m.text", "body": "yes"})
    await ash.pump()
    assert len(restart.calls) == 1


async def _joined(person, room):
    return person.me in await person.matrix.members(room)


async def test_request_still_waiting_when_its_time_passes_expires_and_is_never_done_late(people):
    wren, ash = await people("wren"), await people("ash")
    restart = Counter()
    await ash.offer("restart", "Restarts Ash's gateway", restart, agree=wire.AGREE_SELF)

    await wren.ask(ash.me, "restart", conversation="w1", expires_in_s=2)
    await until(lambda: ash.host.woken, ash)
    [request] = await ash.take("fresh-1")
    await asyncio.sleep(2.2)
    await ash.pump()
    outcome = await outcome_in(wren, "w1")

    assert outcome.outcome["result"] == wire.EXPIRED
    with pytest.raises(DeskError):
        await ash.settle(request.ref, True)
    assert restart.calls == []


async def test_request_can_be_withdrawn_until_the_doing_starts(people):
    wren, ash = await people("wren"), await people("ash")
    restart = Counter()
    await ash.offer("restart", "Restarts Ash's gateway", restart, agree=wire.AGREE_SELF)

    asked = await wren.ask(ash.me, "restart", conversation="w1")
    await until(lambda: ash.ledger.requests_in("awaiting"), ash)
    await wren.take_back(asked.id)
    await until(lambda: ash.ledger.requests_in(wire.REFUSED), ash)
    outcome = await outcome_in(wren, "w1")

    assert outcome.outcome["result"] == wire.REFUSED and "withdrawn" in outcome.outcome["detail"]
    assert restart.calls == []


class Crash(BaseException):
    """The host process dying partway through an offer."""


@pytest.mark.parametrize("survives_restart, expected", [(False, wire.FAILED), (True, wire.DONE)])
async def test_an_offer_interrupted_by_a_restart_is_never_done_twice(people, survives_restart, expected):
    wren, ash = await people("wren"), await people("ash")
    calls = []

    async def restart_gateway(args):
        calls.append(args)
        raise Crash()               # the gateway goes down while doing it

    await ash.offer("restart", "Restarts Ash's gateway", restart_gateway, survives_restart=survives_restart)
    await wren.ask(ash.me, "restart", conversation="w1")
    with pytest.raises(Crash):
        await until(lambda: False, ash)

    # The gateway comes back: same identity, same state, a fresh process.
    reborn = Desk(ash.state_dir)
    reborn.host = RecordingHost()
    try:
        await reborn.offer("restart", "Restarts Ash's gateway", restart_gateway, survives_restart=survives_restart)
        await reborn._recover()
        for _ in range(3):
            await reborn.pump()
        outcome = await outcome_in(wren, "w1")
    finally:
        await reborn.close()

    assert outcome.outcome["result"] == expected
    assert len(calls) == 1


async def test_two_takers_of_one_agreed_request_do_it_once(people):
    wren, ash = await people("wren"), await people("ash")
    calls = []

    async def slow(args):
        calls.append(args)
        await asyncio.sleep(0.3)
        return "ok"

    await ash.offer("restart", "Restarts Ash's gateway", slow, agree=wire.AGREE_SELF)
    await wren.ask(ash.me, "restart", conversation="w1")
    await until(lambda: ash.ledger.requests_in("awaiting"), ash)
    ref = ash.ledger.requests_in("awaiting")[0]["ref"]
    ash.ledger.move_request(ref, ("awaiting",), "agreed", agreed_by=ash.me)

    await asyncio.gather(ash._perform(ref), ash._perform(ref))   # e.g. a recovering process and a live one

    assert len(calls) == 1


async def test_agreement_that_comes_after_the_request_expired_does_nothing(people):
    wren, ash = await people("wren"), await people("ash")
    restart = Counter()
    await ash.offer("restart", "Restarts Ash's gateway", restart, agree=wire.AGREE_SELF)

    await wren.ask(ash.me, "restart", conversation="w1", expires_in_s=1.5)
    await until(lambda: ash.host.woken, ash)
    [request] = await ash.take("fresh-1")
    await asyncio.sleep(1.8)                 # its time passes before anything looks at the clock
    await ash.settle(request.ref, True)
    outcome = await outcome_in(wren, "w1")

    assert outcome.outcome["result"] == wire.EXPIRED and restart.calls == []
