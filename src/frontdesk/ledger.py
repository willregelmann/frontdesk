"""What a host must remember that the desk cannot know: which conversation each channel stands
for, each conversation's place, and how far each request has got.

One SQLite file per identity, shared by every process acting as that identity (several Claude Code
sessions, or one Hermes gateway). Claims are single UPDATE/INSERT statements, so two processes never
both take the same message or do the same offer.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from frontdesk.wire import now_ms

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS channels (
    handle TEXT PRIMARY KEY, conversation TEXT UNIQUE, description TEXT NOT NULL DEFAULT '',
    seat TEXT NOT NULL, ended INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS offers (
    name TEXT PRIMARY KEY, description TEXT NOT NULL, needs TEXT NOT NULL, agree TEXT NOT NULL,
    survives_restart INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS lines (
    room_id TEXT PRIMARY KEY, peer TEXT NOT NULL, my_channel TEXT, peer_channel TEXT,
    agreement_for TEXT, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, event_id TEXT UNIQUE NOT NULL,
    mine INTEGER NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS inbox (
    event_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, room_id TEXT NOT NULL, channel TEXT,
    seat TEXT NOT NULL, state TEXT NOT NULL, arrival TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
    msg_id TEXT PRIMARY KEY, kind TEXT NOT NULL, to_identity TEXT NOT NULL, to_channel TEXT,
    from_channel TEXT, room_id TEXT, event_id TEXT, delay_id TEXT, state TEXT NOT NULL, reason TEXT,
    held_until INTEGER, expires INTEGER, read_at INTEGER, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
    ref TEXT PRIMARY KEY, room_id TEXT NOT NULL, offer TEXT NOT NULL, args TEXT NOT NULL,
    asker TEXT NOT NULL, state TEXT NOT NULL, agreed_by TEXT, agreement_room TEXT,
    expires INTEGER NOT NULL, detail TEXT);
"""


class Ledger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def _one(self, sql: str, *args: Any) -> Optional[sqlite3.Row]:
        return self._db.execute(sql, args).fetchone()

    def _all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        return self._db.execute(sql, args).fetchall()

    def _run(self, sql: str, *args: Any) -> int:
        return self._db.execute(sql, args).rowcount

    # -- meta -------------------------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        row = self._one("SELECT value FROM meta WHERE key=?", key)
        return row["value"] if row else None

    def put(self, key: str, value: str) -> None:
        self._run("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  key, value)

    # -- channels and offers ----------------------------------------------------------------------

    def add_channel(self, handle: str, conversation: str, description: str, seat: str) -> None:
        self._run("INSERT INTO channels(handle, conversation, description, seat) VALUES(?, ?, ?, ?)",
                  handle, conversation, description, seat)

    def channel(self, handle: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM channels WHERE handle=?", handle)

    def channel_of(self, conversation: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM channels WHERE conversation=?", conversation)

    def live_channels(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM channels WHERE ended=0 ORDER BY rowid")

    def describe_channel(self, handle: str, description: str) -> None:
        self._run("UPDATE channels SET description=? WHERE handle=?", description, handle)

    def forget_channel(self, handle: str) -> None:
        self._run("UPDATE channels SET conversation=NULL WHERE handle=?", handle)

    def end_channel(self, handle: str) -> None:
        self._run("UPDATE channels SET ended=1 WHERE handle=?", handle)

    def put_offer(self, name: str, description: str, needs: dict, agree: str, survives_restart: bool) -> None:
        self._run("INSERT INTO offers VALUES(?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                  "description=excluded.description, needs=excluded.needs, agree=excluded.agree, "
                  "survives_restart=excluded.survives_restart",
                  name, description, json.dumps(needs), agree, int(survives_restart))

    def drop_offer(self, name: str) -> None:
        self._run("DELETE FROM offers WHERE name=?", name)

    def offer(self, name: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM offers WHERE name=?", name)

    def offers(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM offers ORDER BY name")

    # -- lines ------------------------------------------------------------------------------------

    def add_line(self, room_id: str, peer: str, my_channel: Optional[str], peer_channel: Optional[str],
                 agreement_for: Optional[str] = None) -> None:
        self._run("INSERT OR IGNORE INTO lines VALUES(?, ?, ?, ?, ?, ?)",
                  room_id, peer, my_channel, peer_channel, agreement_for, now_ms())

    def line(self, room_id: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM lines WHERE room_id=?", room_id)

    def find_line(self, peer: str, my_channel: str, peer_channel: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM lines WHERE peer=? AND my_channel=? AND peer_channel=? AND agreement_for IS NULL "
                         "ORDER BY created LIMIT 1", peer, my_channel, peer_channel)

    def bind_line(self, room_id: str, *, my_channel: Optional[str] = None, peer_channel: Optional[str] = None) -> None:
        if my_channel is not None:
            self._run("UPDATE lines SET my_channel=? WHERE room_id=?", my_channel, room_id)
        if peer_channel is not None:
            self._run("UPDATE lines SET peer_channel=? WHERE room_id=?", peer_channel, room_id)

    # -- order within a line ----------------------------------------------------------------------

    def note_event(self, room_id: str, event_id: str, mine: bool, ts: int) -> int:
        self._run("INSERT OR IGNORE INTO events(room_id, event_id, mine, ts) VALUES(?, ?, ?, ?)",
                  room_id, event_id, int(mine), ts)
        return int(self._one("SELECT seq FROM events WHERE event_id=?", event_id)["seq"])

    def mine_after(self, room_id: str, event_id: Optional[str]) -> int:
        """How many of my messages in this line come after ``event_id`` (all of them when it is unknown)."""
        row = self._one("SELECT seq FROM events WHERE event_id=?", event_id) if event_id else None
        after = int(row["seq"]) if row else 0
        return int(self._one("SELECT COUNT(*) AS n FROM events WHERE room_id=? AND mine=1 AND seq>?",
                             room_id, after)["n"])

    def last_taken_in(self, room_id: str) -> Optional[str]:
        row = self._one("SELECT event_id FROM inbox WHERE room_id=? AND state IN ('shown', 'taken_in') "
                        "ORDER BY seq DESC LIMIT 1", room_id)
        return row["event_id"] if row else None

    # -- inbox ------------------------------------------------------------------------------------

    def claim(self, event_id: str, seq: int, room_id: str, seat: str) -> bool:
        """True for exactly one caller per event: the one that now owns handling it."""
        return self._run("INSERT OR IGNORE INTO inbox(event_id, seq, room_id, seat, state, arrival) "
                         "VALUES(?, ?, ?, ?, 'claimed', '{}')", event_id, seq, room_id, seat) == 1

    def claimed(self, seat: str) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM inbox WHERE seat=? AND state='claimed' ORDER BY seq", seat)

    def release(self, event_id: str) -> None:
        self._run("DELETE FROM inbox WHERE event_id=? AND state='claimed'", event_id)

    def seen(self, event_id: str) -> bool:
        return self._one("SELECT 1 FROM inbox WHERE event_id=?", event_id) is not None

    def file(self, event_id: str, channel: Optional[str], state: str, arrival: dict) -> None:
        self._run("UPDATE inbox SET channel=?, state=?, arrival=? WHERE event_id=?",
                  channel, state, json.dumps(arrival), event_id)

    def inbox_row(self, event_id: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM inbox WHERE event_id=?", event_id)

    def inbox_by_msg(self, ref_or_id: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM inbox WHERE event_id=? OR json_extract(arrival, '$.id')=?",
                         ref_or_id, ref_or_id)

    def pending(self, channel: str) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM inbox WHERE channel=? AND state IN ('arrived', 'shown') ORDER BY seq", channel)

    def waiting_wakes(self, seat: str) -> list[sqlite3.Row]:
        return self._all("SELECT i.* FROM inbox i JOIN channels c ON c.handle=i.channel "
                         "WHERE c.seat=? AND i.state='arrived' ORDER BY i.seq", seat)

    def set_state(self, event_id: str, state: str) -> None:
        self._run("UPDATE inbox SET state=? WHERE event_id=?", state, event_id)

    def shown(self, channel: str) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM inbox WHERE channel=? AND state='shown' ORDER BY seq", channel)

    def roll_back(self, channel: str, from_event: str) -> list[sqlite3.Row]:
        row = self._one("SELECT seq FROM inbox WHERE event_id=?", from_event)
        if row is None:
            return []
        rows = self._all("SELECT * FROM inbox WHERE channel=? AND seq>=? AND state IN ('shown', 'taken_in') ORDER BY seq",
                         channel, row["seq"])
        self._run("UPDATE inbox SET state='arrived' WHERE channel=? AND seq>=? AND state IN ('shown', 'taken_in')",
                  channel, row["seq"])
        return rows

    # -- outbox -----------------------------------------------------------------------------------

    def log_attempt(self, msg_id: str, kind: str, to_identity: str, to_channel: Optional[str],
                    from_channel: Optional[str], expires: Optional[int]) -> None:
        self._run("INSERT INTO outbox(msg_id, kind, to_identity, to_channel, from_channel, state, expires, created) "
                  "VALUES(?, ?, ?, ?, ?, 'failed', ?, ?)", msg_id, kind, to_identity, to_channel, from_channel,
                  expires, now_ms())
        self._run("UPDATE outbox SET reason='not sent' WHERE msg_id=?", msg_id)

    def update_attempt(self, msg_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{name}=?" for name in fields)
        self._run(f"UPDATE outbox SET {sets} WHERE msg_id=?", *fields.values(), msg_id)

    def attempt(self, msg_id: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM outbox WHERE msg_id=?", msg_id)

    def attempts(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM outbox ORDER BY created DESC LIMIT ?", limit)

    def mark_read(self, room_id: str, up_to_event: str, at: int) -> None:
        row = self._one("SELECT seq FROM events WHERE event_id=?", up_to_event)
        if row is None:
            return
        self._run("UPDATE outbox SET read_at=? WHERE read_at IS NULL AND room_id=? AND event_id IN "
                  "(SELECT event_id FROM events WHERE room_id=? AND mine=1 AND seq<=?)",
                  at, room_id, room_id, row["seq"])

    # -- requests ---------------------------------------------------------------------------------

    def add_request(self, ref: str, room_id: str, offer: str, args: dict, asker: str, expires: int) -> None:
        self._run("INSERT OR IGNORE INTO requests(ref, room_id, offer, args, asker, state, expires) "
                  "VALUES(?, ?, ?, ?, ?, 'received', ?)", ref, room_id, offer, json.dumps(args), asker, expires)

    def request(self, ref: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM requests WHERE ref=?", ref)

    def request_by_agreement_room(self, room_id: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM requests WHERE agreement_room=? AND state='awaiting'", room_id)

    def move_request(self, ref: str, from_states: tuple[str, ...], to_state: str, **fields: Any) -> bool:
        """Advance a request only if it is still in one of ``from_states``. True for exactly one caller."""
        sets = ", ".join(["state=?", *(f"{name}=?" for name in fields)])
        marks = ", ".join("?" for _ in from_states)
        return self._run(f"UPDATE requests SET {sets} WHERE ref=? AND state IN ({marks})",
                         to_state, *fields.values(), ref, *from_states) == 1

    def requests_in(self, *states: str) -> list[sqlite3.Row]:
        marks = ", ".join("?" for _ in states)
        return self._all(f"SELECT * FROM requests WHERE state IN ({marks})", *states)

    def unsent_outcomes(self, *closed: str) -> list[sqlite3.Row]:
        """Closed requests whose outcome the desk has not taken (no attempt yet, or one without an event)."""
        marks = ", ".join("?" for _ in closed)
        return self._all(f"SELECT r.* FROM requests r LEFT JOIN outbox o ON o.msg_id = 'out-' || r.ref "
                         f"WHERE r.state IN ({marks}) AND o.event_id IS NULL", *closed)
