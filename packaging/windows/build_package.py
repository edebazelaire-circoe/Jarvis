#!/usr/bin/env python3
"""Paquet Windows de JARVIS Presentation Edition (docs/windows-packaging.md, Slice 06).

Quatre commandes, aucune ne touche au JARVIS vivant ni à `%LOCALAPPDATA%\\CIRCOE\\Jarvis` :

    python packaging/windows/build_package.py lock  [--channel production|internal] [--cache DIR] [--constraints FILE]
        Résout `requirements.in` en roues Windows cp314 et réécrit `requirements.lock`
        (chaque dépendance transitive, version exacte, SHA-256). Maintenance seulement (réseau).
        `--channel internal` : résout `requirements-internal.in` sous la contrainte de `requirements.lock` et écrit
        `requirements-internal.lock` (seulement les roues EN PLUS du build interne).

    python packaging/windows/build_package.py build --out DIR [--channel production|internal] [--cache DIR] [--rev HEAD]
        Construit le dossier d'installation : Python embarquable et Node épinglés (SHA-256
        vérifié), roues installées depuis le verrou (`--require-hashes`, roues seulement),
        code `jarvis/` tiré de git (`git archive`, rien de non versionné), marqueur produit,
        bytecode précompilé (`unchecked-hash` : rien n'est écrit dans le dossier du programme
        à l'exécution), licences, `third-party-manifest.json` et `runtime-manifest.json`.
        Canal (HD-V12-01, docs/windows-packaging.md › Canaux) : `production` par défaut, sans openWakeWord ;
        `internal` sur demande explicite, qui ajoute l'extra `wakeword` (verrou `requirements-internal.lock`) et les
        trois modèles du catalogue épinglés SHA-256 sous `models/wake-word`, avec leurs avis de licence. Le canal
        est écrit dans `runtime-manifest.json` (`product.channel`) et `third-party-manifest.json`.
        Termine par une sonde du paquet lancé avec un PATH réduit à Windows. Exige un dépôt git (pas une archive des
        sources) et refuse un arbre de travail qui diffère de `--rev` sur `jarvis/`, `packaging/windows/`, `pyproject.toml`.

    python packaging/windows/build_package.py verify DIR
        Recalcule les empreintes des arbres et les compare au manifeste ; refuse un paquet de production qui
        porterait un composant réservé au build interne (`private_runtime.channel_problems`).

    python packaging/windows/build_package.py installer --package DIR --out FILE.exe
        Installeur par utilisateur (Slice 07, docs/product-install.md) : amorce C# compilée par le compilateur du
        .NET Framework livré avec Windows, paquet vérifié puis zippé (déterministe) et accolé, remorque JVSETUP1.

Le cache des téléchargements vit hors du dépôt (`%LOCALAPPDATA%\\Temp\\jarvis-build-cache` par défaut).
Lancer avec le Python de développement (`.venv`) de la MÊME version que le runtime épinglé (3.14.6) : pip y est
requis, et il produit le bytecode du paquet (graine de hachage fixée).
"""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from jarvis import private_runtime as PR  # noqa: E402 - après le chemin du dépôt
from jarvis.adapters import wakeword_model_catalog as WAKE_MODELS  # noqa: E402 - modèles épinglés du build interne
from jarvis.installation import PRODUCT_MARKER, marker_payload  # noqa: E402

RUNTIMES_FILE = HERE / "runtimes.json"
REQUIREMENTS_IN = HERE / "requirements.in"
LOCK_FILE = HERE / "requirements.lock"
INTERNAL_REQUIREMENTS_IN = HERE / "requirements-internal.in"
INTERNAL_LOCK_FILE = HERE / "requirements-internal.lock"
CHANNELS = PR.CHANNELS
DEFAULT_CHANNEL = PR.CHANNEL_PRODUCTION
#: Avis livré avec les modèles du build interne (CC BY-NC-SA 4.0 § 3(a)(1) : attribution, licence par URI,
#: modifications indiquées).
WAKE_MODELS_NOTICE = """openWakeWord pre-trained models - internal build of JARVIS only (HD-V12-01)

Files: melspectrogram.onnx, embedding_model.onnx, hey_jarvis_v0.1.onnx (models/wake-word/)
Source: https://github.com/dscripka/openWakeWord/releases/tag/v0.5.1 (release v0.5.1), unmodified;
size and SHA-256 pinned by jarvis/adapters/wakeword_model_catalog.py.
Author: David Scripka and the openWakeWord contributors.
License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)
         https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode
The openWakeWord code itself is Apache-2.0 (licenses/python-packages/openwakeword).

WARNING: non-commercial internal use only. These models must be replaced by another technology
before any production release of JARVIS (release blocker, docs/release.md).
Avertissement : usage interne non commercial ; à remplacer avant production.
"""
POLICY_FILE = HERE / "third_party_policy.json"
THIRD_PARTY_MANIFEST = "third-party-manifest.json"
LICENSES_DIR = "licenses"
PRODUCT_NAME = "Jarvis"
EDITION = "presentation"
#: Variables minimales d'une sonde « poste sans outils de développement ».
PROBE_ENV_KEYS = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA",
                  "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROCESSOR_ARCHITECTURE",
                  "NUMBER_OF_PROCESSORS", "OS", "HOMEDRIVE", "HOMEPATH")
_WHEEL = re.compile(r"^(?P<name>[^-]+)-(?P<version>[^-]+)(?:-\d[^-]*)?-[^-]+-[^-]+-[^-]+\.whl$")
_LOCK_LINE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>\S+)\s+--hash=sha256:(?P<sha>[0-9a-f]{64})$")


class BuildError(RuntimeError):
    """Échec de build nommé : jamais un paquet à moitié construit présenté comme bon."""


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def default_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "Temp" / "jarvis-build-cache"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def python_tag(version: str) -> tuple[str, str]:
    """`3.14.6` → (`3.14`, `cp314`)."""

    major, minor = version.split(".")[:2]
    return f"{major}.{minor}", f"cp{major}{minor}"


def pip_target_args(runtimes: dict) -> list[str]:
    short, abi = python_tag(runtimes["runtimes"]["python"]["version"])
    return ["--platform", "win_amd64", "--python-version", short, "--implementation", "cp", "--abi", abi,
            "--only-binary", ":all:"]


# ---------------------------------------------------------------------- verrou

def parse_lock(text: str) -> list[dict]:
    """Lignes `nom==version --hash=sha256:…` (une par roue, les suites `\\` jointes)."""

    joined = re.sub(r"\\\s*\n\s*", " ", text)
    rows: list[dict] = []
    for raw in joined.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.match(line)
        if not match:
            raise BuildError(f"requirements.lock: ligne illisible: {line[:80]}")
        rows.append({"name": normalize(match["name"]), "version": match["version"], "sha256": match["sha"]})
    return rows


def render_lock(rows: list[dict], channel: str = DEFAULT_CHANNEL) -> str:
    if channel == DEFAULT_CHANNEL:
        header = ("# Verrou de l'édition presentation (docs/windows-packaging.md) : NE PAS ÉDITER À LA MAIN.\n"
                  "# Généré par `python packaging/windows/build_package.py lock` depuis requirements.in.\n"
                  "# Une roue Windows cp314 par dépendance, transitives comprises ; pip l'installe avec --require-hashes.\n")
    else:
        header = ("# Verrou du build INTERNE (HD-V12-01, docs/windows-packaging.md › Canaux) : NE PAS ÉDITER À LA MAIN.\n"
                  "# Généré par `python packaging/windows/build_package.py lock --channel internal` depuis\n"
                  "# requirements-internal.in, sous la contrainte de requirements.lock : seulement les roues EN PLUS.\n")
    body = "".join(f"{row['name']}=={row['version']} \\\n    --hash=sha256:{row['sha256']}\n"
                   for row in sorted(rows, key=lambda r: r["name"]))
    return header + body


def command_lock(args: argparse.Namespace) -> int:
    runtimes = load_json(RUNTIMES_FILE)
    channel = getattr(args, "channel", DEFAULT_CHANNEL)
    internal = channel == PR.CHANNEL_INTERNAL
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lock-", dir=str(args.cache)) as tmp:
        target = Path(tmp) / "wheels"
        target.mkdir()
        argv = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "-r",
                str(INTERNAL_REQUIREMENTS_IN if internal else REQUIREMENTS_IN), "-d", str(target), *pip_target_args(runtimes)]
        base = {row["name"]: row for row in parse_lock(LOCK_FILE.read_text(encoding="utf-8"))} if internal else {}
        if internal:  # une dépendance partagée garde la version (et l'empreinte) de la production
            constraints = Path(tmp) / "production-constraints.txt"
            constraints.write_text("".join(f"{name}=={row['version']}\n" for name, row in sorted(base.items())),
                                   encoding="utf-8")
            argv += ["-c", str(constraints)]
        if args.constraints:
            argv += ["-c", str(args.constraints)]
        log("résolution : " + " ".join(argv[3:]))
        subprocess.run(argv, check=True)
        rows = []
        for wheel in sorted(target.glob("*.whl")):
            match = _WHEEL.match(wheel.name)
            if not match:
                raise BuildError(f"nom de roue inattendu: {wheel.name}")
            rows.append({"name": normalize(match["name"]), "version": match["version"], "sha256": PR.file_sha256(wheel)})
        others = [p.name for p in target.iterdir() if p.suffix != ".whl"]
        if others:
            raise BuildError(f"fichiers qui ne sont pas des roues: {others}")
    if internal:
        drift = [f"{row['name']} {row['version']}" for row in rows if row["name"] in base
                 and (base[row["name"]]["version"], base[row["name"]]["sha256"]) != (row["version"], row["sha256"])]
        if drift:
            raise BuildError(f"le build interne changerait des roues de la production : {drift}")
        rows = [row for row in rows if row["name"] not in base]
    destination = INTERNAL_LOCK_FILE if internal else LOCK_FILE
    destination.write_text(render_lock(rows, channel), encoding="utf-8")
    log(f"{len(rows)} roues verrouillées dans {destination.name}")
    return 0


# ---------------------------------------------------------------------- canaux (HD-V12-01)

def in_channel(entry: dict, channel: str) -> bool:
    """Une entrée de politique sans `channels` vaut pour tous les canaux."""

    return channel in entry.get("channels", CHANNELS)


def channel_policy(policy: dict, channel: str) -> dict:
    """La politique telle qu'elle s'applique à `channel` : roues, modèles et exclusions de ce canal seulement."""

    if channel not in CHANNELS or channel not in (policy.get("channels") or {}):
        raise BuildError(f"canal inconnu {channel!r} (attendu : {', '.join(CHANNELS)})")
    return {**policy, "channel": channel,
            "python_packages": {name: entry for name, entry in policy["python_packages"].items() if in_channel(entry, channel)},
            "models": {name: entry for name, entry in (policy.get("models") or {}).items() if in_channel(entry, channel)},
            "excluded": [entry for entry in policy["excluded"] if in_channel(entry, channel)]}


def channel_locks(policy: dict, channel: str) -> list[Path]:
    """Les verrous que ce canal installe (`channels.<canal>.locks`), la production d'abord."""

    names = ((policy.get("channels") or {}).get(channel) or {}).get("locks") or [LOCK_FILE.name]
    return [HERE / name for name in names]


def read_locks(locks: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for lock in locks:
        rows += parse_lock(lock.read_text(encoding="utf-8"))
    names = [row["name"] for row in rows]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise BuildError(f"roues verrouillées deux fois : {duplicated}")
    return rows


# ---------------------------------------------------------------------- téléchargements

def fetch_verified(entry: dict, cache: Path) -> Path:
    """L'archive épinglée, téléchargée une fois dans le cache ; SHA-256 (et taille) revérifiés à chaque build."""

    cache.mkdir(parents=True, exist_ok=True)
    target = cache / entry["url"].rsplit("/", 1)[-1]
    if not target.is_file():
        partial = target.with_suffix(target.suffix + ".partial")
        log(f"téléchargement {entry['url']}")
        with urllib.request.urlopen(entry["url"], timeout=120) as response, open(partial, "wb") as handle:  # noqa: S310 - URL épinglée https
            shutil.copyfileobj(response, handle, 1 << 20)
        partial.replace(target)
    actual = PR.file_sha256(target)
    if actual != entry["sha256"]:
        target.unlink()
        raise BuildError(f"{target.name}: SHA-256 {actual} ≠ {entry['sha256']} (fichier retiré du cache)")
    if entry.get("size") and target.stat().st_size != entry["size"]:
        target.unlink()
        raise BuildError(f"{target.name}: taille {target.stat().st_size} ≠ {entry['size']}")
    return target


def safe_destination(target: Path, name: str, *, strip_components: int = 0, label: str) -> Path | None:
    r"""Destination d'un membre d'archive sous `target`, `None` s'il ne reste rien après `strip_components`.

    Refuse (Zip Slip) : `..`, nom absolu (`/x`, `\x`), lettre de lecteur (`C:x`, `C:\x`), et toute destination
    qui sortirait de `target` une fois résolue.
    """

    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(name).drive or ":" in normalized:
        raise BuildError(f"{label}: chemin refusé {name}")
    raw = normalized.split("/")
    if ".." in raw:
        raise BuildError(f"{label}: chemin refusé {name}")
    parts = [part for part in raw if part not in ("", ".")][strip_components:]
    if not parts:
        return None
    destination = target.joinpath(*parts)
    if not destination.resolve().is_relative_to(target.resolve()):
        raise BuildError(f"{label}: chemin refusé {name}")
    return destination


def extract_zip(archive: Path, target: Path, *, strip_components: int = 0) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            destination = safe_destination(target, info.filename, strip_components=strip_components, label=archive.name)
            if destination is None or info.is_dir():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, open(destination, "wb") as sink:
                shutil.copyfileobj(source, sink, 1 << 20)


def pth_content(version: str) -> str:
    r"""Chemins du Python embarquable, et rien d'autre : sa bibliothèque, `Lib\site-packages` (+ dossiers de pywin32) et
    le code (`..\..\app`).

    Pas de ligne `import site` : l'interpréteur tourne alors comme `-S`, donc ni site utilisateur
    (`%APPDATA%\Python\Python314\site-packages`, qui sur un poste de développeur porte par exemple onnxruntime et
    réintroduirait des composants exclus) ni fichiers `.pth`. Un fichier `._pth` rend aussi l'interpréteur sourd à
    `PYTHONPATH`/`PYTHONHOME` : le paquet ne lit jamais un code venu de l'environnement (I-002 point 2). Ce que
    `pywin32.pth` aurait fait est fait ici (dossiers) et par `install_pywin32_dlls` (DLL à côté de `python.exe`).
    """

    _short, abi = python_tag(version)
    lines = [f"python{abi[2:]}.zip", ".", r"Lib\site-packages", r"Lib\site-packages\win32", r"Lib\site-packages\win32\lib",
             r"Lib\site-packages\pythonwin", "..\\..\\" + PR.APP_DIR]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- étapes du build

def build_python(out: Path, runtimes: dict, cache: Path) -> Path:
    entry = runtimes["runtimes"]["python"]
    archive = fetch_verified(entry, cache / "runtimes")
    target = out / PR.RUNTIME_DIR / PR.PYTHON_DIR
    extract_zip(archive, target)
    pth = sorted(target.glob("python*._pth"))
    if len(pth) != 1:
        raise BuildError(f"Python embarquable sans fichier ._pth unique ({[p.name for p in pth]})")
    pth[0].write_text(pth_content(entry["version"]), encoding="ascii", newline="\r\n")
    return target


def install_wheels(out: Path, runtimes: dict, cache: Path, locks: list[Path] | None = None) -> Path:
    wheels = cache / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    requirements = [arg for lock in (locks or [LOCK_FILE]) for arg in ("-r", str(lock))]
    # `--no-cache-dir` (I-007 point 2) : pip n'écrit rien dans le cache de l'utilisateur ; le seul cache est `wheels`.
    common = ["--disable-pip-version-check", "--no-cache-dir", "--require-hashes", "--no-deps", *requirements,
              *pip_target_args(runtimes)]
    subprocess.run([sys.executable, "-m", "pip", "download", "-d", str(wheels), *common], check=True)
    site = out / PR.RUNTIME_DIR / PR.PYTHON_DIR / "Lib" / "site-packages"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "--no-compile",
                    "--no-warn-script-location", "--target", str(site), *common], check=True)
    # Lanceurs de scripts : ils portent le chemin absolu du Python de BUILD ; le produit ne les utilise jamais.
    shutil.rmtree(site / "bin", ignore_errors=True)
    shutil.rmtree(site / "Scripts", ignore_errors=True)
    drop_script_records(site)
    install_pywin32_dlls(site)
    return site


def drop_script_records(site: Path) -> None:
    """Retire des `RECORD` les lanceurs supprimés (`bin/…`) : leur empreinte dépend du dossier de build (non reproductible)."""

    for record in sorted(site.glob("*.dist-info/RECORD")):
        with open(record, encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines(keepends=True)
        kept = [line for line in lines if not line.startswith(("../../bin/", "bin/", "../../Scripts/", "Scripts/"))]
        if kept != lines:
            record.write_text("".join(kept), encoding="utf-8", newline="")


def install_pywin32_dlls(site: Path) -> None:
    """`pywintypes3xx.dll`/`pythoncom3xx.dll` à côté de `python.exe` (dossier de l'application dans l'ordre de recherche
    des DLL) : ce que fait `pywin32_bootstrap` via `pywin32.pth`, que le paquet ne traite pas (pas de `site`)."""

    for dll in sorted((site / "pywin32_system32").glob("*.dll")):
        shutil.copyfile(dll, site.parents[1] / dll.name)


def build_wake_models(out: Path, cache: Path) -> Path:
    """Build interne : les trois modèles du catalogue, vérifiés (taille, SHA-256) dans le cache puis copiés là où le
    produit installé les lit (`PackageLayout.wake_models_dir`). Le produit ne télécharge rien au premier lancement."""

    source = cache / "wake-word-models"
    target = out / PR.MODELS_DIR / PR.WAKE_MODELS_SUBDIR
    target.mkdir(parents=True, exist_ok=True)
    for spec in WAKE_MODELS.MODELS:
        try:
            cached = WAKE_MODELS.download_spec(spec, source)
            shutil.copyfile(cached, spec.path(target))
            WAKE_MODELS.verify_spec(spec, target)
        except WAKE_MODELS.WakeModelError as exc:
            raise BuildError(f"modèle {spec.filename} : {exc.code} : {exc}") from exc
    return target


def build_node(out: Path, runtimes: dict, cache: Path) -> Path:
    entry = runtimes["runtimes"]["node"]
    archive = fetch_verified(entry, cache / "runtimes")
    target = out / PR.RUNTIME_DIR / PR.NODE_DIR
    extract_zip(archive, target, strip_components=int(entry.get("strip_components", 0)))
    if not (target / "node.exe").is_file() or not (target / "node_modules" / "npm" / "bin" / "npm-cli.js").is_file():
        raise BuildError("archive Node sans node.exe ou npm-cli.js")
    return target


#: Ce que le build lit dans le dépôt : le code (`git archive`), le verrou, la politique, les runtimes, le marqueur et la
#: version. Ils doivent être ceux de `--rev` : sinon le paquet dirait une révision et en porterait une autre.
BUILD_INPUTS = ("jarvis", "packaging/windows", "pyproject.toml")
PREREQUISITES = ("le build exige un dépôt git du code (clone ou worktree, pas une archive) avec git sur le PATH, et le "
                 "Python de développement de la version du runtime épinglé (docs/windows-packaging.md › Build)")


def git(*args: str) -> bytes:
    """`git -C <dépôt> …` ; échec = `BuildError` avec la commande, le code et le message complet de git."""

    try:
        result = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True)
    except FileNotFoundError as exc:
        raise BuildError(f"git introuvable : {PREREQUISITES}") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise BuildError(f"`git {' '.join(args)}` a échoué (code {result.returncode}) : {message}\n{PREREQUISITES}")
    return result.stdout


def git_revision(rev: str) -> str:
    return git("rev-parse", "--verify", f"{rev}^{{commit}}").decode("utf-8").strip()


def ensure_inputs_match(revision: str) -> None:
    """Refuse un arbre de travail dont les entrées du build diffèrent de `revision` (modifiées, ou autre révision)."""

    changed = [line for line in git("diff", "--name-only", revision, "--", *BUILD_INPUTS).decode("utf-8").splitlines()
               if line.strip()]
    if changed:
        shown = ", ".join(changed[:10]) + (f" (+{len(changed) - 10})" if len(changed) > 10 else "")
        raise BuildError(f"l'arbre de travail diffère de {revision[:12]} sur les entrées du build : {shown}. "
                         "Committez, ou construisez depuis un checkout propre de cette révision.")


def build_app(out: Path, revision: str) -> Path:
    """`jarvis/` tel que versionné à `revision` (aucun fichier non suivi, aucun `__pycache__`) + marqueur produit."""

    app = out / PR.APP_DIR
    app.mkdir(parents=True, exist_ok=True)
    archive = git("archive", "--format=tar", revision, "jarvis")
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            destination = safe_destination(app, member.name, label="git archive")
            if destination is None:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.extractfile(member).read())
    (app / PRODUCT_MARKER).write_text(json.dumps(marker_payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return app


def compileall_argv(out: Path, roots: list[Path]) -> list[str]:
    """`compileall` en un seul processus (`-j 1`) : avec `-j 0`, le bytecode de certains modules change d'un build à
    l'autre (QA S06 : 3 jeux différents sur 6 exécutions, `protocol/server.py` entre autres) ; `-j 1` : 4 sur 4 égaux."""

    return [sys.executable, "-m", "compileall", "-q", "-j", "1", "--invalidation-mode", "unchecked-hash",
            "-s", str(out), *[str(root) for root in roots]]


def precompile(out: Path, runtime_version: str, roots: list[Path]) -> None:
    """Bytecode `unchecked-hash` : jamais réécrit à l'exécution, identique d'un build à l'autre.

    Produit par le Python de BUILD, qui doit être exactement la version du runtime embarqué (même nombre magique),
    avec `PYTHONHASHSEED=0` : l'ordre des ensembles constants (`frozenset`) dans le bytecode dépend du hachage des
    chaînes, et le Python du paquet ignore l'environnement (`._pth`), donc ne peut pas fixer la graine.
    `-s <out>` retire le dossier de build des noms de fichiers enregistrés (traces lisibles, build reproductible).
    Un fichier tiers non compilable (exemple Python 2 livré dans une roue) est signalé, pas fatal.
    """

    if platform.python_version() != runtime_version:
        raise BuildError(f"Python de build {platform.python_version()} ≠ runtime {runtime_version} : bytecode incompatible")
    env = dict(os.environ, PYTHONHASHSEED="0")
    result = subprocess.run(compileall_argv(out, roots), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=env)
    if result.returncode != 0:
        failed = [line for line in result.stdout.splitlines() if line.startswith("*** Error compiling")]
        app_failures = [line for line in failed if f"{os.sep}{PR.APP_DIR}{os.sep}" in line or "app\\jarvis" in line]
        if app_failures or not failed:
            raise BuildError("compileall a échoué sur le code JARVIS:\n" + (result.stdout + result.stderr)[-2000:])
        log(f"compileall : {len(failed)} fichier(s) tiers non compilables ignorés")


def read_metadata(dist_info: Path) -> dict:
    message = email.parser.Parser().parsestr((dist_info / "METADATA").read_text(encoding="utf-8", errors="replace"),
                                              headersonly=True)
    classifiers = [value.split("::")[-1].strip() for value in message.get_all("Classifier") or []
                   if value.startswith("License ::")]
    declared = message.get("License-Expression") or (message.get("License") or "").strip().splitlines()[0:1]
    declared = declared if isinstance(declared, str) else (declared[0] if declared else "")
    return {"name": normalize(message.get("Name", "")), "version": message.get("Version", ""),
            "declared_license": declared[:120], "license_classifiers": classifiers,
            "home_page": message.get("Home-page") or ""}


def collect_licenses(out: Path, site: Path, runtimes: dict, policy: dict | None = None) -> dict[str, list[str]]:
    """Copie les textes de licence sous `licenses/<composant>/` ; rend les chemins relatifs par composant.

    `policy` (celle du canal construit) ajoute les textes qu'une roue range hors de `dist-info` (`license_files`,
    relatifs à `site-packages`, ex. onnxruntime) et l'avis des modèles livrés (`models`)."""

    licenses = out / LICENSES_DIR
    copied: dict[str, list[str]] = {}

    def copy(component: str, files: list[Path], base: Path) -> None:
        for path in sorted(files):
            relative = path.relative_to(base)
            destination = licenses / component / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            copied.setdefault(component, []).append(destination.relative_to(out).as_posix())

    python_dir = out / PR.RUNTIME_DIR / PR.PYTHON_DIR
    copy("python", [python_dir / runtimes["runtimes"]["python"]["license_file"]], python_dir)
    node_dir = out / PR.RUNTIME_DIR / PR.NODE_DIR
    copy("node", [node_dir / runtimes["runtimes"]["node"]["license_file"]], node_dir)
    for dist_info in sorted(site.glob("*.dist-info")):
        name = read_metadata(dist_info)["name"]
        files = [p for p in dist_info.rglob("*") if p.is_file() and (p.parent.name == "licenses" or "licenses" in p.parts
                 or re.match(r"(?i)^(licen[cs]e|copying|notice|authors)", p.name))]
        if files:
            copy(f"python-packages/{name}", files, dist_info)
    for name, entry in sorted(((policy or {}).get("python_packages") or {}).items()):
        extra = [site / relative for relative in entry.get("license_files") or []]
        missing = [path.relative_to(site).as_posix() for path in extra if not path.is_file()]
        if missing:
            raise BuildError(f"{name}: textes de licence déclarés absents de la roue : {missing}")
        if extra:
            copy(f"python-packages/{normalize(name)}", extra, site)
    for name in sorted(((policy or {}).get("models") or {})):
        notice = licenses / name / "NOTICE.txt"
        notice.parent.mkdir(parents=True, exist_ok=True)
        notice.write_text(WAKE_MODELS_NOTICE, encoding="utf-8", newline="\n")
        copied.setdefault(name, []).append(notice.relative_to(out).as_posix())
    return copied


def third_party_manifest(site: Path, lock_rows: list[dict], policy: dict, runtimes: dict,
                         licenses: dict[str, list[str]], models_dir: Path | None = None) -> dict:
    """Une ligne par composant livré (runtime, roue, modèle), plus les exclus et les dépendances externes ; refuse un
    trou.

    `policy` est celle du canal construit (`channel_policy`) : une roue réservée à un autre canal n'y a pas d'entrée,
    donc est refusée. Un composant réservé à certains canaux porte `channels`, que `verify` relit."""

    locked = {row["name"]: row for row in lock_rows}
    declared = {normalize(name): entry for name, entry in policy["python_packages"].items()}
    installed = {}
    for dist_info in sorted(site.glob("*.dist-info")):
        meta = read_metadata(dist_info)
        installed[meta["name"]] = meta
    problems = []
    problems += [f"{name}: installé mais absent du verrou" for name in installed if name not in locked]
    problems += [f"{name}: verrouillé mais non installé" for name in locked if name not in installed]
    problems += [f"{name}: aucune entrée dans third_party_policy.json" for name in installed if name not in declared]
    problems += [f"{name}: entrée de politique sans roue livrée" for name in declared if name not in installed]
    problems += [f"{name}: statut {entry.get('status')!r} non livrable" for name, entry in declared.items()
                 if name in installed and entry.get("status") != "bundled"]
    excluded = {normalize(item["id"]) for item in policy["excluded"] if item.get("kind") == "python-package"}
    problems += [f"{name}: composant exclu présent dans le paquet" for name in installed if name in excluded]
    problems += [f"{name}: aucun texte de licence livré" for name, entry in declared.items()
                 if name in installed and "channels" in entry and not licenses.get(f"python-packages/{name}")]
    models = policy.get("models") or {}
    if models and (models_dir is None or not models_dir.is_dir()):
        problems.append("modèles déclarés par la politique du canal mais non livrés")
    if not models and models_dir is not None and models_dir.exists():
        problems.append("modèles livrés alors que la politique du canal n'en déclare aucun")
    if problems:
        raise BuildError("manifeste tiers incomplet:\n  " + "\n  ".join(problems))
    components = []
    for name, entry in sorted(runtimes["runtimes"].items()):
        components.append({"id": name, "kind": "runtime", "version": entry["version"], "license": entry["license"],
                           "status": "bundled", "source": entry["url"], "sha256": entry["sha256"],
                           "license_files": licenses.get(name, [])})
    for name, meta in sorted(installed.items()):
        components.append({"id": name, "kind": "python-package", "version": meta["version"],
                           "license": declared[name]["license"], "declared_license": meta["declared_license"],
                           "license_classifiers": meta["license_classifiers"], "status": "bundled",
                           "source": f"https://pypi.org/project/{name}/{meta['version']}/",
                           "sha256": locked[name]["sha256"], "notes": declared[name].get("notes", ""),
                           "license_files": licenses.get(f"python-packages/{name}", []),
                           **({"channels": declared[name]["channels"]} if "channels" in declared[name] else {})})
    for name, entry in sorted(models.items()):
        for spec in WAKE_MODELS.MODELS:
            components.append({"id": f"{name}/{spec.key}", "kind": "model", "file": f"{entry['destination']}/{spec.filename}",
                               "license": entry["license"], "status": "bundled", "source": spec.url, "sha256": spec.sha256,
                               "size": spec.size, "channels": entry["channels"], "warning": entry.get("warning", ""),
                               "notes": entry.get("notes", ""), "license_files": licenses.get(name, [])})
    channel = policy.get("channel", DEFAULT_CHANNEL)
    payload = {"schema": "jarvis.third-party-manifest", "schema_version": 1, "edition": EDITION, "channel": channel,
               "components": components, "excluded": policy["excluded"], "external": policy["external"],
               "provisioned": policy["provisioned"]}
    warning = ((policy.get("channels") or {}).get(channel) or {}).get("warning")
    if warning:
        payload["warning"] = warning
    return payload


def node_npm_version(node_dir: Path) -> str:
    return load_json(node_dir / "node_modules" / "npm" / "package.json")["version"]


def runtime_manifest(out: Path, runtimes: dict, revision: str, policy: dict) -> dict:
    """Manifeste du paquet ; `policy` est celle du canal construit (`product.channel`, bloc `models` si livrés)."""

    project = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8"))
    entries = {}
    for name, executable in (("python", "python.exe"), ("node", "node.exe")):
        root = out / PR.RUNTIME_DIR / name
        tree, count = PR.tree_sha256(root)
        entries[name] = {"version": runtimes["runtimes"][name]["version"], "root": f"{PR.RUNTIME_DIR}/{name}",
                         "executable": f"{PR.RUNTIME_DIR}/{name}/{executable}", "tree_sha256": tree, "files": count,
                         "source": {"url": runtimes["runtimes"][name]["url"], "sha256": runtimes["runtimes"][name]["sha256"]}}
    entries["node"]["npm_version"] = node_npm_version(out / PR.RUNTIME_DIR / PR.NODE_DIR)
    app_tree, app_files = PR.tree_sha256(out / PR.APP_DIR)
    lic_tree, lic_files = PR.tree_sha256(out / LICENSES_DIR)
    channel = policy.get("channel", DEFAULT_CHANNEL)
    product = {"name": PRODUCT_NAME, "edition": EDITION, "version": project[1] if project else "unknown",
               "source_revision": revision, "channel": channel}
    warning = ((policy.get("channels") or {}).get(channel) or {}).get("warning")
    if warning:
        product["channel_warning"] = warning
    extra = {}
    if (out / PR.MODELS_DIR).is_dir():
        models_tree, models_files = PR.tree_sha256(out / PR.MODELS_DIR)
        extra["models"] = {"root": PR.MODELS_DIR, "tree_sha256": models_tree, "files": models_files,
                           "wake_word": f"{PR.MODELS_DIR}/{PR.WAKE_MODELS_SUBDIR}"}
    return {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
            "product": product, **extra,
            "app": {"root": PR.APP_DIR, "tree_sha256": app_tree, "files": app_files},
            "licenses": {"root": LICENSES_DIR, "tree_sha256": lic_tree, "files": lic_files},
            "third_party_manifest_sha256": PR.file_sha256(out / THIRD_PARTY_MANIFEST),
            "runtimes": entries,
            "excluded": [{"id": item["id"], "kind": item["kind"], "reason": item["reason"]} for item in policy["excluded"]],
            "external": [{"id": item["id"], "resolution": item["resolution"]} for item in policy["external"]],
            "provisioned": [{"id": item["id"], "resolution": item["resolution"]} for item in policy["provisioned"]]}


def package_digest(manifest: dict) -> str:
    """Empreinte du paquet entier (`private_runtime.package_digest`, partagée avec l'installeur)."""

    return PR.package_digest(manifest)


def probe_env(out: Path) -> dict[str, str]:
    """Environnement d'un poste sans outils de développement : PATH = Windows seulement, aucune variable Python/Node."""

    env = {key: os.environ[key] for key in PROBE_ENV_KEYS if key in os.environ}
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env["PATH"] = os.pathsep.join([str(Path(root) / "System32"), root, str(Path(root) / "System32" / "Wbem")])
    return env


#: Modules jamais importables d'un paquet, par canal (le build interne livre openWakeWord et onnxruntime).
PROBE_EXCLUDED_MODULES = {
    PR.CHANNEL_PRODUCTION: ("onnxruntime", "openwakeword", "imageio_ffmpeg", "pvporcupine", "sherpa_onnx"),
    PR.CHANNEL_INTERNAL: ("imageio_ffmpeg", "pvporcupine", "sherpa_onnx"),
}

#: Sonde lancée avec le Python du paquet : `argv[1]` = canal, `argv[2:]` = modules qui ne doivent pas s'importer.
#: Réveil vocal (les deux canaux) : défaut d'un profil vierge (`wake_word_settings.load({})`) ; build interne : le
#: détecteur openWakeWord est construit depuis les modèles du paquet et nourri de silence (trames de zéros), sans
#: jamais ouvrir de périphérique audio.
PROBE_SCRIPT = r"""
import json, shutil, subprocess, sys
import aiohttp, httpx, numpy, sounddevice, mcp, googleapiclient, google_auth_oauthlib, livekit.rtc, pynput, tzdata
import jarvis, jarvis.app
from jarvis import private_runtime as pr
from jarvis.installation import detect_installation
from jarvis.runtime import wake_word_settings
channel = sys.argv[1]
layout = pr.package_layout()
node = pr.which("node")
version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
missing = {name: shutil.which(name) for name in ("python", "node", "npm", "ffmpeg", "git")}
import importlib.util
excluded = {name: importlib.util.find_spec(name) is not None for name in sys.argv[2:]}
import win32api, pywintypes, mcp.client.stdio
outside = [p for p in sys.path if not p.lower().startswith(str(layout.install_root).lower())]
blank = wake_word_settings.load({})
wake = {"default_enabled": blank.enabled, "default_provider": blank.provider}
if channel == "internal":
    from jarvis.adapters import wakeword_model_catalog as catalog
    from jarvis.adapters.wakeword_openwakeword import openwakeword_engine_factory
    model_dir = catalog.default_model_dir()
    engine = openwakeword_engine_factory(keyword="hey_jarvis")()
    silence = [engine.process([0] * engine.frame_length) for _ in range(5)]
    engine.delete()
    wake |= {"model_dir_in_package": str(model_dir).lower().startswith(str(layout.wake_models_dir).lower()),
             "models_verified": sorted(catalog.verified_paths()), "detector": type(engine).__name__,
             "silence_detections": silence}
print(json.dumps({"python": sys.version.split()[0], "executable_in_package": sys.executable.lower().startswith(str(layout.install_root).lower()),
                  "installed": detect_installation().installed, "node": version, "node_private": node.lower().startswith(str(layout.node_dir).lower()),
                  "ffmpeg": pr.which("ffmpeg"), "no_site": sys.flags.no_site == 1, "sys_path_outside_package": outside,
                  "excluded_importable": excluded, "py_launcher_on_path": shutil.which("py"),
                  "path_tools": missing, "diagnostics": pr.diagnostics(), "channel": channel, "wake": wake}))
"""


def probe(out: Path, channel: str = DEFAULT_CHANNEL) -> dict:
    python = out / PR.RUNTIME_DIR / PR.PYTHON_DIR / "python.exe"
    env = probe_env(out) | {"LOCALAPPDATA": str(out / "_probe-localappdata")}
    result = subprocess.run([str(python), "-c", PROBE_SCRIPT, channel, *PROBE_EXCLUDED_MODULES[channel]],
                            capture_output=True, text=True, env=env, cwd=str(out),
                            encoding="utf-8", errors="replace", timeout=300)
    shutil.rmtree(out / "_probe-localappdata", ignore_errors=True)
    if result.returncode != 0:
        raise BuildError("sonde du paquet en échec:\n" + (result.stdout + result.stderr)[-3000:])
    report = json.loads(result.stdout.strip().splitlines()[-1])
    problems = probe_problems(report, channel)
    if problems:
        raise BuildError(f"sonde du paquet inattendue ({'; '.join(problems)}): {json.dumps(report)}")
    return report


def wake_probe_problems(wake: dict | None, channel: str) -> list[str]:
    """Le réveil vocal selon le canal : production = défaut F9 seul ; interne = armé par défaut, moteur chargé depuis
    les modèles du paquet, aucune détection sur du silence."""

    wake = wake or {}
    if channel == PR.CHANNEL_PRODUCTION:
        return [] if wake.get("default_enabled") is False else ["production : mot de réveil vocal armé par défaut"]
    problems = []
    if wake.get("default_enabled") is not True or wake.get("default_provider") != "openwakeword":
        problems.append("interne : le mot de réveil openWakeWord n'est pas armé par défaut")
    if not wake.get("model_dir_in_package"):
        problems.append("interne : les modèles ne sont pas lus dans le paquet")
    if sorted(wake.get("models_verified") or []) != sorted(spec.key for spec in WAKE_MODELS.MODELS):
        problems.append("interne : modèles non vérifiés")
    detections = wake.get("silence_detections")
    if not detections or any(value >= 0 for value in detections):
        problems.append(f"interne : détecteur non chargé ou déclenché par du silence ({detections!r})")
    return problems


def probe_problems(report: dict, channel: str = DEFAULT_CHANNEL) -> list[str]:
    """Écarts du rapport de sonde au contrat du paquet du canal ; vide = paquet conforme."""

    problems = [f"{key} faux" for key in ("installed", "executable_in_package", "node_private", "no_site")
                if not report.get(key)]
    if report.get("sys_path_outside_package"):
        problems.append(f"sys.path hors du paquet : {report['sys_path_outside_package']}")
    importable = sorted(name for name, present in (report.get("excluded_importable") or {}).items() if present)
    if importable:
        problems.append(f"composants exclus importables : {importable}")
    problems += wake_probe_problems(report.get("wake"), channel)
    if report.get("ffmpeg") is not None:
        problems.append("ffmpeg résolu alors que l'édition ne le livre pas")
    on_path = sorted(name for name, found in (report.get("path_tools") or {}).items() if found)
    if on_path:
        problems.append(f"outils trouvés sur le PATH réduit : {on_path}")
    status = (report.get("diagnostics") or {}).get("status")
    if status != "ok":
        problems.append(f"diagnostic des runtimes : {status}")
    return problems


def command_build(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    cache = Path(args.cache).resolve()
    if out.exists() and any(out.iterdir()):
        raise BuildError(f"{out} n'est pas vide : un build part toujours d'un dossier vide")
    if out == REPO or REPO in out.parents:
        raise BuildError("le dossier de sortie ne peut pas être dans le dépôt")
    channel = getattr(args, "channel", DEFAULT_CHANNEL)
    revision = git_revision(args.rev)
    ensure_inputs_match(revision)
    runtimes = load_json(RUNTIMES_FILE)
    full_policy = load_json(POLICY_FILE)
    policy = channel_policy(full_policy, channel)
    locks = channel_locks(full_policy, channel)
    lock_rows = read_locks(locks)
    out.mkdir(parents=True, exist_ok=True)
    log(f"révision {revision}, canal {channel} → {out}")
    warning = (full_policy["channels"][channel]).get("warning")
    if warning:
        log(f"AVERTISSEMENT ({channel}) : {warning}")
    build_python(out, runtimes, cache)
    site = install_wheels(out, runtimes, cache, locks)
    build_node(out, runtimes, cache)
    models_dir = build_wake_models(out, cache) if policy["models"] else None
    app = build_app(out, revision)
    precompile(out, runtimes["runtimes"]["python"]["version"], [app, site])
    licenses = collect_licenses(out, site, runtimes, policy)
    write_json(out / THIRD_PARTY_MANIFEST, third_party_manifest(site, lock_rows, policy, runtimes, licenses,
                                                                models_dir or out / PR.MODELS_DIR))
    manifest = runtime_manifest(out, runtimes, revision, policy)
    manifest["package_sha256"] = package_digest(manifest)
    write_json(out / PR.RUNTIME_MANIFEST, manifest)
    problems = PR.channel_problems(out, manifest)
    if problems:
        raise BuildError("canal du paquet non respecté:\n  " + "\n  ".join(problems))
    report = probe(out, channel)
    log(f"sonde OK : Python {report['python']}, Node {report['node']}, aucun outil du PATH, réveil {report['wake']}")
    log(f"package_sha256 {manifest['package_sha256']}")
    print(json.dumps({"out": str(out), "package_sha256": manifest["package_sha256"], "probe": report}, ensure_ascii=False))
    return 0


def unexpected_entries(out: Path, manifest: dict) -> list[str]:
    """Fichiers ou dossiers hors des arbres suivis (`private_runtime.unexpected_entries`)."""

    return PR.unexpected_entries(out, manifest)


def command_verify(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    manifest, problems = PR.verify_package(PR.PackageLayout(out))
    if manifest is None:
        raise BuildError(f"paquet altéré : {problems[0] if problems else PR.RUNTIME_MANIFEST + ' absent'}")
    if problems:
        raise BuildError("paquet altéré:" + "".join(f"\n  {problem}" for problem in problems))
    channel = PR.package_channel(manifest)
    log(f"paquet intact : {manifest['package_sha256']} (canal {channel})")
    warning = (manifest.get("product") or {}).get("channel_warning")
    if warning:
        log(f"AVERTISSEMENT ({channel}) : {warning}")
    return 0


# ---------------------------------------------------------------------- installeur (Slice 07, HV-PACKAGE-10)

STUB_SOURCE = HERE / "setup_stub.cs"
SETUP_MAGIC = b"JVSETUP1"
#: Date fixe des membres du zip : le même paquet donne le même zip (l'exécutable de l'amorce, lui, porte l'heure du
#: compilateur C# 4.x, qui n'a pas de mode déterministe).
ZIP_EPOCH = (2026, 1, 1, 0, 0, 0)
CSC_REFERENCES = ("System.dll", "System.Core.dll", "System.Drawing.dll", "System.Windows.Forms.dll",
                  "System.IO.Compression.dll", "System.Web.Extensions.dll")


def find_csc() -> Path:
    """Compilateur C# du .NET Framework 4.x livré avec Windows (dossier `Microsoft.NET` de `%WINDIR%`, v4.0.30319)."""

    root = Path(os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT") or r"C:\Windows") / "Microsoft.NET"
    for flavour in ("Framework64", "Framework"):
        candidate = root / flavour / "v4.0.30319" / "csc.exe"
        if candidate.is_file():
            return candidate
    raise BuildError("compilateur C# du .NET Framework 4.x introuvable (csc.exe du dossier Microsoft.NET de %WINDIR%) : "
                     "l'amorce de l'installeur ne peut pas être compilée sur ce poste (voir HV-PACKAGE-10)")


def compile_stub(out_exe: Path) -> None:
    csc = find_csc()
    argv = [str(csc), "/nologo", "/target:winexe", "/optimize+", "/codepage:65001", f"/out:{out_exe}",
            *(f"/reference:{name}" for name in CSC_REFERENCES), str(STUB_SOURCE)]
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not out_exe.is_file():
        output = (result.stdout + result.stderr)[-3000:]
        raise BuildError(f"compilation de l'amorce en échec (code {result.returncode}) :\n{output}")


def zip_package(package: Path, out_zip: Path) -> int:
    """Zip déterministe du paquet (ordre des chemins, date fixe, deflate) ; rend le nombre de fichiers."""

    count = 0
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for relative, path in PR.iter_tree(package):
            info = zipfile.ZipInfo(relative, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as handle, bundle.open(info, "w") as target:
                shutil.copyfileobj(handle, target, 1 << 20)
            count += 1
    return count


def command_installer(args: argparse.Namespace) -> int:
    package = Path(args.package).resolve()
    out = Path(args.out).resolve()
    if out.exists():
        raise BuildError(f"{out} existe déjà : choisissez un nouveau nom")
    if out == REPO or REPO in out.parents:
        raise BuildError("l'installeur ne s'écrit pas dans le dépôt")
    manifest, problems = PR.verify_package(PR.PackageLayout(package))
    if manifest is None or problems:
        raise BuildError("paquet altéré, installeur refusé:" + "".join(f"\n  {problem}" for problem in problems))
    with tempfile.TemporaryDirectory(prefix="jarvis-setup-build-") as work:
        stub = Path(work) / "stub.exe"
        payload = Path(work) / "package.zip"
        compile_stub(stub)
        log(f"amorce compilée ({stub.stat().st_size} octets)")
        files = zip_package(package, payload)
        log(f"paquet zippé : {files} fichiers, {payload.stat().st_size} octets")
        offset = stub.stat().st_size
        length = payload.stat().st_size
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as target:
            for part in (stub, payload):
                with open(part, "rb") as handle:
                    shutil.copyfileobj(handle, target, 1 << 20)
            target.write(SETUP_MAGIC + offset.to_bytes(8, "little") + length.to_bytes(8, "little"))
        payload_sha = PR.file_sha256(payload)
    report = {"out": str(out), "package_sha256": manifest["package_sha256"], "payload_sha256": payload_sha,
              "installer_sha256": PR.file_sha256(out), "files": files, "bytes": out.stat().st_size, "signed": False}
    log(f"installeur : {out} ({report['bytes']} octets, non signé : HV-PACKAGE-10)")
    print(json.dumps(report, ensure_ascii=False))
    return 0


def read_trailer(installer: Path) -> tuple[int, int]:
    """(position, longueur) du zip accolé à l'amorce ; `BuildError` sans remorque valide."""

    with open(installer, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size < 24:
            raise BuildError("installeur trop court")
        handle.seek(-24, os.SEEK_END)
        trailer = handle.read(24)
    if trailer[:8] != SETUP_MAGIC:
        raise BuildError("remorque de l'installeur absente")
    offset, length = int.from_bytes(trailer[8:16], "little"), int.from_bytes(trailer[16:24], "little")
    if offset < 0 or length <= 0 or offset + length > size - 24:
        raise BuildError("remorque de l'installeur incohérente")
    return offset, length


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lock = sub.add_parser("lock")
    lock.add_argument("--cache", default=str(default_cache()))
    lock.add_argument("--constraints")
    lock.add_argument("--channel", choices=CHANNELS, default=DEFAULT_CHANNEL)
    build = sub.add_parser("build")
    build.add_argument("--out", required=True)
    build.add_argument("--channel", choices=CHANNELS, default=DEFAULT_CHANNEL,
                       help="production (défaut, sans openWakeWord) ou internal (HD-V12-01 : mot de réveil livré)")
    build.add_argument("--cache", default=str(default_cache()))
    build.add_argument("--rev", default="HEAD")
    verify = sub.add_parser("verify")
    verify.add_argument("out")
    installer = sub.add_parser("installer")
    installer.add_argument("--package", required=True)
    installer.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # console Windows en cp1252 quand la sortie est redirigée
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return {"lock": command_lock, "build": command_build, "verify": command_verify,
                "installer": command_installer}[args.command](args)
    except (BuildError, subprocess.CalledProcessError) as exc:
        print(f"[build] ÉCHEC : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
