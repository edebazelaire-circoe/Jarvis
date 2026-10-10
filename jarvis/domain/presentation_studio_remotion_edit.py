"""Edition de source d'une scene REMOTION : vocabulaire et regles pures (handoff jarvis-remotion-presentation-integration, Slice 14).

Le chemin d'edition de source du Studio (`presentation_studio_reload`) sait publier une revision immuable du prefab d'une scene,
epingler ce pin et patcher la fenetre stage. Ce module n'ajoute que ce qui change quand la source est du TSX :

- `parse_remotion_edit` : les clefs `sources` (`{chemin: texte | null}`, `null` supprime) et `assets` (`{chemin: base64 | null}`) du
  corps `files` ; bornes de forme seulement (les regles de chemin, les gardes d'isolation et les bornes de contenu sont celles de
  `parse_candidate`, jamais recopiees ici) ;
- `compose_remotion_candidate` : le candidat `{manifest, sources, assets}` = la source du pin (ou de la version restauree) + les
  changements demandes. Les listes `source.modules` / `source.assets` du manifeste sont **recalculees par Core** a partir des fichiers
  (l'agent n'a pas a les tenir) ; tout le reste du bloc (moteur, entree, composition) est celui du pin, sauf si l'agent envoie un
  manifeste ;
- `format_diagnostics` : `fichier:ligne:colonne texte`, la forme qu'un agent ou une bande d'erreur sait lire.

Aucune E/S. Le garde de compilation (esbuild, processus gere de la capacite Remotion) est dans le service Core.
"""

from __future__ import annotations

import base64
import binascii
import copy
from collections.abc import Iterable, Mapping
from typing import Any

from jarvis.domain.presentation_studio_checks import _fail
from jarvis.domain.remotion_source import (
    MAX_ASSETS, MAX_MODULE_BYTES, MAX_MODULES, MAX_MODULES_TOTAL_BYTES, MAX_PATH_CHARS,
)

#: Clefs du corps `files` propres aux scenes Remotion (les clefs HTML sont `template`, `style`, `behavior`).
REMOTION_KEYS = ("sources", "assets")
#: Un seul fichier du corps : revenir a une version du pin de la scene (annuler / retablir).
RESTORE_KEY = "restore_version"
#: Octets d'assets (base64, caracteres) qu'UNE edition peut porter : la porte d'edition n'est pas le chemin des gros assets
#: (`docs/remotion-source.md` § 2 : les gros assets passent par la publication interne du Studio).
MAX_EDIT_ASSETS_B64 = 2 * 1024 * 1024
#: Plafond du corps de la route Core (modules JSON-echappes + assets base64 + marge).
MAX_REMOTION_BODY_BYTES = 2 * MAX_MODULES_TOTAL_BYTES + MAX_EDIT_ASSETS_B64 + 64 * 1024
MAX_SHOWN_DIAGNOSTICS = 3


def _mapping(name: str, value: object, limit: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"files.{name} must be an object {{path: ...}}")
    if len(value) > limit:
        raise _fail(f"files.{name} names {len(value)} paths, at most {limit}")
    for path in value:
        if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS:
            raise _fail(f"files.{name}: a path must be a non-empty string of at most {MAX_PATH_CHARS} characters")
    return dict(value)


def parse_remotion_edit(sources: object | None, assets: object | None) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """`(sources, assets)` normalises. Une valeur `None` supprime le fichier. Ne regarde ni les chemins (regles lexicales du
    candidat) ni le contenu des assets : seulement la forme et les plafonds de taille d'une requete."""

    modules: dict[str, str | None] = {}
    if sources is not None:
        modules = _mapping("sources", sources, MAX_MODULES)
        total = 0
        for path, text in modules.items():
            if text is None:
                continue
            if not isinstance(text, str):
                raise _fail(f"files.sources[{path[:60]!r}] must be a string (the module text) or null (delete the module)")
            size = len(text.encode("utf-8", errors="surrogatepass"))
            if size > MAX_MODULE_BYTES:
                raise _fail(f"files.sources[{path[:60]!r}] is {size} bytes, at most {MAX_MODULE_BYTES}")
            total += size
        if total > MAX_MODULES_TOTAL_BYTES:
            raise _fail(f"files.sources carries {total} bytes, at most {MAX_MODULES_TOTAL_BYTES}")
    files: dict[str, str | None] = {}
    if assets is not None:
        files = _mapping("assets", assets, MAX_ASSETS)
        total = 0
        for path, encoded in files.items():
            if encoded is None:
                continue
            if not isinstance(encoded, str):
                raise _fail(f"files.assets[{path[:60]!r}] must be base64 text or null (delete the asset)")
            total += len(encoded)
        if total > MAX_EDIT_ASSETS_B64:
            raise _fail(f"files.assets carries {total} base64 characters, at most {MAX_EDIT_ASSETS_B64} "
                        "(large assets do not travel through a source edit)")
    return modules, files


def compose_remotion_candidate(base_manifest: Mapping[str, Any], base_files: Mapping[str, bytes], *,
                               sources: Mapping[str, str | None], assets: Mapping[str, str | None],
                               manifest: Mapping[str, Any] | None, prefab_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """`(candidat, problemes)`. Un probleme (suppression d'un fichier absent, base64 invalide) rend `(None, [...])` : rien n'est
    devine. Le numero de version du manifeste est celui de Core a la publication, jamais celui du candidat."""

    block = base_manifest.get("source")
    if not isinstance(block, Mapping):
        return None, ["the scene's current version has no Remotion source block"]
    modules = set(block.get("modules") or ())
    declared_assets = set(block.get("assets") or ())
    files: dict[str, bytes] = dict(base_files)
    problems: list[str] = []
    for path, text in sources.items():
        if text is None:
            if path in modules:
                modules.discard(path)
                files.pop(path, None)
            else:
                problems.append(f"{path}: cannot delete a module the scene does not have")
        else:
            modules.add(path)
            files[path] = text.encode("utf-8", errors="surrogatepass")
    for path, encoded in assets.items():
        if encoded is None:
            if path in declared_assets:
                declared_assets.discard(path)
                files.pop(path, None)
            else:
                problems.append(f"{path}: cannot delete an asset the scene does not have")
            continue
        try:
            files[path] = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            problems.append(f"{path}: asset content must be base64 text")
            continue
        declared_assets.add(path)
    if problems:
        return None, problems[:5]
    merged = copy.deepcopy(dict(manifest if manifest is not None else base_manifest))
    new_block = dict(merged.get("source") if isinstance(merged.get("source"), Mapping) else block)
    new_block["modules"], new_block["assets"] = sorted(modules), sorted(declared_assets)
    merged["source"] = new_block
    merged["id"] = prefab_id
    merged.setdefault("version", base_manifest.get("version", 1))
    return {"manifest": merged,
            "sources": {path: files[path].decode("utf-8", errors="surrogatepass") for path in sorted(modules) if path in files},
            "assets": {path: base64.b64encode(files[path]).decode("ascii") for path in sorted(declared_assets) if path in files}}, []


def candidate_files(candidate: Mapping[str, Any]) -> dict[str, bytes]:
    """Les fichiers (octets) d'un candidat Remotion deja compose : la base du retouche suivante d'une rafale."""

    files = {path: text.encode("utf-8", errors="surrogatepass") for path, text in candidate["sources"].items()}
    files.update({path: base64.b64decode(encoded) for path, encoded in candidate["assets"].items()})
    return files


def format_diagnostics(diagnostics: Iterable[Mapping[str, Any]], *, limit: int = MAX_SHOWN_DIAGNOSTICS) -> str:
    """`src/Scene.tsx:12:5 Expected ";"...` : au plus `limit` constats, separes par ` | `."""

    rows = list(diagnostics)
    shown = [f"{row.get('file')}:{row.get('line')}:{row.get('column')} {row.get('text')}" for row in rows[:limit]]
    more = f" (+{len(rows) - limit} more)" if len(rows) > limit else ""
    return " | ".join(shown) + more


__all__ = ["MAX_EDIT_ASSETS_B64", "MAX_REMOTION_BODY_BYTES", "REMOTION_KEYS", "RESTORE_KEY",
           "candidate_files", "compose_remotion_candidate", "format_diagnostics", "parse_remotion_edit"]
