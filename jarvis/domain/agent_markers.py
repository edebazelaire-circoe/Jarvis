"""La grammaire des marqueurs de tête d'un appel `Agent` : profil, rôle, éphémère.

Le cerveau ne peut pas ajouter de paramètre à l'outil `Agent` du CLI : il
déclare ce que Jarvis doit savoir d'un sous-agent par des marqueurs entre
crochets en tête de la `description` (`[code] [coder] Corriger le bug`,
`[éphémère] Liste des tâches`). Deux lecteurs relisent ces marqueurs :

- le hook `PreToolUse` (`jarvis/runtime/routing_hook.py`), avant le lancement,
  pour choisir le modèle, le loadout et la méthode du rôle ;
- le suivi des tâches (`jarvis/runtime/agent_tasks.py`), sur le flux
  `stream-json`, pour le libellé et le drapeau éphémère.

Ce module est **la** grammaire, et les deux lecteurs l'appellent (I-005 du
handoff jarvis-organic-agent-orchestration : chacun avait la sienne, et
`[éphémère] [code] [coder] …` perdait le rôle d'un côté tandis que
`[code] [coder] [éphémère] …` perdait le drapeau de l'autre).

Grammaire (contrat : `docs/subagent-roles.md`, « Marqueurs de tête ») :

- la tête est la suite des groupes entre crochets au début du texte (après les
  blancs de bord), au plus `MAX_HEAD_MARKERS` ;
- un groupe ASCII `[mot]` (`[A-Za-z_-]{2,24}`, blancs internes tolérés) est un
  mot de marqueur ;
- le marqueur éphémère `[éphémère]` est un jeton exact (minuscules, accents,
  sans blanc interne) suivi d'au moins un espace ou une tabulation. Il peut
  occuper n'importe quelle place de la tête, une seule fois, et il est
  transparent : il est retiré, et les mots restants se lisent comme s'il
  n'avait jamais été là. Il ne compte que si un texte non vide reste après son
  retrait ;
- sur les mots : le premier est toujours consommé (profil connu ou non) ; s'il
  nomme un rôle annoncé, c'est le rôle et le profil reste `general` ; s'il
  nomme un profil, le second mot est consommé s'il nomme un rôle annoncé (ou un
  rôle de production passé par `extra_consumed`), sinon il reste dans le
  libellé ;
- tout le reste — casse ou accents différents, marqueur collé au libellé,
  deux marqueurs éphémères, marqueur hors de la tête — ne déclare rien et
  laisse le texte intact : l'échec est du côté sûr, une tâche ordinaire.

Le drapeau éphémère ne se lit que sur la `description` ; le repli sur la clé
`prompt` (historique du hook) ne vaut que pour le profil et le rôle.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from jarvis.domain import routing
from jarvis.domain.memory_settings import LOADOUT_ROLES
from jarvis.domain.subagent_roles import ROLE_ALIASES, ROLE_MARKERS, RoleResolution, resolve_role

#: Marqueur de tâche éphémère : jeton exact, voir la grammaire du module.
EPHEMERAL_MARKER = "[éphémère]"

#: Groupes lus en tête : trois mots (profil, rôle, rôle de production) et le marqueur éphémère.
MAX_HEAD_MARKERS = 4
MAX_HEAD_WORDS = 3

#: Un mot de marqueur : ASCII, 2 à 24 caractères. Les marqueurs de rôle (`subagent_roles`) y tiennent.
WORD_PATTERN = r"[A-Za-z_-]{2,24}"
_WORD = re.compile(r"\[\s*(" + WORD_PATTERN + r")\s*\]\s*")
_EPHEMERAL = re.compile(re.escape(EPHEMERAL_MARKER) + r"[ \t]+")

#: Les rôles qu'une description peut annoncer : ceux du loadout (`memory_settings.LOADOUT_ROLES`), ceux du
#: registre des sous-agents (`subagent_roles.ROLE_MARKERS`) et leurs alias de compatibilité.
ANNOUNCED_ROLES: tuple[str, ...] = tuple(dict.fromkeys((*LOADOUT_ROLES, *ROLE_MARKERS, *ROLE_ALIASES)))


@dataclass(frozen=True, slots=True)
class HeadMarkers:
    """Ce que la tête d'un texte déclare. Toutes les positions se rapportent au texte reçu (`raw`).

    - `words` : les mots de marqueur ASCII de la tête, en minuscules, dans l'ordre, éphémère exclu ;
    - `profile` : le profil annoncé, ou `None` (le hook prend alors `general` ou se rabat sur `prompt`) ;
    - `role` : le marqueur de rôle annoncé, tel qu'écrit (`reviewer` reste `reviewer`), ou `None` ;
    - `ephemeral` : le marqueur éphémère est déclaré, bien formé ;
    - `description` : le texte sans le marqueur éphémère (les autres marqueurs restent), borné par `strip` ;
    - `label` : le texte sans aucun marqueur consommé, ce que l'utilisateur lit ;
    - `head_end` : fin, dans `raw`, des marqueurs consommés (éphémère compris s'il est dans cette tête).
    """

    raw: str
    words: tuple[str, ...]
    profile: str | None
    role: str | None
    ephemeral: bool
    description: str
    label: str
    head_end: int


def parse_head(text: object, *, extra_consumed: Iterable[str] = ()) -> HeadMarkers:
    """Lire la tête de `text` selon la grammaire du module. Ne lève jamais."""

    raw = str(text or "")
    pos = len(raw) - len(raw.lstrip())
    words: list[tuple[str, int, int]] = []  # (mot, début, fin) dans `raw`
    ephemeral_spans: list[tuple[int, int]] = []
    while len(words) + len(ephemeral_spans) < MAX_HEAD_MARKERS:
        found = _EPHEMERAL.match(raw, pos)
        if found is not None:
            ephemeral_spans.append((pos, found.end()))
            pos = found.end()
            continue
        if len(words) >= MAX_HEAD_WORDS:
            break
        found = _WORD.match(raw, pos)
        if found is None:
            break
        words.append((found.group(1).strip().lower(), pos, found.end()))
        pos = found.end()

    # Éphémère : exactement un marqueur, et un texte non vide après son retrait. Sinon, rien n'est retiré.
    span = ephemeral_spans[0] if len(ephemeral_spans) == 1 else None
    clean = raw if span is None else raw[:span[0]] + raw[span[1]:]
    if span is not None and not clean.strip():
        span, clean = None, raw
    if len(ephemeral_spans) > 1:
        # Deux marqueurs : mal formé. Le texte reste intact et sa tête s'arrête au premier marqueur.
        words = [word for word in words if word[1] < ephemeral_spans[0][0]]

    consumed, profile, role = _interpret([word for word, _start, _end in words], frozenset(extra_consumed))
    head_end = words[consumed - 1][2] if consumed else (len(raw) - len(raw.lstrip()))
    # Le marqueur éphémère appartient à la tête consommée s'il précède ou suit directement ses mots.
    if span is not None and sum(1 for word in words if word[1] < span[0]) <= consumed:
        head_end = max(head_end, span[1])
    # Dans `clean`, la tête consommée a perdu la longueur du marqueur s'il en faisait partie.
    inside = span is not None and span[1] <= head_end
    label_start = head_end - (span[1] - span[0]) if inside else head_end
    return HeadMarkers(
        raw=raw,
        words=tuple(word for word, _start, _end in words),
        profile=profile,
        role=role,
        ephemeral=span is not None,
        description=clean.strip(),
        label=clean[label_start:].strip(),
        head_end=head_end,
    )


def _interpret(words: list[str], extra: frozenset[str]) -> tuple[int, str | None, str | None]:
    """(mots consommés, profil, rôle) : la règle historique du hook, inchangée."""

    if not words:
        return 0, None, None
    first = words[0]
    if first in ANNOUNCED_ROLES:
        return 1, None, first
    if routing.is_profile(first) and len(words) > 1:
        second = words[1]
        if second in ANNOUNCED_ROLES:
            return 2, first, second
        if second in extra:  # consommé pour l'affichage, sans rôle
            return 2, first, None
    return 1, (first if routing.is_profile(first) else None), None


def parse_ephemeral_description(description: object) -> tuple[str, bool]:
    """`(description sans le marqueur éphémère, drapeau)`. Forme historique du suivi des tâches."""

    head = parse_head(description)
    return head.description, head.ephemeral


# ------------------------------------------------------------- déclaration


@dataclass(frozen=True, slots=True)
class AgentDeclaration:
    """Ce que le cerveau déclare d'un sous-agent dans un appel `Agent`, résolu contre le registre.

    Forme stable destinée à voyager vers Core (arbitrage D25 : le hook `PreToolUse` est la source du rôle et
    de l'éphémère transmis à Core ; le câblage relève des Slices 03 et 05). `role` porte l'id canonique
    (`reviewer` → `qa`) et la provenance ; `tool_use_id` et `caller_agent_id` sont ceux de l'événement du
    hook quand il est fourni (`caller_agent_id` n'existe que pour un appel imbriqué).
    """

    profile: str
    role: RoleResolution
    ephemeral: bool
    label: str
    tool_use_id: str | None = None
    caller_agent_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            **self.role.to_payload(),
            "ephemeral": self.ephemeral,
            "label": self.label,
            "tool_use_id": self.tool_use_id,
            "caller_agent_id": self.caller_agent_id,
        }


def _fields(tool_input: Mapping[str, Any], key: str) -> str:
    return str(tool_input.get(key) or "")


def read_profile(tool_input: Mapping[str, Any]) -> str:
    """Le profil annoncé (`description`, sinon `prompt`), ou `general`."""

    for key in ("description", "prompt"):
        profile = parse_head(_fields(tool_input, key)).profile
        if profile is not None:
            return profile
    return routing.GENERAL_PROFILE


def read_role(tool_input: Mapping[str, Any]) -> str | None:
    """Le marqueur de rôle annoncé (`description`, sinon `prompt`), tel qu'écrit, ou `None`."""

    for key in ("description", "prompt"):
        role = parse_head(_fields(tool_input, key)).role
        if role is not None:
            return role
    return None


def declaration_from_tool_input(
    tool_input: Mapping[str, Any], *, tool_use_id: str | None = None, caller_agent_id: str | None = None,
) -> AgentDeclaration:
    """La déclaration d'un appel `Agent` : mêmes lectures que le hook et le suivi des tâches."""

    description = parse_head(_fields(tool_input, "description"))
    return AgentDeclaration(
        profile=read_profile(tool_input),
        role=resolve_role(read_role(tool_input)),
        ephemeral=description.ephemeral,
        label=description.label,
        tool_use_id=tool_use_id or None,
        caller_agent_id=caller_agent_id or None,
    )


def declaration_from_hook_event(event: Mapping[str, Any]) -> AgentDeclaration:
    """La déclaration portée par un événement `PreToolUse` (`tool_input`, `tool_use_id`, `agent_id`)."""

    tool_input = event.get("tool_input")
    tool_use_id = event.get("tool_use_id")
    agent_id = event.get("agent_id")
    return declaration_from_tool_input(
        tool_input if isinstance(tool_input, Mapping) else {},
        tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
        caller_agent_id=agent_id if isinstance(agent_id, str) else None,
    )
