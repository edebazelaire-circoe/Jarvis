"""Empreinte vocale locale par sherpa-onnx (moteur de référence, tâche 03).

Premier moteur réel derrière `SpeakerVerifier` — une base de comparaison, pas
le choix définitif : la tâche 09 le met en concurrence avec d'autres (D12).

- Bibliothèque : `sherpa-onnx` (Apache-2.0), extra `speaker` du projet.
- Modèle : CAM++ « zh_en common advanced » de 3D-Speaker (ModelScope
  `iic/speech_campplus_sv_zh_en_16k-common_advanced`, licence Apache-2.0),
  converti en ONNX par sherpa-onnx. 16 kHz, empreinte de 192 valeurs.

Import paresseux : ce module se charge sans sherpa-onnx ni numpy ; seul le
premier calcul d'empreinte les importe, dans le fil du vérificateur.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
from pathlib import Path
import threading
import urllib.request
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry

ENGINE_NAME = "sherpa-onnx"
_DISTRIBUTION = "sherpa-onnx"
_MODULE = "sherpa_onnx"

MODEL_ID = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced"
MODEL_FILENAME = f"{MODEL_ID}.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + MODEL_FILENAME
)
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
MODEL_SIZE = 28_281_164
MODEL_DIM = 192
MODEL_SAMPLE_RATE = 16_000
MODEL_LICENSE = "Apache-2.0"
MODEL_CARD = "https://www.modelscope.cn/models/iic/speech_campplus_sv_zh_en_16k-common_advanced"
#: Seuil par défaut sur l'échelle commune (= similarité cosinus écrêtée),
#: **provisoire** : la fiche du modèle donne 0,33 pour des énoncés complets ;
#: sur des fenêtres de 1 à 2 s, les imposteurs montent jusqu'à ~0,45 (tâche 03).
#: Le banc d'essai de la tâche 14 (synthétique, `docs/results/speaker-benchmark/`)
#: montre qu'à 0,5 la porte Solo Owner ouvre encore le flux sur 4 prises de
#: parole étrangères sur 24, contre 1 à 0,6, pour un délai de confirmation
#: inchangé (P50 1,6 s) ; à 0,65 plus aucune, mais un tour du propriétaire sur
#: dix est manqué. 0,6 applique donc D07 (mieux vaut attendre que répondre à
#: un collègue) sans rendre JARVIS sourd. À régler sur poste, sur des voix
#: réelles : « Reading the results » de `docs/SPEAKER_BENCHMARK.md`.
DEFAULT_THRESHOLD = 0.6


class SpeakerModelError(RuntimeError):
    """Modèle absent, tronqué ou différent de celui épinglé."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def engine_installed() -> bool:
    """La bibliothèque est-elle installée ? Sans l'importer (sonde bon marché)."""

    try:
        return importlib.util.find_spec(_MODULE) is not None
    except (ImportError, ValueError):
        return False


def engine_version() -> str | None:
    try:
        return importlib.metadata.version(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return None


def engine_id() -> str:
    """Identifiant « nom/version » envoyé dans chaque verdict."""

    return f"{ENGINE_NAME}/{engine_version() or 'unknown'}"


def model_path(model_dir: Path) -> Path:
    return Path(model_dir) / MODEL_FILENAME


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


#: Empreintes déjà calculées, par (chemin, taille, date de modification) : le
#: Control Center sonde le modèle à chaque `GET /api/settings`, et relire 27 Mio
#: à chaque fois coûterait ~50 ms de disque pour rien. Borné, jamais persisté.
_SHA256_CACHE: dict[tuple[str, int, int], str] = {}
_SHA256_CACHE_MAX = 8


def cached_file_sha256(path: Path) -> str:
    """SHA-256 du fichier, recalculé seulement si sa taille ou sa date change.

    Une modification qui garde exactement la taille **et** `st_mtime_ns` passerait
    inaperçue ; `verify_model` (chargement du modèle, installation après
    téléchargement) relit toujours le fichier, lui.
    """

    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    digest = _SHA256_CACHE.get(key)
    if digest is None:
        digest = file_sha256(path)
        if len(_SHA256_CACHE) >= _SHA256_CACHE_MAX:
            _SHA256_CACHE.clear()
        _SHA256_CACHE[key] = digest
    return digest


def verify_model(path: Path) -> None:
    """Refuser tout fichier qui n'est pas exactement le modèle épinglé."""

    path = Path(path)
    if not path.is_file():
        raise SpeakerModelError("speaker_model_missing", f"Modèle de vérification absent : {path}")
    if path.stat().st_size != MODEL_SIZE or file_sha256(path) != MODEL_SHA256:
        raise SpeakerModelError(
            "speaker_model_mismatch",
            f"Le modèle {path} ne correspond pas à l'empreinte SHA-256 épinglée ; retéléchargez-le.",
        )


def download_model(model_dir: Path, *, force: bool = False, timeout_s: float = 120.0) -> Path:
    """Télécharger le modèle épinglé et vérifier son SHA-256 avant de l'installer."""

    target = model_path(model_dir)
    if target.is_file() and not force:
        verify_model(target)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Jarvis-speaker-model/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response, partial.open("wb") as handle:
            written = 0
            for block in iter(lambda: response.read(1 << 20), b""):
                written += len(block)
                if written > MODEL_SIZE:
                    # La taille est épinglée comme le SHA-256 : une redirection
                    # vers autre chose n'a pas à remplir le disque avant d'être
                    # refusée.
                    raise SpeakerModelError(
                        "speaker_model_mismatch",
                        f"{MODEL_URL} dépasse la taille épinglée ({MODEL_SIZE} octets) : téléchargement abandonné.",
                    )
                digest.update(block)
                handle.write(block)
        if digest.hexdigest() != MODEL_SHA256:
            raise SpeakerModelError(
                "speaker_model_mismatch", f"SHA-256 inattendu pour {MODEL_URL} : {digest.hexdigest()}"
            )
        try:
            replace_with_retry(partial, target)
        except OSError as exc:
            # Même verrou bref que pour le profil : l'antivirus inspecte le
            # fichier qui vient d'être écrit. Après les essais, on le dit.
            raise SpeakerModelError(
                "speaker_model_install_failed",
                f"Modèle téléchargé mais non installé ({target}) : {type(exc).__name__}. Réessayez.",
            ) from None
    finally:
        partial.unlink(missing_ok=True)
    return target


class SherpaSpeakerEmbedder:
    """`SpeakerEmbedder` sherpa-onnx, chargé au premier besoin.

    Un seul fil de calcul ONNX : la capture, l'annulation d'écho et la lecture
    ont priorité sur la vérification.
    """

    model_id = MODEL_ID
    dim = MODEL_DIM
    sample_rate = MODEL_SAMPLE_RATE

    def __init__(self, model_file: Path, *, num_threads: int = 1, verify: bool = True) -> None:
        self.model_file = Path(model_file)
        self.num_threads = max(1, int(num_threads))
        self.verify = verify
        self._extractor: Any = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._extractor is not None

    def load(self) -> None:
        with self._lock:
            if self._extractor is not None:
                return
            if self.verify:
                verify_model(self.model_file)
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.model_file), num_threads=self.num_threads, debug=False, provider="cpu"
            )
            if not config.validate():
                raise SpeakerModelError("speaker_model_invalid", f"Configuration sherpa-onnx refusée : {self.model_file}")
            extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            # `self.dim` / `self.sample_rate` (= MODEL_DIM / MODEL_SAMPLE_RATE ici) :
            # le banc d'essai (tâche 09) y branche d'autres modèles sherpa-onnx.
            if int(extractor.dim) != int(self.dim):
                raise SpeakerModelError(
                    "speaker_model_mismatch", f"Le modèle rend des empreintes de {extractor.dim} valeurs, {self.dim} attendues"
                )
            self._extractor = extractor

    def embed(self, samples):  # noqa: ANN001, ANN201 - tableau numpy, import paresseux
        import numpy as np

        self.load()
        extractor = self._extractor
        stream = extractor.create_stream()
        stream.accept_waveform(int(self.sample_rate), np.ascontiguousarray(samples, dtype=np.float32))
        stream.input_finished()
        if not extractor.is_ready(stream):
            raise ValueError("not enough audio for a speaker embedding")
        return np.asarray(extractor.compute(stream), dtype=np.float32)

    def close(self) -> None:
        with self._lock:
            self._extractor = None
