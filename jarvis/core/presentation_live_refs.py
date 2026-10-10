"""Résolution Core des références vivantes d'une scène Remotion vers un Board (Remotion Slice 09).

Contrat : `docs/presentation-live-refs.md`. Le code d'une scène est **non fiable** (`remotion-isolation.md`) : il n'a ni
disque, ni outil, ni secret. Ce service est donc le seul à lire un Board ; il ne rend que des `ResolvedLiveRef` typés, et
`sandbox_payload` n'en laisse passer que des données (jamais la référence, l'id de Board ni un chemin).

Il ne possède rien : les Boards, la mémoire de Board et les Artifacts gardent leurs propriétaires (`BoardRepository`,
`BoardMemoryStore`, `ArtifactService`, `board_artifact_links`) ; ici, lecture seule et bornes. Une référence qui ne se résout
pas n'est **jamais** une exception pendant l'édition : c'est un état typé que l'écran montre (`LiveRefState`).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Collection, Iterable, Mapping
from typing import Any

from jarvis.domain.artifacts import ArtifactError, ArtifactErrorCode, ArtifactState
from jarvis.domain.board_memory import BoardMemoryError, BoardMemoryErrorCode, BoardMemoryPath
from jarvis.domain.presentation_live_refs import (
    ALLOWED_ARTIFACT_KINDS, BINARY_MIMES, MAX_BINARY_BYTES, MAX_SET_BYTES, MAX_TEXT_BYTES, TEXT_MEMORY_SUFFIXES, TEXT_MIMES,
    LiveRef, LiveRefError, LiveRefErrorCode, LiveRefState, ResolvedLiveRef, binary_signature_ok,
)
from jarvis.ports.v2 import DiagnosticSink

LINKS_READ = 100
CHUNK = 1 << 20
_S = LiveRefState


class LiveRefResolver:
    def __init__(self, *, boards: Any, memory: Any, artifacts: Any, links: Any,
                 diagnostics: DiagnosticSink | None = None) -> None:
        self._boards = boards
        self._memory = memory
        self._artifacts = artifacts
        self._links = links
        self._diagnostics = diagnostics

    async def resolve(self, ref: LiveRef, *, authorised_boards: Collection[str],
                      expected_sha256: str | None = None) -> ResolvedLiveRef:
        """Une référence -> un état typé. Ne lève pas pour une absence, une taille ou un type : ces cas sont des états.
        `expected_sha256` (édition) : le contenu vu la dernière fois ; un autre contenu est rendu `changed` (périmé), avec les
        nouvelles données.

        `authorised_boards` : liste blanche **obligatoire** (refus par défaut) que le code Core appelant dérive des Boards avec
        lesquels l'utilisateur travaille ou qu'il a explicitement accordés. La déclaration d'une scène ne décide jamais quel
        Board est lu : un Board hors liste donne `not_authorised`, sans aucune lecture ni test d'existence."""

        if ref.board_id not in authorised_boards:
            self._trace("core.live_refs.not_authorised", "Référence vivante vers un Board non autorisé", level="warning",
                        data={"name": ref.name, "kind": ref.kind})
            return ResolvedLiveRef(ref, _S.NOT_AUTHORISED, "this Board is not authorised for this presentation")
        try:
            board = await self._boards.get_board(ref.board_id)
            if board is None:
                result = ResolvedLiveRef(ref, _S.BOARD_MISSING, "the Board no longer exists")
            elif ref.kind == "memory":
                result = await self._memory_item(ref)
            else:
                result = await self._artifact_item(ref)
        except Exception as exc:  # noqa: BLE001 - argued: any store failure is reported as a typed state, never swallowed
            self._trace("core.live_refs.unreadable", "Référence vivante illisible", level="warning",
                        data={"name": ref.name, "kind": ref.kind, "error": type(exc).__name__})
            result = ResolvedLiveRef(ref, _S.UNREADABLE, f"the Board could not be read ({type(exc).__name__})")
        if result.state is _S.OK and expected_sha256 is not None and result.sha256 != expected_sha256:
            result = ResolvedLiveRef(ref, _S.CHANGED, "the Board item changed since it was last seen", result.mime,
                                     result.data, result.sha256)
        if not result.usable:
            self._trace("core.live_refs.unresolved", "Référence vivante non résolue", level="warning",
                        data={"name": ref.name, "kind": ref.kind, "state": result.state.value})
        return result

    async def resolve_all(self, refs: Iterable[LiveRef], *, authorised_boards: Collection[str],
                          expected: Mapping[str, str] | None = None) -> dict[str, ResolvedLiveRef]:
        """Toutes, dans l'ordre ; le total des octets reste borné (`MAX_SET_BYTES`) : au-delà, l'élément est `too_large`."""

        out: dict[str, ResolvedLiveRef] = {}
        total = 0
        for ref in refs:
            item = await self.resolve(ref, authorised_boards=authorised_boards, expected_sha256=(expected or {}).get(ref.name))
            if item.usable:
                assert item.data is not None
                if total + len(item.data) > MAX_SET_BYTES:
                    item = ResolvedLiveRef(ref, _S.TOO_LARGE, f"the set of live items exceeds {MAX_SET_BYTES} bytes")
                else:
                    total += len(item.data)
            out[ref.name] = item
        return out

    @staticmethod
    def require_all_usable(resolved: Mapping[str, ResolvedLiveRef]) -> None:
        """Gel : tout se résout, sinon `live_ref_unresolved` listant chaque référence en cause (aucun paquet partiel)."""

        bad = tuple(item.status() for item in resolved.values() if item.state is not _S.OK)
        if bad:
            code = (LiveRefErrorCode.NOT_AUTHORISED if any(row["state"] == _S.NOT_AUTHORISED.value for row in bad)
                    else LiveRefErrorCode.UNRESOLVED)
            raise LiveRefError(code,
                               f"{len(bad)} live reference(s) cannot be frozen: "
                               + ", ".join(f"{row['name']} ({row['state']})" for row in bad), details=bad)

    # ------------------------------------------------------------ éléments

    async def _memory_item(self, ref: LiveRef) -> ResolvedLiveRef:
        suffix = "." + ref.locator.rsplit(".", 1)[-1].lower() if "." in ref.locator.rsplit("/", 1)[-1] else ""
        if suffix not in TEXT_MEMORY_SUFFIXES:
            return ResolvedLiveRef(ref, _S.NOT_ALLOWED, f"a Board memory file must end in one of {sorted(TEXT_MEMORY_SUFFIXES)}")
        exists = await asyncio.to_thread(self._memory.exists, ref.board_id)
        if not exists:
            return ResolvedLiveRef(ref, _S.MISSING, "the Board has no memory")
        try:
            text = await asyncio.to_thread(self._memory.read, ref.board_id, BoardMemoryPath.parse(ref.locator),
                                           offset=0, max_bytes=MAX_TEXT_BYTES)
        except BoardMemoryError as exc:
            state = {BoardMemoryErrorCode.MEMORY_NOT_FOUND: _S.MISSING, BoardMemoryErrorCode.MEMORY_TOO_LARGE: _S.TOO_LARGE,
                     BoardMemoryErrorCode.MEMORY_NOT_TEXT: _S.NOT_TEXT}.get(exc.code, _S.NOT_ALLOWED)
            return ResolvedLiveRef(ref, state, exc.code.value)
        if not text.eof or text.size > MAX_TEXT_BYTES:
            return ResolvedLiveRef(ref, _S.TOO_LARGE, f"a text item is at most {MAX_TEXT_BYTES} bytes")
        data = text.text.encode("utf-8")
        mime = {".md": "text/markdown", ".json": "application/json", ".csv": "text/csv"}.get(suffix, "text/plain")
        return ResolvedLiveRef(ref, _S.OK, "", mime, data, hashlib.sha256(data).hexdigest())

    async def _artifact_item(self, ref: LiveRef) -> ResolvedLiveRef:
        try:
            artifact = await self._artifacts.get(ref.locator)
        except ArtifactError as exc:
            if exc.code is ArtifactErrorCode.ARTIFACT_NOT_FOUND:
                return ResolvedLiveRef(ref, _S.MISSING, "the artifact no longer exists")
            raise
        if artifact.kind not in ALLOWED_ARTIFACT_KINDS:
            return ResolvedLiveRef(ref, _S.NOT_ALLOWED, f"artifact kind {artifact.kind.value} is not a usable scene item")
        links = await self._links.boards_of_artifact(ref.locator, limit=LINKS_READ + 1)
        if ref.board_id not in {link.board_id for link in links[:LINKS_READ + 1]}:
            return ResolvedLiveRef(ref, _S.NOT_ON_BOARD, "the artifact is not linked to this Board")
        if artifact.state is not ArtifactState.COMPLETE:
            return ResolvedLiveRef(ref, _S.NOT_READY, f"the artifact is {artifact.state.value}")
        mime = (artifact.mime_type or "").split(";")[0].strip().lower()
        if mime not in BINARY_MIMES and mime not in TEXT_MIMES:
            return ResolvedLiveRef(ref, _S.NOT_ALLOWED, f"content type {mime[:40] or 'unknown'!r} is not allowed")
        limit = MAX_BINARY_BYTES if mime in BINARY_MIMES else MAX_TEXT_BYTES
        info = self._artifacts.payload_info(artifact)
        if info is None or info.final_bytes is None:
            return ResolvedLiveRef(ref, _S.MISSING, "the artifact has no payload on disk")
        if info.final_bytes > limit:
            return ResolvedLiveRef(ref, _S.TOO_LARGE, f"{mime} items are at most {limit} bytes")

        def read() -> bytes:
            chunks, offset = [], 0
            while offset <= limit:
                chunk = self._artifacts.read_payload(artifact, offset, min(CHUNK, limit + 1 - offset))
                if not chunk:
                    break
                chunks.append(chunk)
                offset += len(chunk)
            return b"".join(chunks)

        data = await asyncio.to_thread(read)
        if len(data) > limit:
            return ResolvedLiveRef(ref, _S.TOO_LARGE, f"{mime} items are at most {limit} bytes")
        if mime in BINARY_MIMES:
            if not binary_signature_ok(mime, data):
                return ResolvedLiveRef(ref, _S.NOT_ALLOWED, f"the content is not a valid {mime} file")
        else:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                return ResolvedLiveRef(ref, _S.NOT_TEXT, "the artifact is not UTF-8 text")
        return ResolvedLiveRef(ref, _S.OK, "", mime, data, hashlib.sha256(data).hexdigest())

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
