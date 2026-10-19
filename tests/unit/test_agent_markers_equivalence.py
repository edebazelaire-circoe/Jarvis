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
Sans ce jeton, tout est identique, rôles désactivés `qa` et `research-lead` compris.
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


def old_markers(text):
    first = _OLD_PROFILE.match(text)
    if first is None:
        return 0, None
    word = first.group(1).strip().lower()
    if word in _OLD_ANNOUNCED:
        return first.end(), word
    if routing.is_profile(word):
        second = _OLD_BRACKET.match(text, first.end())
        if second is not None:
            name = second.group(1).strip().lower()
            if name in _OLD_ANNOUNCED:
                return second.end(), name
            if name in PLAYBOOK_ROLES:
                return second.end(), None
    return first.end(), None


def old_role(ti):
    for key in ("description", "prompt"):
        role = old_markers(str(ti.get(key) or ""))[1]
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


def old_reading(ti):
    role = old_role(ti)
    description = ti["description"]
    return {
        "profile": old_profile(ti),
        "role": role,
        "loadout": role if role in _OLD_LOADOUT else None,
        "playbook": old_playbook(ti),
        "strip": description[old_markers(description)[0]:].strip(),
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
            assert new_reading(ti) == old_reading(ti), ti


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
