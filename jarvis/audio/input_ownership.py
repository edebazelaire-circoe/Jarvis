"""Qui tient le micro, en ce moment, dans ce processus — et combien sont ouverts.

La contrainte centrale de la Slice 05 est « **exactement un** propriétaire
physique de l'entrée en mode PRESENTATION ». Une contrainte qu'on ne peut pas
compter est une phrase d'en-tête, et la Slice 04 a payé pour apprendre qu'une
invariante inobservable dérive. Ce module est donc le compteur : tout code qui
ouvre un flux d'entrée PortAudio s'y déclare, tout code qui le ferme s'y
retire, et `open_input_stream_count()` rend le nombre de propriétaires vivants.

Trois inscrivants aujourd'hui, et ce n'est pas un hasard qu'ils soient trois :

- `jarvis.runtime.realtime_audio.SoundDeviceRealtimeAudio` — le chemin
  interactif, qui n'ouvre **rien** quand on lui passe `input_source` ;
- `jarvis.audio.capture_hub.AudioCaptureHub` — la capture partagée de
  PRESENTATION ;
- `jarvis.adapters.wakeword_porcupine.PorcupineWakeWordBackend` — le chemin
  autonome conservé pour SIMPLE (D14). Il est inscrit précisément pour que son
  second flux soit **visible et compté** plutôt que tacite : en SIMPLE le
  compte vaut 2 et c'est le comportement existant, en PRESENTATION il doit
  valoir 1 et un test le compte.

Contenu : un identifiant d'objet et une étiquette de propriétaire. Jamais le
flux lui-même (aucune référence qui empêcherait sa libération), jamais d'audio.
Le registre vit en mémoire, comme les flux qu'il décrit ; il n'est pas persisté
et un redémarrage repart à zéro.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

#: Étiquettes connues. Une étiquette hors liste n'est pas refusée — le registre
#: ne doit jamais empêcher une fermeture — mais elle est repérable dans le
#: décompte, ce qui est le point.
OWNER_REALTIME_AUDIO = "realtime_audio"
OWNER_CAPTURE_HUB = "audio_capture_hub"
OWNER_WAKEWORD_PORCUPINE = "wakeword_porcupine"


@dataclass(frozen=True, slots=True)
class InputStreamOwner:
    """Un flux d'entrée physique vivant : qui l'a ouvert, et lequel."""

    owner: str
    stream_id: int
    label: str | None = None


_lock = threading.Lock()
_owners: dict[int, InputStreamOwner] = {}


def register_input_stream(owner: str, stream: object, *, label: str | None = None) -> None:
    """Déclarer un flux d'entrée physique nouvellement ouvert.

    Appelé juste après l'ouverture réussie, y compris depuis un thread de
    travail (`asyncio.to_thread`) : le verrou est un `threading.Lock`, pas une
    primitive asyncio, et il n'est jamais tenu pendant un appel PortAudio.
    """

    with _lock:
        _owners[id(stream)] = InputStreamOwner(owner=str(owner), stream_id=id(stream), label=label)


def release_input_stream(stream: object) -> None:
    """Retirer un flux fermé. Idempotent, et sans effet sur un flux inconnu.

    Volontairement total : il est appelé depuis les chemins de fermeture, où
    lever ferait perdre la fermeture elle-même. Retirer deux fois, ou retirer un
    flux de sortie qui n'a jamais été inscrit, est normal et silencieux.
    """

    with _lock:
        _owners.pop(id(stream), None)


def open_input_streams() -> tuple[InputStreamOwner, ...]:
    """Les propriétaires vivants, dans l'ordre d'inscription."""

    with _lock:
        return tuple(_owners.values())


def open_input_stream_count(owner: str | None = None) -> int:
    """Combien de flux d'entrée sont ouverts — en tout, ou pour un propriétaire."""

    with _lock:
        if owner is None:
            return len(_owners)
        return sum(1 for entry in _owners.values() if entry.owner == owner)


def reset_for_test() -> None:
    """Vider le registre entre deux tests.

    Un test qui fait échouer une ouverture laisse parfois un identifiant
    inscrit ; sans remise à zéro, le test suivant compterait un propriétaire
    fantôme et son verdict ne voudrait plus rien dire.
    """

    with _lock:
        _owners.clear()
