"""What became of a request is its outcome (#22): never "arrived" forever, once the outcome is in."""

from frontdesk import wire
from tests.conftest import until
from tests.test_requests import Counter, outcome_in


async def test_a_request_traces_to_its_outcome_once_the_outcome_has_arrived(people):
    wren, ash = await people("wren"), await people("ash")
    ping = Counter()
    await ash.offer("ping", "Answers pong", ping)

    asked = await wren.ask(ash.me, "ping", conversation="w1")
    before = await wren.trace(asked.id)
    await until(lambda: ping.calls, ash)
    outcome = await outcome_in(wren, "w1")
    after = await wren.trace(asked.id)

    assert before.state in (wire.ACCEPTED, wire.ARRIVED)
    assert after.state == wire.DONE and after.reason == "pong" and after.at == outcome.sent_at


async def test_a_refused_request_traces_as_refused(people):
    wren, ash = await people("wren"), await people("ash")
    await ash.offer("ping", "Answers pong", Counter())
    await wren.find(ash.me)
    ash.ledger.drop_offer("ping")           # the register still lists it, so the ask goes out

    asked = await wren.ask(ash.me, "ping", conversation="w1")
    await until(lambda: ash.ledger.requests_in(wire.REFUSED), ash)
    await outcome_in(wren, "w1")

    assert (await wren.trace(asked.id)).state == wire.REFUSED


async def test_each_of_two_requests_traces_to_its_own_outcome(people):
    """Two requests out from one asker, ending differently: each trace is its own request's outcome,
    not the first outcome that came back (Ash's mutation on #25)."""
    wren, ash = await people("wren"), await people("ash")
    ping = Counter()
    await ash.offer("ping", "Answers pong", ping)
    await ash.offer("gone", "Withdrawn before it is asked", Counter())
    await wren.find(ash.me)
    ash.ledger.drop_offer("gone")           # the register still lists it, so the ask goes out

    done = await wren.ask(ash.me, "ping", conversation="w1")
    await until(lambda: ping.calls, ash)
    await outcome_in(wren, "w1")
    refused = await wren.ask(ash.me, "gone", conversation="w1")
    await until(lambda: ash.ledger.requests_in(wire.REFUSED), ash)
    await outcome_in(wren, "w1")

    assert (await wren.trace(done.id)).state == wire.DONE
    assert (await wren.trace(refused.id)).state == wire.REFUSED
