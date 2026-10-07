"""Progression de la parole pour le Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 4).

Contrat : `docs/tool-brain-contracts.md` §10. **Projection en lecture seule**, aucune vérité de parole :

- le **plan** (chaînes de morceaux, statut de chacun) vient de `SpeechScheduler.presentation_snapshot()` ;
- la **preuve d'écoute** (`played_ms`, durée totale) vient de `VoiceSpeechRecord` (journal vocal de Core),
  passée en `ChunkEvidence` ; ce module ne lit ni le planificateur ni Core lui-même ;
- le texte d'un morceau n'est jamais dans le snapshot : l'appelant peut fournir `texts` (texte de la
  `brain.speech.requested`) pour un aperçu d'une ligne, rien d'autre n'est lu.

Granularité : le **morceau** (paragraphe, `semantic_text_spans`) ; dans le morceau joué, le curseur est
**proportionnel** (`played_ms / total_ms`, même estimation que `estimate_heard_text`), seulement quand la durée
totale est connue (génération terminée). Sinon le curseur reste au début du morceau (borne basse, dite par
`cursor_basis`). Pas d'alignement mot à mot, pas d'évènement `speech.*` nouveau : les faits d'écoute restent
`mouth.speech.*` / `mouth.floor.taken` (clé = id de morceau).

Interruption : un morceau `interrupted` rend **obsolètes** les morceaux suivants de sa chaîne qui n'ont pas
été joués (contrat §3.2 : la file est gelée, la parole interrompue ne reprend pas). `obsolete_chunk_ids` est
ce qu'un décideur doit annuler ou remplacer.

`SpeechProgressTracker` garde seulement le plus haut curseur par chaîne : le curseur d'une chaîne est
**monotone** d'une observation à l'autre, sauf redémarrage explicite (chaîne revenue entièrement en attente
après avoir progressé : `restarts` augmente et le curseur repart).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from jarvis.domain.speech_presentation import SpeechCandidateStatus
from jarvis.domain.voice_events import VoiceGenerationStatus
from jarvis.domain.voice_state import VoiceSpeechRecord
from jarvis.runtime.tool_brain_perception import SpeechSection

SPEECH_SCHEMA = "tool_brain.speech/1"
#: Budget de la section dans la perception (8 Kio au total, `MAX_PERCEPTION_BYTES`).
MAX_SPEECH_SECTION_BYTES = 2048
MAX_CHAINS = 3
#: Morceaux à venir détaillés par chaîne ; le reste est compté (`pending`).
MAX_UPCOMING = 3
MAX_OBSOLETE_IDS = 8
MAX_PREVIEW_CHARS = 60

# Phases d'un morceau (vocabulaire stable pour S5-S6), dérivées de `SpeechCandidateStatus`.
PENDING, PLAYING, HEARD, INTERRUPTED, OBSOLETE, UNCONFIRMED = (
    "pending", "playing", "heard", "interrupted", "obsolete", "unconfirmed")
_PHASE_OF = {
    SpeechCandidateStatus.ELIGIBLE: PENDING, SpeechCandidateStatus.SELECTED: PENDING,
    SpeechCandidateStatus.DEFERRED: PENDING, SpeechCandidateStatus.STARTED: PLAYING,
    SpeechCandidateStatus.COMPLETED: HEARD, SpeechCandidateStatus.INTERRUPTED: INTERRUPTED,
    SpeechCandidateStatus.SUPERSEDED: OBSOLETE, SpeechCandidateStatus.EXPIRED: OBSOLETE,
    SpeechCandidateStatus.UNCONFIRMED: UNCONFIRMED,
}
_TERMINAL = frozenset({HEARD, INTERRUPTED, OBSOLETE, UNCONFIRMED})

BASIS_PROPORTIONAL = "proportional"
BASIS_CHUNK_START = "chunk_start"
BASIS_CHUNK_END = "chunk_end"


@dataclass(frozen=True)
class ChunkEvidence:
    """Preuve d'écoute d'un morceau (clé : id de morceau). `total_ms is None` : durée totale inconnue."""

    played_ms: int = 0
    total_ms: int | None = None


def evidence_from_voice_records(records: Iterable[VoiceSpeechRecord]) -> dict[str, ChunkEvidence]:
    """`VoiceSpeechRecord` -> `ChunkEvidence`, clé `correlation.speech_id` (= id de morceau).

    La durée totale n'est dite que si la génération est terminée (même règle que `interrupted_speeches`).
    """

    found: dict[str, ChunkEvidence] = {}
    for record in records:
        speech_id = record.correlation.speech_id
        if speech_id is None:
            continue
        complete = record.generation_status == VoiceGenerationStatus.COMPLETED and record.received_audio_ms > 0
        found[speech_id] = ChunkEvidence(max(0, int(record.played_ms or 0)),
                                         int(record.received_audio_ms) if complete else None)
    return found


def _one_line(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass(frozen=True)
class SpeechProgress:
    """Projection figée d'un instant. `data` est le contenu ; `to_section()` le branche à la perception."""

    data: Mapping[str, Any]

    def serialize(self) -> str:
        return json.dumps(self.data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def to_section(self) -> SpeechSection:
        """Couture S3 : la perception stocke ce contenu tel quel et le compte dans son budget."""

        return SpeechSection("wired", self.data)


def _chain_view(chain_id: str, entries: list[dict[str, Any]], evidence: Mapping[str, ChunkEvidence],
                texts: Mapping[str, str] | None, floor: Mapping[str, Any] | None,
                high_cursor: int) -> tuple[dict[str, Any], list[str]]:
    entries.sort(key=lambda item: item["chunk"]["index"])
    interrupted_at = next((item["chunk"]["index"] for item in entries if item["phase"] == INTERRUPTED), None)
    obsolete: list[str] = []
    for item in entries:
        if interrupted_at is not None and item["phase"] == PENDING and item["chunk"]["index"] > interrupted_at:
            item["phase"], item["reason"] = OBSOLETE, "chain_interrupted"
        if item["phase"] == OBSOLETE:
            obsolete.append(item["id"])
    cursor, basis, playing = 0, BASIS_CHUNK_START, None
    for item in entries:
        start, end = item["chunk"]["span"]["start"], item["chunk"]["span"]["end"]
        if item["phase"] in (HEARD,):
            cursor, basis = max(cursor, end), BASIS_CHUNK_END
        elif item["phase"] in (PLAYING, INTERRUPTED):
            proof = evidence.get(item["id"], ChunkEvidence())
            item["played_ms"], item["total_ms"] = proof.played_ms, proof.total_ms
            if item["phase"] == PLAYING:
                playing = item
            if proof.total_ms and proof.played_ms > 0:
                ratio = min(1.0, proof.played_ms / proof.total_ms)
                cursor, basis = max(cursor, start + int((end - start) * ratio)), BASIS_PROPORTIONAL
            else:
                cursor = max(cursor, start)
    cursor = max(cursor, high_cursor)  # monotone : jamais en arrière dans une chaîne
    counts = {phase: sum(1 for item in entries if item["phase"] == phase)
              for phase in (HEARD, PENDING, OBSOLETE, UNCONFIRMED)}
    upcoming = [item for item in entries if item["phase"] == PENDING][:MAX_UPCOMING]
    cut = [item for item in entries if item["phase"] == INTERRUPTED]
    listed = cut + ([playing] if playing else []) + upcoming
    focus = playing or (upcoming[0] if upcoming else None)
    chunks = []
    for item in listed:
        view: dict[str, Any] = {"id": item["id"], "i": item["chunk"]["index"], "ph": item["phase"],
                                "s": item["chunk"]["span"]["start"], "e": item["chunk"]["span"]["end"]}
        if item["phase"] in (PLAYING, INTERRUPTED):
            view["played_ms"] = item.get("played_ms", 0)
        text = (texts or {}).get(chain_id)
        if text and item is focus:
            span = item["chunk"]["span"]
            preview = _one_line(text[span["start"]:span["end"]], MAX_PREVIEW_CHARS)
            if preview:
                view["preview"] = preview
        chunks.append(view)
    if interrupted_at is not None:
        state = "interrupted"
    elif playing is not None:
        state = "playing"
    elif counts[PENDING]:
        state = "frozen" if floor is not None else "queued"
    else:
        state = "done"
    head = entries[0]
    view = {"chain": chain_id, "corr": head["correlation_id"], "n": head["chunk"]["count"], "state": state,
            "heard": counts[HEARD], "pending": counts[PENDING], "cursor": cursor, "basis": basis,
            "chunks": chunks}
    if counts[OBSOLETE]:
        view["obsolete"] = counts[OBSOLETE]
    return view, obsolete


class SpeechProgressTracker:
    """Observe le planificateur, rend `SpeechProgress` ; retient le plus haut curseur par chaîne (monotonie)."""

    def __init__(self) -> None:
        self._high: dict[str, int] = {}
        self._restarts: dict[str, int] = {}

    def observe(self, snapshot: Mapping[str, Any], evidence: Mapping[str, ChunkEvidence] | None = None, *,
                texts: Mapping[str, str] | None = None,
                max_bytes: int = MAX_SPEECH_SECTION_BYTES) -> SpeechProgress:
        evidence = evidence or {}
        chains: dict[str, list[dict[str, Any]]] = {}
        for candidate in snapshot.get("candidates", ()):
            chunk_id, chunk = candidate.get("speech_id"), candidate.get("chunk")
            if not chunk_id or not isinstance(chunk, Mapping):
                continue  # candidat de conversation : pas une parole du cerveau
            phase = _PHASE_OF.get(SpeechCandidateStatus(candidate["status"]), PENDING)
            chains.setdefault(chunk["chain_id"], []).append(
                {"id": chunk_id, "phase": phase, "chunk": chunk, "correlation_id": candidate.get("correlation_id")})
        for gone in set(self._high) - set(chains):
            self._high.pop(gone, None)  # chaîne évincée du planificateur : l'état tombe avec elle
            self._restarts.pop(gone, None)
        floor = snapshot.get("floor")
        views, obsolete = [], []
        for chain_id, entries in chains.items():
            high = self._high.get(chain_id, 0)
            if high and all(item["phase"] == PENDING for item in entries):
                high = 0  # redémarrage explicite : la chaîne a tout rejoué depuis le début
                self._restarts[chain_id] = self._restarts.get(chain_id, 0) + 1
            view, gone = _chain_view(chain_id, entries, evidence, texts, floor, high)
            self._high[chain_id] = view["cursor"]
            if self._restarts.get(chain_id):
                view["restarts"] = self._restarts[chain_id]
            views.append(view)
            obsolete.extend(gone)
        order = {"playing": 0, "interrupted": 1, "frozen": 2, "queued": 3, "done": 4}
        views.sort(key=lambda item: (order[item["state"]], item["chain"]))
        data: dict[str, Any] = {"schema": SPEECH_SCHEMA, "chains": views[:MAX_CHAINS],
                                "more_chains": max(0, len(views) - MAX_CHAINS),
                                "floor": dict(floor) if floor else None,
                                "obsolete_chunk_ids": obsolete[:MAX_OBSOLETE_IDS]}
        return SpeechProgress(_fit(data, max_bytes))


def _size(data: Mapping[str, Any]) -> int:
    return len(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _fit(data: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Borne dure : aperçus, puis morceaux à venir, puis chaînes les moins vives, sont retirés. Jamais de dépassement."""

    for step in ("preview", "chunks", "chains"):
        while _size(data) > max_bytes:
            if step == "preview":
                found = [chunk for chain in data["chains"] for chunk in chain["chunks"] if "preview" in chunk]
                if not found:
                    break
                found[-1].pop("preview")
            elif step == "chunks":
                longest = max(data["chains"], key=lambda chain: len(chain["chunks"]), default=None)
                if longest is None or len(longest["chunks"]) <= 1:
                    break
                longest["chunks"].pop()
            else:
                if len(data["chains"]) <= 1:
                    break
                data["chains"].pop()
                data["more_chains"] += 1
    if _size(data) > max_bytes:
        raise ValueError(f"speech progress exceeds {max_bytes} bytes after every reduction")
    return data


__all__ = [
    "BASIS_CHUNK_END", "BASIS_CHUNK_START", "BASIS_PROPORTIONAL", "ChunkEvidence", "HEARD", "INTERRUPTED",
    "MAX_SPEECH_SECTION_BYTES", "OBSOLETE", "PENDING", "PLAYING", "SPEECH_SCHEMA", "SpeechProgress",
    "SpeechProgressTracker", "UNCONFIRMED", "evidence_from_voice_records",
]
