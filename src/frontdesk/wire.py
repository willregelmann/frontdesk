"""What travels through the desk, and how it is written into Matrix events.

A message is an ordinary ``m.room.message`` (so a person reads it in any chat client) carrying an
``io.frontdesk`` block. A message typed by a person has no block at all; ``parse_message`` gives it
the meaning the map assigns: from that person, waking, addressed to whatever this line reaches.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

NS = "io.frontdesk"
EV_IDENTITY = "io.frontdesk.identity"   # state event in the register, state_key = the identity's own id
EV_STATUS = "io.frontdesk.status"       # what became of a message; references it
ACCT_BINDING = "io.frontdesk.binding"   # room account data: which of MY channels this line reaches
REGISTER_LOCALPART = "frontdesk"
DEFAULT_CHANNEL = "default"

WAKE, WAIT = "wake", "wait"
MESSAGE, REQUEST, OUTCOME, AGREEMENT, WITHDRAW = "message", "request", "outcome", "agreement", "withdraw"

# States of a message. HELD and WITHDRAWN are kinds of "accepted": the desk has it, the receiver doesn't.
ACCEPTED, HELD, WITHDRAWN = "accepted", "held", "withdrawn"
ARRIVED, TAKEN_IN, REFUSED, EXPIRED, FAILED = "arrived", "taken_in", "refused", "expired", "failed"

# Outcomes of a request.
DONE = "done"

AGREE_NOBODY, AGREE_SELF = "nobody", "self"


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Listing:
    """What the register says about one identity."""
    identity: str
    name: str
    kind: str
    answerable: Optional[str]
    channels: dict[str, dict]
    offers: dict[str, dict]
    there: Optional[bool]  # True/False only when the desk knows; None when it doesn't


@dataclass(frozen=True)
class Receipt:
    """What Send says: the desk has the message (or why it doesn't). Never that the receiver has it."""
    id: str
    state: str
    held_until: Optional[int] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class Trace:
    """What became of a message."""
    id: str
    state: str
    reason: Optional[str] = None
    held_until: Optional[int] = None
    at: Optional[int] = None


@dataclass
class Arrival:
    """One message as it appears in the receiver's conversation."""
    id: str                      # the desk's id for the message
    ref: str                     # where it sits in its line (the Matrix event id)
    line: str
    kind: str
    sender: str                  # verified by the desk, never taken from the message
    sender_name: str
    sender_kind: str             # "agent" | "person" | "unknown"
    from_channel: Optional[str]
    to_channel: str
    text: str
    arrive: str
    sent_at: int
    answers: Optional[str] = None
    late_by_ms: int = 0
    crossed: int = 0             # messages of ours the sender had not seen when it wrote
    expires: Optional[int] = None
    request: Optional[dict] = None    # {"offer", "args", "asker"} for a request or an agreement
    outcome: Optional[dict] = None    # {"result", "detail", "asked", "agreed"}
    extra: dict = field(default_factory=dict)


def message_content(text: str, *, kind: str = MESSAGE, to: Optional[str], sender_channel: Optional[str],
                    arrive: str, msg_id: Optional[str] = None, answers: Optional[str] = None,
                    expires: Optional[int] = None, due: Optional[int] = None, seen: Optional[str] = None,
                    **more: Any) -> dict:
    block: dict[str, Any] = {"id": msg_id or new_id(), "kind": kind, "arrive": arrive}
    for key, value in (("to", to), ("from", sender_channel), ("answers", answers), ("expires", expires),
                       ("due", due), ("seen", seen), *more.items()):
        if value is not None:
            block[key] = value
    content: dict[str, Any] = {"msgtype": "m.text", "body": text, NS: block}
    if answers:
        content["m.relates_to"] = {"m.in_reply_to": {"event_id": answers}}
    return content


def parse_block(event: dict) -> dict:
    """The ``io.frontdesk`` block of a message event, with the defaults a plain typed message gets."""
    raw = event.get("content", {}).get(NS)
    block = dict(raw) if isinstance(raw, dict) else {}
    block.setdefault("id", event["event_id"])
    block.setdefault("kind", MESSAGE)
    if block.get("arrive") not in (WAKE, WAIT):
        block["arrive"] = WAKE
    return block


def _ago(ms: int) -> str:
    seconds = ms // 1000
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


_LABELS = {MESSAGE: "message", REQUEST: "request", AGREEMENT: "agreement", OUTCOME: "outcome", WITHDRAW: "withdrawal"}


def describe(arrival: Arrival) -> tuple[dict[str, str], str]:
    """How an arrival looks to an agent, the same on every host: attributes the desk vouches for,
    and the sender's own words kept apart from them."""
    attrs = {"kind": _LABELS.get(arrival.kind, arrival.kind), "from": arrival.sender_name,
             "from_kind": arrival.sender_kind, "ref": arrival.ref,
             "sent": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(arrival.sent_at / 1000))}
    if arrival.answers:
        attrs["answers"] = arrival.answers
    if arrival.late_by_ms:
        attrs["late_by"] = _ago(arrival.late_by_ms)
    if arrival.crossed:
        attrs["sender_had_not_seen_your_last"] = str(arrival.crossed)
    if arrival.request:
        attrs["offer"] = str(arrival.request.get("offer"))
        attrs["settle_with_ref"] = arrival.ref
    if arrival.outcome:
        attrs["result"] = str(arrival.outcome.get("result"))
    return attrs, arrival.text


def render(arrival: Arrival) -> str:
    """One arrival as text for a conversation. Nothing the sender wrote can close the tag early or
    pass itself off as the desk's."""
    attrs, body = describe(arrival)
    head = " ".join(f'{key}="{value.replace(chr(34), chr(39))}"' for key, value in attrs.items())
    body = body.replace("<frontdesk", "&lt;frontdesk").replace("</frontdesk", "&lt;/frontdesk")
    return f"<frontdesk {head}>\n{body}\n</frontdesk>"
