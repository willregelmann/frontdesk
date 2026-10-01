"""``frontdesk``: join the desk and use it from a terminal.

A person joins with ``frontdesk join will --person`` and then signs into any Matrix chat client
with what ``frontdesk proof`` prints. An agent's host joins once and afterwards holds the proof
itself. ``frontdesk hook`` is what the Claude Code plugin's hooks run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from frontdesk import Desk, DeskError, wire
from frontdesk.wire import now_ms

DEFAULT_DESK = "http://127.0.0.1:8008"


def home_for(name: str | None) -> Path:
    if os.environ.get("FRONTDESK_HOME"):
        return Path(os.environ["FRONTDESK_HOME"]).expanduser()
    return Path.home() / ".frontdesk" / (name or os.environ.get("FRONTDESK_AS") or "default")


def _print(value) -> None:
    print(json.dumps(value, indent=2, default=str))


async def _join(args) -> int:
    home = home_for(args.name)
    desk = await Desk.join(args.desk, args.name, home, kind="person" if args.person else "agent",
                           answerable=args.answerable)
    print(f"{desk.me} is listed. Its proof is kept in {home}.")
    if args.person:
        _print(desk.proof_for_a_chat_client())
    await desk.close()
    return 0


async def _with_desk(args, action) -> int:
    desk = Desk(home_for(args.as_name), seat=getattr(args, "seat", None) or "cli")
    try:
        return await action(desk) or 0
    finally:
        await desk.close()


async def _find(desk: Desk, args) -> None:
    _print([asdict(entry) for entry in await desk.find(args.name)])


async def _send(desk: Desk, args) -> int:
    receipt = await desk.send(
        args.to, args.text, conversation=args.conversation, channel=args.channel,
        arrive=wire.WAIT if args.wait else wire.WAKE, answers=args.answers,
        hold_until=now_ms() + int(args.hold * 1000) if args.hold else None,
        expires=now_ms() + int(args.expires * 1000) if args.expires else None)
    _print(asdict(receipt))
    return 0 if receipt.state in (wire.ACCEPTED, wire.HELD) else 1


async def _listen(desk: Desk, args) -> None:
    """A host with nothing behind it: print what arrives for one conversation and take it in."""
    conversation = args.conversation

    class Printer:
        async def wake(self, woken: str) -> None:
            for arrival in await desk.take(woken):
                print(wire.render(arrival), flush=True)
            await desk.commit(woken)

        async def start(self, arrival):
            return conversation

    handle = await desk.list_channel(conversation, args.description)
    print(f"listening as {desk.me} on channel {handle} (ctrl-c to stop)", file=sys.stderr)
    await desk.run(Printer(), poll_ms=5000)


async def _hook(args) -> int:
    from frontdesk.hosts.claude_code import hooks
    return await hooks.run(json.load(sys.stdin), home_for(args.as_name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frontdesk", description=__doc__.splitlines()[0])
    parser.add_argument("--as", dest="as_name", help="which identity to act as (default: $FRONTDESK_HOME, "
                        "$FRONTDESK_AS or 'default')")
    sub = parser.add_subparsers(dest="command", required=True)

    join = sub.add_parser("join", help="list a new identity")
    join.add_argument("name")
    join.add_argument("--person", action="store_true", help="a person, not an agent")
    join.add_argument("--answerable", help="the listed person answerable for this agent")
    join.add_argument("--desk", default=os.environ.get("FRONTDESK_DESK", DEFAULT_DESK))

    find = sub.add_parser("find", help="who is listed")
    find.add_argument("name", nargs="?")

    send = sub.add_parser("send", help="leave a message")
    send.add_argument("to")
    send.add_argument("text")
    send.add_argument("--channel")
    send.add_argument("--conversation", help="the conversation this is sent from")
    send.add_argument("--wait", action="store_true", help="read at their next turn instead of waking them")
    send.add_argument("--hold", type=float, metavar="SECONDS")
    send.add_argument("--expires", type=float, metavar="SECONDS")
    send.add_argument("--answers", metavar="REF")

    trace = sub.add_parser("trace", help="what became of a message")
    trace.add_argument("id")
    take_back = sub.add_parser("take-back", help="withdraw a held message or a request")
    take_back.add_argument("id")
    sub.add_parser("sent", help="the record of what was sent")
    sub.add_parser("proof", help="what a person types into a chat client")

    ask = sub.add_parser("ask", help="ask for someone's offer")
    ask.add_argument("to")
    ask.add_argument("offer")
    ask.add_argument("--args", default="{}", help="JSON")
    ask.add_argument("--conversation")

    listen = sub.add_parser("listen", help="print what arrives for a conversation")
    listen.add_argument("--conversation", default="terminal")
    listen.add_argument("--description", default="A terminal")

    sub.add_parser("hook", help="run a Claude Code hook (reads the hook's JSON on stdin)")

    args = parser.parse_args(argv)
    actions = {
        "find": lambda d: _find(d, args),
        "send": lambda d: _send(d, args),
        "trace": lambda d: _async_print(d.trace(args.id)),
        "take-back": lambda d: _async_print(d.take_back(args.id)),
        "sent": lambda d: _sync_print(d.attempts()),
        "proof": lambda d: _sync_print(d.proof_for_a_chat_client()),
        "ask": lambda d: _async_print(d.ask(args.to, args.offer, json.loads(args.args), conversation=args.conversation)),
        "listen": lambda d: _listen(d, args),
    }
    try:
        if args.command == "join":
            return asyncio.run(_join(args))
        if args.command == "hook":
            return asyncio.run(_hook(args))
        return asyncio.run(_with_desk(args, actions[args.command]))
    except DeskError as exc:
        print(f"frontdesk: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


async def _async_print(awaitable) -> None:
    result = await awaitable
    _print(asdict(result) if hasattr(result, "__dataclass_fields__") else result)


async def _sync_print(value) -> None:
    _print(value)


if __name__ == "__main__":
    sys.exit(main())
