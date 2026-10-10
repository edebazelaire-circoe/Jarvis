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
import json
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
#: Largest answer read. 64 texts x 3 072 floats of JSON is about 5 MB; anything above is not an embeddings answer.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


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
            body = await asyncio.wait_for(self._post(client, payload, headers, timeout), timeout)
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
        return self._parse(body, len(batch))

    async def _post(self, client: httpx.AsyncClient, payload: dict, headers: dict, timeout: float) -> bytes:
        """The answer body, read as a stream and refused past `MAX_RESPONSE_BYTES`."""

        async with client.stream("POST", self._url, json=payload, headers=headers, timeout=timeout) as response:
            if response.status_code != 200:
                # Status only: the body of an auth error can echo part of the key.
                _LOG.warning("openai embeddings answered HTTP %s", response.status_code)
                raise _unavailable(f"the embedding service answered HTTP {response.status_code}")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                raise _unavailable("the embedding answer is larger than allowed")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise _unavailable("the embedding answer is larger than allowed")
                chunks.append(chunk)
            return b"".join(chunks)

    def _parse(self, raw: bytes, expected: int) -> list[list[float]]:
        try:
            items = json.loads(raw)["data"]
            if not isinstance(items, list) or len(items) != expected:
                raise ValueError("wrong number of embeddings")
            indexes = [item["index"] for item in items]
            # Exactly 0..n-1, each once, and real integers (a bool is an int to Python).
            if any(type(index) is not int for index in indexes) or sorted(indexes) != list(range(expected)):
                raise ValueError("missing, duplicate or invalid index")
            ordered = sorted(items, key=lambda item: item["index"])
            vectors = []
            for item in ordered:
                values = item["embedding"]
                if not isinstance(values, list) or any(type(v) not in (int, float) for v in values):
                    raise ValueError("embedding is not a list of numbers")
                vectors.append([float(v) for v in values])
        except (ValueError, KeyError, TypeError) as exc:
            raise _unavailable("the embedding service answered an unreadable body") from exc
        if any(len(vector) != self._dim for vector in vectors):
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
