"""Catalogue des modèles d'empreinte sherpa-onnx comparés au banc d'essai (tâche 09).

Le moteur de production reste celui épinglé par `sherpa_speaker_embedder`
(CAM++ zh_en « advanced ») : ce catalogue ne change aucun défaut. Il décrit
d'autres exports du même dépôt de modèles sherpa-onnx pour que le banc d'essai
les compare sur le même audio (D12) ; la tâche 14 choisit sur mesures.

Chaque modèle est épinglé : SHA-256 et taille relevés dans le `checksum.txt`
de la publication sherpa-onnx `speaker-recongition-models`, licence des poids
vérifiée à la source (API ModelScope pour 3D-Speaker, documentation WeSpeaker
pour WeSpeaker). Les fichiers vont dans le dossier des modèles du runtime
(ignoré par Git), jamais dans le dépôt.

Aucun import de sherpa-onnx ici : le calcul passe par `SherpaSpeakerEmbedder`,
seul importeur du moteur.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import urllib.request

from jarvis.adapters import sherpa_speaker_embedder as baseline
from jarvis.adapters.file_replace import replace_with_retry
from jarvis.adapters.sherpa_speaker_embedder import SherpaSpeakerEmbedder, SpeakerModelError, file_sha256

_RELEASE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
_MODELSCOPE = "https://www.modelscope.cn/models/iic/"
_APACHE = "Apache-2.0"
_APACHE_SOURCE = "ModelScope API (License: Apache License 2.0), vérifié le 2026-09-11"


@dataclass(frozen=True, slots=True)
class SherpaModelSpec:
    """Un modèle d'empreinte sherpa-onnx épinglé."""

    #: Nom court utilisé par le manifeste et la ligne de commande.
    key: str
    model_id: str
    sha256: str
    size: int
    dim: int
    license: str
    license_source: str
    card: str
    family: str
    sample_rate: int = 16_000
    notes: str = ""

    @property
    def filename(self) -> str:
        return f"{self.model_id}.onnx"

    @property
    def url(self) -> str:
        return _RELEASE_URL + self.filename

    def path(self, model_dir: Path) -> Path:
        return Path(model_dir) / self.filename

    def payload(self) -> dict[str, object]:
        return {
            "key": self.key,
            "model_id": self.model_id,
            "model_file": self.filename,
            "model_sha256": self.sha256,
            "model_size": self.size,
            "embedding_dim": self.dim,
            "model_sample_rate": self.sample_rate,
            "model_license": self.license,
            "model_license_source": self.license_source,
            "model_card": self.card,
            "model_url": self.url,
            "family": self.family,
            "notes": self.notes,
        }


def _3dspeaker(key: str, model_id: str, sha256: str, size: int, dim: int, card: str, family: str, notes: str = "") -> SherpaModelSpec:
    return SherpaModelSpec(
        key=key,
        model_id=model_id,
        sha256=sha256,
        size=size,
        dim=dim,
        license=_APACHE,
        license_source=_APACHE_SOURCE,
        card=_MODELSCOPE + card,
        family=family,
        notes=notes,
    )


#: Modèle de référence de la tâche 03, décrit par ses propres constantes.
BASELINE_KEY = "campplus-zh-en-advanced"

MODELS: tuple[SherpaModelSpec, ...] = (
    SherpaModelSpec(
        key=BASELINE_KEY,
        model_id=baseline.MODEL_ID,
        sha256=baseline.MODEL_SHA256,
        size=baseline.MODEL_SIZE,
        dim=baseline.MODEL_DIM,
        sample_rate=baseline.MODEL_SAMPLE_RATE,
        license=baseline.MODEL_LICENSE,
        license_source=_APACHE_SOURCE,
        card=baseline.MODEL_CARD,
        family="3D-Speaker CAM++",
        notes="moteur de référence de la tâche 03 (défaut de production actuel)",
    ),
    _3dspeaker(
        "campplus-zh-cn-common",
        "3dspeaker_speech_campplus_sv_zh-cn_16k-common",
        "f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11",
        28_281_138,
        192,
        "speech_campplus_sv_zh-cn_16k-common",
        "3D-Speaker CAM++",
    ),
    _3dspeaker(
        "campplus-en-voxceleb",
        "3dspeaker_speech_campplus_sv_en_voxceleb_16k",
        "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b",
        29_596_978,
        512,
        "speech_campplus_sv_en_voxceleb_16k",
        "3D-Speaker CAM++",
        "écarté par la tâche 03 (ne séparait pas les voix d'essai)",
    ),
    _3dspeaker(
        "eres2net-en-voxceleb",
        "3dspeaker_speech_eres2net_sv_en_voxceleb_16k",
        "c59158379255ad66e161679cca6af8d52d51e389e3224ab7d7a7baae295c2db5",
        26_485_263,
        192,
        "speech_eres2net_sv_en_voxceleb_16k",
        "3D-Speaker ERes2Net",
    ),
    _3dspeaker(
        "eres2net-base-200k-zh-cn",
        "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common",
        "e2d2048292e055f7b61cdec3db010503f35369b245bf0b3bbad021c9a91e4053",
        39_593_765,
        512,
        "speech_eres2net_base_200k_sv_zh-cn_16k-common",
        "3D-Speaker ERes2Net",
    ),
    _3dspeaker(
        "eres2net-base-3dspeaker",
        "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k",
        "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
        39_593_761,
        512,
        "speech_eres2net_base_sv_zh-cn_3dspeaker_16k",
        "3D-Speaker ERes2Net",
    ),
    _3dspeaker(
        "eres2netv2-zh-cn",
        "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common",
        "bf1a75b9930474cf3389ef415e6e5d38ca96fea4a3a00f7e301d080a58ee2239",
        71_441_526,
        192,
        "speech_eres2netv2_sv_zh-cn_16k-common",
        "3D-Speaker ERes2NetV2",
    ),
    SherpaModelSpec(
        key="wespeaker-resnet34-en-voxceleb",
        model_id="wespeaker_en_voxceleb_resnet34",
        sha256="5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94",
        size=26_534_365,
        dim=256,
        license="CC-BY-4.0",
        license_source=(
            "WeSpeaker docs/pretrained.md : les poids suivent la licence du corpus (VoxCeleb, CC BY 4.0), "
            "attribution requise ; vérifié le 2026-09-11"
        ),
        card="https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md",
        family="WeSpeaker ResNet34",
    ),
)

_BY_KEY = {spec.key: spec for spec in MODELS}
_BY_ID = {spec.model_id: spec for spec in MODELS}


def find_model(name: str) -> SherpaModelSpec | None:
    """Modèle par nom court ou par identifiant complet (avec ou sans `.onnx`)."""

    name = str(name).strip()
    if name.endswith(".onnx"):
        name = name[: -len(".onnx")]
    return _BY_KEY.get(name) or _BY_ID.get(name)


def verify_spec(spec: SherpaModelSpec, model_dir: Path) -> Path:
    """Chemin du modèle, s'il est exactement celui épinglé ; sinon `SpeakerModelError`."""

    path = spec.path(model_dir)
    if not path.is_file():
        raise SpeakerModelError("speaker_model_missing", f"Modèle absent : {path}")
    if path.stat().st_size != spec.size or file_sha256(path) != spec.sha256:
        raise SpeakerModelError(
            "speaker_model_mismatch", f"{path} ne correspond pas au SHA-256 épinglé ({spec.sha256}) ; retéléchargez-le."
        )
    return path


def download_spec(spec: SherpaModelSpec, model_dir: Path, *, force: bool = False, timeout_s: float = 300.0) -> Path:
    """Télécharger un modèle du catalogue, SHA-256 vérifié avant installation."""

    target = spec.path(model_dir)
    if target.is_file() and not force:
        return verify_spec(spec, model_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(spec.url, headers={"User-Agent": "Jarvis-speaker-benchmark/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response, partial.open("wb") as handle:
            written = 0
            for block in iter(lambda: response.read(1 << 20), b""):
                written += len(block)
                if written > spec.size:
                    # Taille épinglée au même titre que le SHA-256 : inutile de
                    # remplir le disque pour refuser ensuite.
                    raise SpeakerModelError(
                        "speaker_model_mismatch",
                        f"{spec.url} dépasse la taille épinglée ({spec.size} octets) : téléchargement abandonné.",
                    )
                digest.update(block)
                handle.write(block)
        if digest.hexdigest() != spec.sha256:
            raise SpeakerModelError("speaker_model_mismatch", f"SHA-256 inattendu pour {spec.url} : {digest.hexdigest()}")
        try:
            replace_with_retry(partial, target)
        except OSError as exc:
            raise SpeakerModelError(
                "speaker_model_install_failed",
                f"Modèle téléchargé mais non installé ({target}) : {type(exc).__name__}. Réessayez.",
            ) from None
    finally:
        partial.unlink(missing_ok=True)
    return target


class CatalogSherpaEmbedder(SherpaSpeakerEmbedder):
    """`SpeakerEmbedder` sherpa-onnx pour un modèle du catalogue.

    Même code de calcul que le moteur de production ; seuls le fichier, la
    dimension et l'identifiant changent. La vérification du SHA-256 se fait à
    part (`verify_spec`), pour que le banc d'essai mesure le chargement seul.
    """

    def __init__(self, spec: SherpaModelSpec, model_dir: Path, *, num_threads: int = 1) -> None:
        super().__init__(spec.path(model_dir), num_threads=num_threads, verify=False)
        self.spec = spec
        self.model_id = spec.model_id
        self.dim = spec.dim
        self.sample_rate = spec.sample_rate
