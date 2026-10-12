"""Native authoring (handoff jarvis-remotion-native-studio-playback-fix, Slice 13): normal editable Remotion code is a creation path.

`brief.authoring: "native"`: the agent writes React/TSX as in any Remotion project (text and colours in the source, its own modules, no
props, no score, no roles, no art direction) and the deck is delivered; only validity and safety block (`NATIVE_BLOCKING`). The guided
path (the default) is unchanged. Proven without a model and without Node (`ScriptedCompiler`), like the other planner tests.
"""

from __future__ import annotations

import pytest

from jarvis.domain.presentation_studio_authoring import Authoring, SceneRole, native_role, parse_brief, parse_draft
from jarvis.domain.presentation_studio_authoring_gate import ERROR, NATIVE_BLOCKING, OFF, RULES, WARNING
from jarvis.domain.presentation_studio_authoring import Workflow
from jarvis.domain.presentation_studio_checks import PresentationStudioError
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv
from tests.fakes.remotion_authoring import BROKEN_MARKER, engine_pin

#: What a Claude agent writes in a plain Remotion project: literal French text, literal colours, no props, its own helper module.
NATIVE_TSX = """import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {Title} from "./lib/Title";

export default function Scene() {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 200}});
  const glow = interpolate(frame, [0, 60], [0, 1], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{background: "#05070d", color: "#f4f6fb", justifyContent: "center", padding: 120}}>
      <Title text="Un assistant vocal qui reste sur votre poste" progress={enter} />
      <div style={{color: "#7cf0c4", opacity: glow, fontSize: 42}}>Appuyez, parlez, il agit.</div>
      <div style={{borderTop: "2px solid #1d2433", marginTop: 40}} />
    </AbsoluteFill>
  );
}
"""
TITLE_TSX = """import React from "react";

export const Title: React.FC<{text: string; progress: number}> = ({text, progress}) => (
  <h1 style={{fontSize: 96, margin: 0, transform: `translateY(${(1 - progress) * 40}px)`, opacity: progress}}>{text}</h1>
);
"""


def native_bundle(key: str, *, tsx: str = NATIVE_TSX, frames: int = 300) -> dict:
    return {"key": key, "remotion": {"title": f"Scène {key}", "composition": {"width": 1920, "height": 1080, "fps": 30,
                                                                               "duration_in_frames": frames},
                                     "files": {"src/Scene.tsx": tsx, "src/lib/Title.tsx": TITLE_TSX}}}


def native_request(count: int = 3, **brief_extra) -> tuple[dict, dict]:
    brief = {"title": "JARVIS en quelques scènes", "workflow": "directed", "authoring": "native", "language": "fr", **brief_extra}
    draft = {"prefabs": [native_bundle(f"s{i}", frames=240 + 30 * i) for i in range(count)],
             "scenes": [{"key": f"s{i}", "title": f"Scène {i + 1}", "prefab": {"bundle": f"s{i}"}} for i in range(count)]}
    return brief, draft


@pytest.fixture
async def env(tmp_path):
    return await AuthoringEnv(tmp_path / "e").start()


def codes(report: dict, key: str) -> set[str]:
    return {f["code"] for f in report[key]}


# ------------------------------------------------------------------ the rule table


def test_native_keeps_only_validity_and_safety_blocking_and_reports_the_rest():
    for rule in RULES:
        for workflow in (Workflow.DIRECTED, Workflow.ONE_SHOT):
            base, native = rule.level(workflow), rule.level(workflow, native=True)
            if base == OFF:
                assert native == OFF, rule.code                       # native never switches a rule ON
            elif rule.code in NATIVE_BLOCKING:
                assert native == base, rule.code
            else:
                assert native == WARNING, rule.code
    creative = {"tsx_text_hardcoded", "tsx_color_hardcoded", "tsx_theme_unread", "tsx_props_unread", "tsx_monolith", "content_thin",
                "text_density", "cue_weak", "controls_too_many", "notes_missing", "must_cover_missing", "duration_off", "arc_incomplete",
                "scene_unbound", "transition_missing", "da_missing", "contrast_low", "placeholder_text"}
    assert not creative & NATIVE_BLOCKING
    assert {"tsx_compile", "prefab_invalid", "behavior_risky", "tsx_live_ref_unresolved", "draft_schema"} <= NATIVE_BLOCKING
    assert all(rule.level(Workflow.DIRECTED, native=True) in (ERROR, WARNING, OFF) for rule in RULES)


# ------------------------------------------------------------------ the brief and the draft


def test_the_brief_says_native_explicitly_and_a_guided_brief_keeps_its_digest():
    native = parse_brief({"title": "T", "workflow": "directed", "authoring": "native"})
    assert native.native and native.authoring is Authoring.NATIVE and native.speech.value == "none"   # a native deck is silent by default
    guided = parse_brief({"title": "T", "workflow": "directed"})
    assert not guided.native and "authoring" not in guided.to_dict() and native.to_dict()["authoring"] == "native"
    with pytest.raises(PresentationStudioError, match="exploratory"):
        parse_brief({"title": "T", "workflow": "exploratory", "authoring": "native"})
    with pytest.raises(PresentationStudioError):
        parse_brief({"title": "T", "workflow": "directed", "authoring": "free"})


def test_a_native_draft_needs_no_score_no_role_no_art_direction():
    brief, draft = native_request(3)
    parsed = parse_draft(draft, parse_brief(brief), engine_pin())
    assert parsed.draft is not None, [p.message for p in parsed.problems]
    roles = [s.role for s in parsed.draft.scenes]
    assert roles == [SceneRole.OPENING, SceneRole.BODY, SceneRole.CLOSING]
    items = parsed.draft.items
    assert [i.scene for i in items] == ["s0", "s1", "s2"] and all(i.presenter.value == "none" and not i.text and not i.note for i in items)
    assert [i.target_duration_ms for i in items] == [8000, 9000, 10000]               # the declared compositions, in milliseconds
    assert parsed.draft.directions[0].profile is not None                            # a generated fallback direction
    assert native_role(0, 1) is SceneRole.SINGLE


def test_the_same_draft_without_native_is_refused_by_the_guided_schema():
    brief, draft = native_request(2)
    brief.pop("authoring")
    parsed = parse_draft(draft, parse_brief(brief), engine_pin())
    assert parsed.draft is None and any("score" in p.message or "role" in p.message for p in parsed.problems)


# ------------------------------------------------------------------ assembly


async def test_native_code_is_delivered_with_its_creative_findings_as_warnings(env):
    brief, draft = native_request(3)
    out = await env.assemble(brief, draft)
    body = out.to_dict()
    assert out.status == "delivered", body.get("report", {}).get("failures")
    warned = codes(body["report"], "warnings")
    assert {"tsx_text_hardcoded", "tsx_color_hardcoded", "tsx_theme_unread"} <= warned, warned
    assert not body["report"]["failures"]
    assert len(body["scenes"]) == 3 and body["engine"] == "remotion"
    variant = await env.studio.get_variant(body["presentation_id"], body["active_variant_id"])
    score = (await env.studio.get_score(body["presentation_id"], variant.variant_id))["score"]
    assert [item["presenter"] for item in score["items"]] == ["none"] * 3


async def test_a_native_scene_that_does_not_compile_is_still_refused_and_nothing_is_written(env):
    brief, draft = native_request(2)
    draft["prefabs"][1]["remotion"]["files"]["src/Scene.tsx"] = NATIVE_TSX.replace("const frame", BROKEN_MARKER + "\n  const frame")
    out = await env.assemble(brief, draft)
    body = out.to_dict()
    assert out.status == "refused" and "tsx_compile" in codes(body["report"], "failures")
    assert env.folders() == []


async def test_a_risky_native_scene_is_refused_before_anything_is_written(env):
    brief, draft = native_request(1)
    risky = NATIVE_TSX.replace("const frame = useCurrentFrame();", "const frame = useCurrentFrame(); fetch('https://example.com/x');")
    draft["prefabs"][0]["remotion"]["files"]["src/Scene.tsx"] = risky
    out = await env.assemble(brief, draft)
    failures = codes(out.to_dict()["report"], "failures")
    assert out.status == "refused" and failures & {"behavior_risky", "prefab_invalid"}, failures


async def test_the_native_guide_example_is_delivered_as_it_is(env):
    from jarvis.domain.presentation_studio_authoring_guide import NATIVE_LOOP, draft_guide

    guide = draft_guide("native")
    assert guide["loop"] == NATIVE_LOOP and guide["brief"]["authoring"] == "native" and "presentation_source" in NATIVE_LOOP
    out = await env.assemble(guide["example"]["brief"], guide["example"]["draft"])
    assert out.status == "delivered", out.to_dict().get("report", {}).get("failures")


def test_the_native_guide_offers_only_brief_keys_a_native_deck_uses():
    from jarvis.domain.presentation_studio_authoring import _BRIEF_OPTIONAL
    from jarvis.domain.presentation_studio_authoring_guide import draft_guide

    offered = set(draft_guide("native")["brief"]["optional"])
    assert offered <= _BRIEF_OPTIONAL and "strict_content" not in offered, "a real run was refused once for strict_content (Slice 13 trace)"
