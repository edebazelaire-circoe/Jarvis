"""Deterministic `EmbeddingProvider` for tests and CI (memory handoff, Slice 03).

A hashed bag of concepts: each word (folded, plural stripped) is mapped through
an optional `concepts` table (so "voiture", "car" and "auto" share a concept,
as a multilingual embedder would place them) and hashed with blake2b to a
signed bucket. Same text, same vector, on every machine and run: no clock, no
randomness, no network.

Failure modes for the tests: `delay` (seconds, slow provider), `fail` (an
exception instance raised by `embed`), `calls` (every batch seen, to assert
what was or was not sent).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import hashlib
import re
import unicodedata

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
#: Function words carry no meaning for the fake (a real model discounts them too).
_STOP = frozenset(
    "le la les l un une des du de d et ou en au aux a est sont dans sur pour par que qui ce cette il elle on je tu "
    "mon ma mes ton ta son sa ses the an of and or in on at to for is are was be it its my your this that with from "
    "as by do does what how where when who which me i you we".split()
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith(("s", "x")) else word


class FakeEmbedder:
    def __init__(
        self,
        *,
        dim: int = 128,
        model_id: str = "fake-embedder-v1",
        concepts: Mapping[str, str] | None = None,
        delay: float = 0.0,
        fail: BaseException | None = None,
    ) -> None:
        self._dim = dim
        self._model_id = model_id
        self._concepts = {_stem(_fold(word)): concept for word, concept in (concepts or {}).items()}
        self.delay = delay
        self.fail = fail
        self.calls: list[list[str]] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    @model_id.setter
    def model_id(self, value: str) -> None:
        self._model_id = value

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def texts_seen(self) -> list[str]:
        return [text for batch in self.calls for text in batch]

    def vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for word in _WORD.findall(_fold(text)):
            if word in _STOP:
                continue
            stem = _stem(word)
            digest = hashlib.blake2b(self._concepts.get(stem, stem).encode("utf-8"), digest_size=8).digest()
            number = int.from_bytes(digest, "big")
            vector[number % self._dim] += 1.0 if (number >> 40) & 1 else -1.0
        return vector

    async def embed(self, texts: Sequence[str], timeout: float) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return [self.vector(text) for text in texts]
