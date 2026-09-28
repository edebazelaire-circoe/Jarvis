"""Préférence de mode d'interaction : sa clé, son schéma, sa lecture tolérante.

Le Control Center possède la **persistance** de ce que l'utilisateur a choisi.
Core possède la valeur **effective vivante** (`jarvis/core/interaction_mode.py`).
Ce module est la frontière entre les deux : il lit et écrit un bloc, il ne
décide d'aucun comportement.

Forme reprise de `barehands_test_mode` et de `scene_settings` : ``SETTING_KEY``,
une lecture **tolérante** (``load``), une écriture **stricte** (``apply``, qui
lève avec un ``code`` stable repris dans l'en-tête ``X-Jarvis-Error-Code``) et
un ``describe``.

**Sa propre clé et son propre chemin d'écriture** (constat G1 de la Slice 00).
`ControlCenter._apply_voice` est une alternative à trois branches mutuellement
exclusives (`brain_compatibility` / `architecture` / `arch`) dont la première
*supprime* ``voice_architecture``. Un axe neuf qui passerait par là hériterait
de cette exclusion : choisir « cerveau continu » effacerait le mode. Le mode
n'entre donc ni dans ``voice``, ni dans ``/api/settings`` ; il a sa route, comme
Bare Hands et les raccourcis, et il s'applique à chaud sans revalider la voix.

**Et jamais une clé où une valeur d'architecture pourrait atterrir** (Slice 01).
``VoiceArchitectureId.SIMPLE.name`` vaut ``"SIMPLE"``, qui est aussi
``InteractionMode.ASSISTANT.label``. Le mode est donc rangé dans un bloc à lui,
lu par la porte des **valeurs** (`parse_interaction_mode`, qui refuse `simple`),
jamais par la porte des étiquettes, et jamais dans un champ partagé avec la voix.
"""

from __future__ import annotations

from typing import Any, Mapping

from jarvis.core.interaction_mode import supported_modes
from jarvis.domain.interaction_mode import (
    DEFAULT_INTERACTION_MODE,
    InteractionMode,
    InteractionModeError,
    behaving_interaction_mode,
    ensure_activatable,
    parse_interaction_mode,
    stored_interaction_mode,
)


#: Bloc de réglages, à la racine de ``runtime/control-center-settings.json``.
#: Absent : mode assistant, c'est-à-dire le comportement d'avant cette
#: fonctionnalité (Décision 14).
SETTING_KEY = "interaction_mode"

#: Version du schéma que **ce serveur écrit**. Le pendant JS n'existe pas
#: encore : la Slice 03 dessine le sélecteur et lira `schema_version` dans
#: `GET /api/interaction-mode`. Élargir ce bloc, c'est monter ce numéro dans le
#: même changement — un producteur et un consommateur qui ne partagent pas ce
#: nombre ne partagent pas ce contrat.
SCHEMA_VERSION = 1

#: Clé de version dans le bloc et dans la charge utile.
SCHEMA_KEY = "schema_version"

#: Clé de la valeur interne du mode (`assistant` / `presentation` / `meeting`),
#: jamais de son étiquette.
MODE_KEY = "mode"


class InteractionModeSettingsError(ValueError):
    """Refus d'écriture, avec un code stable. Même convention que ses voisins."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _stored_version(stored: Mapping[str, Any]) -> int:
    """Version du bloc enregistré. Absente = « écrit par nous »."""

    raw = stored.get(SCHEMA_KEY)
    if raw is None:
        return SCHEMA_VERSION
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def inspect(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que le bloc dit de lui-même, **avant** toute tolérance.

    ``load`` répond « voici le mode qui s'applique » et ne peut donc pas
    distinguer « le défaut parce qu'il n'y avait rien » de « le défaut parce
    que ce qu'il y avait était illisible ». Les deux se ressemblent à l'octet
    près : le premier est un premier lancement, le second est une perte. C'est
    cette fonction qui les sépare et ``describe`` qui la publie.

    ``stored_value`` rend la valeur brute telle quelle : un bloc qu'on ne sait
    pas appliquer n'est pas archivé — il n'y a qu'un mot à reperdre, contre un
    mécanisme d'archivage entier à maintenir — mais il reste **dit**, à l'écran
    et dans le journal, au lieu de disparaître sans un mot.
    """

    stored = settings.get(SETTING_KEY)
    present = isinstance(stored, Mapping)
    version = _stored_version(stored) if present else None
    raw = stored.get(MODE_KEY) if present else None
    unreadable = present and version != SCHEMA_VERSION
    return {
        "present": present,
        "stored_schema_version": version,
        "unreadable": unreadable,
        "stored_value": raw if isinstance(raw, str) else None,
        # Vrai quand le bloc est lisible mais que sa valeur n'est pas un mode.
        "invalid_value": bool(present and not unreadable and parse_interaction_mode(raw) is None),
    }


def load(settings: Mapping[str, Any]) -> InteractionMode:
    """Le mode **choisi**, pour l'affichage. Ne lève jamais, `meeting` survit.

    C'est la lecture `stored_interaction_mode` de la Slice 01 : ce que
    l'utilisateur a demandé, y compris un mode réservé qu'une interface doit
    continuer à montrer coché (Décision 02). Manquant, mal typé, inconnu, écrit
    par une version inconnue : le mode assistant.

    Pour savoir quel comportement tourne, c'est `behaving()` — ou, mieux, la
    valeur effective que Core publie.
    """

    stored = settings.get(SETTING_KEY)
    if not isinstance(stored, Mapping) or _stored_version(stored) != SCHEMA_VERSION:
        return DEFAULT_INTERACTION_MODE
    return stored_interaction_mode(stored.get(MODE_KEY))


def behaving(settings: Mapping[str, Any]) -> InteractionMode:
    """Le mode dont le comportement tournerait, Core injoignable compris.

    Complément de `load` : un ``meeting`` enregistré reste affiché par `load`
    mais ne produit ici que le comportement assistant. Ne jamais alimenter un
    affichage avec ceci — ce serait faire disparaître ``REUNION`` de l'écran,
    ce que la Décision 02 interdit.
    """

    return behaving_interaction_mode(load(settings))


def apply(settings: dict[str, Any], payload: Any) -> InteractionMode:
    """Valider puis ranger la préférence dans ``settings`` (sans écrire le fichier).

    Écriture **stricte**, parce que quelqu'un vient de cliquer : chaque refus
    porte un code stable, et aucun ne retombe en silence sur le défaut.

    - charge utile qui n'est pas un objet : ``interaction_mode_bad_payload`` ;
    - ``mode`` absent : ``interaction_mode_missing`` ;
    - valeur qui n'est pas un mode : ``interaction_mode_unknown`` ;
    - version de schéma étrangère : ``interaction_mode_schema_version_unsupported`` ;
    - ``REUNION`` : ``interaction_mode_not_implemented``, dit par
      `ensure_activatable` (Slice 01) avec son message français.
    """

    if not isinstance(payload, Mapping):
        raise InteractionModeSettingsError(
            "interaction_mode_bad_payload", "Le mode d'interaction attend un objet JSON."
        )
    unknown = set(payload) - {MODE_KEY, SCHEMA_KEY}
    if unknown:
        raise InteractionModeSettingsError(
            "interaction_mode_unknown_field",
            f"Champ inconnu : {', '.join(sorted(map(str, unknown)))}.",
        )
    version = payload.get(SCHEMA_KEY)
    if version is not None and version != SCHEMA_VERSION:
        raise InteractionModeSettingsError(
            "interaction_mode_schema_version_unsupported",
            f"Mode d'interaction en version {version!r} ; ce serveur n'écrit que la version {SCHEMA_VERSION}.",
        )
    if MODE_KEY not in payload:
        raise InteractionModeSettingsError(
            "interaction_mode_missing", "Précisez « mode » (assistant, presentation ou meeting)."
        )
    raw = payload[MODE_KEY]
    mode = parse_interaction_mode(raw)
    if mode is None:
        raise InteractionModeSettingsError(
            "interaction_mode_unknown",
            f"Mode d'interaction inconnu : {raw!r}. Valeurs acceptées : "
            + ", ".join(f"« {value.value} »" for value in InteractionMode)
            + ".",
        )
    try:
        ensure_activatable(mode)
    except InteractionModeError as exc:
        # Le code reste celui de la Slice 01 : c'est lui que l'écran, les
        # tests et Core comparent. Retyper ici en créerait un second pour le
        # même refus.
        raise InteractionModeSettingsError(exc.code, str(exc)) from exc
    settings[SETTING_KEY] = {SCHEMA_KEY: SCHEMA_VERSION, MODE_KEY: mode.value}
    return mode


def describe(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que rendent `GET /api/interaction-mode` et la charge utile des réglages.

    ``mode`` est la **préférence** (lecture d'affichage, ``meeting`` compris) ;
    ``behaving`` est ce qui tournerait si Core rejouait ce réglage tel quel.
    Les deux sont nommés, parce que choisir le mauvais lecteur fait disparaître
    ``REUNION`` de l'interface — exactement ce que la Décision 02 empêche.

    ``unreadable`` et ``stored_value`` séparent « le défaut parce que neuf » de
    « le défaut parce qu'illisible ».
    """

    seen = inspect(settings)
    mode = load(settings)
    return {
        "mode": mode.value,
        "label": mode.label,
        "behaving": behaving(settings).value,
        "schema_version": SCHEMA_VERSION,
        "stored_schema_version": seen["stored_schema_version"],
        "unreadable": seen["unreadable"],
        "invalid_value": seen["invalid_value"],
        "stored_value": seen["stored_value"],
        "modes": supported_modes(),
    }
