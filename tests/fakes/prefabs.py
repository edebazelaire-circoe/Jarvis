"""Fixtures de prefab partagées par les tests de la Slice 02 (domaine, magasin, service).

`tests/fixtures/prefabs/<id>/1/` : `test.counter` est valide, `test.bad_*`
sont refusés chacun pour une raison. `install_version` écrit une version
**publiée** (avec `publication.json` à la bonne empreinte) dans une racine de
test, comme le ferait le paquet ou un `publish`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jarvis.domain.prefab import (
    CreatorActor, PrefabRef, Provenance, ProvenanceOrigin, Publication, parse_bundle, prefab_class, with_version,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "prefabs"
PUBLISHED_AT = "2026-10-03T12:00:00Z"


def candidate(prefab_id: str = "test.counter", **manifest_changes: Any) -> dict[str, Any]:
    """Le candidat `{manifest, template, style, behavior}` d'une fixture, manifeste modifiable."""

    folder = FIXTURES / prefab_id / "1"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(copy.deepcopy(manifest_changes))
    return {"manifest": manifest, "template": (folder / "template.html").read_text(encoding="utf-8"),
            "style": (folder / "style.css").read_text(encoding="utf-8"),
            "behavior": (folder / "behavior.js").read_text(encoding="utf-8")}


def install_version(root: Path, prefab_id: str, version: int = 1, *, origin: ProvenanceOrigin | None = None,
                    source: dict[str, Any] | None = None, title: str | None = None) -> Publication:
    """Écrit `<root>/<prefab_id>/<version>/` publié (manifeste renommé à cet id et cette version)."""

    raw = copy.deepcopy(source or candidate())
    manifest = with_version({**raw["manifest"], "id": prefab_id}, version)
    if title is not None:
        manifest["title"] = title
    bundle = parse_bundle(manifest, raw["template"], raw["style"], raw["behavior"])
    if origin is None:
        origin = ProvenanceOrigin.BASE if prefab_class(prefab_id).value == "base" else ProvenanceOrigin.CUSTOM
    derived = None if origin in (ProvenanceOrigin.BASE, ProvenanceOrigin.CUSTOM) else PrefabRef(prefab_id, version - 1)
    actor = CreatorActor.SYSTEM if origin is ProvenanceOrigin.BASE else CreatorActor.USER
    publication = Publication(prefab_id, version, bundle.fingerprint(), PUBLISHED_AT, Provenance(origin, actor, derived))
    folder = Path(root) / prefab_id / str(version)
    folder.mkdir(parents=True)
    files = {"manifest.json": json.dumps(manifest, indent=2), "template.html": bundle.template,
             "style.css": bundle.style, "behavior.js": bundle.behavior, "publication.json": publication.render()}
    for name, text in files.items():
        (folder / name).write_bytes(text.encode("utf-8"))  # bytes: no newline translation on Windows
    return publication
