"""In-process fake of the Tencent MemoryCore v3 sidecar (memory handoff, Slice 06).

An aiohttp server on a loopback port that speaks the part of the v3 API the
adapter uses (`/v3/conversation/add|search|delete`, envelope `{code, message,
data}`), pinned in `docs/memory-tencent.md`. It is a double of the DOCUMENTED
shape, not a proof of the real one (that is `tests/integration/test_tencent_live.py`).

Modes (set `fake.mode`, switch at any time):

- `normal`: answers like the documentation says, isolating by `team_id`/`user_id`/`agent_id`;
- `slow`: sleeps `delay` seconds before answering;
- `error500`: HTTP 500;
- `malformed`: HTTP 200 with a body that is not JSON; `wrong_shape` an envelope without `data.messages`;
- `refuse`: envelope with `code` 403 (isolation refused);
- `wrong_identity`: search ignores the identity trio and returns every stored message (a leaking sidecar);
- `huge`: an answer larger than any sane bound; `flood`: 5 000 hits;
- `ghosts`: search also returns hits that name no canonical note (no marker, unknown ids, hostile ids).

`stop()` closes the port: the next call is a refused connection (sidecar down).
Every request is kept in `requests` (path, body, `Authorization` header).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import re
from typing import Any

from aiohttp import web

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(slots=True)
class Request:
    path: str
    body: dict[str, Any]
    authorization: str


@dataclass(slots=True)
class FakeTencentSidecar:
    token: str = ""
    mode: str = "normal"
    delay: float = 0.0
    requests: list[Request] = field(default_factory=list)
    #: `(team_id, user_id, agent_id)` -> {message id: content}
    store: dict[tuple[str, str, str], dict[str, str]] = field(default_factory=dict)
    _runner: web.AppRunner | None = None
    _counter: int = 0
    url: str = ""

    async def start(self) -> str:
        app = web.Application()
        app.router.add_post("/v3/conversation/add", self._add)
        app.router.add_post("/v3/conversation/search", self._search)
        app.router.add_post("/v3/conversation/delete", self._delete)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = self._runner.addresses[0][1]
        self.url = f"http://127.0.0.1:{port}"
        return self.url

    async def stop(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None:
            await runner.cleanup()

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _envelope(data: dict[str, Any] | None = None, code: int = 0) -> web.Response:
        return web.json_response({"code": code, "message": "ok" if code == 0 else "refused", "request_id": "r", "data": data or {}})

    async def _gate(self, request: web.Request) -> tuple[dict[str, Any], web.Response | None]:
        body = await request.json()
        self.requests.append(Request(request.path, body, request.headers.get("Authorization", "")))
        if self.token and request.headers.get("Authorization") != f"Bearer {self.token}":
            return body, web.json_response({"code": 401, "message": "auth"}, status=401)
        if self.mode == "slow":
            await asyncio.sleep(self.delay)
        if self.mode == "error500":
            return body, web.Response(status=500, text="boom")
        if self.mode == "malformed":
            return body, web.Response(text="<<not json>>", content_type="application/json")
        if self.mode == "refuse":
            return body, self._envelope(code=403)
        return body, None

    @staticmethod
    def _bucket(body: dict[str, Any]) -> tuple[str, str, str]:
        return (str(body.get("team_id", "default")), str(body.get("user_id", "default")), str(body.get("agent_id", "default")))

    # ------------------------------------------------------------ endpoints
    async def _add(self, request: web.Request) -> web.Response:
        body, early = await self._gate(request)
        if early is not None:
            return early
        bucket = self.store.setdefault(self._bucket(body), {})
        ids = []
        for message in body["messages"]:
            self._counter += 1
            message_id = f"msg_{self._counter}"
            bucket[message_id] = message["content"]
            ids.append(message_id)
        return self._envelope({"accepted_ids": ids, "accepted_versions": ["v1"] * len(ids), "total_count": len(ids)})

    async def _delete(self, request: web.Request) -> web.Response:
        body, early = await self._gate(request)
        if early is not None:
            return early
        bucket = self.store.get(self._bucket(body), {})
        deleted = sum(1 for message_id in body["ids"] if bucket.pop(message_id, None) is not None)
        return self._envelope({"deleted_count": deleted})

    async def _search(self, request: web.Request) -> web.Response:
        body, early = await self._gate(request)
        if early is not None:
            return early
        if self.mode == "wrong_shape":
            return self._envelope({"items": []})
        if self.mode == "huge":
            return web.Response(text=json.dumps({"code": 0, "data": {"messages": [], "pad": "x" * 2_000_000}}))
        if self.mode == "flood":
            flood = [{"id": f"m{i}", "content": f"[jarvis:ghost{i}:r1]\nx", "score": 1.0} for i in range(5_000)]
            return self._envelope({"messages": flood})
        buckets = list(self.store.values()) if self.mode == "wrong_identity" else [self.store.get(self._bucket(body), {})]
        words = set(_WORD.findall(str(body["query"]).casefold()))
        scored = []
        for bucket in buckets:
            for message_id, content in bucket.items():
                overlap = len(words & set(_WORD.findall(content.casefold())))
                if overlap:
                    scored.append((overlap, message_id, content))
        scored.sort(key=lambda item: (-item[0], item[1]))
        messages = [
            {"id": message_id, "version": "v1", "role": "user", "content": content, "score": float(score), "timestamp": "2026-10-07T00:00:00Z"}
            for score, message_id, content in scored[: int(body.get("limit", 5))]
        ]
        if self.mode == "ghosts":
            messages = [
                {"id": "g1", "content": "no marker at all", "score": 9.0},
                {"id": "g2", "content": "[jarvis:does-not-exist:r1]\nghost", "score": 8.0},
                {"id": "g3", "content": "[jarvis:../../etc/passwd:r1]\nhostile id", "score": 7.0},
                {"id": "g4", "content": 12345, "score": 6.0},
                "not even a dict",
            ] + messages
        return self._envelope({"messages": messages})
