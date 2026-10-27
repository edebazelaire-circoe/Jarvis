"""Paquet de support du produit (Slice 10, `docs/release.md` › *Support bundle*).

    python -B -m jarvis support-bundle [--out DIR]

Rassemble, dans un zip borné, ce qu'il faut pour diagnostiquer une installation SANS rien emporter de la vie de
l'utilisateur :

- `bundle.json` : version, édition, mode d'installation, intégrité du paquet (`verify_package`), état du lanceur et
  du premier lancement, état des capacités locales, versions de schéma des bases (lecture seule, jamais une ligne),
  nombre et taille des fichiers par dossier de données (jamais un nom), place libre, système ;
- `logs/errors.jsonl` : la fin du journal d'erreurs, chaque ligne masquée (`DiagnosticRedactor.structured`) ;
- `logs/trace-events.jsonl` : la fin de la trace réduite à `ts`, `kind`, `level` (ni message ni données : la trace peut
  porter des paroles d'une salle, `docs/presentation-audio-capture.md`) ;
- `logs/<rôle>.log` : la fin des journaux du lanceur et de ses enfants, chaque ligne masquée et bornée ;
- `config-keys.json` : les NOMS des variables de `config\\.env` (jamais leurs valeurs).

Jamais : bases, historique, mémoire, `CONTEXT_GLOBAL`, présentations, artefacts, réglages du Control Center, jetons.
Le zip est écrit sous `runtime\\support\\` (ou `--out`) ; son chemin est rendu à l'appelant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
from typing import Any
import zipfile

from jarvis.domain.diagnostic_redaction import DiagnosticRedactor
from jarvis.runtime.journal import read_jsonl_tail, tail_lines

SCHEMA = "jarvis.support-bundle"
SUPPORT_DIR = "support"
#: Bornes : un paquet de support reste petit et ne grossit pas avec l'âge des journaux.
ERROR_LINES = 400
TRACE_LINES = 600
LOG_LINES = 300
MAX_LINE_CHARS = 2000
MAX_FILE_BYTES = 1024 * 1024
LOG_ROLES = ("launcher", "core", "ui", "voice")
#: Bases dont seule la version de schéma est lue.
DATABASES = ("state/jarvis.sqlite3", "state/scene.sqlite3")
#: Dossiers de données comptés (nombre, octets), jamais listés.
DATA_FOLDERS = ("state", "CONTEXT_GLOBAL", "boards", "sessions", "artifacts", "presentations", "presentation_templates",
                "memory", "history", "prefabs", "local_capabilities", "backups")
#: Fichiers d'état du runtime recopiés, masqués.
RUNTIME_STATE_FILES = ("launcher.json", "product-onboarding.json")


class SupportBundleError(RuntimeError):
    """Paquet non écrit : la cause est dite, rien de partiel n'est laissé."""


@dataclass
class BundleSources:
    data_root: Path
    runtime_root: Path
    config_dir: Path | None
    environ: Mapping[str, str]
    installation: Mapping[str, Any] = field(default_factory=dict)
    package: Callable[[], Mapping[str, Any]] | None = None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _bounded(text: str) -> str:
    return text if len(text) <= MAX_LINE_CHARS else text[:MAX_LINE_CHARS] + f"… (+{len(text) - MAX_LINE_CHARS})"


def folder_summary(root: Path) -> dict[str, dict[str, int] | None]:
    summary: dict[str, dict[str, int] | None] = {}
    for name in DATA_FOLDERS:
        folder = root / name
        if not folder.is_dir():
            summary[name] = None
            continue
        files = size = 0
        for path in folder.rglob("*"):
            try:
                if path.is_file():
                    files += 1
                    size += path.stat().st_size
            except OSError:
                continue  # intentional: a file vanishing during the count changes a statistic, nothing else
        summary[name] = {"files": files, "bytes": size}
    return summary


def schema_versions(root: Path) -> dict[str, Any]:
    versions: dict[str, Any] = {}
    for relative in DATABASES:
        path = root / relative
        if not path.is_file():
            versions[relative] = None
            continue
        # Sans `-wal`/`-shm` (JARVIS arrêté), `immutable=1` : une ouverture en lecture seule d'une base WAL créerait
        # sinon un `-shm` à côté d'elle. Avec eux (JARVIS ouvert), `mode=ro` : rien de nouveau n'est créé.
        live = any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm"))
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro{'' if live else '&immutable=1'}", uri=True, timeout=2)
            try:
                rows = conn.execute("SELECT version FROM schema_version").fetchall()
            finally:
                conn.close()
            versions[relative] = {"versions": [row[0] for row in rows],
                                  "backups": sorted(p.name for p in path.parent.glob(path.name + ".v*.bak"))}
        except sqlite3.Error as exc:
            versions[relative] = {"error": f"{type(exc).__name__}: {exc}"}
    return versions


def env_keys(config_dir: Path | None) -> list[str]:
    if config_dir is None:
        return []
    try:
        text = (config_dir / ".env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    keys = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            keys.append(stripped.split("=", 1)[0].removeprefix("export ").strip())
    return sorted(set(keys))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return {"unreadable": f"{type(exc).__name__}"}


def collect(sources: BundleSources) -> dict[str, bytes]:
    """Les fichiers du paquet (nom → octets), déjà masqués et bornés."""

    redactor = DiagnosticRedactor(sources.environ)
    try:
        package = dict(sources.package()) if sources.package else None
    except Exception as exc:  # noqa: BLE001 - argued: an unreadable package is itself the diagnostic, written in the bundle
        package = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        free = shutil.disk_usage(sources.data_root if sources.data_root.exists() else sources.data_root.anchor).free
    except OSError:
        free = None
    capabilities = {}
    for state in sorted((sources.data_root / "local_capabilities").glob("*/state.json")):
        capabilities[state.parent.name] = _read_json(state)
    summary = {
        "schema": SCHEMA, "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": {"os": platform.platform(), "python": sys.version.split()[0], "machine": platform.machine()},
        "installation": dict(sources.installation),
        "package": package,
        "launcher": {name: _read_json(sources.runtime_root / name) for name in RUNTIME_STATE_FILES},
        "local_capabilities": capabilities,
        "databases": schema_versions(sources.data_root),
        "data_folders": folder_summary(sources.data_root),
        "disk_free_bytes": free,
        "limits": {"error_lines": ERROR_LINES, "trace_lines": TRACE_LINES, "log_lines": LOG_LINES,
                   "max_line_chars": MAX_LINE_CHARS},
        "excluded": ["databases", "history", "memory", "CONTEXT_GLOBAL", "presentations", "artifacts",
                     "control-center-settings.json", "core.token", "trace messages and data", ".env values"],
    }
    files: dict[str, bytes] = {"bundle.json": _json_bytes(redactor.structured(summary))}
    errors = [redactor.structured({key: row.get(key) for key in ("ts", "kind", "level", "message", "data")})
              for row in read_jsonl_tail(sources.runtime_root / "errors.jsonl", limit=ERROR_LINES)]
    files["logs/errors.jsonl"] = _lines_bytes(json.dumps(row, ensure_ascii=False, default=str) for row in errors)
    events = [{key: row.get(key) for key in ("ts", "kind", "level")}
              for row in read_jsonl_tail(sources.runtime_root / "trace.jsonl", limit=TRACE_LINES)]
    files["logs/trace-events.jsonl"] = _lines_bytes(json.dumps(row, ensure_ascii=False) for row in events)
    for role in LOG_ROLES:
        path = sources.runtime_root / "logs" / f"{role}.log"
        if path.is_file():
            try:
                lines = tail_lines(path, LOG_LINES)
            except OSError as exc:
                lines = [f"<{role}.log illisible : {type(exc).__name__}>"]
            files[f"logs/{role}.log"] = _lines_bytes(redactor.text(line) for line in lines)
    files["config-keys.json"] = _json_bytes({"config_env_keys": env_keys(sources.config_dir)})
    return {name: _cap(content) for name, content in files.items()}


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _lines_bytes(lines) -> bytes:
    return "".join(_bounded(line) + "\n" for line in lines).encode("utf-8")


def _cap(content: bytes) -> bytes:
    if len(content) <= MAX_FILE_BYTES:
        return content
    return content[-MAX_FILE_BYTES:]  # the end of a log is the part that explains the failure


def write_bundle(sources: BundleSources, out_dir: Path | None = None) -> Path:
    """Écrit `jarvis-support-<UTC>.zip` (temporaire puis renommé : jamais un zip à moitié écrit) et rend son chemin."""

    target_dir = Path(out_dir) if out_dir is not None else sources.runtime_root / SUPPORT_DIR
    try:
        files = collect(sources)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"jarvis-support-{utc_stamp()}.zip"
        index = 2
        while target.exists():
            target = target_dir / f"jarvis-support-{utc_stamp()}-{index}.zip"
            index += 1
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, content in sorted(files.items()):
                bundle.writestr(name, content)
        temp = target.with_name(target.name + ".tmp")
        temp.write_bytes(buffer.getvalue())
        os.replace(temp, target)
    except OSError as exc:
        raise SupportBundleError(f"Paquet de support non écrit dans {target_dir} : {type(exc).__name__}: {exc}") from exc
    return target


def sources_from_environment(environ: Mapping[str, str] | None = None) -> BundleSources:
    """Les racines de CE processus, par les résolveurs canoniques (`jarvis/data_root.py`, `jarvis/installation.py`)."""

    from jarvis import private_runtime as PR
    from jarvis.data_root import resolve_data_root, resolve_runtime_root
    from jarvis.installation import detect_installation

    env = os.environ if environ is None else environ
    installation = detect_installation(env)
    layout = PR.package_layout()

    def package() -> Mapping[str, Any]:
        if layout is None:
            return {"mode": "development"}
        manifest, problems = PR.verify_package(layout)
        product = (manifest or {}).get("product") or {}
        return {"version": product.get("version"), "edition": product.get("edition"),
                "source_revision": product.get("source_revision"), "package_sha256": (manifest or {}).get("package_sha256"),
                "intact": manifest is not None and not problems, "problems": problems[:20]}

    return BundleSources(data_root=resolve_data_root(env), runtime_root=resolve_runtime_root(env),
                         config_dir=installation.home.config if installation.home else None, environ=env,
                         installation={"mode": installation.mode.value}, package=package)


def run_cli(args: Any) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        path = write_bundle(sources_from_environment(), Path(args.out) if getattr(args, "out", None) else None)
    except SupportBundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Paquet de support écrit : {path}")
    print("Il ne contient ni conversations, ni présentations, ni clés ; vous pouvez l'ouvrir pour le relire avant de l'envoyer.")
    return 0
