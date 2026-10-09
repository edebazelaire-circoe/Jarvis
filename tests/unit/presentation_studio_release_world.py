"""The representative fixture presentation and the counters of the release gate (jarvis-interactive-presentation-studio, Slice 22).

One fixture, many scenarios: a 12-scene quarterly review assembled by the REAL authoring door (`presentation_draft_assemble`, the very
deck the Slice 11 rig scores), with its inferred art direction, its 12-item score and five armable cues, on a real Core
(`JarvisCoreApplication` behind the real `LocalProtocolServer`) reached by the real `jarvis-presentation` tools. Nothing here is a
second implementation: it only composes the worlds of Slices 11, 12 and 21 and adds the counters a leak check needs (stage objects,
asyncio tasks, files) so a resource check compares numbers, not impressions.

`Deck` holds the ids a scenario needs. `Counters` is a snapshot to compare before and after a repeated action.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from tests.fakes import presentation_studio_fake_author as fa
from tests.unit.presentation_studio_mcp_world import World, open_world

ATTESTED = ("GET", "/api/presentation-studio/agent/turn")
#: Words of the fixture's own score and scenes: author text that must never reach a log.
DRAFT_WORDS = ("Bonjour a tous, voici la revue", "chiffre d'affaires progresse de douze pour cent", "abonnements annuels",
               "Dependance a un fournisseur unique")


@dataclass
class Deck:
    pid: str
    vid: str
    scenes: list[str]
    items: list[str]
    cues: list[str]


async def attest(world: World) -> None:
    """The Control Center attests a real addressed user turn (what lets the brain start a run)."""

    world.cc.answers[ATTESTED] = (200, {"ok": True, "addressed_user_turn": True})


async def assemble_deck(world: World, *, count: int = 12) -> Deck:
    """The serious first draft through the real planner door: gate report must be clean, the deck must be stored whole."""

    out = await world.tools.draft("assemble", brief=fa.brief("directed", duration_target_s=count * 50),
                                  draft=fa.good_deck(count))
    assert out["status"] == "delivered" and out["report"]["failures"] == [], out
    pid = out["presentation_id"]
    vid = (await world.tools.inspect("presentation", presentation_id=pid))["active_variant_id"]
    status, variant = await world.core.call("GET", f"/{pid}/variants/{vid}")
    assert status == 200 and len(variant["scenes"]) == count
    status, score = await world.core.call("GET", f"/{pid}/variants/{vid}/score")
    assert status == 200 and score["problems"] == []
    items = [i["item_id"] for i in score["score"]["items"]]
    return Deck(pid, vid, [s["scene_id"] for s in variant["scenes"]], items, [c["cue_id"] for c in score["score"]["cues"]])


async def reopen(tmp_path: Path) -> tuple[Any, World]:
    """A Core restart on the same data root: the stores are re-read, nothing is carried in memory."""

    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.runtime.presentation_studio_mcp_tools import PresentationTools
    from tests.unit.presentation_studio_mcp_world import DirectCore, FakeCC
    from tests.unit.test_presentation_studio_routes import Core

    core = Core(tmp_path)
    await core.__aenter__()
    direct = DirectCore(core.client)
    cc = FakeCC()
    root = tmp_path / "journal2"
    root.mkdir(exist_ok=True)
    tools = PresentationTools(direct, cc, journal=RuntimeJournal(root))
    return core, World(core, tools, direct.spy, cc, root, "", "")


@dataclass(frozen=True)
class Counters:
    stage_objects: int
    objects: int
    tasks: int
    store_files: int
    trace_rows: int

    @staticmethod
    async def take(core: Any) -> "Counters":
        snapshot = await core.stack.core.scene.snapshot()
        objects = list(snapshot.objects)
        root = core.stack.data_root / "presentations"
        return Counters(
            stage_objects=sum(1 for o in objects if o.object_id.startswith("studio-stage-")),
            objects=len(objects), tasks=len(asyncio.all_tasks()),
            store_files=sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0,
            trace_rows=len(core.stack.trace()))


def log_text(tmp_path: Path, world: World | None = None) -> str:
    """Everything the product wrote as a log or a trace (the Control Center trace, the tools journal, the sqlite event store, its
    WAL), never the Presentation store itself, which holds the author's content by design."""

    parts: list[str] = []
    for path in sorted(tmp_path.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(tmp_path).as_posix()
        if relative.startswith("data/presentations/") or relative.startswith("data/prefabs") or "/prefab" in relative:
            continue
        if path.suffix in (".jsonl", ".log") or "sqlite3" in path.name:
            parts.append(path.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(parts)


def decode(text: str) -> str:
    """The same text with JSON escapes undone, so an accented word cannot hide behind `\\u00e9` in a log line."""

    out = [text]
    for line in text.splitlines():
        try:
            out.append(json.dumps(json.loads(line), ensure_ascii=False))
        except ValueError:
            continue
    return "\n".join(out)


__all__ = ["ATTESTED", "Counters", "DRAFT_WORDS", "Deck", "assemble_deck", "attest", "decode", "log_text", "open_world", "reopen"]
