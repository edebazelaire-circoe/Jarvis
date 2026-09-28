"""Adresse explicite : un mot d'éveil et une touche manuelle, un seul type.

Décision D05 du handoff `jarvis-presentation-interaction-mode` : « le mot
d'éveil et la touche manuelle sont la même chose ». En mode PRESENTATION JARVIS
écoute déjà ; ce qui change quand l'un des deux se déclenche n'est pas
« commencer à écouter » mais « le tour qui suit m'est adressé, et il est
prioritaire ». Les deux sources doivent donc produire **un seul type**, et ce
type doit porter deux choses que la suite ne peut pas reconstituer après coup :

- **d'où vient le déclenchement** (`source`), parce qu'une panne du détecteur de
  mot d'éveil doit rester visible alors même que la touche manuelle continue de
  fonctionner (`docs/03-implementation-strategy.md`, « Failure behavior ») ;
- **quand** il a été admis, sur une horloge **monotone**. Pas `time.time()` :
  une correction d'horloge (NTP, changement d'heure, veille) ferait reculer le
  temps, et la latence d'admission — la seule grandeur que D04 oblige à borner —
  deviendrait négative ou absurde au pire moment. `time.monotonic()` ne recule
  jamais.

Pur : aucune E/S, aucune dépendance hors bibliothèque standard, aucune
importation de `jarvis.core` ni de `jarvis.runtime`. Aucun PCM n'entre ici — un
déclencheur est un fait, pas de l'audio.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from jarvis.domain._checks import check_token

#: Étiquette portée par le déclencheur : le mot d'éveil reconnu (« jarvis ») ou
#: le nom de la touche (« f9 »). Jeton court — jamais de la parole, jamais du
#: texte libre : ce champ est journalisé tel quel.
MAX_TRIGGER_LABEL_CHARS = 32

#: Âge au-delà duquel un déclencheur en file n'adresse plus rien. Un appui resté
#: derrière une lane saturée pendant plus d'une seconde ne désigne plus la phrase
#: que l'utilisateur est en train de dire ; le servir produirait un tour adressé
#: décalé d'une phrase, ce qui est pire que de le refuser en le disant.
MAX_TRIGGER_AGE_S = 1.0


class ExplicitAddressSource(str, Enum):
    """Qui a adressé JARVIS. Fermé : deux sources, pas une de plus en V1."""

    WAKE_WORD = "wake_word"
    MANUAL_KEY = "manual_key"

    @property
    def label(self) -> str:
        return "mot d'éveil" if self is ExplicitAddressSource.WAKE_WORD else "touche manuelle"


class ExplicitAddressError(ValueError):
    """Refus explicite et nommé (convention de la Slice 01).

    `code` est stable et anglais : c'est une identité de défaut, elle se compare
    et se journalise. Le message est lu par un humain francophone.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExplicitAddressTrigger:
    """Un tour explicitement adressé vient d'être demandé.

    Immuable et gelé : le temps d'admission est constaté une fois, à l'entrée de
    la lane, et ne peut plus être réécrit ensuite — c'est ce qui rend la latence
    mesurable au lieu d'être une opinion du consommateur.

    `sequence` est strictement croissant dans une lane donnée. Il sert à
    ordonner deux déclencheurs qui partagent la même valeur de `time.monotonic()`
    (la résolution de l'horloge est finie sous Windows) et à prouver, dans un
    test, qu'aucun déclencheur n'a été réordonné.
    """

    source: ExplicitAddressSource
    label: str
    monotonic_s: float
    sequence: int

    #: Un déclencheur dit *qui* parle et *quand*, jamais *quoi faire*. Rien ici
    #: n'autorise une action : c'est la parole qui suit qui sera interprétée, et
    #: D03 lui interdit déjà d'autoriser quoi que ce soit sans adresse.
    authorizes_actions: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.source, ExplicitAddressSource):
            raise ExplicitAddressError(
                "explicit_address_source_unknown",
                "La source d'un déclencheur doit être un ExplicitAddressSource.",
            )
        try:
            check_token("label", self.label, MAX_TRIGGER_LABEL_CHARS, required=True)
        except (TypeError, ValueError) as exc:
            raise ExplicitAddressError(
                "explicit_address_label_invalid",
                f"Étiquette de déclencheur invalide : {exc}",
            ) from exc
        if not isinstance(self.monotonic_s, float) or not math.isfinite(self.monotonic_s):
            raise ExplicitAddressError(
                "explicit_address_time_invalid",
                "Le temps d'un déclencheur doit être un flottant fini issu de time.monotonic().",
            )
        if self.monotonic_s < 0.0:
            # `time.monotonic()` est positif sur toutes les plateformes visées ;
            # une valeur négative signale une horloge fabriquée, pas une mesure.
            raise ExplicitAddressError(
                "explicit_address_time_invalid",
                "Le temps d'un déclencheur ne peut pas être négatif.",
            )
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise ExplicitAddressError(
                "explicit_address_sequence_invalid",
                "Le rang d'un déclencheur doit être un entier positif ou nul.",
            )

    @classmethod
    def admitted(
        cls,
        source: ExplicitAddressSource,
        label: str,
        *,
        sequence: int,
        clock: object = time.monotonic,
    ) -> "ExplicitAddressTrigger":
        """Estampiller un déclencheur **au moment de son admission**.

        `clock` est injectable pour les tests ; par défaut `time.monotonic`.
        Un `clock` qui ne rend pas un flottant fini est refusé ici plutôt que
        de produire un déclencheur au temps invalide.
        """

        stamped = clock()  # type: ignore[operator]
        if isinstance(stamped, int) and not isinstance(stamped, bool):
            stamped = float(stamped)
        return cls(source=source, label=label, monotonic_s=stamped, sequence=int(sequence))

    def age_s(self, now: float) -> float:
        """Âge du déclencheur, jamais négatif.

        Une horloge monotone ne recule pas ; si `now` est malgré tout antérieur
        (deux horloges différentes mélangées par erreur), on rend 0.0 plutôt
        qu'un âge négatif, qui ferait passer un déclencheur périmé pour frais.
        """

        return max(0.0, float(now) - self.monotonic_s)

    def is_fresh(self, now: float, *, max_age_s: float = MAX_TRIGGER_AGE_S) -> bool:
        return self.age_s(now) <= max_age_s

    def to_payload(self) -> dict[str, object]:
        """Forme journalisable. Bornée, sans audio, sans parole."""

        return {
            "source": self.source.value,
            "label": self.label,
            "monotonic_s": round(self.monotonic_s, 6),
            "sequence": self.sequence,
        }
