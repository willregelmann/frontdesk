"""The Claude Code plugin as installed: every command its manifests launch exists and runs.

``test_claude_code.py`` drives the server and hooks with ``python -m`` directly, so it cannot see a
manifest that points at the wrong file. This one reads the manifests the way Claude Code does."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "claude-code"


def _commands() -> list[str]:
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    found = [server["command"] for server in manifest["mcpServers"].values()]
    for entries in hooks["hooks"].values():
        found += [hook["command"] for entry in entries for hook in entry["hooks"]]
    assert found, "the manifests launch nothing"
    return found


def _executable(command: str) -> Path:
    return Path(shlex.split(command.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN)))[0])


def test_every_command_the_plugin_launches_exists_and_is_executable():
    for command in _commands():
        path = _executable(command)
        assert path.is_file(), f"{command!r} launches {path}, which does not exist"
        assert os.access(path, os.X_OK), f"{path} is not executable"


def test_the_launcher_runs_the_configured_python():
    launcher = _executable(_commands()[0])
    ran = subprocess.run([str(launcher), "-c", "import sys; print(sys.executable)"],
                         env={"PATH": os.environ["PATH"], "FRONTDESK_PYTHON": sys.executable},
                         capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    assert Path(ran.stdout.strip()).resolve() == Path(sys.executable).resolve()
