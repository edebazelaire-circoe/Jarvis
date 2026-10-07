"""Moteur de mot d'éveil openWakeWord, derrière le contrat `WakeWordEngine`.

`SharedPcmWakeWordBackend` attend un moteur de la forme `pvporcupine.Porcupine` :
`frame_length`, `sample_rate`, `process(pcm) -> int` (>= 0 si détecté), `delete()`.
`OpenWakeWordEngine` tient ce contrat avec un modèle ONNX local : trames de
1280 échantillons (80 ms à 16 kHz), `0` sur détection (l'indice de l'unique mot),
`-1` sinon. Rien ne change côté backend ni côté Porcupine.

Pourquoi le score est un **attribut** et pas une valeur de retour
-----------------------------------------------------------------

Le port `WakeWordBackend` (`jarvis/ports/v2.py`) ne transporte que des chaînes,
et `process()` rend un entier : le score se perdrait au moteur. Il reste donc
lisible sur le moteur (`last_score`, `threshold`, `cooldown_ignored`,
`below_threshold`, `slow_calls`...) pour que les Slices de câblage le mettent en
trace sans toucher au contrat.

Seuil et anti-rebond
--------------------

- `threshold_from_sensitivity` : fonction pure, décroissante et affine,
  `seuil = 0,9 - 0,8 x sensibilité` ; la sensibilité 0,5 donne 0,5, le seuil que
  recommande openWakeWord. Une sensibilité hors 0..1 est **refusée** (jamais
  bornée en silence : un réglage faux doit se voir).
- Le cooldown se compte en **trames**, jamais à l'horloge murale (tests
  déterministes, et un processus gelé ne « rate » pas son cooldown). Une
  détection ouvre une fenêtre de `cooldown_frames` trames pendant lesquelles
  `process` rend `-1` ; le modèle, lui, continue de recevoir toutes les trames
  (son état de flux ne doit pas se fausser).

Coût d'inférence (décision D7)
------------------------------

En PRESENTATION `process` s'exécute sur la boucle asyncio. Mesuré en Slice 01 :
p99 de 6,2 ms pour un budget de 80 ms. Chaque appel est chronométré ; au-delà de
`DEFAULT_SLOW_CALL_MS` (la moitié de la trame) une trace dite part au journal
injecté, au plus une par seconde de trames, et `slow_calls` compte tout. Si cela
arrive en usage réel, c'est le signal pour passer à un exécuteur dédié.

Ce module n'importe ni `openwakeword`, ni `onnxruntime`, ni `numpy` à son
import : seule la fabrique les charge, à la construction du moteur. Sans l'extra
`wakeword`, la construction échoue avec `wake_engine_unavailable`, que le backend
rend sans empêcher Jarvis de démarrer. Aucun téléchargement n'a lieu ici : les
modèles viennent du catalogue (`wakeword_model_catalog`), déjà installés et
vérifiés par SHA-256, sinon l'erreur est dite.

Le moteur n'ouvre aucun flux, n'écrit aucun fichier, ne retient aucune trame et
ne journalise jamais d'audio ni de texte parlé.
"""

from __future__ import annotations

from collections.abc import Callable
import math
from numbers import Integral, Real
from pathlib import Path
import time
from typing import Any

from jarvis.adapters import wakeword_model_catalog as catalog
from jarvis.ports.v2 import DiagnosticSink

PROVIDER = "openwakeword"
FRAME_LENGTH = 1280  # 80 ms à 16 kHz
SAMPLE_RATE = 16000
FRAME_MS = 80
DEFAULT_KEYWORD = "hey_jarvis"
DEFAULT_SENSITIVITY = 0.5
DEFAULT_COOLDOWN_MS = 2000

#: Alerte d'un appel `process` trop lent : la moitié de la trame (D7, Slice 01).
DEFAULT_SLOW_CALL_MS = 40.0

#: Trames minimales entre deux traces de lenteur (12 x 80 ms ~ 1 s) : une boucle
#: saturée ne doit pas noyer le journal, `slow_calls` compte tout de même.
SLOW_TRACE_MIN_FRAMES = 12

_INT16_MIN, _INT16_MAX = -32768, 32767
_PREPROCESSING_KEYS = frozenset({"melspectrogram", "embedding"})

#: Seuil = _THRESHOLD_AT_ZERO - _THRESHOLD_SLOPE x sensibilité (0,9 -> 0,1).
_THRESHOLD_AT_ZERO = 0.9
_THRESHOLD_SLOPE = 0.8


class WakeEngineError(RuntimeError):
    """Erreur dite du moteur, avec un code stable.

    Codes : `wake_engine_unavailable` (paquet ou modèle absent ; `cause_code`
    donne le détail), `wake_config_invalid`, `wake_frame_invalid`,
    `wake_inference_failed`, `wake_engine_closed`.
    """

    def __init__(self, code: str, message: str, *, cause_code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.cause_code = cause_code


def _is_real(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _config_error(message: str) -> WakeEngineError:
    return WakeEngineError("wake_config_invalid", message)


def threshold_from_sensitivity(sensitivity: float) -> float:
    """Seuil de détection pour une sensibilité de 0 à 1 (plus sensible = seuil plus bas)."""

    if not _is_real(sensitivity) or not 0.0 <= float(sensitivity) <= 1.0:
        raise _config_error(f"Sensibilité du mot d'éveil invalide (0 à 1 attendu) : {sensitivity!r}")
    return _THRESHOLD_AT_ZERO - _THRESHOLD_SLOPE * float(sensitivity)


def cooldown_frames_from_ms(cooldown_ms: float) -> int:
    """Durée de cooldown convertie en trames de 80 ms, arrondie au-dessus."""

    if not _is_real(cooldown_ms) or float(cooldown_ms) < 0:
        raise _config_error(f"Cooldown du mot d'éveil invalide (ms >= 0 attendu) : {cooldown_ms!r}")
    return math.ceil(float(cooldown_ms) / FRAME_MS)


class OpenWakeWordEngine:
    """`WakeWordEngine` à base de scores. Le `model` est injecté : `score(pcm) -> float`, `close()`."""

    frame_length = FRAME_LENGTH
    sample_rate = SAMPLE_RATE
    provider = PROVIDER

    def __init__(
        self,
        *,
        model: Any,
        keyword: str = DEFAULT_KEYWORD,
        threshold: float = 0.5,
        cooldown_frames: int = 0,
        slow_call_ms: float = DEFAULT_SLOW_CALL_MS,
        journal: DiagnosticSink | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not _is_real(threshold) or not 0.0 < float(threshold) <= 1.0:
            raise _config_error(f"Seuil du mot d'éveil invalide (]0, 1] attendu) : {threshold!r}")
        if not isinstance(cooldown_frames, Integral) or isinstance(cooldown_frames, bool) or cooldown_frames < 0:
            raise _config_error(f"Cooldown en trames invalide (entier >= 0 attendu) : {cooldown_frames!r}")
        if not _is_real(slow_call_ms) or float(slow_call_ms) <= 0:
            raise _config_error(f"Seuil d'appel lent invalide (ms > 0 attendu) : {slow_call_ms!r}")
        self._model: Any | None = model
        self._closed = False
        self._clock = clock
        self._journal = journal
        self.keyword = keyword
        self.threshold = float(threshold)
        self.cooldown_frames = int(cooldown_frames)
        self.slow_call_ms = float(slow_call_ms)
        #: Observables : la confiance ne voyage pas par le port, elle se lit ici.
        self.last_score: float | None = None
        self.frames_seen = 0
        self.detections = 0
        self.below_threshold = 0
        self.cooldown_ignored = 0
        self.failures = 0
        self.slow_calls = 0
        self.last_process_ms: float | None = None
        self.max_process_ms = 0.0
        self._cooldown_left = 0
        self._frames_since_slow_trace = SLOW_TRACE_MIN_FRAMES

    # -- contrat WakeWordEngine ------------------------------------------

    def process(self, pcm: Any) -> int:
        """`0` si le mot est détecté sur cette trame, `-1` sinon."""

        if self._closed or self._model is None:
            raise WakeEngineError("wake_engine_closed", "Le moteur de mot d'éveil est déjà libéré.")
        _check_frame(pcm)
        self.frames_seen += 1
        start = self._clock()
        failure: Exception | None = None
        raw: object = None
        try:
            raw = self._model.score(pcm)
        except Exception as exc:  # noqa: BLE001 - toute panne d'inférence est dite, jamais avalée
            failure = exc
        self._account_time((self._clock() - start) * 1000.0)
        if failure is not None:
            self.failures += 1
            raise WakeEngineError(
                "wake_inference_failed",
                f"Inférence du mot d'éveil en échec : {type(failure).__name__}",
            ) from failure
        if not _is_real(raw) or not 0.0 <= float(raw) <= 1.0:
            self.failures += 1
            raise WakeEngineError(
                "wake_inference_failed", f"Score du mot d'éveil hors de 0..1 : {type(raw).__name__}"
            )
        score = float(raw)
        self.last_score = score
        loud = score >= self.threshold
        if self._cooldown_left > 0:
            self._cooldown_left -= 1
            if loud:
                self.cooldown_ignored += 1
            else:
                self.below_threshold += 1
            return -1
        if not loud:
            self.below_threshold += 1
            return -1
        self.detections += 1
        self._cooldown_left = self.cooldown_frames
        return 0

    def delete(self) -> None:
        """Libérer le modèle. Idempotent ; une erreur de libération se lève une seule fois."""

        model, self._model = self._model, None
        self._closed = True
        if model is not None:
            close = getattr(model, "close", None)
            if close is not None:
                close()

    # -- chronométrage ----------------------------------------------------

    def _account_time(self, duration_ms: float) -> None:
        self.last_process_ms = duration_ms
        self.max_process_ms = max(self.max_process_ms, duration_ms)
        self._frames_since_slow_trace += 1
        if duration_ms <= self.slow_call_ms:
            return
        self.slow_calls += 1
        if self._frames_since_slow_trace < SLOW_TRACE_MIN_FRAMES or self._journal is None:
            return
        self._frames_since_slow_trace = 0
        try:
            self._journal.emit(
                "wake.openwakeword.slow_inference",
                f"Inférence du mot d'éveil lente : {duration_ms:.1f} ms pour une trame de {FRAME_MS} ms "
                "(la boucle de capture est en retard ; envisager un exécuteur dédié)",
                level="warning",
                data={
                    "code": "wake_inference_slow",
                    "provider": PROVIDER,
                    "duration_ms": round(duration_ms, 3),
                    "threshold_ms": self.slow_call_ms,
                    "slow_calls": self.slow_calls,
                },
            )
        except Exception:  # noqa: BLE001
            # Tracer est au mieux : on ne peut pas dire l'échec du journal par
            # le journal, et il ne doit jamais faire tomber la détection.
            pass


def _check_frame(pcm: object) -> None:
    if not isinstance(pcm, (tuple, list)):
        raise WakeEngineError(
            "wake_frame_invalid", f"Trame attendue sous forme de tuple d'entiers, reçu {type(pcm).__name__}."
        )
    if len(pcm) != FRAME_LENGTH:
        raise WakeEngineError(
            "wake_frame_invalid", f"Trame de {FRAME_LENGTH} échantillons attendue, reçu {len(pcm)}."
        )
    for value in pcm:
        if type(value) is not int and (isinstance(value, bool) or not isinstance(value, Integral)):
            raise WakeEngineError(
                "wake_frame_invalid", f"Échantillon entier attendu, reçu {type(value).__name__}."
            )
    if min(pcm) < _INT16_MIN or max(pcm) > _INT16_MAX:
        raise WakeEngineError("wake_frame_invalid", "Échantillon hors de la plage int16.")


# -- chargement du vrai modèle (import paresseux) ---------------------------


class _OpenWakeWordScorer:
    """Adapte `openwakeword.model.Model` au `score(pcm) -> float` du moteur."""

    def __init__(self, model: Any, name: str) -> None:
        self._model: Any | None = model
        self._name = name

    def score(self, pcm: Any) -> float:
        import numpy as np

        model = self._model
        if model is None:
            raise RuntimeError("modèle libéré")
        scores = model.predict(np.asarray(pcm, dtype=np.int16))
        if self._name in scores:
            return float(scores[self._name])
        if len(scores) == 1:
            return float(next(iter(scores.values())))
        raise KeyError(f"aucun score pour {self._name}")

    def close(self) -> None:
        self._model = None


def _unavailable(message: str, cause_code: str) -> WakeEngineError:
    return WakeEngineError("wake_engine_unavailable", f"{message} ({cause_code})", cause_code=cause_code)


def _load_scorer(spec: catalog.WakeModelSpec, model_dir: Path | None) -> _OpenWakeWordScorer:
    try:
        import openwakeword  # noqa: F401
        from openwakeword.model import Model
    except ImportError as exc:
        raise _unavailable(
            "openWakeWord n'est pas installé : pip install .[wakeword]", "wake_package_missing"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - une DLL ou une dépendance cassée est dite aussi
        raise _unavailable(
            f"openWakeWord ne se charge pas : {type(exc).__name__}", "wake_package_failed"
        ) from exc
    try:
        paths = catalog.verified_paths(model_dir)
    except catalog.WakeModelError as exc:
        raise _unavailable(str(exc), exc.code) from exc
    try:
        model = Model(
            wakeword_models=[str(paths[spec.key])],
            inference_framework="onnx",
            melspec_model_path=str(paths["melspectrogram"]),
            embedding_model_path=str(paths["embedding"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(
            f"Chargement du modèle openWakeWord en échec : {type(exc).__name__}", "wake_model_load_failed"
        ) from exc
    return _OpenWakeWordScorer(model, Path(spec.filename).stem)


def openwakeword_engine_factory(
    *,
    keyword: str = DEFAULT_KEYWORD,
    sensitivity: float = DEFAULT_SENSITIVITY,
    cooldown_ms: float = DEFAULT_COOLDOWN_MS,
    model_dir: Path | None = None,
    slow_call_ms: float = DEFAULT_SLOW_CALL_MS,
    journal: DiagnosticSink | None = None,
) -> Callable[[], OpenWakeWordEngine]:
    """Fabrique paresseuse, de même forme que `porcupine_engine_factory`.

    La configuration est validée **ici** (un réglage faux se refuse tout de
    suite) ; `openwakeword` et les modèles ne sont chargés qu'au `build()`.
    """

    threshold = threshold_from_sensitivity(sensitivity)
    cooldown_frames = cooldown_frames_from_ms(cooldown_ms)
    spec = catalog.find_model(keyword) if isinstance(keyword, str) else None
    if spec is None or spec.key in _PREPROCESSING_KEYS:
        raise _config_error(f"Mot d'éveil inconnu du catalogue des modèles : {keyword!r}")
    if not _is_real(slow_call_ms) or float(slow_call_ms) <= 0:
        raise _config_error(f"Seuil d'appel lent invalide (ms > 0 attendu) : {slow_call_ms!r}")

    def build() -> OpenWakeWordEngine:
        scorer = _load_scorer(spec, model_dir)
        return OpenWakeWordEngine(
            model=scorer,
            keyword=spec.key,
            threshold=threshold,
            cooldown_frames=cooldown_frames,
            slow_call_ms=slow_call_ms,
            journal=journal,
        )

    return build
