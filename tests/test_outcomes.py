"""Every request ends in exactly one outcome, even when sending it fails or the host stops right after
deciding it."""

import httpx
import pytest

from frontdesk import Desk, wire
from tests.conftest import RecordingHost, until


class Crash(BaseException):
    """The host process dying."""


async def _ping(args):
    return "pong"


async def _outcomes(desk, conversation):
    handle = desk.ledger.channel_of(conversation)["handle"]
    return [a for a in await desk.take(conversation) if a.kind == wire.OUTCOME] if desk.ledger.pending(handle) else []


async def test_an_outcome_the_desk_did_not_take_is_sent_again(people):
    wren, ash = await people("wren"), await people("ash")
    await ash.offer("ping", "Answers pong", _ping)
    real_send, dropped, sent = ash.matrix.send, [], []

    async def flaky_send(room, event_type, txn_id, content, **kw):
        if str(txn_id).startswith("out-") and not dropped:
            dropped.append(txn_id)
            raise httpx.ConnectError("the desk was away for a moment")
        event_id = await real_send(room, event_type, txn_id, content, **kw)
        if str(txn_id).startswith("out-"):
            sent.append(txn_id)
        return event_id

    ash.matrix.send = flaky_send
    await wren.ask(ash.me, "ping", conversation="w1")
    await until(lambda: dropped, ash)
    await until(lambda: _outcomes(wren, "w1"), ash, wren)
    for _ in range(3):                                   # more ticks must not send it a second time
        await ash.pump()
        await wren.pump()

    # Count sends, not arrivals: the homeserver drops a repeated txn id for a while (Synapse: 30 min),
    # so a desk that re-sent every tick would still show one arrival here and a fresh one later.
    assert sent == [dropped[0]], sent
    outcomes = [a for a in await wren.take("w1") if a.kind == wire.OUTCOME]
    assert len(outcomes) == 1 and outcomes[0].outcome["result"] == wire.DONE


@pytest.mark.parametrize("survives_restart", [False, True])
async def test_a_restart_between_deciding_an_outcome_and_sending_it_is_not_silence(people, survives_restart):
    wren, ash = await people("wren"), await people("ash")
    await ash.offer("ping", "Answers pong", _ping, survives_restart=survives_restart)
    real_send = ash.matrix.send

    async def dies_sending_outcome(room, event_type, txn_id, content, **kw):
        if str(txn_id).startswith("out-"):
            raise Crash()
        return await real_send(room, event_type, txn_id, content, **kw)

    ash.matrix.send = dies_sending_outcome
    await wren.ask(ash.me, "ping", conversation="w1")
    with pytest.raises(Crash):
        await until(lambda: False, ash)

    reborn = Desk(ash.state_dir)
    reborn.host = RecordingHost()
    try:
        await reborn.offer("ping", "Answers pong", _ping, survives_restart=survives_restart)
        await reborn._recover()
        await until(lambda: _outcomes(wren, "w1"), reborn, wren)
        [outcome] = [a for a in await wren.take("w1") if a.kind == wire.OUTCOME]
        assert outcome.outcome["result"] == wire.DONE
    finally:
        await reborn.close()
