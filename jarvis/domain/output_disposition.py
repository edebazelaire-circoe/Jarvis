"""Comment un tour terminé se manifeste : voix, écran, les deux, ou rien.

Module séparé **volontairement**. `jarvis/domain/scene.py` définit déjà un
`Disposition{ACTIVE, ARCHIVED}` qui parle de présence dans la scène, un sujet
sans rapport. Deux `Disposition` dans le même domaine seraient un piège, donc
celui-ci s'appelle `OutputDisposition`, vit seul, et n'est jamais importé sans
son nom complet dans un module qui importe aussi celui de la scène.

Rien ici n'exécute : c'est du vocabulaire que le runtime consomme (Slices 02+).
La disposition est une **donnée du tour**, pas une consigne de prompt : un
modèle qui décide seul de se taire redevient bavard à la première reformulation,
ce que la Décision 09 refuse explicitement.
"""
from __future__ import annotations

from enum import StrEnum


class OutputDisposition(StrEnum):
    """Canaux par lesquels un tour terminé se manifeste réellement.

    `SILENT` n'est pas « raté » : c'est l'issue normale d'une observation
    ambiante (Décision 03). `VISUAL_ONLY` est l'issue normale d'une commande
    visuelle en mode présentation (Décision 09).
    """

    SILENT = "silent"
    VISUAL_ONLY = "visual_only"
    VOICE_ONLY = "voice_only"
    VISUAL_AND_VOICE = "visual_and_voice"

    @property
    def speaks(self) -> bool:
        return self in (OutputDisposition.VOICE_ONLY, OutputDisposition.VISUAL_AND_VOICE)

    @property
    def shows(self) -> bool:
        return self in (OutputDisposition.VISUAL_ONLY, OutputDisposition.VISUAL_AND_VOICE)


#: Table de vérité canonique (`shows`, `speaks`) -> disposition. Le runtime
#: compose souvent deux booléens indépendants ; les recoller par des `if`
#: imbriqués à chaque appel est exactement la duplication qui finit par
#: diverger.
_BY_CHANNELS = {
    (False, False): OutputDisposition.SILENT,
    (True, False): OutputDisposition.VISUAL_ONLY,
    (False, True): OutputDisposition.VOICE_ONLY,
    (True, True): OutputDisposition.VISUAL_AND_VOICE,
}


def output_disposition(*, shows: bool, speaks: bool) -> OutputDisposition:
    """Disposition portée par deux canaux observés. Total, sans exception."""
    return _BY_CHANNELS[(bool(shows), bool(speaks))]


def parse_output_disposition(value: object) -> OutputDisposition | None:
    """Valeur transportée -> disposition, ou `None` si elle n'en est pas une.

    Strict par construction : c'est l'appelant qui décide ce que vaut un
    inconnu, jamais ce module en silence.
    """
    if isinstance(value, OutputDisposition):
        return value
    if not isinstance(value, str):
        return None
    try:
        return OutputDisposition(value.strip().casefold())
    except ValueError:
        return None
