"""Paquet de support du produit (Slice 10, `docs/release.md` › *Support bundle*).

    python -B -m jarvis support-bundle [--out DIR]

Rassemble, dans un zip borné, ce qu'il faut pour diagnostiquer une installation SANS rien emporter de la vie de
l'utilisateur :

- `bundle.json` : version, édition, mode d'installation, intégrité du paquet (`verify_package`), état du lanceur et
  du premier lancement, état des capacités locales, versions de schéma des bases (lecture seule, jamais une ligne),
  nombre et taille des fichiers par dossier de données (jamais un nom), place libre, système ;
- `logs/errors.jsonl` : la fin du journal d'erreurs, chaque ligne masquée (`DiagnosticRedactor.structured`), `message`
  borné, `data` filtré par LISTE BLANCHE (nombres, booléens, identifiants sans espace, texte des seules clés de
  diagnostic `DIAGNOSTIC_KEYS`) : un titre, une requête ou une phrase d'utilisateur n'y entre pas (QA S10 m3) ;
- `logs/trace-events.jsonl` : la fin de la trace réduite à `ts`, `kind`, `level` (ni message ni données : la trace peut
  porter des paroles d'une salle, `docs/presentation-audio-capture.md`) ;
- `logs/<rôle>.log` : la fin des journaux du lanceur et de ses enfants, chaque ligne masquée et bornée ;
- `config-keys.json` : les NOMS des variables de `config\\.env` (jamais leurs valeurs).

Jamais : bases, historique, mémoire, `CONTEXT_GLOBAL`, présentations, artefacts, réglages du Control Center, jetons.
Les valeurs de `config\\.env` (lues par le parseur canonique `jarvis.environment.parse_environment_lines`), le jeton
local `core.token`, les clés des réglages locaux (scellées DPAPI dans le produit, `local_secrets.py`) et les
identifiants du coffre MCP (`mcp_credentials`) sont donnés au masqueur comme secrets CONNUS (QA S10 M2, X1, x6) : un
jeton opaque, sans forme reconnaissable, qui apparaît seul dans un journal est masqué quand même. Les valeurs
descellées ne vivent qu'en mémoire, le temps du paquet ; `bundle.json` ne dit que des COMPTES (`secret_sources`), et
un descellement impossible (autre compte Windows, coffre indisponible) dégrade le masquage sans empêcher le paquet.
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
import re
import shutil
import sqlite3
import sys
from typing import Any
import zipfile

from jarvis.domain.diagnostic_redaction import DiagnosticRedactor
from jarvis.domain.mcp_plugins import REDACTED
from jarvis.runtime.journal import read_jsonl_tail, tail_lines

SCHEMA = "jarvis.support-bundle"
SUPPORT_DIR = "support"
#: Bornes : un paquet de support reste petit et ne grossit pas avec l'âge des journaux.
ERROR_LINES = 400
TRACE_LINES = 600
LOG_LINES = 300
MAX_LINE_CHARS = 2000
#: Une ligne est coupée à cette longueur AVANT d'être masquée (le masquage reste linéaire ; la sortie est de toute façon
#: bornée à `MAX_LINE_CHARS`).
MAX_INPUT_CHARS = 8 * MAX_LINE_CHARS
MESSAGE_CHARS = 500
DATA_TEXT_CHARS = 300
DATA_LIST_ITEMS = 50
#: Clés de `data` (journal d'erreurs) dont la valeur texte est un diagnostic : gardée, masquée et bornée. Toute autre
#: chaîne n'est gardée que si elle a la forme d'un identifiant (aucun espace, 120 caractères au plus).
DIAGNOSTIC_KEYS = frozenset({"error", "error_type", "exception", "code", "reason", "status", "phase", "kind", "type",
                             "detail", "cause", "stage", "operation", "op", "role", "level", "component", "module",
                             "step", "state", "mode", "method", "exit_code", "signal", "errno"})
_IDENTIFIER = re.compile(r"\S{1,120}")
#: Mots (séparés par `_`, `-` ou `.`) d'un nom de variable dont la valeur est un secret quelle que soit sa forme :
#: `INFOMANIAK_TOKEN`, `API_KEY`, `DB_PASSWORD`… Mot entier, ou fin de mot pour les formes collées (`APIKEY`,
#: `ACCESSTOKEN`) ; jamais un morceau (`KEYBOARD_LAYOUT`, `BYPASS_HOST` ne sont pas des secrets, QA S10 x4).
SECRET_NAME_WORDS = frozenset({"TOKEN", "KEY", "SECRET", "PASSWORD", "PASSWD", "PWD", "PASS", "PASSPHRASE",
                               "CREDENTIAL", "CREDENTIALS", "COOKIE", "SIGNATURE", "AUTHORIZATION", "BEARER"})
SECRET_NAME_ENDINGS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "CREDENTIAL", "CREDENTIALS")
#: Mots qui font d'un nom « sensible » un réglage descriptif (`TOKEN_TYPE`, `KEY_FILE`, `MAX_TOKEN`, `TOKEN_EXPIRES_AT`).
DESCRIPTIVE_NAME_WORDS = frozenset({"TYPE", "KIND", "EXPIRES", "EXPIRY", "EXPIRATION", "AT", "SCOPE", "SCOPES", "URL",
                                    "URI", "HOST", "PORT", "MODE", "TIMEOUT", "LENGTH", "SIZE", "COUNT", "MAX", "MIN",
                                    "LIMIT", "ENABLED", "FILE", "PATH", "DIR", "NAME", "ID", "CACHE", "LAYOUT", "HINT"})
_TRIVIAL_VALUE = re.compile(r"(?i)(?:true|false|yes|no|on|off|none|null|enabled|disabled|[0-9.:+-]*)")
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
    #: Descelleurs des réglages locaux et du coffre MCP (DPAPI par défaut ; injectés par les tests).
    credentials_sealer: Callable[[], Any] | None = None
    mcp_sealer: Callable[[], Any] | None = None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _bounded(text: str, limit: int = MAX_LINE_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"… (+{len(text) - limit})"


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
        # `mode=ro` sur une base WAL crée un `-shm` s'il manque (QA S10 m9 : `-wal` présent sans `-shm`, après un arrêt
        # brutal ou une copie). On n'ouvre donc en `mode=ro` (qui lit aussi le `-wal`) que si le `-shm` existe déjà
        # (JARVIS ouvert, ou arrêté avec les deux) ; sinon `immutable=1`, qui ne crée rien et ne lit pas le `-wal` :
        # la version lue est alors celle de la base seule, et `wal_not_read` le dit.
        wal = path.with_name(path.name + "-wal").exists()
        shm = path.with_name(path.name + "-shm").exists()
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro{'' if shm else '&immutable=1'}", uri=True, timeout=2)
            try:
                rows = conn.execute("SELECT version FROM schema_version").fetchall()
            finally:
                conn.close()
            versions[relative] = {"versions": [row[0] for row in rows],
                                  "backups": sorted(p.name for p in path.parent.glob(path.name + ".v*.bak"))}
            if wal and not shm:
                versions[relative]["wal_not_read"] = True
        except sqlite3.Error as exc:
            versions[relative] = {"error": f"{type(exc).__name__}: {exc}"}
    return versions


def env_items(config_dir: Path | None) -> tuple[list[tuple[str, str]], int]:
    """((nom, valeur) de chaque variable de `config\\.env`, lignes illisibles) ; jamais écrit tel quel dans le paquet.

    Parseur CANONIQUE (`parse_environment_lines`, le même que le démarrage, QA S10 X1) : BOM retiré (`utf-8-sig`),
    commentaire ` #…` après une valeur sans guillemets et après un guillemet fermant, `export `. Ce parseur refuse le
    fichier entier sur une ligne illisible (au démarrage, c'est voulu) ; ici chaque ligne est lue seule, pour qu'une
    ligne fautive ne fasse perdre ni les autres noms ni les autres secrets : elle est seulement comptée."""

    from jarvis.domain.errors import ConfigurationError
    from jarvis.environment import parse_environment_lines

    if config_dir is None:
        return [], 0
    try:
        lines = (config_dir / ".env").read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return [], 0
    items: list[tuple[str, str]] = []
    unreadable = 0
    for line in lines:
        try:
            items.extend((name, value) for _index, name, value in parse_environment_lines([line]))
        except ConfigurationError:
            unreadable += 1  # intentional: counted in `secret_sources`, never copied (it may hold a value)
    return items, unreadable


def env_keys(config_dir: Path | None) -> list[str]:
    return sorted({name for name, _value in env_items(config_dir)[0]})


def _sensitive_name(name: str) -> bool:
    words = [word for word in re.split(r"[_.\-]+", name.upper()) if word]
    if any(word in DESCRIPTIVE_NAME_WORDS for word in words):
        return False
    return any(word in SECRET_NAME_WORDS or word.endswith(SECRET_NAME_ENDINGS) for word in words)


def _secret_like(name: str, value: str) -> bool:
    if not value or _TRIVIAL_VALUE.fullmatch(value):
        return False
    if _sensitive_name(name):
        return len(value) >= 6
    # Prudence : toute valeur non triviale qui ressemble à un jeton (sans espace ; lettres ET chiffres, ou longue).
    # Un mot seul (`presentation`, `Europe/Paris`) reste lisible : il nomme un réglage, pas un secret.
    if len(value) < 8 or any(char.isspace() for char in value):
        return False
    return (any(char.isdigit() for char in value) and any(char.isalpha() for char in value)) or len(value) >= 20


def _sealer(factory: Callable[[], Any] | None, default: Callable[[], Any]) -> Any:
    try:
        return (factory or default)()
    except Exception:  # noqa: BLE001 - argued: no vault on this machine is reported as `unavailable`, never raised
        return None


def _local_settings_secrets(sources: BundleSources) -> tuple[list[str], dict[str, Any]]:
    """Clés des réglages locaux (`control-center-settings.json`) : en clair (développement) ou scellées (produit)."""

    from jarvis.runtime.credentials import LEGACY_KEYS
    from jarvis.runtime.local_secrets import credential_sealer, unseal_value

    path = sources.runtime_root / "control-center-settings.json"
    if not path.is_file():
        return [], {"present": False}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], {"present": True, "error": type(exc).__name__}
    if not isinstance(settings, dict):
        return [], {"present": True, "error": "not_an_object"}
    found = [str(settings.get(key) or "").strip() for key in LEGACY_KEYS]
    entries = [item for item in settings.get("credentials") or [] if isinstance(item, dict)]
    found += [str(item.get("value") or "").strip() for item in entries]
    sealed = [item["sealed"] for item in entries if "sealed" in item]
    report: dict[str, Any] = {"present": True, "plain": sum(1 for value in found if value), "sealed": len(sealed),
                              "unsealed": 0}
    sealer = _sealer(sources.credentials_sealer, credential_sealer) if sealed else None
    if sealed and (sealer is None or not getattr(sealer, "available", False)):
        report["degraded"] = "vault_unavailable"
    elif sealed:
        for blob in sealed:
            try:
                found.append(unseal_value(blob, sealer).strip())
                report["unsealed"] += 1
            except ValueError:
                continue  # intentional: another Windows account's blob; counted as not unsealed below
        if report["unsealed"] < len(sealed):
            report["degraded"] = "some_sealed_values_unreadable"
    return [value for value in found if len(value) >= 6], report


def _vault_leaves(value: Any, key: str = "") -> list[str]:
    if isinstance(value, Mapping):
        return [leaf for item_key, item in value.items() for leaf in _vault_leaves(item, str(item_key))]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _vault_leaves(item, key)]
    if not isinstance(value, str):
        return []
    found = [value] if _secret_like(key, value) else []
    if any(char.isspace() for char in value):  # `Bearer <jeton>`: each word judged by its shape only (never `Bearer`)
        found += [part for part in value.split() if _secret_like("", part)]
    return found


def _mcp_vault_secrets(sources: BundleSources) -> tuple[list[str], dict[str, Any]]:
    """Identifiants du coffre MCP (`mcp_credentials` de `jarvis.sqlite3`), descellés en mémoire seulement.

    Lecture seule, comme `schema_versions` : `immutable=1` sans `-shm` (rien de créé, le `-wal` non lu)."""

    from jarvis.adapters.dpapi_sealer import default_sealer

    path = sources.data_root / "state" / "jarvis.sqlite3"
    if not path.is_file():
        return [], {"present": False}
    shm = path.with_name(path.name + "-shm").exists()
    report: dict[str, Any] = {"present": True, "rows": 0, "unsealed": 0}
    if path.with_name(path.name + "-wal").exists() and not shm:
        report["wal_not_read"] = True
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro{'' if shm else '&immutable=1'}", uri=True, timeout=2)
        try:
            blobs = [row[0] for row in conn.execute("SELECT blob FROM mcp_credentials")]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        report["error"] = type(exc).__name__  # an older schema without the table, or a damaged base
        return [], report
    report["rows"] = len(blobs)
    if not blobs:
        return [], report
    sealer = _sealer(sources.mcp_sealer, default_sealer)
    if sealer is None or not getattr(sealer, "available", False):
        report["degraded"] = "vault_unavailable"
        return [], report
    found: list[str] = []
    for blob in blobs:
        try:
            body = json.loads(sealer.unseal(bytes(blob)).decode("utf-8"))
        except Exception:  # noqa: BLE001 - argued: SealerError, UnicodeError, ValueError: unreadable, counted below
            continue
        if isinstance(body, dict) and body.get("kind") in ("static", "oauth"):
            found += _vault_leaves(body.get(body["kind"]))
            report["unsealed"] += 1
    if report["unsealed"] < len(blobs):
        report["degraded"] = "some_sealed_values_unreadable"
    return found, report


def secret_sources(sources: BundleSources) -> tuple[list[str], dict[str, Any]]:
    """(secrets connus, comptes par source). Les valeurs ne quittent jamais la mémoire ; seuls les comptes vont dans
    `bundle.json`."""

    items, unreadable = env_items(sources.config_dir)
    secrets = [value for name, value in items if _secret_like(name, value)]
    report: dict[str, Any] = {"env": {"values": len(secrets), "unreadable_lines": unreadable}}
    token_file = Path(sources.environ.get("JARVIS_CORE_TOKEN_FILE") or sources.runtime_root / "core.token")
    try:
        token = token_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        token = ""  # intentional: no token file (JARVIS stopped cleanly) means nothing to mask
    if len(token) >= 6:
        secrets.append(token)
    report["core_token"] = len(token) >= 6
    for name, reader in (("local_settings", _local_settings_secrets), ("mcp_vault", _mcp_vault_secrets)):
        try:
            found, report[name] = reader(sources)
        except Exception as exc:  # noqa: BLE001 - argued: a secret source that fails degrades masking, never the bundle
            found, report[name] = [], {"degraded": f"{type(exc).__name__}"}
        secrets += found
    return secrets, report


def known_secrets(sources: BundleSources) -> list[str]:
    """Valeurs à masquer partout où elles apparaissent (voir `secret_sources`)."""

    return secret_sources(sources)[0]


def allowlisted_data(value: Any, key: str | None = None) -> Any:
    """`data` d'une ligne du journal d'erreurs, DÉJÀ masqué, réduit à ce qui diagnostique (liste blanche, m3)."""

    if isinstance(value, Mapping):
        return {item_key: allowlisted_data(item, item_key if isinstance(item_key, str) else None)
                for item_key, item in value.items()}
    if isinstance(value, list):
        return [allowlisted_data(item, key) for item in value[:DATA_LIST_ITEMS]]
    if isinstance(value, str):
        if key is not None and key.lower() in DIAGNOSTIC_KEYS:
            return value[:DATA_TEXT_CHARS]
        if value == REDACTED or _IDENTIFIER.fullmatch(value) or (value.startswith("<") and value.endswith(">")):
            return value
        return f"<{len(value)} caractères retirés>"
    return value


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return {"unreadable": f"{type(exc).__name__}"}


def collect(sources: BundleSources) -> dict[str, bytes]:
    """Les fichiers du paquet (nom → octets), déjà masqués et bornés."""

    secrets, secret_report = secret_sources(sources)
    redactor = DiagnosticRedactor(sources.environ, known_secrets=secrets)
    del secrets  # the values stay in the redactor only, for the time of this bundle
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
        "secret_sources": secret_report,
        "limits": {"error_lines": ERROR_LINES, "trace_lines": TRACE_LINES, "log_lines": LOG_LINES,
                   "max_line_chars": MAX_LINE_CHARS},
        "excluded": ["databases", "history", "memory", "CONTEXT_GLOBAL", "presentations", "artifacts",
                     "control-center-settings.json", "core.token", "trace messages and data", ".env values"],
    }
    files: dict[str, bytes] = {"bundle.json": _json_bytes(redactor.structured(summary))}
    errors = []
    for row in read_jsonl_tail(sources.runtime_root / "errors.jsonl", limit=ERROR_LINES):
        message = row.get("message")
        kept = redactor.structured({"ts": row.get("ts"), "kind": row.get("kind"), "level": row.get("level"),
                                    "message": str(message)[:MAX_INPUT_CHARS] if message is not None else None,
                                    "data": row.get("data")})
        if isinstance(kept["message"], str):  # bounded AFTER masking: a cut never leaves half a secret readable
            kept["message"] = _bounded(kept["message"], MESSAGE_CHARS)
        kept["data"] = allowlisted_data(kept["data"])
        errors.append(kept)
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
            files[f"logs/{role}.log"] = _lines_bytes(redactor.text(line[:MAX_INPUT_CHARS]) for line in lines)
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
