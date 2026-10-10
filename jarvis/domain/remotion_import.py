"""Import d'un modèle Remotion amont : analyse d'une archive vérifiée -> candidat de prefab (Slice 18, `docs/remotion-import.md`).

Pur : reçoit les octets d'une archive DÉJÀ téléchargée (`remotion_upstream.read_tar_source` la lit) et rend un plan (`ImportPlan`)
dont le `candidate` est un manifeste v3 (`source` + `catalog`) que `PrefabService.save` publie. Rien n'est exécuté : le code amont
n'est lu que comme TEXTE. Le plan s'appuie sur ce que la source atteint réellement, pas sur ce que `package.json` annonce :

- **Dépendances** : seuls les imports nus de `SCENE_ALLOWED_IMPORTS` (`react`, `remotion`) existent dans l'arbre partagé épinglé
  (`docs/remotion-source.md` §5). Un import atteignable d'un autre paquet est un refus typé `dependency_refused` ; une dépendance
  déclarée mais jamais atteinte est écartée et le dit. `package.json` n'est jamais copié ni exécuté (aucun script, aucun npm).
- **Composition** : la scène amont enregistre ses compositions dans un `Root` (`<Composition id component .../>`), pas par un
  `export default`. Le plan choisit une composition, lit ses réglages (littéraux ou constantes numériques uniques) et génère une
  entrée `src/Scene.tsx` qui rend le composant avec les `defaultProps` du `Root`.
- **Modules** : seuls les modules ATTEIGNABLES depuis ce composant sont repris (le `Root`, `index.ts`, les configurations restent
  dehors) ; les assets de `public/` ne sont repris que si un `staticFile("...")` littéral les nomme.
- **Licence** : celle du modèle (`remotion_upstream.classify_licence`), recopiée dans `src/upstream/license.json`.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import json
import posixpath
import re
import time
from typing import Any

from jarvis.domain.prefab import PrefabDefinitionError, parse_candidate
from jarvis.domain.presentation_studio import is_presentation_id
from jarvis.domain.remotion_compile import SCENE_ALLOWED_IMPORTS
from jarvis.domain.remotion_source import (
    ASSET_EXTENSIONS, ASSET_ROOT, COMPOSITION_ID, MAX_ASSET_BYTES, MAX_ASSETS_TOTAL_BYTES, MAX_MODULE_BYTES, MODULE_EXTENSIONS,
    MODULE_ROOT, Composition, EnginePin, RemotionSourceError, build_candidate, sha256_hex, source_digest,
)
from jarvis.domain.remotion_upstream import (
    MAX_LICENCE_BYTES, REMOTION_RUNTIME_LICENCE, TarContent, UpstreamErrorCode, UpstreamOrigin, UpstreamRefusal, classify_licence,
    is_licence_file, normalise_owners, parse_origin, read_tar_source, valid_subdir,
)

MAX_PACKAGE_JSON_BYTES = 256 * 1024
MAX_CHANGES = 16
MAX_CHANGE_CHARS = 120
ENTRY_NAME = "src/Scene.tsx"
FALLBACK_ENTRY_NAME = "src/JarvisEntry.tsx"
LICENCE_MODULE = "src/upstream/license.json"
_RESOLVE_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js", ".json")
STACK = ("react", "remotion", "typescript")
# `import` / `require` au milieu d'une chaîne ou d'une propriété (`x.import`) n'est pas une instruction. Les espaces sont optionnels
# (`import{a}from'zod'`, `export*from'zod'` sont des imports) et les quantificateurs bornés (aucun retour sur trace quadratique).
_NIS = r"""(?<![\w$."'`])"""
_IMPORT_FROM = re.compile(_NIS + r"""import(?![\w$])(?!\s*type\b)\s*(?:[^;'"`]{0,400}?from\s*|\s*)(['"])([^'"\n]{1,300})\1""")
_EXPORT_FROM = re.compile(_NIS + r"""export(?![\w$])(?!\s*type\b)\s*(?:\*(?:\s*as\s+[\w$]+)?|\{[^}]{0,2000}\})\s*from\s*(['"])([^'"\n]{1,300})\1""")
_REQUIRE = re.compile(_NIS + r"""require\s*\(\s*(['"])([^'"\n]{1,300})\1\s*\)""")
_DYNAMIC = re.compile(_NIS + r"""import\s*\(\s*(['"])([^'"\n]{1,300})\1\s*\)""")
_STATIC_FILE = re.compile(r"""\bstaticFile\s*\(\s*(['"`])([^'"`$\n]*)\1\s*\)""")
_STATIC_FILE_ANY = re.compile(r"\bstaticFile\s*\(")
_IMPORT_STATEMENT = re.compile(_NIS + r"""import(?![\w$])(?!\s*type\b)\s*([^;'"`]{0,400}?)\s*from\s*(['"])([^'"\n]{1,300})\2""")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_JS_WORDS = frozenset({"true", "false", "null", "undefined", "as", "const", "satisfies", "typeof", "new", "NaN", "Infinity", "Math",
                       "Object", "Array", "String", "Number", "Boolean", "JSON", "Date", "Symbol", "Map", "Set"})


#: Échéance de toute l'analyse (CPU) : un texte piégé ne tient pas Core plus longtemps (`import_timeout`).
ANALYSIS_BUDGET_S = 20.0
MAX_EXPRESSION_CHARS = 200


class _Budget:
    def __init__(self, seconds: float, clock=time.monotonic) -> None:
        self._clock = clock
        self._limit = clock() + seconds

    def check(self) -> None:
        if self._clock() > self._limit:
            raise UpstreamRefusal(UpstreamErrorCode.IMPORT_TIMEOUT, "analysing the template took too long")


class ImportErrorCode(UpstreamErrorCode):
    """Codes de l'analyse (en plus de ceux de l'origine, de l'archive et de la licence)."""

    REQUEST_INVALID = "request_invalid"
    NO_PROJECT = "no_project"
    NO_COMPOSITION = "no_composition"
    COMPOSITION_AMBIGUOUS = "composition_ambiguous"
    COMPOSITION_UNRESOLVED = "composition_unresolved"
    COMPONENT_UNRESOLVED = "component_unresolved"
    DEFAULT_PROPS_UNRESOLVED = "default_props_unresolved"
    DEPENDENCY_REFUSED = "dependency_refused"
    REMOTION_VERSION = "remotion_version_incompatible"
    IMPORT_UNRESOLVED = "import_unresolved"
    IMPORT_UNSUPPORTED = "import_unsupported_file"
    IMPORT_OUTSIDE = "import_outside_source"
    FILE_TOO_LARGE = "file_too_large"
    SOURCE_INVALID = "source_invalid"
    SOURCE_GUARD = "source_guard_refused"


@dataclass(frozen=True, slots=True)
class ImportRequest:
    origin: UpstreamOrigin
    subdir: str = ""
    composition_id: str = ""
    composition: Composition | None = None  # réglages donnés à la main quand le code ne les rend pas lisibles
    title: str = ""
    ref: str = ""
    presentation_id: str = ""
    scene_id: str = ""


_REQUEST_KEYS = frozenset({"repo_url", "commit", "presentation_id", "scene_id", "composition_id", "subdir", "composition", "title", "ref"})


def parse_import_request(raw: object, *, allowed_owners: tuple[str, ...], need_presentation: bool) -> ImportRequest:
    """Corps d'une requête d'import ou de plan. Clés fermées ; `UpstreamRefusal` (`request_invalid`, `origin_*`, `commit_*`)."""

    if not isinstance(raw, Mapping):
        raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID, "the body must be a JSON object")
    unknown = sorted(str(key)[:40] for key in raw if key not in _REQUEST_KEYS)
    if unknown:
        raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID,
                              f"unknown fields {unknown[:5]}: an import is always scoped to a presentation, promotion is a separate "
                              f"explicit step; allowed fields are {sorted(_REQUEST_KEYS)}")
    origin = parse_origin(raw.get("repo_url"), raw.get("commit"), normalise_owners(allowed_owners))
    presentation_id = raw.get("presentation_id", "")
    if need_presentation and not is_presentation_id(presentation_id):
        raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID, "presentation_id (pst_ followed by 32 hexadecimal characters) is required: an import is scoped to one presentation")
    if not need_presentation and presentation_id not in ("", None) and not isinstance(presentation_id, str):
        raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID, "presentation_id must be a string")
    scene_id = raw.get("scene_id", "")
    if scene_id not in ("", None) and not (isinstance(scene_id, str) and re.fullmatch(r"pss_[0-9a-f]{12}", scene_id)):
        raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID, "scene_id must look like pss_ followed by 12 hexadecimal characters")
    composition_id = raw.get("composition_id", "")
    if composition_id not in ("", None) and not (isinstance(composition_id, str) and COMPOSITION_ID.fullmatch(composition_id)):
        raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID, "composition_id must match [A-Za-z][A-Za-z0-9-]{0,63}")
    title = raw.get("title", "")
    ref = raw.get("ref", "")
    for name, value in (("title", title), ("ref", ref)):
        if value not in ("", None) and not (isinstance(value, str) and value.isprintable() and len(value.strip()) <= 80):
            raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID, f"{name} must be one printable line of at most 80 characters")
    override = None
    given = raw.get("composition")
    if given is not None:
        keys = {"width", "height", "fps", "duration_in_frames"}
        if not isinstance(given, Mapping) or set(given) != keys or any(isinstance(given[k], bool) or not isinstance(given[k], int) for k in keys):
            raise UpstreamRefusal(ImportErrorCode.REQUEST_INVALID, f"composition must be exactly {sorted(keys)} (integers)")
        override = Composition(composition_id or "Imported", given["width"], given["height"], given["fps"], given["duration_in_frames"])
    return ImportRequest(origin, valid_subdir(raw.get("subdir")), composition_id or "", override, (title or "").strip(),
                         (ref or "").strip(), presentation_id or "", scene_id or "")


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """Résultat de l'analyse : le candidat à publier et tout ce qu'un utilisateur doit voir avant de confirmer."""

    request: ImportRequest
    archive_sha256: str
    archive_bytes: int
    licence: dict[str, str]
    composition: Composition
    dependencies: tuple[tuple[str, str], ...]
    dropped_dependencies: tuple[str, ...]
    modules: tuple[str, ...]
    assets: tuple[str, ...]
    dropped_modules: int
    dropped_assets: int
    changes: tuple[str, ...]
    warnings: tuple[str, ...]
    source_digest: str
    candidate: dict[str, Any] = field(repr=False)

    def to_public(self) -> dict[str, Any]:
        """Forme publique : jamais d'octet de source, de chemin du poste ni de jeton."""

        origin = self.request.origin
        return {"origin": {"name": origin.name, "url": origin.repository_url, "commit": origin.commit,
                           "archive_url": origin.archive_url, "archive_sha256": self.archive_sha256,
                           "archive_bytes": self.archive_bytes, "subdir": self.request.subdir},
                "license": {**self.licence, "runtime_license": REMOTION_RUNTIME_LICENCE},
                "composition": self.composition.to_dict(),
                "dependencies": [{"name": name, "version": version} for name, version in self.dependencies],
                "dropped_dependencies": list(self.dropped_dependencies),
                "files": {"modules": list(self.modules), "assets": list(self.assets),
                          "dropped_modules": self.dropped_modules, "dropped_assets": self.dropped_assets},
                "changes": list(self.changes), "warnings": list(self.warnings), "source_digest": self.source_digest,
                "scope": "presentation"}


# ------------------------------------------------------------------ lecture de l'archive

class _Selector:
    """Quels fichiers lire, en UNE passe : licences, `package.json`, modules, et les assets de `public/` dans la limite d'un budget
    souple (`MAX_ASSETS_TOTAL_BYTES`) ; ce qui ne tient pas est noté (`skipped`) et refusé seulement si une scène le nomme."""

    def __init__(self, subdir: str) -> None:
        self.base = f"{subdir}/" if subdir else ""
        self.assets_total = 0
        self.skipped: set[str] = set()

    def __call__(self, path: str, size: int) -> int | None:
        base = self.base
        if is_licence_file(path) or (base and path.startswith(base) and is_licence_file(path.removeprefix(base))):
            return MAX_LICENCE_BYTES
        if path in (base + "package.json", "package.json"):
            return MAX_PACKAGE_JSON_BYTES
        if path.startswith(base + MODULE_ROOT) and posixpath.splitext(path)[1].lower() in MODULE_EXTENSIONS:
            return MAX_MODULE_BYTES
        if path.startswith(base + ASSET_ROOT) and posixpath.splitext(path)[1].lower() in ASSET_EXTENSIONS:
            if size <= MAX_ASSET_BYTES and self.assets_total + size <= MAX_ASSETS_TOTAL_BYTES:
                self.assets_total += size
                return MAX_ASSET_BYTES
            self.skipped.add(path)
        return None


def analyse_archive(data: bytes, request: ImportRequest, *, engine: EnginePin, imported_at: datetime,
                    budget_s: float = ANALYSIS_BUDGET_S, clock=time.monotonic) -> ImportPlan:
    """Archive vérifiée -> plan. `UpstreamRefusal` (codes de `ImportErrorCode`) à la première cause établie, sinon le plan."""

    origin, subdir = request.origin, request.subdir
    base = f"{subdir}/" if subdir else ""
    budget = _Budget(budget_s, clock)
    selector = _Selector(subdir)
    first = read_tar_source(data, expected_commit=origin.commit, select=selector, deadline_s=budget_s, clock=clock)
    budget.check()
    package = _package_json(first.files, base)
    modules = {path.removeprefix(base): body.decode("utf-8", errors="strict") if _decodable(body) else None
               for path, body in first.files.items() if path.startswith(base + MODULE_ROOT)}
    if any(text is None for text in modules.values()):
        bad = sorted(path for path, text in modules.items() if text is None)[:3]
        raise UpstreamRefusal(ImportErrorCode.SOURCE_INVALID, "modules are not valid UTF-8 text", tuple(bad))
    texts: dict[str, str] = {path: text for path, text in modules.items() if text is not None}
    if not texts:
        raise UpstreamRefusal(ImportErrorCode.NO_PROJECT, f"no src/ module found{f' under {subdir}' if subdir else ''}: not a Remotion project")
    licence_files = {name: body for name, body in first.files.items() if is_licence_file(name)}
    if base:
        licence_files.update({name.removeprefix(base): body for name, body in first.files.items()
                              if name.startswith(base) and is_licence_file(name.removeprefix(base))})
    licence = classify_licence(licence_files, package)
    tag = _choose_composition(texts, request, budget)
    settings = _composition_settings(tag, _constants_of(texts, budget), request)
    entry_name = ENTRY_NAME if ENTRY_NAME not in texts else FALLBACK_ENTRY_NAME
    wrapper, wrapper_imports = _wrapper(tag, texts, entry_name, origin)
    all_modules = {**texts, entry_name: wrapper}
    reachable, bare_imports, assets_named, dynamic = _reach(entry_name, all_modules, first, base, budget)
    _check_dependencies(bare_imports, package)
    kept_modules = {path: all_modules[path] for path in sorted(reachable)}
    kept_modules[LICENCE_MODULE] = json.dumps(
        {"spdx_id": licence.spdx, "source": licence.source, "upstream": f"{origin.name}@{origin.commit}", "text": licence.text},
        indent=2, ensure_ascii=True) + "\n"
    asset_paths: dict[str, bytes] = {}
    warnings: list[str] = []
    for name in sorted(assets_named):
        full = base + ASSET_ROOT + name
        if full in first.files and posixpath.splitext(name)[1].lower() in ASSET_EXTENSIONS:
            asset_paths[ASSET_ROOT + name] = first.files[full]
        elif full in first.oversize or full in selector.skipped:
            raise UpstreamRefusal(ImportErrorCode.FILE_TOO_LARGE,
                                  f"staticFile({name!r}): the asset is larger than {MAX_ASSET_BYTES} bytes or past the {MAX_ASSETS_TOTAL_BYTES} bytes budget")
        else:
            warnings.append(f"staticFile({name!r}) names a file missing from public/ or of an unsupported type: the scene will not find it")
    if dynamic:
        warnings.append(f"{dynamic} staticFile call(s) with a computed name: those assets cannot be known, none was copied")
    dependencies = _dependency_map(bare_imports, engine, package, warnings)
    dropped_dependencies = _dropped(package, {name for name, _ in dependencies})
    all_paths_under = {path.removeprefix(base) for path in first.paths if path.startswith(base)}
    dropped_modules = len({p for p in all_paths_under if p.startswith(MODULE_ROOT)
                           and posixpath.splitext(p)[1].lower() in MODULE_EXTENSIONS} - set(reachable))
    public_total = len({p for p in all_paths_under if p.startswith(ASSET_ROOT)})
    dropped_assets = max(0, public_total - len(asset_paths))
    changes = _changes(request, tag, entry_name, kept_modules, dropped_modules, asset_paths, dropped_assets, dependencies,
                       dropped_dependencies, package, settings, licence.source, wrapper_imports)
    composition = settings
    title = request.title or f"{origin.repo} - {composition.composition_id}"
    files: dict[str, str | bytes] = {**kept_modules, **asset_paths}
    byte_files = {path: (body if isinstance(body, bytes) else body.encode("utf-8")) for path, body in files.items()}
    stamp = imported_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    catalog = {
        "type": "composition", "compatibility": {"remotion": "native", "slidecar": "unsupported"}, "stack": list(STACK),
        "dependencies": [{"name": name, "version": version} for name, version in dependencies],
        "license": licence.spdx, "runtime_license": REMOTION_RUNTIME_LICENCE,
        "upstream": {k: v for k, v in (("name", origin.name), ("url", origin.repository_url), ("ref", request.ref),
                                       ("license", licence.spdx), ("author", origin.owner), ("commit", origin.commit),
                                       ("archive_sha256", sha256_hex(data)), ("imported_at", stamp),
                                       ("source_sha256", source_digest(byte_files)),
                                       ("changes", list(changes))) if v},
    }
    try:
        candidate = build_candidate(
            prefab_id="presentation-studio.p000000000000.s000000000000", title=title[:80], composition=composition, engine=engine,
            files=files, entry=entry_name, description=f"Imported from {origin.name}@{origin.commit[:12]} ({licence.spdx})"[:200],
            catalog=catalog)
    except RemotionSourceError as exc:
        raise UpstreamRefusal(ImportErrorCode.SOURCE_INVALID, "the imported source does not fit the Jarvis source layout",
                              tuple(str(item) for item in getattr(exc, "problems", [str(exc)]))) from None
    try:
        parse_candidate(candidate)  # manifeste v3, bornes, fichiers et gardes de la Slice 06 : un seul juge, le même que la publication
    except PrefabDefinitionError as exc:
        guard = any(item.startswith("guard:") for item in exc.errors)
        raise UpstreamRefusal(ImportErrorCode.SOURCE_GUARD if guard else ImportErrorCode.SOURCE_INVALID,
                              "the imported source is refused by the Jarvis source guards" if guard
                              else "the imported source does not fit the Jarvis source layout", tuple(exc.errors[:20])) from None
    return ImportPlan(
        request=request, archive_sha256=sha256_hex(data), archive_bytes=len(data), licence=licence.to_dict(), composition=composition,
        dependencies=tuple(dependencies), dropped_dependencies=tuple(dropped_dependencies),
        modules=tuple(sorted(kept_modules)), assets=tuple(sorted(asset_paths)), dropped_modules=dropped_modules,
        dropped_assets=dropped_assets, changes=tuple(changes), warnings=tuple(warnings), source_digest=source_digest(byte_files),
        candidate=candidate)


def _decodable(body: bytes) -> bool:
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in body


def _package_json(files: Mapping[str, bytes], base: str) -> Mapping[str, Any] | None:
    for name in (base + "package.json", "package.json"):
        if name in files:
            try:
                value = json.loads(files[name].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise UpstreamRefusal(ImportErrorCode.SOURCE_INVALID, "package.json is not valid JSON") from None
            return value if isinstance(value, dict) else None
    return None


# ------------------------------------------------------------------ texte JavaScript : commentaires, balises

@functools.lru_cache(maxsize=96)
def strip_comments(text: str) -> str:
    """Retire `//` et `/* */` hors chaînes (les numéros de ligne restent : un commentaire devient des espaces)."""

    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c in "\"'`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Contenu entre l'accolade ouvrante à `start` et sa fermante (chaînes respectées) ; rend (contenu, indice après)."""

    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    raise UpstreamRefusal(ImportErrorCode.COMPOSITION_UNRESOLVED, "unbalanced braces in a <Composition> tag")


@dataclass(frozen=True, slots=True)
class CompositionTag:
    file: str
    attrs: Mapping[str, tuple[str, str]]  # nom -> ("str" | "expr", texte)

    @property
    def id(self) -> str:
        kind, value = self.attrs.get("id", ("", ""))
        return value.strip().strip("'\"`") if kind in ("str", "expr") else ""


def find_composition_tags(texts: Mapping[str, str], budget: _Budget | None = None) -> list[CompositionTag]:
    tags: list[CompositionTag] = []
    for path in sorted(texts):
        if budget is not None:
            budget.check()
        clean = strip_comments(texts[path])
        for match in re.finditer(r"<Composition(?=[\s/>])", clean):
            attrs = _read_attrs(clean, match.end())
            if attrs is not None and "id" in attrs:
                tags.append(CompositionTag(path, attrs))
    return tags


def _read_attrs(text: str, i: int) -> dict[str, tuple[str, str]] | None:
    attrs: dict[str, tuple[str, str]] = {}
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if text.startswith("/>", i) or text.startswith(">", i):
            return attrs
        if text[i] == "{":
            _, i = _balanced(text, i)
            continue
        m = re.compile(r"[A-Za-z_:][\w:.-]*").match(text, i)
        if not m:
            return None
        name, i = m.group(0), m.end()
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "=":
            i += 1
            while i < n and text[i].isspace():
                i += 1
            if i < n and text[i] in "\"'":
                j = text.find(text[i], i + 1)
                if j < 0:
                    return None
                attrs[name] = ("str", text[i + 1:j])
                i = j + 1
            elif i < n and text[i] == "{":
                inner, i = _balanced(text, i)
                attrs[name] = ("expr", inner.strip())
            else:
                return None
        else:
            attrs[name] = ("expr", "true")
    return None


def _choose_composition(texts: Mapping[str, str], request: ImportRequest, budget: _Budget | None = None) -> CompositionTag:
    tags = find_composition_tags(texts, budget)
    ids = sorted({tag.id for tag in tags if tag.id})
    if not tags:
        raise UpstreamRefusal(ImportErrorCode.NO_COMPOSITION, "no <Composition id=... component=...> found in src/: not a Remotion project")
    if request.composition_id:
        picked = [tag for tag in tags if tag.id == request.composition_id]
        if not picked:
            raise UpstreamRefusal(ImportErrorCode.NO_COMPOSITION, f"composition {request.composition_id!r} not found", tuple(ids))
        return picked[0]
    if len(ids) != 1:
        raise UpstreamRefusal(ImportErrorCode.COMPOSITION_AMBIGUOUS,
                              f"the project registers {len(ids)} compositions: pass composition_id", tuple(ids))
    return next(tag for tag in tags if tag.id == ids[0])


_CONSTANT = re.compile(r"\bconst\s+([A-Za-z_$][\w$]*)\s*(?::\s*number\s*)?=\s*([0-9][0-9_]{0,12})\s*(?:;|\n|,)")


def _constants_of(texts: Mapping[str, str], budget: _Budget | None = None) -> dict[str, int | None]:
    """`{nom: valeur}` des `const NOM = <entier>` du projet (un seul balayage) ; `None` quand deux valeurs différentes se disputent le nom."""

    found: dict[str, int | None] = {}
    for text in texts.values():
        if budget is not None:
            budget.check()
        for name, raw in _CONSTANT.findall(strip_comments(text)):
            value = int(raw.replace("_", ""))
            if name not in found:
                found[name] = value
            elif found[name] != value:
                found[name] = None
    return found


def _number(expr: str, constants: Mapping[str, int | None]) -> int | None:
    """Entier d'une expression : littéral, constante numérique unique, ou arithmétique de ceux-là. Sinon `None` (jamais d'exception :
    expression trop longue ou trop profonde, `RecursionError` comprise)."""

    if len(expr) > MAX_EXPRESSION_CHARS:
        return None
    substituted = _IDENT.sub(lambda m: str(constants[m.group(0)]) if constants.get(m.group(0)) is not None else m.group(0), expr)
    if not re.fullmatch(r"[0-9_\s+\-*/()]+", substituted):
        return None

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -walk(node.operand) if isinstance(node.op, ast.USub) else walk(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = walk(node.left), walk(node.right)
            return {ast.Add: left + right, ast.Sub: left - right, ast.Mult: left * right,
                    ast.Div: left / right if right else float("nan")}[type(node.op)]
        raise ValueError

    try:
        value = walk(ast.parse(substituted.replace("_", "").strip(), mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, RecursionError, MemoryError, OverflowError):
        return None
    return int(value) if value == value and abs(value) < 1e12 and value == int(value) else None


def _composition_settings(tag: CompositionTag, constants: Mapping[str, int | None], request: ImportRequest) -> Composition:
    if not COMPOSITION_ID.fullmatch(tag.id):
        raise UpstreamRefusal(ImportErrorCode.COMPOSITION_UNRESOLVED, "a composition id must match [A-Za-z][A-Za-z0-9-]{0,63}")
    found: dict[str, int | None] = {}
    for attr, key in (("width", "width"), ("height", "height"), ("fps", "fps"), ("durationInFrames", "duration_in_frames")):
        kind, value = tag.attrs.get(attr, ("", ""))
        found[key] = _number(value, constants) if kind in ("expr", "str") and value else None
    given = request.composition
    if given is not None:
        found = {key: (getattr(given, key) if getattr(given, key) is not None else found[key]) for key in found}
    missing = [key for key, value in found.items() if value is None]
    if missing:
        raise UpstreamRefusal(ImportErrorCode.COMPOSITION_UNRESOLVED,
                              f"composition {tag.id!r}: {missing} are not readable literals or unique numeric constants "
                              f"(pass them in the 'composition' field: width, height, fps, duration_in_frames)")
    return Composition(tag.id, int(found["width"]), int(found["height"]), int(found["fps"]), int(found["duration_in_frames"]))  # type: ignore[arg-type]


# ------------------------------------------------------------------ entrée générée

def _imports_of(text: str) -> dict[str, tuple[str, str]]:
    """Liaisons locales d'un module : `{nom local: (spécificateur, nom importé ou "default")}`."""

    bindings: dict[str, tuple[str, str]] = {}
    for clause, _, spec in _IMPORT_STATEMENT.findall(strip_comments(text)):
        clause = clause.strip()
        named = re.search(r"\{([^}]*)\}", clause)
        if named:
            for part in named.group(1).split(","):
                part = re.sub(r"^\s*type\s+", "", part.strip())
                if not part:
                    continue
                pieces = re.split(r"\s+as\s+", part)
                bindings[pieces[-1].strip()] = (spec, pieces[0].strip())
            clause = clause.replace(named.group(0), "")
        clause = clause.strip(" ,")
        if clause.startswith("* as"):
            bindings[clause.split()[-1]] = (spec, "*")
        elif clause and _IDENT.fullmatch(clause.split(",")[0].strip()):
            bindings[clause.split(",")[0].strip()] = (spec, "default")
    return bindings


def _comment_safe(text: str) -> str:
    """Un id venu du code amont dans un commentaire généré : une ligne, caractères simples (aucun saut de ligne ni `*/`)."""

    return re.sub(r"[^A-Za-z0-9_-]", "?", text)[:64]


def _relative(from_dir: str, target_path: str) -> str:
    rel = posixpath.relpath(posixpath.splitext(target_path)[0] if target_path.endswith(_RESOLVE_EXTENSIONS) else target_path, from_dir or ".")
    return rel if rel.startswith(".") else "./" + rel


def _wrapper(tag: CompositionTag, texts: Mapping[str, str], entry_name: str, origin: UpstreamOrigin) -> tuple[str, tuple[str, ...]]:
    kind, expr = tag.attrs.get("component", ("", ""))
    component = expr.strip() if kind == "expr" else ""
    if not _IDENT.fullmatch(component or "."):
        raise UpstreamRefusal(ImportErrorCode.COMPONENT_UNRESOLVED,
                              f"composition {tag.id!r}: component={{...}} is not a plain identifier (lazyComponent and expressions are not imported)")
    here = posixpath.dirname(tag.file)
    entry_dir = posixpath.dirname(entry_name)
    text = texts[tag.file]
    bindings = _imports_of(text)
    lines: list[str] = ['import {createElement} from "react";']
    notes: list[str] = []

    def import_line(local: str, spec: str, imported: str) -> str:
        if not spec.startswith("."):
            raise UpstreamRefusal(ImportErrorCode.COMPONENT_UNRESOLVED, f"{local!r} comes from the package {spec!r}, not from the project source")
        target = _resolve(here, spec, texts)
        if target is None:
            raise UpstreamRefusal(ImportErrorCode.IMPORT_UNRESOLVED, f"{tag.file}: cannot resolve {spec!r}")
        rel = _relative(entry_dir, target)
        if imported == "default":
            return f"import {local} from {json.dumps(rel)};"
        if imported == local:
            return f"import {{{local}}} from {json.dumps(rel)};"
        return f"import {{{imported} as {local}}} from {json.dumps(rel)};"

    if component in bindings:
        spec, imported = bindings[component]
        if imported == "*":
            raise UpstreamRefusal(ImportErrorCode.COMPONENT_UNRESOLVED, f"{component!r} is a namespace import, not a component")
        lines.append(import_line(component, spec, imported))
    elif re.search(rf"\bexport\s+(?:const|function|class)\s+{re.escape(component)}\b", strip_comments(text)):
        lines.append(f"import {{{component}}} from {json.dumps(_relative(entry_dir, tag.file))};")
    else:
        raise UpstreamRefusal(ImportErrorCode.COMPONENT_UNRESOLVED,
                              f"component {component!r} is neither imported nor exported by {tag.file}")
    kind, props = tag.attrs.get("defaultProps", ("", ""))
    body = "{...props}"
    if kind == "expr" and props:
        stripped = re.sub(r"""(["'`])(?:\\.|(?!\1).)*\1""", '""', props)
        local_consts = set(re.findall(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)", strip_comments(text), re.M))
        used: list[str] = []
        for ident in _IDENT.findall(stripped):
            if ident in _JS_WORDS or ident in used:
                continue
            if ident in bindings and ident != component:
                used.append(ident)
            elif ident in local_consts and not re.search(rf"[{{,]\s*{re.escape(ident)}\s*:", stripped):
                raise UpstreamRefusal(ImportErrorCode.DEFAULT_PROPS_UNRESOLVED,
                                      f"defaultProps uses {ident!r}, a constant local to {tag.file}: it cannot be carried to the generated entry")
        for ident in used:
            spec, imported = bindings[ident]
            if imported == "*":
                raise UpstreamRefusal(ImportErrorCode.DEFAULT_PROPS_UNRESOLVED, f"defaultProps uses the namespace import {ident!r}")
            if spec.startswith("."):
                lines.append(import_line(ident, spec, imported))
            elif spec in SCENE_ALLOWED_IMPORTS:
                lines.append(f"import {{{imported} as {ident}}} from {json.dumps(spec)};" if imported not in ("default", ident)
                             else (f"import {ident} from {json.dumps(spec)};" if imported == "default" else f"import {{{ident}}} from {json.dumps(spec)};"))
            else:
                lines.append(f"import {{{imported} as {ident}}} from {json.dumps(spec)};")  # refusé ensuite par l'audit des imports
        lines.append(f"const defaultProps = {props};")
        body = "{...defaultProps, ...props}"
        notes.append("defaultProps")
    lines.append("")
    lines.append(f"// Entry generated by the Jarvis importer from {origin.name}@{origin.commit[:12]}, composition {_comment_safe(tag.id)}.")
    lines.append("export default function ImportedScene(props: Record<string, unknown>) {")
    lines.append(f"  return createElement({component} as any, {body});")
    lines.append("}")
    return "\n".join(lines) + "\n", tuple(notes)


# ------------------------------------------------------------------ graphe d'imports

def _resolve(from_dir: str, spec: str, texts: Mapping[str, str]) -> str | None:
    base = posixpath.normpath(posixpath.join(from_dir, spec))
    if base.startswith("../") or base == "..":
        return None
    candidates = [base] if base.endswith(_RESOLVE_EXTENSIONS) else []
    candidates += [base + ext for ext in _RESOLVE_EXTENSIONS] + [f"{base}/index{ext}" for ext in _RESOLVE_EXTENSIONS]
    return next((c for c in candidates if c in texts), None)


def specifiers(text: str, *, comments_stripped: bool = True) -> list[str]:
    """Spécificateurs d'import du texte. `comments_stripped=False` lit le texte BRUT : un `/*` au milieu d'un texte JSX
    (`<p>/*</p>`) n'est pas un commentaire, mais ferait taire tout ce qui suit dans le texte nettoyé."""

    clean = strip_comments(text) if comments_stripped else text
    found: list[str] = []
    for pattern in (_IMPORT_FROM, _EXPORT_FROM, _REQUIRE, _DYNAMIC):
        found += [m.group(2) for m in pattern.finditer(clean)]
    return found


def _package_of(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def _reach(entry: str, modules: Mapping[str, str], archive: TarContent, base: str, budget: _Budget | None = None):
    reachable: set[str] = set()
    bare: dict[str, list[str]] = {}
    assets: set[str] = set()
    dynamic = 0
    queue = [entry]
    seen_paths = {path.removeprefix(base) for path in archive.paths if path.startswith(base)}
    while queue:
        path = queue.pop()
        if path in reachable:
            continue
        reachable.add(path)
        if budget is not None:
            budget.check()
        text = modules[path]
        clean = strip_comments(text)
        for match in _STATIC_FILE.finditer(clean):
            assets.add(match.group(2).lstrip("/"))
        dynamic += len(_STATIC_FILE_ANY.findall(clean)) - len(_STATIC_FILE.findall(clean))
        strict = specifiers(text)
        # Le texte brut ajoute les imports qu'un faux commentaire cacherait : un paquet refusé l'est même s'il n'apparaît que là
        # (prudence : un `import` en commentaire d'un paquet hors liste refuse aussi), un relatif trouvé là est suivi s'il existe.
        for spec in dict.fromkeys(strict + specifiers(text, comments_stripped=False)):
            if spec not in strict and spec.startswith("."):
                hidden = _resolve(posixpath.dirname(path), spec, modules)
                if hidden is not None:
                    queue.append(hidden)
                continue
            if spec.startswith("."):
                target = _resolve(posixpath.dirname(path), spec, modules)
                if target is not None:
                    queue.append(target)
                    continue
                joined = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
                if not joined.startswith(MODULE_ROOT):
                    raise UpstreamRefusal(ImportErrorCode.IMPORT_OUTSIDE, f"{path}: {spec!r} leaves the src/ folder")
                if joined in seen_paths:
                    raise UpstreamRefusal(ImportErrorCode.IMPORT_UNSUPPORTED,
                                          f"{path}: {spec!r} is a style or media file: the Jarvis compiler imports modules only (use staticFile)")
                raise UpstreamRefusal(ImportErrorCode.IMPORT_UNRESOLVED, f"{path}: cannot resolve {spec!r}")
            bare.setdefault(spec, []).append(path)
    return reachable, bare, assets, dynamic


def _check_dependencies(bare: Mapping[str, list[str]], package: Mapping[str, Any] | None) -> None:
    refused: list[str] = []
    declared: dict[str, Any] = {}
    for key in ("devDependencies", "dependencies"):
        section = (package or {}).get(key)
        if isinstance(section, dict):
            declared.update(section)
    for spec, where in sorted(bare.items()):
        if spec in SCENE_ALLOWED_IMPORTS:
            continue
        name = _package_of(spec)
        reason = ("not exposed by the shared Remotion tree" if name.startswith("@remotion/") else
                  "a Node built-in" if name.startswith("node:") or name in ("fs", "path", "os", "child_process", "net", "http", "https") else
                  "not part of the audited list")
        refused.append(f"{spec} ({reason}; imported by {where[0]}; declared {declared.get(name, 'nowhere')})")
    if refused:
        raise UpstreamRefusal(ImportErrorCode.DEPENDENCY_REFUSED,
                              f"the scene imports {len(refused)} package(s) outside the audited list {list(SCENE_ALLOWED_IMPORTS)}",
                              tuple(refused))


def _major(range_text: str) -> int | None:
    m = re.search(r"(\d+)", range_text)
    return int(m.group(1)) if m else None


def _dependency_map(bare: Mapping[str, list[str]], engine: EnginePin, package: Mapping[str, Any] | None, warnings: list[str]
                    ) -> list[tuple[str, str]]:
    declared = (package or {}).get("dependencies", {}) if package else {}
    declared = declared if isinstance(declared, dict) else {}
    pinned = {"react": engine.react_version, "remotion": engine.version}
    result = [("react", engine.react_version), ("remotion", engine.version)]
    for name, shipped in pinned.items():
        want = declared.get(name)
        if isinstance(want, str) and _major(want) is not None and _major(want) != _major(shipped):
            if name == "remotion":
                raise UpstreamRefusal(ImportErrorCode.REMOTION_VERSION,
                                      f"the template targets remotion {want} but the shared tree is {shipped}: another major version")
            warnings.append(f"the template declares {name} {want} but it will run on {shipped}")
    return result


def _dropped(package: Mapping[str, Any] | None, kept: set[str]) -> list[str]:
    if not package:
        return []
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = package.get(key)
        if isinstance(section, dict):
            names |= {str(name) for name in section}
    return sorted(names - kept)[:64]


def _changes(request, tag, entry_name, kept_modules, dropped_modules, assets, dropped_assets, dependencies, dropped, package, settings,
             licence_source, notes) -> list[str]:
    origin = request.origin

    def line(text: str) -> str:
        return text if len(text) <= MAX_CHANGE_CHARS else text[:MAX_CHANGE_CHARS - 1] + "~"

    out = [line(f"entry {entry_name} generated: renders {tag.id} from {tag.file}" + (" with the Root defaultProps" if notes else "")),
           line(f"composition {settings.composition_id} {settings.width}x{settings.height} {settings.fps}fps {settings.duration_in_frames}f "
                f"read from {tag.file}"),
           line(f"kept {len(kept_modules) - 2} upstream module(s) reachable from the component; dropped {dropped_modules} other src module(s)"),
           line(f"kept {len(assets)} public asset(s) named by staticFile; left {dropped_assets} other file(s)")]
    for name, shipped in dependencies:
        wanted = ((package or {}).get("dependencies", {}) or {}).get(name) if package else None
        out.append(line(f"{name}: {wanted + ' declared -> ' if wanted else ''}{shipped} from the shared tree"))
    if dropped:
        out.append(line("dependencies not shipped (never imported by the scene): " + ", ".join(dropped[:8]) + (" ..." if len(dropped) > 8 else "")))
    out.append("package.json, lockfiles, scripts and tool configs were never copied or run")
    out.append(line(f"licence {licence_source}: text kept in {LICENCE_MODULE}; Remotion's own licence recorded separately"))
    return out[:MAX_CHANGES]
