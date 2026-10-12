"""Espace de travail de Remotion Studio et publication vers une variante (handoff jarvis-remotion-native-studio-playback-fix, Slice 12).

Pur (aucune E/S). Le dossier servi par Remotion Studio (`runtime/studio/work/`) est un **espace de travail** : `src/**` et `public/**`
modifiables ; sa **base** est la version exacte matérialisée (`StudioState.pin`) et ses empreintes (`work.files.json`). Ce module
décide, à partir d'un relevé du disque fait par le runner (`WorkspaceDiff`) :

- ce qui est une modification non publiée (ajout, changement, suppression, lien) ;
- ce qui est publiable : un module `src/**` ou un asset `public/**` au chemin de source valide, pas un lien, pas un fichier de premier
  niveau (`studio-root.tsx`, `package.json` sont générés ; `remotion.config.ts` n'est pas une source) ;
- la frontière de confiance : un import « nu » hors de `SCENE_ALLOWED_IMPORTS` est refusé avant toute compilation ; aucun
  élargissement n'existe (ni route, ni réglage, ni outil : la liste est une constante) ;
- le corps exact de `POST .../studio/publish` (geste confirmé de l'utilisateur).

Contrat : `docs/remotion-studio.md` § 2 bis et `docs/presentation-studio.md` › *Remotion Studio round trip (Level 3, Slice 12)*.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jarvis.domain.remotion_compile import SCENE_ALLOWED_IMPORTS
from jarvis.domain.remotion_import import specifiers
from jarvis.domain.remotion_source import (
    ASSET_EXTENSIONS, ASSET_ROOT, MAX_MODULE_BYTES, MODULE_EXTENSIONS, MODULE_ROOT, source_path_problem,
)
from jarvis.domain.remotion_studio import PREFAB_ID, StudioError, StudioErrorCode as C, StudioPin, parse_pin

#: Champ de confirmation de la publication : ajouté par la page après la confirmation de l'utilisateur, jamais par le cerveau.
CONFIRM_FIELD = "confirm_publish"
#: Champ de `open` / `sync` qui autorise à mettre de côté des modifications non publiées (confirmation de l'utilisateur).
DISCARD_FIELD = "discard_unpublished"
#: Au plus ce nombre de chemins est nommé dans un message ou dans la vue (le compte, lui, est exact).
MAX_NAMED_PATHS = 20
_PUBLISH_KEYS = frozenset({"presentation_id", "variant_id", "scene_id", "base", CONFIRM_FIELD})
_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
WIDENING_REFUSAL = ("no trust widening exists (HV-RFX-12-01): a published scene imports only " + ", ".join(SCENE_ALLOWED_IMPORTS)
                    + "; other packages, Node built-ins, host files or network would need an explicit per-project Human approval")


@dataclass(frozen=True, slots=True)
class WorkspaceDiff:
    """Relevé du disque par le runner. `base` : empreintes de la base ; `changed` : chemin -> octets actuels (`None` = supprimé) ;
    `links` : chemins devenus des liens ou jonctions (jamais suivis, jamais lus)."""

    base: Mapping[str, str]
    changed: Mapping[str, bytes | None]
    links: tuple[str, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.changed) | set(self.links)))

    def kind(self, path: str) -> str:
        if path in self.links:
            return "link"
        if self.changed.get(path) is None:
            return "removed"
        return "changed" if path in self.base else "added"


@dataclass(frozen=True, slots=True)
class PublishPlan:
    """Ce qui part vers la porte d'édition de source (`files.sources` / `files.assets`) et ce que la confirmation affiche."""

    sources: dict[str, str | None] = field(default_factory=dict)
    assets: dict[str, str | None] = field(default_factory=dict)
    summary: dict[str, list[str]] = field(default_factory=dict)

    def files(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.sources:
            out["sources"] = dict(self.sources)
        if self.assets:
            out["assets"] = dict(self.assets)
        return out


@dataclass(frozen=True, slots=True)
class PublishRequest:
    presentation_id: str
    variant_id: str
    scene_id: str
    base: StudioPin


def _named(paths: list[str]) -> str:
    shown = ", ".join(paths[:MAX_NAMED_PATHS])
    return shown + (f" (+{len(paths) - MAX_NAMED_PATHS})" if len(paths) > MAX_NAMED_PATHS else "")


def summary_of(diff: WorkspaceDiff) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"added": [], "changed": [], "removed": [], "link": []}
    for path in diff.paths:
        out[diff.kind(path)].append(path)
    return out


def plan_publish(diff: WorkspaceDiff) -> PublishPlan:
    """Ce qui est publiable, ou un refus typé qui nomme les chemins (rien n'est publié tant qu'un seul fichier est refusé)."""

    paths = diff.paths
    if not paths:
        raise StudioError(C.PUBLISH_NOTHING, "the Remotion Studio workspace holds no unpublished change")
    links = [path for path in paths if path in diff.links]
    if links:
        raise StudioError(C.PUBLISH_INVALID_FILE, f"links or junctions are never published (their target is not read): {_named(links)}")
    top = [path for path in paths if not path.startswith((MODULE_ROOT, ASSET_ROOT))]
    if top:
        raise StudioError(C.PUBLISH_INVALID_FILE, f"only src/** and public/** are a scene source; generated or extra top-level files are not "
                                                  f"published (studio-root.tsx and package.json are generated from the manifest): {_named(top)}")
    sources: dict[str, str | None] = {}
    assets: dict[str, str | None] = {}
    bad: list[str] = []
    for path in paths:
        module = path.startswith(MODULE_ROOT)
        problem = source_path_problem(path, root=MODULE_ROOT if module else ASSET_ROOT,
                                      extensions=MODULE_EXTENSIONS if module else ASSET_EXTENSIONS)
        data = diff.changed.get(path)
        if problem and data is not None:
            bad.append(f"{path[:120]} ({problem})")
            continue
        if module:
            if data is None:
                sources[path] = None
                continue
            if len(data) > MAX_MODULE_BYTES:
                bad.append(f"{path} (larger than {MAX_MODULE_BYTES} bytes)")
                continue
            try:
                sources[path] = data.decode("utf-8")
            except UnicodeDecodeError:
                bad.append(f"{path} (not UTF-8 text)")
        else:
            assets[path] = None if data is None else base64.b64encode(data).decode("ascii")
    if bad:
        raise StudioError(C.PUBLISH_INVALID_FILE, f"these workspace files cannot be part of a scene source: {_named(bad)}")
    refused = refused_imports(sources)
    if refused:
        raise StudioError(C.PUBLISH_IMPORT_REFUSED, f"{WIDENING_REFUSAL}; refused: {_named(refused)}",
                          extra={"imports": refused[:MAX_NAMED_PATHS]})
    return PublishPlan(sources, assets, summary_of(diff))


def refused_imports(sources: Mapping[str, str | None]) -> list[str]:
    """`"<spécificateur> (<fichier>)"` pour chaque import nu hors de la liste ; la compilation reste l'autorité finale."""

    out: list[str] = []
    for path, text in sorted(sources.items()):
        if text is None:
            continue
        for spec in specifiers(text):
            if spec.startswith(".") or spec in SCENE_ALLOWED_IMPORTS:
                continue
            item = f"{spec[:80]} ({path})"
            if item not in out:
                out.append(item)
    return out


def _ident(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not set(value) <= _ID_CHARS:
        raise StudioError(C.INVALID, f"{key} must be a plain identifier")
    return value


def parse_publish(raw: object) -> PublishRequest:
    """Corps exact de `publish` : la cible (présentation, variante, scène), la base que la page a vue, et la confirmation."""

    if not isinstance(raw, Mapping) or set(raw) != _PUBLISH_KEYS:
        raise StudioError(C.INVALID, "the body must be exactly {presentation_id, variant_id, scene_id, base: {prefab_id, version}, "
                                     f"{CONFIRM_FIELD}: true}}")
    if raw.get(CONFIRM_FIELD) is not True:
        raise StudioError(C.PUBLISH_CONFIRM_REQUIRED, "publishing writes a new version into the variant: send "
                                                      f"{CONFIRM_FIELD}: true after the user confirmed")
    base = parse_pin(raw.get("base"))
    return PublishRequest(_ident(raw, "presentation_id"), _ident(raw, "variant_id"), _ident(raw, "scene_id"), base)


def split_discard(raw: object) -> tuple[dict[str, Any], bool]:
    """Retire `discard_unpublished` d'un corps de `open` / `sync` ; seule la valeur `true` compte (rien d'implicite)."""

    if not isinstance(raw, Mapping):
        return raw, False  # type: ignore[return-value]
    body = {key: value for key, value in raw.items() if key != DISCARD_FIELD}
    if DISCARD_FIELD in raw and raw[DISCARD_FIELD] is not True:
        raise StudioError(C.INVALID, f"{DISCARD_FIELD} must be true when present")
    return body, raw.get(DISCARD_FIELD) is True


__all__ = ["CONFIRM_FIELD", "DISCARD_FIELD", "PREFAB_ID", "PublishPlan", "PublishRequest", "WIDENING_REFUSAL", "WorkspaceDiff",
           "parse_publish", "plan_publish", "refused_imports", "split_discard", "summary_of"]
