"""Profils de personnalisation : des jeux nommés de réglages réels, dont un seul est actif.

Un profil ne porte que ce que JARVIS sait déjà appliquer : les préférences de
réponse (`agent_behavior` : verbosité, formalité, instructions personnalisées)
et la voix de chaque pile vocale (`voice_stack_settings.<pile>.voice`). Il n'a
pas de valeur à lui : **le profil actif, ce sont les réglages en vigueur**. Les
autres profils gardent l'instantané pris au moment où on les a quittés ;
choisir un profil recopie son instantané dans les réglages, après avoir
recopié les réglages en vigueur dans le profil qu'on quitte.

Bloc `personalization_profiles` de `control-center-settings.json` :
`{"schema_version": 1, "active": id, "profiles": [{id, name, accent, values}]}`.
Absent ou illisible, il vaut un seul profil implicite, « Jarvis Classique »,
fait des réglages en vigueur ; rien n'est écrit en lisant. La première action
(choisir, créer, supprimer) l'écrit.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from jarvis.runtime import agent_behavior, voice_stack

SETTING_KEY = "personalization_profiles"
SCHEMA_VERSION = 1
MAX_PROFILES = 12
MAX_NAME_CHARS = 40
#: Teintes d'avatar, de la présentation seulement.
ACCENTS = ("blue", "violet", "amber", "teal", "rose")
DEFAULT_ID = "classic"
DEFAULT_NAME = "Jarvis Classique"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


class ProfileError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _voice_fields() -> dict[str, tuple[str, ...]]:
    """Les piles qui ont une voix, et leurs voix acceptées (catalogue de `voice_stack`)."""

    out: dict[str, tuple[str, ...]] = {}
    for spec in voice_stack.VOICE_STACKS:
        for field in spec.fields:
            if field.key == "voice" and field.options:
                out[spec.id] = tuple(field.options)
    return out


def capture(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Les réglages en vigueur que porte un profil."""

    voices = {stack: str(voice_stack.settings_for(dict(settings), stack).get("voice") or "")
              for stack in _voice_fields()}
    return {"behavior": agent_behavior.load(settings).as_dict(), "voices": voices}


def _clean_values(raw: object, fallback: dict[str, Any]) -> dict[str, Any]:
    """Instantané lu tolérant : chaque valeur inconnue ou abîmée retombe sur la valeur en vigueur."""

    raw = raw if isinstance(raw, Mapping) else {}
    behavior = agent_behavior.load({agent_behavior.SETTING_KEY: raw.get("behavior")}).as_dict()
    if not isinstance(raw.get("behavior"), Mapping):
        behavior = dict(fallback["behavior"])
    stored_voices = raw.get("voices") if isinstance(raw.get("voices"), Mapping) else {}
    voices = {}
    for stack, options in _voice_fields().items():
        voice = stored_voices.get(stack)
        voices[stack] = voice if isinstance(voice, str) and voice in options else fallback["voices"].get(stack, "")
    return {"behavior": behavior, "voices": voices}


def _load(settings: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], bool]:
    """`(actif, profils, enregistré)`. Le profil actif reçoit toujours les réglages en vigueur."""

    live = capture(settings)
    block = settings.get(SETTING_KEY)
    profiles: list[dict[str, Any]] = []
    if isinstance(block, Mapping) and block.get("schema_version") == SCHEMA_VERSION:
        seen: set[str] = set()
        for item in block.get("profiles") or ():
            if not isinstance(item, Mapping):
                continue
            pid, name = item.get("id"), item.get("name")
            if not (isinstance(pid, str) and _ID_RE.match(pid)) or pid in seen:
                continue
            if not isinstance(name, str) or not name.strip():
                continue
            seen.add(pid)
            accent = item.get("accent") if item.get("accent") in ACCENTS else ACCENTS[0]
            profiles.append({"id": pid, "name": name.strip()[:MAX_NAME_CHARS], "accent": accent,
                             "values": _clean_values(item.get("values"), live)})
    if not profiles:
        return DEFAULT_ID, [{"id": DEFAULT_ID, "name": DEFAULT_NAME, "accent": ACCENTS[0], "values": live}], False
    active = block.get("active") if isinstance(block, Mapping) else None
    if active not in {p["id"] for p in profiles}:
        active = profiles[0]["id"]
    for profile in profiles:
        if profile["id"] == active:
            profile["values"] = live
    return active, profiles, True


def _store(settings: dict[str, Any], active: str, profiles: list[dict[str, Any]]) -> None:
    settings[SETTING_KEY] = {"schema_version": SCHEMA_VERSION, "active": active, "profiles": profiles}


def _apply_values(settings: dict[str, Any], values: Mapping[str, Any]) -> bool:
    """Recopier un instantané dans les réglages ; rend vrai si une voix a changé (Voice la relit au démarrage)."""

    agent_behavior.apply(settings, values["behavior"])
    changed = False
    for stack, voice in values["voices"].items():
        if voice and voice_stack.settings_for(settings, stack).get("voice") != voice:
            voice_stack.store_for(settings, stack, {"voice": voice})
            changed = True
    return changed


def _slug(name: str, taken: set[str]) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:40] or "profil"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def select(settings: dict[str, Any], profile_id: object) -> bool:
    """Rendre `profile_id` actif ; rend vrai si la voix change (redémarrage de Voice pour l'entendre)."""

    active, profiles, _stored = _load(settings)
    target = next((p for p in profiles if p["id"] == profile_id), None)
    if target is None:
        raise ProfileError("personalization_profile_unknown", "Ce profil n'existe plus.")
    if target["id"] == active:
        _store(settings, active, profiles)
        return False
    voice_changed = _apply_values(settings, target["values"])
    _store(settings, target["id"], profiles)
    return voice_changed


def create(settings: dict[str, Any], name: object, accent: object = None) -> str:
    """Nouveau profil fait des réglages en vigueur, aussitôt actif. Rend son identifiant."""

    _active, profiles, _stored = _load(settings)
    clean = " ".join(name.split()) if isinstance(name, str) else ""
    if not clean or len(clean) > MAX_NAME_CHARS:
        raise ProfileError("personalization_profile_invalid_name",
                           f"Donnez au profil un nom de 1 à {MAX_NAME_CHARS} caractères.")
    if any(p["name"].casefold() == clean.casefold() for p in profiles):
        raise ProfileError("personalization_profile_duplicate", f"Un profil s'appelle déjà « {clean} ».")
    if len(profiles) >= MAX_PROFILES:
        raise ProfileError("personalization_profile_limit", f"{MAX_PROFILES} profils au plus.")
    if accent is None:
        accent = ACCENTS[len(profiles) % len(ACCENTS)]
    if accent not in ACCENTS:
        raise ProfileError("personalization_profile_invalid_accent", "Teinte de profil inconnue.")
    pid = _slug(clean, {p["id"] for p in profiles})
    profiles.append({"id": pid, "name": clean, "accent": accent, "values": capture(settings)})
    _store(settings, pid, profiles)
    return pid


def delete(settings: dict[str, Any], profile_id: object) -> None:
    active, profiles, _stored = _load(settings)
    if profile_id == active:
        raise ProfileError("personalization_profile_active",
                           "Le profil actif ne se supprime pas : choisissez-en un autre d'abord.")
    remaining = [p for p in profiles if p["id"] != profile_id]
    if len(remaining) == len(profiles):
        raise ProfileError("personalization_profile_unknown", "Ce profil n'existe plus.")
    _store(settings, active, remaining)


def describe(settings: Mapping[str, Any]) -> dict[str, Any]:
    active, profiles, stored = _load(settings)
    return {
        "active": active,
        "stored": stored,
        "max_profiles": MAX_PROFILES,
        "max_name_chars": MAX_NAME_CHARS,
        "accents": list(ACCENTS),
        "profiles": [{"id": p["id"], "name": p["name"], "accent": p["accent"], "active": p["id"] == active,
                      "values": p["values"]} for p in profiles],
    }
