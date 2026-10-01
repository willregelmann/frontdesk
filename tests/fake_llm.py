"""A scripted stand-in for a model behind an OpenAI-compatible endpoint.

It acts the way a model following the Front Desk instructions would: when a turn shows a
``<frontdesk ...>`` arrival it answers it with ``frontdesk_send(answers=ref)``, then finishes the
turn with a short reply. Everything it was sent is kept so a test can see what the host showed it.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_REF = re.compile(r'<frontdesk [^>]*\bref="([^"]+)"')
_SETTLE = re.compile(r'<frontdesk [^>]*\bsettle_with_ref="([^"]+)"')


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


class FakeLLM:
    def __init__(self, answer: str = "pong from hermes", final: str = "Told them."):
        self.answer, self.final = answer, final
        self.requests: list[dict] = []
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

    def _decide(self, body: dict) -> dict:
        messages = body.get("messages") or []
        last = messages[-1] if messages else {}
        tool_names = [t.get("function", {}).get("name") for t in body.get("tools") or []]
        shown = _text(last.get("content")) if last.get("role") == "user" else ""
        refs, to_settle = _REF.findall(shown), _SETTLE.findall(shown)
        if refs:
            tool, arguments = "frontdesk_send", {"text": self.answer, "answers": refs[-1]}
            if to_settle:   # a request waiting on this agent's agreement: agree to it
                tool, arguments = "frontdesk_settle", {"ref": to_settle[-1], "agree": True}
            if tool in tool_names:
                name = tool
            elif "tool_call" in tool_names:
                # Hermes keeps plugin tools behind its tool-search bridge and lists them in the prompt.
                name, arguments = "tool_call", {"calls": [{"name": tool, "arguments": arguments}]}
            else:
                name = ""
            if name:
                return {"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"call_{len(self.requests)}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)}}]}
        return {"role": "assistant", "content": self.final}

    def _handler(fake):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self._json({"object": "list", "data": [{"id": "fake", "object": "model"}]})

            def _json(self, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                fake.requests.append(body)
                message = fake._decide(body)
                base = {"id": f"chatcmpl-{len(fake.requests)}", "created": int(time.time()), "model": body.get("model")}
                usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
                finish = "tool_calls" if message.get("tool_calls") else "stop"
                if not body.get("stream"):
                    self._json({**base, "object": "chat.completion", "usage": usage,
                                "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                delta = dict(message)
                if delta.get("tool_calls"):
                    delta["tool_calls"] = [{**call, "index": i} for i, call in enumerate(delta["tool_calls"])]
                chunks = [
                    {**base, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {**base, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage},
                ]
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
        return Handler
