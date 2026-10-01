"""Offers and requests: asking for something to be done, agreeing, doing it once, saying how it went.

Every request ends in exactly one outcome sent back to where it came from. The ledger row is
advanced with a single conditional UPDATE before each step, so an offer is done at most once per
request even if the host stops partway, including when the offer is restarting the host itself.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional

import httpx

from frontdesk import wire
from frontdesk.matrix import MatrixError
from frontdesk.wire import Arrival, Receipt, now_ms

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
    # Provided by Desk.
    ledger: Any
    matrix: Any
    me: str
    _handlers: dict[str, Handler]

    # ── listing offers ───────────────────────────────────────────────────────────────────────────

    async def offer(self, name: str, description: str, handler: Optional[Handler] = None, *,
                    needs: Optional[dict] = None, agree: str = wire.AGREE_NOBODY,
                    survives_restart: bool = False) -> None:
        """List something this identity will do when asked. ``handler`` is what it does, fixed
        here by the host: whoever asks supplies only ``needs``. ``agree`` is who must agree first:
        "nobody", "self", or the name of another listed identity."""
        if agree not in (wire.AGREE_NOBODY, wire.AGREE_SELF):
            approver = await self._listing(self._resolve(agree), fresh=True)  # type: ignore[attr-defined]
            if approver is None:
                from frontdesk.desk import DeskError
                raise DeskError(f"{agree!r} is not listed, so they can't be the one who agrees")
            agree = approver.identity
        self.ledger.put_offer(name, description, needs or {}, agree, survives_restart)
        if handler is not None:
            self._handlers[name] = handler
        await self._publish()  # type: ignore[attr-defined]

    async def withdraw_offer(self, name: str) -> None:
        self.ledger.drop_offer(name)
        self._handlers.pop(name, None)
        await self._publish()  # type: ignore[attr-defined]

    # ── asking ───────────────────────────────────────────────────────────────────────────────────

    async def ask(self, to: str, offer: str, args: Optional[dict] = None, *, conversation: Optional[str] = None,
                  channel: Optional[str] = None, expires_in_s: float = DEFAULT_REQUEST_MS / 1000) -> Receipt:
        """Ask for someone's offer. The outcome arrives later as a message of its own."""
        peer = self._resolve(to)  # type: ignore[attr-defined]
        try:
            listing = await self._listing(peer, fresh=True)  # type: ignore[attr-defined]
        except (MatrixError, httpx.HTTPError):
            listing = None  # send() reports the register being unreachable
        if listing is not None and offer not in listing.offers:
            msg_id = wire.new_id()
            self.ledger.log_attempt(msg_id, wire.REQUEST, peer, channel, None, None)
            reason = f"{listing.name} lists no offer called {offer!r}"
            self.ledger.update_attempt(msg_id, state=wire.REFUSED, reason=reason)
            return Receipt(id=msg_id, state=wire.REFUSED, reason=reason)
        text = f"Request: {offer}" + (f" {json.dumps(args)}" if args else "")
        return await self.send(  # type: ignore[attr-defined]
            to, text, conversation=conversation, channel=channel, kind=wire.REQUEST, offer=offer,
            args=args or {}, expires=now_ms() + int(expires_in_s * 1000))

    async def settle(self, ref: str, agree: bool, reason: str = "") -> None:
        """Agree to or refuse a request that is waiting on this identity."""
        from frontdesk.desk import DeskError
        request = self.ledger.request(ref)
        if request is not None:
            offer = self.ledger.offer(request["offer"])
            if request["state"] != "awaiting" or offer is None or offer["agree"] != wire.AGREE_SELF:
                raise DeskError("that request is not waiting on you")
            if not agree:
                await self._outcome(ref, wire.REFUSED, reason or "refused", _OPEN)
            elif self.ledger.move_request(ref, ("awaiting",), "agreed", agreed_by=self.me):
                await self._perform(ref)
            return
        row = self.ledger.inbox_by_msg(ref)
        if row is None or json.loads(row["arrival"]).get("kind") != wire.AGREEMENT:
            raise DeskError(f"nothing waiting on you with ref {ref!r}")
        receipt = await self.send(  # type: ignore[attr-defined]
            "", "yes" if agree else f"no: {reason}" if reason else "no", answers=row["event_id"],
            kind=wire.AGREEMENT, agree=agree)
        if receipt.state != wire.ACCEPTED:
            raise DeskError(f"your answer was not sent: {receipt.reason}")

    # ── being asked ──────────────────────────────────────────────────────────────────────────────

    async def _accept_request(self, arrival: Arrival) -> bool:
        """Record a request and start it on its way. True when it must now be shown to this
        identity's own conversation so the agent can agree or refuse."""
        if arrival.request is None:
            return True  # not well formed: show it as the message it is
        ref, name = arrival.ref, arrival.request["offer"]
        self.ledger.add_request(ref, arrival.line, name, arrival.request["args"], arrival.sender,
                                arrival.expires or now_ms() + DEFAULT_REQUEST_MS)
        offer = self.ledger.offer(name)
        if offer is None:
            await self._status(arrival.line, ref, wire.ARRIVED)  # type: ignore[attr-defined]
            await self._outcome(ref, wire.REFUSED, f"no offer called {name!r} is listed", _OPEN, arrival=arrival)
            return False
        if offer["agree"] == wire.AGREE_SELF:
            self.ledger.move_request(ref, ("received",), "awaiting")
            return True
        await self._status(arrival.line, ref, wire.ARRIVED)  # type: ignore[attr-defined]
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
            listing = await self._listing(approver, fresh=True)  # type: ignore[attr-defined]
            if listing is None:
                await self._outcome(ref, wire.FAILED, "whoever must agree is no longer listed", _OPEN, arrival=arrival)
                return
            room = await self._open_line(  # type: ignore[attr-defined]
                approver, listing, wire.DEFAULT_CHANNEL, wire.DEFAULT_CHANNEL, agreement_for=ref)
            request = arrival.request or {}
            needs = f" with {json.dumps(request['args'])}" if request.get("args") else ""
            text = (f"{arrival.sender_name} asks {self.profile.get('name')} to do "  # type: ignore[attr-defined]
                    f"\"{request.get('offer')}\"{needs}. Answer yes or no.")
            await self.matrix.send(room, "m.room.message", f"agr-{ref}", wire.message_content(
                text, kind=wire.AGREEMENT, to=None, sender_channel=None, arrive=wire.WAKE,
                expires=self.ledger.request(ref)["expires"], offer=request.get("offer"),
                args=request.get("args") or {}, asker=arrival.sender, request=ref))
            self.ledger._run("UPDATE requests SET agreement_room=? WHERE ref=?", room, ref)
        except (MatrixError, httpx.HTTPError) as exc:
            await self._outcome(ref, wire.FAILED, f"could not ask for agreement: {exc}", _OPEN, arrival=arrival)

    async def _agreement_answer(self, line: Any, event: dict, block: dict) -> None:
        """An answer from whoever the offer names. One answer settles it; nobody else's counts
        (the line holds only them, and the desk verified the sender)."""
        ref = line["agreement_for"]
        request = self.ledger.request(ref)
        if request is None or request["state"] != "awaiting":
            return
        body = str(event["content"].get("body") or "")
        verdict = block["agree"] if isinstance(block.get("agree"), bool) else _verdict(body)
        if verdict is None:
            await self.matrix.send(line["room_id"], "m.room.message", f"hint-{event['event_id']}", wire.message_content(
                "That wasn't a yes or a no, so nothing was decided. Answer yes or no.",
                to=None, sender_channel=None, arrive=wire.WAIT))
            return
        await self._status(line["room_id"], event["event_id"], wire.TAKEN_IN)  # type: ignore[attr-defined]
        if not verdict:
            await self._outcome(ref, wire.REFUSED, body, ("awaiting",))
        elif self.ledger.move_request(ref, ("awaiting",), "agreed", agreed_by=event["sender"]):
            await self._perform(ref)

    async def _withdrawn(self, arrival: Arrival) -> None:
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
        handler = self._handlers.get(request["offer"])
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
        request = self.ledger.request(ref)
        if arrival is None:
            row = self.ledger.inbox_row(ref)
            stored = json.loads(row["arrival"]) if row else {}
            asker_channel = stored.get("from_channel")
        else:
            asker_channel = arrival.from_channel
        agreed = request["agreed_by"]
        text = f"{request['offer']}: {result.replace('_', ' ')}" + (f". {detail}" if detail else "")
        msg_id = f"out-{ref}"
        self.ledger.log_attempt(msg_id, wire.OUTCOME, request["asker"], asker_channel, None, None)
        try:
            sent = await self.matrix.send(request["room_id"], "m.room.message", msg_id, wire.message_content(
                text, kind=wire.OUTCOME, to=asker_channel, sender_channel=None, arrive=wire.WAKE, msg_id=msg_id,
                answers=ref, result=result, detail=detail, asked=request["asker"], agreed=agreed,
                offer=request["offer"]))
            self.ledger.update_attempt(msg_id, state=wire.ACCEPTED, reason=None, room_id=request["room_id"],
                                       event_id=sent["event_id"])
        except (MatrixError, httpx.HTTPError) as exc:
            self.ledger.update_attempt(msg_id, reason=f"the desk did not take it: {exc}")
            logger.warning("outcome of %s could not be sent: %s", ref, exc)

    async def _expire_requests(self) -> None:
        for request in self.ledger.requests_in(*_OPEN):
            if now_ms() > request["expires"]:
                await self._outcome(request["ref"], wire.EXPIRED, None, _OPEN)

    async def _recover_requests(self) -> None:
        """Requests caught mid-flight by a restart. One that had started is never started again."""
        for request in self.ledger.requests_in("started"):
            offer = self.ledger.offer(request["offer"])
            if offer is not None and offer["survives_restart"]:
                await self._outcome(request["ref"], wire.DONE, "done; it restarted what was doing it", ("started",))
            else:
                await self._outcome(request["ref"], wire.FAILED, "interrupted partway; not done again", ("started",))
        for request in self.ledger.requests_in("agreed"):
            await self._perform(request["ref"])
