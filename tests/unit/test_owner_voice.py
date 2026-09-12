"""Tâche 03 Solo Owner : profil du propriétaire et premier vérificateur local.

Les tests déterministes n'ont besoin ni du modèle ni de sherpa-onnx : un faux
moteur d'empreinte (bandes spectrales) suffit à éprouver la fenêtre glissante,
la normalisation du score, le seuil et le cycle de vie du profil. Le test du
moteur réel, en fin de fichier, est sauté si le moteur, le modèle ou la
synthèse vocale Windows manquent — aucun enregistrement privé n'est versionné.
"""

from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types
import urllib.error
import urllib.request
import wave

import numpy as np
import pytest

from jarvis import app
from jarvis.adapters import file_replace
from jarvis.adapters import sherpa_model_catalog as catalog
from jarvis.adapters import sherpa_speaker_embedder as engine
from jarvis.adapters.owner_voice_profile import (
    OwnerProfileError,
    OwnerVoiceProfile,
    delete_profile,
    load_profile,
    save_profile,
)
from jarvis.audio.owner_verifier import (
    EmbeddingSpeakerVerifier,
    EnrollmentError,
    SpeechGate,
    enroll_embedding,
    owner_score_from_cosine,
    resample,
)
from jarvis.audio.duplex import CaptureFrameContext
from jarvis.audio.speaker_shadow import OWNER_CONFIRMED, OWNER_UNAVAILABLE, SpeakerVerificationWorker
from jarvis.domain.speaker import ConversationAuthorizationError, VerificationStatus, VerifierAvailability
from jarvis.runtime import owner_voice
from jarvis.runtime.control_center import ControlCenter
from jarvis.v2_config import (
    DEFAULT_OWNER_EVIDENCE_MS,
    OWNER_PROFILE_FILENAME,
    SPEAKER_VERIFICATION_DIRNAME,
    SpeakerVerifierSettings,
    parse_speaker_verifier_settings,
)

ROOT = Path(__file__).resolve().parents[2]
RATE = 24_000  # fréquence de capture de la pile OpenAI
HOP_MS = 100


# ===========================================================================
# Faux moteur et signaux
# ===========================================================================


class BandEmbedder:
    """Empreinte = énergie de 16 bandes spectrales : deux « voix » = deux tons."""

    model_id = "fake-bands"
    dim = 16
    sample_rate = 16_000

    def __init__(self) -> None:
        self.loads = 0
        self.calls: list[int] = []

    def load(self) -> None:
        self.loads += 1

    def embed(self, samples: np.ndarray) -> np.ndarray:
        self.calls.append(int(samples.size))
        spectrum = np.abs(np.fft.rfft(samples.astype(np.float64))) ** 2
        return np.sqrt(np.array([band.sum() for band in np.array_split(spectrum[1:], self.dim)]))


class CosineEmbedder:
    """Rend un vecteur de similarité cosinus choisie avec `e0` (le propriétaire)."""

    model_id = "fake-cosine"
    dim = 4
    sample_rate = 16_000

    def __init__(self, cosine: float) -> None:
        self.cosine = cosine

    def embed(self, samples: np.ndarray) -> np.ndarray:
        del samples
        c = self.cosine
        return np.array([c, math.sqrt(max(0.0, 1.0 - c * c)), 0.0, 0.0])


OWNER_HZ = 300.0
STRANGER_HZ = 2600.0


def tone(freq: float, ms: int, rate: int = RATE, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(rate * ms // 1000) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(ms: int, rate: int = RATE) -> np.ndarray:
    return np.zeros(rate * ms // 1000, dtype=np.float32)


def pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def hops(samples: np.ndarray, rate: int = RATE, hop_ms: int = HOP_MS) -> list[bytes]:
    size = rate * hop_ms // 1000
    return [pcm(samples[i : i + size]) for i in range(0, samples.size - size + 1, size)]


def owner_vector(embedder: BandEmbedder) -> np.ndarray:
    return embedder.embed(resample(tone(OWNER_HZ, 1000), RATE, 16_000))


def verifier_for(embedder=None, **kwargs) -> EmbeddingSpeakerVerifier:  # noqa: ANN001
    embedder = embedder or BandEmbedder()
    owner = kwargs.pop("owner", None)
    if owner is None:
        owner = owner_vector(embedder) if isinstance(embedder, BandEmbedder) else [1.0, 0.0, 0.0, 0.0]
    kwargs.setdefault("threshold", 0.5)
    return EmbeddingSpeakerVerifier(embedder, owner, engine="fake-engine/1", profile_id="owner-test", **kwargs)


def feed(verifier: EmbeddingSpeakerVerifier, samples: np.ndarray, rate: int = RATE):  # noqa: ANN201
    return [verifier.process(chunk, rate) for chunk in hops(samples, rate)]


def make_profile(**overrides) -> OwnerVoiceProfile:  # noqa: ANN003
    values = dict(
        profile_id="owner-abcd1234",
        engine="sherpa-onnx/1.13.8",
        model_id=engine.MODEL_ID,
        model_sha256=engine.MODEL_SHA256,
        embedding_dim=engine.MODEL_DIM,
        sample_rate=engine.MODEL_SAMPLE_RATE,
        enrollment_ms=21_000,
        segments=7,
        created_at="2026-09-11T14:00:00+00:00",
        embedding=tuple(float(i + 1) / 1000.0 for i in range(engine.MODEL_DIM)),
        consistency=0.8,
    )
    values.update(overrides)
    return OwnerVoiceProfile(**values)


def keys_and_lists(value, found=None):  # noqa: ANN001, ANN201
    """Toutes les clés et toutes les listes numériques d'une charge utile JSON."""

    found = found if found is not None else {"keys": set(), "numeric_lists": []}
    if isinstance(value, dict):
        for key, item in value.items():
            found["keys"].add(key)
            keys_and_lists(item, found)
    elif isinstance(value, list):
        if value and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            found["numeric_lists"].append(value)
        for item in value:
            keys_and_lists(item, found)
    return found


# ===========================================================================
# Réglages
# ===========================================================================


def test_default_settings_live_under_the_git_ignored_runtime_dir(tmp_path):
    settings = parse_speaker_verifier_settings({}, runtime_root=tmp_path)

    assert settings.profile_path == tmp_path / SPEAKER_VERIFICATION_DIRNAME / OWNER_PROFILE_FILENAME
    assert settings.model_dir == tmp_path / SPEAKER_VERIFICATION_DIRNAME / "models"
    assert settings.threshold is None
    assert settings.evidence_ms == DEFAULT_OWNER_EVIDENCE_MS


def test_explicit_settings_are_parsed(tmp_path):
    absolute = tmp_path / "ailleurs" / "moi.json"
    settings = parse_speaker_verifier_settings(
        {"owner_threshold": "0.62", "owner_evidence_ms": 2000, "owner_profile_path": str(absolute)},
        runtime_root=tmp_path,
    )
    relative = parse_speaker_verifier_settings({"owner_profile_path": "profils/moi.json"}, runtime_root=tmp_path)

    assert (settings.threshold, settings.evidence_ms, settings.profile_path) == (0.62, 2000, absolute)
    assert relative.profile_path == tmp_path / "profils" / "moi.json"


@pytest.mark.parametrize(
    "values, code",
    [
        ({"owner_threshold": "0"}, "owner_threshold_invalid"),
        ({"owner_threshold": 1.5}, "owner_threshold_invalid"),
        ({"owner_threshold": "beaucoup"}, "owner_threshold_invalid"),
        ({"owner_threshold": True}, "owner_threshold_invalid"),
        ({"owner_threshold": "nan"}, "owner_threshold_invalid"),
        ({"owner_evidence_ms": 100}, "owner_evidence_invalid"),
        ({"owner_evidence_ms": 9000}, "owner_evidence_invalid"),
        ({"owner_evidence_ms": "1500.5"}, "owner_evidence_invalid"),
        ({"owner_profile_path": 42}, "owner_profile_path_invalid"),
    ],
)
def test_invalid_settings_are_refused_with_a_stable_code(tmp_path, values, code):
    with pytest.raises(ConversationAuthorizationError) as caught:
        parse_speaker_verifier_settings(values, runtime_root=tmp_path)
    assert caught.value.code == code


@pytest.mark.parametrize("value", ["../../empreinte.json", "..", "~/empreinte.json"])
def test_a_profile_path_that_leaves_the_ignored_runtime_dir_is_refused(tmp_path, value):
    """L'empreinte vocale est biométrique : elle ne sort pas du dossier ignoré par Git."""

    runtime = tmp_path / "runtime"

    with pytest.raises(ConversationAuthorizationError) as caught:
        parse_speaker_verifier_settings({"owner_profile_path": value}, runtime_root=runtime)
    assert caught.value.code == "owner_profile_path_outside_runtime"


def test_an_absolute_profile_path_outside_the_runtime_dir_is_refused_too(tmp_path):
    outside = tmp_path / "ailleurs" / "empreinte.json"

    with pytest.raises(ConversationAuthorizationError) as caught:
        parse_speaker_verifier_settings({"owner_profile_path": str(outside)}, runtime_root=tmp_path / "runtime")
    assert caught.value.code == "owner_profile_path_outside_runtime"
    # Un chemin qui reste dedans passe, relatif comme absolu.
    inside = parse_speaker_verifier_settings(
        {"owner_profile_path": "profils/../moi.json"}, runtime_root=tmp_path / "runtime"
    )
    assert inside.profile_path.name == "moi.json"


# ===========================================================================
# Profil
# ===========================================================================


def test_a_profile_round_trips_and_never_shows_its_voiceprint(tmp_path):
    path = tmp_path / "p" / "owner.json"
    profile = make_profile()

    save_profile(path, profile)
    loaded = load_profile(path)

    assert loaded == profile
    assert "embedding=" not in repr(loaded)
    assert "embedding" not in loaded.metadata()
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "content",
    [
        "{ pas du json",
        json.dumps({"kind": "autre chose", "schema": 1}),
        json.dumps({"kind": "jarvis.owner_voice_profile", "schema": 99}),
        "[]",
    ],
)
def test_a_corrupt_profile_is_reported_never_used(tmp_path, content):
    path = tmp_path / "owner.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(OwnerProfileError) as caught:
        load_profile(path)
    assert caught.value.code == "owner_profile_corrupt"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(embedding=p["embedding"][:-1]),
        lambda p: p.update(embedding=["x"] * len(p["embedding"])),
        lambda p: p.update(embedding=[0.0] * len(p["embedding"])),
        lambda p: p.update(profile_id=""),
        lambda p: p.update(embedding_dim=-3),
    ],
)
def test_a_tampered_profile_is_corrupt_and_the_error_does_not_leak_values(tmp_path, mutate):
    path = tmp_path / "owner.json"
    save_profile(path, make_profile())
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OwnerProfileError) as caught:
        load_profile(path)
    assert caught.value.code == "owner_profile_corrupt"
    assert "0.001" not in str(caught.value)


def test_a_missing_profile_has_its_own_code(tmp_path):
    with pytest.raises(OwnerProfileError) as caught:
        load_profile(tmp_path / "absent.json")
    assert caught.value.code == "owner_profile_missing"


def test_incompatibility_is_explained_per_model_dimension_and_rate():
    profile = make_profile()
    same = dict(model_sha256=engine.MODEL_SHA256, embedding_dim=engine.MODEL_DIM, sample_rate=engine.MODEL_SAMPLE_RATE)

    assert profile.incompatibility(**same) is None
    assert "autre modèle" in profile.incompatibility(**{**same, "model_sha256": "0" * 64})
    assert "dimension" in profile.incompatibility(**{**same, "embedding_dim": 512})
    assert "Hz" in profile.incompatibility(**{**same, "sample_rate": 8000})


class FakeResponse:
    """Réponse HTTP en mémoire : le téléchargement n'atteint jamais le réseau."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:  # noqa: ANN002
        return False

    def read(self, size: int = -1) -> bytes:
        chunk = self.payload[self.offset :] if size is None or size < 0 else self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class FlakyReplace:
    """`os.replace` qui refuse l'accès les `failures` premières fois (Windows : antivirus, indexeur)."""

    def __init__(self, failures: int) -> None:
        self.failures = int(failures)
        self.calls = 0
        self.real = os.replace

    def __call__(self, source, target):  # noqa: ANN001, ANN204
        self.calls += 1
        if self.calls <= self.failures:
            raise PermissionError(13, "Access is denied", str(target), 5)
        return self.real(source, target)


@pytest.fixture()
def no_replace_backoff(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_S", 0.0)
    monkeypatch.setattr(file_replace, "REPLACE_BACKOFF_MAX_S", 0.0)


def test_saving_a_profile_survives_a_target_briefly_held_by_windows(tmp_path, monkeypatch, no_replace_backoff):
    path = tmp_path / "owner.json"
    flaky = FlakyReplace(file_replace.REPLACE_ATTEMPTS - 1)
    monkeypatch.setattr(os, "replace", flaky)
    profile = make_profile()

    save_profile(path, profile)

    assert flaky.calls == file_replace.REPLACE_ATTEMPTS
    assert load_profile(path) == profile
    assert not list(path.parent.glob("*.tmp"))


def test_a_profile_that_cannot_be_replaced_fails_with_a_code_and_keeps_the_old_one(
    tmp_path, monkeypatch, no_replace_backoff
):
    path = tmp_path / "owner.json"
    previous = make_profile(profile_id="owner-previous")
    save_profile(path, previous)
    flaky = FlakyReplace(file_replace.REPLACE_ATTEMPTS + 1)
    monkeypatch.setattr(os, "replace", flaky)

    with pytest.raises(OwnerProfileError) as caught:
        save_profile(path, make_profile(profile_id="owner-new"))

    assert caught.value.code == "owner_profile_write_failed"
    assert flaky.calls == file_replace.REPLACE_ATTEMPTS
    # Atomicité : jamais d'écriture en place, l'ancien profil reste lisible.
    assert load_profile(path) == previous
    assert not list(path.parent.glob("*.tmp"))


def test_a_model_download_retries_the_install_then_reports_a_code(tmp_path, monkeypatch, no_replace_backoff):
    payload = b"modele-factice"
    monkeypatch.setattr(engine, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(payload))
    flaky = FlakyReplace(file_replace.REPLACE_ATTEMPTS - 1)
    monkeypatch.setattr(os, "replace", flaky)

    path = engine.download_model(tmp_path)

    assert path.read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))

    monkeypatch.setattr(os, "replace", FlakyReplace(file_replace.REPLACE_ATTEMPTS + 1))
    with pytest.raises(engine.SpeakerModelError) as caught:
        engine.download_model(tmp_path, force=True)
    assert caught.value.code == "speaker_model_install_failed"
    assert not list(tmp_path.glob("*.part"))


class CountingResponse(FakeResponse):
    """Réponse dont on mesure ce qui a réellement été lu du réseau."""


def test_a_download_stops_at_the_pinned_size_instead_of_filling_the_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "MODEL_SIZE", 1 << 20)
    response = CountingResponse(bytes(8 << 20))  # le serveur en sert huit fois trop
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=None: response)

    with pytest.raises(engine.SpeakerModelError) as caught:
        engine.download_model(tmp_path)

    assert caught.value.code == "speaker_model_mismatch"
    assert response.offset <= engine.MODEL_SIZE + (1 << 20)  # un bloc de dépassement, pas huit
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.onnx"))


def test_a_catalog_download_stops_at_the_pinned_size_too(tmp_path, monkeypatch):
    spec = replace(catalog.MODELS[0], size=1 << 20)
    response = CountingResponse(bytes(8 << 20))
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=None: response)

    with pytest.raises(catalog.SpeakerModelError) as caught:
        catalog.download_spec(spec, tmp_path)

    assert caught.value.code == "speaker_model_mismatch"
    assert response.offset <= spec.size + (1 << 20)
    assert not list(tmp_path.glob("*.part"))


def test_a_catalog_download_installs_through_the_same_retry(tmp_path, monkeypatch, no_replace_backoff):
    payload = b"modele-de-catalogue"
    spec = replace(catalog.MODELS[0], sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(payload))
    flaky = FlakyReplace(2)
    monkeypatch.setattr(os, "replace", flaky)

    path = catalog.download_spec(spec, tmp_path)

    assert path.read_bytes() == payload and flaky.calls == 3
    assert not list(tmp_path.glob("*.part"))


def test_deleting_a_profile(tmp_path):
    path = tmp_path / "owner.json"
    save_profile(path, make_profile())

    assert delete_profile(path) is True
    assert not path.exists()
    assert delete_profile(path) is False


# ===========================================================================
# Sonde (Control Center) : jamais de chargement du modèle
# ===========================================================================


@pytest.fixture
def model_ready(tmp_path, monkeypatch):
    """Moteur « installé » et fichier modèle de la bonne taille (zéros, jamais chargé).

    La sonde vérifie aussi l'empreinte du fichier : le SHA-256 épinglé est celui
    de ces zéros, faute du vrai modèle de 27 Mio dans les tests.
    """

    monkeypatch.setattr(engine, "engine_installed", lambda: True)
    monkeypatch.setattr(engine, "engine_version", lambda: "1.13.8")
    settings = parse_speaker_verifier_settings({}, runtime_root=tmp_path)
    settings.model_dir.mkdir(parents=True)
    model = engine.model_path(settings.model_dir)
    with model.open("wb") as handle:
        handle.truncate(engine.MODEL_SIZE)
    monkeypatch.setattr(engine, "MODEL_SHA256", engine.cached_file_sha256(model))
    return settings


def test_probe_without_the_engine_says_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "engine_installed", lambda: False)
    probe = owner_voice.probe_owner_verifier(parse_speaker_verifier_settings({}, runtime_root=tmp_path))

    assert (probe.availability, probe.code) == (VerifierAvailability.NOT_INSTALLED, "speaker_engine_not_installed")


def test_probe_without_the_model_says_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "engine_installed", lambda: True)
    probe = owner_voice.probe_owner_verifier(parse_speaker_verifier_settings({}, runtime_root=tmp_path))

    assert (probe.availability, probe.code) == (VerifierAvailability.NOT_INSTALLED, "speaker_model_missing")
    assert "download-model" in probe.message


def test_probe_with_a_truncated_model_says_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "engine_installed", lambda: True)
    settings = parse_speaker_verifier_settings({}, runtime_root=tmp_path)
    settings.model_dir.mkdir(parents=True)
    engine.model_path(settings.model_dir).write_bytes(b"pas un modele")

    probe = owner_voice.probe_owner_verifier(settings)
    assert (probe.availability, probe.code) == (VerifierAvailability.FAILED, "speaker_model_mismatch")


def test_probe_without_profile_then_corrupt_then_incompatible_then_ready(model_ready):
    settings = model_ready
    missing = owner_voice.probe_owner_verifier(settings)
    settings.profile_path.write_text("{", encoding="utf-8")
    corrupt = owner_voice.probe_owner_verifier(settings)
    save_profile(settings.profile_path, make_profile(model_sha256="f" * 64))
    incompatible = owner_voice.probe_owner_verifier(settings)
    save_profile(settings.profile_path, make_profile())
    ready = owner_voice.probe_owner_verifier(settings)

    assert (missing.availability, missing.code) == (VerifierAvailability.NO_OWNER_PROFILE, "owner_profile_missing")
    assert (corrupt.availability, corrupt.code) == (VerifierAvailability.NO_OWNER_PROFILE, "owner_profile_corrupt")
    assert (incompatible.availability, incompatible.code) == (
        VerifierAvailability.NO_OWNER_PROFILE,
        "owner_profile_incompatible",
    )
    assert (ready.availability, ready.code, ready.engine) == (VerifierAvailability.READY, "ready", "sherpa-onnx/1.13.8")
    assert ready.profile["profile_id"] == "owner-abcd1234"
    found = keys_and_lists(ready.payload())
    assert "embedding" not in found["keys"] and not found["numeric_lists"]


def test_a_model_of_the_right_size_but_wrong_content_is_never_ready(tmp_path, monkeypatch):
    """Un modèle corrompu ne doit pas afficher « Solo Owner appliqué » alors que Voice le refusera."""

    monkeypatch.setattr(engine, "engine_installed", lambda: True)
    settings = parse_speaker_verifier_settings({}, runtime_root=tmp_path)
    settings.model_dir.mkdir(parents=True)
    with engine.model_path(settings.model_dir).open("wb") as handle:
        handle.truncate(engine.MODEL_SIZE)  # la bonne taille, 27 Mio de zéros
    save_profile(settings.profile_path, make_profile())

    probe = owner_voice.probe_owner_verifier(settings)

    assert (probe.availability, probe.code) == (VerifierAvailability.FAILED, "speaker_model_mismatch")
    assert owner_voice.probe_remedy(probe.code).endswith("download-model --force")


def test_the_model_fingerprint_is_read_once_for_repeated_probes(model_ready, monkeypatch):
    """`GET /api/settings` sonde sans cesse : relire 27 Mio à chaque fois serait inacceptable."""

    reads: list[Path] = []
    real = engine.file_sha256
    monkeypatch.setattr(engine, "file_sha256", lambda path: reads.append(Path(path)) or real(path))
    save_profile(model_ready.profile_path, make_profile())
    engine._SHA256_CACHE.clear()

    states = [owner_voice.probe_owner_verifier(model_ready).availability for _ in range(4)]

    # Une lecture réelle du fichier (la sonde vérifie bien le contenu), une seule.
    assert states == [VerifierAvailability.READY] * 4
    assert reads == [engine.model_path(model_ready.model_dir)]


def test_probe_from_invalid_settings_is_a_state_not_a_crash(tmp_path):
    probe = owner_voice.probe_from_settings({"owner_threshold": "-1"}, runtime_root=tmp_path)

    assert (probe.availability, probe.code) == (VerifierAvailability.FAILED, "owner_threshold_invalid")


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


async def test_the_control_center_reports_the_real_verifier_without_biometrics(model_ready, tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    # Tâche 07 : Solo Owner n'existe qu'en continuous_brain, le Control Center le dit comme Voice.
    await control.save_settings(
        JsonRequest({"voice": {"arch": "continuous_brain", "authorization": {"conversation_mode": "solo_owner"}}})
    )

    before = json.loads((await control.get_settings(None)).text)["voice"]["authorization"]
    save_profile(model_ready.profile_path, make_profile())
    response = await control.get_settings(None)
    after = json.loads(response.text)["voice"]["authorization"]

    assert (before["verifier"], before["status"]) == ("no_owner_profile", "refused")
    assert before["verifier_detail"]["code"] == "owner_profile_missing"
    assert (after["verifier"], after["status"]) == ("ready", "ready")
    assert after["verifier_detail"]["profile"]["profile_id"] == "owner-abcd1234"
    found = keys_and_lists(json.loads(response.text))
    assert "embedding" not in found["keys"]
    assert not any(len(values) == engine.MODEL_DIM for values in found["numeric_lists"])


# ===========================================================================
# Normalisation et seuil
# ===========================================================================


@pytest.mark.parametrize("cosine, score", [(-0.7, 0.0), (0.0, 0.0), (0.42, 0.42), (1.3, 1.0), (math.nan, 0.0)])
def test_the_cosine_is_clipped_onto_the_common_score_scale(cosine, score):
    assert owner_score_from_cosine(cosine) == pytest.approx(score)


@pytest.mark.parametrize("cosine, detected", [(0.49, False), (0.5, True), (0.9, True), (-0.4, False)])
def test_the_threshold_decides_owner_detected(cosine, detected):
    verifier = verifier_for(CosineEmbedder(cosine), threshold=0.5, evidence_ms=500)
    verdict = feed(verifier, tone(OWNER_HZ, 600))[-1]

    assert verdict.status is VerificationStatus.OK
    assert verdict.owner_detected is detected
    assert verdict.owner_score == pytest.approx(max(0.0, cosine))


def test_the_owner_tone_is_recognised_and_the_stranger_is_not():
    owner = feed(verifier_for(), tone(OWNER_HZ, 3000))
    stranger = feed(verifier_for(), tone(STRANGER_HZ, 3000))

    assert owner[-1].owner_detected and owner[-1].owner_score > 0.95
    assert not stranger[-1].owner_detected and stranger[-1].owner_score < 0.1
    assert owner[-1].engine == "fake-engine/1" and owner[-1].profile_id == "owner-test"


def test_invalid_construction_is_refused():
    with pytest.raises(ValueError):
        verifier_for(threshold=0.0)
    with pytest.raises(ValueError):
        verifier_for(owner=[1.0, 0.0])
    with pytest.raises(ValueError):
        verifier_for(evidence_ms=5)


# ===========================================================================
# Fenêtre glissante
# ===========================================================================


def test_silence_is_insufficient_audio_never_a_verdict():
    verdicts = feed(verifier_for(), silence(3000))

    assert {v.status for v in verdicts} == {VerificationStatus.INSUFFICIENT_AUDIO}
    assert all(v.owner_score is None for v in verdicts)


def test_no_verdict_before_the_evidence_window_is_full():
    embedder = BandEmbedder()
    verifier = verifier_for(embedder, evidence_ms=1500)
    verdicts = feed(verifier, tone(OWNER_HZ, 2000))
    statuses = [v.status for v in verdicts]

    first_ok = statuses.index(VerificationStatus.OK)
    assert first_ok == 14  # 15e fenêtre de 100 ms : 1500 ms de parole
    assert all(s is VerificationStatus.INSUFFICIENT_AUDIO for s in statuses[:first_ok])
    assert verdicts[first_ok].evidence_ms == 1500
    assert [v.evidence_ms for v in verdicts[:3]] == [100, 200, 300]


def test_the_engine_runs_once_per_stride_and_the_verdict_is_reused_in_between():
    embedder = BandEmbedder()
    verifier = verifier_for(embedder, evidence_ms=1000, stride_ms=500)
    feed(verifier, tone(OWNER_HZ, 5000))

    # Premier verdict à 1 s, puis un calcul par 500 ms de parole nouvelle.
    assert verifier.embeddings_computed == 1 + (5000 - 1000) // 500
    assert set(embedder.calls) == {16_000}  # toujours 1 s ramenée à 16 kHz


def test_the_window_stays_bounded_during_long_speech():
    verifier = verifier_for(evidence_ms=1500)
    feed(verifier, tone(OWNER_HZ, 20_000))

    assert 1500 <= verifier.voiced_ms <= 1500 + 20
    assert sum(frame.size for frame in verifier._voiced) <= RATE * 1520 // 1000


def test_a_short_pause_keeps_the_verdict_a_long_silence_clears_the_evidence():
    verifier = verifier_for(evidence_ms=1000, max_gap_ms=600)
    feed(verifier, tone(OWNER_HZ, 1500))
    pause = feed(verifier, silence(300))
    gap = feed(verifier, silence(700))

    assert all(v.status is VerificationStatus.OK for v in pause)
    assert gap[-1].status is VerificationStatus.INSUFFICIENT_AUDIO
    assert verifier.voiced_ms == 0


def test_a_stranger_after_the_owner_does_not_inherit_the_owner_evidence():
    verifier = verifier_for(evidence_ms=1000)
    feed(verifier, tone(OWNER_HZ, 2000))
    feed(verifier, silence(800))
    verdicts = feed(verifier, tone(STRANGER_HZ, 1500))

    judged = [v for v in verdicts if v.status is VerificationStatus.OK]
    assert judged and not any(v.owner_detected for v in judged)


def test_the_window_slides_from_stranger_to_owner_during_continuous_speech():
    """D06 : pas de segment verrouillé, le propriétaire finit par être reconnu."""

    verifier = verifier_for(evidence_ms=1000, stride_ms=300)
    stranger = feed(verifier, tone(STRANGER_HZ, 2000))
    owner = feed(verifier, tone(OWNER_HZ, 2000))

    assert not stranger[-1].owner_detected
    assert owner[-1].owner_detected


def test_reset_forgets_the_evidence_and_preloads_the_engine():
    embedder = BandEmbedder()
    verifier = verifier_for(embedder, evidence_ms=500)
    feed(verifier, tone(OWNER_HZ, 1000))
    verifier.reset()

    assert embedder.loads == 1
    assert verifier.voiced_ms == 0
    assert verifier.process(hops(tone(OWNER_HZ, 100))[0], RATE).status is VerificationStatus.INSUFFICIENT_AUDIO


def test_a_sample_rate_change_restarts_the_evidence():
    verifier = verifier_for(evidence_ms=500)
    feed(verifier, tone(OWNER_HZ, 1000))
    verdict = feed(verifier, tone(OWNER_HZ, 100, rate=16_000), rate=16_000)[-1]

    assert verdict.status is VerificationStatus.INSUFFICIENT_AUDIO
    assert verdict.evidence_ms == 100


def test_an_engine_returning_the_wrong_dimension_raises():
    class Broken(BandEmbedder):
        def embed(self, samples):  # noqa: ANN001, ANN201
            return np.ones(3)

    verifier = EmbeddingSpeakerVerifier(Broken(), np.ones(16), engine="x/1", profile_id="p", threshold=0.5, evidence_ms=500)
    with pytest.raises(ValueError):
        feed(verifier, tone(OWNER_HZ, 600))


def test_the_speech_gate_ignores_low_noise_but_passes_speech_after_it():
    gate = SpeechGate()
    noise = [gate.update(-65.0 + (i % 3)) for i in range(100)]

    assert not any(noise)
    assert gate.update(-30.0)


def test_resampling_keeps_duration_and_pitch():
    out = resample(tone(1000.0, 1000, rate=24_000), 24_000, 16_000)
    peak_hz = np.argmax(np.abs(np.fft.rfft(out))) * 16_000 / out.size

    assert out.size == 16_000
    assert peak_hz == pytest.approx(1000.0, abs=2.0)
    assert resample(out, 16_000, 16_000) is not None


# ===========================================================================
# Ombre : le vrai fil du vérificateur, sans empreinte dans le journal
# ===========================================================================


class ListJournal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, dict(data or {})))


def test_the_adapter_confirms_the_owner_through_the_shadow_worker():
    journal = ListJournal()
    embedder = BandEmbedder()
    worker = SpeakerVerificationWorker(verifier_for(embedder), sample_rate=RATE, diagnostics=journal, max_pending_ms=10_000)
    try:
        worker.reset()
        samples = pcm(tone(OWNER_HZ, 3000))
        frame = RATE // 100 * 2
        for index in range(0, len(samples), frame):
            # Parole proche, JARVIS silencieux : ce que la capture dirait.
            context = CaptureFrameContext(
                stream_ms=index // frame * 10, sample_rate=RATE, near_end=True, far_end=False,
                near_end_latched=False, gate_open=True,
            )
            worker.observe(samples[index : index + frame], context)
        assert worker.flush(timeout=10)
    finally:
        worker.close()

    kinds = [kind for kind, _, _ in journal.events]
    assert OWNER_CONFIRMED in kinds
    assert embedder.loads == 1
    for _, _, data in journal.events:
        found = keys_and_lists(data)
        assert "embedding" not in found["keys"] and not found["numeric_lists"]


# ===========================================================================
# Enrôlement
# ===========================================================================


def test_enrolling_silence_or_too_little_speech_is_refused():
    embedder = BandEmbedder()
    with pytest.raises(EnrollmentError) as silent:
        enroll_embedding(embedder, [(silence(20_000), RATE)])
    with pytest.raises(EnrollmentError) as short:
        enroll_embedding(embedder, [(tone(OWNER_HZ, 4000), RATE), (silence(10_000), RATE)])

    assert silent.value.code == "enrollment_no_speech"
    assert short.value.code == "enrollment_too_short"


def test_enrollment_averages_segments_into_a_unit_voiceprint():
    embedder = BandEmbedder()
    result = enroll_embedding(embedder, [(tone(OWNER_HZ, 7000), RATE), (tone(OWNER_HZ, 5000, rate=48_000), 48_000)])

    assert result.voiced_ms == pytest.approx(12_000, abs=40)
    assert result.segments == 4
    assert np.linalg.norm(result.embedding) == pytest.approx(1.0)
    assert result.consistency > 0.99


def test_enroll_writes_a_compatible_profile_and_refuses_to_overwrite(model_ready):
    settings = model_ready
    embedder = BandEmbedder()

    profile = owner_voice.enroll(settings, [(tone(OWNER_HZ, 12_000), RATE)], embedder=embedder)
    with pytest.raises(EnrollmentError) as caught:
        owner_voice.enroll(settings, [(tone(OWNER_HZ, 12_000), RATE)], embedder=embedder)
    replaced = owner_voice.enroll(settings, [(tone(OWNER_HZ, 12_000), RATE)], embedder=embedder, replace=True)

    assert load_profile(settings.profile_path) == replaced != profile
    assert caught.value.code == "owner_profile_exists"
    # Profil de dimension 16 : incompatible avec le modèle réel (192), donc refusé.
    probe = owner_voice.probe_owner_verifier(settings)
    assert (probe.availability, probe.code) == (VerifierAvailability.NO_OWNER_PROFILE, "owner_profile_incompatible")


def test_build_owner_verifier_uses_the_profile_and_the_configured_threshold(model_ready, tmp_path):
    save_profile(model_ready.profile_path, make_profile())
    journal = ListJournal()
    settings = parse_speaker_verifier_settings({"owner_threshold": "0.7", "owner_evidence_ms": 800}, runtime_root=tmp_path)

    class Real192(BandEmbedder):
        dim = engine.MODEL_DIM

    verifier = owner_voice.build_owner_verifier(settings, journal=journal, embedder=Real192())

    assert (verifier.threshold, verifier.evidence_ms, verifier.profile_id) == (0.7, 800, "owner-abcd1234")
    assert verifier.engine == "sherpa-onnx/1.13.8"
    kind, level, data = journal.events[-1]
    assert (kind, level, data["model_id"]) == ("voice.owner.engine", "info", engine.MODEL_ID)
    assert "embedding" not in data


def _write_wav(path: Path, samples: np.ndarray, rate: int, *, channels: int = 1, width: int = 2) -> None:
    data = np.repeat(samples[:, None], channels, axis=1).reshape(-1)
    if width == 1:
        raw = (np.clip(data, -1, 1) * 127 + 128).astype(np.uint8).tobytes()
    elif width == 2:
        raw = (np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()
    else:
        ints = (np.clip(data, -1, 1) * (2**23 - 1)).astype("<i4")
        raw = b"".join(int(v).to_bytes(4, "little", signed=True)[:3] for v in ints)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(raw)


@pytest.mark.parametrize("width, channels, rate", [(2, 2, 48_000), (1, 1, 8_000), (3, 1, 16_000), (2, 1, 24_000)])
def test_wav_input_is_converted_to_mono_float(tmp_path, width, channels, rate):
    path = tmp_path / "clip.wav"
    source = tone(440.0, 500, rate=rate, amplitude=0.5)
    _write_wav(path, source, rate, channels=channels, width=width)

    samples, got_rate = owner_voice.read_wav(path)

    assert got_rate == rate and samples.dtype == np.float32 and samples.ndim == 1
    assert samples.size == source.size
    assert np.max(np.abs(samples - source)) < 0.02


def test_a_non_pcm_wav_is_refused_with_a_code(tmp_path):
    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEpas un wav")

    with pytest.raises(EnrollmentError) as caught:
        owner_voice.read_wav(path)
    assert caught.value.code == "enrollment_unsupported_wav"


# ===========================================================================
# Ligne de commande
# ===========================================================================


def test_the_cli_is_declared_on_the_jarvis_entry_point():
    args = app._parser().parse_args(["owner-voice", "enroll", "--wav", "a.wav", "b.wav"])

    assert (args.command, args.owner_command, [p.name for p in args.wav]) == ("owner-voice", "enroll", ["a.wav", "b.wav"])
    assert app._parser().parse_args(["owner-voice", "enroll", "--mic"]).seconds == owner_voice.DEFAULT_ENROLL_SECONDS
    with pytest.raises(SystemExit):
        app._parser().parse_args(["owner-voice", "enroll"])


def test_cli_show_and_delete_never_print_the_voiceprint(model_ready, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    save_profile(model_ready.profile_path, make_profile())

    shown = owner_voice.run_cli(app._parser().parse_args(["owner-voice", "show"]))
    show_out = capsys.readouterr().out
    deleted = owner_voice.run_cli(app._parser().parse_args(["owner-voice", "delete"]))
    delete_out = capsys.readouterr().out
    missing = owner_voice.run_cli(app._parser().parse_args(["owner-voice", "show"]))

    assert (shown, deleted, missing) == (0, 0, 1)
    assert json.loads(show_out)["profile"]["profile_id"] == "owner-abcd1234"
    assert "0.001," not in show_out and '"embedding"' not in show_out
    assert "Profil supprimé" in delete_out
    assert not model_ready.profile_path.exists()


def test_cli_download_without_network_says_what_to_do_instead_of_a_traceback(model_ready, tmp_path, monkeypatch, capsys):
    """B6 : `download-model` est la première commande de la recette ; pas de trace d'appels."""

    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))

    def offline(request, timeout=None):  # noqa: ANN001, ANN202
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(urllib.request, "urlopen", offline)

    code = owner_voice.run_cli(app._parser().parse_args(["owner-voice", "download-model", "--force"]))

    err = capsys.readouterr().err
    assert code == 1 and "[speaker_model_download_failed]" in err
    assert "getaddrinfo failed" in err and "download-model" in err


def test_cli_enroll_with_a_busy_microphone_says_to_stop_voice(model_ready, tmp_path, monkeypatch, capsys):
    """B6 : le danger documenté — Voice tient déjà le micro — doit rester un code, pas une trace."""

    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    sounddevice = types.ModuleType("sounddevice")

    class PortAudioError(Exception):
        pass

    sounddevice.PortAudioError = PortAudioError
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    def busy(seconds, *, device=None):  # noqa: ANN001, ANN202
        raise PortAudioError("Error opening InputStream: Device unavailable [PaErrorCode -9985]")

    monkeypatch.setattr(owner_voice, "record_microphone", busy)

    code = owner_voice.run_cli(app._parser().parse_args(["owner-voice", "enroll", "--mic", "--seconds", "1"]))

    err = capsys.readouterr().err
    assert code == 1 and "[enrollment_device_unavailable]" in err
    assert "arrêtez Voice" in err and "-9985" in err
    assert not model_ready.profile_path.exists()


def test_cli_enroll_without_a_keyboard_is_an_abandon_not_a_traceback(model_ready, tmp_path, monkeypatch, capsys):
    """B6 : lancée sans terminal interactif, la confirmation lève `EOFError`."""

    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))

    def no_tty(prompt=""):  # noqa: ANN001, ANN202
        raise EOFError

    monkeypatch.setattr("builtins.input", no_tty)

    code = owner_voice.run_cli(app._parser().parse_args(["owner-voice", "enroll", "--mic"]))

    err = capsys.readouterr().err
    assert code == 1 and "[enrollment_aborted]" in err


def test_cli_enroll_without_the_audio_library_names_the_install_command(model_ready, tmp_path, monkeypatch, capsys):
    """B6 : `sounddevice` absent ne doit pas non plus sortir en trace d'appels."""

    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    def missing(seconds, *, device=None):  # noqa: ANN001, ANN202
        raise ModuleNotFoundError("No module named 'sounddevice'", name="sounddevice")

    monkeypatch.setattr(owner_voice, "record_microphone", missing)

    code = owner_voice.run_cli(app._parser().parse_args(["owner-voice", "enroll", "--mic", "--seconds", "1"]))

    err = capsys.readouterr().err
    assert code == 1 and "[enrollment_audio_unavailable]" in err and "sounddevice" in err


def test_cli_still_reports_an_unknown_failure_as_itself(model_ready, tmp_path, monkeypatch):
    """Rien d'inconnu n'est déguisé en code stable : une vraie panne reste une trace."""

    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    monkeypatch.setattr(owner_voice, "record_microphone", lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("bug")))

    with pytest.raises(ZeroDivisionError):
        owner_voice.run_cli(app._parser().parse_args(["owner-voice", "enroll", "--mic", "--seconds", "1"]))


# ===========================================================================
# Câblage Voice : ombre seulement, rien sans demande explicite
# ===========================================================================


def test_voice_wires_no_verifier_while_verification_is_off(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(owner_voice, "open_owner_verifier", lambda *a, **k: calls.append(1) or object())

    assert app._speaker_verifier({}, tmp_path) is None
    assert app._speaker_verifier({"speaker_verification": "off"}, tmp_path) is None
    assert app._speaker_verifier({"speaker_verification": "n'importe quoi"}, tmp_path) is None
    assert calls == []


@pytest.mark.parametrize("overrides", [{"speaker_verification": "shadow"}, {"conversation_mode": "solo_owner"}])
def test_voice_wires_the_real_verifier_when_verification_is_requested(tmp_path, monkeypatch, overrides):
    sentinel = object()
    monkeypatch.setattr(owner_voice, "open_owner_verifier", lambda settings, **kwargs: sentinel)

    assert app._speaker_verifier(overrides, tmp_path) is sentinel


def test_a_crashing_verifier_factory_never_costs_the_duplex_capture(tmp_path, monkeypatch):
    journal = ListJournal()

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("disque")

    monkeypatch.setattr(owner_voice, "open_owner_verifier", explode)

    assert app._speaker_verifier({"speaker_verification": "shadow"}, tmp_path, journal) is None
    assert journal.events[-1][2] == {"code": "verifier_open_failed", "error": "OSError"}


def test_a_profile_removed_after_the_probe_is_reported_not_raised(model_ready, monkeypatch):
    save_profile(model_ready.profile_path, make_profile())
    ready = owner_voice.probe_owner_verifier(model_ready)
    monkeypatch.setattr(owner_voice, "probe_owner_verifier", lambda settings: ready)
    delete_profile(model_ready.profile_path)
    journal = ListJournal()

    assert owner_voice.build_owner_verifier(model_ready, journal=journal) is None
    assert (journal.events[-1][0], journal.events[-1][2]["code"]) == (OWNER_UNAVAILABLE, "owner_profile_missing")


def test_an_unusable_verifier_leaves_the_capture_unchanged_and_says_why(tmp_path):
    journal = ListJournal()

    assert app._speaker_verifier({"speaker_verification": "shadow"}, tmp_path, journal) is None
    kind, level, data = journal.events[-1]
    assert (kind, level) == (OWNER_UNAVAILABLE, "warning")
    assert data["code"] in {"speaker_engine_not_installed", "speaker_model_missing"}


# ===========================================================================
# Garde-fous : Git et architecture
# ===========================================================================


def test_the_default_profile_and_model_paths_are_ignored_by_git():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("git indisponible")
    paths = [
        f"runtime/{SPEAKER_VERIFICATION_DIRNAME}/{OWNER_PROFILE_FILENAME}",
        f"runtime/{SPEAKER_VERIFICATION_DIRNAME}/models/{engine.MODEL_FILENAME}",
        f"data/{OWNER_PROFILE_FILENAME}",
        f"data/{SPEAKER_VERIFICATION_DIRNAME}/profil.json",
    ]
    for path in paths:
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True)
        assert result.returncode == 0, f"{path} n'est pas ignoré par Git"
    tracked = subprocess.run(
        ["git", "ls-files", "*.onnx", "*owner-voice-profile*", f"*{SPEAKER_VERIFICATION_DIRNAME}*"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout.strip() == ""


def test_the_speaker_engine_is_imported_only_by_its_adapter():
    offenders = []
    for path in (ROOT / "jarvis").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name.split(".")[0] in {"sherpa_onnx", "onnxruntime"} for name in names):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert set(offenders) <= {"jarvis/adapters/sherpa_speaker_embedder.py"}


def test_the_adapter_module_imports_without_the_engine():
    code = (
        "import sys; import jarvis.adapters.sherpa_speaker_embedder, jarvis.runtime.owner_voice; "
        "print('sherpa_onnx' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


# ===========================================================================
# Moteur réel (sauté sans moteur, modèle ou synthèse vocale Windows)
# ===========================================================================

_TTS_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$voices = @((New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
$voices = @($voices | Sort-Object { if ($_ -like '*Hortense*') { 0 } else { 1 } })
if ($voices.Count -lt 2) { exit 3 }
$texts = @{
  'enroll' = "Bonjour, je teste la reconnaissance de ma voix. Aujourd'hui il fait beau sur Paris, le ciel est bleu et les oiseaux chantent dans les arbres du jardin. Je voudrais savoir quels rendez-vous sont prevus cet apres-midi, puis ranger les dossiers du projet et relire le rapport de la semaine derniere avant la reunion de dix-sept heures.";
  'test' = "Peux-tu me rappeler d'appeler le garage demain matin, et verifier si la livraison est bien arrivee au bureau ?"
}
$jobs = @(@($voices[0], 'a-enroll', 'enroll'), @($voices[0], 'a-test', 'test'), @($voices[1], 'b-test', 'test'))
foreach ($job in $jobs) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice($job[0]); $s.SetOutputToWaveFile((Join-Path $args[0] ($job[1] + '.wav')), $fmt); $s.Speak($texts[$job[2]]); $s.Dispose()
}
"""


def _real_model_dir() -> Path:
    runtime = Path(os.getenv("JARVIS_RUNTIME_DIR") or ROOT / "runtime")
    if not runtime.is_absolute():
        runtime = ROOT / runtime
    return runtime / SPEAKER_VERIFICATION_DIRNAME / "models"


@pytest.mark.skipif(not engine.engine_installed(), reason="extra speaker absent (sherpa-onnx)")
@pytest.mark.skipif(not engine.model_path(_real_model_dir()).is_file(), reason="modèle absent : jarvis owner-voice download-model")
@pytest.mark.skipif(sys.platform != "win32", reason="synthèse vocale SAPI Windows seulement")
def test_real_engine_enrolls_a_synthetic_voice_and_rejects_another(tmp_path):
    script = tmp_path / "tts.ps1"
    script.write_text(_TTS_SCRIPT, encoding="utf-8")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(tmp_path)],
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0 or not (tmp_path / "b-test.wav").is_file():
        pytest.skip(f"synthèse vocale indisponible (code {result.returncode})")
    settings = SpeakerVerifierSettings(model_dir=_real_model_dir(), profile_path=tmp_path / "owner.json")

    profile = owner_voice.enroll(settings, [owner_voice.read_wav(tmp_path / "a-enroll.wav")])
    verifier = owner_voice.build_owner_verifier(settings)
    assert verifier is not None and verifier.availability is VerifierAvailability.READY
    verifier.reset()

    def replay(name: str) -> list:
        samples, rate = owner_voice.read_wav(tmp_path / f"{name}.wav")
        verifier.reset()
        return feed(verifier, resample(samples, rate, RATE))

    owner = [v for v in replay("a-test") if v.status is VerificationStatus.OK]
    stranger = [v for v in replay("b-test") if v.status is VerificationStatus.OK]
    verifier.close()

    assert profile.embedding_dim == engine.MODEL_DIM and profile.enrollment_ms >= 10_000
    assert owner and stranger
    assert any(v.owner_detected for v in owner)
    assert not any(v.owner_detected for v in stranger)
    assert max(v.owner_score for v in owner) > max(v.owner_score for v in stranger)
    assert owner[0].engine.startswith("sherpa-onnx/")
