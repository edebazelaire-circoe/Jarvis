"""Intention d'interface publiée par Jarvis (handoff jarvis-tool-brain-ui-orchestrator, Slice 4).

Contrat : `docs/tool-brain-contracts.md` §11. Jarvis dit **ce qu'il veut que l'utilisateur voie** (typé,
borné), jamais une commande d'écran : le Tool Brain reste le seul maître de l'action, de son moment et de
son annulation. Une intention n'accorde aucun droit et ne s'exécute pas ; elle est une donnée lue par S5/S6.

Pur domaine : pas d'I/O, pas d'horloge implicite, pas de dépendance au transport.

- `kind` : `reveal` (montrer), `attention` (attirer l'œil), `relevance` (ceci concerne ce que je dis ; à toi
  de juger), `dismiss` (n'est plus utile, peut s'effacer) ;
- `refs` : ids **stables** pris dans les choix de S2 (`scene.object` -> `object`, `board.switchable` ->
  `board`) ; jamais un id inventé, mais ce module ne lit aucun état (le Tool Brain valide à l'action) ;
- `subject` : quelques mots pour ce qui n'a pas encore d'id (« le résultat de la recherche ») ;
- `timing` : `now`, `with_speech` (au moment où le paragraphe `paragraph` est dit), `after_speech` ;
- `paragraph` : index (base 0) du paragraphe de la réponse, **le même** que `SpeechChunk.index` (les morceaux
  sont les paragraphes de `semantic_text_spans`) : le chunk visé se calcule, sans texte ni id à recopier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from jarvis.domain.speech_presentation import MAX_SPEECH_CHUNKS, speech_id

MAX_REFS = 8
MAX_SUBJECT_CHARS = 80
MAX_REF_ID_CHARS = 128
_REF_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]*")


class UiIntentKind(StrEnum):
    REVEAL = "reveal"
    ATTENTION = "attention"
    RELEVANCE = "relevance"
    DISMISS = "dismiss"


class UiIntentTiming(StrEnum):
    NOW = "now"
    WITH_SPEECH = "with_speech"
    AFTER_SPEECH = "after_speech"


class UiIntentRefKind(StrEnum):
    #: Fournisseur de choix S2 `scene.object`.
    OBJECT = "object"
    #: Fournisseur de choix S2 `board.switchable`.
    BOARD = "board"


#: Ref kind -> id de fournisseur de choix (`mcp_tool_meta.CHOICE_PROVIDERS`), seule table de correspondance.
PROVIDER_OF_REF: dict[UiIntentRefKind, str] = {
    UiIntentRefKind.OBJECT: "scene.object",
    UiIntentRefKind.BOARD: "board.switchable",
}

_PAYLOAD_KEYS = frozenset({"kind", "refs", "subject", "timing", "paragraph"})


@dataclass(frozen=True, slots=True)
class UiIntentRef:
    kind: UiIntentRefKind
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, UiIntentRefKind):
            raise ValueError("ref kind must be typed")
        if (not isinstance(self.id, str) or not 0 < len(self.id) <= MAX_REF_ID_CHARS
                or _REF_ID.fullmatch(self.id) is None):
            raise ValueError("ref id must be a stable id (letters, digits, _ . : -)")

    def to_payload(self) -> dict:
        return {"kind": self.kind.value, "id": self.id}

    @classmethod
    def from_payload(cls, value: object) -> UiIntentRef:
        if not isinstance(value, dict) or set(value) != {"kind", "id"}:
            raise ValueError("ref must be {kind, id}")
        try:
            kind = UiIntentRefKind(value["kind"])
        except ValueError:
            raise ValueError("ref kind must be one of " + ", ".join(item.value for item in UiIntentRefKind)) from None
        return cls(kind, value["id"])


@dataclass(frozen=True, slots=True)
class UiIntentDraft:
    """Ce que Jarvis déclare ; Core ajoute l'identité (`UiIntent`)."""

    kind: UiIntentKind
    refs: tuple[UiIntentRef, ...] = ()
    subject: str = ""
    timing: UiIntentTiming = UiIntentTiming.WITH_SPEECH
    paragraph: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, UiIntentKind) or not isinstance(self.timing, UiIntentTiming):
            raise ValueError("kind and timing must be typed")
        if (not isinstance(self.refs, tuple) or len(self.refs) > MAX_REFS
                or any(not isinstance(item, UiIntentRef) for item in self.refs)):
            raise ValueError(f"refs must be at most {MAX_REFS} typed refs")
        if len(set(self.refs)) != len(self.refs):
            raise ValueError("refs must be unique")
        if not isinstance(self.subject, str) or len(self.subject) > MAX_SUBJECT_CHARS or "\n" in self.subject:
            raise ValueError(f"subject must be one line of at most {MAX_SUBJECT_CHARS} characters")
        if not self.refs and not self.subject.strip():
            raise ValueError("an intent needs refs or a subject")
        if self.paragraph is not None:
            if type(self.paragraph) is not int or not 0 <= self.paragraph < MAX_SPEECH_CHUNKS:
                raise ValueError(f"paragraph must be an integer in 0..{MAX_SPEECH_CHUNKS - 1}")
            if self.timing is not UiIntentTiming.WITH_SPEECH:
                raise ValueError("paragraph only applies to timing with_speech")

    def to_payload(self) -> dict:
        payload: dict = {"kind": self.kind.value, "refs": [item.to_payload() for item in self.refs],
                         "subject": self.subject, "timing": self.timing.value}
        if self.paragraph is not None:
            payload["paragraph"] = self.paragraph
        return payload

    @classmethod
    def from_payload(cls, value: object) -> UiIntentDraft:
        if not isinstance(value, dict):
            raise ValueError("ui intent must be a JSON object")
        unknown = sorted(str(key)[:40] for key in set(value) - _PAYLOAD_KEYS)
        if unknown:
            raise ValueError(f"unknown ui intent fields: {unknown[:5]}")
        try:
            kind = UiIntentKind(value.get("kind"))
        except ValueError:
            raise ValueError("kind must be one of " + ", ".join(item.value for item in UiIntentKind)) from None
        try:
            timing = UiIntentTiming(value.get("timing", UiIntentTiming.WITH_SPEECH.value))
        except ValueError:
            raise ValueError("timing must be one of " + ", ".join(item.value for item in UiIntentTiming)) from None
        raw_refs = value.get("refs", [])
        if not isinstance(raw_refs, list):
            raise ValueError("refs must be a list")
        return cls(kind, tuple(UiIntentRef.from_payload(item) for item in raw_refs),
                   str(value.get("subject") or "").strip(), timing, value.get("paragraph"))


@dataclass(frozen=True, slots=True)
class UiIntent:
    """Intention publiée : identité Core + déclaration de Jarvis. Immuable ; corrélée au tour `correlation_id`."""

    intent_id: str
    conversation_id: str
    correlation_id: str
    draft: UiIntentDraft
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("intent_id", "conversation_id", "correlation_id"):
            speech_id(getattr(self, name), name)
        if not isinstance(self.draft, UiIntentDraft) or not isinstance(self.created_at, datetime):
            raise ValueError("intent needs a typed draft and a creation time")

    def to_payload(self) -> dict:
        return {"intent_id": self.intent_id, "conversation_id": self.conversation_id,
                "correlation_id": self.correlation_id, **self.draft.to_payload(),
                "created_at": self.created_at.isoformat()}


__all__ = [
    "MAX_REFS", "MAX_SUBJECT_CHARS", "PROVIDER_OF_REF", "UiIntent", "UiIntentDraft", "UiIntentKind", "UiIntentRef",
    "UiIntentRefKind", "UiIntentTiming",
]
