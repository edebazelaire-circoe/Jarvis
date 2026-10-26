"""Runtimes privés du paquet Windows (`docs/windows-packaging.md`, Slice 06 de jarvis-presentation-edition-v1).

Contrat plateforme sous `jarvis/installation.py` : un produit installé (marqueur
`jarvis-product.json`) n'utilise JAMAIS un outil de développement trouvé sur le
PATH du poste (Python, Node/npm, FFmpeg). Il utilise les runtimes épinglés que le
paquet pose à côté du code :

    <dossier d'installation>/
        app/                    CODE_ROOT : paquet `jarvis/` + marqueur `jarvis-product.json`
        runtime/python/         Python embarquable épinglé (+ `Lib/site-packages` verrouillé)
        runtime/node/           Node.js épinglé (npm livré avec lui)
        runtime-manifest.json   manifeste machine (versions, empreintes, composants exclus)
        licenses/, third-party-manifest.json

- **Développement** (pas de marqueur) : `which` = `shutil.which`, rien ne change
  (`setup.ps1`, `.venv`, PATH du développeur).
- **Produit installé** : `which("node")` = `runtime/node/node.exe` du paquet ou
  `None` (jamais le PATH : un Node absent est une installation à réparer, pas un
  outil à chercher ailleurs). `npm`/`npx` : toujours `None` (le runner lance
  `node npm-cli.js` à côté de ce Node). `ffmpeg` : celui du paquet seulement si le
  manifeste le déclare livré (édition `presentation` : exclu, licence GPL). Tout
  autre nom (CLI Claude Code, navigateur sous Linux) reste résolu sur le PATH :
  ce sont des dépendances externes déclarées comme telles dans le manifeste.
- `child_path` place `runtime/node` en tête du PATH des processus enfants, pour
  qu'un `node` cherché par npm ou Remotion soit le Node privé.

Lecture seule ; aucune écriture. Le hachage complet (`verify_runtimes`) n'est
fait qu'à la demande (diagnostic, réparation), jamais au démarrage.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil

from jarvis.installation import CODE_ROOT, read_product_marker

#: Nom du dossier du code dans le paquet : `CODE_ROOT` d'un produit installé.
APP_DIR = "app"
RUNTIME_DIR = "runtime"
PYTHON_DIR = "python"
NODE_DIR = "node"
FFMPEG_DIR = "ffmpeg"
RUNTIME_MANIFEST = "runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "jarvis.runtime-manifest"
RUNTIME_MANIFEST_VERSION = 1
#: Noms jamais résolus sur le PATH en produit installé (le paquet fournit ou rien).
OWNED_TOOLS = frozenset({"node", "node.exe", "npm", "npm.cmd", "npx", "npx.cmd", "ffmpeg", "ffmpeg.exe", "ffprobe",
                         "ffprobe.exe", "python", "python.exe", "python3", "py", "py.exe"})


#: Valeur par défaut des paramètres `layout` : le paquet de CE processus (`package_layout()`) ; `None` = développement.
PROCESS = object()


class RuntimeProblemCode(StrEnum):
    MANIFEST_MISSING = "runtime_manifest_missing"
    MANIFEST_INVALID = "runtime_manifest_invalid"
    RUNTIME_MISSING = "private_runtime_missing"
    INTEGRITY_FAILED = "private_runtime_integrity_failed"


@dataclass(frozen=True, slots=True)
class RuntimeProblem:
    code: RuntimeProblemCode
    component: str
    detail: str

    def to_payload(self) -> dict:
        return {"code": self.code.value, "component": self.component, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PackageLayout:
    """Emplacements du paquet, dérivés du seul dossier d'installation (`CODE_ROOT.parent`)."""

    install_root: Path

    @property
    def app(self) -> Path:
        return self.install_root / APP_DIR

    @property
    def python_dir(self) -> Path:
        return self.install_root / RUNTIME_DIR / PYTHON_DIR

    @property
    def python_exe(self) -> Path:
        return self.python_dir / "python.exe"

    @property
    def node_dir(self) -> Path:
        return self.install_root / RUNTIME_DIR / NODE_DIR

    @property
    def node_exe(self) -> Path:
        return self.node_dir / "node.exe"

    @property
    def ffmpeg_exe(self) -> Path:
        return self.install_root / RUNTIME_DIR / FFMPEG_DIR / "ffmpeg.exe"

    @property
    def manifest_path(self) -> Path:
        return self.install_root / RUNTIME_MANIFEST

    def manifest(self) -> dict | None:
        """Le manifeste validé, `None` s'il manque ; `ValueError` s'il est illisible ou d'un autre schéma."""

        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise ValueError(f"{RUNTIME_MANIFEST} illisible ({type(exc).__name__})") from exc
        if (not isinstance(payload, dict) or payload.get("schema") != RUNTIME_MANIFEST_SCHEMA
                or payload.get("schema_version") != RUNTIME_MANIFEST_VERSION):
            raise ValueError(f"{RUNTIME_MANIFEST} : schéma attendu {RUNTIME_MANIFEST_SCHEMA!r} v{RUNTIME_MANIFEST_VERSION}")
        return payload

    def ships(self, component: str) -> bool:
        """Vrai si le manifeste déclare ce runtime livré (`runtimes.<component>`) ; faux sans manifeste lisible."""

        try:
            manifest = self.manifest()
        except ValueError:
            return False
        return bool(manifest and isinstance(manifest.get("runtimes"), dict) and component in manifest["runtimes"])

    def tool(self, name: str) -> str | None:
        """Chemin d'un outil possédé par le paquet, ou `None` : jamais le PATH pour ces noms."""

        key = name.lower().removesuffix(".exe")
        if key == "node":
            path = self.node_exe
        elif key in {"ffmpeg", "ffprobe"} and self.ships("ffmpeg"):
            path = self.ffmpeg_exe.with_name(f"{key}.exe")
        elif key in {"python", "python3"}:
            path = self.python_exe
        else:
            return None
        return str(path) if path.is_file() else None


def layout_for(code_root: Path) -> PackageLayout | None:
    """Le paquet de ce code s'il tourne comme produit installé, sinon `None` (checkout de développement).

    Le marqueur fait foi (`read_product_marker`, `ConfigurationError` s'il est illisible) ; le paquet est le parent de
    `CODE_ROOT`. Un marqueur posé hors d'un dossier `app/` reste un produit installé : ses runtimes sont alors absents
    et le diagnostic le dit (`private_runtime_missing`), sans jamais retomber sur le PATH.
    """

    root = Path(code_root)
    if read_product_marker(root) is None:
        return None
    return PackageLayout(root.parent)


@lru_cache(maxsize=1)
def package_layout() -> PackageLayout | None:
    """`layout_for(CODE_ROOT)`, lu une fois par processus (le marqueur ne change pas sous un processus vivant)."""

    return layout_for(CODE_ROOT)


def which(name: str, *, layout: object = PROCESS,
          fallback: Callable[[str], str | None] = shutil.which) -> str | None:
    """`shutil.which` en développement ; en produit installé, les outils possédés par le paquet seulement."""

    current = package_layout() if layout is PROCESS else layout
    if current is None:
        return fallback(name)
    if name.lower() in OWNED_TOOLS:
        return current.tool(name)
    return fallback(name)


def child_path(path_value: str, *, layout: object = PROCESS) -> str:
    """PATH d'un processus enfant : en produit installé, `runtime/node` d'abord ; inchangé en développement."""

    current = package_layout() if layout is PROCESS else layout
    if current is None:
        return path_value
    head = str(current.node_dir)
    parts = [part for part in str(path_value or "").split(os.pathsep) if part]
    return os.pathsep.join([head, *[p for p in parts if os.path.normcase(p) != os.path.normcase(head)]])


def missing_tool_hint(tool: str, *, layout: object = PROCESS) -> str:
    """Fin de phrase des refus « outil absent » : réinstaller le produit, ou l'installer sur le PATH en développement."""

    current = package_layout() if layout is PROCESS else layout
    if current is None:
        return f"{tool} was not found on PATH; install it, Jarvis does not"
    return f"the private {tool} runtime of this Jarvis installation is missing; repair or reinstall Jarvis"


# ---------------------------------------------------------------------- empreintes

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_tree(root: Path) -> Iterable[tuple[str, Path]]:
    """(chemin relatif POSIX, chemin) de chaque fichier sous `root`, trié ; aucun lien suivi."""

    rows: list[tuple[str, Path]] = []
    stack = [Path(root)]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    rows.append((path.relative_to(root).as_posix(), path))
    return sorted(rows)


def tree_sha256(root: Path, *, exclude: frozenset[str] = frozenset()) -> tuple[str, int]:
    """Empreinte d'un arbre (chemins relatifs + contenu) et nombre de fichiers ; indépendante du dossier d'installation."""

    digest = hashlib.sha256()
    count = 0
    for relative, path in iter_tree(root):
        if relative in exclude:
            continue
        digest.update(f"{relative}\0{file_sha256(path)}\n".encode("utf-8"))
        count += 1
    return digest.hexdigest(), count


# ---------------------------------------------------------------------- diagnostic

def diagnostics(layout: object = PROCESS) -> dict:
    """Bloc `runtimes` de `/v1/health` et du journal de démarrage : présence et versions, sans hachage ni chemin absolu."""

    current = package_layout() if layout is PROCESS else layout
    if current is None:
        return {"mode": "development", "source": "path"}
    payload: dict = {"mode": "installed", "source": "package"}
    try:
        manifest = current.manifest()
    except ValueError as exc:
        return payload | {"status": "invalid", "problems": [RuntimeProblem(
            RuntimeProblemCode.MANIFEST_INVALID, "manifest", str(exc)).to_payload()]}
    if manifest is None:
        return payload | {"status": "invalid", "problems": [RuntimeProblem(
            RuntimeProblemCode.MANIFEST_MISSING, "manifest", f"{RUNTIME_MANIFEST} absent").to_payload()]}
    runtimes = manifest.get("runtimes") if isinstance(manifest.get("runtimes"), dict) else {}
    problems = [problem.to_payload() for problem in _presence_problems(current, runtimes)]
    return payload | {"status": "ok" if not problems else "degraded",
                      "edition": (manifest.get("product") or {}).get("edition"),
                      "version": (manifest.get("product") or {}).get("version"),
                      "runtimes": {name: (entry or {}).get("version") for name, entry in sorted(runtimes.items())},
                      "excluded": sorted((entry or {}).get("id") for entry in manifest.get("excluded") or [] if entry),
                      "problems": problems}


def _presence_problems(layout: PackageLayout, runtimes: Mapping[str, Mapping]) -> list[RuntimeProblem]:
    problems: list[RuntimeProblem] = []
    for name, entry in sorted(runtimes.items()):
        executable = (entry or {}).get("executable")
        if not executable or not (layout.install_root / executable).is_file():
            problems.append(RuntimeProblem(RuntimeProblemCode.RUNTIME_MISSING, name, f"{executable or name} absent"))
    return problems


def verify_runtimes(layout: PackageLayout) -> list[RuntimeProblem]:
    """Vérification complète (à la demande) : chaque runtime présent et son arbre égal à l'empreinte du manifeste."""

    try:
        manifest = layout.manifest()
    except ValueError as exc:
        return [RuntimeProblem(RuntimeProblemCode.MANIFEST_INVALID, "manifest", str(exc))]
    if manifest is None:
        return [RuntimeProblem(RuntimeProblemCode.MANIFEST_MISSING, "manifest", f"{RUNTIME_MANIFEST} absent")]
    runtimes = manifest.get("runtimes") if isinstance(manifest.get("runtimes"), dict) else {}
    problems = _presence_problems(layout, runtimes)
    missing = {problem.component for problem in problems}
    for name, entry in sorted(runtimes.items()):
        if name in missing:
            continue
        root = layout.install_root / str(entry.get("root") or "")
        expected = entry.get("tree_sha256")
        actual, _count = tree_sha256(root)
        if actual != expected:
            problems.append(RuntimeProblem(RuntimeProblemCode.INTEGRITY_FAILED, name,
                                           f"tree sha256 {actual[:12]}… differs from the manifest"))
    return problems
