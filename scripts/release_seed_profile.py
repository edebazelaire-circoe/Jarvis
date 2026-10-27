#!/usr/bin/env python3
"""Profil JARVIS « d'une version précédente », jetable, pour éprouver une mise à jour (Slice 10, `docs/release.md`).

    python scripts/release_seed_profile.py seed   --home DIR --manifest FILE
    python scripts/release_seed_profile.py verify --home DIR --manifest FILE [--report FILE]

`seed` écrit sous `DIR` (la maison `…\\CIRCOE\\Jarvis` d'un `LOCALAPPDATA` SIMULÉ, jamais une vraie) :

- `data\\state\\jarvis.sqlite3` créée par le code de CE dépôt ramené à la version de schéma `STATE_FROM` (les vraies
  migrations jusque-là), avec trois Boards dont deux Présentation (un archivé d'un autre type, comme un profil réel
  d'avant l'édition Presentation) ; `data\\state\\scene.sqlite3` à la version `SCENE_FROM` ;
- `CONTEXT_GLOBAL`, une Presentation du Studio, un Artifact, une mémoire de Board, un `.env` produit : octets connus.

`verify` relit la maison APRÈS la mise à jour et le démarrage du nouveau Core : chaque fichier semé identique à
l'octet, bases montées à la version courante, sauvegardes `<base>.v<ancienne>.bak` présentes et restées à
l'ancienne version, Boards conservés (identifiant, titre, type). Il ne modifie rien (bases ouvertes en lecture seule
immuable). Code 0 : profil préservé ; 1 : écarts listés.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.adapters import sqlite_scene, sqlite_state  # noqa: E402 - après le chemin du dépôt
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository  # noqa: E402
from jarvis.adapters.sqlite_state import SQLiteStateRepository  # noqa: E402
from jarvis.adapters.sqlite_workspace_board import SQLiteBoardRepository  # noqa: E402
from jarvis.domain.workspace_board import Board, BoardKind, BoardStatus  # noqa: E402

SCHEMA = "jarvis.seeded-profile"
#: Versions « précédentes » semées : une étape de migration de chaque base au moins (v10 → v11, scène v1 → v2).
STATE_FROM = 10
SCENE_FROM = 1
SEEDED_AT = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
BOARDS = (("default", "Mes présentations", BoardKind.PRESENTATION, BoardStatus.ACTIVE),
          ("board_seed_rapport", "Rapport annuel 2026", BoardKind.PRESENTATION, BoardStatus.ACTIVE),
          ("board_seed_ancien", "Ancien espace assistant", BoardKind.ASSISTANT, BoardStatus.ARCHIVED))
FILES = {
    "data/CONTEXT_GLOBAL/profil-seme.md": "# Profil semé\n\nPréférences de l'utilisateur : ton sobre, police lisible.\n",
    "data/presentations/pres_seed/presentation.json": json.dumps(
        {"presentation_id": "pres_seed", "title": "Rapport annuel 2026", "note": "semée pour la mise à jour"}, indent=2) + "\n",
    "data/artifacts/art_seed/export.mp4": "MP4-FAKE-PAYLOAD " * 64,
    "data/boards/board_seed_rapport/memory/notes.md": "Notes du Board semé.\n",
    "config/.env": "# .env du produit semé\nJARVIS_SEED_MARKER=1\n",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _state_at(path: Path, version: int) -> None:
    saved = sqlite_state._SCHEMA_VERSION
    sqlite_state._SCHEMA_VERSION = version  # the real DDL and migrations up to `version`, as an older Core wrote them
    try:
        state = SQLiteStateRepository(path)
        await state.initialize()
        try:
            boards = SQLiteBoardRepository(state)
            for board_id, title, kind, status in BOARDS:
                await boards.save_board(Board(board_id=board_id, title=title, created_at=SEEDED_AT, updated_at=SEEDED_AT,
                                              status=status, board_kind=kind))
        finally:
            await state.close()
    finally:
        sqlite_state._SCHEMA_VERSION = saved


async def _scene_at(path: Path, version: int) -> None:
    saved = sqlite_scene._SCHEMA_VERSION
    sqlite_scene._SCHEMA_VERSION = version
    try:
        scene = SQLiteSceneRepository(path)
        await scene.initialize()
        await scene.close()
    finally:
        sqlite_scene._SCHEMA_VERSION = saved


def seed(home: Path) -> dict:
    if home.exists() and any(home.iterdir()):
        raise SystemExit(f"[seed] ÉCHEC : {home} n'est pas vide (un profil semé part toujours d'un dossier vide)")
    state_dir = home / "data" / "state"
    state_dir.mkdir(parents=True)
    asyncio.run(_state_at(state_dir / "jarvis.sqlite3", STATE_FROM))
    asyncio.run(_scene_at(state_dir / "scene.sqlite3", SCENE_FROM))
    for relative, text in FILES.items():
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return {"schema": SCHEMA, "schema_version": 1, "state_from": STATE_FROM, "scene_from": SCENE_FROM,
            "state_current": sqlite_state._SCHEMA_VERSION, "scene_current": sqlite_scene._SCHEMA_VERSION,
            "files": {relative: sha256(home / relative) for relative in FILES},
            "boards": [{"board_id": b, "title": t, "board_kind": k.value, "status": s.value} for b, t, k, s in BOARDS]}


def _read_only(path: Path) -> sqlite3.Connection:
    live = any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm"))
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro{'' if live else '&immutable=1'}", uri=True)


def _version(path: Path) -> int | None:
    conn = _read_only(path)
    try:
        return max(row[0] for row in conn.execute("SELECT version FROM schema_version"))
    finally:
        conn.close()


def verify(home: Path, manifest: dict) -> dict:
    problems: list[str] = []
    for relative, expected in manifest["files"].items():
        path = home / relative
        if not path.is_file():
            problems.append(f"{relative} disparu")
        elif sha256(path) != expected:
            problems.append(f"{relative} modifié")
    state, scene = home / "data" / "state" / "jarvis.sqlite3", home / "data" / "state" / "scene.sqlite3"
    versions = {}
    for path, old, current in ((state, manifest["state_from"], manifest["state_current"]),
                               (scene, manifest["scene_from"], manifest["scene_current"])):
        if not path.is_file():
            problems.append(f"{path.name} disparue")
            continue
        now = _version(path)
        backup = path.with_name(f"{path.name}.v{old}.bak")
        kept = _version(backup) if backup.is_file() else None
        versions[path.name] = {"now": now, "backup": backup.name if backup.is_file() else None, "backup_version": kept}
        if now != current:
            problems.append(f"{path.name} à la version {now}, attendu {current}")
        if kept != old:
            problems.append(f"{backup.name} absente ou pas à la version {old} ({kept})")
    boards = []
    if state.is_file():
        conn = _read_only(state)
        try:
            rows = {row[0]: json.loads(row[1]) for row in conn.execute("SELECT board_id, data FROM work_boards")}
        finally:
            conn.close()
        for expected in manifest["boards"]:
            found = rows.get(expected["board_id"])
            if found is None:
                problems.append(f"Board {expected['board_id']} disparu")
                continue
            got = {key: found.get(key) for key in ("board_id", "title", "board_kind", "status")}
            boards.append(got)
            if got != expected:
                problems.append(f"Board {expected['board_id']} changé : {got} au lieu de {expected}")
    return {"green": not problems, "problems": problems, "databases": versions, "boards": boards,
            "files_checked": len(manifest["files"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("seed", "verify"))
    parser.add_argument("--home", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    home, manifest_path = Path(args.home), Path(args.manifest)
    if args.action == "seed":
        manifest = seed(home)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[seed] profil semé sous {home} (jarvis.sqlite3 v{STATE_FROM}, scene.sqlite3 v{SCENE_FROM})")
        return 0
    report = verify(home, json.loads(manifest_path.read_text(encoding="utf-8")))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
