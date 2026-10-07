"""Composition du mot d'éveil en SIMPLE : au plus **un** détecteur de repos.

`jarvis/app.py` ajoute la touche manuelle (toujours) puis ce que cette fonction
rend. La politique tient en quatre lignes, et un test la prouve :

| bloc `wake_word`                                  | détecteur de repos |
| ------------------------------------------------- | ------------------ |
| absent, ou `enabled=false` (défaut, D1)           | Porcupine si une clé existe, sinon aucun : comportement d'avant |
| `enabled=true`, `provider=porcupine`              | Porcupine si une clé existe (idem) |
| `enabled=true`, `provider=openwakeword`           | `OwnStreamWakeWordBackend` ; Porcupine n'est **pas instancié**, même avec une clé |

Donc jamais deux flux micro de repos : un fournisseur actif, l'autre absent.
Le choix « openWakeWord » est celui de PRESENTATION
(`presentation_runtime.openwakeword_engine_selection`), appelé tel quel : une
même configuration choisit le même moteur dans les deux modes, et c'est le seul
endroit qui atteint `wakeword_openwakeword`.

Rien ici n'ouvre de micro ni ne charge de modèle : les détecteurs sont
construits au repos et ne s'ouvrent qu'à `start()`.
"""

from __future__ import annotations

from typing import Any

from jarvis.adapters.wakeword_own_stream import OwnStreamWakeWordBackend
from jarvis.adapters.wakeword_porcupine import PorcupineWakeWordBackend
from jarvis.runtime import presentation_runtime
from jarvis.runtime import wake_word_settings


def simple_wake_backends(
    *,
    block: Any | None,
    access_key: str,
    keyword: str,
    device: int | str | None,
    fallback_sample_rate: int | None = None,
    model_dir: Any | None = None,
    journal: Any | None = None,
) -> list[Any]:
    """Les détecteurs de repos à composer avec la touche manuelle : zéro ou un."""

    chosen = presentation_runtime.openwakeword_engine_selection(
        block, model_dir=model_dir, journal=journal,
    )
    if chosen is not None:
        factory, wake_keyword = chosen
        return [
            OwnStreamWakeWordBackend(
                engine_factory=factory,
                keyword=wake_keyword,
                provider=wake_word_settings.PROVIDER_OPENWAKEWORD,
                device=device,
                fallback_sample_rate=fallback_sample_rate,
                journal=journal,
            )
        ]
    if access_key:
        return [PorcupineWakeWordBackend(access_key=access_key, keyword=keyword, device=device)]
    return []
