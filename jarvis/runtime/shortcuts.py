"""Registre des raccourcis clavier réellement branchés.

Ne figure ici que ce qui fait quelque chose. Un raccourci listé mais inerte
est pire qu'un raccourci absent : on l'essaie, il ne répond pas, et on croit
que le réglage est cassé.

Deux portées, et elles n'obéissent pas aux mêmes règles :

* `global` — capté par pynput dans le processus Voice, même quand JARVIS n'a
  pas le focus. `KeyboardWakeWordBackend` ne sait résoudre qu'une **touche
  seule**, pas une combinaison : `ctrl+j` est donc refusé ici, plutôt que
  d'être accepté puis ignoré au démarrage.
* `ui` — capté par le Control Center dans le navigateur, où les combinaisons
  avec modificateurs sont possibles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Touches nommées que pynput sait résoudre et qui ne se déclenchent pas toutes
# seules. Les modificateurs purs (ctrl, shift, alt) en sont volontairement
# absents : ils sont enfoncés en permanence pendant l'usage normal du clavier.
GLOBAL_NAMED_KEYS: tuple[str, ...] = (
    *(f"f{n}" for n in range(1, 21)),
    "home", "end", "insert", "delete", "page_up", "page_down",
    "up", "down", "left", "right", "pause", "scroll_lock", "menu", "print_screen",
    "media_play_pause", "media_next", "media_previous",
)

UI_MODIFIERS: tuple[str, ...] = ("ctrl", "alt", "shift", "meta")

# Touches acceptées dans un raccourci d'interface, en plus des caractères
# imprimables uniques. Les noms suivent `KeyboardEvent.key`.
UI_NAMED_KEYS: tuple[str, ...] = (
    *(f"F{n}" for n in range(1, 13)),
    "Escape", "Enter", "Tab", "Backspace", "Delete", "Insert",
    "Home", "End", "PageUp", "PageDown",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space",
)


class ShortcutError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ShortcutSpec:
    id: str
    label: str
    scope: str
    default: str
    description: str
    # Clé de réglage historique, quand le raccourci en avait déjà une.
    settings_key: str = ""

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "scope": self.scope,
            "default": self.default,
            "description": self.description,
        }


SHORTCUTS: tuple[ShortcutSpec, ...] = (
    ShortcutSpec(
        id="wake_toggle",
        label="Réveiller / envoyer / interrompre",
        scope="global",
        default="f9",
        description="Touche système, active même quand JARVIS n'a pas le focus. En fin de tour "
        "automatique elle ne sert plus qu'à interrompre ; en fin de tour manuelle, le "
        "deuxième appui envoie. Une touche seule, sans modificateur.",
        settings_key="manual_wake_key",
    ),
    ShortcutSpec(
        id="ui_settings",
        label="Ouvrir les réglages",
        scope="ui",
        default="s",
        description="Ouvre la fenêtre de réglages depuis le Control Center.",
    ),
    ShortcutSpec(
        id="ui_close",
        label="Fermer la fenêtre ou le panneau",
        scope="ui",
        default="Escape",
        description="Ferme les réglages, sinon le panneau latéral ouvert.",
    ),
    ShortcutSpec(
        id="ui_panel_errors",
        label="Panneau Erreurs",
        scope="ui",
        default="e",
        description="Affiche ou masque le panneau ERR.",
    ),
    ShortcutSpec(
        id="ui_panel_trace",
        label="Panneau Trace",
        scope="ui",
        default="t",
        description="Affiche ou masque le panneau TRC.",
    ),
    ShortcutSpec(
        id="ui_panel_agents",
        label="Panneau Agents",
        scope="ui",
        default="a",
        description="Affiche ou masque le panneau AGT.",
    ),
    ShortcutSpec(
        id="ui_tab_next",
        label="Onglet de réglages suivant",
        scope="ui",
        default="ctrl+ArrowRight",
        description="Dans la fenêtre de réglages, passe à l'onglet suivant.",
    ),
    ShortcutSpec(
        id="ui_tab_prev",
        label="Onglet de réglages précédent",
        scope="ui",
        default="ctrl+ArrowLeft",
        description="Dans la fenêtre de réglages, revient à l'onglet précédent.",
    ),
)

SHORTCUT_IDS: tuple[str, ...] = tuple(spec.id for spec in SHORTCUTS)
_BY_ID: dict[str, ShortcutSpec] = {spec.id: spec for spec in SHORTCUTS}


def normalize_global(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key:
        raise ShortcutError("shortcut_empty", "Aucune touche n'a été saisie.")
    if "+" in key:
        raise ShortcutError(
            "shortcut_global_no_modifier",
            "Un raccourci système JARVIS est une touche seule : les combinaisons ne sont pas "
            "captées par le détecteur de réveil.",
        )
    if key in GLOBAL_NAMED_KEYS or len(key) == 1:
        return key
    raise ShortcutError(
        "shortcut_global_unsupported",
        f"« {key} » n'est pas une touche que le détecteur de réveil sait résoudre.",
    )


def normalize_ui(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ShortcutError("shortcut_empty", "Aucune touche n'a été saisie.")
    parts = [part.strip() for part in raw.split("+") if part.strip()]
    if not parts:
        raise ShortcutError("shortcut_empty", "Aucune touche n'a été saisie.")
    key = parts[-1]
    modifiers = [part.lower() for part in parts[:-1]]
    for modifier in modifiers:
        if modifier not in UI_MODIFIERS:
            raise ShortcutError("shortcut_unknown_modifier", f"Modificateur inconnu : {modifier}.")
    if len(modifiers) != len(set(modifiers)):
        raise ShortcutError("shortcut_duplicate_modifier", "Un modificateur est répété.")
    if key not in UI_NAMED_KEYS and len(key) != 1:
        raise ShortcutError("shortcut_unknown_key", f"« {key} » n'est pas une touche reconnue.")
    ordered = [name for name in UI_MODIFIERS if name in modifiers]
    normalized_key = key if key in UI_NAMED_KEYS else key.lower()
    return "+".join([*ordered, normalized_key])


def normalize(spec: ShortcutSpec, value: object) -> str:
    return normalize_global(value) if spec.scope == "global" else normalize_ui(value)


def current(settings: dict[str, Any]) -> dict[str, str]:
    """Raccourcis effectifs : défauts, puis ce qui est enregistré s'il est valide."""
    stored = settings.get("shortcuts")
    stored = stored if isinstance(stored, dict) else {}
    out: dict[str, str] = {}
    for spec in SHORTCUTS:
        value = stored.get(spec.id)
        if value is None and spec.settings_key:
            value = settings.get(spec.settings_key)
        try:
            out[spec.id] = normalize(spec, value) if value else spec.default
        except ShortcutError:
            # Un réglage devenu invalide (touche retirée d'une version de
            # pynput, par exemple) ne doit pas empêcher l'interface de s'ouvrir.
            out[spec.id] = spec.default
    return out


def describe(settings: dict[str, Any]) -> dict[str, Any]:
    values = current(settings)
    return {
        "shortcuts": [{**spec.describe(), "value": values[spec.id]} for spec in SHORTCUTS],
        "values": values,
        "ui_modifiers": list(UI_MODIFIERS),
    }


def apply(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
    """Valider un lot de raccourcis, refuser les collisions, puis enregistrer.

    Deux actions sur la même touche dans la même portée sont indétectables à
    l'usage : la seconde ne se déclenche jamais et rien ne le dit.
    """
    values = current(settings)
    for key, raw in payload.items():
        spec = _BY_ID.get(str(key))
        if spec is None:
            raise ShortcutError("shortcut_unknown", f"Raccourci inconnu : {key}.")
        values[spec.id] = normalize(spec, raw)

    seen: dict[tuple[str, str], str] = {}
    for spec in SHORTCUTS:
        signature = (spec.scope, values[spec.id].lower())
        if signature in seen:
            raise ShortcutError(
                "shortcut_conflict",
                f"« {values[spec.id]} » est déjà utilisé par « {_BY_ID[seen[signature]].label} ».",
            )
        seen[signature] = spec.id

    settings["shortcuts"] = values
    # La touche de réveil garde son ancienne clé : le processus Voice et le
    # bandeau d'état la lisent encore sous ce nom.
    settings["manual_wake_key"] = values["wake_toggle"]
    return values
