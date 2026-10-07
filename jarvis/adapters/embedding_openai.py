"""Optional remote `EmbeddingProvider`: OpenAI embeddings over httpx (Slice 03).

Off by default (settings `semantic.provider = "none"`). Opt-in only: texts
leave the machine, so which texts it sees is decided one layer up
(`SemanticIndex` never hands it a `private`-scope note unless `allow_private`,
risk R12) and this adapter only ships what it is given.

The key comes from `credentials.secret_for(settings, "openai")` on every call
(a key saved later works without a restart) and never appears in an error,
a log line or a diagnostic. Failures and timeouts raise
`MemoryStoreError(memory_unavailable)`; the caller turns them into a degraded
reason. Nothing here runs at import or at construction: no network until the
first `embed`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
import logging
import math
from typing import Any

import httpx

from jarvis.domain.memory import MemoryErrorCode, MemoryStoreError
from jarvis.runtime.credentials import secret_for

_LOG = logging.getLogger("jarvis")

DEFAULT_MODEL = "text-embedding-3-small"
#: Smaller than the model's native 1 536: the brute-force scan is linear in it,
#: and the 3-series models are trained to be shortened.
DEFAULT_DIM = 512
DEFAULT_BASE_URL = "https://api.openai.com/v1"
#: Texts per HTTP request.
MAX_BATCH = 64


def _unavailable(message: str) -> MemoryStoreError:
    return MemoryStoreError(MemoryErrorCode.UNAVAILABLE, message)


class OpenAIEmbedder:
    """`EmbeddingProvider` for the OpenAI embeddings endpoint."""

    def __init__(
        self,
        api_key: str | Callable[[], str],
        *,
        model: str = DEFAULT_MODEL,
        dim: int = DEFAULT_DIM,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model or dim < 1:
            raise ValueError("model and a positive dim are required")
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._url = base_url.rstrip("/") + "/embeddings"
        self._client = client

    @property
    def model_id(self) -> str:
        return f"openai:{self._model}:{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def _key(self) -> str:
        key = self._api_key() if callable(self._api_key) else self._api_key
        key = (key or "").strip()
        if not key:
            raise _unavailable("no OpenAI API key is configured")
        return key

    async def embed(self, texts: Sequence[str], timeout: float) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            vectors.extend(await self._embed_batch(list(texts[start:start + MAX_BATCH]), timeout))
        return vectors

    async def _embed_batch(self, batch: list[str], timeout: float) -> list[list[float]]:
        payload: dict[str, Any] = {"model": self._model, "input": batch}
        if self._model.startswith("text-embedding-3"):
            payload["dimensions"] = self._dim
        headers = {"Authorization": f"Bearer {self._key()}"}
        client = self._client or httpx.AsyncClient()
        try:
            response = await asyncio.wait_for(
                client.post(self._url, json=payload, headers=headers, timeout=timeout), timeout,
            )
        except asyncio.TimeoutError as exc:
            raise _unavailable("the embedding request timed out") from exc
        except httpx.TimeoutException as exc:
            raise _unavailable("the embedding request timed out") from exc
        except httpx.HTTPError as exc:
            # The class only: an httpx message can carry the URL or a header.
            raise _unavailable(f"the embedding request failed ({type(exc).__name__})") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code != 200:
            # Status only: the body of an auth error can echo part of the key.
            _LOG.warning("openai embeddings answered HTTP %s", response.status_code)
            raise _unavailable(f"the embedding service answered HTTP {response.status_code}")
        return self._parse(response, len(batch))

    def _parse(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            body = response.json()
            items = sorted(body["data"], key=lambda item: item["index"])
            vectors = [[float(value) for value in item["embedding"]] for item in items]
        except (ValueError, KeyError, TypeError) as exc:
            raise _unavailable("the embedding service answered an unreadable body") from exc
        if len(vectors) != expected or any(len(vector) != self._dim for vector in vectors):
            raise _unavailable("the embedding service returned the wrong number or size of vectors")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise _unavailable("the embedding service returned a non-finite value")
        return vectors


def openai_embedder_from_settings(
    settings: Mapping[str, Any] | Callable[[], Mapping[str, Any]], **options: Any,
) -> OpenAIEmbedder:
    """An embedder whose key is read from the credential store (`settings` or a loader of it) at each call."""

    def key() -> str:
        current = settings() if callable(settings) else settings
        return secret_for(dict(current), "openai")

    return OpenAIEmbedder(key, **options)
