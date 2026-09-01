from __future__ import annotations

from typing import Any
import httpx
from urllib.parse import urlparse

from jarvis.domain.errors import ConfigurationError


class BarehandsBoardClient:
    def __init__(
        self,
        base_url: str,
        session_token: str,
        *,
        timeout_s: float = 2.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ConfigurationError("Barehands board client requires an HTTP loopback URL")
        if not session_token:
            raise ConfigurationError("Barehands board session token cannot be empty")
        self.base_url = base_url.rstrip("/")
        self.session_token = session_token
        self.timeout_s = timeout_s
        self._client = client

    async def present(
        self,
        title: str,
        body: str,
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        cmd: dict[str, Any] = {"a": "present", "title": title, "body": body}
        if x is not None:
            cmd["x"] = float(x)
        if y is not None:
            cmd["y"] = float(y)
        own = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            response = await client.post(
                f"{self.base_url}/cmd",
                json=cmd,
                headers={"X-Jarvis-Token": self.session_token},
            )
            response.raise_for_status()
            return {"presented": True, "status": response.status_code, "title": title}
        finally:
            if own:
                await client.aclose()

    async def health(self) -> bool:
        own = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            response = await client.get(f"{self.base_url}/config")
            return response.status_code == 200
        except httpx.HTTPError:
            return False
        finally:
            if own:
                await client.aclose()
