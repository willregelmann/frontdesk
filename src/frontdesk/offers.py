"""What a host can carry out, read from ``offers.json`` beside the identity's credentials.

The file is the host's, not the model's: it fixes what each offer does. An agent can list or
withdraw an offer named here, and whoever asks supplies only what the offer says it needs.

    {"restart-gateway": {"description": "Restart my gateway", "agree": "self",
                         "command": ["hermes", "gateway", "restart"], "survives_restart": true,
                         "listed": true}}
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from frontdesk.desk import Desk
from frontdesk.tools import Catalog

OFFERS_FILE = "offers.json"


def _command_handler(argv: list[str]):
    async def handler(args: dict) -> str:
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await process.communicate(json.dumps(args).encode())
        text = output.decode(errors="replace").strip()[-2000:]
        if process.returncode != 0:
            raise RuntimeError(f"exit {process.returncode}: {text}" if text else f"exit {process.returncode}")
        return text
    return handler


def load_catalog(state_dir: Path | str) -> Catalog:
    path = Path(state_dir) / OFFERS_FILE
    if not path.exists():
        return {}
    catalog: Catalog = {}
    for name, entry in json.loads(path.read_text()).items():
        catalog[name] = {**entry, "handler": _command_handler([str(part) for part in entry["command"]])}
    return catalog


async def attach(desk: Desk, catalog: Catalog) -> None:
    """Give this process the means to do what the identity already lists, and list what the file
    says is listed from the start."""
    for name, entry in catalog.items():
        if desk.ledger.offer(name) is not None or entry.get("listed"):
            await desk.offer(name, entry["description"], entry["handler"], needs=entry.get("needs"),
                             agree=entry.get("agree", "nobody"), survives_restart=bool(entry.get("survives_restart")))
