"""One identity's side of the desk: list, find, send, receive and request.

A ``Desk`` is what a host (Hermes, Claude Code, the CLI) holds for the identity it runs. The host
supplies two things only it can do, starting a turn and starting a fresh conversation, and tells the
desk about the moments it provides: a turn finished (``commit``), a conversation was rolled back
(``roll_back``) or ended (``end``). Everything that must hold on every host lives here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

from frontdesk import wire
from frontdesk.ledger import Ledger
from frontdesk.matrix import Matrix, MatrixError
from frontdesk.requests import Requests
from frontdesk.wire import Arrival, Listing, Receipt, Trace, now_ms

logger = logging.getLogger("frontdesk")

LATE_MS = 60_000              # beyond this, something that happened after its time says so
_LISTING_TTL_S = 10.0
_NAME = re.compile(r"[a-z0-9_-]+")


def check_name(what: str, value: str) -> str:
    """Names and namespaces are plain words. A dot is what joins them on the desk, so neither may
    contain one: otherwise ``t1.ash`` in the main register is ``ash`` in namespace ``t1``."""
    value = value.lower()
    if not _NAME.fullmatch(value):
        raise DeskError(f"{what} {value!r} may only use a-z, 0-9, '_' and '-'")
    return value


def listed_name(identity: str, namespace: str = "") -> Optional[str]:
    """The name a register shows for ``identity``, from its verified user id and never from its own
    entry. A namespace's register lists only ids under that namespace's prefix, and the main register
    only ids with no namespace at all: anyone may write their own entry into any register room, so the
    room alone does not say who belongs in it."""
    local = identity[1:].split(":", 1)[0]
    if namespace:
        prefix = f"{namespace}."
        return local[len(prefix):] if local.startswith(prefix) and "." not in local[len(prefix):] else None
    return None if "." in local else local


def localpart(name: str, namespace: str = "") -> str:
    """Where a name lives on the desk. Each namespace has its own names and its own register, so
    nothing joined in one is ever listed, found or reachable by name in another."""
    return f"{namespace}.{name}" if namespace else name


class DeskError(Exception):
    """The desk could not do what was asked, and says why."""


class Host(Protocol):
    async def wake(self, conversation: str) -> None:
        """A waking message is ready for ``conversation``: start a turn when free, then ``take``."""

    async def start(self, arrival: Arrival) -> Optional[str]:
        """Start a fresh conversation for a message to the default channel and return its id,
        or None when this host cannot start one right now (the message then waits)."""


class _NoHost:
    async def wake(self, conversation: str) -> None:
        return None

    async def start(self, arrival: Arrival) -> Optional[str]:
        return None


class Desk(Requests):
    def __init__(self, state_dir: Path | str, *, seat: str = "main"):
        self.state_dir = Path(state_dir)
        creds_path = self.state_dir / "credentials.json"
        if not creds_path.exists():
            raise DeskError(f"No identity here yet ({self.state_dir}). Join the desk first.")
        self._creds = json.loads(creds_path.read_text())
        self.me: str = self._creds["user_id"]
        self.server = self.me.split(":", 1)[1]
        self.namespace: str = self._creds.get("namespace", "")
        self.seat = seat
        self.ledger = Ledger(self.state_dir / "ledger.db")
        self.matrix = Matrix(self._creds["homeserver"], self._creds["access_token"])
        self.host: Host = _NoHost()
        self._handlers: dict[str, Any] = {}
        self._listings: dict[str, tuple[float, Optional[Listing]]] = {}
        self._stop = asyncio.Event()

    # ── joining ──────────────────────────────────────────────────────────────────────────────────

    @classmethod
    async def join(cls, homeserver: str, name: str, state_dir: Path | str, *, kind: str = "agent",
                   answerable: Optional[str] = None, seat: str = "main", namespace: str = "") -> "Desk":
        """List a new identity. An agent may name a listed person answerable for it, who is then invited
        to watch its lines; without one, nobody else is invited. ``namespace``
        keeps it out of the main register (tests, trials): it is listed, found and reached only by
        others in the same namespace, and fixed for the life of the identity."""
        state_dir = Path(state_dir)
        name = check_name("name", name)
        namespace = check_name("namespace", namespace) if namespace else ""
        if (state_dir / "credentials.json").exists():
            raise DeskError(f"{state_dir} already holds an identity")
        if kind not in ("agent", "person"):
            raise DeskError("kind is 'agent' or 'person'")
        matrix = Matrix(homeserver)
        password = secrets.token_urlsafe(32)
        try:
            data = await matrix.register(localpart(name, namespace), password)
        except MatrixError as exc:
            if exc.errcode == "M_USER_IN_USE":
                raise DeskError(f"the name {name!r} is taken") from exc
            raise DeskError(f"could not join the desk: {exc}") from exc
        finally:
            await matrix.close()
        state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(state_dir, 0o700)
        fd = os.open(state_dir / "credentials.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump({"homeserver": homeserver, "user_id": data["user_id"], "password": password,
                       "access_token": data["access_token"], "device_id": data["device_id"],
                       "namespace": namespace}, fh)
        desk = cls(state_dir, seat=seat)
        try:
            if answerable:
                person = await desk._listing(desk._resolve(answerable))
                if person is None or person.kind != "person":
                    raise DeskError(f"{answerable!r} is not a listed person")
                answerable = person.identity
            desk.ledger.put("profile", json.dumps({"name": name, "kind": kind, "answerable": answerable}))
            await desk._publish()
            # In a person's chat client an agent is told apart at a glance, and so is anyone joined
            # in a namespace: a trial's Will must never look like the real one.
            tags = [t for t in ("agent" if kind == "agent" else "", namespace) if t]
            if tags:
                await desk.matrix.set_display_name(desk.me, f"{name} ({', '.join(tags)})")
        except BaseException:
            await desk.close()
            raise
        return desk

    async def close(self) -> None:
        self._stop.set()
        await self.matrix.close()
        self.ledger.close()

    async def change_proof(self) -> None:
        """Replace what proves this identity. It stays the same identity, and messages keep arriving."""
        new = secrets.token_urlsafe(32)
        await self.matrix.change_password(self.me, self._creds["password"], new)
        self._creds["password"] = new
        (self.state_dir / "credentials.json").write_text(json.dumps(self._creds))

    def proof_for_a_chat_client(self) -> dict:
        """What a person types into an ordinary chat client to be this identity there."""
        return {"homeserver": self._creds["homeserver"], "user_id": self.me, "password": self._creds["password"]}

    # ── the register ─────────────────────────────────────────────────────────────────────────────

    def _resolve(self, name: str) -> str:
        return name if name.startswith("@") else f"@{localpart(name.lower(), self.namespace)}:{self.server}"

    @property
    def profile(self) -> dict:
        return json.loads(self.ledger.get("profile") or "{}")

    async def _register_room(self) -> str:
        room = self.ledger.get("register")
        if room:
            return room
        register = localpart(wire.REGISTER_LOCALPART, self.namespace)
        alias = f"#{register}:{self.server}"
        room = await self.matrix.resolve_alias(alias)
        if room is None:
            try:
                room = await self.matrix.create_room(
                    preset="public_chat", room_alias_name=register,
                    name=f"Front Desk register ({self.namespace})" if self.namespace else "Front Desk register",
                    power_level_content_override={"events": {wire.EV_IDENTITY: 0}})
            except MatrixError as exc:
                if exc.errcode != "M_ROOM_IN_USE":
                    raise
                room = await self.matrix.resolve_alias(alias)
        assert room is not None
        await self.matrix.join(room)
        self.ledger.put("register", room)
        return room

    async def _publish(self) -> None:
        """Write this identity's own entry. The homeserver refuses anyone else writing it."""
        channels = {wire.DEFAULT_CHANNEL: {"description": "Starts a fresh conversation", "default": True}}
        for row in self.ledger.live_channels():
            channels[row["handle"]] = {"description": row["description"]}
        offers = {row["name"]: {"description": row["description"], "needs": json.loads(row["needs"]),
                                "agree": row["agree"]} for row in self.ledger.offers()}
        try:
            await self.matrix.put_state(await self._register_room(), wire.EV_IDENTITY, self.me,
                                        {**self.profile, "channels": channels, "offers": offers})
        except (MatrixError, httpx.HTTPError) as exc:
            raise DeskError(f"the register could not be updated, so this is not listed: {exc}") from exc
        self._listings.pop(self.me, None)

    def _to_listing(self, identity: str, content: dict, there: Optional[bool]) -> Optional[Listing]:
        # The name comes from the verified user id (listed_name), never the entry's own "name", which
        # is only what the identity says about itself. "kind" can only ever be self-declared: it is
        # passed on as a claim (see wire.describe).
        if not content or content.get("left") or not content.get("name"):
            return None
        name = listed_name(identity, self.namespace)
        if name is None:     # an identity from another namespace (or none) that wrote itself in here
            return None
        return Listing(identity=identity, name=name, kind=content.get("kind", "unknown"),
                       answerable=content.get("answerable"), channels=content.get("channels") or {},
                       offers=content.get("offers") or {}, there=there)

    async def _there(self, identity: str) -> Optional[bool]:
        try:
            presence = (await self.matrix.presence(identity)).get("presence")
        except (MatrixError, httpx.HTTPError):
            return None
        return {"online": True, "offline": False}.get(presence)

    async def _listing(self, identity: str, *, fresh: bool = False) -> Optional[Listing]:
        loop_time = asyncio.get_running_loop().time()
        cached = self._listings.get(identity)
        if cached and not fresh and loop_time - cached[0] < _LISTING_TTL_S:
            return cached[1]
        content = await self.matrix.get_state(await self._register_room(), wire.EV_IDENTITY, identity)
        listing = self._to_listing(identity, content or {}, None)
        self._listings[identity] = (loop_time, listing)
        return listing

    async def find(self, name: Optional[str] = None) -> list[Listing]:
        """Who is listed, where they can be reached and what they offer. Raises when the register
        could not be read: an empty answer always means nobody matched."""
        try:
            if name:
                identity = self._resolve(name)
                content = await self.matrix.get_state(await self._register_room(), wire.EV_IDENTITY, identity)
                listing = self._to_listing(identity, content or {}, await self._there(identity))
                return [listing] if listing else []
            found = []
            for event in await self.matrix.state(await self._register_room()):
                if event["type"] == wire.EV_IDENTITY:
                    listing = self._to_listing(event["state_key"], event["content"],
                                               await self._there(event["state_key"]))
                    if listing:
                        found.append(listing)
            return sorted(found, key=lambda entry: entry.name)
        except (MatrixError, httpx.HTTPError) as exc:
            raise DeskError(f"the register could not be searched: {exc}") from exc

    async def leave(self) -> None:
        """Leave the register. The name is never given to anyone else."""
        await self.matrix.put_state(await self._register_room(), wire.EV_IDENTITY, self.me, {"left": True})
        await self.matrix.call("POST", "/v3/account/deactivate", {
            "auth": {"type": "m.login.password", "identifier": {"type": "m.id.user", "user": self.me},
                     "password": self._creds["password"]}})

    # ── listing channels ─────────────────────────────────────────────────────────────────────────

    async def list_channel(self, conversation: str, description: str = "") -> str:
        """List a conversation so it can be reached. Listing it twice leaves one listing."""
        row = self.ledger.channel_of(conversation)
        if row and not row["ended"]:
            if description and description != row["description"]:
                self.ledger.describe_channel(row["handle"], description)
                await self._publish()
            return row["handle"]
        if row:
            self.ledger.forget_channel(row["handle"])   # withdrawn earlier: it gets a new handle, never the old one
        handle = "ch_" + secrets.token_hex(6)
        self.ledger.add_channel(handle, conversation, description, self.seat)
        try:
            await self._publish()
        except DeskError:
            self.ledger.end_channel(handle)
            raise
        return handle

    async def end(self, conversation: str) -> None:
        """The conversation ended: withdraw its channel and refuse what was still waiting for it."""
        row = self.ledger.channel_of(conversation)
        if row is None or row["ended"]:
            return
        self.ledger.end_channel(row["handle"])
        for pending in self.ledger.pending(row["handle"]):
            self.ledger.set_state(pending["event_id"], wire.REFUSED)
            await self._status(pending["room_id"], pending["event_id"], wire.REFUSED, "channel has ended")
        await self._publish()

    # ── sending ──────────────────────────────────────────────────────────────────────────────────

    async def send(self, to: str, text: str, *, conversation: Optional[str] = None,
                   channel: Optional[str] = None, arrive: str = wire.WAKE, hold_until: Optional[int] = None,
                   expires: Optional[int] = None, answers: Optional[str] = None, kind: str = wire.MESSAGE,
                   description: str = "", **more: Any) -> Receipt:
        """Leave a message. Comes back as soon as the desk has it, and says only that.

        ``conversation`` is where the sender is; sending from one that isn't listed lists it, so the
        answer comes back to it. ``answers`` is the ref of an arrival being answered: the message
        then goes back down the same line. Every attempt is recorded, including the ones that fail.
        """
        msg_id = wire.new_id()
        peer = self._resolve(to)
        self.ledger.log_attempt(msg_id, kind, peer, channel, None, expires)

        def fail(state: str, reason: str) -> Receipt:
            self.ledger.update_attempt(msg_id, state=state, reason=reason)
            return Receipt(id=msg_id, state=state, reason=reason)

        if arrive not in (wire.WAKE, wire.WAIT):
            return fail(wire.FAILED, "arrive is 'wake' or 'wait'")
        try:
            sender_channel = (await self.list_channel(conversation, description)) if conversation else wire.DEFAULT_CHANNEL
            self.ledger.update_attempt(msg_id, from_channel=sender_channel)
            room: Optional[str] = None
            if answers:
                answered = self.ledger.inbox_by_msg(answers)
                if answered is None:
                    return fail(wire.FAILED, f"nothing arrived here with ref {answers!r}")
                arrival = json.loads(answered["arrival"])
                room, answers = answered["room_id"], answered["event_id"]
                peer, channel = arrival["sender"], arrival.get("from_channel")
                self.ledger.update_attempt(msg_id, to_identity=peer, to_channel=channel)
            else:
                listing = await self._listing(peer, fresh=True)
                if listing is None:
                    return fail(wire.REFUSED, f"nobody listed as {to!r}")
                channel = channel or wire.DEFAULT_CHANNEL
                if channel not in listing.channels:
                    return fail(wire.REFUSED, "channel has ended or was never listed")
                self.ledger.update_attempt(msg_id, to_channel=channel)
                if channel != wire.DEFAULT_CHANNEL:
                    line = self.ledger.find_line(peer, sender_channel, channel)
                    room = line["room_id"] if line else None
                if room is None:
                    room = await self._open_line(peer, listing, sender_channel, channel)
            delay = hold_until - now_ms() if hold_until else None
            if delay is not None and delay <= 0:
                delay = None
            content = wire.message_content(
                text, kind=kind, to=None if answers and not channel else channel, sender_channel=sender_channel,
                arrive=arrive, msg_id=msg_id, answers=answers, expires=expires,
                due=hold_until if delay else None, seen=self.ledger.last_taken_in(room) or "", **more)
            sent = await self.matrix.send(room, "m.room.message", msg_id, content, delay_ms=delay)
        except DeskError as exc:
            return fail(wire.FAILED, str(exc))
        except (MatrixError, httpx.HTTPError) as exc:
            return fail(wire.FAILED, f"the desk did not take it: {exc}")
        if "event_id" in sent:
            self.ledger.note_event(room, sent["event_id"], True, now_ms())
        self.ledger.update_attempt(msg_id, room_id=room, event_id=sent.get("event_id"), delay_id=sent.get("delay_id"),
                                   state=wire.HELD if delay else wire.ACCEPTED, reason=None,
                                   held_until=hold_until if delay else None)
        return Receipt(id=msg_id, state=wire.HELD if delay else wire.ACCEPTED, held_until=hold_until if delay else None)

    async def say(self, line: str, text: str, *, arrive: str = wire.WAKE) -> Receipt:
        """Speak down a line this identity is already on: how a conversation that a message
        started answers whoever started it, with no tool call."""
        row = self.ledger.line(line)
        msg_id = wire.new_id()
        if row is None:
            self.ledger.log_attempt(msg_id, wire.MESSAGE, "", None, None, None)
            self.ledger.update_attempt(msg_id, reason="no such line")
            return Receipt(id=msg_id, state=wire.FAILED, reason="no such line")
        self.ledger.log_attempt(msg_id, wire.MESSAGE, row["peer"], row["peer_channel"], row["my_channel"], None)
        try:
            sent = await self.matrix.send(line, "m.room.message", msg_id, wire.message_content(
                text, to=row["peer_channel"], sender_channel=row["my_channel"], arrive=arrive, msg_id=msg_id,
                seen=self.ledger.last_taken_in(line) or ""))
        except (MatrixError, httpx.HTTPError) as exc:
            reason = f"the desk did not take it: {exc}"
            self.ledger.update_attempt(msg_id, reason=reason)
            return Receipt(id=msg_id, state=wire.FAILED, reason=reason)
        self.ledger.note_event(line, sent["event_id"], True, now_ms())
        self.ledger.update_attempt(msg_id, room_id=line, event_id=sent["event_id"], state=wire.ACCEPTED, reason=None)
        return Receipt(id=msg_id, state=wire.ACCEPTED)

    def rename_conversation(self, old: str, new: str) -> bool:
        """The host now knows the conversation by another id (it was started before it had one)."""
        row = self.ledger.channel_of(old)
        if row is None or self.ledger.channel_of(new) is not None:
            return False
        self.ledger._run("UPDATE channels SET conversation=? WHERE handle=?", new, row["handle"])
        return True

    async def _open_line(self, peer: str, listing: Listing, my_channel: str, peer_channel: str,
                         agreement_for: Optional[str] = None) -> str:
        """A line is a room between two conversations. The person answerable for this agent is
        invited so they can watch; the peer's host invites theirs."""
        invite = [] if peer == self.me else [peer]
        watcher = self.profile.get("answerable")
        if watcher and watcher not in (peer, self.me):
            invite.append(watcher)
        room = await self.matrix.create_room(
            preset="private_chat", invite=invite, name=f"{self.profile.get('name')} ↔ {listing.name}")
        self.ledger.add_line(room, peer, my_channel, None if peer_channel == wire.DEFAULT_CHANNEL else peer_channel,
                             agreement_for)
        return room

    async def trace(self, msg_id: str) -> Trace:
        """What became of a message this identity sent."""
        row = self.ledger.attempt(msg_id)
        if row is None:
            raise DeskError(f"no record of a message {msg_id!r}")
        if row["state"] in (wire.FAILED, wire.REFUSED, wire.WITHDRAWN):
            return Trace(id=msg_id, state=row["state"], reason=row["reason"])
        try:
            if row["event_id"] is None:
                if any(d["delay_id"] == row["delay_id"] for d in await self.matrix.delayed()):
                    return Trace(id=msg_id, state=wire.HELD, held_until=row["held_until"])
                return Trace(id=msg_id, state=wire.ACCEPTED, held_until=row["held_until"])
            # Only the receiver says what became of it: the sender and anyone watching the line can
            # write a status event too, and theirs is not the receiver taking it in.
            statuses = [s for s in await self.matrix.references(row["room_id"], row["event_id"], wire.EV_STATUS)
                        if s.get("sender") == row["to_identity"]]
        except (MatrixError, httpx.HTTPError) as exc:
            raise DeskError(f"the desk could not be asked: {exc}") from exc
        if statuses:
            last = statuses[-1]
            return Trace(id=msg_id, state=last["content"].get("state", wire.ACCEPTED),
                         reason=last["content"].get("reason"), at=last["origin_server_ts"])
        if row["read_at"]:
            return Trace(id=msg_id, state=wire.TAKEN_IN, at=row["read_at"])
        if row["expires"] and now_ms() > row["expires"]:
            return Trace(id=msg_id, state=wire.EXPIRED, at=row["expires"])
        return Trace(id=msg_id, state=wire.ACCEPTED)

    async def take_back(self, msg_id: str) -> Trace:
        """Withdraw a held message before it arrives, or a request before the doing starts."""
        row = self.ledger.attempt(msg_id)
        if row is None:
            raise DeskError(f"no record of a message {msg_id!r}")
        if row["event_id"] is None and row["delay_id"]:
            try:
                await self.matrix.cancel_delayed(row["delay_id"])
            except MatrixError as exc:
                raise DeskError("it has already arrived, so it can't be taken back") from exc
            self.ledger.update_attempt(msg_id, state=wire.WITHDRAWN, reason="taken back by its sender")
            return await self.trace(msg_id)
        if row["kind"] == wire.REQUEST and row["event_id"]:
            await self.matrix.send(row["room_id"], "m.room.message", f"wd-{msg_id}", wire.message_content(
                "Withdrawn.", kind=wire.WITHDRAW, to=row["to_channel"], sender_channel=row["from_channel"],
                arrive=wire.WAIT, answers=row["event_id"]))
            return await self.trace(msg_id)
        raise DeskError("it has already arrived, so it can't be taken back")

    def attempts(self, limit: int = 50) -> list[dict]:
        """The record of what this identity tried to send, newest first."""
        return [dict(row) for row in self.ledger.attempts(limit)]

    # ── receiving ────────────────────────────────────────────────────────────────────────────────

    async def run(self, host: Optional[Host] = None, *, poll_ms: int = 10_000) -> None:
        """Stay at the desk: bring in what arrives until ``close``."""
        if host is not None:
            self.host = host
        await self._recover()
        while not self._stop.is_set():
            try:
                await self.pump(timeout_ms=poll_ms)
            except (MatrixError, httpx.HTTPError) as exc:
                logger.warning("the desk can't be reached (%s); trying again", exc)
                await asyncio.sleep(2)

    async def pump(self, *, timeout_ms: int = 0) -> None:
        """One look at the desk: absorb what is new, then act on what has come due."""
        key = f"since:{self.seat}"
        data = await self.matrix.sync(self.ledger.get(key) or self.ledger.get("since"), timeout_ms)
        for room_id, room in (data.get("rooms", {}).get("join") or {}).items():
            for event in room.get("timeline", {}).get("events", []):
                if event.get("type") == "m.room.message":
                    await self._absorb(room_id, event)
            for event in room.get("ephemeral", {}).get("events", []):
                if event.get("type") == "m.receipt":
                    self._note_receipts(room_id, event)
        self.ledger.put(key, data["next_batch"])
        self.ledger.put("since", data["next_batch"])
        await self._tick()

    def _note_receipts(self, room_id: str, event: dict) -> None:
        """A person's chat client says what they have read; that is 'taken in' for a person."""
        line = self.ledger.line(room_id)
        if line is None:
            return
        for event_id, kinds in (event.get("content") or {}).items():
            reader = (kinds.get("m.read") or {}).get(line["peer"])
            if reader is not None:
                self.ledger.mark_read(room_id, event_id, int(reader.get("ts") or now_ms()))

    async def _absorb(self, room_id: str, event: dict) -> None:
        block = wire.parse_block(event)
        sender, event_id = event["sender"], event["event_id"]
        mine = sender == self.me
        seq = self.ledger.note_event(room_id, event_id, mine, event["origin_server_ts"])
        line = self.ledger.line(room_id)
        if mine:
            attempt = self.ledger.attempt(block["id"])
            if attempt is not None and attempt["event_id"] is None:   # a held message has now been sent
                self.ledger.update_attempt(block["id"], event_id=event_id, state=wire.ACCEPTED)
            if line is None or line["peer"] != self.me:
                return
        if line is None:
            self.ledger.add_line(room_id, sender, None, block.get("from"))
            line = self.ledger.line(room_id)
            watcher = self.profile.get("answerable")
            if watcher and watcher not in (sender, self.me):
                try:
                    await self.matrix.invite(room_id, watcher)
                except MatrixError:
                    pass  # already there
        if sender != line["peer"]:
            return  # someone watching the line spoke; it is not addressed to anyone
        if line["agreement_for"]:
            await self._agreement_answer(line, event, block)
            return
        if not self.ledger.claim(event_id, seq, room_id, self.seat):
            return
        await self._route(room_id, line, event, block)

    async def _route(self, room_id: str, line: Any, event: dict, block: dict) -> None:
        event_id = event["event_id"]
        if block.get("from") and block["from"] != line["peer_channel"]:
            self.ledger.bind_line(room_id, peer_channel=block["from"])
        arrival = await self._arrival(room_id, event, block, line)
        if arrival.expires and now_ms() > arrival.expires:
            self.ledger.file(event_id, None, wire.EXPIRED, asdict(arrival))
            await self._status(room_id, event_id, wire.EXPIRED)
            return
        if arrival.kind == wire.WITHDRAW:
            self.ledger.file(event_id, None, wire.TAKEN_IN, asdict(arrival))
            await self._withdrawn(arrival)
            return
        if arrival.kind == wire.REQUEST and not await self._accept_request(arrival):
            self.ledger.file(event_id, None, wire.TAKEN_IN, asdict(arrival))
            return
        target = arrival.to_channel
        if not block.get("to") and target != wire.DEFAULT_CHANNEL:
            bound = self.ledger.channel(target)
            if bound is None or bound["ended"]:
                # Addressed to "whatever this line reaches", and that conversation has ended:
                # a fresh one starts, as for any message to the default channel.
                target = arrival.to_channel = wire.DEFAULT_CHANNEL
        if target == wire.DEFAULT_CHANNEL:
            self.ledger.file(event_id, None, "waiting", asdict(arrival))
            await self._start_fresh(event_id, arrival)
            return
        channel = self.ledger.channel(target)
        if channel is None or channel["ended"]:
            self.ledger.file(event_id, None, wire.REFUSED, asdict(arrival))
            await self._status(room_id, event_id, wire.REFUSED, "channel has ended")
            return
        if channel["seat"] != self.seat:
            self.ledger.release(event_id)   # another seat runs that conversation and will take it
            return
        if line["my_channel"] is None:
            self.ledger.bind_line(room_id, my_channel=target)   # answers from that conversation use this line
        await self._deliver(event_id, arrival, channel)

    async def _start_fresh(self, event_id: str, arrival: Arrival) -> bool:
        """Start a conversation for a message to the default channel. When this host can't, the
        message waits and is never reported as arrived."""
        try:
            conversation = await self.host.start(arrival)
        except Exception:
            logger.exception("the host failed to start a conversation; the message waits")
            conversation = None
        if conversation is None:
            return False
        return await self.adopt(event_id, conversation)

    async def adopt(self, ref: str, conversation: str, description: str = "") -> bool:
        """Bring a message that is waiting on the default channel into ``conversation``."""
        row = self.ledger.inbox_row(ref)
        if row is None or row["state"] != "waiting":
            return False
        arrival = Arrival(**json.loads(row["arrival"]))
        handle = await self.list_channel(conversation, description)
        self.ledger.bind_line(arrival.line, my_channel=handle)
        arrival.to_channel = handle
        await self._deliver(ref, arrival, self.ledger.channel(handle))
        return True

    def waiting(self) -> list[Arrival]:
        """Messages to the default channel that nothing has started a conversation for yet."""
        rows = self.ledger._all("SELECT arrival FROM inbox WHERE state='waiting' ORDER BY seq")
        return [Arrival(**json.loads(row["arrival"])) for row in rows]

    async def _deliver(self, event_id: str, arrival: Arrival, channel: Any) -> None:
        self.ledger.file(event_id, channel["handle"], wire.ARRIVED, asdict(arrival))
        await self._status(arrival.line, event_id, wire.ARRIVED)
        if arrival.arrive == wire.WAKE:
            await self._wake(channel["conversation"])

    async def _wake(self, conversation: str) -> None:
        try:
            await self.host.wake(conversation)
        except Exception:
            logger.exception("the host failed to wake %s; the message stays pending", conversation)

    async def _arrival(self, room_id: str, event: dict, block: dict, line: Any) -> Arrival:
        sender = event["sender"]
        try:
            listing = await self._listing(sender)
        except (MatrixError, httpx.HTTPError):
            listing = None
        sent_at = int(event["origin_server_ts"])
        late = max(0, sent_at - int(block["due"])) if block.get("due") else 0
        arrival = Arrival(
            id=str(block["id"]), ref=event["event_id"], line=room_id, kind=str(block["kind"]), sender=sender,
            sender_name=listing.name if listing else sender, sender_kind=listing.kind if listing else "unknown",
            from_channel=block.get("from"), to_channel=str(block.get("to") or line["my_channel"] or wire.DEFAULT_CHANNEL),
            text=str(event["content"].get("body") or ""), arrive=block["arrive"], sent_at=sent_at,
            answers=block.get("answers"), late_by_ms=late if late > LATE_MS else 0,
            crossed=self.ledger.mine_after(room_id, block.get("seen") or None)
            if "seen" in block and sender != self.me else 0,
            expires=block.get("expires"))
        if arrival.kind in (wire.REQUEST, wire.AGREEMENT) and block.get("offer"):
            arrival.request = {"offer": block["offer"], "args": block.get("args") or {},
                               "asker": block.get("asker") or sender, "ref": block.get("request") or event["event_id"]}
        if arrival.kind == wire.OUTCOME:
            arrival.outcome = {key: block.get(key) for key in ("result", "detail", "asked", "agreed", "offer")}
        return arrival

    async def _status(self, room_id: str, event_id: str, state: str, reason: Optional[str] = None) -> None:
        content = {"state": state, "m.relates_to": {"rel_type": "m.reference", "event_id": event_id}}
        if reason:
            content["reason"] = reason
        try:
            await self.matrix.send(room_id, wire.EV_STATUS, f"st-{state}-{event_id}", content)
        except (MatrixError, httpx.HTTPError) as exc:
            logger.warning("could not record %s for %s: %s", state, event_id, exc)

    # ── the moments a host provides ──────────────────────────────────────────────────────────────

    async def take(self, conversation: str, *, mark: bool = True) -> list[Arrival]:
        """What is waiting for this conversation, in the line's order. Call when a turn begins.
        Nothing here counts as taken in until ``commit``. ``mark=False`` only looks: for a host
        that cannot tell, at the time, whether what it showed was really seen."""
        channel = self.ledger.channel_of(conversation)
        if channel is None:
            return []
        arrivals = []
        for row in self.ledger.pending(channel["handle"]):
            arrival = Arrival(**json.loads(row["arrival"]))
            if arrival.expires and now_ms() > arrival.expires:
                self.ledger.set_state(row["event_id"], wire.EXPIRED)
                await self._status(row["room_id"], row["event_id"], wire.EXPIRED)
                continue
            waited = now_ms() - arrival.sent_at
            if arrival.arrive == wire.WAKE and waited > LATE_MS:
                arrival.late_by_ms = max(arrival.late_by_ms, waited)
            if mark:
                self.ledger.set_state(row["event_id"], "shown")
            arrivals.append(arrival)
        return arrivals

    def mark_shown(self, refs: list[str]) -> None:
        for ref in refs:
            self.ledger.set_state(ref, "shown")

    async def commit(self, conversation: str, *, also: Optional[list[str]] = None) -> None:
        """The turn that was shown these messages finished: they are taken in, and the place moves.
        ``also`` names pending messages the host has since learned were seen."""
        channel = self.ledger.channel_of(conversation)
        if channel is None:
            return
        self.mark_shown([row["event_id"] for row in self.ledger.pending(channel["handle"])
                         if row["event_id"] in (also or [])])
        rows = self.ledger.shown(channel["handle"])
        for row in rows:
            self.ledger.set_state(row["event_id"], wire.TAKEN_IN)
            await self._status(row["room_id"], row["event_id"], wire.TAKEN_IN)
        for room_id, event_id in {row["room_id"]: row["event_id"] for row in rows}.items():
            try:
                await self.matrix.read_receipt(room_id, event_id)
            except (MatrixError, httpx.HTTPError):
                pass

    async def roll_back(self, conversation: str, ref: str) -> None:
        """The conversation was rolled back to before it took ``ref`` in: its place goes back too."""
        channel = self.ledger.channel_of(conversation)
        if channel is None:
            return
        for row in self.ledger.roll_back(channel["handle"], ref):
            await self._status(row["room_id"], row["event_id"], wire.ARRIVED, "conversation rolled back")

    async def _tick(self) -> None:
        for row in self.ledger._all("SELECT event_id, arrival FROM inbox WHERE state='waiting' ORDER BY seq"):
            arrival = Arrival(**json.loads(row["arrival"]))
            if arrival.expires and now_ms() > arrival.expires:
                self.ledger.set_state(row["event_id"], wire.EXPIRED)
                await self._status(arrival.line, row["event_id"], wire.EXPIRED)
            else:
                await self._start_fresh(row["event_id"], arrival)
        await self._expire_requests()
        await self._resend_outcomes()

    async def _recover(self) -> None:
        """After a restart: finish what was in flight without doing anything twice, and wake the
        conversations that still have waking messages they have not seen."""
        await self._recover_requests()
        for row in self.ledger.claimed(self.seat):
            if self.ledger.request(row["event_id"]) is not None:
                self.ledger.set_state(row["event_id"], wire.TAKEN_IN)   # a request: its own record carries it on
                continue
            event = await self.matrix.event(row["room_id"], row["event_id"])
            line = self.ledger.line(row["room_id"])
            if event is not None and line is not None:
                await self._route(row["room_id"], line, event, wire.parse_block(event))
        woken = set()
        for row in self.ledger.waiting_wakes(self.seat):
            arrival = json.loads(row["arrival"])
            channel = self.ledger.channel(row["channel"])
            if arrival["arrive"] == wire.WAKE and channel and channel["conversation"] not in woken:
                woken.add(channel["conversation"])
                await self._wake(channel["conversation"])
