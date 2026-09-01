from __future__ import annotations

from typing import Any
import httpx

from jarvis.domain.errors import ProviderError


class OpenAIHTTP:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_s: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = client

    async def post_json(self, path: str, payload: dict[str, Any], *, operation: str) -> httpx.Response:
        return await self._request("POST", path, operation=operation, json=payload)

    async def post_multipart(
        self,
        path: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        operation: str,
    ) -> httpx.Response:
        return await self._request("POST", path, operation=operation, data=data, files=files)

    async def _request(self, method: str, path: str, *, operation: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.api_key}"
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            response = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
            if response.status_code >= 400:
                raise ProviderError(
                    "openai",
                    operation,
                    f"OpenAI HTTP {response.status_code}",
                    retryable=response.status_code in {408, 409, 429} or response.status_code >= 500,
                )
            return response
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("openai", operation, "OpenAI timeout", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ProviderError("openai", operation, f"OpenAI network error: {type(exc).__name__}", retryable=True) from exc
        finally:
            if own_client:
                await client.aclose()
