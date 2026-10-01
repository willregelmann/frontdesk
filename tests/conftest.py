"""Every test runs against a real desk (``desk/up.sh``): the invariants are about what the
homeserver and two real hosts do together, which a fake would only assert about itself."""

import asyncio
import os
import time
import uuid

import httpx
import pytest

from frontdesk import Desk

# Never the real desk (desk/up.sh, :8008): start a throwaway one with ``desk/up.sh --test``.
DESK = os.environ.get("FRONTDESK_TEST_DESK", "http://127.0.0.1:8018")


def _desk_is_up() -> bool:
    try:
        return httpx.get(f"{DESK}/_matrix/client/versions", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def pytest_collection_modifyitems(config, items):
    if not _desk_is_up():
        skip = pytest.mark.skip(reason=f"no desk at {DESK}; start one with desk/up.sh --test")
        for item in items:
            item.add_marker(skip)


class RecordingHost:
    """A host that can start conversations (unless told it can't) and records being woken."""

    def __init__(self, can_start: bool = True):
        self.can_start = can_start
        self.woken: list[str] = []
        self.started: list[str] = []

    async def wake(self, conversation: str) -> None:
        self.woken.append(conversation)

    async def start(self, arrival):
        if not self.can_start:
            return None
        conversation = f"fresh-{len(self.started) + 1}"
        self.started.append(conversation)
        return conversation


async def until(condition, *desks, timeout: float = 15.0):
    """Let every desk look until ``condition`` holds."""
    deadline = time.monotonic() + timeout
    while True:
        for desk in desks:
            await desk.pump()
        result = condition()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the desk")
        await asyncio.sleep(0.1)


@pytest.fixture
async def people(tmp_path):
    """Join identities for one test: ``await people("will", kind="person")``, ``await people("wren")``.
    Agents answer to the first person joined. Each test has its own namespace, so its identities
    keep their plain names and never appear in the main register."""
    namespace = f"test-{uuid.uuid4().hex[:8]}"
    desks: list[Desk] = []
    state = {"person": None}

    async def join(name: str, *, kind: str = "agent", can_start: bool = True) -> Desk:
        if kind == "agent" and state["person"] is None:
            await join("keeper", kind="person")
        desk = await Desk.join(DESK, name, tmp_path / name, kind=kind, namespace=namespace,
                               answerable=state["person"] if kind == "agent" else None)
        desk.host = RecordingHost(can_start)
        if kind == "person" and state["person"] is None:
            state["person"] = desk.me
        desks.append(desk)
        return desk

    join.state_dir = lambda desk: desk.state_dir  # type: ignore[attr-defined]
    join.namespace = namespace  # type: ignore[attr-defined]
    yield join
    for desk in desks:
        await desk.close()
