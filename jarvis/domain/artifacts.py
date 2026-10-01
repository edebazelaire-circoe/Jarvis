"""Contrat pur du registre d'Artifacts (handoff session-context-recording, Slice 04).

Un **Artifact** est une pièce de preuve acquise par Jarvis : enregistrement
audio, segment de transcription, capture d'écran, enregistrement d'écran,
description dérivée... Le registre en porte l'identité, le temps, la source,
l'état d'acquisition, l'association éventuelle à une Session et un Context,
la référence de son fichier (payload) et des métadonnées bornées. Le contenu
lourd reste un fichier sous `<data_root>/artifacts/<artifact_id>/` (D09).
Contrat : `docs/artifacts.md`.

Invariants portés ici :

- l'identité (`artifact_id`, `kind`, `source`, `created_at`, Session,
  Context, `started_at`, `payload_ref`) est fixée à l'acquisition (D07) et ne
  change jamais ;
- `pending` est le seul état ouvert ; `complete`, `partial` et `failed` sont
  terminaux pour les champs d'acquisition. `partial` est un état de premier
  rang (preuve incomplète, jamais présentée comme complète) ;
- l'enrichissement (`enrichment`) s'ajoute à tout moment sans toucher aux
  champs d'acquisition : une description n'est jamais requise pour acquérir ;
- la provenance est explicite (`ArtifactRelation`), jamais cachée dans des
  métadonnées opaques (D08) ;
- toute chaîne et toute collection est bornée ; la validation refuse, elle ne
  tronque pas.

Pur : aucune E/S, aucune horloge implicite (chaque transition reçoit `now`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any
import uuid

from jarvis.domain._checks import (
    MAX_ID_CHARS, TOKEN, check_aware, check_prefixed_id, freeze_runtime_metadata, parse_dt, parse_enum, preview,
    strict_keys,
)
from jarvis.domain.session_context import CONTEXT_ID_PREFIX
from jarvis.domain.workspace_board import SESSION_ID_PREFIX

# ------------------------------------------------------------------ constantes

ARTIFACT_ID_PREFIX = "jart_"
#: Dossier des payloads, relatif à la racine de données (D-ART).
ARTIFACTS_DIR = "artifacts"
#: Suffixe d'un payload en cours d'écriture ; jamais un nom de payload final.
PARTIAL_SUFFIX = ".partial"

MAX_SOURCE_CHARS = 64
MAX_MIME_CHARS = 100
MAX_ERROR_CODE_CHARS = 64
MAX_PAYLOAD_NAME_CHARS = 64
#: Texte court porté directement par la ligne (segment de transcription,
#: description). Au-delà, le texte est un payload fichier.
MAX_ARTIFACT_TEXT_CHARS = 16_000
#: Métadonnées d'acquisition : quelques scalaires (périphérique, codec...).
MAX_METADATA_KEYS = 32
MAX_METADATA_VALUE_CHARS = 512
#: Enrichissement (descriptions, locuteurs, étiquettes) : scalaires plus longs.
MAX_ENRICHMENT_KEYS = 32
MAX_ENRICHMENT_VALUE_CHARS = 4_000
MAX_KEY_CHARS = 64
#: Origines d'un Artifact (relations dont il est le sujet).
MAX_RELATIONS_PER_ARTIFACT = 64
#: 8 jours de vidéo 4K restent sous cette borne ; au-delà, valeur suspecte.
MAX_SIZE_BYTES = 1 << 50
MAX_DURATION_MS = 1_000 * 3_600 * 24 * 31
MAX_DIMENSION = 65_535

#: Nom de fichier d'un payload : minuscules (NTFS ignore la casse), chiffres,
#: `_`, `.`, `-`, commence par une lettre ou un chiffre (ni `..`, ni nom caché).
_PAYLOAD_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


# ------------------------------------------------------------------ erreurs


class ArtifactErrorCode(StrEnum):
    """Motif stable d'un refus du registre : se compare, se journalise, voyage en HTTP/MCP."""

    INVALID_ARTIFACT = "invalid_artifact"
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    #: Identifiant déjà pris, ou ligne changée entre la lecture et l'écriture.
    ARTIFACT_CONFLICT = "artifact_conflict"
    #: Transition depuis un état terminal (`complete`, `partial`, `failed`),
    #: ou suppression d'un Artifact encore `pending` (acquisition en cours).
    ARTIFACT_NOT_PENDING = "artifact_not_pending"
    ARTIFACT_STILL_PENDING = "artifact_still_pending"
    #: Suppression d'une origine dont d'autres Artifacts dérivent, sans `cascade`.
    ARTIFACT_HAS_DEPENDENTS = "artifact_has_dependents"
    INVALID_RELATION = "invalid_relation"
    #: La relation fermerait un cycle de provenance.
    RELATION_CYCLE = "relation_cycle"


HTTP_STATUS: Mapping[ArtifactErrorCode, int] = MappingProxyType({
    ArtifactErrorCode.INVALID_ARTIFACT: 400,
    ArtifactErrorCode.ARTIFACT_NOT_FOUND: 404,
    ArtifactErrorCode.ARTIFACT_CONFLICT: 409,
    ArtifactErrorCode.ARTIFACT_NOT_PENDING: 409,
    ArtifactErrorCode.ARTIFACT_STILL_PENDING: 409,
    ArtifactErrorCode.ARTIFACT_HAS_DEPENDENTS: 409,
    ArtifactErrorCode.INVALID_RELATION: 400,
    ArtifactErrorCode.RELATION_CYCLE: 409,
})


class ArtifactError(ValueError):
    """Refus nommé du registre ; `code` stable, `status` HTTP (forme de `SessionContextError`)."""

    def __init__(self, code: ArtifactErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = ArtifactErrorCode(code)
        self.status = HTTP_STATUS[self.code]


def _invalid(message: str) -> ArtifactError:
    return ArtifactError(ArtifactErrorCode.INVALID_ARTIFACT, message)


def _invalid_relation(message: str) -> ArtifactError:
    return ArtifactError(ArtifactErrorCode.INVALID_RELATION, message)


# ------------------------------------------------------------------ énumérations


class ArtifactKind(StrEnum):
    """Ensemble **fermé** des natures V1. Ajouter une nature = ajouter une valeur ici
    et la documenter (`docs/artifacts.md`) ; aucune migration (pas de CHECK SQL sur
    `kind`). Pas de fourre-tout `other` : une preuve sans nature n'est pas indexable.
    """

    AUDIO_RECORDING = "audio_recording"
    TRANSCRIPT_SEGMENT = "transcript_segment"
    TRANSCRIPT = "transcript"
    SCREENSHOT = "screenshot"
    SCREEN_RECORDING = "screen_recording"
    #: Description d'une preuve (vision, résumé d'image...).
    DESCRIPTION = "description"
    #: Autre preuve dérivée (résumé, observation, extrait).
    DERIVED = "derived"


class ArtifactState(StrEnum):
    #: Acquisition en cours : payload éventuellement en `.partial`.
    PENDING = "pending"
    #: Acquisition terminée, payload final.
    COMPLETE = "complete"
    #: Preuve incomplète (arrêt brutal, perte) : lisible, jamais présentée complète.
    PARTIAL = "partial"
    #: Aucune preuve exploitable ; `error_code` dit pourquoi.
    FAILED = "failed"


TERMINAL_STATES = frozenset({ArtifactState.COMPLETE, ArtifactState.PARTIAL, ArtifactState.FAILED})


class ArtifactRelationKind(StrEnum):
    """Vocabulaire fermé de provenance : « `artifact_id` <relation> `origin_artifact_id` »."""

    #: Transcription (ou segment) tirée d'un enregistrement audio.
    TRANSCRIBED_FROM = "transcribed_from"
    #: Segment d'un tout (segment de transcription -> transcription).
    SEGMENT_OF = "segment_of"
    #: Image extraite d'un enregistrement d'écran.
    FRAME_FROM = "frame_from"
    #: Description d'une capture, d'une image ou d'un extrait.
    DESCRIBED_FROM = "described_from"
    #: Toute autre dérivation (résumé, observation).
    DERIVED_FROM = "derived_from"


# ------------------------------------------------------------------ identifiants et chemins


def new_artifact_id() -> str:
    return f"{ARTIFACT_ID_PREFIX}{uuid.uuid4().hex}"


def check_artifact_id(value: object, name: str = "artifact_id") -> None:
    check_prefixed_id(_invalid, name, value, ARTIFACT_ID_PREFIX)


def check_payload_name(value: object) -> None:
    if not isinstance(value, str):
        raise _invalid(f"payload name must be a string, got {preview(value)}")
    if (len(value) > MAX_PAYLOAD_NAME_CHARS or not _PAYLOAD_NAME.fullmatch(value) or ".." in value
            or value.endswith(PARTIAL_SUFFIX)):
        raise _invalid(
            f"payload name must be lowercase letters, digits, '_', '.' or '-' (<= {MAX_PAYLOAD_NAME_CHARS} chars, "
            f"no '..', not ending with {PARTIAL_SUFFIX!r}), got {preview(value)}")


def artifact_folder_path(artifact_id: str) -> PurePosixPath:
    """`artifacts/<artifact_id>`, **relatif** à la racine de données."""

    check_artifact_id(artifact_id)
    return PurePosixPath(ARTIFACTS_DIR, artifact_id)


def payload_ref_for(artifact_id: str, name: str) -> str:
    """`artifacts/<artifact_id>/<name>` : la seule forme de `payload_ref` acceptée."""

    check_payload_name(name)
    return (artifact_folder_path(artifact_id) / name).as_posix()


def parse_payload_ref(payload_ref: object) -> tuple[str, str]:
    """`(artifact_id, name)` d'une référence ; `invalid_artifact` pour toute autre forme."""

    if not isinstance(payload_ref, str):
        raise _invalid(f"payload_ref must be a string, got {preview(payload_ref)}")
    parts = payload_ref.split("/")
    if len(parts) != 3 or parts[0] != ARTIFACTS_DIR:
        raise _invalid(f"payload_ref must be '{ARTIFACTS_DIR}/<artifact_id>/<name>', got {preview(payload_ref)}")
    check_artifact_id(parts[1], "payload_ref artifact id")
    check_payload_name(parts[2])
    return parts[1], parts[2]


# ------------------------------------------------------------------ contrôles


def _check_token(name: str, value: object, limit: int, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value or len(value) > limit or not TOKEN.fullmatch(value):
        raise _invalid(f"{name} must be a short token (letters, digits, '_', '.', '-', <= {limit}), "
                       f"got {preview(value)}")


def _check_count(name: str, value: object, limit: int) -> None:
    if value is None:
        return
    if type(value) is not int or not 0 <= value <= limit:
        raise _invalid(f"{name} must be an integer in 0..{limit}, got {preview(value)}")


def _freeze(value: object, *, max_keys: int, max_value_chars: int, name: str) -> Mapping[str, Any]:
    def fail(message: str) -> ArtifactError:
        return _invalid(message.replace("runtime_metadata", name))

    return freeze_runtime_metadata(fail, value, max_keys=max_keys, max_key_chars=MAX_KEY_CHARS,
                                   max_value_chars=max_value_chars)


def _freeze_metadata(value: object) -> Mapping[str, Any]:
    return _freeze(value, max_keys=MAX_METADATA_KEYS, max_value_chars=MAX_METADATA_VALUE_CHARS, name="metadata")


def _freeze_enrichment(value: object) -> Mapping[str, Any]:
    return _freeze(value, max_keys=MAX_ENRICHMENT_KEYS, max_value_chars=MAX_ENRICHMENT_VALUE_CHARS,
                   name="enrichment")


# ------------------------------------------------------------------ valeur


@dataclass(frozen=True, slots=True)
class Artifact:
    """Une preuve du registre. Voir `docs/artifacts.md`.

    `payload_ref` : `artifacts/<artifact_id>/<name>` (relatif à la racine de
    données, jamais absolu), fixé à la création ; le fichier final n'existe
    qu'après finalisation. `text` : texte court porté par la ligne. `metadata` :
    acquisition (figée avec l'état terminal) ; `enrichment` : ajouté plus tard.
    """

    artifact_id: str
    kind: ArtifactKind
    source: str
    state: ArtifactState
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    jarvis_session_id: str | None = None
    context_id: str | None = None
    payload_ref: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    text: str | None = None
    error_code: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    enrichment: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        check_artifact_id(self.artifact_id)
        if not isinstance(self.kind, ArtifactKind):
            raise _invalid("kind must be an ArtifactKind")
        if not isinstance(self.state, ArtifactState):
            raise _invalid("state must be an ArtifactState")
        _check_token("source", self.source, MAX_SOURCE_CHARS)
        check_aware(_invalid, "created_at", self.created_at)
        check_aware(_invalid, "updated_at", self.updated_at)
        check_aware(_invalid, "started_at", self.started_at, required=False)
        check_aware(_invalid, "ended_at", self.ended_at, required=False)
        if self.updated_at < self.created_at:
            raise _invalid("updated_at must not precede created_at")
        if self.started_at is not None and self.ended_at is not None and self.ended_at < self.started_at:
            raise _invalid("ended_at must not precede started_at")
        if self.jarvis_session_id is not None:
            check_prefixed_id(_invalid, "jarvis_session_id", self.jarvis_session_id, SESSION_ID_PREFIX)
        if self.context_id is not None:
            check_prefixed_id(_invalid, "context_id", self.context_id, CONTEXT_ID_PREFIX)
            if self.jarvis_session_id is None:
                raise _invalid("an artifact with a context_id must name its jarvis_session_id")
        if self.payload_ref is not None:
            owner, _name = parse_payload_ref(self.payload_ref)
            if owner != self.artifact_id:
                raise _invalid("payload_ref must live in the artifact's own folder")
        if self.mime_type is not None and (not isinstance(self.mime_type, str) or len(self.mime_type) > MAX_MIME_CHARS
                                           or not _MIME.fullmatch(self.mime_type)):
            raise _invalid(f"mime_type must be a lowercase type/subtype, got {preview(self.mime_type)}")
        _check_count("size_bytes", self.size_bytes, MAX_SIZE_BYTES)
        _check_count("duration_ms", self.duration_ms, MAX_DURATION_MS)
        _check_count("width", self.width, MAX_DIMENSION)
        _check_count("height", self.height, MAX_DIMENSION)
        if (self.width is None) != (self.height is None):
            raise _invalid("width and height go together")
        if self.text is not None and (not isinstance(self.text, str) or len(self.text) > MAX_ARTIFACT_TEXT_CHARS):
            raise _invalid(f"text must be a string of at most {MAX_ARTIFACT_TEXT_CHARS} characters")
        _check_token("error_code", self.error_code, MAX_ERROR_CODE_CHARS, required=False)
        if self.state is ArtifactState.FAILED and self.error_code is None:
            raise _invalid("a failed artifact must carry an error_code")
        if self.state in (ArtifactState.PENDING, ArtifactState.COMPLETE) and self.error_code is not None:
            raise _invalid(f"a {self.state.value} artifact carries no error_code")
        if self.state is ArtifactState.COMPLETE:
            if self.payload_ref is None and self.text is None:
                raise _invalid("a complete artifact must have a payload or a text")
            if self.payload_ref is not None and self.size_bytes is None:
                raise _invalid("a complete artifact with a payload must carry size_bytes")
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))
        object.__setattr__(self, "enrichment", _freeze_enrichment(self.enrichment))

    @property
    def is_pending(self) -> bool:
        return self.state is ArtifactState.PENDING

    @property
    def payload_name(self) -> str | None:
        return None if self.payload_ref is None else parse_payload_ref(self.payload_ref)[1]

    def to_payload(self) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat()

        return {
            "artifact_id": self.artifact_id, "kind": self.kind.value, "source": self.source,
            "state": self.state.value, "created_at": iso(self.created_at), "updated_at": iso(self.updated_at),
            "started_at": iso(self.started_at), "ended_at": iso(self.ended_at),
            "jarvis_session_id": self.jarvis_session_id, "context_id": self.context_id,
            "payload_ref": self.payload_ref, "mime_type": self.mime_type, "size_bytes": self.size_bytes,
            "duration_ms": self.duration_ms, "width": self.width, "height": self.height, "text": self.text,
            "error_code": self.error_code, "metadata": dict(self.metadata), "enrichment": dict(self.enrichment),
        }

    @classmethod
    def from_payload(cls, payload: object) -> Artifact:
        """Strict : champ inconnu ou manquant, type faux, date naïve, énum inconnue -> `invalid_artifact`."""

        payload = strict_keys(_invalid, "artifact", payload, _KEYS, required=_REQUIRED)
        return cls(
            artifact_id=payload["artifact_id"],
            kind=parse_enum(_invalid, "kind", payload["kind"], ArtifactKind),
            source=payload["source"],
            state=parse_enum(_invalid, "state", payload["state"], ArtifactState),
            created_at=parse_dt(_invalid, "created_at", payload["created_at"]),
            updated_at=parse_dt(_invalid, "updated_at", payload["updated_at"]),
            started_at=parse_dt(_invalid, "started_at", payload.get("started_at"), required=False),
            ended_at=parse_dt(_invalid, "ended_at", payload.get("ended_at"), required=False),
            **{key: payload.get(key) for key in _OPTIONAL_SCALARS},
            metadata=payload.get("metadata", {}),
            enrichment=payload.get("enrichment", {}),
        )


_OPTIONAL_SCALARS = ("jarvis_session_id", "context_id", "payload_ref", "mime_type", "size_bytes", "duration_ms",
                     "width", "height", "text", "error_code")
_REQUIRED = frozenset({"artifact_id", "kind", "source", "state", "created_at", "updated_at"})
_KEYS = _REQUIRED | frozenset({"started_at", "ended_at", "metadata", "enrichment", *_OPTIONAL_SCALARS})

#: Champs fixés à l'acquisition, jamais modifiés ensuite (D07).
IDENTITY_FIELDS = ("artifact_id", "kind", "source", "created_at", "started_at", "jarvis_session_id", "context_id",
                   "payload_ref")
#: Champs d'acquisition gelés dès qu'un état est terminal.
ACQUISITION_FIELDS = (*IDENTITY_FIELDS, "state", "ended_at", "mime_type", "size_bytes", "duration_ms", "width",
                      "height", "text", "error_code", "metadata")


# ------------------------------------------------------------------ transitions


def new_artifact(
    *,
    kind: ArtifactKind,
    source: str,
    now: datetime,
    jarvis_session_id: str | None = None,
    context_id: str | None = None,
    payload_name: str | None = None,
    started_at: datetime | None = None,
    mime_type: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    artifact_id: str | None = None,
) -> Artifact:
    """Artifact `pending` : identité, temps et source fixés à l'acquisition (D07).

    `payload_name` réserve `artifacts/<id>/<name>` ; le fichier n'existe qu'à
    la finalisation (l'écrivain écrit `<name>.partial`).
    """

    new_id = new_artifact_id() if artifact_id is None else artifact_id
    check_artifact_id(new_id)
    return Artifact(
        artifact_id=new_id, kind=kind, source=source, state=ArtifactState.PENDING, created_at=now, updated_at=now,
        started_at=started_at, jarvis_session_id=jarvis_session_id, context_id=context_id,
        payload_ref=None if payload_name is None else payload_ref_for(new_id, payload_name),
        mime_type=mime_type, metadata={} if metadata is None else metadata,
    )


def _require_pending(artifact: Artifact) -> None:
    if not artifact.is_pending:
        raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_PENDING,
                            f"artifact {artifact.artifact_id} is {artifact.state.value}; acquisition is closed")


def finalize_artifact(
    artifact: Artifact,
    *,
    now: datetime,
    state: ArtifactState = ArtifactState.COMPLETE,
    size_bytes: int | None = None,
    ended_at: datetime | None = None,
    duration_ms: int | None = None,
    width: int | None = None,
    height: int | None = None,
    text: str | None = None,
    error_code: str | None = None,
) -> Artifact:
    """`pending` -> `complete` ou `partial` (avec `error_code` facultatif disant la perte).

    Depuis un état terminal : `artifact_not_pending`. Les valeurs `None`
    gardent celles déjà connues (durée, dimensions).
    """

    _require_pending(artifact)
    if state not in (ArtifactState.COMPLETE, ArtifactState.PARTIAL):
        raise _invalid("finalize_artifact reaches complete or partial; use fail_artifact for failed")
    return replace(
        artifact, state=state, updated_at=max(now, artifact.updated_at),
        size_bytes=artifact.size_bytes if size_bytes is None else size_bytes,
        ended_at=artifact.ended_at if ended_at is None else ended_at,
        duration_ms=artifact.duration_ms if duration_ms is None else duration_ms,
        width=artifact.width if width is None else width, height=artifact.height if height is None else height,
        text=artifact.text if text is None else text, error_code=error_code,
    )


def fail_artifact(artifact: Artifact, *, now: datetime, error_code: str, ended_at: datetime | None = None) -> Artifact:
    """`pending` -> `failed` : aucune preuve exploitable. Le payload éventuel n'est pas effacé."""

    _require_pending(artifact)
    return replace(artifact, state=ArtifactState.FAILED, updated_at=max(now, artifact.updated_at),
                   error_code=error_code, ended_at=artifact.ended_at if ended_at is None else ended_at)


def update_pending(artifact: Artifact, *, now: datetime, size_bytes: int | None = None,
                   duration_ms: int | None = None, text: str | None = None,
                   metadata: Mapping[str, Any] | None = None) -> Artifact:
    """Progrès d'une acquisition en cours, sans changer d'état.

    Octets ou durée écrits ; `text` réécrit (projection de transcription en
    cours, Slice 06) ; `metadata` **remplace** les métadonnées d'acquisition
    (l'appelant fusionne). `None` garde la valeur connue. Bornes de la
    création (`invalid_artifact`, rien n'est tronqué).
    """

    _require_pending(artifact)
    return replace(artifact, updated_at=max(now, artifact.updated_at),
                   size_bytes=artifact.size_bytes if size_bytes is None else size_bytes,
                   duration_ms=artifact.duration_ms if duration_ms is None else duration_ms,
                   text=artifact.text if text is None else text,
                   metadata=artifact.metadata if metadata is None else metadata)


def enrich_artifact(artifact: Artifact, updates: Mapping[str, Any], *, now: datetime) -> Artifact:
    """Fusionne `updates` dans `enrichment` (valeur `None` : clé retirée), dans **tout** état.

    Ne touche jamais aux champs d'acquisition (D07). Résultat borné comme à la
    création (`invalid_artifact` au-delà, rien n'est tronqué).
    """

    if not isinstance(updates, Mapping) or not updates:
        raise _invalid("enrichment updates must be a non-empty mapping")
    merged = dict(artifact.enrichment)
    for key, value in updates.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return replace(artifact, enrichment=merged, updated_at=max(now, artifact.updated_at))


def check_artifact_update(previous: Artifact, updated: Artifact) -> None:
    """Garde du magasin : l'identité ne change jamais ; un état terminal ne change que son enrichissement."""

    if previous.artifact_id != updated.artifact_id:
        raise _invalid("an update must target the same artifact")
    for name in IDENTITY_FIELDS:
        if getattr(previous, name) != getattr(updated, name):
            raise ArtifactError(ArtifactErrorCode.ARTIFACT_CONFLICT,
                                f"artifact {previous.artifact_id}: {name} is fixed at acquisition")
    if not previous.is_pending:
        changed = [name for name in ACQUISITION_FIELDS if getattr(previous, name) != getattr(updated, name)]
        if changed:
            raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_PENDING,
                                f"artifact {previous.artifact_id} is {previous.state.value}: "
                                f"{changed[0]} cannot change")
    if updated.updated_at < previous.updated_at:
        raise _invalid("updated_at must not go backwards")


# ------------------------------------------------------------------ relations


@dataclass(frozen=True, slots=True)
class ArtifactRelation:
    """« `artifact_id` <`relation`> `origin_artifact_id` » : provenance explicite (D08).

    Exemple : segment `transcribed_from` enregistrement audio. Jamais vers
    soi-même ; le magasin refuse aussi un cycle (`relation_cycle`).
    """

    artifact_id: str
    relation: ArtifactRelationKind
    origin_artifact_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        check_prefixed_id(_invalid_relation, "artifact_id", self.artifact_id, ARTIFACT_ID_PREFIX)
        check_prefixed_id(_invalid_relation, "origin_artifact_id", self.origin_artifact_id, ARTIFACT_ID_PREFIX)
        if not isinstance(self.relation, ArtifactRelationKind):
            raise _invalid_relation(f"relation must be an ArtifactRelationKind, got {preview(self.relation)}")
        check_aware(_invalid_relation, "created_at", self.created_at)
        if self.artifact_id == self.origin_artifact_id:
            raise _invalid_relation(f"artifact {self.artifact_id} cannot derive from itself")

    def to_payload(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "relation": self.relation.value,
                "origin_artifact_id": self.origin_artifact_id, "created_at": self.created_at.isoformat()}

    @classmethod
    def from_payload(cls, payload: object) -> ArtifactRelation:
        payload = strict_keys(_invalid_relation, "relation", payload, _RELATION_KEYS, required=_RELATION_KEYS)
        return cls(
            artifact_id=payload["artifact_id"],
            relation=parse_enum(_invalid_relation, "relation", payload["relation"], ArtifactRelationKind),
            origin_artifact_id=payload["origin_artifact_id"],
            created_at=parse_dt(_invalid_relation, "created_at", payload["created_at"]),
        )


_RELATION_KEYS = frozenset({"artifact_id", "relation", "origin_artifact_id", "created_at"})


def check_relations(artifact_id: str, relations: tuple[ArtifactRelation, ...]) -> tuple[ArtifactRelation, ...]:
    """Relations dont `artifact_id` est le sujet : bornées, sans doublon."""

    if not isinstance(relations, tuple):
        raise _invalid_relation("relations must be a tuple")
    if len(relations) > MAX_RELATIONS_PER_ARTIFACT:
        raise _invalid_relation(f"an artifact has at most {MAX_RELATIONS_PER_ARTIFACT} origins")
    seen = set()
    for relation in relations:
        if not isinstance(relation, ArtifactRelation):
            raise _invalid_relation(f"expected an ArtifactRelation, got {preview(relation)}")
        if relation.artifact_id != artifact_id:
            raise _invalid_relation(f"relation subject {relation.artifact_id} is not {artifact_id}")
        key = (relation.relation, relation.origin_artifact_id)
        if key in seen:
            raise _invalid_relation(f"relation {relation.relation.value} -> {relation.origin_artifact_id} repeated")
        seen.add(key)
    return relations


# ------------------------------------------------------------------ requêtes

DEFAULT_ARTIFACT_LIMIT = 50
MAX_ARTIFACT_LIMIT = 200
MAX_QUERY_FILTER_VALUES = 16


@dataclass(frozen=True, slots=True)
class ArtifactQuery:
    """Filtre borné du registre ; résultat du plus récent au plus ancien (`created_at`, puis id).

    `since` inclus, `until` exclu. `cursor` : `next_cursor` d'une page
    précédente (pagination par clé, stable même à `created_at` égal).
    """

    jarvis_session_id: str | None = None
    context_id: str | None = None
    kinds: tuple[ArtifactKind, ...] = ()
    states: tuple[ArtifactState, ...] = ()
    since: datetime | None = None
    until: datetime | None = None
    cursor: str | None = None
    limit: int = DEFAULT_ARTIFACT_LIMIT

    def __post_init__(self) -> None:
        if self.jarvis_session_id is not None:
            check_prefixed_id(_invalid, "jarvis_session_id", self.jarvis_session_id, SESSION_ID_PREFIX)
        if self.context_id is not None:
            check_prefixed_id(_invalid, "context_id", self.context_id, CONTEXT_ID_PREFIX)
        for name, values, enum in (("kinds", self.kinds, ArtifactKind), ("states", self.states, ArtifactState)):
            if not isinstance(values, tuple) or len(values) > MAX_QUERY_FILTER_VALUES:
                raise _invalid(f"{name} must be a tuple of at most {MAX_QUERY_FILTER_VALUES} values")
            if not all(isinstance(value, enum) for value in values):
                raise _invalid(f"{name} must hold {enum.__name__} values")
        check_aware(_invalid, "since", self.since, required=False)
        check_aware(_invalid, "until", self.until, required=False)
        if self.since is not None and self.until is not None and self.until < self.since:
            raise _invalid("until must not precede since")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_ARTIFACT_LIMIT:
            raise _invalid(f"limit must be an integer in 1..{MAX_ARTIFACT_LIMIT}")
        if self.cursor is not None:
            decode_artifact_cursor(self.cursor)


def encode_artifact_cursor(created_key: str, artifact_id: str) -> str:
    return f"{created_key}|{artifact_id}"


def decode_artifact_cursor(cursor: object) -> tuple[str, str]:
    """`(clé de created_at UTC, artifact_id)` ; `invalid_artifact` pour un curseur forgé."""

    if not isinstance(cursor, str) or len(cursor) > MAX_ID_CHARS + 40 or cursor.count("|") != 1:
        raise _invalid(f"cursor is not a registry cursor: {preview(cursor)}")
    key, artifact_id = cursor.split("|")
    check_artifact_id(artifact_id, "cursor artifact id")
    try:
        datetime.fromisoformat(key)
    except ValueError:
        raise _invalid(f"cursor is not a registry cursor: {preview(cursor)}") from None
    return key, artifact_id


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    items: tuple[Artifact, ...]
    #: Curseur de la page suivante ; `None` quand la page n'est pas pleine.
    next_cursor: str | None
