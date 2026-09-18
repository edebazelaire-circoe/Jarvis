"""Provider-neutral decision to remain silent or permit one useful preamble."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata


class ReflexAction(StrEnum):
    WAIT = "wait"
    BACKCHANNEL = "backchannel"
    SPEAK = "speak"
    PREAMBLE = "preamble"
    DELEGATE = "delegate"


@dataclass(frozen=True, slots=True)
class ReflexDecision:
    action: ReflexAction
    reason: str


def conversational_wait_reason(text: str) -> str | None:
    normalized = "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if tokens[:1] == ["jarvis"]:
        tokens = tokens[1:]
    phrase = " ".join(tokens)
    if not tokens:
        return "no_content"
    acknowledgements = {"ok", "okay", "oui", "non", "merci", "bien", "parfait", "entendu", "super", "tres", "c", "est", "bon", "d", "accord", "ca", "marche", "tout", "a", "fait"}
    if all(token in acknowledgements for token in tokens):
        return "acknowledgement_only"
    if phrase.endswith(("attends je reflechis", "attend je reflechis", "je reflechis", "laisse moi reflechir")) or "j ai pas fini de parler" in phrase:
        return "user_continuing"
    if phrase.startswith(("je voulais dire ", "plutot ", "non pas ", "quoique non ")):
        return "correction"
    return None


def decide_reflex(*, text: str, enabled: bool, admitted: bool, user_speaking: bool,
                  useful_ready: bool, work_confirmed: bool, work_terminal: bool,
                  noticeable_wait: bool, already_used: bool, stale: bool,
                  require_work: bool = False) -> ReflexDecision:
    """No execution, prompt generation, timers or mutable conversation state.

    Le déclencheur est **temporel**, pas contractuel : le silence du cerveau
    au-delà du délai d'accusé suffit. Exiger en plus un `brain.work.started`
    corrélé (`require_work`) a rendu le réflexe muet dès que le cerveau
    répondait sans déclarer de travail de fond — c'est-à-dire presque toujours.
    `require_work=True` restaure cette porte, et n'est plus qu'un retour arrière.

    Ce que la porte évitait reste évité par les contrôles qui l'entourent, et
    qui n'ont pas bougé : `useful_ready` (le cerveau a déjà de quoi parler),
    `work_terminal` (le travail est fini, la réponse arrive), `already_used`
    (un seul préambule par tour), `noticeable_wait` (l'échéance n'est pas
    atteinte) et les motifs conversationnels ci-dessus.
    """
    checks = ((not enabled, "disabled"), (not admitted, "not_admitted"), (stale, "stale"),
              (user_speaking, "user_speaking"), (already_used, "already_used"))
    for condition, reason in checks:
        if condition:
            return ReflexDecision(ReflexAction.WAIT, reason)
    if reason := conversational_wait_reason(text):
        return ReflexDecision(ReflexAction.WAIT, reason)
    if useful_ready:
        return ReflexDecision(ReflexAction.SPEAK, "useful_content_ready")
    if work_terminal:
        return ReflexDecision(ReflexAction.WAIT, "work_terminal")
    if require_work and not work_confirmed:
        return ReflexDecision(ReflexAction.WAIT, "work_unconfirmed")
    if not noticeable_wait:
        return ReflexDecision(ReflexAction.WAIT, "answer_may_arrive_quickly")
    return ReflexDecision(ReflexAction.PREAMBLE,
                          "confirmed_work_wait" if work_confirmed else "brain_silent_wait")
