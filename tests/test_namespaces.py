"""Namespaces: identities joined for a test or a trial are never listed in, found from or reachable
by name from any other namespace, including the main register."""

import uuid

import pytest

from frontdesk import Desk
from frontdesk.desk import DeskError
from tests.conftest import DESK


async def _join(tmp_path, namespace, name, *, kind="agent", answerable=None):
    return await Desk.join(DESK, name, tmp_path / namespace / name, kind=kind, namespace=namespace,
                           answerable=answerable)


async def test_the_same_name_in_two_namespaces_is_two_identities_that_never_see_each_other(tmp_path):
    a, b = f"test-{uuid.uuid4().hex[:8]}", f"test-{uuid.uuid4().hex[:8]}"
    desks = []
    try:
        for ns in (a, b):
            keeper = await _join(tmp_path, ns, "keeper", kind="person")
            ash = await _join(tmp_path, ns, "ash", answerable="keeper")
            desks += [keeper, ash]
        keeper_a, ash_a, keeper_b, ash_b = desks

        assert ash_a.me != ash_b.me
        assert {e.identity for e in await keeper_a.find()} == {keeper_a.me, ash_a.me}
        assert {e.identity for e in await keeper_b.find()} == {keeper_b.me, ash_b.me}
        # Answerable resolved inside the namespace, not to a same-named person elsewhere.
        assert ash_a.profile["answerable"] == keeper_a.me
        # A plain name reaches only the namespace's own identity.
        [found] = await keeper_a.find("ash")
        assert found.identity == ash_a.me
        assert await keeper_a.find(ash_b.me) == []
    finally:
        for desk in desks:
            await desk.close()


async def test_a_person_in_a_namespace_never_looks_like_the_same_name_outside_it(people):
    will = await people("will", kind="person")
    ash = await people("ash")
    shown = lambda desk: desk.matrix.call("GET", f"/v3/profile/{desk.me}/displayname")
    assert (await shown(will))["displayname"] == f"will ({people.namespace})"
    assert (await shown(ash))["displayname"] == f"ash (agent, {people.namespace})"


async def test_a_namespaced_register_holds_nothing_from_the_main_one(people):
    keeper = await people("keeper", kind="person")
    listed = {e.identity for e in await keeper.find()}
    assert listed == {keeper.me}


@pytest.mark.parametrize("name, namespace", [("t1.ash", ""), ("ash", "t1.x"), ("ash", "T 1"), ("a:b", "")])
async def test_a_name_or_namespace_that_could_collide_is_refused_before_anything_is_created(tmp_path, name, namespace):
    with pytest.raises(DeskError):
        await Desk.join(DESK, name, tmp_path / "x", kind="person", namespace=namespace)
    assert not (tmp_path / "x").exists()


async def test_an_identity_that_writes_itself_into_another_namespaces_register_is_not_listed_there(tmp_path):
    """Any member may write its own entry into a register room (Foil's probe), so the room alone does
    not say who belongs in it: a main-desk ``ash`` that lists itself in namespace t1's register must
    not appear there as t1's ``ash``, and a t1 identity that lists itself in the main register must
    not appear there at all."""
    from frontdesk import wire
    from frontdesk.desk import localpart
    ns, name = f"test-{uuid.uuid4().hex[:8]}", f"x{uuid.uuid4().hex[:6]}"
    desks = []
    try:
        will = await _join(tmp_path, ns, "will", kind="person")
        real = await _join(tmp_path, ns, name, answerable="will")
        boss = await Desk.join(DESK, f"b{name}", tmp_path / "main" / "boss", kind="person")
        intruder = await Desk.join(DESK, name, tmp_path / "main" / name, answerable=f"b{name}")
        desks += [will, real, boss, intruder]
        entry = {"name": name, "kind": "agent", "answerable": will.me, "channels": {}, "offers": {}}

        theirs = await intruder.matrix.resolve_alias(f"#{localpart(wire.REGISTER_LOCALPART, ns)}:{intruder.server}")
        await intruder.matrix.join(theirs)
        await intruder.matrix.put_state(theirs, wire.EV_IDENTITY, intruder.me, entry)
        ours = await real.matrix.resolve_alias(f"#{wire.REGISTER_LOCALPART}:{real.server}")
        await real.matrix.join(ours)
        await real.matrix.put_state(ours, wire.EV_IDENTITY, real.me, entry)
        will._listings.clear()
        boss._listings.clear()

        assert {(e.name, e.identity) for e in await will.find()} == {("will", will.me), (name, real.me)}
        assert await will.find(intruder.me) == []
        assert real.me not in {e.identity for e in await boss.find()}
    finally:
        for desk in desks:
            await desk.leave() if desk.namespace == "" else None
            await desk.close()
