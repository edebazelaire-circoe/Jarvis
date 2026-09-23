"""Qui tient le micro, en ce moment, dans ce processus — et combien sont ouverts.

La contrainte centrale de la Slice 05 est « **exactement un** propriétaire
physique de l'entrée en mode PRESENTATION ». Une contrainte qu'on ne peut pas
compter est une phrase d'en-tête, et la Slice 04 a payé pour apprendre qu'une
invariante inobservable dérive. Ce module est donc le compteur : tout code qui
ouvre un flux d'entrée PortAudio s'y déclare, tout code qui le ferme s'y
retire, et `open_input_stream_count()` rend le nombre de propriétaires vivants.

**Tous** les sites du dépôt qui ouvrent une entrée physique s'y déclarent, et
c'est vérifié par un test de conformité (`test_presentation_audio_capture.py`,
`test_every_site_that_opens_a_physical_input_registers_its_owner`) qui énumère
les appels à `RawInputStream(` et `sd.rec(` : six aujourd'hui, six inscrits.
Sans cette exhaustivité le compte mentirait exactement là où il sert — un
`SoundDeviceRecorder` vivant laisserait PRESENTATION lire « zéro propriétaire »,
ouvrir le hub, relire « un », et démarrer à deux flux concurrents.

| Inscrivant | Étiquette | Durée de vie |
| --- | --- | --- |
| `runtime.realtime_audio.SoundDeviceRealtimeAudio` | `realtime_audio` | un tour ; n'ouvre **rien** avec `input_source` |
| `audio.capture_hub.AudioCaptureHub` | `audio_capture_hub` | la séance PRESENTATION |
| `adapters.wakeword_porcupine.PorcupineWakeWordBackend` | `wakeword_porcupine` | l'attente du mot d'éveil, en SIMPLE |
| `audio.capture.SoundDeviceRecorder` | `audio_recorder` | un enregistrement pousser-pour-parler |
| `runtime.audio_devices` (`sd.rec`) | `audio_device_probe` | quelques secondes de test de périphérique |
| `runtime.owner_voice.record_microphone` (`sd.rec`) | `owner_voice_enrollment` | quelques secondes d'enrôlement |

Porcupine est inscrit précisément pour que son second flux soit **visible et
compté** plutôt que tacite : en SIMPLE le compte vaut 2 et c'est le
comportement existant, en PRESENTATION il doit valoir 1 et un test le compte.

Contenu : un identifiant d'objet et une étiquette de propriétaire. Jamais le
flux lui-même — mais un `weakref.finalize` le suit, si bien qu'un flux ramassé
par le GC sans passer par `release_input_stream` ne laisse pas d'entrée
fantôme. Sans ce filet, une seule fuite bloquerait PRESENTATION pour toujours,
sans chemin de purge. Jamais d'audio. Le registre vit en mémoire, comme les
flux qu'il décrit ; il n'est pas persisté et un redémarrage repart à zéro.
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass

#: Étiquettes connues. Une étiquette hors liste n'est pas refusée — le registre
#: ne doit jamais empêcher une fermeture — mais elle est repérable dans le
#: décompte, ce qui est le point.
OWNER_REALTIME_AUDIO = "realtime_audio"
OWNER_CAPTURE_HUB = "audio_capture_hub"
OWNER_WAKEWORD_PORCUPINE = "wakeword_porcupine"
OWNER_AUDIO_RECORDER = "audio_recorder"
OWNER_DEVICE_PROBE = "audio_device_probe"
OWNER_OWNER_VOICE_ENROLLMENT = "owner_voice_enrollment"


@dataclass(frozen=True, slots=True)
class InputStreamOwner:
    """Un flux d'entrée physique vivant : qui l'a ouvert, et lequel."""

    owner: str
    stream_id: int
    label: str | None = None


_lock = threading.Lock()
_owners: dict[int, InputStreamOwner] = {}
_finalizers: dict[int, "weakref.finalize"] = {}


def _drop_by_key(key: int) -> None:
    """Retirer une entrée par sa clé. Total : une clé inconnue ne fait rien."""

    with _lock:
        _owners.pop(key, None)
        finalizer = _finalizers.pop(key, None)
    if finalizer is not None:
        finalizer.detach()


def register_input_stream(owner: str, stream: object, *, label: str | None = None) -> None:
    """Déclarer un flux d'entrée physique nouvellement ouvert.

    Appelé juste après l'ouverture réussie, y compris depuis un thread de
    travail (`asyncio.to_thread`) : le verrou est un `threading.Lock`, pas une
    primitive asyncio, et il n'est jamais tenu pendant un appel PortAudio.
    """

    key = id(stream)
    with _lock:
        _owners[key] = InputStreamOwner(owner=str(owner), stream_id=key, label=label)
        _finalizers.pop(key, None)
        try:
            # Filet : un flux ramassé sans fermeture explicite se retire seul.
            # Tous les objets ne sont pas référençables faiblement (un `int`,
            # un jeton de test) ; dans ce cas la libération explicite reste la
            # seule voie, ce qui est le comportement d'avant ce filet.
            _finalizers[key] = weakref.finalize(stream, _drop_by_key, key)
        except TypeError:
            pass


def release_input_stream(stream: object) -> None:
    """Retirer un flux fermé. Idempotent, et sans effet sur un flux inconnu.

    Volontairement total : il est appelé depuis les chemins de fermeture, où
    lever ferait perdre la fermeture elle-même. Retirer deux fois, ou retirer un
    flux de sortie qui n'a jamais été inscrit, est normal et silencieux.
    """

    _drop_by_key(id(stream))


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
        finalizers = list(_finalizers.values())
        _owners.clear()
        _finalizers.clear()
    for finalizer in finalizers:
        finalizer.detach()
