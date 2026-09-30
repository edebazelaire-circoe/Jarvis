"""Relais spontané typé : ce qu'un relais déclare de lui-même avant d'être dit.

Un relais est une parole que personne n'a demandée : la fin d'un sous-agent
d'arrière-plan résumée par le cerveau, l'accusé de réception d'une analyse de
calibration, puis cette analyse. Il suit la chaîne

    ClaudeLocalAgent.publish_notice / _push_notice   (Control Center)
    -> GET /api/agent/notices                         (Control Center)
    -> ControlCenterBrainBackend.next_notices         (Core, client HTTP)
    -> JarvisCoreApplication._brain_notice_loop       (Core)
    -> BrainOrchestrator.announce_notice              (Core -> SpeechRequest)

Contrat (tâche `jarvis-voice-stale-speech-presentation`, Slice 03 ;
`docs/conversation-events.md`, « Spontaneous notices ») : **aucun relais sans
genre**. Chaque relais déclare

- `kind` (`ack`, `progress` ou `result` — `NOTICE_KINDS` ; défaut `result`) — un accusé (`ack`) ou une étape
  (`progress`) est transitoire : il reçoit une échéance, la sienne (`ttl_s`) ou
  celle de Core par défaut (`DEFAULT_TRANSIENT_SPEECH_TTL_S`) ;
- `supersedes_key` (optionnel) — même emplacement de parole : le relais le plus
  récent remplace celui qui n'a pas encore démarré (règle de l'ordonnanceur
  vocal, `SpeechRequest.supersedes`, jamais dupliquée ici) ;
- `ttl_s` (optionnel) — durée de vie en secondes, comptée depuis la création
  de la `SpeechRequest` par Core ;
- `work_id` (optionnel) — le travail que le relais conclut, quand il est connu.

Le texte reste celui du cerveau ou la phrase fixe du Control Center : ce
contrat ne porte que le genre et la clé (Décision 14).

Toute valeur hors contrat lève `ValueError` : chaque frontière la **refuse et
le trace**, jamais en silence. Un relais de l'ancien format (sans `kind`) est
un `result` : il est toujours dit (compatibilité, `docs/legacy/untyped-brain-notices.md`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any

from jarvis.domain.speech_presentation import speech_id
from jarvis.domain.v2 import SpeechKind

#: Champs de genre qu'une notice transporte, en plus de son texte.
NOTICE_TYPING_FIELDS = ("kind", "supersedes_key", "ttl_s", "work_id")
#: Genres qu'un relais peut déclarer. `error` et `question` en sont exclus : ce
#: sont des natures de **sûreté** que la matrice de présentation laisse passer
#: malgré le plafond (`safety_speech_kinds`), et Core seul les pose, à partir du
#: contenu (`public_answer_kind`) ou d'un échec réel — jamais sur la foi d'un
#: champ transporté (garde `test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole`).
NOTICE_KINDS = (SpeechKind.ACK, SpeechKind.PROGRESS, SpeechKind.RESULT)
#: Genre d'un relais qui n'en déclare pas (ancien format) : un résultat durable.
DEFAULT_NOTICE_KIND = SpeechKind.RESULT
#: Borne basse d'une durée de vie déclarée : en deçà, la parole serait périmée
#: avant même d'être publiée (et `SpeechRequest` refuserait une échéance qui
#: n'est pas strictement après sa création). Une seconde est le plus court
#: délai où dire quelque chose a encore un sens.
MIN_NOTICE_TTL_S = 1.0
#: Borne haute d'une durée de vie déclarée : au-delà, ce n'est plus une
#: échéance mais un oubli (une heure couvre le plus long tour du cerveau).
MAX_NOTICE_TTL_S = 3600.0


def notice_kind(value: object) -> SpeechKind:
    """Le genre déclaré, `SpeechKind` ou sa valeur textuelle ; `None` = ancien format."""

    if value is None:
        # Compatibilité ancien format (retrait : docs/legacy/untyped-brain-notices.md).
        return DEFAULT_NOTICE_KIND
    for kind in NOTICE_KINDS:
        if value is kind or (isinstance(value, str) and value == kind.value):
            return kind
    raise ValueError(f"notice kind must be one of {[kind.value for kind in NOTICE_KINDS]}, got {value!r}")


def notice_ttl_s(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"notice ttl_s must be a finite number of seconds, got {value!r}")
    if not MIN_NOTICE_TTL_S <= value <= MAX_NOTICE_TTL_S:
        raise ValueError(f"notice ttl_s must be in [{MIN_NOTICE_TTL_S:g}, {MAX_NOTICE_TTL_S:g}], got {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class NoticeTyping:
    """Le genre d'un relais, validé. Construire l'objet, c'est valider."""

    kind: SpeechKind = DEFAULT_NOTICE_KIND
    supersedes_key: str | None = None
    ttl_s: float | None = None
    work_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", notice_kind(self.kind))
        object.__setattr__(self, "ttl_s", notice_ttl_s(self.ttl_s))
        speech_id(self.supersedes_key, "supersedes_key", optional=True)
        speech_id(self.work_id, "work_id", optional=True)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> NoticeTyping:
        """Lire le genre d'une notice transportée ; champs absents = ancien format."""

        return cls(**{name: payload.get(name) for name in NOTICE_TYPING_FIELDS if payload.get(name) is not None})

    def to_payload(self) -> dict[str, Any]:
        """Forme de transport : `kind` toujours explicite, les autres champs à `None` s'ils manquent."""

        return {"kind": self.kind.value, "supersedes_key": self.supersedes_key, "ttl_s": self.ttl_s,
                "work_id": self.work_id}
