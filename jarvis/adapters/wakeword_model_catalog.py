"""Catalogue des modèles openWakeWord (mot d'éveil « hey jarvis »), épinglés par SHA-256.

openWakeWord a besoin de trois modèles ONNX : le spectrogramme de mel, le
modèle d'empreinte audio partagé et le détecteur du mot (`hey_jarvis`). Rien
n'est versionné dans le dépôt : chaque fichier est téléchargé à la demande,
sur action explicite, depuis la publication `v0.5.1` du dépôt amont, dans
`runtime/wake-word/models/` (ignoré par Git), et n'est installé qu'après
vérification de sa taille et de son SHA-256 épinglés ici. Aucune confiance
n'est accordée à l'URL.

Licence : le code d'openWakeWord est Apache-2.0 ; les modèles préentraînés sont
CC BY-NC-SA 4.0 (usage privé non commercial), voir `third_party/README.md`.

Le modèle de ce fichier est `sherpa_model_catalog` : mêmes garde-fous (taille
bornée, `.part` jamais laissé, remplacement atomique), codes d'erreur
`wake_model_*` calqués sur `speaker_model_*`.

Aucun import d'openwakeword ni d'onnxruntime ici, et aucun accès réseau au
chargement : le moteur (Slice 02) est le seul importeur de la bibliothèque.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import urllib.request

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.adapters.sherpa_speaker_embedder import file_sha256

ROOT = Path(__file__).resolve().parents[2]

_RELEASE_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
LICENSE = "CC-BY-NC-SA-4.0"
LICENSE_SOURCE = (
    "README du dépôt github.com/dscripka/openWakeWord, section « License » : code Apache-2.0, "
    "modèles préentraînés CC BY-NC-SA 4.0 ; vérifié le 2026-10-07"
)


class WakeModelError(RuntimeError):
    """Modèle absent, tronqué, altéré ou impossible à installer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WakeModelSpec:
    """Un modèle ONNX openWakeWord épinglé."""

    key: str
    filename: str
    sha256: str
    size: int
    role: str
    license: str = LICENSE
    license_source: str = LICENSE_SOURCE

    @property
    def url(self) -> str:
        return _RELEASE_URL + self.filename

    def path(self, model_dir: Path) -> Path:
        return Path(model_dir) / self.filename

    def payload(self) -> dict[str, object]:
        return {
            "key": self.key,
            "model_file": self.filename,
            "model_sha256": self.sha256,
            "model_size": self.size,
            "model_role": self.role,
            "model_license": self.license,
            "model_license_source": self.license_source,
            "model_url": self.url,
        }


#: SHA-256 et tailles mesurés le 2026-10-07 sur les fichiers de la publication
#: `v0.5.1` (tailles identiques à celles de l'API des publications GitHub).
MODELS: tuple[WakeModelSpec, ...] = (
    WakeModelSpec(
        key="melspectrogram",
        filename="melspectrogram.onnx",
        sha256="ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
        size=1_087_958,
        role="prétraitement : spectrogramme de mel",
    ),
    WakeModelSpec(
        key="embedding",
        filename="embedding_model.onnx",
        sha256="70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
        size=1_326_578,
        role="empreinte audio partagée",
    ),
    WakeModelSpec(
        key="hey_jarvis",
        filename="hey_jarvis_v0.1.onnx",
        sha256="94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
        size=1_271_370,
        role="détecteur du mot « hey jarvis »",
    ),
)


def find_model(name: str) -> WakeModelSpec | None:
    """Modèle par clé courte ou par nom de fichier."""

    name = str(name).strip()
    for spec in MODELS:
        if name in (spec.key, spec.filename):
            return spec
    return None


def default_model_dir() -> Path:
    """`<runtime>/wake-word/models`, le runtime étant `JARVIS_RUNTIME_DIR` ou `runtime/` du dépôt."""

    raw = os.getenv("JARVIS_RUNTIME_DIR")
    if raw:
        path = Path(raw).expanduser()
        runtime = path if path.is_absolute() else ROOT / path
    else:
        runtime = ROOT / "runtime"
    return runtime / "wake-word" / "models"


def verify_spec(spec: WakeModelSpec, model_dir: Path) -> Path:
    """Chemin du modèle, s'il est exactement celui épinglé ; sinon `WakeModelError`."""

    path = spec.path(model_dir)
    if not path.is_file():
        raise WakeModelError("wake_model_missing", f"Modèle absent : {path.name}")
    if path.stat().st_size != spec.size or file_sha256(path) != spec.sha256:
        raise WakeModelError(
            "wake_model_mismatch",
            f"{path.name} ne correspond pas au SHA-256 épinglé ({spec.sha256}) ; supprimez-le puis retéléchargez-le.",
        )
    return path


def download_spec(spec: WakeModelSpec, model_dir: Path, *, force: bool = False, timeout_s: float = 120.0) -> Path:
    """Télécharger un modèle du catalogue ; SHA-256 vérifié AVANT installation.

    Un fichier déjà présent est vérifié, jamais réécrit (sauf `force`) : un
    fichier altéré est refusé, pas écrasé en silence.
    """

    target = spec.path(model_dir)
    if target.is_file() and not force:
        return verify_spec(spec, model_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(spec.url, headers={"User-Agent": "Jarvis-wake-word/1"})
    try:
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response, partial.open("wb") as handle:
                written = 0
                for block in iter(lambda: response.read(1 << 20), b""):
                    written += len(block)
                    if written > spec.size:
                        raise WakeModelError(
                            "wake_model_mismatch",
                            f"{spec.url} dépasse la taille épinglée ({spec.size} octets) : téléchargement abandonné.",
                        )
                    digest.update(block)
                    handle.write(block)
        except OSError as exc:
            raise WakeModelError(
                "wake_model_download_failed", f"Téléchargement impossible ({type(exc).__name__}) : {spec.url}"
            ) from None
        if written != spec.size or digest.hexdigest() != spec.sha256:
            raise WakeModelError("wake_model_mismatch", f"SHA-256 inattendu pour {spec.url} : {digest.hexdigest()}")
        try:
            replace_with_retry(partial, target)
        except OSError as exc:
            raise WakeModelError(
                "wake_model_install_failed",
                f"Modèle téléchargé mais non installé ({target.name}) : {type(exc).__name__}. Réessayez.",
            ) from None
    finally:
        partial.unlink(missing_ok=True)
    return target


def ensure_models(
    model_dir: Path | None = None, *, specs: Iterable[WakeModelSpec] | None = None, force: bool = False
) -> dict[str, Path]:
    """Installer à la demande les modèles manquants ; chemins vérifiés par clé.

    Appel explicite uniquement (commande ou action de l'utilisateur) : rien
    n'appelle cette fonction au chargement du code.
    """

    directory = Path(model_dir) if model_dir is not None else default_model_dir()
    return {spec.key: download_spec(spec, directory, force=force) for spec in (MODELS if specs is None else specs)}


def verified_paths(model_dir: Path | None = None) -> dict[str, Path]:
    """Chemins des trois modèles s'ils sont tous installés et conformes ; jamais de réseau."""

    directory = Path(model_dir) if model_dir is not None else default_model_dir()
    return {spec.key: verify_spec(spec, directory) for spec in MODELS}
