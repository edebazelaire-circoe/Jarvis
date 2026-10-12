"""Cycle de vie du Player et transport de Variantes dans un VRAI Chrome (handoff jarvis-remotion-native-studio-playback-fix, Slice 06).

VRAI Core, VRAI Control Center, VRAI Player Remotion, sur des ports libres et une racine jetable (`RemotionStack`), jamais le Jarvis
vivant. La présentation de 9 scènes de la porte de la Slice 03 (`presentation_playback_gate_world.DECK` : 3 s, 8 s et 30 s, de 24 à
60 i/s), la même sonde de page. Opt-in : `JARVIS_REMOTION_RUNTIME_DIR`, Node et Chrome ; sinon ignoré. Les contrôles sont trouvés par
leur rôle et leur nom du contrat (barre d'outils « Lecture de la vidéo », « Lire » / « Pause » / « Rejouer », « Scène précédente » /
« Scène suivante », `role="slider"`, « ⋯ »).

Prouvé ici (contrat 2026-10 § 4, § 7) :
- PX-4 : Variantes s'ouvre en pause sur l'image 0 de la scène 1, aucun Player (même préchargé, caché) ne dit `playing`, la page de la scène
  n'a pas de barre à elle (`rs-bar`), la lecture du temps est celle de la composition ;
- PX-7 : la pause tient l'image 5 s, la reprise repart de cette image ;
- PX-8 : ⏭ en lecture entre dans la scène suivante sur son image 0 et lit ; ⏮ en pause se pose sur l'image 0 ; trois ⏭ rapides = trois scènes ;
- PX-9 : la barre à travers les scènes, en avant et en arrière : Player, bande, libellé et temps d'accord (§ 4.8) ;
- PX-10 : Fin, la dernière image tenue 5 s, « Rejouer » repart de 0 ;
- PX-18 : une scène qui échoue met la lecture en pause sur elle, nommée, avec « Réessayer » ; jamais sautée ;
- PX-19 : une nouvelle version de la scène en cours de lecture garde (scène, image) et l'état de lecture ; le Player change sur place ;
- Core ne lance aucune lecture ; Variantes reste ouvert.

Preuves (JSON + PNG, chemin personnel masqué) : `JARVIS_PLAYBACK_GATE_EVIDENCE_DIR`, en pratique
`tasks/jarvis-remotion-native-studio-playback-fix/slices/06-player-lifecycle-and-transport/evidence/`, avec `summary.json`.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.remotion_source import Composition
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.presentation_playback_gate_world import (
    BASE, CONTROLS, DECK, PLAYBACK, PREFABS, PROPS, READ_PROBE, READOUTS, SCENE_IDS, SCENE_TSX, VSTATE, composition_seconds, evidence_dir,
    first_play, harness, make_deck, open_variants, parse_readout, player_clocks, readout_problems, record, redact, run_long, scrub_to,
    thumbnail, variants_scene_ready, wraps,
)
from tests.unit.test_remotion_player_realpage_browser import http_step

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

X = "#jvStudioExplorer"
LIRE = f"{X} [role=\"toolbar\"] [data-act=\"continuous\"]"
NEXT = f"{X} [role=\"toolbar\"] [aria-label=\"Scène suivante\"]"
PREV = f"{X} [role=\"toolbar\"] [aria-label=\"Scène précédente\"]"
NOW = {"expr": "Math.round(performance.now()-__pg.t0)"}
LABEL = f"document.querySelector('{LIRE}').textContent.trim()"
#: The transport as a viewer and a screen reader see it.
TRANSPORT = ("(()=>{const x=document.querySelector('#jvStudioExplorer');const bars=[...x.querySelectorAll('[role=\"toolbar\"]')].filter(b=>b.querySelector('[data-act=\"continuous\"]'));"
             "const bar=bars[0];if(!bar)return null;const sl=bar.querySelector('[role=\"slider\"]');const son=bar.querySelector('[aria-label=\"Son\"]');"
             "return {toolbars:bars.length,name:bar.getAttribute('aria-label'),buttons:[...bar.querySelectorAll('button')].filter(b=>!b.hidden).map(b=>b.getAttribute('aria-label')||b.textContent.trim()),"
             "slider:{min:sl.getAttribute('aria-valuemin'),max:sl.getAttribute('aria-valuemax'),now:sl.getAttribute('aria-valuenow'),text:sl.getAttribute('aria-valuetext')},"
             "son:[son.getAttribute('aria-disabled'),son.title],more:bar.querySelector('[aria-haspopup=\"menu\"]').getAttribute('aria-label'),"
             "stageBars:[...x.querySelectorAll('iframe[data-remotion-stage]')].map(f=>{try{return f.contentDocument.querySelectorAll('.rs-bar').length}catch(e){return -1}}),"
             "embedded:[...x.querySelectorAll('iframe[data-remotion-stage]')].map(f=>f.src.includes('embed=variants'))}})()")
PHASE = "JarvisStudioExplorer.playback.view().phase"


#: Installed once in the page (`{eval: HELPERS}`): the plan is passed on the command line, which Windows caps at 32 K characters.
HELPERS = f"window.__vs=()=>{VSTATE};window.__ro=()=>{READOUTS};"
VS, RO = "__vs()", "__ro()"


def vstate_is(scene: int, cond: str = "true") -> str:
    return f"(()=>{{const s=__vs();return !!s&&s.scene==='S{scene}'&&s.phase==='ready'&&({cond})}})()"


PREVIEW_RECT = ("(()=>{const r=document.querySelector('#jvStudioExplorer .jvx-preview').getBoundingClientRect();"
                "return {x:Math.max(0,r.left),y:Math.max(0,r.top),width:Math.max(16,r.width),height:Math.max(16,Math.min(r.height,innerHeight-r.top))}})()")


def snap(folder, name: str) -> dict:
    """One small capture of the Variants preview (stage, transport, strip), half size: `<folder>/<name>-000.png`."""

    return {"burst": str(folder), "ms": 1, "clipExpr": PREVIEW_RECT, "scale": 0.5, "prefix": name, "as": f"snap_{name}"}


def opened(pid: str) -> list[dict]:
    return open_variants(pid)[:2] + [{"eval": HELPERS}] + open_variants(pid)[2:]


def summarize(key: str, payload: dict) -> None:
    """Adds `key` to `summary.json` of the evidence folder (one file for the Slice, each test its own entry)."""

    folder = evidence_dir()
    if folder is None:
        return
    path = folder / "summary.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"slice": "06-player-lifecycle-and-transport"}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "jarvis"], capture_output=True, text=True, check=False).stdout.strip()
    data.update({"tested_head": head + (" + uncommitted jarvis/ changes" if dirty else ""), "runtime": "headless Chrome over CDP, RemotionStack on free loopback ports, throw-away data root; "
                 "the live Jarvis was never contacted", key: payload})
    path.write_text(redact(json.dumps(data, indent=1, ensure_ascii=False, default=str)), encoding="utf-8")


def uids_of(probe: dict, scene: str, place: str = "explorer") -> list[int]:
    return [row[2] for row in probe["ev"] if row[1] == "mount" and row[3] == place and row[4] == scene]


def first_play_after(probe: dict, scene: str, since_ms: int) -> tuple[int, int] | None:
    clocks = player_clocks(probe)
    rows = sorted((c for u in uids_of(probe, scene) for c in clocks.get(u, []) if c[0] >= since_ms and c[2]), key=lambda c: c[0])
    return (rows[0][0], rows[0][1]) if rows else None


def core_phase(reads: dict) -> str | None:
    return (((reads.get("core") or {}).get("body") or {}).get("state") or {}).get("phase")


# ---------------------------------------------------------------------------------------------------------------- PX-4, 7, 8, 9, 10

async def test_variants_opens_paused_and_the_transport_drives_one_clock_pause_resume_navigation_scrub_and_end(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = opened(pid) + [
            {"wait": 3000}, {"value": "opened", "expr": VS}, {"value": "transport", "expr": TRANSPORT}, {"value": "readouts0", "expr": RO},
            snap(tmp_path, "opened"), {"value": "first_order_at", **NOW},
            # PX-7: play, pause, 5 s, resume
            {"click": LIRE}, {"until": vstate_is(1, "s.playing&&s.frame>=40"), "ms": 30000, "required": True, "as": "playing_40"},
            {"click": LIRE}, {"until": vstate_is(1, "!s.playing"), "ms": 5000, "required": True, "as": "paused"},
            {"wait": 300}, {"value": "paused1", "expr": VS}, {"value": "label_paused", "expr": LABEL}, {"wait": 5000},
            {"value": "paused2", "expr": VS}, {"value": "resume_at", **NOW}, {"click": LIRE}, {"wait": 800},
            {"value": "resumed", "expr": VS},
            # PX-8: next while playing, previous while paused, three fast next
            {"value": "next_at", **NOW}, {"click": NEXT}, {"until": vstate_is(2, "s.playing&&s.frame>=10"), "ms": 30000, "required": True, "as": "s2"},
            {"value": "next", "expr": RO},
            {"click": LIRE}, {"until": vstate_is(2, "!s.playing"), "ms": 5000}, {"click": PREV},
            {"until": vstate_is(1, "!s.playing&&s.frame===0"), "ms": 30000, "required": True, "as": "prev_s1"}, {"wait": 500},
            {"value": "prev", "expr": RO},
            {"eval": f"(()=>{{const b=document.querySelector('{NEXT}');b.click();b.click();b.click()}})()"},
            {"until": vstate_is(4, "!s.playing&&s.frame===0"), "ms": 60000, "required": True, "as": "rapid_s4"}, {"wait": 800},
            {"value": "rapid", "expr": RO},
            # PX-9: scrub across scenes, forward then back, paused
            {"value": "scrub_fwd_kind", "expr": scrub_to(6, 2, legacy_local_frame=48)},
            {"until": vstate_is(7, "s.frame===48"), "ms": 60000, "as": "scrub_fwd_landed"}, {"wait": 600},
            {"value": "scrub_fwd", "expr": RO}, snap(tmp_path, "scrub-forward-S7"),
            {"value": "scrub_back_kind", "expr": scrub_to(1, 3, legacy_local_frame=90)},
            {"until": vstate_is(2, "s.frame===90"), "ms": 60000, "as": "scrub_back_landed"}, {"wait": 600},
            {"value": "scrub_back", "expr": RO},
            # PX-10: End, the final frame held, « Rejouer »
            {"eval": "(()=>{const s=document.querySelector('#jvStudioExplorer [role=\"slider\"]');s.focus();"
                     "s.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true}))})()"},
            {"until": vstate_is(9, "s.frame===239&&!s.playing"), "ms": 60000, "required": True, "as": "end_s9"},
            {"click": LIRE}, {"until": f"{PHASE}==='ended'", "ms": 5000, "as": "ended"}, {"value": "label_end", "expr": LABEL},
            {"wait": 5000}, {"value": "held", "expr": RO}, snap(tmp_path, "held-final-frame"),
            {"value": "replay_at", **NOW}, {"click": LIRE},
            {"until": vstate_is(1, "s.playing&&s.frame>=10"), "ms": 30000, "as": "replayed"},
            {"value": "probe", "expr": READ_PROBE}, http_step(stack, "core", "GET", PLAYBACK)]
        result = await run_long(stack.page_url, plan, timeout=600)
        reads = result["reads"]
        probe = reads.get("probe")
        harness(probe, reads.get("failed"))
        clocks = player_clocks(probe)
        played_before_lire = [(u, c) for u, rows in clocks.items() for c in rows if c[2] and c[0] < reads["first_order_at"]]
        evidence = {k: reads.get(k) for k in ("opened", "transport", "readouts0", "paused1", "paused2", "label_paused", "resumed", "next", "prev",
                                              "rapid", "scrub_fwd_kind", "scrub_fwd", "scrub_back", "label_end", "held", "failed")}
        evidence.update({"played_before_lire": played_before_lire, "resume_first_play": first_play_after(probe, "S1", reads["resume_at"]),
                         "next_first_play_S2": first_play_after(probe, "S2", reads["next_at"]),
                         "replay_first_play_S1": first_play_after(probe, "S1", reads["replay_at"]), "core_phase": core_phase(reads),
                         "wraps": {u: wraps(rows) for u, rows in clocks.items() if wraps(rows)}})
        record("transport", {"evidence": evidence, "probe_ev": probe["ev"]},
               [tmp_path / "opened-000.png", tmp_path / "scrub-forward-S7-000.png", tmp_path / "held-final-frame-000.png"])
        harness("failed" not in reads, reads.get("failed"))
        t = evidence["transport"]
        checks = {
            "PX-4 opens paused on S1 frame 0": evidence["opened"]["scene"] == "S1" and evidence["opened"]["frame"] == 0 and evidence["opened"]["playing"] is False,
            "PX-4 nothing plays before « Lire » (staged frames included)": played_before_lire == [],
            "PX-4 no stage bar, embedded page": t["stageBars"] and all(n == 0 for n in t["stageBars"]) and all(t["embedded"]),
            # Slice 08: « Son » is the sound toggle, muted at opening (no longer disabled; `test_variants_media_fullscreen_browser.py`)
            "PX-4 « Son » muted at opening": t["son"][0] is None and t["son"][1] == "Activer le son (M)",
            "§ 4.16 one named toolbar": t["toolbars"] == 1 and t["name"] == "Lecture de la vidéo"
                # Slice 10: playback controls only; « Présenter ▾ » is on the scene row (« Arrêter » shows only during a run)
                and t["buttons"] == ["Scène précédente", "Lire", "Scène suivante", "Son", "Plus de lecture"],
            "§ 4.16 slider": t["slider"]["min"] == "0" and t["slider"]["now"] == "0" and t["slider"]["max"] == str(74 * 60 - 1),
            "§ 4.8 composition readout at opening": readout_problems(evidence["readouts0"], 0) == [],
            "PX-7 pause holds 5 s": evidence["paused1"]["frame"] == evidence["paused2"]["frame"] and evidence["paused2"]["playing"] is False
                and evidence["label_paused"] == "Lire",
            "PX-7 resume continues from the held frame": evidence["resume_first_play"] is not None
                and evidence["paused2"]["frame"] <= evidence["resume_first_play"][1] <= evidence["paused2"]["frame"] + 3,
            "PX-8 next lands on S2 frame 0 and keeps playing": evidence["next_first_play_S2"] is not None and evidence["next_first_play_S2"][1] == 0
                and evidence["next"]["label"] == 2 and evidence["next"]["selected"] == SCENE_IDS[1],
            "PX-8 previous lands on S1 frame 0 paused": evidence["prev"]["player"]["frame"] == 0 and evidence["prev"]["player"]["playing"] is False
                and evidence["prev"]["label"] == 1,
            "PX-8 three fast next = three scenes": evidence["rapid"]["label"] == 4 and evidence["rapid"]["selected"] == SCENE_IDS[3],
            "PX-9 forward scrub into S7": evidence["scrub_fwd_kind"] == "slider" and evidence["scrub_fwd"]["player"]["frame"] == 48
                and evidence["scrub_fwd"]["label"] == 7 and evidence["scrub_fwd"]["selected"] == SCENE_IDS[6]
                and readout_problems(evidence["scrub_fwd"], 6) == [],
            "PX-9 backward scrub into S2": evidence["scrub_back"]["player"]["frame"] == 90 and evidence["scrub_back"]["label"] == 2
                and evidence["scrub_back"]["selected"] == SCENE_IDS[1] and readout_problems(evidence["scrub_back"], 1) == [],
            "PX-10 final frame held 5 s, « Rejouer »": evidence["label_end"] == "Rejouer" and evidence["held"]["player"]["frame"] == 239
                and evidence["held"]["player"]["playing"] is False and evidence["held"]["player"]["scene"] == "S9",
            "PX-10 « Rejouer » restarts from frame 0": evidence["replay_first_play_S1"] is not None and evidence["replay_first_play_S1"][1] == 0,
            "no Core run": evidence["core_phase"] in (None, "idle", "stopped"),
            "never wraps": evidence["wraps"] == {},
        }
        summarize("transport", {"checks": checks, "readout_at_opening": evidence["readouts0"]["readouts"],
                                "scrub_forward": evidence["scrub_fwd"], "held": evidence["held"]["player"]})
        assert all(checks.values()), {k: v for k, v in checks.items() if not v}


# ---------------------------------------------------------------------------------------------------------------- § 4.6 pointer drag, the row

def at_slider(fraction: float) -> str:
    """{x, y} of the slider at `fraction` of its width (CDP coordinates of the page)."""

    return ("(()=>{const r=document.querySelector('#jvStudioExplorer [role=\"slider\"]').getBoundingClientRect();"
            f"return {{x:r.left+r.width*{fraction},y:r.top+r.height/2}}}})()")


def mouse(kind: str, fraction: float) -> dict:
    return {"mouse": kind, "atExpr": at_slider(fraction)}


#: The row under the stage (transport, scene line, « Scène n sur N »): one row, every child inside it and the row inside the preview, nothing
#: wider than its box, and the scene count either whole or cut with an ellipsis (QA P5).
ROW = ("(()=>{const x=document.querySelector('#jvStudioExplorer');const pe=x.querySelector('.jvx-preview'),b=pe.getBoundingClientRect(),cs=getComputedStyle(pe);"
       "const p={left:b.left+parseFloat(cs.paddingLeft),right:Math.min(innerWidth,b.right)-parseFloat(cs.paddingRight)};"
       "const note=x.querySelector('.jvx-stage-note');const n=note.getBoundingClientRect();"
       "const kids=[...note.children].map(c=>{const b=c.getBoundingClientRect();return {cls:c.className,left:Math.round(b.left),right:Math.round(b.right),"
       "scroll:c.scrollWidth,client:c.clientWidth,ellipsis:getComputedStyle(c).textOverflow,text:c.textContent.slice(0,40)}});"
       "return {preview:[Math.round(p.left),Math.round(p.right)],row:[Math.round(n.left),Math.round(n.right)],rowScroll:note.scrollWidth,rowClient:note.clientWidth,kids}})()")


SLIDER_W = "Math.round(document.querySelector('#jvStudioExplorer [role=\"slider\"]').getBoundingClientRect().width)"


def row_problems(row: dict) -> list[str]:
    problems = []
    if row["row"][0] < row["preview"][0] - 1 or row["row"][1] > row["preview"][1] + 1:
        problems.append(f"row {row['row']} outside the preview {row['preview']}")
    if row["rowScroll"] > row["rowClient"] + 1:
        problems.append(f"row overflows: {row['rowScroll']} > {row['rowClient']}")
    for kid in row["kids"]:
        if kid["right"] == kid["left"]:
            continue   # not displayed (the scene title leaves a narrow row)
        if kid["left"] < row["row"][0] - 1 or kid["right"] > row["row"][1] + 1:
            problems.append(f"{kid['cls']!r} {kid['left']}..{kid['right']} outside the row {row['row']}")
        if kid["cls"] == "jvx-transport" and kid["scroll"] > kid["client"] + 1:
            problems.append(f"the transport overflows its box: {kid['scroll']} > {kid['client']}")
        if kid["cls"] == "jvx-scene-count" and kid["scroll"] > kid["client"] + 1 and kid["ellipsis"] != "ellipsis":
            problems.append(f"scene count cut without an ellipsis: {kid}")
    return problems


@pytest.mark.parametrize("viewport", ["800x600", "1280x720"])
async def test_a_pointer_drag_on_the_slider_pauses_then_plays_from_the_scrubbed_frame_and_the_row_fits(tmp_path, viewport):
    """§ 4.6 with a real mouse (CDP press, moves, release on the slider): playing, the press pauses; `f` follows the moves; the release plays
    from the scrubbed frame with Player, readout, label and strip in agreement. A drag that starts paused stays paused. QA B1, P5."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        tag = f"drag-{viewport}"
        plan = opened(pid) + [
            {"wait": 2000}, {"value": "row_opened", "expr": ROW}, snap(tmp_path, "opened"),
            {"click": LIRE}, {"until": vstate_is(1, "s.playing&&s.frame>=20"), "ms": 30000, "required": True, "as": "playing"},
            mouse("mouseMoved", 0.2), mouse("mousePressed", 0.2),
            {"value": "pressed", "expr": "JarvisStudioExplorer.playback.view()"}, {"value": "w_pressed", "expr": SLIDER_W},
            mouse("mouseMoved", 0.4), mouse("mouseMoved", 0.6), mouse("mouseMoved", 0.78),
            {"value": "moved", "expr": "JarvisStudioExplorer.playback.view()"}, {"value": "w_moved", "expr": SLIDER_W}, {"value": "moved_now", "expr": "document.querySelector('#jvStudioExplorer [role=\"slider\"]').getAttribute('aria-valuenow')"},
            mouse("mouseReleased", 0.78),
            {"until": vstate_is(7, "s.playing&&s.frame>0"), "ms": 60000, "required": True, "as": "released_s7"}, {"wait": 400},
            {"value": "released", "expr": RO}, {"value": "released_view", "expr": "JarvisStudioExplorer.playback.view()"},
            {"value": "row_playing", "expr": ROW}, snap(tmp_path, "released"),
            # a drag that starts paused stays paused
            {"click": LIRE}, {"until": f"{PHASE}==='paused'", "ms": 5000, "required": True, "as": "paused"},
            mouse("mouseMoved", 0.1), mouse("mousePressed", 0.1), mouse("mouseMoved", 0.05), mouse("mouseReleased", 0.05),
            {"until": vstate_is(2, "!s.playing"), "ms": 60000, "as": "paused_s2"}, {"wait": 1500},
            {"value": "paused_after", "expr": RO}, {"value": "paused_view", "expr": "JarvisStudioExplorer.playback.view()"},
            {"value": "probe", "expr": READ_PROBE}, http_step(stack, "core", "GET", PLAYBACK)]
        result = await run_long(stack.page_url, plan, timeout=500, viewport=viewport)
        reads = result["reads"]
        harness(reads.get("probe"), reads.get("failed"))
        rel, view = reads["released"], reads["released_view"]
        evidence = {k: reads.get(k) for k in ("row_opened", "w_pressed", "w_moved", "pressed", "moved", "moved_now", "released", "released_view", "row_playing",
                                              "paused_after", "paused_view", "failed")}
        evidence["core_phase"] = core_phase(reads)
        record(tag, evidence, [tmp_path / "opened-000.png", tmp_path / "released-000.png"])
        harness("failed" not in reads, reads.get("failed"))
        total = 74 * 60
        target = round(0.78 * (total - 1))
        player = rel["player"]
        local = (view["frame"] - view["starts"][6]) * 24 / 60
        checks = {
            "press while playing pauses": evidence["pressed"]["phase"] == "paused",
            "the slider keeps its width while the scene changes under the drag": reads["w_pressed"] == reads["w_moved"],
            "f follows the moves": abs(evidence["moved"]["frame"] - target) <= 6 and evidence["moved_now"] == str(evidence["moved"]["frame"]),
            "release plays from the scrubbed frame": view["phase"] == "playing" and player["scene"] == "S7" and player["playing"] is True
                and view["frame"] >= evidence["moved"]["frame"],
            "Player, readout, label and strip agree": rel["label"] == 7 and rel["selected"] == SCENE_IDS[6]
                and readout_problems(rel, 6) == [] and abs(player["frame"] - local) <= 24,
            "a drag that starts paused stays paused": evidence["paused_view"]["phase"] == "paused"
                and evidence["paused_after"]["player"]["playing"] is False and evidence["paused_after"]["label"] == 2,
            "the row fits the preview (opened)": row_problems(evidence["row_opened"]) == [],
            "the row fits the preview (playing S7)": row_problems(evidence["row_playing"]) == [],
            "no Core run": evidence["core_phase"] in (None, "idle", "stopped"),
        }
        summarize(tag, {"checks": checks, "moved": evidence["moved"]["frame"], "target": target, "released": rel,
                        "row": evidence["row_playing"], "row_problems": row_problems(evidence["row_playing"])})
        assert all(checks.values()), ({k: v for k, v in checks.items() if not v}, row_problems(evidence["row_playing"]), evidence["moved"], view, player)


# ---------------------------------------------------------------------------------------------------------------- PX-18

BROKEN_TSX = """import React from "react";
export default function Scene(props: {title: string; bg: string}): React.ReactElement {
  throw new Error("scene S2 is broken on purpose");
}
"""


async def make_small_deck(stack: RemotionStack) -> str:
    """S1 (3 s), S2 (renders an error), S3 (3 s)."""

    prefabs = [f"presentation-studio.p0000000000b1.s{n:012d}" for n in range(1, 4)]
    for index, prefab_id in enumerate(prefabs):
        await stack.core.prefabs.save(scene_candidate(
            prefab_id, engine=shipped_engine_pin(), title=f"S{index + 1}", composition=Composition("Scene", 1280, 720, 30, 90),
            files={"src/Scene.tsx": BROKEN_TSX if index == 1 else SCENE_TSX}, props=PROPS,
            sample={"props": {"title": f"S{index + 1}", "bg": "#202060"}, "data": {}}), actor="user")
    _, created = await stack.call("POST", BASE, json={"title": "Trois scenes"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    scenes = [{"scene_id": SCENE_IDS[i], "prefab": {"id": prefabs[i], "version": 1}, "title": f"S{i + 1}", "props": {"title": f"S{i + 1}", "bg": bg},
               "data": {}, "controls": CONTROLS, "anchors": []} for i, bg in enumerate(["#b01010", "#10a010", "#1030c0"])]
    status, saved = await stack.call("PUT", f"{BASE}/{pid}/variants/{variant['variant_id']}", json={
        "expected_revision": variant["revision"], "title": variant["title"], "scenes": scenes,
        "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]})
    harness(status == 200, f"variant save refused: {saved}")
    return pid


async def test_a_scene_that_fails_pauses_playback_on_it_named_with_retry_and_is_never_skipped(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid = await make_small_deck(stack)
        veil = ("(()=>{const v=document.querySelector('#jvStudioExplorer .jvx-stage-veil');return {hidden:v.hidden,title:v.querySelector('strong').textContent,"
                "text:v.querySelector('span').textContent,actions:[...v.querySelectorAll('button')].filter(b=>!b.hidden).map(b=>b.textContent)}})()")
        plan = opened(pid) + [
            {"wait": 1500}, {"click": LIRE},
            {"until": f"{PHASE}==='failed'", "ms": 90000, "required": True, "as": "phase_failed"},
            {"value": "view", "expr": "JarvisStudioExplorer.playback.view()"}, {"value": "veil", "expr": veil}, {"value": "readouts", "expr": RO},
            snap(tmp_path, "failure-veil"), {"wait": 4000},
            {"value": "later", "expr": "JarvisStudioExplorer.playback.view()"}, {"value": "probe", "expr": READ_PROBE},
            http_step(stack, "core", "GET", PLAYBACK)]
        result = await run_long(stack.page_url, plan, timeout=400)
        reads = result["reads"]
        harness(reads.get("probe"), reads.get("failed"))
        probe = reads["probe"]
        lives = [row for row in probe["ev"] if row[1] == "live"]
        live_scenes = [next((m[4] for m in probe["ev"] if m[1] == "mount" and m[2] == row[2]), None) for row in lives]
        errors_logged = [line for line in result.get("console", []) if "sequencer_failed" in str(line)]
        evidence = {"view": reads.get("view"), "veil": reads.get("veil"), "readouts": reads.get("readouts"), "later": reads.get("later"),
                    "live_scenes": live_scenes, "errors_logged": errors_logged, "core_phase": core_phase(reads), "failed": reads.get("failed")}
        record("failure", evidence, [tmp_path / "failure-veil-000.png"])
        harness("failed" not in reads, reads.get("failed"))
        view, later = evidence["view"], evidence["later"]
        checks = {
            "PX-18 paused at the failing scene's start": view["phase"] == "failed" and view["scene_index"] == 1 and view["frame"] == 90
                and later["phase"] == "failed" and later["frame"] == 90,
            "PX-18 the reason, named": evidence["veil"]["hidden"] is False and evidence["veil"]["title"] == "Scène 2 : lecture impossible"
                and "Scène 2" in evidence["veil"]["text"],
            "PX-18 « Réessayer »": "Réessayer" in evidence["veil"]["actions"],
            "PX-18 never a silent skip": "S3" not in live_scenes,
            "PX-18 an Error Logs row (console error key)": len(errors_logged) >= 1,
            "no Core run": evidence["core_phase"] in (None, "idle", "stopped"),
        }
        summarize("failure", {"checks": checks, "veil": evidence["veil"], "live_scenes": live_scenes})
        assert all(checks.values()), {k: v for k, v in checks.items() if not v}


# ---------------------------------------------------------------------------------------------------------------- PX-19

async def test_a_new_version_of_the_scene_that_plays_keeps_its_frame_and_the_play_state(tmp_path):
    """S3 (30 s) plays; at about 7 s a new version of its source (40 s long) is pinned in the variant: Variants reads the new revision, the
    Player swaps in place and goes on from the kept frame, still playing; the composition is now 84 s long."""

    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, vid = await make_deck(stack)
        await stack.core.prefabs.save(scene_candidate(
            PREFABS[2], engine=shipped_engine_pin(), title="S3", composition=Composition("Scene", 1280, 720, 30, 1200),
            files={"src/Scene.tsx": SCENE_TSX}, props=PROPS, sample={"props": {"title": "S3 v2", "bg": "#1030c0"}, "data": {}}), actor="user")
        _, current = await stack.call("GET", f"{BASE}/{pid}/variants/{vid}")
        scenes = []
        for index, (seconds, fps, anchors, bg) in enumerate(DECK):
            scenes.append({"scene_id": SCENE_IDS[index], "prefab": {"id": PREFABS[index], "version": 2 if index == 2 else 1},
                           "title": f"S{index + 1} {seconds}s@{fps}", "props": {"title": f"S{index + 1} {seconds}s@{fps}", "bg": bg}, "data": {},
                           "controls": CONTROLS, "anchors": [{"anchor_id": f"a{index + 1}_{k}", "label": f"Ancre {k}", "at_ms": at} for k, at in enumerate(anchors)]})
        edit = http_step(stack, "edit", "PUT", f"{BASE}/{pid}/variants/{vid}", {
            "expected_revision": current["revision"], "title": current["title"], "scenes": scenes,
            "art_direction_id": current["art_direction_id"], "score_id": current["score_id"]})
        v2 = (f"(()=>{{const f=[...document.querySelectorAll('#jvStudioExplorer iframe[data-remotion-stage]')].find(x=>!x.classList.contains('sc-prefab-staged')"
              f"&&x.style.visibility!=='hidden'&&x.getBoundingClientRect().width>0);if(!f||!f.src.includes('&v=2'))return false;"
              f"try{{const s=f.contentWindow.__remotionStage.state();return s.phase==='ready'&&s.playing&&s.frame>0}}catch(e){{return false}}}})()")
        plan = opened(pid) + [
            thumbnail(2), variants_scene_ready(2), {"wait": 800}, {"click": LIRE},
            {"until": vstate_is(3, "s.playing&&s.frame>=200"), "ms": 40000, "required": True, "as": "s3_200"},
            {"value": "before", "expr": RO}, {"value": "edit_at", **NOW}, edit, {"eval": "JarvisStudioExplorer.refresh()"},
            {"until": v2, "ms": 120000, "required": True, "as": "v2_playing"}, {"value": "after", "expr": RO},
            {"value": "view_after", "expr": "JarvisStudioExplorer.playback.view()"}, {"wait": 2000},
            {"value": "later", "expr": RO}, snap(tmp_path, "hot-reload-v2"), {"value": "probe", "expr": READ_PROBE},
            http_step(stack, "core", "GET", PLAYBACK)]
        result = await run_long(stack.page_url, plan, timeout=500)
        reads = result["reads"]
        harness(reads.get("probe"), reads.get("failed"))
        harness((reads.get("edit") or {}).get("status") == 200, f"the edit was refused: {reads.get('edit')}")
        probe = reads["probe"]
        clocks = player_clocks(probe)
        new_uids = [row[2] for row in probe["ev"] if row[1] == "mount" and row[3] == "explorer" and row[4] == "S3" and row[0] >= reads["edit_at"]]
        v2_first = next(((ms, f) for u in new_uids for ms, f, p in clocks.get(u, []) if p), None)
        held = sorted(((ms, f) for u, rows in clocks.items() for ms, f, p in rows if ms >= reads["edit_at"] and not p and u not in new_uids))
        before = reads["before"]["player"]["frame"]
        after_text = [r["text"] for r in (reads.get("after") or {}).get("readouts", [])]
        evidence = {"before": reads.get("before"), "after": reads.get("after"), "later": reads.get("later"), "view_after": reads.get("view_after"),
                    "v2_first_play": v2_first, "old_held_at": held[:3], "core_phase": core_phase(reads), "failed": reads.get("failed")}
        record("hot_reload", {"evidence": evidence, "probe_ev": probe["ev"]}, [tmp_path / "hot-reload-v2-000.png"])
        harness("failed" not in reads, reads.get("failed"))
        total = parse_readout(after_text[0])[1] if after_text and parse_readout(after_text[0]) else None
        later = reads["later"]["player"]
        checks = {
            "PX-19 the new version goes on from the kept frame (not 0)": v2_first is not None and before - 2 <= v2_first[1] <= before + 45,
            "PX-19 play state kept": later["playing"] is True and later["scene"] == "S3" and later["frame"] > v2_first[1],
            "PX-19 the map was rebuilt (84 s)": total is not None and abs(total - 84) <= 1,
            "§ 4.8 readout = composition time after the swap": reads["later"]["label"] == 3 and reads["later"]["selected"] == SCENE_IDS[2],
            "no Core run": evidence["core_phase"] in (None, "idle", "stopped"),
        }
        summarize("hot_reload", {"checks": checks, "frame_before_edit": before, "v2_first_play": v2_first, "readout_after": after_text,
                                 "composition_seconds_check": composition_seconds(2, later["frame"])})
        assert all(checks.values()), {k: v for k, v in checks.items() if not v}
