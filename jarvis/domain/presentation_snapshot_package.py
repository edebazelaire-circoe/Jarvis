"""Paquet autonome et immuable d'une variante de Presentation (Remotion Slice 09). Pur : octets en entrée, octets en sortie.

Contrat : `docs/presentation-artifacts.md` (« Snapshot package ») et `docs/presentation-live-refs.md`. Le paquet est le
`snapshot.zip` du snapshot de la Slice 07 :

    manifest.json                                  provenance, moteur, pins, références résolues, empreintes
    presentation/{presentation,variant,art_direction,score}.json
    prefabs/<prefab_id>/<version>/...              source exacte d'un pin (Remotion : src/**, public/**, source.json ; HTML : bundle.json)
    prefabs/<prefab_id>/<version>/live/<nom><ext>  données du Board copiées au gel

Il ne contient ni chemin de la machine, ni id de session, ni URL : rouvrir un paquet ne consulte ni le Board d'origine, ni le
disque de l'auteur, ni un réseau. `manifest.files` donne le SHA-256 et la taille de **chaque** autre membre ;
`manifest.package_digest` est le SHA-256 du JSON canonique de cette table : `read_package` refuse un paquet dont un octet,
un membre ou l'empreinte diffère. Écriture déterministe (ordre trié, dates fixes, pas de compression) : mêmes octets, même zip.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
import zipfile

from jarvis.domain.presentation_live_refs import LiveRefError, LiveRefErrorCode

PACKAGE_FORMAT = "jarvis.presentation-snapshot/1"
MANIFEST_PATH = "manifest.json"
MAX_PACKAGE_FILES = 600
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_PATH_CHARS = 300
#: `prefabs/<id>/<version>/` (3 segments) + le chemin d'une source Remotion (`MAX_DEPTH` = 8 de remotion-source) + marge.
MAX_PATH_SEGMENTS = 12
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)
_MANIFEST_KEYS = frozenset({"format", "provenance", "frozen_at", "scenes", "prefabs", "live_refs", "runtime", "files",
                            "package_digest"})
_WINDOWS_DEVICES = frozenset({"con", "prn", "aux", "nul"} | {f"{d}{n}" for d in ("com", "lpt") for n in "123456789"})


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _invalid(message: str) -> LiveRefError:
    return LiveRefError(LiveRefErrorCode.PACKAGE_INVALID, message)


def package_path_problem(path: object) -> str | None:
    """Pourquoi un nom de membre est refusé (`None` : accepté). Lexical, identique sur tous les postes."""

    if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS:
        return "path must be a non-empty string of at most 300 characters"
    if path.startswith("/") or "\\" in path or ":" in path or "\x00" in path:
        return "path must be relative, use '/', and hold no ':' or NUL"
    segments = path.split("/")
    if len(segments) > MAX_PATH_SEGMENTS:
        return f"path is deeper than {MAX_PATH_SEGMENTS} segments"
    for segment in segments:
        if segment in ("", ".", "..") or not _SEGMENT.fullmatch(segment) or segment.endswith(".") or segment.endswith(" "):
            return f"segment {segment[:40]!r} is not allowed"
        if segment.split(".", 1)[0].lower() in _WINDOWS_DEVICES:
            return f"segment {segment[:40]!r} is a Windows device name"
    return None


def file_table(files: Mapping[str, bytes]) -> dict[str, dict[str, Any]]:
    return {path: {"sha256": sha256_hex(files[path]), "size": len(files[path])} for path in sorted(files)}


def digest_of(table: Mapping[str, Mapping[str, Any]]) -> str:
    canonical = json.dumps(table, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_hex(canonical.encode("ascii"))


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_package(manifest_core: Mapping[str, Any], files: Mapping[str, bytes]) -> bytes:
    """`manifest_core` = tout le manifeste sauf `files` et `package_digest` (calculés ici). Octets du `snapshot.zip`."""

    if MANIFEST_PATH in files:
        raise _invalid("manifest.json is written by the packager, not supplied")
    for path in files:
        problem = package_path_problem(path)
        if problem is not None:
            raise _invalid(f"{str(path)[:80]}: {problem}")
    if len(files) + 1 > MAX_PACKAGE_FILES:
        raise LiveRefError(LiveRefErrorCode.PACKAGE_TOO_LARGE, f"{len(files)} files, at most {MAX_PACKAGE_FILES - 1}")
    total = sum(len(data) for data in files.values())
    if total > MAX_PACKAGE_BYTES:
        raise LiveRefError(LiveRefErrorCode.PACKAGE_TOO_LARGE, f"{total} bytes, at most {MAX_PACKAGE_BYTES}")
    table = file_table(files)
    manifest = {**manifest_core, "format": PACKAGE_FORMAT, "files": table, "package_digest": digest_of(table)}
    if set(manifest) != _MANIFEST_KEYS:
        raise _invalid(f"manifest keys must be {sorted(_MANIFEST_KEYS)}")
    encoded = canonical_json(manifest)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise LiveRefError(LiveRefErrorCode.PACKAGE_TOO_LARGE, f"manifest is {len(encoded)} bytes, at most {MAX_MANIFEST_BYTES}")
    members = {MANIFEST_PATH: encoded, **files}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for path in sorted(members):
            info = zipfile.ZipInfo(path, _FIXED_DATE)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, members[path])
    built = buffer.getvalue()
    # The bound is on the ZIP itself (headers and manifest included), not only on the member sizes: a snapshot that is
    # complete but that `read_package` / `read_snapshot` would refuse must not be producible.
    if len(built) > MAX_PACKAGE_BYTES:
        raise LiveRefError(LiveRefErrorCode.PACKAGE_TOO_LARGE, f"the package is {len(built)} bytes, at most {MAX_PACKAGE_BYTES}")
    return built


@dataclass(frozen=True, slots=True)
class FrozenPackage:
    """Un paquet relu et **vérifié** : chaque membre correspond à son empreinte, aucun membre n'est hors manifeste."""

    manifest: Mapping[str, Any]
    files: Mapping[str, bytes]

    @property
    def provenance(self) -> Mapping[str, Any]:
        return self.manifest["provenance"]

    @property
    def package_digest(self) -> str:
        return self.manifest["package_digest"]

    def live(self, prefab_id: str, version: int, name: str) -> bytes | None:
        """Donnée résolue au gel pour (pin, nom) ; `None` si la référence n'a pas été figée."""

        for row in self.manifest["live_refs"]:
            if row["prefab_id"] == prefab_id and row["version"] == version and row["name"] == name:
                return self.files[row["path"]]
        return None


def read_package(data: bytes) -> FrozenPackage:
    """Relit et vérifie un `snapshot.zip` sans rien écrire sur disque. `LiveRefError(PACKAGE_INVALID)` au premier écart :
    zip illisible, nom dangereux ou doublon (casse comprise), lien, membre chiffré, taille menteuse, manifeste inconnu,
    membre absent du manifeste ou manifeste qui cite un membre absent, empreinte fausse."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise _invalid("not a ZIP file") from None
    members: dict[str, bytes] = {}
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_PACKAGE_FILES:
            raise _invalid(f"{len(infos)} members, at most {MAX_PACKAGE_FILES}")
        seen: set[str] = set()
        total = 0
        for info in infos:
            name = info.filename
            problem = package_path_problem(name)
            if problem is not None:
                raise _invalid(f"{name[:80]}: {problem}")
            if name.lower() in seen:
                raise _invalid(f"{name[:80]}: duplicate member (or differs only by case)")
            seen.add(name.lower())
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise _invalid(f"{name[:80]}: links are refused")
            if info.flag_bits & 0x1:
                raise _invalid(f"{name[:80]}: encrypted members are refused")
            limit = MAX_MANIFEST_BYTES if name == MANIFEST_PATH else MAX_PACKAGE_BYTES
            try:
                with archive.open(info) as member:
                    body = member.read(limit + 1)
            except (zipfile.BadZipFile, EOFError, NotImplementedError, RuntimeError):
                raise _invalid(f"{name[:80]}: unreadable member") from None
            total += len(body)
            if len(body) > limit or len(body) != info.file_size or total > MAX_PACKAGE_BYTES:
                raise _invalid(f"{name[:80]}: size does not match its directory entry or exceeds the bound")
            members[name] = body
    raw = members.pop(MANIFEST_PATH, None)
    if raw is None:
        raise _invalid("manifest.json is missing")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _invalid("manifest.json is not UTF-8 JSON") from None
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS or manifest["format"] != PACKAGE_FORMAT:
        raise _invalid(f"manifest must be {PACKAGE_FORMAT} with keys {sorted(_MANIFEST_KEYS)}")
    table = manifest["files"]
    if not isinstance(table, dict) or set(table) != set(members):
        extra = sorted(set(members) - set(table if isinstance(table, dict) else ()))[:3]
        raise _invalid(f"members and manifest.files differ (unlisted: {extra})")
    for path, body in members.items():
        row = table[path]
        if not isinstance(row, dict) or row.get("sha256") != sha256_hex(body) or row.get("size") != len(body):
            raise _invalid(f"{path[:80]}: content does not match the manifest")
    if manifest["package_digest"] != digest_of(table):
        raise _invalid("package_digest does not match manifest.files")
    if not isinstance(manifest["live_refs"], list):
        raise _invalid("manifest.live_refs must be a list")
    for row in manifest["live_refs"]:
        if not isinstance(row, dict) or row.get("path") not in members:
            raise _invalid("a live reference points at a member that is not in the package")
    return FrozenPackage(manifest, members)
