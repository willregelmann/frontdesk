"""Front Desk inside Hermes: something is always running, and it can start conversations.

The gateway holds the identity's proof and stays at the desk (``adapter.py``). A message for a
session on any platform wakes that session; a message to the default channel starts a session of its
own, whose replies go back down the line. What arrived is shown at the start of the turn
(``pre_llm_call``), taken in when the turn ends (``post_llm_call``), and a conversation ended with
``/new`` has its channel withdrawn (``on_session_reset``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["register"]

TOOL_PREFIX = "frontdesk_"
STATE_SUBDIR = "frontdesk"
_CALL_TIMEOUT_S = 120

# Desks at which a gateway in this process is attending, keyed by the profile home they belong to.
_ATTENDING: dict[str, tuple[Any, asyncio.AbstractEventLoop, dict]] = {}


def state_dir() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()) / STATE_SUBDIR


def joined() -> bool:
    return (state_dir() / "credentials.json").exists()


def attending() -> Optional[tuple[Any, asyncio.AbstractEventLoop, dict]]:
    return _ATTENDING.get(str(state_dir()))


def _on_gateway(coro_factory, loop: asyncio.AbstractEventLoop) -> Any:
    return asyncio.run_coroutine_threadsafe(coro_factory(), loop).result(timeout=_CALL_TIMEOUT_S)


def _conversation() -> Optional[str]:
    from gateway.session_context import get_session_env
    return get_session_env("HERMES_SESSION_ID") or None


def _tool(name: str):
    def handler(args: dict, **_kw: Any) -> str:
        from frontdesk import Desk, DeskError, tools
        from frontdesk.offers import load_catalog
        conversation = _conversation()
        live = attending()
        try:
            if live is not None:
                desk, loop, catalog = live
                result = _on_gateway(lambda: tools.call(desk, conversation, name, args or {}, catalog), loop)
            else:
                # No gateway here (a CLI session): this conversation can send and ask, and can be
                # answered once a gateway is attending.
                async def once():
                    desk = Desk(state_dir(), seat="cli")
                    try:
                        return await tools.call(desk, conversation, name, args or {}, load_catalog(state_dir()))
                    finally:
                        await desk.close()
                result = asyncio.run(once())
        except DeskError as exc:
            result = {"error": str(exc)}
        except Exception as exc:
            result = {"error": f"the Front Desk could not be reached: {exc}"}
        return json.dumps(result, default=str, ensure_ascii=False)
    return handler


def _show_arrivals(session_id: str = "", platform: str = "", **_kw: Any) -> Optional[dict]:
    """Start of a turn: what is waiting for this conversation is shown, without being asked for."""
    live = attending()
    if live is None or not session_id:
        return None
    from frontdesk import wire
    desk, loop, _catalog = live
    line = ""
    if platform == "frontdesk":
        from gateway.session_context import get_session_env
        line = get_session_env("HERMES_SESSION_CHAT_ID")

    async def take():   # the desk is only ever touched on the gateway's loop
        if line:        # a conversation the desk started before the session had an id
            desk.rename_conversation(f"fd:{line}", session_id)
        return await desk.take(session_id)

    try:
        arrivals = _on_gateway(take, loop)
    except Exception:
        logger.warning("Front Desk: could not show arrivals for %s", session_id, exc_info=True)
        return None
    return {"context": "\n\n".join(wire.render(a) for a in arrivals)} if arrivals else None


def _take_in(session_id: str = "", **_kw: Any) -> None:
    """End of a turn: what it was shown is taken in, and the place moves."""
    live = attending()
    if live is None or not session_id:
        return
    desk, loop, _catalog = live
    try:
        _on_gateway(lambda: desk.commit(session_id), loop)
    except Exception:
        logger.warning("Front Desk: could not record what %s took in", session_id, exc_info=True)


def _conversation_ended(old_session_id: str = "", **_kw: Any) -> None:
    live = attending()
    if live is None or not old_session_id:
        return
    desk, loop, _catalog = live
    try:
        _on_gateway(lambda: desk.end(old_session_id), loop)
    except Exception:
        logger.warning("Front Desk: could not withdraw the channel of %s", old_session_id, exc_info=True)


def _prompt_section(_session: Any = None) -> str:
    if not joined():
        return ""
    from frontdesk import tools
    return tools.instructions(TOOL_PREFIX)


def register(ctx) -> None:
    from frontdesk import tools
    for spec in tools.TOOLS:
        name = TOOL_PREFIX + spec["name"]
        ctx.register_tool(
            name=name, toolset="frontdesk", handler=_tool(spec["name"]), description=spec["description"],
            schema={"name": name, "description": spec["description"], "parameters": spec["input"]},
            emoji="\U0001f6ce", check_fn=joined)
    ctx.register_hook("pre_llm_call", _show_arrivals)
    ctx.register_hook("post_llm_call", _take_in)
    ctx.register_hook("on_session_reset", _conversation_ended)
    ctx.register_system_prompt_section("frontdesk", _prompt_section)
    try:
        from .adapter import FrontDeskAdapter, check_requirements, is_connected, validate_config
        ctx.register_platform(
            name="frontdesk", label="Front Desk", adapter_factory=lambda cfg: FrontDeskAdapter(cfg),
            check_fn=check_requirements, validate_config=validate_config, is_connected=is_connected,
            required_env=[], install_hint="pip install frontdesk", emoji="\U0001f6ce", allow_update_command=False,
            platform_hint=(
                "This conversation was started by a message that reached you through the Front Desk. Your "
                "replies here go back to whoever sent it. If there is nothing to say, reply with exactly [SILENT]."))
    except Exception:
        logger.warning("Front Desk: failed to register the platform adapter", exc_info=True)
