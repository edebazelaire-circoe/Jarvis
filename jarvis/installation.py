"""Identité d'installation : checkout de développement ou produit installé (`docs/local-data.md` › *Produit installé*).

Contrat plateforme sous `jarvis/data_root.py` : une seule question, « ce code
tourne-t-il comme produit installé ? », et une seule réponse pour tous les
processus (Core, Control Center, voix, serveurs MCP enfants).

- **Signal** : le fichier `jarvis-product.json` posé par le paquet d'installation
  (Slice 06) à côté du paquet `jarvis/` (`CODE_ROOT`). Présent = produit
  installé ; absent = checkout de développement. Rien d'autre ne compte : ni le
  chemin d'installation, ni le nom du dossier, ni un exécutable gelé. Un
  marqueur illisible ou d'un autre schéma est un refus de démarrer
  (`ConfigurationError`), jamais un repli silencieux vers le mode développement,
  qui ouvrirait un profil dérivé du chemin.
- **Maison du produit** : `%LOCALAPPDATA%\\CIRCOE\\Jarvis\\`, lue dans
  l'environnement (`LOCALAPPDATA`), jamais déduite de `CODE_ROOT`. Déplacer ou
  mettre à jour le programme ne change donc pas de profil. `LOCALAPPDATA` absent
  ou relatif en mode installé : refus de démarrer.
- **Plateformes** (Slice 08 de la V1.2, `docs/macos-portability.md`) : `product_home`
  est le SEUL adaptateur des racines logiques par plateforme. Windows, et tout
  système autre que macOS : la maison ci-dessus, inchangée. macOS :
  `~/Library/Application Support/CIRCOE/Jarvis` (`HOME` absolu exigé), caches et
  journaux réservés sous `~/Library/Caches/CIRCOE/Jarvis` et
  `~/Library/Logs/CIRCOE/Jarvis` (aucun consommateur ne les crée encore, comme
  `cache\\` et `logs\\` sous Windows). Les exports restent `<Documents>/Jarvis`
  (`jarvis/adapters/known_folders.py`) sur les deux plateformes. macOS n'est PAS
  une plateforme supportée tant que `HV-V12-MAC-01` n'est pas passé.

Pur côté identité (l'environnement est passé en argument) ; la seule E/S est la
lecture du marqueur.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys

from jarvis.domain.errors import ConfigurationError

#: Racine du code : le dossier qui contient le paquet `jarvis/` (le dépôt, ou le dossier d'installation).
CODE_ROOT = Path(__file__).resolve().parents[1]
#: Marqueur posé par le paquet d'installation, et seulement par lui (ignoré par git).
PRODUCT_MARKER = "jarvis-product.json"
PRODUCT_MARKER_SCHEMA = "jarvis.product-install"
PRODUCT_MARKER_VERSION = 1
#: `%LOCALAPPDATA%\<VENDOR_DIR>\<PRODUCT_DIR>` : identité stable du produit par utilisateur Windows.
VENDOR_DIR = "CIRCOE"
PRODUCT_DIR = "Jarvis"
LOCALAPPDATA_ENV = "LOCALAPPDATA"
#: Forme affichable de la maison : jamais le nom de l'utilisateur dans un diagnostic.
PRODUCT_HOME_LABEL = r"%LOCALAPPDATA%\CIRCOE\Jarvis"
#: macOS (non supporté avant `HV-V12-MAC-01`) : maison sous `$HOME`, libellé sans nom d'utilisateur.
HOME_ENV = "HOME"
MACOS_HOME_LABEL = "~/Library/Application Support/CIRCOE/Jarvis"
_MACOS_APP_SUPPORT = ("Library", "Application Support")
_MACOS_CACHES = ("Library", "Caches")
_MACOS_LOGS = ("Library", "Logs")


class HostPlatform(StrEnum):
    """Famille de plateforme des racines. `OTHER` (Linux de test) garde le comportement Windows d'avant la Slice 08."""

    WINDOWS = "windows"
    MACOS = "macos"
    OTHER = "other"


def host_platform(sys_platform: str | None = None) -> HostPlatform:
    """`sys.platform` (ou la valeur donnée, pour les tests de plateforme simulée) → famille de plateforme."""

    value = sys.platform if sys_platform is None else sys_platform
    if value == "win32":
        return HostPlatform.WINDOWS
    if value == "darwin":
        return HostPlatform.MACOS
    return HostPlatform.OTHER


class InstallMode(StrEnum):
    DEVELOPMENT = "development"
    INSTALLED = "installed"


@dataclass(frozen=True, slots=True)
class ProductHome:
    """`%LOCALAPPDATA%\\CIRCOE\\Jarvis\\` et ses sous-dossiers canoniques.

    `data` : racine de données (chemins internes inchangés : `state/`,
    `CONTEXT_GLOBAL/`, `boards/`, `sessions/`…). `runtime` : jeton de Core,
    réglages du Control Center, journaux `trace.jsonl`/`errors.jsonl`, modèles.
    `config` : `.env` du produit. `logs\\` et `cache\\` ne sont pas créés en V1 :
    aucun consommateur ne les utilise encore (journaux dans `runtime`).
    macOS : `cache_root`/`logs_root` hors de la maison (`~/Library/Caches|Logs/CIRCOE/Jarvis`),
    mêmes règles (réservés, jamais créés ici).
    """

    root: Path
    label: str = PRODUCT_HOME_LABEL
    cache_root: Path | None = None
    logs_root: Path | None = None

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def cache(self) -> Path:
        return self.cache_root if self.cache_root is not None else self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.logs_root if self.logs_root is not None else self.root / "logs"

    def sub_label(self, sub: str) -> str:
        """Libellé affichable d'un sous-dossier : `%LOCALAPPDATA%\\CIRCOE\\Jarvis\\data`, `~/Library/…/Jarvis/data`."""

        return self.label + ("/" if self.label.startswith("~") else "\\") + sub


@dataclass(frozen=True, slots=True)
class Installation:
    mode: InstallMode
    code_root: Path
    home: ProductHome | None = None

    @property
    def installed(self) -> bool:
        return self.mode is InstallMode.INSTALLED


def product_home(environ: Mapping[str, str], *, platform: HostPlatform | None = None) -> ProductHome:
    """`%LOCALAPPDATA%\\CIRCOE\\Jarvis` ; `ConfigurationError` si `LOCALAPPDATA` manque ou n'est pas absolu.

    macOS (`platform`, défaut `host_platform()`) : `$HOME/Library/Application Support/CIRCOE/Jarvis` ;
    `ConfigurationError` si `HOME` manque ou n'est pas absolu. Aucune E/S.
    """

    if (platform or host_platform()) is HostPlatform.MACOS:
        return _macos_home(environ)
    raw = str(environ.get(LOCALAPPDATA_ENV) or "").strip()
    if not raw:
        raise ConfigurationError(f"produit installé : {LOCALAPPDATA_ENV} absent, maison du produit introuvable")
    base = Path(raw).expanduser()
    if not (base.is_absolute() or PureWindowsPath(raw).is_absolute()):
        raise ConfigurationError(f"produit installé : {LOCALAPPDATA_ENV} doit être un chemin absolu")
    return ProductHome(base / VENDOR_DIR / PRODUCT_DIR)


def _macos_home(environ: Mapping[str, str]) -> ProductHome:
    raw = str(environ.get(HOME_ENV) or "").strip()
    if not raw:
        raise ConfigurationError(f"produit installé (macOS) : {HOME_ENV} absent, maison du produit introuvable")
    if not PurePosixPath(raw).is_absolute():
        raise ConfigurationError(f"produit installé (macOS) : {HOME_ENV} doit être un chemin absolu")
    base = Path(raw)
    return ProductHome(base.joinpath(*_MACOS_APP_SUPPORT, VENDOR_DIR, PRODUCT_DIR), label=MACOS_HOME_LABEL,
                       cache_root=base.joinpath(*_MACOS_CACHES, VENDOR_DIR, PRODUCT_DIR),
                       logs_root=base.joinpath(*_MACOS_LOGS, VENDOR_DIR, PRODUCT_DIR))


def read_product_marker(code_root: Path) -> dict | None:
    """Le marqueur validé, ou `None` s'il n'existe pas. Illisible ou d'un autre schéma : `ConfigurationError`."""

    path = Path(code_root) / PRODUCT_MARKER
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigurationError(f"{PRODUCT_MARKER} illisible ({type(exc).__name__}) : démarrage refusé") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{PRODUCT_MARKER} n'est pas un JSON valide : démarrage refusé") from exc
    if (not isinstance(payload, dict) or payload.get("schema") != PRODUCT_MARKER_SCHEMA
            or payload.get("schema_version") != PRODUCT_MARKER_VERSION):
        raise ConfigurationError(
            f"{PRODUCT_MARKER} : schéma attendu {PRODUCT_MARKER_SCHEMA!r} v{PRODUCT_MARKER_VERSION} : démarrage refusé")
    return payload


def detect_installation(environ: Mapping[str, str] | None = None, *, code_root: Path | None = None,
                        platform: HostPlatform | None = None) -> Installation:
    """Mode de ce code : marqueur présent = produit installé (maison de la plateforme), sinon développement."""

    env = os.environ if environ is None else environ
    root = Path(CODE_ROOT if code_root is None else code_root)
    if read_product_marker(root) is None:
        return Installation(InstallMode.DEVELOPMENT, root)
    return Installation(InstallMode.INSTALLED, root, product_home(env, platform=platform))


def marker_payload() -> dict:
    """Contenu exact du marqueur que le paquet d'installation doit poser dans `CODE_ROOT` (couture Slice 06)."""

    return {"schema": PRODUCT_MARKER_SCHEMA, "schema_version": PRODUCT_MARKER_VERSION,
            "vendor": VENDOR_DIR, "product": PRODUCT_DIR}
