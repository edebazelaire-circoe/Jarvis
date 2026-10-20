"""Équivalence de la grammaire commune avec les lecteurs d'avant (main@336f21be), sur un corpus représentatif.

L'oracle ci-dessous est la copie figée des anciens lecteurs : `routing_hook.read_profile`, `_markers`,
`read_role`, `read_loadout_role`, `read_playbook_role`, `strip_profile` et
`agent_tasks.parse_ephemeral_description`, avec l'ancien `ANNOUNCED_ROLES` (loadout + cinq rôles). Il ne doit
jamais suivre le code : il fige le comportement d'avant pour prouver que seuls les écarts voulus existent.

Écarts voulus (tous liés au jeton exact `[éphémère]`) :
- le marqueur est transparent dans la tête : profil, rôle, loadout, rôle de production et libellé se lisent à
  travers lui, y compris dans la consigne ;
- le marqueur est accepté ailleurs qu'en premier dans la tête ;
- un marqueur en double, ou sans libellé après tous les marqueurs de tête, ne déclare plus rien (côté sûr).
Sans ce jeton, tout est identique, sauf l'activation voulue de `qa` et `research-lead` (Slice 04) :
- `[qa]` et `[research-lead]` sont des rôles annoncés : lus comme rôle (dans la description, sinon la consigne),
  consommés du libellé (`strip`) ;
- leur loadout est celui de leur contrat : `qa` -> `reviewer`, `research-lead` -> `research`.
Ces deux écarts sont exactement ceux de l'oracle « activé » (ancien oracle avec ces deux rôles annoncés) ; sans
ces deux marqueurs, l'ancien oracle reste exact.
"""

from __future__ import annotations

import itertools
import re

import pytest

from jarvis.domain import routing
from jarvis.runtime import agent_tasks, routing_hook
from jarvis.runtime.presentation_playbooks import PLAYBOOK_ROLES

E = "[éphémère]"

# ---------------------------------------------------------------- oracle figé (main@336f21be)

_OLD_ANNOUNCED = ("coder", "reviewer", "research", "interviewer", "web-research", "concept")
_OLD_LOADOUT = ("coder", "reviewer", "research")
_OLD_PROFILE = re.compile(r"^\s*\[\s*([A-Za-z_-]{2,24})\s*\]\s*")
_OLD_BRACKET = re.compile(r"\[\s*([A-Za-z_-]{2,24})\s*\]\s*")
_OLD_LEADING = re.compile(r"\s*\[\s*([A-Za-z_-]{2,24})\s*\]")
_OLD_EPHEMERAL = re.compile(re.escape(E) + r"[ \t]+(\S.*)", re.DOTALL)


def old_profile(ti):
    for key in ("description", "prompt"):
        match = _OLD_PROFILE.match(str(ti.get(key) or ""))
        if match is not None and routing.is_profile(match.group(1)):
            return match.group(1).strip().lower()
    return routing.GENERAL_PROFILE


#: Écart voulu de la Slice 04 : les deux rôles activés et le loadout de leur contrat.
_ACTIVATED = {"qa": "reviewer", "research-lead": "research"}


def old_markers(text, announced=_OLD_ANNOUNCED):
    first = _OLD_PROFILE.match(text)
    if first is None:
        return 0, None
    word = first.group(1).strip().lower()
    if word in announced:
        return first.end(), word
    if routing.is_profile(word):
        second = _OLD_BRACKET.match(text, first.end())
        if second is not None:
            name = second.group(1).strip().lower()
            if name in announced:
                return second.end(), name
            if name in PLAYBOOK_ROLES:
                return second.end(), None
    return first.end(), None


def old_role(ti, announced=_OLD_ANNOUNCED):
    for key in ("description", "prompt"):
        role = old_markers(str(ti.get(key) or ""), announced)[1]
        if role is not None:
            return role
    return None


def old_playbook(ti):
    for key in ("description", "prompt"):
        text, position = str(ti.get(key) or ""), 0
        for _ in range(3):
            match = _OLD_LEADING.match(text, position)
            if match is None:
                break
            word = match.group(1).strip().lower()
            if word in PLAYBOOK_ROLES:
                return word
            position = match.end()
    return None


def old_ephemeral(description):
    text = (description or "").strip()
    match = _OLD_EPHEMERAL.fullmatch(text)
    if match is None or match.group(1).startswith(E):
        return text, False
    return match.group(1).strip(), True


def old_reading(ti, *, activated=False):
    """L'ancien oracle ; `activated` y ajoute seulement l'écart voulu de la Slice 04 (`_ACTIVATED`)."""
    announced = (*_OLD_ANNOUNCED, *_ACTIVATED) if activated else _OLD_ANNOUNCED
    role = old_role(ti, announced)
    description = ti["description"]
    loadout = role if role in _OLD_LOADOUT else (_ACTIVATED.get(role) if activated else None)
    return {
        "profile": old_profile(ti),
        "role": role,
        "loadout": loadout,
        "playbook": old_playbook(ti),
        "strip": description[old_markers(description, announced)[0]:].strip(),
        "eph": old_ephemeral(description),
    }


def new_reading(ti):
    return {
        "profile": routing_hook.read_profile(ti),
        "role": routing_hook.read_role(ti),
        "loadout": routing_hook.read_loadout_role(ti),
        "playbook": routing_hook.read_playbook_role(ti),
        "strip": routing_hook.strip_profile(ti["description"]),
        "eph": agent_tasks.parse_ephemeral_description(ti["description"]),
    }


# ---------------------------------------------------------------- corpus

TOKENS = ["[code]", "[general]", "[coder]", "[reviewer]", "[research]", "[interviewer]", "[qa]", "[research-lead]",
          "[presentation-author]", "[foo]", "[ CODE ]", "[Coder]", E, "[Éphémère]", "[ephemere]"]
TAILS = ["Corriger le bug", "", "Liste [éphémère] milieu", "x\nsuite"]
PROMPTS = ["", "[code] [coder] consigne", "[éphémère] [code] [coder] consigne", "[code] [qa] consigne"]


def corpus():
    for count in range(4):
        for combo in itertools.product(TOKENS, repeat=count):
            if count == 3 and len(set(combo)) < 2:
                continue
            for sep in ((" ", "\t", "") if count <= 1 else (" ",)):
                for tail in TAILS:
                    yield sep.join(combo) + (sep if combo else "") + tail


CASES = sorted(set(corpus()))


def test_the_corpus_is_representative():
    assert len(CASES) > 10_000
    assert sum(E in case for case in CASES) > 1_000


def test_without_the_ephemeral_token_every_reader_is_unchanged():
    for description in CASES:
        if E in description:
            continue
        for prompt in PROMPTS:
            if E in prompt:
                continue
            ti = {"description": description, "prompt": prompt}
            assert new_reading(ti) == old_reading(ti, activated=True), ti
            if not any(f"[{marker}]" in text for marker in _ACTIVATED for text in (description, prompt)):
                assert new_reading(ti) == old_reading(ti), ti


def test_the_slice_04_activation_differences_are_pinned():
    # Avant : `[qa]` restait dans le libellé et la consigne donnait le rôle ; désormais il est le rôle.
    ti = {"description": "[code] [qa] Relire", "prompt": "[code] [coder] consigne"}
    assert old_reading(ti)["role"] == "coder" and old_reading(ti)["strip"] == "[qa] Relire"
    assert new_reading(ti)["role"] == "qa" and new_reading(ti)["strip"] == "Relire"
    assert (old_reading(ti)["loadout"], new_reading(ti)["loadout"]) == ("coder", "reviewer")
    ti = {"description": "[research-lead] Comparer", "prompt": ""}
    assert (old_reading(ti)["role"], new_reading(ti)["role"]) == (None, "research-lead")
    assert (old_reading(ti)["loadout"], new_reading(ti)["loadout"]) == (None, "research")
    # Le profil, le rôle de production et l'éphémère ne bougent jamais.
    for key in ("profile", "playbook", "eph"):
        assert old_reading(ti)[key] == new_reading(ti)[key]


def _only_head_markers(text):
    return re.fullmatch(r"(?:\s*\[[^\]\n]*\])*\s*", text) is not None


def test_ephemeral_differences_are_exactly_the_intended_ones():
    for description in CASES:
        old_text, old_flag = old_ephemeral(description)
        new_text, new_flag = agent_tasks.parse_ephemeral_description(description)
        if old_flag == new_flag:
            if old_flag:
                # Même déclaration : le marqueur était en tête, seul ce marqueur est retiré.
                assert new_text == old_text, description
            continue
        stripped = description.strip()
        if new_flag:
            # Gagné : le marqueur est dans la tête sans être le premier groupe.
            assert not stripped.startswith(E) and E in stripped, description
        else:
            # Perdu, côté sûr : doublon, ou rien d'autre que des marqueurs après le jeton.
            rest = stripped[len(E):]
            assert E in rest or _only_head_markers(rest), description
            assert new_text == stripped


@pytest.mark.parametrize(
    ("description", "old", "new"),
    [
        ("[code] [coder] [éphémère] Corriger", ("[code] [coder] [éphémère] Corriger", False),
         ("[code] [coder] Corriger", True)),
        ("[éphémère] [code] [éphémère] x", ("[code] [éphémère] x", True), ("[éphémère] [code] [éphémère] x", False)),
        ("[éphémère] [code]", ("[code]", True), ("[éphémère] [code]", False)),
        ("[éphémère] Liste", ("Liste", True), ("Liste", True)),
    ],
)
def test_pinned_intended_differences(description, old, new):
    assert old_ephemeral(description) == old
    assert agent_tasks.parse_ephemeral_description(description) == new
