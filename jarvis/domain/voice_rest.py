"""Les deux niveaux de repos de la voix GPT-Live : IDLE puis SLEEP (`docs/voice-lifecycle.md`).

`VoiceLifecycleState` n'a qu'un état hors séance (`BACKGROUND`) et le Control
Center, Core et le canal vocal le lisent tel quel. IDLE et SLEEP sont donc deux
**niveaux de repos** de `BACKGROUND`, tenus par le processus Voice :

- **IDLE** : séance fermée (plus de coût fournisseur), micro local ouvert ; le
  mot d'éveil, la touche, la fin d'une tâche entière **et la parole de
  l'utilisateur** rouvrent une séance.
- **SLEEP** : même chose sans la parole. Plus rien ne rouvre une séance sauf le
  mot d'éveil, la touche, ou la fin d'une tâche entière.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from jarvis.domain.v2 import SpeechKind, SpeechProvenance


class RestLevel(StrEnum):
    IDLE = "idle"
    SLEEP = "sleep"


#: Message Core d'une demande de parole du cerveau (`BRAIN_SPEECH_REQUESTED`).
BRAIN_SPEECH_REQUESTED = "brain.speech.requested"


def is_task_completion_speech(message_type: object, payload: object) -> bool:
    """Cette demande de parole de Core est-elle le compte rendu d'une tâche terminée ?

    Un résultat ou une erreur durable du cerveau (genre `result` / `error`, provenance `brain`) : c'est ce
    que Core publie quand une tâche entière vient de finir (le relais de fin de
    sous-agent n'est publié qu'une fois toutes les tâches de fond rendues,
    `AgentTaskTracker.whole_task_finished`). Un accusé, une progression ou une
    parole du système (accueil) sont transitoires ou n'ont pas cette provenance :
    ils ne réveillent jamais.
    """

    if message_type != BRAIN_SPEECH_REQUESTED or not isinstance(payload, Mapping):
        return False
    kind = str(payload.get("kind") or "")
    provenance = str(payload.get("provenance") or SpeechProvenance.BRAIN.value)
    text = payload.get("text")
    return (kind in (SpeechKind.RESULT.value, SpeechKind.ERROR.value) and provenance == SpeechProvenance.BRAIN.value
            and isinstance(text, str) and bool(text.strip()))
