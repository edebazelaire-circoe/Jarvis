#!/usr/bin/env python3
"""Publie et verrouille les prefabs de base livrés (`jarvis/prefabs/base/`).

Handoff jarvis-scene-window-prefab-foundation, Slice 05 ; contrat
`docs/prefabs.md` › *Storage and library* et *Base catalogue*.

Une version de base livrée porte un `publication.json` (origine `base`,
acteur `system`) et une entrée de `catalog.lock.json` à son empreinte. Les deux
sont calculés ici par le domaine (`parse_bundle(...).fingerprint()`, la même
fonction que Core relit au chargement), jamais à la main :

    python -m scripts.lock_base_prefabs            # écrit ce qui manque
    python -m scripts.lock_base_prefabs --check    # n'écrit rien, code 1 si quelque chose manque

Règles (motif du Test Lab) : une version déjà publiée ou verrouillée n'est
jamais réécrite. Si ses fichiers ont changé, le script refuse (« publish a new
version ») au lieu de remettre l'empreinte à jour ; une entrée du verrou sans
dossier (orpheline) est refusée aussi. Les fichiers sont lus en octets : un
CR rendrait l'empreinte dépendante du poste (`.gitattributes` garde LF).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.domain.prefab import (  # noqa: E402  (racine du dépôt ajoutée juste au-dessus)
    MAX_MANIFEST_BYTES, CatalogLock, CreatorActor, LockEntry, PrefabDefinitionError, Provenance, ProvenanceOrigin,
    Publication, decode_json_text, format_published_at, parse_bundle,
)

PACKAGE = ROOT / "jarvis" / "prefabs" / "base"
SOURCES = ("manifest.json", "template.html", "style.css", "behavior.js")


class LockError(RuntimeError):
    """Écart que le script refuse de réparer : il faut une nouvelle version, pas une réécriture."""


def _read(folder: Path, name: str) -> str:
    raw = (folder / name).read_bytes()
    if b"\r" in raw:
        raise LockError(f"{folder.parent.name}/{folder.name}/{name} contains CR; base prefab files are LF")
    return raw.decode("utf-8")


def fingerprint_of(folder: Path) -> str:
    """Empreinte du paquet `{manifest, template, style, behavior}` d'un dossier `<id>/<version>/`."""

    texts = {name: _read(folder, name) for name in SOURCES}
    try:
        bundle = parse_bundle(decode_json_text(texts["manifest.json"], MAX_MANIFEST_BYTES, "manifest"),
                              texts["template.html"], texts["style.css"], texts["behavior.js"])
    except PrefabDefinitionError as exc:
        raise LockError(f"{folder.parent.name}@{folder.name} is invalid: " + "; ".join(exc.errors)) from None
    if (bundle.manifest.prefab_id, bundle.manifest.version) != (folder.parent.name, int(folder.name)):
        raise LockError(f"{folder.parent.name}/{folder.name}: manifest names "
                        f"{bundle.manifest.prefab_id}@{bundle.manifest.version}")
    return bundle.fingerprint()


def shipped_versions(package: Path) -> list[Path]:
    return sorted((folder for folder in package.glob("jarvis.*/*") if folder.is_dir() and folder.name.isdigit()),
                  key=lambda folder: (folder.parent.name, int(folder.name)))


def plan(package: Path, published_at: str) -> tuple[dict[Path, str], CatalogLock]:
    """`({chemin: texte à écrire}, verrou complet)` ; lève `LockError` sur tout écart non réparable."""

    lock_path = package / "catalog.lock.json"
    lock = CatalogLock.decode_text(lock_path.read_text(encoding="utf-8"))
    index = lock.index
    writes: dict[Path, str] = {}
    entries = list(lock.entries)
    seen: set[tuple[str, int]] = set()
    for folder in shipped_versions(package):
        key = (folder.parent.name, int(folder.name))
        seen.add(key)
        digest = fingerprint_of(folder)
        publication_path = folder / "publication.json"
        if publication_path.exists():
            publication = Publication.decode_text(publication_path.read_text(encoding="utf-8"))
            if publication.fingerprint != digest:
                raise LockError(f"{key[0]}@{key[1]} was edited after publication; publish a new version")
            if publication.provenance.origin is not ProvenanceOrigin.BASE:
                raise LockError(f"{key[0]}@{key[1]} ships a non-base publication")
        else:
            publication = Publication(key[0], key[1], digest, published_at,
                                      Provenance(ProvenanceOrigin.BASE, CreatorActor.SYSTEM))
            writes[publication_path] = publication.render()
        entry = index.get(key)
        if entry is None:
            entries.append(LockEntry(key[0], key[1], digest))
        elif entry.fingerprint != digest:
            raise LockError(f"{key[0]}@{key[1]} differs from catalog.lock.json; publish a new version")
    orphans = sorted(set(index) - seen)
    if orphans:
        raise LockError(f"catalog.lock.json locks versions with no folder: {orphans}")
    full = CatalogLock(tuple(entries))
    if full.render() != lock_path.read_text(encoding="utf-8").replace("\r\n", "\n"):
        writes[lock_path] = full.render()
    return writes, full


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 when something is missing")
    parser.add_argument("--published-at", default=None, help="YYYY-MM-DDTHH:MM:SSZ for new publications (now)")
    args = parser.parse_args(argv)
    published_at = args.published_at or format_published_at(datetime.now(timezone.utc))
    try:
        writes, lock = plan(PACKAGE, published_at)
    except (LockError, PrefabDefinitionError, OSError, json.JSONDecodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for path in writes:
        print(("missing: " if args.check else "wrote: ") + str(path.relative_to(ROOT)).replace("\\", "/"))
    if args.check:
        return 1 if writes else 0
    for path, text in writes.items():
        path.write_bytes(text.encode("utf-8"))  # octets : pas de CRLF sous Windows
    print(f"{len(lock.entries)} base version(s) locked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
