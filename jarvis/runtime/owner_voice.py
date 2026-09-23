"""Voix du propriétaire : enrôlement, profil et vérificateur local.

Trois usages, un seul endroit qui assemble le moteur (`sherpa-onnx`), le
profil (`jarvis/adapters/owner_voice_profile.py`) et la vérification
glissante (`jarvis/audio/owner_verifier.py`) :

- `probe_owner_verifier` : sonde bon marché pour le Control Center — module
  installé, fichier du modèle présent, métadonnées du profil. Ne charge jamais
  le modèle ;
- `open_owner_verifier` : le `SpeakerVerifier` que Voice branche en ombre ;
- `run_cli` : `jarvis owner-voice download-model | enroll | show | delete | score`.

Biométrie : l'empreinte ne sort d'ici que vers le vérificateur. Le terminal,
le journal et l'API ne voient que des métadonnées et des scores.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from urllib.error import URLError
import wave
from typing import Any, Mapping

from jarvis.adapters import sherpa_speaker_embedder as engine
from jarvis.adapters.owner_voice_profile import (
    OwnerProfileError,
    OwnerVoiceProfile,
    delete_profile,
    load_profile,
    new_profile_id,
    save_profile,
    utc_now,
)
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.speaker import VerifierAvailability
from jarvis.v2_config import SpeakerVerifierSettings, parse_speaker_verifier_settings

#: Pas de la fenêtre glissante : une empreinte recalculée toutes les 500 ms de
#: parole nouvelle, soit ~20 % d'un cœur pendant que quelqu'un parle.
DEFAULT_STRIDE_MS = 500
#: Durée d'enregistrement micro proposée à l'enrôlement.
DEFAULT_ENROLL_SECONDS = 30.0

_ENROLL_TEXT = (
    "Lisez ce texte d'une voix naturelle, à votre distance habituelle du micro :\n\n"
    "  « Bonjour JARVIS. Aujourd'hui je voudrais faire le point sur mes rendez-vous, relire les\n"
    "  messages importants et préparer la réunion de cet après-midi. Rappelle-moi aussi d'appeler\n"
    "  le garage demain matin, de vérifier la livraison au bureau et de réserver une table pour\n"
    "  vendredi soir. Si quelqu'un d'autre parle dans la pièce, ne l'écoute pas : c'est ma voix\n"
    "  que tu dois reconnaître, même quand je parle vite, doucement ou un peu fatigué. »\n"
)


@dataclass(frozen=True, slots=True)
class OwnerVerifierProbe:
    """État du vérificateur tel qu'on peut le constater sans charger le modèle."""

    availability: VerifierAvailability
    code: str
    message: str
    engine: str | None
    model_id: str
    model_present: bool
    profile: dict[str, object] | None = None

    def payload(self) -> dict[str, object]:
        """Vue publique : jamais d'empreinte, seulement des métadonnées."""

        return {
            "availability": self.availability.value,
            "code": self.code,
            "message": self.message,
            "engine": self.engine,
            "model_id": self.model_id,
            "model_license": engine.MODEL_LICENSE,
            "model_present": self.model_present,
            "profile": self.profile,
        }


def _probe(availability: VerifierAvailability, code: str, message: str, **extra: Any) -> OwnerVerifierProbe:
    return OwnerVerifierProbe(
        availability=availability,
        code=code,
        message=message,
        engine=extra.pop("engine", None),
        model_id=engine.MODEL_ID,
        model_present=extra.pop("model_present", False),
        profile=extra.pop("profile", None),
    )


def probe_owner_verifier(settings: SpeakerVerifierSettings) -> OwnerVerifierProbe:
    """Moteur installé, modèle présent, profil présent et compatible ?"""

    if not engine.engine_installed():
        return _probe(
            VerifierAvailability.NOT_INSTALLED,
            "speaker_engine_not_installed",
            "sherpa-onnx n'est pas installé : pip install -e \".[speaker]\".",
        )
    engine_id = engine.engine_id()
    model = engine.model_path(settings.model_dir)
    if not model.is_file():
        return _probe(
            VerifierAvailability.NOT_INSTALLED,
            "speaker_model_missing",
            f"Modèle de vérification absent ({model}) : jarvis owner-voice download-model.",
            engine=engine_id,
        )
    try:
        # Taille d'abord (gratuite), puis l'empreinte réelle, mise en cache sur
        # (taille, date de modification) : un modèle corrompu de la bonne taille
        # ne doit pas s'annoncer « prêt » au Control Center alors que Voice le
        # refusera au chargement. Une sonde répétée ne relit pas les 27 Mio.
        if model.stat().st_size != engine.MODEL_SIZE or engine.cached_file_sha256(model) != engine.MODEL_SHA256:
            return _probe(
                VerifierAvailability.FAILED,
                "speaker_model_mismatch",
                f"Le modèle {model} ne correspond pas à celui qui est épinglé ; retéléchargez-le "
                f"(download-model --force).",
                engine=engine_id,
                model_present=True,
            )
    except OSError as exc:
        return _probe(
            VerifierAvailability.FAILED,
            "speaker_model_unreadable",
            f"Modèle de vérification illisible ({model}) : {type(exc).__name__}.",
            engine=engine_id,
            model_present=True,
        )
    try:
        profile = load_profile(settings.profile_path)
    except OwnerProfileError as exc:
        return _probe(
            VerifierAvailability.NO_OWNER_PROFILE, exc.code, str(exc), engine=engine_id, model_present=True
        )
    reason = profile.incompatibility(
        model_sha256=engine.MODEL_SHA256, embedding_dim=engine.MODEL_DIM, sample_rate=engine.MODEL_SAMPLE_RATE
    )
    if reason is not None:
        return _probe(
            VerifierAvailability.NO_OWNER_PROFILE,
            "owner_profile_incompatible",
            f"Profil vocal inutilisable ({reason}) : enrôlez-vous de nouveau.",
            engine=engine_id,
            model_present=True,
            profile=profile.metadata(),
        )
    return _probe(
        VerifierAvailability.READY,
        "ready",
        "Vérificateur prêt.",
        engine=engine_id,
        model_present=True,
        profile=profile.metadata(),
    )


def probe_from_settings(settings: Mapping[str, object], *, runtime_root: Path) -> OwnerVerifierProbe:
    """Sonde à partir des réglages bruts ; un réglage invalide est un état, pas une panne."""

    try:
        parsed = parse_speaker_verifier_settings(settings, runtime_root=runtime_root)
    except ConfigurationError as exc:
        return _probe(VerifierAvailability.FAILED, getattr(exc, "code", "speaker_settings_invalid"), str(exc))
    return probe_owner_verifier(parsed)


def effective_verifier_settings(settings: SpeakerVerifierSettings) -> dict[str, object]:
    """Valeurs que Voice appliquerait, défauts du moteur compris (Control Center, tâche 08).

    Même résolution que `build_owner_verifier` : un seuil absent est celui du
    moteur ; une règle brève désactivée vaut 0, comme dans le réglage.
    """

    return {
        "owner_threshold": settings.threshold if settings.threshold is not None else engine.DEFAULT_THRESHOLD,
        "owner_evidence_ms": settings.evidence_ms,
        "owner_short_evidence_ms": settings.short_evidence_ms or 0,
        "owner_short_margin": settings.short_margin,
        "owner_profile_path": str(settings.profile_path),
    }


#: Commande qui lève chaque cause d'indisponibilité, pour l'écran de réglages.
#: Voice doit être arrêtée pour enrôler au micro (il ne se partage pas).
_PYTHON = r".\.venv\Scripts\python.exe"
_REMEDIES: dict[str, str] = {
    "speaker_engine_not_installed": f'{_PYTHON} -m pip install -e ".[speaker]"',
    "speaker_model_missing": f"{_PYTHON} -m jarvis owner-voice download-model",
    "speaker_model_mismatch": f"{_PYTHON} -m jarvis owner-voice download-model --force",
    "speaker_model_unreadable": f"{_PYTHON} -m jarvis owner-voice download-model --force",
    "owner_profile_missing": f"{_PYTHON} -m jarvis owner-voice enroll --mic",
    "owner_profile_corrupt": f"{_PYTHON} -m jarvis owner-voice enroll --mic --replace",
    "owner_profile_incompatible": f"{_PYTHON} -m jarvis owner-voice enroll --mic --replace",
}


def probe_remedy(code: str) -> str | None:
    """La commande à lancer pour un code de sonde, ou None (prêt, ou réglage à corriger)."""

    return _REMEDIES.get(code)


def _trace(journal: Any, kind: str, message: str, level: str, data: dict[str, object]) -> None:
    if journal is None:
        return
    try:
        journal.emit(kind, message, level=level, data=data)
    except Exception:
        # Un journal qui refuse d'écrire ne doit pas empêcher Voice de démarrer.
        pass


def open_owner_verifier(settings: Mapping[str, object], *, runtime_root: Path, journal: Any = None):
    """Le vérificateur réel, ou `None` s'il est inutilisable (raison journalisée).

    Rapide : le modèle n'est chargé que plus tard, dans le fil du vérificateur
    (`EmbeddingSpeakerVerifier.reset`), jamais sur la boucle asyncio.
    """

    from jarvis.audio.speaker_shadow import OWNER_UNAVAILABLE

    try:
        parsed = parse_speaker_verifier_settings(settings, runtime_root=runtime_root)
    except ConfigurationError as exc:
        _trace(journal, OWNER_UNAVAILABLE, str(exc), "warning", {"code": getattr(exc, "code", "speaker_settings_invalid")})
        return None
    return build_owner_verifier(parsed, journal=journal)


def build_owner_verifier(parsed: SpeakerVerifierSettings, *, journal: Any = None, embedder: Any = None):
    """Assembler moteur, profil et fenêtre glissante ; `None` si pas prêt.

    `embedder` remplace le moteur sherpa-onnx (tests, banc d'essai de la
    tâche 09) : le profil doit alors avoir été enrôlé avec ce même moteur.
    """

    from jarvis.audio.owner_verifier import EmbeddingSpeakerVerifier
    from jarvis.audio.speaker_shadow import OWNER_UNAVAILABLE

    probe = probe_owner_verifier(parsed)
    if probe.availability is not VerifierAvailability.READY:
        _trace(
            journal,
            OWNER_UNAVAILABLE,
            f"Vérification du locuteur indisponible : {probe.message}",
            "warning",
            {"code": probe.code, "availability": probe.availability.value, "engine": probe.engine},
        )
        return None
    threshold = parsed.threshold if parsed.threshold is not None else engine.DEFAULT_THRESHOLD
    try:
        profile = load_profile(parsed.profile_path)
        verifier = EmbeddingSpeakerVerifier(
            embedder or engine.SherpaSpeakerEmbedder(engine.model_path(parsed.model_dir)),
            profile.embedding,
            engine=probe.engine or engine.engine_id(),
            profile_id=profile.profile_id,
            threshold=threshold,
            evidence_ms=parsed.evidence_ms,
            stride_ms=DEFAULT_STRIDE_MS,
            # Tâche 07 : réponses brèves et passage de relais sans silence.
            short_evidence_ms=parsed.short_evidence_ms,
            short_margin=parsed.short_margin,
        )
    except (OwnerProfileError, ValueError) as exc:
        # Profil supprimé ou modifié entre la sonde et la lecture : l'ombre
        # renonce, la capture duplex reste intacte.
        _trace(
            journal,
            OWNER_UNAVAILABLE,
            f"Vérification du locuteur indisponible : {exc}",
            "warning",
            {"code": getattr(exc, "code", "owner_profile_incompatible"), "engine": probe.engine},
        )
        return None
    _trace(
        journal,
        "voice.owner.engine",
        "Vérificateur de locuteur branché (ombre : l'audio n'en est pas changé)",
        "info",
        {
            "engine": verifier.engine,
            "model_id": engine.MODEL_ID,
            "model_sha256": engine.MODEL_SHA256,
            "profile_id": profile.profile_id,
            "threshold": threshold,
            "evidence_ms": parsed.evidence_ms,
            "stride_ms": DEFAULT_STRIDE_MS,
            "short_evidence_ms": parsed.short_evidence_ms,
            "short_margin": parsed.short_margin,
        },
    )
    return verifier


# -- enregistrements --------------------------------------------------------------


def read_wav(path: Path):  # noqa: ANN201 - (numpy.ndarray, int)
    """WAV PCM (8/16/24/32 bits, mono ou multicanal) → float32 mono, fréquence."""

    import numpy as np

    from jarvis.audio.owner_verifier import EnrollmentError

    try:
        with wave.open(str(path), "rb") as handle:
            channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
            raw = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError) as exc:
        raise EnrollmentError(
            "enrollment_unsupported_wav", f"{path} : WAV PCM entier attendu ({exc})."
        ) from None
    except OSError as exc:
        raise EnrollmentError("enrollment_unreadable", f"{path} : {exc}") from None
    if width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        bytes3 = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = bytes3[:, 0] | (bytes3[:, 1] << 8) | (bytes3[:, 2] << 16)
        values = np.where(values >= 1 << 23, values - (1 << 24), values)
        samples = values.astype(np.float32) / float(1 << 23)
    elif width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        raise EnrollmentError("enrollment_unsupported_wav", f"{path} : {8 * width} bits par échantillon non pris en charge.")
    if channels > 1:
        samples = samples[: samples.size - samples.size % channels].reshape(-1, channels).mean(axis=1)
    return samples.astype(np.float32, copy=False), int(rate)


def record_microphone(seconds: float, *, device: object = None):  # noqa: ANN201 - (numpy.ndarray, int)
    """Enregistrer le micro en mono 16 kHz, en mémoire seulement."""

    import sounddevice as sd

    from jarvis.audio.input_ownership import (
        OWNER_OWNER_VOICE_ENROLLMENT,
        register_input_stream,
        release_input_stream,
    )

    frames = int(max(1.0, float(seconds)) * engine.MODEL_SAMPLE_RATE)
    # Registre des proprietaires d'entree : l'enrolement tient un vrai micro le
    # temps de l'appel, et doit donc etre compte comme les autres, sinon
    # PRESENTATION pourrait s'activer par-dessus.
    token = object()
    register_input_stream(OWNER_OWNER_VOICE_ENROLLMENT, token, label=str(device))
    try:
        audio = sd.rec(frames, samplerate=engine.MODEL_SAMPLE_RATE, channels=1, dtype="float32", device=device)
        sd.wait()
    finally:
        release_input_stream(token)
    return audio.reshape(-1), engine.MODEL_SAMPLE_RATE


def enroll(
    settings: SpeakerVerifierSettings,
    clips: list[tuple[Any, int]],
    *,
    replace: bool = False,
    embedder: Any = None,
) -> OwnerVoiceProfile:
    """Calculer et enregistrer le profil du propriétaire."""

    from jarvis.audio.owner_verifier import EnrollmentError, enroll_embedding

    if settings.profile_path.exists() and not replace:
        raise EnrollmentError(
            "owner_profile_exists",
            f"Un profil existe déjà ({settings.profile_path}) : --replace pour le remplacer, ou delete d'abord.",
        )
    if embedder is None:
        embedder = engine.SherpaSpeakerEmbedder(engine.model_path(settings.model_dir))
    result = enroll_embedding(embedder, clips)
    profile = OwnerVoiceProfile(
        profile_id=new_profile_id(),
        engine=engine.engine_id(),
        model_id=embedder.model_id,
        model_sha256=engine.MODEL_SHA256,
        embedding_dim=int(embedder.dim),
        sample_rate=int(embedder.sample_rate),
        enrollment_ms=result.voiced_ms,
        segments=result.segments,
        created_at=utc_now(),
        embedding=result.embedding,
        consistency=result.consistency,
    )
    save_profile(settings.profile_path, profile)
    return profile


def score_clip(settings: SpeakerVerifierSettings, samples: Any, rate: int) -> dict[str, object]:
    """Rejouer un enregistrement en fenêtres de 100 ms, comme la capture le ferait."""

    import numpy as np

    verifier = build_owner_verifier(settings)
    if verifier is None:
        raise RuntimeError(probe_owner_verifier(settings).message)
    verifier.reset()
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
    hop = int(rate) // 10
    scores: list[float] = []
    detected = 0
    first_ms: int | None = None
    for index in range(0, pcm.size - hop + 1, hop):
        verdict = verifier.process(pcm[index : index + hop].tobytes(), int(rate))
        if verdict.owner_score is not None:
            scores.append(float(verdict.owner_score))
            detected += int(verdict.owner_detected)
            if verdict.owner_detected and first_ms is None:
                first_ms = (index + hop) * 1000 // int(rate)
    verifier.close()
    return {
        "judged_hops": len(scores),
        "owner_detected_hops": detected,
        "score_max": round(max(scores), 3) if scores else None,
        "score_mean": round(sum(scores) / len(scores), 3) if scores else None,
        "first_detection_ms": first_ms,
        "threshold": verifier.threshold,
        "embeddings_computed": verifier.embeddings_computed,
    }


# -- ligne de commande ---------------------------------------------------------------


def add_parser(sub: Any) -> None:
    """Déclarer `jarvis owner-voice …` (appelé par `jarvis.app._parser`)."""

    owner = sub.add_parser("owner-voice", help="Enroll, show or delete the owner voice profile (speaker verification)")
    owner.add_argument("--profile", help="Owner profile path (default: owner_profile_path setting, else runtime)")
    commands = owner.add_subparsers(dest="owner_command", required=True)
    download = commands.add_parser("download-model", help="Download and verify the pinned speaker model")
    download.add_argument("--force", action="store_true")
    enroll_cmd = commands.add_parser("enroll", help="Enroll the owner from WAV files or the microphone")
    source = enroll_cmd.add_mutually_exclusive_group(required=True)
    source.add_argument("--wav", nargs="+", type=Path, help="PCM WAV file(s), any rate, mono or stereo")
    source.add_argument("--mic", action="store_true", help="Record from the configured input device")
    enroll_cmd.add_argument("--seconds", type=float, default=DEFAULT_ENROLL_SECONDS)
    enroll_cmd.add_argument("--replace", action="store_true", help="Replace an existing profile")
    commands.add_parser("show", help="Show profile metadata and verifier status (never the voiceprint)")
    commands.add_parser("delete", help="Delete the owner voice profile")
    score = commands.add_parser("score", help="Score a WAV file against the profile (shadow replay)")
    score.add_argument("wav", type=Path)


def run_cli(args: argparse.Namespace) -> int:
    from jarvis.audio.owner_verifier import EnrollmentError
    from jarvis.runtime.audio_devices import normalize_device_id
    from jarvis.v2_config import V2Settings

    runtime_root = V2Settings.load().runtime_root
    overrides = _control_settings(runtime_root)
    if getattr(args, "profile", None):
        overrides = {**overrides, "owner_profile_path": str(Path(args.profile).expanduser().resolve())}
    try:
        settings = parse_speaker_verifier_settings(overrides, runtime_root=runtime_root)
    except ConfigurationError as exc:
        print(f"Réglage invalide : {exc}", file=sys.stderr)
        return 2
    command = args.owner_command
    try:
        if command == "download-model":
            path = engine.download_model(settings.model_dir, force=args.force)
            print(f"Modèle vérifié : {path}\n  {engine.MODEL_ID} · SHA-256 {engine.MODEL_SHA256} · {engine.MODEL_LICENSE}")
            return 0
        if command == "show":
            probe = probe_owner_verifier(settings)
            print(json.dumps({"profile_path": str(settings.profile_path), **probe.payload()}, ensure_ascii=False, indent=2))
            return 0 if probe.availability is VerifierAvailability.READY else 1
        if command == "delete":
            removed = delete_profile(settings.profile_path)
            print(f"Profil supprimé : {settings.profile_path}" if removed else f"Aucun profil à supprimer ({settings.profile_path}).")
            return 0
        if not engine.engine_installed():
            print("sherpa-onnx n'est pas installé : pip install -e \".[speaker]\"", file=sys.stderr)
            return 2
        engine.verify_model(engine.model_path(settings.model_dir))
        if command == "score":
            samples, rate = read_wav(args.wav)
            print(json.dumps(score_clip(settings, samples, rate), ensure_ascii=False, indent=2))
            return 0
        if command == "enroll":
            if args.mic:
                device = normalize_device_id(overrides.get("audio_input_device"))
                print(_ENROLL_TEXT)
                input("Appuyez sur Entrée pour commencer l'enregistrement…")
                print(f"Enregistrement pendant {args.seconds:.0f} s…")
                clips = [record_microphone(args.seconds, device=device)]
                print("Enregistrement terminé (gardé en mémoire, jamais écrit sur disque).")
            else:
                clips = [read_wav(path) for path in args.wav]
            profile = enroll(settings, clips, replace=args.replace)
            print(f"Profil enrôlé : {settings.profile_path}")
            print(json.dumps(profile.metadata(), ensure_ascii=False, indent=2))
            if profile.consistency is not None and profile.consistency < 0.3:
                print("Attention : enregistrement peu homogène (plusieurs voix ou beaucoup de bruit ?) ; "
                      "envisagez de recommencer au calme.", file=sys.stderr)
            return 0
    except (EnrollmentError, OwnerProfileError, engine.SpeakerModelError) as exc:
        print(f"{exc} [{exc.code}]", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - remis à `_cli_failure`, qui relaie l'inconnu
        failure = _cli_failure(exc, command)
        if failure is None:
            raise
        code, message = failure
        print(f"{message} [{code}]", file=sys.stderr)
        return 1
    raise AssertionError(command)


class _NeverRaised(Exception):
    """Place-tenant : sounddevice absent, il n'y a pas de `PortAudioError` à attraper."""


def _portaudio_error() -> type[BaseException]:
    """`sounddevice.PortAudioError`, sans jamais importer sounddevice pour le savoir."""

    module = sys.modules.get("sounddevice")
    return getattr(module, "PortAudioError", _NeverRaised) if module is not None else _NeverRaised


def _cli_failure(exc: BaseException, command: str) -> tuple[str, str] | None:
    """Code stable et message opérateur d'une panne prévisible, ou `None` (inconnue).

    Les quatre pannes réelles de ces commandes — pas de réseau au
    `download-model`, micro déjà pris par Voice à l'`enroll --mic`, terminal
    sans clavier, bibliothèque audio absente — doivent dire quoi faire, comme
    partout ailleurs dans ce module. Tout le reste remonte tel quel : une
    trace d'appels vaut mieux qu'un code inventé.
    """

    if isinstance(exc, URLError):
        return (
            "speaker_model_download_failed",
            f"Modèle non téléchargé ({engine.MODEL_URL}) : {exc.reason}. Vérifiez la connexion réseau "
            f"(ou le proxy), puis relancez « {_PYTHON} -m jarvis owner-voice download-model ».",
        )
    if isinstance(exc, EOFError):
        return (
            "enrollment_aborted",
            "Enrôlement abandonné : ce terminal n'a pas d'entrée clavier. Relancez la commande dans une "
            "console interactive.",
        )
    if isinstance(exc, ImportError):
        return (
            "enrollment_audio_unavailable",
            f"Bibliothèque audio absente ({getattr(exc, 'name', None) or exc}) : {_PYTHON} -m pip install -e \".[voice]\".",
        )
    if isinstance(exc, (_portaudio_error(), OSError)):
        if command == "download-model":
            return (
                "speaker_model_download_failed",
                f"Modèle non téléchargé ({engine.MODEL_URL}) : {type(exc).__name__} — {exc}. Réessayez.",
            )
        if command == "enroll":
            return (
                "enrollment_device_unavailable",
                f"Micro indisponible ({type(exc).__name__} — {exc}) : arrêtez Voice (le micro ne se partage pas), "
                "vérifiez le périphérique d'entrée, puis recommencez.",
            )
    return None


def _control_settings(runtime_root: Path) -> dict[str, object]:
    path = Path(runtime_root) / "control-center-settings.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
