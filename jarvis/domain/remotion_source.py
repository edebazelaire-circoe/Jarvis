"""Source d'une scène Remotion : disposition des fichiers, bloc `source` du manifeste de prefab v2, empreintes
(handoff jarvis-remotion-presentation-integration, Slice 05 ; contrat `docs/remotion-source.md`).

Une source de scène Remotion est une **version de prefab** (`PrefabService`, versions immuables, épinglage, rétention,
retour arrière) dont le manifeste est en `schema_version` 2 et porte un bloc `source`. Ce module est pur : aucune E/S.
Il fixe

- la **disposition** : `src/**` (modules `.ts .tsx .js .jsx .json`, le point d'entrée en fait partie) et `public/**`
  (assets de la scène, atteints par `staticFile("...")`) ; jamais `node_modules`, `package.json`, verrou ni
  configuration : l'unique arbre de dépendances est celui de la capacité Remotion (Slice 04) ;
- les **chemins** : relatifs, POSIX, ASCII, sans `..`, sans lien ni nom réservé Windows, sans collision de casse ;
  l'identité d'un fichier est son chemin dans SA scène (deux scènes peuvent avoir chacune `src/Scene.tsx`) ;
- les **empreintes** : SHA-256 par fichier, `source_digest` de l'ensemble (clé du cache de compilation, Slice 10) ;
- le **crochet d'isolation** (Slice 06) : `SOURCE_GUARDS`, fonctions `(RemotionSource) -> messages` appelées à chaque
  analyse. Vide ici : l'isolation n'est pas livrée par la Slice 05.

Les erreurs sont collectées (`RemotionSourceError.errors`) et nommées par leur chemin, comme pour les prefabs HTML.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

SOURCE_FORMAT = "remotion"
ENGINE_NAME = "remotion"
#: Version du manifeste qui porte un bloc `source` (la 1 est l'HTML historique, jamais réécrite).
MANIFEST_SCHEMA_VERSION = 2

MODULE_ROOT = "src/"
ASSET_ROOT = "public/"
DEFAULT_ENTRY = "src/Scene.tsx"
MODULE_EXTENSIONS = frozenset({".tsx", ".ts", ".jsx", ".js", ".json"})
ASSET_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".woff2", ".woff", ".ttf", ".otf",
                              ".mp3", ".wav", ".ogg", ".mp4", ".webm"})

# Bornes. Le catalogue garde jusqu'à `MAX_VERSIONS_PER_ID` versions par scène : on reste petit.
MAX_MODULES = 64
MAX_ASSETS = 64
MAX_MODULE_BYTES = 256 * 1024
MAX_MODULES_TOTAL_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_ASSETS_TOTAL_BYTES = 32 * 1024 * 1024
MAX_PATH_CHARS = 120
MAX_SEGMENT_CHARS = 64
MAX_DEPTH = 8
MAX_ERRORS = 20
MAX_ERROR_CHARS = 300

_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))})
#: Noms qui n'ont rien à faire dans une source : l'arbre de dépendances est partagé, jamais par scène.
_FORBIDDEN_SEGMENTS = frozenset({"node_modules", "package.json", "package-lock.json", "tsconfig.json", "jsconfig.json",
                                 "remotion.config.ts", "remotion.config.js", "yarn.lock", "pnpm-lock.yaml"})
COMPOSITION_ID = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,63}\Z")
SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
VERSION_TEXT = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}\Z")
MIN_DIMENSION, MAX_DIMENSION = 16, 7680
MAX_FPS = 120
MAX_DURATION_FRAMES = 108_000


class RemotionSourceError(ValueError):
    """Source refusée ; `errors` : messages bornés, nommés par chemin."""

    def __init__(self, errors: Iterable[str]) -> None:
        clipped = tuple(_clip(item) for item in list(errors)[:MAX_ERRORS]) or ("invalid remotion source",)
        super().__init__("; ".join(clipped)[:MAX_ERROR_CHARS])
        self.errors = clipped


def _clip(message: str) -> str:
    return message if len(message) <= MAX_ERROR_CHARS else message[: MAX_ERROR_CHARS - 1] + "…"


class _Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, path: str, message: str) -> None:
        if len(self.items) < MAX_ERRORS:
            self.items.append(_clip(f"{path}: {message}" if path else message))

    def raise_if_any(self) -> None:
        if self.items:
            raise RemotionSourceError(self.items)


# ------------------------------------------------------------------ chemins

def source_path_problem(path: object, *, root: str, extensions: frozenset[str]) -> str | None:
    """Pourquoi `path` n'est pas un chemin de source acceptable sous `root` (`src/` ou `public/`), ou `None`.

    Aucune résolution disque : la règle est lexicale, donc identique sur tous les postes et sans suivre de lien.
    """

    if not isinstance(path, str) or not path:
        return "must be a non-empty string"
    if len(path) > MAX_PATH_CHARS:
        return f"is longer than {MAX_PATH_CHARS} characters"
    if "\\" in path or ":" in path or path.startswith("/") or "\x00" in path:
        return "must be a relative POSIX path (no backslash, drive letter or leading slash)"
    if not path.startswith(root):
        return f"must live under {root}"
    parts = path.split("/")
    if len(parts) > MAX_DEPTH:
        return f"is deeper than {MAX_DEPTH} folders"
    for part in parts:
        if part in ("", ".", ".."):
            return "must not contain empty, '.' or '..' segments (path traversal)"
        if len(part) > MAX_SEGMENT_CHARS or not _SEGMENT.fullmatch(part):
            return f"segment {part[:40]!r} must match [A-Za-z0-9][A-Za-z0-9._-]* (ASCII, no leading dot)"
        if part.endswith(".") or part.lower() in _FORBIDDEN_SEGMENTS:
            return f"segment {part[:40]!r} is not allowed in a scene source (the dependency tree is shared)"
        if part.split(".")[0].lower() in _RESERVED:
            return f"segment {part[:40]!r} is a reserved Windows device name"
    name = parts[-1]
    dot = name.rfind(".")
    extension = name[dot:] if dot > 0 else ""
    if extension not in extensions:
        return f"extension {extension or '(none)'} is not allowed here (allowed: {', '.join(sorted(extensions))})"
    return None


def path_set_problems(paths: Iterable[str]) -> list[str]:
    """Collisions de casse (Windows, macOS) et fichier qui est aussi un dossier."""

    problems: list[str] = []
    folded: dict[str, str] = {}
    all_paths = sorted(set(paths))
    for path in all_paths:
        other = folded.setdefault(path.lower(), path)
        if other != path:
            problems.append(f"{path}: differs from {other} only by letter case")
    taken = set(all_paths)
    for path in all_paths:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            if "/".join(parts[:depth]) in taken:
                problems.append(f"{path}: {'/'.join(parts[:depth])} is a file, not a folder")
                break
    return problems


# ------------------------------------------------------------------ bloc `source` du manifeste

@dataclass(frozen=True, slots=True)
class EnginePin:
    """Ce pour quoi la source a été écrite. L'arbre installé est unique : un écart est **signalé**, jamais corrigé."""

    name: str
    version: str
    react_version: str
    lock_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version, "react_version": self.react_version,
                "lock_sha256": self.lock_sha256}


@dataclass(frozen=True, slots=True)
class Composition:
    """Réglages de la composition, **déclarés** (jamais lus dans le code) : taille, cadence, durée en images."""

    composition_id: str
    width: int
    height: int
    fps: int
    duration_in_frames: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.composition_id, "width": self.width, "height": self.height, "fps": self.fps,
                "duration_in_frames": self.duration_in_frames}


@dataclass(frozen=True, slots=True)
class SourceBlock:
    engine: EnginePin
    entry: str
    composition: Composition
    modules: tuple[str, ...]
    assets: tuple[str, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return (*self.modules, *self.assets)

    def to_dict(self) -> dict[str, Any]:
        return {"format": SOURCE_FORMAT, "engine": self.engine.to_dict(), "entry": self.entry,
                "composition": self.composition.to_dict(), "modules": list(self.modules),
                "assets": list(self.assets)}


def _int_in(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def parse_source_block(raw: object) -> SourceBlock:
    """Le bloc `source` d'un manifeste v2 : clés exactes, chemins sûrs et triés, entrée présente parmi les modules."""

    problems = _Problems()
    keys = {"format", "engine", "entry", "composition", "modules", "assets"}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise RemotionSourceError([f"source must be exactly {sorted(keys)}"])
    if raw["format"] != SOURCE_FORMAT:
        problems.add("source.format", f"must be {SOURCE_FORMAT!r}")
    engine_raw = raw["engine"]
    engine_keys = {"name", "version", "react_version", "lock_sha256"}
    engine = None
    if not isinstance(engine_raw, dict) or set(engine_raw) != engine_keys:
        problems.add("source.engine", f"must be exactly {sorted(engine_keys)}")
    else:
        before = len(problems.items)
        if engine_raw["name"] != ENGINE_NAME:
            problems.add("source.engine.name", f"must be {ENGINE_NAME!r}")
        for field in ("version", "react_version"):
            if not isinstance(engine_raw[field], str) or not VERSION_TEXT.fullmatch(engine_raw[field]):
                problems.add(f"source.engine.{field}", "must be an exact x.y.z version")
        if not isinstance(engine_raw["lock_sha256"], str) or not SHA256_HEX.fullmatch(engine_raw["lock_sha256"]):
            problems.add("source.engine.lock_sha256", "must be a sha256 hex digest of the package-lock.json")
        if len(problems.items) == before:
            engine = EnginePin(engine_raw["name"], engine_raw["version"], engine_raw["react_version"],
                               engine_raw["lock_sha256"])
    comp_raw = raw["composition"]
    comp_keys = {"id", "width", "height", "fps", "duration_in_frames"}
    composition = None
    if not isinstance(comp_raw, dict) or set(comp_raw) != comp_keys:
        problems.add("source.composition", f"must be exactly {sorted(comp_keys)}")
    else:
        before = len(problems.items)
        if not isinstance(comp_raw["id"], str) or not COMPOSITION_ID.fullmatch(comp_raw["id"]):
            problems.add("source.composition.id", "must match [A-Za-z][A-Za-z0-9-]{0,63}")
        for field in ("width", "height"):
            if not _int_in(comp_raw[field], MIN_DIMENSION, MAX_DIMENSION):
                problems.add(f"source.composition.{field}", f"must be an integer {MIN_DIMENSION}..{MAX_DIMENSION}")
        if not _int_in(comp_raw["fps"], 1, MAX_FPS):
            problems.add("source.composition.fps", f"must be an integer 1..{MAX_FPS}")
        if not _int_in(comp_raw["duration_in_frames"], 1, MAX_DURATION_FRAMES):
            problems.add("source.composition.duration_in_frames", f"must be an integer 1..{MAX_DURATION_FRAMES}")
        if len(problems.items) == before:
            composition = Composition(comp_raw["id"], comp_raw["width"], comp_raw["height"], comp_raw["fps"],
                                      comp_raw["duration_in_frames"])
    lists: dict[str, tuple[str, ...]] = {}
    for name, root, extensions, limit in (("modules", MODULE_ROOT, MODULE_EXTENSIONS, MAX_MODULES),
                                          ("assets", ASSET_ROOT, ASSET_EXTENSIONS, MAX_ASSETS)):
        listed = raw[name]
        if not isinstance(listed, list) or len(listed) > limit:
            problems.add(f"source.{name}", f"must be a list of at most {limit} paths")
            lists[name] = ()
            continue
        for index, path in enumerate(listed):
            why = source_path_problem(path, root=root, extensions=extensions)
            if why:
                problems.add(f"source.{name}[{index}]", why)
        if list(listed) != sorted({p for p in listed if isinstance(p, str)}):
            problems.add(f"source.{name}", "must be sorted and without duplicates (a canonical order)")
        lists[name] = tuple(p for p in listed if isinstance(p, str))
    entry = raw["entry"]
    if not isinstance(entry, str) or entry not in lists["modules"]:
        problems.add("source.entry", "must be one of source.modules")
    elif not entry.endswith((".tsx", ".jsx")):
        problems.add("source.entry", "must be a .tsx or .jsx module that default-exports the scene component")
    for message in path_set_problems(lists["modules"] + lists["assets"]):
        problems.add("source", message)
    problems.raise_if_any()
    assert engine is not None and composition is not None
    return SourceBlock(engine, entry, composition, lists["modules"], lists["assets"])


# ------------------------------------------------------------------ fichiers et empreintes

#: Crochet de la Slice 06 (isolation) : chaque garde reçoit la source analysée et rend des messages de refus.
#: Vide à la Slice 05. Ajouter une garde ici la fait appliquer à **toute** publication et relecture du catalogue.
SourceGuard = Callable[["RemotionSource"], Iterable[str]]
SOURCE_GUARDS: tuple[SourceGuard, ...] = ()


@dataclass(frozen=True, slots=True)
class RemotionSource:
    """Bloc validé et contenu de chaque fichier (octets), tels que le prefab les publie."""

    block: SourceBlock
    files: Mapping[str, bytes]

    @property
    def digest(self) -> str:
        return source_digest(self.files)

    def text(self, path: str) -> str:
        return self.files[path].decode("utf-8")

    def module_texts(self) -> dict[str, str]:
        return {path: self.text(path) for path in self.block.modules}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hashes(files: Mapping[str, bytes]) -> dict[str, str]:
    return {path: sha256_hex(files[path]) for path in sorted(files)}


def source_digest(files: Mapping[str, bytes]) -> str:
    """Empreinte déterministe de l'ensemble : chemins triés + SHA-256 de chaque contenu. Indépendante de l'ordre,
    du moment et de l'endroit où la source vit (donc de l'id et de la version du prefab)."""

    canonical = json.dumps(file_hashes(files), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def parse_source(block: SourceBlock, files: Mapping[str, bytes]) -> RemotionSource:
    """Contenu contre bloc : exactement les fichiers déclarés, bornés, modules en UTF-8 sans NUL, gardes de la Slice 06."""

    problems = _Problems()
    declared = set(block.paths)
    for path in sorted(declared - set(files)):
        problems.add(path, "is declared by the manifest but missing")
    for path in sorted(set(files) - declared):
        problems.add(str(path)[:80], "is present but not declared by the manifest")
    totals = {"modules": 0, "assets": 0}
    for kind, paths, per_file, total_limit in (("modules", block.modules, MAX_MODULE_BYTES, MAX_MODULES_TOTAL_BYTES),
                                              ("assets", block.assets, MAX_ASSET_BYTES, MAX_ASSETS_TOTAL_BYTES)):
        for path in paths:
            data = files.get(path)
            if data is None:
                continue
            if not isinstance(data, (bytes, bytearray)):
                problems.add(path, "content must be bytes")
                continue
            totals[kind] += len(data)
            if len(data) > per_file:
                problems.add(path, f"is {len(data)} bytes, at most {per_file}")
            elif kind == "modules":
                if b"\x00" in data:
                    problems.add(path, "must not contain NUL characters")
                else:
                    try:
                        data.decode("utf-8")
                    except UnicodeDecodeError:
                        problems.add(path, "is not valid UTF-8")
        if totals[kind] > total_limit:
            problems.add(kind, f"total {totals[kind]} bytes, at most {total_limit}")
    problems.raise_if_any()
    source = RemotionSource(block, {path: bytes(files[path]) for path in sorted(declared)})
    for guard in SOURCE_GUARDS:
        for message in guard(source):
            problems.add("guard", message)
    problems.raise_if_any()
    return source


def decode_candidate_files(sources: object, assets: object) -> dict[str, bytes]:
    """Fichiers d'un candidat JSON : `sources` `{chemin: texte}`, `assets` `{chemin: base64}` -> `{chemin: octets}`."""

    problems = _Problems()
    files: dict[str, bytes] = {}
    if not isinstance(sources, dict):
        problems.add("sources", "must be an object {path: text}")
    else:
        for path, text in sources.items():
            if not isinstance(text, str):
                problems.add(str(path)[:80], "source content must be a string")
            else:
                files[str(path)] = text.encode("utf-8", errors="surrogatepass")
    if not isinstance(assets, dict):
        problems.add("assets", "must be an object {path: base64}")
    else:
        for path, encoded in assets.items():
            if str(path) in files:
                problems.add(str(path)[:80], "appears in both sources and assets")
                continue
            try:
                if not isinstance(encoded, str):
                    raise ValueError
                files[str(path)] = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                problems.add(str(path)[:80], "asset content must be base64 text")
    problems.raise_if_any()
    return files


# ------------------------------------------------------------------ construction d'un candidat

def build_candidate(*, prefab_id: str, title: str, composition: Composition, engine: EnginePin,
                    files: Mapping[str, str | bytes], entry: str = DEFAULT_ENTRY, props: Mapping[str, Any] | None = None,
                    data: Mapping[str, Any] | None = None, sample: Mapping[str, Any] | None = None, family: str = "scene",
                    description: str = "", default_size: tuple[float, float] | None = None) -> dict[str, Any]:
    """Candidat `{manifest, sources, assets}` (manifeste v2) pour `PrefabService.save` / `parse_candidate`.

    `files` : `{chemin: texte}` pour `src/**`, `{chemin: octets}` pour `public/**`. Le numéro de version du manifeste est
    un espace réservé : Core attribue le vrai à la publication. Les listes de chemins sont triées (forme canonique).
    `props` / `data` : schémas d'entrée (`type: object`) des paramètres éditables de la scène ; `sample` : `{props, data}`.
    Aucune validation ici : `parse_candidate` la fait, une seule fois, avec toutes les erreurs.
    """

    # Classement par racine, sans rien écarter en silence : tout chemin hors de `public/` est un module (donc jugé par
    # `parse_candidate`, qui refuse `../x.ts`, `C:/x.ts`...) ; un contenu en octets hors de `public/` est refusé de même.
    assets = sorted(path for path in files if str(path).startswith(ASSET_ROOT) or isinstance(files[path], bytes))
    modules = sorted(path for path in files if path not in assets)
    scene: dict[str, Any] = {"kind": "window"}
    if default_size is not None:
        scene["default_size"] = {"w": default_size[0], "h": default_size[1]}
    manifest: dict[str, Any] = {
        "schema": "jarvis.prefab", "schema_version": MANIFEST_SCHEMA_VERSION, "id": prefab_id, "version": 1, "title": title,
        "description": description, "family": family, "tags": [], "aliases": [], "scene": scene,
        "inputs": {"props": dict(props or {"type": "object", "properties": {}}),
                   "data": dict(data or {"type": "object", "properties": {}})},
        "sample": dict(sample or {"props": {}, "data": {}}),
        "source": SourceBlock(engine, entry, composition, tuple(modules), tuple(assets)).to_dict()}
    return {"manifest": manifest, "sources": {path: files[path] for path in modules},
            "assets": {path: base64.b64encode(files[path] if isinstance(files[path], bytes) else files[path].encode("utf-8")
                                              ).decode("ascii") for path in assets}}
