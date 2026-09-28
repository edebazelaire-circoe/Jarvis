"""Faux point Messages local : enregistre les CORPS (jamais les en-têtes), rejoue un script d'appels d'outils."""
import json, sys, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]); SCRIPT = json.load(open(sys.argv[2], encoding="utf-8")); LOG = sys.argv[3]


def tool_results(body):
    return sum(1 for m in body.get("messages", []) if isinstance(m.get("content"), list)
               for c in m["content"] if c.get("type") == "tool_result")


def events(blocks, stop):
    msg = {"id": "msg_" + uuid.uuid4().hex[:12], "type": "message", "role": "assistant", "model": "claude-fake",
           "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
    yield "message_start", {"type": "message_start", "message": msg}
    for i, b in enumerate(blocks):
        if b["type"] == "text":
            yield "content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}
            yield "content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}}
        else:
            yield "content_block_start", {"type": "content_block_start", "index": i,
                                          "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}}
            yield "content_block_delta", {"type": "content_block_delta", "index": i,
                                          "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}}
        yield "content_block_stop", {"type": "content_block_stop", "index": i}
    yield "message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 1}}
    yield "message_stop", {"type": "message_stop"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        self._json({"data": []})

    def do_HEAD(self):
        self.send_response(200); self.end_headers()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "body": body}, ensure_ascii=False) + "\n")
        if "count_tokens" in self.path:
            return self._json({"input_tokens": 10})
        if not self.path.startswith("/v1/messages"):
            return self._json({})
        names = [t.get("name", "") for t in body.get("tools") or []]
        main = any(n.startswith("mcp__jarvis") for n in names) or "ToolSearch" in names
        step = tool_results(body)
        if main and step < len(SCRIPT):
            s = SCRIPT[step]
            blocks, stop = [{"type": "tool_use", "id": f"toolu_fake{step:02d}", "name": s["name"], "input": s["input"]}], "tool_use"
        else:
            blocks, stop = [{"type": "text", "text": "fin"}], "end_turn"
        if not body.get("stream"):
            msg = {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-fake", "stop_reason": stop,
                   "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
                   "content": [dict(b) for b in blocks]}
            return self._json(msg)
        self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
        for ev, data in events(blocks, stop):
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode()); self.wfile.flush()


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
