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
