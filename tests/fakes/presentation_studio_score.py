"""Données déterministes de la partition (Slice 10) : 12 scènes, une partition mixte utilisateur/Jarvis/silence
avec une séquence verrouillée, et des fixtures négatives. Mêmes appels -> mêmes documents, octet pour octet.

`python -m tests.fakes.presentation_studio_score` réécrit `tests/fixtures/presentation_studio/score.full12.json`.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from jarvis.domain.prefab import PrefabRef, canonical_json
from jarvis.domain.presentation_studio import PRESENTATION_ID  # noqa: F401 - documents the id shape used below
from jarvis.domain.presentation_studio_scene import ControlBounds, ScoreAnchor, StudioControl, StudioScene
from jarvis.domain.presentation_studio_score import Score, parse_score

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio" / "score.full12.json"
PRESENTATION = "pst_" + "a" * 32
VARIANT = "psv_" + "b" * 32
SCORE_ID = "psr_000000000001"
STAMP = "2026-10-07T12:00:00.000000Z"


def scene_id(n: int) -> str:
    return f"pss_{n:012x}"


def item_id(n: int) -> str:
    return f"psi_{n:012x}"


def cue_id(n: int) -> str:
    return f"psc_{n:012x}"


def scenes() -> tuple[StudioScene, ...]:
    """12 scènes : chacune déclare `title_text` (content), `accent` (visual), `glow` (motion, borné 0..10), ancres `callout`, `chart`."""

    out = []
    for n in range(1, 13):
        out.append(StudioScene(
            scene_id(n), PrefabRef("jarvis.window", 1), title=f"Scene {n}", section=f"part{(n - 1) // 4 + 1}",
            props={"title": f"Scene {n}", "accent": "#112233", "glow": 3},
            controls=(StudioControl("title_text", "props.title", "Title", "content"),
                      StudioControl("accent", "props.accent", "Accent", "visual"),
                      StudioControl("glow", "props.glow", "Glow", "motion", bounds=ControlBounds(min=0, max=10))),
            anchors=(ScoreAnchor("callout", "Callout"), ScoreAnchor("chart", "Chart", "accent"))))
    return tuple(out)


def _act(kind: str, n: int, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "scene_id": scene_id(n), **extra}


def content() -> dict[str, Any]:
    items: list[dict[str, Any]] = [
        {"item_id": item_id(1), "scene_id": scene_id(1), "presenter": "jarvis", "kind": "speech", "label": "Opening",
         "text": "Bonjour, voici le plan de la presentation.", "visual": [_act("scene_goto", 1)],
         "target_duration_ms": 8000, "next_item_id": item_id(2)},
        {"item_id": item_id(2), "scene_id": scene_id(2), "presenter": "user", "kind": "speech",
         "note": "Explain the context in my own words", "cue_id": cue_id(1),
         "visual": [_act("scene_goto", 2), _act("reveal", 2, anchor_id="callout")], "next_item_id": item_id(3)},
        {"item_id": item_id(3), "scene_id": scene_id(3), "presenter": "none", "kind": "silence", "label": "Let it breathe",
         "motion": [_act("control_set", 3, control_id="glow", value=8)], "target_duration_ms": 4000,
         "next_item_id": item_id(4)},
        {"item_id": item_id(4), "scene_id": scene_id(4), "presenter": "jarvis", "kind": "speech",
         "note": "Summarise the three figures", "cue_id": cue_id(2), "visual": [_act("scene_goto", 4)],
         "recovery": "restart_item", "next_item_id": item_id(5)},
        {"item_id": item_id(5), "scene_id": scene_id(5), "presenter": "user", "kind": "speech",
         "text": "Voila le fond du sujet.", "visual": [_act("reveal", 5, anchor_id="chart")],
         "next_item_id": item_id(6)},
        {"item_id": item_id(6), "scene_id": scene_id(6), "presenter": "jarvis", "kind": "speech",
         "label": "Locked demo", "visual": [{"kind": "sequence", "sequence_id": "demo"}], "timing": "locked",
         "interruption": "at_boundary", "target_duration_ms": 9000, "recovery": "recovery_point",
         "recovery_point_id": "demo_start", "next_item_id": item_id(7)},
        {"item_id": item_id(7), "scene_id": scene_id(7), "presenter": "none", "kind": "silence",
         "next_item_id": item_id(8)},
        {"item_id": item_id(8), "scene_id": scene_id(8), "presenter": "user", "kind": "speech",
         "note": "Walk the audience through the result", "cue_id": cue_id(3),
         "visual": [_act("control_set", 8, control_id="accent", value="#ff8800")], "next_item_id": item_id(9)},
        {"item_id": item_id(9), "scene_id": scene_id(9), "presenter": "jarvis", "kind": "speech",
         "text": "Encore une fois, regardez bien.", "loop": {"to_item_id": item_id(8), "max_repeats": 1},
         "next_item_id": item_id(10)},
        {"item_id": item_id(10), "scene_id": scene_id(10), "presenter": "user", "kind": "speech",
         "note": "Questions", "recovery": "recovery_point", "recovery_point_id": "opening",
         "next_item_id": item_id(11)},
        {"item_id": item_id(11), "scene_id": scene_id(11), "presenter": "jarvis", "kind": "speech",
         "text": "Merci de votre attention.", "next_item_id": item_id(12)},
        {"item_id": item_id(12), "scene_id": scene_id(12), "presenter": "none", "kind": "silence",
         "label": "End", "next_item_id": None},
    ]
    return {
        "start_item_id": item_id(1), "items": items,
        "cues": [
            {"cue_id": cue_id(1), "label": "Context done", "armable": True,
             "predicate": {"phrases": ["Next the context", "passons au contexte"], "semantics": ["topic_context"]}},
            {"cue_id": cue_id(2), "label": "Manual advance", "armable": False},
            {"cue_id": cue_id(3), "label": "Result", "armable": True, "predicate": {"phrases": ["le résultat"]}},
        ],
        "sequences": [{
            "sequence_id": "demo", "label": "Demo choreography", "duration_ms": 9000,
            "on_interrupt": "pause_resume",
            "steps": [
                {"step_id": "intro", "offset_ms": 0, "speaker": "jarvis", "text": "Regardez la courbe monter.",
                 "visual": [_act("reveal", 6, anchor_id="chart")]},
                {"step_id": "glow_up", "offset_ms": 3000, "motion": [_act("control_set", 6, control_id="glow", value=9)]},
                {"step_id": "wrap", "offset_ms": 6500, "speaker": "jarvis", "text": "Et voila.",
                 "visual": [_act("hide", 6, anchor_id="callout")]},
            ]}],
        "recovery_points": [{"recovery_id": "opening", "label": "Back to the opening", "item_id": item_id(1)},
                            {"recovery_id": "demo_start", "label": "Demo start", "item_id": item_id(6)}],
    }


def document(**changes: Any) -> dict[str, Any]:
    base = {"schema": "jarvis.presentation_studio.score", "schema_version": 1, "score_id": SCORE_ID,
            "presentation_id": PRESENTATION, "variant_id": VARIANT, **content(), "revision": 1,
            "created_at": STAMP, "updated_at": STAMP}
    return {**base, **changes}


def score() -> Score:
    return parse_score(document())


def mutated(path: list[Any], value: Any) -> dict[str, Any]:
    """Copie profonde du document avec `value` posé à `path` (négatifs : une seule altération par fixture)."""

    doc = copy.deepcopy(document())
    node: Any = doc
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return doc


def write_fixture() -> None:
    from jarvis.domain.presentation_studio import dump_document

    FIXTURE.write_text(dump_document(score().to_document()), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write_fixture()
    print(canonical_json(score().to_document())[:80])
