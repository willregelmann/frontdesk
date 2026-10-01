"""The gateway's seat at the desk, and the surface of conversations the desk starts."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, Dict, Optional

from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent, MessageType

logger = logging.getLogger(__name__)

NUDGE = "[Front Desk] Something arrived for this conversation. It is shown below."
PROVISIONAL = "fd:"   # a conversation the desk started, before its session has an id
HOME = "answerable"   # the platform's home channel: the person answerable for this agent


def check_requirements() -> bool:
    try:
        import frontdesk  # noqa: F401
    except ImportError:
        return False
    return True


def validate_config(config) -> bool:
    from . import joined
    return joined()


def is_connected(config) -> bool:
    return bool((getattr(config, "extra", {}) or {}).get("enabled")) or bool(getattr(config, "enabled", False))


def _restart_catalog_entry() -> dict:
    async def restart(_args: dict) -> str:
        from gateway.restart import is_container_restart_context, is_gateway_supervisor_process
        from gateway.run import _gateway_runner_ref
        runner = _gateway_runner_ref()
        if runner is None or not hasattr(runner, "request_restart"):
            raise RuntimeError("no gateway is running here")
        if getattr(runner, "_restart_requested", False) or getattr(runner, "_draining", False):
            return "a restart was already under way"
        draining = runner._running_agent_count()
        via_service = is_gateway_supervisor_process() or is_container_restart_context()
        runner.request_restart(detached=not via_service, via_service=via_service)
        return f"restarting after {draining} active turn(s) finish"

    return {"description": "Restart this agent's gateway gracefully: turns in progress finish first. Every "
                           "agent this gateway serves restarts.",
            "needs": {"type": "object", "properties": {}}, "agree": "self", "handler": restart,
            "survives_restart": True}


class FrontDeskAdapter(BasePlatformAdapter):
    """Stays at the desk for one profile. Also the ``Host`` the desk calls to wake a conversation
    or start a fresh one."""

    def __init__(self, config, **kwargs):
        super().__init__(config=config, platform=Platform("frontdesk"))
        from gateway.config import HomeChannel
        from . import state_dir
        self._state_dir = state_dir()   # resolved under the owning profile's scope
        if config.home_channel is None:
            # Unprompted deliveries (cron results) go to the person answerable for this agent. Without
            # a home the gateway would ask whoever first writes in to set one.
            config.home_channel = HomeChannel(platform=self.platform, chat_id=HOME, name="The person answerable")
        config.gateway_restart_notification = False
        config.typing_indicator = False
        self.desk: Any = None
        self._attend_task: Optional[asyncio.Task] = None

    @property
    def name(self) -> str:
        return "Front Desk"

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        from frontdesk import Desk, DeskError
        from frontdesk.offers import attach, load_catalog
        from . import _ATTENDING
        try:
            self.desk = Desk(self._state_dir, seat="gateway")
        except DeskError as exc:
            self._set_fatal_error("config_missing", str(exc), retryable=False)
            return False
        self.desk.host = self
        catalog = {"restart-gateway": _restart_catalog_entry(), **load_catalog(self._state_dir)}
        try:
            await attach(self.desk, catalog)
        except DeskError as exc:
            await self.desk.close()
            self._set_fatal_error("connect_failed", str(exc), retryable=True)
            return False
        _ATTENDING[str(self._state_dir)] = (self.desk, asyncio.get_running_loop(), catalog)
        self._attend_task = asyncio.create_task(self.desk.run(self))
        self._mark_connected()
        logger.info("Front Desk: attending as %s", self.desk.me)
        return True

    async def disconnect(self) -> None:
        from . import _ATTENDING
        _ATTENDING.pop(str(self._state_dir), None)
        self._mark_disconnected()
        if self._attend_task is not None:
            self._attend_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._attend_task
        if self.desk is not None:
            with suppress(Exception):
                await self.desk.close()

    # ── what the agent says in a conversation the desk started ───────────────────────────────────

    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None):
        if self.desk is None:
            return SendResult(success=False, error="Not at the desk")
        if chat_id == HOME:
            person = self.desk.profile.get("answerable")
            if not person:
                return SendResult(success=False, error="nobody is answerable for this identity")
            receipt = await self.desk.send(person, content)
        else:
            receipt = await self.desk.say(chat_id, content)
        if receipt.state != "accepted":
            return SendResult(success=False, error=receipt.reason or receipt.state)
        return SendResult(success=True, message_id=receipt.id)

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """The desk has no typing indicator."""

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"name": chat_id, "type": "dm"}

    # ── the two things only a host can do ────────────────────────────────────────────────────────

    async def start(self, arrival) -> Optional[str]:
        """A message to the default channel: a session of its own, on this platform, in its line."""
        return PROVISIONAL + arrival.line

    async def wake(self, conversation: str) -> None:
        """Start a turn in ``conversation``. What arrived is shown by ``pre_llm_call``; the event
        itself only says that something did."""
        from gateway.wake import admit_internal_event
        if conversation.startswith(PROVISIONAL):
            pending = await self.desk.take(conversation, mark=False)
            if not pending:
                return
            first = pending[0]
            source = self.build_source(
                chat_id=first.line, chat_name=f"Front Desk: {first.sender_name}", chat_type="dm",
                user_id=first.sender, user_name=first.sender_name, is_bot=first.sender_kind == "agent")
            await admit_internal_event(self, MessageEvent(
                text=NUDGE, message_type=MessageType.TEXT, source=source, internal=True))
            return
        from gateway.run import _gateway_runner_ref
        runner = _gateway_runner_ref()
        if runner is None:
            return
        entry = next((e for e in runner.session_store.list_sessions() if e.session_id == conversation), None)
        if entry is None or entry.origin is None:
            logger.info("Front Desk: %s is not a conversation this gateway can wake; its messages wait", conversation)
            return
        adapter = self if entry.origin.platform == self.platform else \
            runner._adapters_for_profile(getattr(entry.origin, "profile", None)).get(entry.origin.platform)
        if adapter is None:
            logger.info("Front Desk: no connection to wake %s on; its messages wait", conversation)
            return
        await admit_internal_event(adapter, runner._synthetic_prompt_event(entry.origin, NUDGE, internal=True))
