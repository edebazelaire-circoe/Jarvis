"""Briques communes du contrat Presentation Studio : erreurs codees et verifications d'entree (Slices 02 et 04).

Sans dependance interne : `presentation_studio` (documents) et
`presentation_studio_scene` (scenes et controles) les importent tous deux, ce qui
evite le cycle entre elles. `presentation_studio` les re-exporte sous leurs noms
d'origine ; le contrat reste `docs/presentation-studio.md`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import re
from typing import Any

MAX_TITLE = 80  # = `MAX_TITLE_CHARS` des prefabs (`jarvis/domain/prefab.py`), verifie par un test
MAX_ERROR_CHARS = 300
SCENE_ID = re.compile(r"pss_[0-9a-f]{12}\Z")

#: Noms d'état d'exécution : refusés avec leur propre code (jamais persistés).
RUNTIME_KEYS = frozenset({
    "object_id", "window_id", "stage_object_id", "scene_object_id", "element", "element_id", "dom", "dom_id", "node",
    "handle", "iframe", "frame", "port", "session_id", "playback", "playback_state", "position", "score_position",
    "reveal", "reveal_progress", "detour", "detours", "aux_resources", "auxiliary_resources", "undo", "redo",
    "undo_stack", "redo_stack", "cursor", "focus", "selection", "selected",
})


def is_scene_id(value: object) -> bool:
    return isinstance(value, str) and bool(SCENE_ID.fullmatch(value))


class PresentationStudioErrorCode(StrEnum):
    #: Entrée refusée (corps de requête, charge utile) : l'appelant corrige.
    INVALID_PRESENTATION = "presentation_studio_invalid"
    #: Clé d'état d'exécution (handle, DOM, position de lecture...) dans un document persistant.
    RUNTIME_STATE_REFUSED = "presentation_studio_runtime_state_refused"
    #: Document stocké plus récent que ce Core sait lire : conservé tel quel, jamais réécrit.
    UNSUPPORTED_SCHEMA_VERSION = "presentation_studio_unsupported_schema_version"
    #: Document stocké illisible ou incohérent : panne de données, pas une demande refusée.
    CORRUPT_DOCUMENT = "presentation_studio_corrupt_document"
    UNKNOWN_PRESENTATION = "presentation_studio_unknown_presentation"
    UNKNOWN_VARIANT = "presentation_studio_unknown_variant"
    ALREADY_EXISTS = "presentation_studio_already_exists"
    #: `expected_revision` différent de la révision stockée : relire puis recommencer.
    STALE_REVISION = "presentation_studio_stale_revision"
    LIMIT_REACHED = "presentation_studio_limit_reached"
    #: Disque, lien/jonction refusé, racine indisponible.
    STORAGE_IO = "presentation_studio_storage_io"
    #: Aucune scène de ce `scene_id` dans la variante (Slice 04).
    UNKNOWN_SCENE = "presentation_studio_unknown_scene"
    #: Contrôles ou valeurs d'une scène en désaccord avec le manifeste de son prefab épinglé (Slice 04).
    SCENE_INCOMPATIBLE = "presentation_studio_scene_incompatible"
    #: Le prefab épinglé n'existe pas, est altéré ou son catalogue est indisponible : la vraie cause est dans le message (Slice 04).
    PREFAB_UNAVAILABLE = "presentation_studio_prefab_unavailable"
    #: La variante n'a pas de partition (`score_id` nul) ou son fichier est absent (Slice 10).
    UNKNOWN_SCORE = "presentation_studio_unknown_score"
    #: La partition cite une scène, un contrôle, une ancre ou une valeur que la variante ne déclare pas (Slice 10).
    SCORE_INCOMPATIBLE = "presentation_studio_score_incompatible"
    #: Aucun contrôle de ce `control_id` n'est déclaré sur la scène : un changement hors contrôles est une demande de source (Slice 05).
    UNKNOWN_CONTROL = "presentation_studio_unknown_control"
    #: La valeur d'un contrôle est refusée par le schéma du prefab ou par les bornes curées (Slice 05).
    VALUE_REFUSED = "presentation_studio_value_refused"
    #: Aucun historique d'annulation pour cette variante (mémoire seulement : redémarrage, anneau abandonné ou évincé) (Slice 08).
    HISTORY_UNAVAILABLE = "presentation_studio_history_unavailable"
    #: Rien à annuler / à rétablir (Slice 08).
    HISTORY_EMPTY = "presentation_studio_history_empty"
    #: Le document ou la tête de l'historique a bougé depuis ce que l'appelant a vu : rien n'est écrit (Slice 08).
    HISTORY_STALE = "presentation_studio_history_stale"
    #: L'actif ne peut pas être archivé tant qu'un autre n'est pas choisi, ni la dernière variante vivante (Slice 16).
    ACTIVE_VARIANT_PROTECTED = "presentation_studio_active_variant_protected"
    #: Une destruction/archivage sans le jeton de confirmation d'un plan (Slice 16).
    CONFIRMATION_REQUIRED = "presentation_studio_confirmation_required"
    #: Le jeton ne correspond plus à ce qui serait archivé (ensemble, titre, révision, nouvel actif) ou a expiré (Slice 16).
    CONFIRMATION_STALE = "presentation_studio_confirmation_stale"
    #: Restaurer une variante qui n'est pas archivée (Slice 16).
    NOT_ARCHIVED = "presentation_studio_not_archived"
    #: Un document lié (partition, direction artistique...) ne sait pas être copié : la branche est refusée plutôt que de le partager (Slice 16).
    LINKED_DOCUMENT_UNSUPPORTED = "presentation_studio_linked_document_unsupported"


_C = PresentationStudioErrorCode
HTTP_STATUS: Mapping[PresentationStudioErrorCode, int] = {
    _C.INVALID_PRESENTATION: 400,
    _C.RUNTIME_STATE_REFUSED: 400,
    _C.UNSUPPORTED_SCHEMA_VERSION: 409,
    _C.CORRUPT_DOCUMENT: 409,
    _C.UNKNOWN_PRESENTATION: 404,
    _C.UNKNOWN_VARIANT: 404,
    _C.ALREADY_EXISTS: 409,
    _C.STALE_REVISION: 409,
    _C.LIMIT_REACHED: 409,
    _C.STORAGE_IO: 500,
    _C.UNKNOWN_SCENE: 404,
    _C.SCENE_INCOMPATIBLE: 400,
    _C.PREFAB_UNAVAILABLE: 409,
    _C.UNKNOWN_SCORE: 404,
    _C.SCORE_INCOMPATIBLE: 400,
    _C.UNKNOWN_CONTROL: 404,
    _C.VALUE_REFUSED: 400,
    _C.HISTORY_UNAVAILABLE: 409,
    _C.HISTORY_EMPTY: 409,
    _C.HISTORY_STALE: 409,
    _C.ACTIVE_VARIANT_PROTECTED: 409,
    _C.CONFIRMATION_REQUIRED: 400,
    _C.CONFIRMATION_STALE: 409,
    _C.NOT_ARCHIVED: 409,
    _C.LINKED_DOCUMENT_UNSUPPORTED: 409,
}


def clip(message: str, limit: int = MAX_ERROR_CHARS) -> str:
    return message if len(message) <= limit else message[: limit - 1] + "…"


class PresentationStudioError(Exception):
    """Refus ou panne codés ; `message` ≤ `MAX_ERROR_CHARS`, sans chemin absolu."""

    def __init__(self, code: PresentationStudioErrorCode | str, message: str, *, warn: bool = False) -> None:
        #: `warn` : un refus qui est la faute de l'appelant même sous un code de panne (un pin inconnu tapé par l'agent) ;
        #: journalisé en `warning`, pas en `error`, pour que le visualiseur d'erreurs reste significatif.
        self.warn = warn
        self.code = PresentationStudioErrorCode(code)
        self.message = clip(message)
        self.status = HTTP_STATUS[self.code]
        super().__init__(f"{self.code.value}: {self.message}")


def _fail(message: str) -> PresentationStudioError:
    return PresentationStudioError(_C.INVALID_PRESENTATION, message)


def _check_id(name: str, value: object, pattern: re.Pattern[str], *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _fail(f"{name} is not a valid id ({pattern.pattern.split('_')[0]}_...)")


def _check_title(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise _fail(f"{name} must be a string")
    if not value.strip() or value != value.strip():
        raise _fail(f"{name} must be non-empty without surrounding spaces")
    if len(value) > MAX_TITLE:
        raise _fail(f"{name} exceeds {MAX_TITLE} characters")
    if not value.isprintable():
        raise _fail(f"{name} must be a single printable line")


def _check_int(name: str, value: object, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise _fail(f"{name} must be an integer in {low}..{high}")


def _exact_keys(raw: object, where: str, required: set[str], optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Objet exact : ni clé manquante ni clé inconnue. Un nom d'état d'exécution a son propre code."""

    if not isinstance(raw, dict):
        raise _fail(f"{where} must be a JSON object")
    keys = set(raw)
    runtime = sorted(keys & RUNTIME_KEYS)
    if runtime:
        raise PresentationStudioError(_C.RUNTIME_STATE_REFUSED, f"{where}: runtime-only state is never stored: "
                                                                 f"{', '.join(runtime[:6])}")
    unknown = keys - required - optional
    if unknown:
        raise _fail(f"{where}: unknown keys {', '.join(sorted(map(str, unknown))[:6])}")
    missing = required - keys
    if missing:
        raise _fail(f"{where}: missing keys {', '.join(sorted(missing)[:6])}")
    return raw
