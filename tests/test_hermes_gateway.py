"""Hermes as a host: a real ``hermes gateway run`` process, with the Front Desk plugin loaded
through Hermes's own plugin discovery, a real desk, and a scripted model.

Needs a Hermes checkout whose virtualenv has frontdesk installed:
    FRONTDESK_TEST_HERMES=/path/to/hermes-agent pytest tests/test_hermes_gateway.py
"""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from frontdesk import wire
from tests.conftest import DESK, until
from tests.fake_llm import FakeLLM

HERMES = os.environ.get("FRONTDESK_TEST_HERMES")
pytestmark = pytest.mark.skipif(not HERMES, reason="set FRONTDESK_TEST_HERMES to a Hermes checkout")
PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "hermes" / "frontdesk"


class Gateway:
    def __init__(self, root: Path, llm: FakeLLM):
        self.root, self.home, self.llm = root, root / ".hermes", llm
        self.process = None

    def env(self) -> dict:
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TERM")}
        # The guard bypass tells Hermes this spawned child's state.db, in a temp home, is meant.
        return {**keep, "HOME": str(self.root), "HERMES_HOME": str(self.home), "HERMES_STATE_DB_GUARD_BYPASS": "1"}

    def configure(self) -> None:
        (self.home / "plugins").mkdir(parents=True)
        (self.home / "plugins" / "frontdesk").symlink_to(PLUGIN)
        (self.home / "config.yaml").write_text(
            "model:\n  provider: custom\n  model: fake\n  default: fake\n"
            f"  base_url: {self.llm.url}\n  api_key: none\n"
            "plugins:\n  enabled: [frontdesk]\n"
            "gateway:\n  multiplex_profiles: false\n"
            "platforms:\n  frontdesk:\n    enabled: true\n"
            "memory:\n  enabled: false\n")

    def start(self) -> None:
        self.log = open(self.root / "gateway.log", "w")
        self.process = subprocess.Popen([f"{HERMES}/.venv/bin/hermes", "gateway", "run"], env=self.env(),
                                        cwd=self.root, stdout=self.log, stderr=subprocess.STDOUT)

    def output(self) -> str:
        logs = [self.root / "gateway.log", *sorted((self.home / "logs").glob("*.log"))]
        return "\n".join(p.read_text(errors="replace") for p in logs if p.exists())

    def wait_for(self, text: str, timeout: float = 90) -> None:
        deadline = time.monotonic() + timeout
        while text not in self.output():
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"gateway never said {text!r}:\n{self.output()[-3000:]}")
            time.sleep(0.5)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.log.close()


@pytest.fixture
async def hermes(people, tmp_path):
    """Ash, run by a real Hermes gateway. Yields (gateway, wren's desk, ash's identity)."""
    wren = await people("wren")
    llm = FakeLLM()
    gateway = Gateway(tmp_path / "ash-machine", llm)
    gateway.configure()
    (gateway.home / "frontdesk").mkdir()
    (gateway.home / "frontdesk" / "offers.json").write_text(json.dumps({
        "echo": {"description": "Says back what it was given", "agree": "self", "listed": True,
                 "command": ["sh", "-c", "cat"]}}))
    joined = subprocess.run(
        [f"{HERMES}/.venv/bin/python", "-m", "frontdesk.cli", "join", f"ash-{wren.profile['name'][-8:]}",
         "--answerable", wren.profile["answerable"], "--desk", DESK],
        env={**gateway.env(), "FRONTDESK_HOME": str(gateway.home / "frontdesk")}, capture_output=True, text=True)
    assert joined.returncode == 0, joined.stderr
    ash = joined.stdout.split()[0]
    gateway.start()
    try:
        gateway.wait_for("Front Desk: attending")
        yield gateway, wren, ash
    finally:
        gateway.stop()
        llm.close()
        (gateway.root / "llm-requests.json").write_text(json.dumps(llm.requests, indent=1, default=str))


async def test_message_to_the_default_channel_starts_a_session_that_answers_down_the_line(hermes):
    gateway, wren, ash = hermes

    sent = await wren.send(ash, "ping", conversation="wren-with-will")
    await until(lambda: len(wren.ledger.pending(wren.ledger.channel_of("wren-with-will")["handle"])) >= 2, wren,
                timeout=40)
    arrivals = await wren.take("wren-with-will")

    # The agent answered with its tool, and its closing reply also came back down the line.
    assert [a.text for a in arrivals] == ["pong from hermes", "Told them."]
    assert all(a.sender == ash and a.sender_kind == "agent" for a in arrivals)
    assert arrivals[0].answers == wren.ledger.attempt(sent.id)["event_id"]
    await until(lambda: _taken_in(wren, sent), wren, timeout=30)

    # What the model was shown: the desk's instructions, a way to its tools, and the arrival as an arrival.
    turn = next(r for r in gateway.llm.requests if r.get("tools"))
    system = " ".join(str(m.get("content")) for m in turn["messages"] if m["role"] == "system")
    shown = str(turn["messages"][-1]["content"])
    assert "Front Desk" in system and "frontdesk_send" in system and "frontdesk_settle" in system
    assert "<frontdesk" in shown and "ping" in shown and wren.profile["name"] in shown


async def _taken_in(desk, receipt):
    return (await desk.trace(receipt.id)).state == wire.TAKEN_IN


async def test_second_message_wakes_the_same_session_through_its_listed_channel(hermes):
    gateway, wren, ash = hermes
    await wren.send(ash, "ping", conversation="w1")
    await until(lambda: len(wren.ledger.pending(wren.ledger.channel_of("w1")["handle"])) >= 2, wren, timeout=60)
    first = await wren.take("w1")
    await wren.commit("w1")
    channel = first[0].from_channel
    assert channel in (await wren.find(ash))[0].channels          # the session it started is now listed

    again = await wren.send(ash, "ping again", conversation="w1", channel=channel)
    await until(lambda: len(wren.ledger.pending(wren.ledger.channel_of("w1")["handle"])) >= 2, wren, timeout=60)
    second = await wren.take("w1")

    assert second[0].answers == wren.ledger.attempt(again.id)["event_id"] and second[0].from_channel == channel
    turns = [r for r in gateway.llm.requests if r.get("tools") and "ping again" in str(r["messages"][-1].get("content"))]
    assert any("ping" in str(m.get("content")) and m["role"] == "user" for m in turns[0]["messages"][:-1]), \
        "the second message arrived in the same conversation as the first"


async def test_request_waiting_on_the_agent_is_agreed_done_by_the_host_and_answered(hermes):
    gateway, wren, ash = hermes
    await until(lambda: _offers(wren, ash), wren, timeout=30)

    await wren.ask(ash, "echo", {"word": "marmalade"}, conversation="w1")
    await until(lambda: [r for r in wren.ledger.pending(wren.ledger.channel_of("w1")["handle"])
                         if json.loads(r["arrival"])["kind"] == wire.OUTCOME], wren, timeout=60)
    outcome = next(a for a in await wren.take("w1") if a.kind == wire.OUTCOME)

    assert outcome.outcome["result"] == wire.DONE and "marmalade" in outcome.outcome["detail"]
    assert outcome.outcome["agreed"] == ash and outcome.outcome["asked"] == wren.me


async def _offers(wren, ash):
    found = await wren.find(ash)
    return found and "echo" in found[0].offers
