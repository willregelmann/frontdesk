"""Without a desk the suite fails loudly. It never skips its way to exit code 0."""

import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _nothing_listening() -> str:
    with socket.socket() as sock:          # a port that was free a moment ago, so nothing answers on it
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def test_with_no_desk_the_suite_fails_and_says_why():
    nowhere = _nothing_listening()
    ran = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_namespaces.py"],
        cwd=ROOT, env={**os.environ, "FRONTDESK_TEST_DESK": nowhere}, capture_output=True, text=True, timeout=120)
    out = ran.stdout + ran.stderr

    assert ran.returncode != 0, out
    assert f"no desk at {nowhere}" in out and "desk/up.sh --test" in out
    assert "skipped" not in out and "passed" not in out
