"""Mode d'interaction produit : comment JARVIS se comporte, pas comment il est câblé.

Deux axes existent déjà dans ce dépôt et **aucun des deux n'est celui-ci** :

- l'architecture vocale, qui dit quel chemin de code tourne. Elle a elle-même
  deux représentations vivantes : `VoiceArchitectureId{SIMPLE, FRONT_BRAIN,
  DUPLEX}` (`jarvis/domain/voice_architecture.py`, clé `voice_architecture`) et
  l'ancienne `VoiceArchitecture{LEGACY, CONTINUOUS_BRAIN}` (`jarvis/v2_config.py`,
  clé `voice_arch`), qui reste l'autorité d'exécution ;
- l'autorisation conversationnelle `ConversationMode{OPEN_ROOM, SOLO_OWNER}`
  (`jarvis/domain/speaker.py`), qui dit *qui* peut constituer un tour.

Le mode d'interaction est orthogonal aux deux (Décision 01) : une présentation
doit rester une présentation quelle que soit l'architecture qui la porte.

Le piège est nominatif. L'étiquette utilisateur du mode assistant est `SIMPLE`,
et `VoiceArchitectureId.SIMPLE` existe déjà avec un sens totalement différent.
Il n'y a donc **aucun membre `SIMPLE` dans `InteractionMode`** : les valeurs
internes sont `assistant` / `presentation` / `meeting`, et `SIMPLE` n'existe que
comme étiquette d'affichage, obtenue par `label` et relue par
`parse_interaction_mode_label`. Écrire `InteractionMode.SIMPLE` lève
`AttributeError` au lieu de confondre silencieusement deux axes ; un test le
verrouille.

Contrat pur : aucune persistance, aucune API, aucune UI, aucun prompt. Le plan
de contrôle (Slice 02) et la politique de réponse (Slice 07) consomment ceci.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from jarvis.domain.output_disposition import OutputDisposition


class InteractionModeError(ValueError):
    """Refus explicite et nommé, jamais un repli silencieux."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InteractionMode(StrEnum):
    """Politique de comportement produit. Valeurs internes, jamais affichées."""

    #: Comportement assistant historique, inchangé (Décision 14). C'est le défaut.
    ASSISTANT = "assistant"
    #: JARVIS écoute une présentation en cours : silence par défaut, écran plutôt
    #: que voix, travail spéculatif sacrifiable (Décisions 03, 07, 08, 09).
    PRESENTATION = "presentation"
    #: Connu, affichable, **jamais activable** en V1 (Décision 02). Aucun
    #: comportement de réunion n'est inventé ici.
    MEETING = "meeting"

    @property
    def label(self) -> str:
        """Étiquette utilisateur verrouillée par la Décision 02."""
        return _LABELS[self]


class InteractionModeStatus(StrEnum):
    """Maturité d'un mode, dans le vocabulaire déjà utilisé par `VoiceAdapterStatus`.

    Même convention que `jarvis/domain/voice_architecture.py`, qui distingue
    déjà « documenté » de « adaptateur prêt » : un mode peut être nommé et
    présenté longtemps avant d'exister. `legacy_only` n'a pas de sens ici et
    n'est donc pas repris.
    """

    READY = "ready"
    PLANNED = "planned"


_LABELS: Mapping[InteractionMode, str] = MappingProxyType({
    InteractionMode.ASSISTANT: "SIMPLE",
    InteractionMode.PRESENTATION: "PRESENTATION",
    InteractionMode.MEETING: "REUNION",
})


@dataclass(frozen=True, slots=True)
class InteractionModeDescriptor:
    """Ce que l'interface peut afficher d'un mode sans rien savoir de son runtime."""

    mode: InteractionMode
    status: InteractionModeStatus
    default_disposition: OutputDisposition
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.mode, InteractionMode) or not isinstance(self.status, InteractionModeStatus):
            raise InteractionModeError("interaction_mode_descriptor_invalid", "Descriptor needs typed mode and status")
        if not isinstance(self.default_disposition, OutputDisposition):
            raise InteractionModeError("interaction_mode_descriptor_invalid", "Descriptor needs a typed output disposition")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise InteractionModeError("interaction_mode_summary_missing", "Descriptor needs a human summary")

    @property
    def label(self) -> str:
        return self.mode.label

    @property
    def implemented(self) -> bool:
        """Faux tant que le mode n'a pas de comportement réel derrière son nom."""
        return self.status is InteractionModeStatus.READY

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value, "label": self.label, "status": self.status.value,
            "implemented": self.implemented, "default_disposition": self.default_disposition.value,
            "summary": self.summary,
        }


#: Mode appliqué quand rien de lisible n'a été demandé. La Décision 14 en fait
#: une frontière de régression : tant qu'un mode n'a pas été choisi
#: explicitement et validement, JARVIS se comporte exactement comme avant.
DEFAULT_INTERACTION_MODE = InteractionMode.ASSISTANT


INTERACTION_MODES: Mapping[InteractionMode, InteractionModeDescriptor] = MappingProxyType({
    descriptor.mode: descriptor for descriptor in (
        InteractionModeDescriptor(
            mode=InteractionMode.ASSISTANT, status=InteractionModeStatus.READY,
            default_disposition=OutputDisposition.VISUAL_AND_VOICE,
            summary="Assistant ordinaire : JARVIS répond à voix haute et affiche ce qu'il produit.",
        ),
        InteractionModeDescriptor(
            mode=InteractionMode.PRESENTATION, status=InteractionModeStatus.READY,
            default_disposition=OutputDisposition.VISUAL_ONLY,
            summary="Présentation en cours : JARVIS écoute, montre, et ne parle que si la parole apporte quelque chose.",
        ),
        InteractionModeDescriptor(
            mode=InteractionMode.MEETING, status=InteractionModeStatus.PLANNED,
            default_disposition=OutputDisposition.SILENT,
            summary="Réunion : réservé, non implémenté. Présenté pour que le nom ne soit pas repris à autre chose.",
        ),
    )
})


def interaction_mode_descriptor(mode: InteractionMode) -> InteractionModeDescriptor:
    return INTERACTION_MODES[mode]


def parse_interaction_mode(value: object) -> InteractionMode | None:
    """Valeur interne transportée/stockée -> mode, ou `None` si ce n'en est pas une.

    Strict, et c'est l'intérêt : aucune valeur d'un autre axe ne se glisse ici.
    `simple`, `continuous_brain`, `solo_owner` renvoient `None`, jamais un mode.
    Les étiquettes utilisateur passent par `parse_interaction_mode_label`.
    """
    if isinstance(value, InteractionMode):
        return value
    if not isinstance(value, str):
        return None
    try:
        return InteractionMode(value.strip().casefold())
    except ValueError:
        return None


def parse_interaction_mode_label(value: object) -> InteractionMode | None:
    """Étiquette utilisateur (`SIMPLE`, `PRESENTATION`, `REUNION`) -> mode, ou `None`.

    Chemin séparé de `parse_interaction_mode` : c'est ce qui empêche l'étiquette
    `SIMPLE` et la valeur d'architecture `simple` de se rencontrer.

    **Sensible à la casse, volontairement.** La Décision 02 verrouille des
    étiquettes en capitales ; tous les autres axes du dépôt transportent des
    valeurs en minuscules. Normaliser la casse ici ferait exactement ce que ce
    module existe pour empêcher : `simple`, la valeur d'architecture vocale,
    entrerait par cette porte et ressortirait en mode produit.
    """
    if isinstance(value, InteractionMode):
        return value
    if not isinstance(value, str):
        return None
    wanted = value.strip()
    return next((mode for mode, label in _LABELS.items() if label == wanted), None)


def resolve_interaction_mode(value: object) -> InteractionMode:
    """Mode retenu pour une valeur stockée quelconque. Ne lève jamais.

    Absente, mal typée, inconnue, vide : le défaut. Un réglage corrompu ne doit
    pas empêcher JARVIS de démarrer, et il ne doit surtout pas le faire démarrer
    dans un mode que personne n'a demandé.
    """
    return parse_interaction_mode(value) or DEFAULT_INTERACTION_MODE


def is_activatable(mode: InteractionMode) -> bool:
    """Un mode réservé est affichable, jamais activable (Décision 02)."""
    return INTERACTION_MODES[mode].implemented


def activatable_interaction_modes() -> tuple[InteractionMode, ...]:
    return tuple(mode for mode in InteractionMode if is_activatable(mode))


def ensure_activatable(mode: InteractionMode) -> InteractionMode:
    """Porte d'une demande **explicite** de changement de mode.

    Refuse bruyamment avec un code stable : un utilisateur qui clique `REUNION`
    doit lire pourquoi rien ne se passe, pas obtenir en silence un autre mode
    que celui qu'il a demandé.
    """
    if not is_activatable(mode):
        raise InteractionModeError(
            "interaction_mode_not_implemented",
            f"Interaction mode {mode.label} is reserved and has no behavior yet",
        )
    return mode


def effective_interaction_mode(value: object) -> InteractionMode:
    """Mode dont le comportement tourne réellement, pour une valeur quelconque.

    Complément silencieux et total de `ensure_activatable` : le chemin
    « je relis ce qui traîne sur le disque » ne doit jamais planter ni jamais
    activer un comportement de réunion qui n'existe pas. Un `meeting` stocké
    reste connu (`resolve_interaction_mode`) mais ne produit que le
    comportement assistant.
    """
    mode = resolve_interaction_mode(value)
    return mode if is_activatable(mode) else DEFAULT_INTERACTION_MODE


def default_disposition(mode: InteractionMode) -> OutputDisposition:
    """Manifestation par défaut d'un tour dans ce mode, avant toute politique."""
    return INTERACTION_MODES[mode].default_disposition
