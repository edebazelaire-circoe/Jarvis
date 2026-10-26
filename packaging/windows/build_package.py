#!/usr/bin/env python3
"""Paquet Windows de JARVIS Presentation Edition (docs/windows-packaging.md, Slice 06).

Trois commandes, aucune ne touche au JARVIS vivant ni à `%LOCALAPPDATA%\\CIRCOE\\Jarvis` :

    python packaging/windows/build_package.py lock  [--cache DIR] [--constraints FILE]
        Résout `requirements.in` en roues Windows cp314 et réécrit `requirements.lock`
        (chaque dépendance transitive, version exacte, SHA-256). Maintenance seulement (réseau).

    python packaging/windows/build_package.py build --out DIR [--cache DIR] [--rev HEAD]
        Construit le dossier d'installation : Python embarquable et Node épinglés (SHA-256
        vérifié), roues installées depuis le verrou (`--require-hashes`, roues seulement),
        code `jarvis/` tiré de git (`git archive`, rien de non versionné), marqueur produit,
        bytecode précompilé (`unchecked-hash` : rien n'est écrit dans le dossier du programme
        à l'exécution), licences, `third-party-manifest.json` et `runtime-manifest.json`.
        Termine par une sonde du paquet lancé avec un PATH réduit à Windows.

    python packaging/windows/build_package.py verify DIR
        Recalcule les empreintes des arbres et les compare au manifeste.

Le cache des téléchargements vit hors du dépôt (`%LOCALAPPDATA%\\Temp\\jarvis-build-cache` par défaut).
Lancer avec le Python 3.14 de développement (`.venv`) : pip y est requis, et le bytecode est produit par le
Python du paquet lui-même.
"""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import io
import json
import os
from pathlib import Path
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
from jarvis.installation import PRODUCT_MARKER, marker_payload  # noqa: E402

RUNTIMES_FILE = HERE / "runtimes.json"
REQUIREMENTS_IN = HERE / "requirements.in"
LOCK_FILE = HERE / "requirements.lock"
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


def render_lock(rows: list[dict]) -> str:
    header = ("# Verrou de l'édition presentation (docs/windows-packaging.md) : NE PAS ÉDITER À LA MAIN.\n"
              "# Généré par `python packaging/windows/build_package.py lock` depuis requirements.in.\n"
              "# Une roue Windows cp314 par dépendance, transitives comprises ; pip l'installe avec --require-hashes.\n")
    body = "".join(f"{row['name']}=={row['version']} \\\n    --hash=sha256:{row['sha256']}\n"
                   for row in sorted(rows, key=lambda r: r["name"]))
    return header + body


def command_lock(args: argparse.Namespace) -> int:
    runtimes = load_json(RUNTIMES_FILE)
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lock-", dir=str(args.cache)) as tmp:
        target = Path(tmp)
        argv = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "-r", str(REQUIREMENTS_IN),
                "-d", str(target), *pip_target_args(runtimes)]
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
    LOCK_FILE.write_text(render_lock(rows), encoding="utf-8")
    log(f"{len(rows)} roues verrouillées dans {LOCK_FILE.name}")
    return 0


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


def extract_zip(archive: Path, target: Path, *, strip_components: int = 0) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            parts = Path(info.filename).parts[strip_components:]
            if not parts or info.is_dir():
                continue
            if any(part in ("..", "") or ":" in part for part in parts):
                raise BuildError(f"{archive.name}: chemin refusé {info.filename}")
            destination = target.joinpath(*parts)
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


def install_wheels(out: Path, runtimes: dict, cache: Path) -> Path:
    wheels = cache / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    common = ["--disable-pip-version-check", "--require-hashes", "--no-deps", "-r", str(LOCK_FILE), *pip_target_args(runtimes)]
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
        lines = record.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [line for line in lines if not line.startswith(("../../bin/", "bin/", "../../Scripts/", "Scripts/"))]
        if kept != lines:
            record.write_text("".join(kept), encoding="utf-8", newline="")


def install_pywin32_dlls(site: Path) -> None:
    """`pywintypes3xx.dll`/`pythoncom3xx.dll` à côté de `python.exe` (dossier de l'application dans l'ordre de recherche
    des DLL) : ce que fait `pywin32_bootstrap` via `pywin32.pth`, que le paquet ne traite pas (pas de `site`)."""

    for dll in sorted((site / "pywin32_system32").glob("*.dll")):
        shutil.copyfile(dll, site.parents[1] / dll.name)


def build_node(out: Path, runtimes: dict, cache: Path) -> Path:
    entry = runtimes["runtimes"]["node"]
    archive = fetch_verified(entry, cache / "runtimes")
    target = out / PR.RUNTIME_DIR / PR.NODE_DIR
    extract_zip(archive, target, strip_components=int(entry.get("strip_components", 0)))
    if not (target / "node.exe").is_file() or not (target / "node_modules" / "npm" / "bin" / "npm-cli.js").is_file():
        raise BuildError("archive Node sans node.exe ou npm-cli.js")
    return target


def git_revision(rev: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", rev], check=True, capture_output=True, text=True).stdout.strip()


def build_app(out: Path, revision: str) -> Path:
    """`jarvis/` tel que versionné à `revision` (aucun fichier non suivi, aucun `__pycache__`) + marqueur produit."""

    app = out / PR.APP_DIR
    app.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", revision, "jarvis"], check=True,
                             capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            if any(part in ("..", "") for part in parts) or Path(member.name).is_absolute():
                raise BuildError(f"git archive: chemin refusé {member.name}")
            destination = app.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.extractfile(member).read())
    (app / PRODUCT_MARKER).write_text(json.dumps(marker_payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return app


def precompile(out: Path, python_exe: Path, roots: list[Path]) -> None:
    """Bytecode `unchecked-hash` par le Python du paquet : jamais réécrit à l'exécution, identique d'un build à l'autre.

    `-s <out>` retire le dossier de build des noms de fichiers enregistrés (traces lisibles, build reproductible).
    Un fichier tiers non compilable (exemple Python 2 livré dans une roue) est signalé, pas fatal.
    """

    result = subprocess.run([str(python_exe), "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
                             "-s", str(out), *[str(root) for root in roots]], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
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


def collect_licenses(out: Path, site: Path, runtimes: dict) -> dict[str, list[str]]:
    """Copie les textes de licence sous `licenses/<composant>/` ; rend les chemins relatifs par composant."""

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
    return copied


def third_party_manifest(site: Path, lock_rows: list[dict], policy: dict, runtimes: dict,
                         licenses: dict[str, list[str]]) -> dict:
    """Une ligne par composant livré (runtime, roue), plus les exclus et les dépendances externes ; refuse un trou."""

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
                           "license_files": licenses.get(f"python-packages/{name}", [])})
    return {"schema": "jarvis.third-party-manifest", "schema_version": 1, "edition": EDITION,
            "components": components, "excluded": policy["excluded"], "external": policy["external"],
            "provisioned": policy["provisioned"]}


def node_npm_version(node_dir: Path) -> str:
    return load_json(node_dir / "node_modules" / "npm" / "package.json")["version"]


def runtime_manifest(out: Path, runtimes: dict, revision: str, policy: dict) -> dict:
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
    return {"schema": PR.RUNTIME_MANIFEST_SCHEMA, "schema_version": PR.RUNTIME_MANIFEST_VERSION,
            "product": {"name": PRODUCT_NAME, "edition": EDITION, "version": project[1] if project else "unknown",
                        "source_revision": revision},
            "app": {"root": PR.APP_DIR, "tree_sha256": app_tree, "files": app_files},
            "licenses": {"root": LICENSES_DIR, "tree_sha256": lic_tree, "files": lic_files},
            "third_party_manifest_sha256": PR.file_sha256(out / THIRD_PARTY_MANIFEST),
            "runtimes": entries,
            "excluded": [{"id": item["id"], "kind": item["kind"], "reason": item["reason"]} for item in policy["excluded"]],
            "external": [{"id": item["id"], "resolution": item["resolution"]} for item in policy["external"]],
            "provisioned": [{"id": item["id"], "resolution": item["resolution"]} for item in policy["provisioned"]]}


def package_digest(manifest: dict) -> str:
    """Empreinte du paquet entier : celle du manifeste canonique (qui porte les empreintes de chaque arbre)."""

    return hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def probe_env(out: Path) -> dict[str, str]:
    """Environnement d'un poste sans outils de développement : PATH = Windows seulement, aucune variable Python/Node."""

    env = {key: os.environ[key] for key in PROBE_ENV_KEYS if key in os.environ}
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env["PATH"] = os.pathsep.join([str(Path(root) / "System32"), root, str(Path(root) / "System32" / "Wbem")])
    return env


PROBE_SCRIPT = r"""
import json, shutil, subprocess, sys
import aiohttp, httpx, numpy, sounddevice, mcp, googleapiclient, google_auth_oauthlib, livekit.rtc, pynput, tzdata
import jarvis, jarvis.app
from jarvis import private_runtime as pr
from jarvis.installation import detect_installation
layout = pr.package_layout()
node = pr.which("node")
version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
missing = {name: shutil.which(name) for name in ("python", "node", "npm", "ffmpeg", "git")}
import importlib.util
excluded = {name: importlib.util.find_spec(name) is not None for name in ("onnxruntime", "openwakeword", "imageio_ffmpeg", "pvporcupine", "sherpa_onnx")}
import win32api, pywintypes, mcp.client.stdio
outside = [p for p in sys.path if not p.lower().startswith(str(layout.install_root).lower())]
print(json.dumps({"python": sys.version.split()[0], "executable_in_package": sys.executable.lower().startswith(str(layout.install_root).lower()),
                  "installed": detect_installation().installed, "node": version, "node_private": node.lower().startswith(str(layout.node_dir).lower()),
                  "ffmpeg": pr.which("ffmpeg"), "no_site": sys.flags.no_site == 1, "sys_path_outside_package": outside,
                  "excluded_importable": excluded, "py_launcher_on_path": shutil.which("py"),
                  "path_tools": missing, "diagnostics": pr.diagnostics()}))
"""


def probe(out: Path) -> dict:
    python = out / PR.RUNTIME_DIR / PR.PYTHON_DIR / "python.exe"
    env = probe_env(out) | {"LOCALAPPDATA": str(out / "_probe-localappdata")}
    result = subprocess.run([str(python), "-c", PROBE_SCRIPT], capture_output=True, text=True, env=env, cwd=str(out),
                            encoding="utf-8", errors="replace", timeout=300)
    shutil.rmtree(out / "_probe-localappdata", ignore_errors=True)
    if result.returncode != 0:
        raise BuildError("sonde du paquet en échec:\n" + (result.stdout + result.stderr)[-3000:])
    report = json.loads(result.stdout.strip().splitlines()[-1])
    expected = (report["installed"] and report["executable_in_package"] and report["node_private"]
                and report["no_site"] and not report["sys_path_outside_package"]
                and not any(report["excluded_importable"].values()) and report["ffmpeg"] is None
                and not any(report["path_tools"].values()) and report["diagnostics"].get("status") == "ok")
    if not expected:
        raise BuildError(f"sonde du paquet inattendue: {json.dumps(report)}")
    return report


def command_build(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    cache = Path(args.cache).resolve()
    if out.exists() and any(out.iterdir()):
        raise BuildError(f"{out} n'est pas vide : un build part toujours d'un dossier vide")
    if out == REPO or REPO in out.parents:
        raise BuildError("le dossier de sortie ne peut pas être dans le dépôt")
    runtimes, policy = load_json(RUNTIMES_FILE), load_json(POLICY_FILE)
    lock_rows = parse_lock(LOCK_FILE.read_text(encoding="utf-8"))
    revision = git_revision(args.rev)
    out.mkdir(parents=True, exist_ok=True)
    log(f"révision {revision} → {out}")
    python_dir = build_python(out, runtimes, cache)
    site = install_wheels(out, runtimes, cache)
    build_node(out, runtimes, cache)
    app = build_app(out, revision)
    precompile(out, python_dir / "python.exe", [app, site])
    licenses = collect_licenses(out, site, runtimes)
    write_json(out / THIRD_PARTY_MANIFEST, third_party_manifest(site, lock_rows, policy, runtimes, licenses))
    manifest = runtime_manifest(out, runtimes, revision, policy)
    manifest["package_sha256"] = package_digest(manifest)
    write_json(out / PR.RUNTIME_MANIFEST, manifest)
    report = probe(out)
    log(f"sonde OK : Python {report['python']}, Node {report['node']}, aucun outil du PATH")
    log(f"package_sha256 {manifest['package_sha256']}")
    print(json.dumps({"out": str(out), "package_sha256": manifest["package_sha256"], "probe": report}, ensure_ascii=False))
    return 0


def command_verify(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    layout = PR.PackageLayout(out)
    manifest = layout.manifest()
    if manifest is None:
        raise BuildError(f"{PR.RUNTIME_MANIFEST} absent")
    problems = [f"{p.component}: {p.code.value} ({p.detail})" for p in PR.verify_runtimes(layout)]
    for key, root in (("app", PR.APP_DIR), ("licenses", LICENSES_DIR)):
        actual, _count = PR.tree_sha256(out / root)
        if actual != manifest[key]["tree_sha256"]:
            problems.append(f"{key}: arbre modifié")
    if PR.file_sha256(out / THIRD_PARTY_MANIFEST) != manifest["third_party_manifest_sha256"]:
        problems.append("third-party-manifest.json modifié")
    body = {key: value for key, value in manifest.items() if key != "package_sha256"}
    if package_digest(body) != manifest.get("package_sha256"):
        problems.append("package_sha256 ne correspond pas au manifeste")
    if problems:
        raise BuildError("paquet altéré:\n  " + "\n  ".join(problems))
    log(f"paquet intact : {manifest['package_sha256']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lock = sub.add_parser("lock")
    lock.add_argument("--cache", default=str(default_cache()))
    lock.add_argument("--constraints")
    build = sub.add_parser("build")
    build.add_argument("--out", required=True)
    build.add_argument("--cache", default=str(default_cache()))
    build.add_argument("--rev", default="HEAD")
    verify = sub.add_parser("verify")
    verify.add_argument("out")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # console Windows en cp1252 quand la sortie est redirigée
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return {"lock": command_lock, "build": command_build, "verify": command_verify}[args.command](args)
    except (BuildError, subprocess.CalledProcessError) as exc:
        print(f"[build] ÉCHEC : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
