"""The small part of the Matrix client-server API the desk needs, and nothing else.

The homeserver IS the desk: it verifies senders, orders messages, holds them until a set time and
lets only an identity write its own register entry. This module only carries requests to it.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx

DELAY_PARAM = "org.matrix.msc4140.delay"
_DELAYED = "/unstable/org.matrix.msc4140/delayed_events"


class MatrixError(Exception):
    def __init__(self, status: int, errcode: str, message: str):
        super().__init__(f"{errcode}: {message} (HTTP {status})")
        self.status, self.errcode, self.message = status, errcode, message


def _q(value: str) -> str:
    return quote(value, safe="")


class Matrix:
    def __init__(self, homeserver: str, access_token: Optional[str] = None):
        self.homeserver = homeserver.rstrip("/")
        self.access_token = access_token
        self._http = httpx.AsyncClient(base_url=f"{self.homeserver}/_matrix/client", timeout=60)

    async def close(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, path: str, body: Any = None, *, timeout: Optional[float] = None,
                   **params: Any) -> dict:
        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        kwargs: dict[str, Any] = {"headers": headers, "params": {k: v for k, v in params.items() if v is not None}}
        if body is not None:
            kwargs["json"] = body
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = await self._http.request(method, path, **kwargs)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            raise MatrixError(response.status_code, str(data.get("errcode") or "M_UNKNOWN"),
                              str(data.get("error") or response.text[:200]))
        return data

    # -- who --------------------------------------------------------------------------------------

    async def register(self, username: str, password: str) -> dict:
        return await self.call("POST", "/v3/register", {
            "username": username, "password": password, "auth": {"type": "m.login.dummy"}})

    async def login(self, user_id: str, password: str) -> dict:
        return await self.call("POST", "/v3/login", {
            "type": "m.login.password", "identifier": {"type": "m.id.user", "user": user_id}, "password": password})

    async def change_password(self, user_id: str, old: str, new: str) -> None:
        await self.call("POST", "/v3/account/password", {
            "new_password": new, "logout_devices": True,
            "auth": {"type": "m.login.password", "identifier": {"type": "m.id.user", "user": user_id}, "password": old}})

    async def set_display_name(self, user_id: str, name: str) -> None:
        await self.call("PUT", f"/v3/profile/{_q(user_id)}/displayname", {"displayname": name})

    async def presence(self, user_id: str) -> dict:
        return await self.call("GET", f"/v3/presence/{_q(user_id)}/status")

    # -- rooms ------------------------------------------------------------------------------------

    async def resolve_alias(self, alias: str) -> Optional[str]:
        try:
            return (await self.call("GET", f"/v3/directory/room/{_q(alias)}"))["room_id"]
        except MatrixError as exc:
            if exc.status == 404:
                return None
            raise

    async def create_room(self, **body: Any) -> str:
        return (await self.call("POST", "/v3/createRoom", body))["room_id"]

    async def join(self, room: str) -> str:
        return (await self.call("POST", f"/v3/join/{_q(room)}", {}))["room_id"]

    async def invite(self, room: str, user_id: str) -> None:
        await self.call("POST", f"/v3/rooms/{_q(room)}/invite", {"user_id": user_id})

    async def members(self, room: str) -> list[str]:
        return list((await self.call("GET", f"/v3/rooms/{_q(room)}/joined_members"))["joined"])

    async def state(self, room: str) -> list[dict]:
        return await self.call("GET", f"/v3/rooms/{_q(room)}/state")  # type: ignore[return-value]

    async def get_state(self, room: str, event_type: str, state_key: str = "") -> Optional[dict]:
        try:
            return await self.call("GET", f"/v3/rooms/{_q(room)}/state/{_q(event_type)}/{_q(state_key)}")
        except MatrixError as exc:
            if exc.status == 404:
                return None
            raise

    async def put_state(self, room: str, event_type: str, state_key: str, content: dict) -> str:
        return (await self.call(
            "PUT", f"/v3/rooms/{_q(room)}/state/{_q(event_type)}/{_q(state_key)}", content))["event_id"]

    # -- events -----------------------------------------------------------------------------------

    async def send(self, room: str, event_type: str, txn_id: str, content: dict, *,
                   delay_ms: Optional[int] = None) -> dict:
        """Send an event. With ``delay_ms`` the homeserver holds it and answers ``{"delay_id"}``;
        otherwise ``{"event_id"}``. The same ``txn_id`` never produces a second event."""
        return await self.call(
            "PUT", f"/v3/rooms/{_q(room)}/send/{_q(event_type)}/{_q(txn_id)}", content, **{DELAY_PARAM: delay_ms})

    async def event(self, room: str, event_id: str) -> Optional[dict]:
        try:
            return await self.call("GET", f"/v3/rooms/{_q(room)}/event/{_q(event_id)}")
        except MatrixError as exc:
            if exc.status == 404:
                return None
            raise

    async def references(self, room: str, event_id: str, event_type: str) -> list[dict]:
        data = await self.call(
            "GET", f"/v1/rooms/{_q(room)}/relations/{_q(event_id)}/m.reference/{_q(event_type)}", limit=100)
        return sorted(data.get("chunk", []), key=lambda e: e["origin_server_ts"])

    async def read_receipt(self, room: str, event_id: str) -> None:
        await self.call("POST", f"/v3/rooms/{_q(room)}/receipt/m.read/{_q(event_id)}", {})

    async def delayed(self) -> list[dict]:
        return list((await self.call("GET", _DELAYED)).get("delayed_events", []))

    async def cancel_delayed(self, delay_id: str) -> None:
        await self.call("POST", f"{_DELAYED}/{_q(delay_id)}/cancel", {})

    async def sync(self, since: Optional[str], timeout_ms: int) -> dict:
        """Long-poll for what happened after ``since``. ``timeout`` here is the server's hold time (a
        query parameter), so this bypasses ``call``, whose ``timeout`` is the HTTP client's."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        params = {"timeout": timeout_ms, **({"since": since} if since else {})}
        response = await self._http.get("/v3/sync", headers=headers, params=params, timeout=timeout_ms / 1000 + 30)
        data = response.json()
        if response.status_code >= 400:
            raise MatrixError(response.status_code, str(data.get("errcode") or "M_UNKNOWN"), str(data.get("error")))
        return data
