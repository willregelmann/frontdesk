"""Offers and requests: asking for something to be done, agreeing, doing it once, saying how it went.

Every request ends in exactly one outcome sent back to where it came from. The ledger row is
advanced with a single conditional UPDATE before each step, so an offer is done at most once per
request even if the host stops partway, including when the offer is restarting the host itself.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

import httpx

from frontdesk import wire
from frontdesk.matrix import MatrixError
from frontdesk.wire import Arrival, DeskError, Receipt, now_ms

if TYPE_CHECKING:
    from frontdesk.desk import Desk

logger = logging.getLogger("frontdesk")

DEFAULT_REQUEST_MS = 10 * 60_000
_OPEN = ("received", "awaiting", "agreed")
_YES = {"yes", "y", "agree", "agreed", "approve", "approved", "ok", "okay"}
_NO = {"no", "n", "refuse", "refused", "deny", "denied", "decline", "declined"}

Handler = Callable[[dict], Awaitable[Optional[str]]]


def _verdict(text: str) -> Optional[bool]:
    words = text.strip().lower().replace(",", " ").replace(".", " ").replace("!", " ").replace(":", " ").split()
    if not words:
        return None
    return True if words[0] in _YES else False if words[0] in _NO else None


class Requests:
    """Request (docs/capabilities/REQUEST.md) for one identity, built on its desk's public side:
    a request, an agreement and an outcome are each sent as a message."""

    def __init__(self, desk: "Desk"):
        self.desk = desk
        self.ledger = desk.ledger

    # ── asking ───────────────────────────────────────────────────────────────────────────────────

    async def ask(self, to: str, offer: str, args: Optional[dict] = None, *, conversation: Optional[str] = None,
                  channel: Optional[str] = None, expires_in_s: Optional[float] = None) -> Receipt:
        """Ask for someone's offer. The outcome arrives later as a message of its own."""
        try:
            listing = await self.desk.lookup(to)
        except (MatrixError, httpx.HTTPError):
            listing = None  # send() reports the register being unreachable
        if listing is not None and offer not in listing.offers:
            msg_id = wire.new_id()
            self.ledger.log_attempt(msg_id, wire.REQUEST, listing.identity, channel, None, None)
            reason = f"{listing.name} lists no offer called {offer!r}"
            self.ledger.update_attempt(msg_id, state=wire.REFUSED, reason=reason)
            return Receipt(id=msg_id, state=wire.REFUSED, reason=reason)
        text = f"Request: {offer}" + (f" {json.dumps(args)}" if args else "")
        lasts_ms = DEFAULT_REQUEST_MS if expires_in_s is None else int(expires_in_s * 1000)
        return await self.desk.send(
            to, text, conversation=conversation, channel=channel, kind=wire.REQUEST, offer=offer,
            args=args or {}, expires=now_ms() + lasts_ms)

    async def settle(self, ref: str, agree: bool, reason: str = "") -> None:
        """Agree to or refuse a request that is waiting on this identity."""
        request = self.ledger.request(ref)
        if request is not None:
            offer = self.ledger.offer(request["offer"])
            if request["state"] != "awaiting" or offer is None or offer["agree"] != wire.AGREE_SELF:
                raise DeskError("that request is not waiting on you")
            if not agree:
                await self._outcome(ref, wire.REFUSED, reason or "refused", _OPEN)
            elif self.ledger.move_request(ref, ("awaiting",), "agreed", agreed_by=self.desk.me):
                await self._perform(ref)
            return
        row = self.ledger.inbox_by_msg(ref)
        if row is None or json.loads(row["arrival"]).get("kind") != wire.AGREEMENT:
            raise DeskError(f"nothing waiting on you with ref {ref!r}")
        receipt = await self.desk.send(
            "", "yes" if agree else f"no: {reason}" if reason else "no", answers=row["event_id"],
            kind=wire.AGREEMENT, agree=agree)
        if receipt.state != wire.ACCEPTED:
            raise DeskError(f"your answer was not sent: {receipt.reason}")

    # ── being asked ──────────────────────────────────────────────────────────────────────────────

    async def received(self, arrival: Arrival) -> bool:
        """Record a request and start it on its way. True when it must now be shown to this
        identity's own conversation so the agent can agree or refuse."""
        if arrival.request is None:
            return True  # not well formed: show it as the message it is
        ref, name = arrival.ref, arrival.request["offer"]
        self.ledger.add_request(ref, arrival.line, name, arrival.request["args"], arrival.sender,
                                arrival.expires or now_ms() + DEFAULT_REQUEST_MS)
        offer = self.ledger.offer(name)
        if offer is None:
            await self.desk.report_state(arrival.line, ref, wire.ARRIVED)
            await self._outcome(ref, wire.REFUSED, f"no offer called {name!r} is listed", _OPEN, arrival=arrival)
            return False
        if offer["agree"] == wire.AGREE_SELF:
            self.ledger.move_request(ref, ("received",), "awaiting")
            return True
        await self.desk.report_state(arrival.line, ref, wire.ARRIVED)
        if offer["agree"] == wire.AGREE_NOBODY:
            self.ledger.move_request(ref, ("received",), "agreed", agreed_by=wire.AGREE_NOBODY)
            await self._perform(ref, arrival=arrival)
        else:
            self.ledger.move_request(ref, ("received",), "awaiting")
            await self._ask_agreement(ref, arrival, offer["agree"])
        return False

    async def _ask_agreement(self, ref: str, arrival: Arrival, approver: str) -> None:
        """Agreement is another identity's to give: asking for it is itself a message to them."""
        try:
            listing = await self.desk.lookup(approver)
            if listing is None:
                await self._outcome(ref, wire.FAILED, "whoever must agree is no longer listed", _OPEN, arrival=arrival)
                return
            room = await self.desk.open_line(
                approver, listing, wire.DEFAULT_CHANNEL, wire.DEFAULT_CHANNEL, agreement_for=ref)
            request = arrival.request or {}
            needs = f" with {json.dumps(request['args'])}" if request.get("args") else ""
            text = (f"{arrival.sender_name} asks {self.desk.profile.get('name')} to do "
                    f"\"{request.get('offer')}\"{needs}. Answer yes or no.")
            expires = self.ledger.request(ref)["expires"]
            asked = await self.desk.post(
                room, f"agr-{ref}", wire.message_content(
                    text, kind=wire.AGREEMENT, to=None, sender_channel=None, arrive=wire.WAKE, expires=expires,
                    offer=request.get("offer"), args=request.get("args") or {}, asker=arrival.sender, request=ref),
                kind=wire.AGREEMENT, to_identity=approver, to_channel=None, from_channel=None, expires=expires)
            if asked.state == wire.FAILED:
                await self._outcome(ref, wire.FAILED, f"could not ask for agreement: {asked.reason}", _OPEN,
                                    arrival=arrival)
                return
            self.ledger.note_agreement_room(ref, room)
        except (MatrixError, httpx.HTTPError) as exc:
            await self._outcome(ref, wire.FAILED, f"could not ask for agreement: {exc}", _OPEN, arrival=arrival)

    async def agreement_answered(self, line: Any, event: dict, block: dict) -> None:
        """An answer from whoever the offer names. One answer settles it; nobody else's counts
        (the line holds only them, and the desk verified the sender)."""
        ref = line["agreement_for"]
        request = self.ledger.request(ref)
        if request is None or request["state"] != "awaiting":
            return
        body = str(event["content"].get("body") or "")
        verdict = block["agree"] if isinstance(block.get("agree"), bool) else _verdict(body)
        if verdict is None:
            await self.desk.post(
                line["room_id"], f"hint-{event['event_id']}", wire.message_content(
                    "That wasn't a yes or a no, so nothing was decided. Answer yes or no.",
                    to=None, sender_channel=None, arrive=wire.WAIT),
                kind=wire.MESSAGE, to_identity=line["peer"], to_channel=None, from_channel=None)
            return
        await self.desk.report_state(line["room_id"], event["event_id"], wire.TAKEN_IN)
        if not verdict:
            await self._outcome(ref, wire.REFUSED, body, ("awaiting",))
        elif self.ledger.move_request(ref, ("awaiting",), "agreed", agreed_by=event["sender"]):
            await self._perform(ref)

    async def withdrawn(self, arrival: Arrival) -> None:
        request = self.ledger.request(arrival.answers) if arrival.answers else None
        if request is not None and request["asker"] == arrival.sender:
            await self._outcome(request["ref"], wire.REFUSED, "withdrawn by whoever asked", _OPEN)

    # ── doing ────────────────────────────────────────────────────────────────────────────────────

    async def _perform(self, ref: str, *, arrival: Optional[Arrival] = None) -> None:
        request = self.ledger.request(ref)
        if now_ms() > request["expires"]:
            await self._outcome(ref, wire.EXPIRED, None, _OPEN, arrival=arrival)
            return
        if not self.ledger.move_request(ref, ("agreed",), "started"):
            return  # someone else has it, or it was withdrawn
        handler = self.desk.handler(request["offer"])
        if handler is None:
            await self._outcome(ref, wire.FAILED, "nothing here can do that right now", ("started",), arrival=arrival)
            return
        try:
            detail = await handler(json.loads(request["args"]))
        except Exception as exc:  # the offer's own action failed; that is the outcome
            await self._outcome(ref, wire.FAILED, str(exc) or type(exc).__name__, ("started",), arrival=arrival)
            return
        await self._outcome(ref, wire.DONE, detail, ("started",), arrival=arrival)

    async def _outcome(self, ref: str, result: str, detail: Optional[str], from_states: tuple[str, ...], *,
                       arrival: Optional[Arrival] = None) -> None:
        """Close a request and say so to whoever asked. Only one caller ever closes a request."""
        if not self.ledger.move_request(ref, from_states, result, detail=detail):
            return
        await self._send_outcome(ref, arrival.from_channel if arrival is not None else None)

    async def _send_outcome(self, ref: str, asker_channel: Optional[str] = None) -> None:
        """Send the outcome of a closed request. Safe to call again until the desk has it: the
        transaction id is fixed per request, so a retry never produces a second outcome."""
        request = self.ledger.request(ref)
        msg_id = f"out-{ref}"
        attempt = self.ledger.attempt(msg_id)
        if attempt is not None:
            asker_channel = attempt["to_channel"]
        elif asker_channel is None:
            row = self.ledger.inbox_row(ref)
            asker_channel = (json.loads(row["arrival"]) if row else {}).get("from_channel")
        result, detail = request["state"], request["detail"]
        text = f"{request['offer']}: {result.replace('_', ' ')}" + (f". {detail}" if detail else "")
        sent = await self.desk.post(
            request["room_id"], msg_id, wire.message_content(
                text, kind=wire.OUTCOME, to=asker_channel, sender_channel=None, arrive=wire.WAKE, msg_id=msg_id,
                answers=ref, result=result, detail=detail, asked=request["asker"], agreed=request["agreed_by"],
                offer=request["offer"]),
            kind=wire.OUTCOME, to_identity=request["asker"], to_channel=asker_channel, from_channel=None)
        if sent.state == wire.FAILED:
            logger.warning("outcome of %s could not be sent; it is sent again later: %s", ref, sent.reason)

    async def tick(self) -> None:
        """Expire requests whose time has passed, then send every outcome the desk doesn't have yet."""
        await self._expire_requests()
        await self._resend_outcomes()

    async def _resend_outcomes(self) -> None:
        """Every closed request whose outcome the desk does not have yet: never silence."""
        for request in self.ledger.unsent_outcomes(wire.DONE, wire.FAILED, wire.REFUSED, wire.EXPIRED):
            await self._send_outcome(request["ref"])

    async def _expire_requests(self) -> None:
        for request in self.ledger.requests_in(*_OPEN):
            if now_ms() > request["expires"]:
                await self._outcome(request["ref"], wire.EXPIRED, None, _OPEN)

    async def recover(self) -> None:
        """Requests caught mid-flight by a restart. One that had started is never started again."""
        for request in self.ledger.requests_in("started"):
            offer = self.ledger.offer(request["offer"])
            if offer is not None and offer["survives_restart"]:
                await self._outcome(request["ref"], wire.DONE, "done; it restarted what was doing it", ("started",))
            else:
                await self._outcome(request["ref"], wire.FAILED, "interrupted partway; not done again", ("started",))
        for request in self.ledger.requests_in("agreed"):
            await self._perform(request["ref"])
