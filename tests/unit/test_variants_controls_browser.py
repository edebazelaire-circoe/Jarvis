"""The Variants control audit on the REAL Control Center page, in a REAL headless Chrome, against an isolated REAL Core
(jarvis-remotion-native-studio-playback-fix, Slice 10: simplify the existing Variants UI).

Nothing is simulated except the display: a real Core behind the real protocol server (own data root, own ports), a real presentation
with a real score, the real `ControlCenter` page relaying to it, real CDP keys and clicks. The live Jarvis is never contacted.

Proved, measured (contract `docs/presentation-studio.md` › *Variants control audit (Level 3, Slice 10)*, § 6, PX-11, PX-12, PX-17):

- each control once at 800x600, 1280x720 and 1920x1080: one transport toolbar, one play button, one previous / next pair, one slider,
  one fullscreen button, one « Arrêter » at most; no variant bar, no `rs-bar`, no dwell (« 8 s par slide »), no loop, no « Tout jouer » /
  « Jouer cette slide »; every visible control has a name; no horizontal overflow; the graph actions are all there; one selected row,
  one selected scene;
- `?` and « ⋯ › Raccourcis clavier » open ONE keyboard sheet (a modal dialog, the § 4.15 map of the mode on screen and the tree keys);
  `Échap` closes it and the focus goes back to where it was;
- during a presentation run the graph actions (« Activer », « Brancher d'ici… », « Renommer… », « Archiver… ») and the tree are inert AND
  visibly dimmed, with the reason on screen; the windowed scene line gives way to the presenter strip; when the run ends they come back;
- every visible readout is the Player's composition time, the score time labelled « Partition », a labelled wait, or labelled authoring
  metadata (the variant count says « variantes »).

With a Remotion runtime (`JARVIS_REMOTION_RUNTIME_DIR`), `test_evidence_…` also opens the 9-scene video deck, checks that the time
readout is the composition time, and writes the before / after screenshots and control inventories of the Slice
(`JARVIS_VARIANTS_CONTROLS_EVIDENCE_DIR`, tag `JARVIS_VARIANTS_CONTROLS_SHOT_TAG`, the SHA in each file name; home path redacted).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.presentation_studio_relay import PLAYBACK_ROUTE
from tests.unit.test_presentation_studio_playback_routes import presentation_with_score, start_body
from tests.unit.test_presentation_studio_routes import Core
from tests.unit.test_variants_run_browser import READY, drive, wire

X = "#jvStudioExplorer"
EXPLORER = "window.JarvisStudioExplorer"
VIEWPORTS = ["800x600", "1280x720", "1920x1080"]
GRAPH_ACTIONS = ["Activer", "Brancher d'ici…", "Renommer…", "Archiver…"]

#: Everything a viewer can see or reach in Variants: each visible control with its name, state, effective opacity (the product of
#: its ancestors'), inertness and box; plus the readouts and the overflow.
INVENTORY = r"""(()=>{const x=document.querySelector('#jvStudioExplorer');if(!x||x.hidden)return null;
const vis=e=>{if(e.closest('[hidden]'))return false;const r=e.getBoundingClientRect();const cs=getComputedStyle(e);return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&cs.display!=='none'};
const op=e=>{let o=1;for(let n=e;n&&n!==document.documentElement;n=n.parentElement)o*=parseFloat(getComputedStyle(n).opacity);return Math.round(o*100)/100};
const nm=e=>(e.getAttribute('aria-label')||e.innerText||'').replace(/\s+/g,' ').trim();   /* innerText: a label hidden by CSS is no name */
const inert=e=>{for(let n=e;n;n=n.parentElement)if(n.inert)return true;return false};
const box=e=>{const r=e.getBoundingClientRect();return [Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom)]};
const controls=[...x.querySelectorAll('button,[role="slider"],[role="option"],[role="treeitem"],[role="menuitem"]')].filter(vis).map(e=>({
  role:e.getAttribute('role')||e.tagName.toLowerCase(),name:nm(e).slice(0,80),act:e.dataset.act||null,disabled:e.getAttribute('aria-disabled')==='true'||!!e.disabled,
  opacity:op(e),inert:inert(e),state:e.getAttribute('aria-selected')||e.getAttribute('aria-pressed')||null,box:box(e),
  where:e.closest('[role="toolbar"]')?e.closest('[role="toolbar"]').getAttribute('aria-label'):e.closest('.jvx-treepane')?'tree':e.closest('.jvx-strip')?'strip':e.closest('.jvx-top')?'header':'other'}));
const text=s=>{const n=x.querySelector(s);return n&&vis(n)?n.textContent.replace(/\s+/g,' ').trim():null};
const tp=x.querySelector('.jvx-treepane .jvx-tree'),acts=x.querySelector('.jvx-actions');
return {vw:innerWidth,vh:innerHeight,overflowX:x.scrollWidth>x.clientWidth+1||document.documentElement.scrollWidth>innerWidth+1,
  transportBars:document.querySelectorAll('[role="toolbar"] [data-act="continuous"]').length,controls,
  time:text('.jvx-time'),scene:text('.jvx-scene-count'),sceneTitle:text('.jvx-scene-line'),count:text('.jvx-panehead .jvx-chip'),
  treeOpacity:tp?op(tp):null,treeInert:tp?inert(tp):null,actionsOpacity:acts?op(acts):null,runNote:text('.jvx-run-note'),
  vbar:!!x.querySelector('.jvx-vbar'),hint:text('.jvx-hint-keys'),rsBars:document.querySelectorAll('.rs-bar').length,
  forbidden:['par slide','Tout jouer','Jouer cette slide','boucle','Boucle'].filter(w=>x.innerText.includes(w)),
  transportRow:(()=>{const t=x.querySelector('.jvx-transport');if(!t)return null;const tops=[...t.children].filter(vis).map(c=>Math.round(c.getBoundingClientRect().top+c.getBoundingClientRect().height/2));
    return {box:box(t),rows:new Set(tops.map(v=>Math.round(v/8))).size}})()}})()"""

#: Every visible text of Variants that looks like a readout (a time, a duration, a « n / N »), with the classes around it.
READOUT_SCAN = r"""(()=>{const x=document.querySelector('#jvStudioExplorer');const RX=/\d+:\d{2}|\b\d+(?:[.,]\d+)?\s?s\b|\b\d+\s?\/\s?\d+\b/;
const out=[];const walk=document.createTreeWalker(x,NodeFilter.SHOW_TEXT);
for(let n=walk.nextNode();n;n=walk.nextNode()){const t=n.textContent.replace(/\s+/g,' ').trim();if(!t||!RX.test(t))continue;const e=n.parentElement;
  if(!e||e.closest('[hidden]')||e.closest('.jvx-sr'))continue;const r=e.getBoundingClientRect();if(!r.width||!r.height)continue;
  const owner=e.closest('.jvx-time,.jvx-presenter-clock,.jvx-stage-wait,.jvx-busy,.jvx-panehead .jvx-chip,.jvx-rowmeta,.jvx-facts,.jvx-meta,.jvx-presenter-where,.jvx-presenter-seq,.jvx-scene-count,.jvx-stage-veil,.jvx-notice,.jvx-row,.jvx-scene,.jvx-rms');
  out.push({text:t.slice(0,80),owner:owner?owner.className:null,label:(owner||e).textContent.replace(/\s+/g,' ').trim().slice(0,120),title:(owner||e).getAttribute('title')||''})}
return out})()"""


def _open_variants(pid: str) -> list[dict]:
    return [{"until": f"!!{EXPLORER}", "ms": 15000},
            {"eval": f"{EXPLORER}.open({{presentation_id:'{pid}',fullscreen:false}})"},
            {"until": f"{EXPLORER}.state().open && {EXPLORER}.state().preview.status==='ready'"
                      " && !!document.querySelector('#jvStudioExplorer .jvx-actions button')", "ms": 20000}]


def _ok(result: dict) -> dict:
    reads = result["reads"]
    assert "failed" not in reads, reads
    assert not [k for k, v in reads.items() if k.startswith("until:") and v is False], reads
    assert not result["errors"], result["errors"]
    return reads


def _by_name(controls: list[dict], name: str) -> list[dict]:
    return [c for c in controls if c["name"] == name]


@pytest.fixture
async def deck(tmp_path):
    """An isolated Core with a 3-scene presentation and its score, the real Control Center wired to it; yields `(core, url, pid)`."""

    async with Core(tmp_path) as core:
        url = await wire(core, tmp_path)
        pid, _ = await presentation_with_score(core)
        yield core, url, pid
        await core.stack.center.scene_view.aclose()


# ---------------------------------------------------------------------------------------------------------------- each control once

@pytest.mark.parametrize("viewport", VIEWPORTS)
async def test_each_control_appears_once_named_inside_the_window_and_nothing_forbidden_is_drawn(deck, viewport, tmp_path):
    core, url, pid = deck
    shot = tmp_path / f"variants-{viewport}.png"
    result = await drive(url, _open_variants(pid) + [{"wait": 600}, {"value": "inv", "expr": INVENTORY}, {"shot": str(shot)}],
                         viewport=viewport)
    inv = _ok(result)["inv"]
    controls = inv["controls"]
    transport = [c for c in controls if c["where"] == "Lecture de la vidéo"]
    assert inv["transportBars"] == 1, "one transport toolbar in the whole page"
    assert len([c for c in controls if c["act"] == "continuous"]) == 1, "one play / pause button"
    assert len(_by_name(controls, "Scène précédente")) == 1 and len(_by_name(controls, "Scène suivante")) == 1, controls
    assert len([c for c in controls if c["role"] == "slider"]) == 1, "one scrub"
    fullscreen = [c for c in controls if "Plein écran" in c["name"]]
    assert len(fullscreen) == 2 and sum(c["act"] == "fullscreen" for c in fullscreen) == 1, "two fullscreen controls: the header's and the transport's"
    assert len([c for c in controls if c["name"] == "Arrêter"]) == 0 and len([c for c in controls if c["act"] == "present"]) == 1
    assert [c["name"] for c in controls if c["name"] in GRAPH_ACTIONS] == GRAPH_ACTIONS, "the four graph actions, once each"
    assert not [c for c in controls if not c["name"]], ("every visible control has a name", [c for c in controls if not c["name"]])
    assert inv["vbar"] is False, "the variant bar is merged into the tree (§ 6 #8)"
    assert inv["hint"] is None or "?" in inv["hint"], "the tree key hint is merged into the keyboard sheet (§ 6 #6)"
    assert inv["rsBars"] == 0 and inv["forbidden"] == [], inv["forbidden"]
    assert inv["overflowX"] is False, "no horizontal overflow"
    assert inv["transportRow"]["rows"] == 1 and inv["transportRow"]["box"][2] <= inv["vw"], inv["transportRow"]
    assert all(0 <= c["box"][0] and c["box"][2] <= inv["vw"] for c in transport), transport
    assert len([c for c in controls if c["role"] == "treeitem" and c["state"] == "true"]) == 1, "one selected variant row"
    assert len([c for c in controls if c["role"] == "option" and c["state"] == "true"]) == 1, "one selected scene"
    assert inv["count"] and "variante" in inv["count"], "the tree count says what it counts (authoring metadata, not a position)"
    assert shot.stat().st_size > 1000


# ---------------------------------------------------------------------------------------------------------------- keyboard sheet

SHEET = f"document.querySelector('{X} .jvx-layer [role=\"dialog\"][data-kind=\"shortcuts\"]')"


async def test_question_mark_and_the_overflow_entry_open_one_keyboard_sheet_and_escape_gives_the_focus_back(deck):
    core, url, pid = deck
    result = await drive(url, _open_variants(pid) + [
        {"eval": f"document.querySelector('{X} .jvx-stage').focus()"},
        {"key": "?"}, {"until": f"!!{SHEET}", "ms": 4000},
        {"value": "sheet", "expr": f"(()=>{{const d={SHEET};return {{title:d.querySelector('h2').textContent,modal:d.getAttribute('aria-modal'),"
                                   "focusIn:d.contains(document.activeElement),keys:[...d.querySelectorAll('kbd')].map(k=>k.textContent),"
                                   "rows:[...d.querySelectorAll('tr')].length,inertBehind:document.querySelector('#jvStudioExplorer .jvx-body').inert}})()"},
        {"key": "Escape"}, {"until": f"!{SHEET}", "ms": 4000},
        {"value": "after_escape", "expr": f"[{EXPLORER}.state().open,document.activeElement===document.querySelector('{X} .jvx-stage'),"
                                          f"document.querySelector('{X} .jvx-body').inert]"},
        {"click": f"{X} [role=\"toolbar\"] [aria-haspopup=\"menu\"][aria-label=\"Plus de lecture\"]"},
        {"until": f"!!document.querySelector('{X} .jvx-menu')", "ms": 3000},
        {"value": "menu", "expr": f"[...document.querySelectorAll('{X} .jvx-menu [role=\"menuitem\"]')].map(b=>b.textContent.replace(/\\s+/g,' ').trim())"},
        {"eval": f"[...document.querySelectorAll('{X} .jvx-menu [role=\"menuitem\"]')].find(b=>b.textContent.includes('Raccourcis')).click()"},
        {"until": f"!!{SHEET}", "ms": 4000},
        {"value": "sheets", "expr": f"document.querySelectorAll('{X} [data-kind=\"shortcuts\"]').length"},
        {"key": "Escape"}, {"until": f"!{SHEET}", "ms": 4000},
        {"value": "focus_more", "expr": "document.activeElement&&document.activeElement.getAttribute('aria-label')"},
    ])
    reads = _ok(result)
    sheet = reads["sheet"]
    assert sheet["title"] == "Raccourcis clavier" and sheet["modal"] == "true" and sheet["focusIn"] is True, sheet
    assert sheet["inertBehind"] is True, "a modal sheet: the rest of Variants is inert behind it"
    for key in ("Espace", "→", "←", "Début", "Fin", "F", "M", "Échap", "?", "F2", "Suppr", "[", "]"):
        assert key in sheet["keys"], (key, sheet["keys"])
    assert reads["after_escape"] == [True, True, False], "Échap closes the sheet only, the focus is back on the stage"
    assert any("Raccourcis clavier" in item for item in reads["menu"]), reads["menu"]
    assert reads["sheets"] == 1
    assert reads["focus_more"] == "Plus de lecture", "closing the sheet opened from « ⋯ » gives the focus back to « ⋯ »"


# ---------------------------------------------------------------------------------------------------------------- run: inert is dimmed

#: The presenter strip starts below the transport row (a crowded preview scrolls; it never draws the strip over the transport).
STACKED = ("(()=>{const t=document.querySelector('#jvStudioExplorer .jvx-transport').getBoundingClientRect(),"
           "p=document.querySelector('#jvStudioExplorer .jvx-presenter').getBoundingClientRect();return {transport:t.bottom,strip:p.top,gap:Math.round(p.top-t.bottom)}})()")

@pytest.fixture
async def running(deck):
    core, url, pid = deck
    status, started, _ = await core.stack.call("POST", f"{PLAYBACK_ROUTE}/start", json=start_body(pid))
    assert status == 200 and started["state"]["phase"] == "playing", started
    yield core, url, pid


@pytest.mark.parametrize("viewport", ["800x600", "1280x720"])
async def test_during_a_run_the_graph_actions_and_the_tree_are_dimmed_with_the_reason_and_come_back_after(running, viewport, tmp_path):
    core, url, pid = running
    shot = tmp_path / f"run-{viewport}.png"
    result = await drive(url, [
        {"wait": 600}, READY, {"wait": 500}, {"value": "run", "expr": INVENTORY}, {"value": "readouts", "expr": READOUT_SCAN},
        {"value": "stacked", "expr": STACKED},
        {"shot": str(shot)},
        {"click": f"{X} [role=\"toolbar\"] [data-act=\"stop_run\"]"},
        {"until": f"!{EXPLORER}.run.view()", "ms": 10000}, {"wait": 600},
        {"value": "after", "expr": INVENTORY},
    ], viewport=viewport)
    reads = _ok(result)
    run, after = reads["run"], reads["after"]
    acts = {c["name"]: c for c in run["controls"] if c["name"] in GRAPH_ACTIONS}
    assert set(acts) == set(GRAPH_ACTIONS), "the graph actions stay on screen during a run (never removed)"
    assert all(a["disabled"] and a["inert"] and a["opacity"] < 0.5 for a in acts.values()), ("dimmer than an idle disabled action (0.5)", acts)
    assert run["treeInert"] is True and run["treeOpacity"] <= 0.6, run["treeOpacity"]
    assert run["runNote"] and "Présentation en cours" in run["runNote"], run["runNote"]
    assert run["sceneTitle"] is None and run["scene"] is None, "windowed, the presenter strip replaces the scene line"
    assert len(_by_name(run["controls"], "Arrêter")) == 1 and not [c for c in run["controls"] if c["act"] == "present"]
    assert run["overflowX"] is False and run["transportRow"]["rows"] == 1, run["transportRow"]
    assert reads["stacked"]["gap"] >= 0, ("the presenter strip is drawn under the transport, never over it", reads["stacked"])
    back = {c["name"]: c for c in after["controls"] if c["name"] in GRAPH_ACTIONS}
    assert set(back) == set(GRAPH_ACTIONS)
    assert back["Brancher d'ici…"]["disabled"] is False and back["Brancher d'ici…"]["opacity"] == 1 and not back["Brancher d'ici…"]["inert"]
    assert after["treeInert"] is False and after["treeOpacity"] == 1 and after["runNote"] is None
    _readouts_are_canonical_or_labelled(reads["readouts"])
    assert shot.stat().st_size > 1000


# ---------------------------------------------------------------------------------------------------------------- readouts

def _readouts_are_canonical_or_labelled(rows: list[dict]) -> None:
    """§ 6 « Forbidden in video playback »: no time readout other than composition time, except the presenter strip's score time,
    labelled. Everything else that looks like a number pair or a duration must say what it is."""

    for row in rows:
        owner, label = row["owner"] or "", row["label"]
        if "jvx-time" in owner:
            continue                                        # the Player's composition time `f / L` (written from the sequencer only)
        if "jvx-presenter-clock" in owner:
            assert label.startswith("Partition") and "jamais le temps de la vidéo" in row["title"], row
        elif "jvx-stage-wait" in owner:
            assert label.startswith("Chargement de la scène"), row
        elif "jvx-rms" in owner:
            assert "Remotion Studio" in label, ("Slice 11: Remotion Studio's state line says whose state it is", row)
        elif "jvx-busy" in owner or "jvx-stage-veil" in owner or "jvx-notice" in owner:
            assert "…" in label or label.endswith("s") or "Chargement" in label, row
        elif "jvx-chip" in owner:
            assert "variante" in label, ("a count chip says what it counts", row)
        elif any(k in owner for k in ("jvx-rowmeta", "jvx-facts", "jvx-meta", "jvx-row", "jvx-scene")):
            continue                                        # authoring metadata (dates, scene counts, numbers of the strip)
        elif "jvx-presenter-where" in owner or "jvx-presenter-seq" in owner or "jvx-scene-count" in owner:
            assert "Scène" in label or "séquence" in label.lower() or "élément" in label, row
        else:
            pytest.fail(f"an unlabelled readout in Variants: {row}")


async def test_every_visible_readout_is_the_player_time_or_says_what_it_is(deck):
    core, url, pid = deck
    result = await drive(url, _open_variants(pid) + [{"wait": 600}, {"value": "readouts", "expr": READOUT_SCAN}])
    rows = _ok(result)["readouts"]
    assert rows, "the count chip at least is scanned"
    _readouts_are_canonical_or_labelled(rows)


# ---------------------------------------------------------------------------------------------------------------- evidence, real video

from tests.fakes.remotion_player_stack import runtime_dir_from_env  # noqa: E402

#: Slice 10 rework (P4): an installation with `node_modules` and `runtime-host.mjs`, as the transport tests read it (else skip, never fail).
RUNTIME = runtime_dir_from_env()


def _evidence_dir() -> Path | None:
    raw = os.environ.get("JARVIS_VARIANTS_CONTROLS_EVIDENCE_DIR")
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _redact(text: str) -> str:
    """The Windows home path and user name, derived at run time, never written into the evidence."""

    home = str(Path.home())
    for form in {home, home.replace("\\", "/"), home.replace("\\", "\\\\"), json.dumps(home)[1:-1]}:
        text = text.replace(form, "<home>")
    return text.replace(Path.home().name, "<user>")


@pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR (with node_modules), node and Chrome")
async def test_evidence_variants_with_the_video_deck_idle_at_three_sizes_and_during_a_run(tmp_path):
    from tests.fakes.remotion_player_stack import RemotionStack
    from tests.unit.presentation_playback_gate_world import READOUTS, make_deck, open_variants, readout_problems, run_long

    tag = os.environ.get("JARVIS_VARIANTS_CONTROLS_SHOT_TAG", "run")
    head = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "jarvis"], capture_output=True, text=True, check=False).stdout.strip()
    sha = head + ("-dirty" if dirty else "")
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        names = {size: tmp_path / f"{tag}-{sha}-variants-{size}.png" for size in VIEWPORTS}
        plan = open_variants(pid) + [{"eval": f"window.__ro=()=>{READOUTS};"}, {"wait": 2500}]
        for size in VIEWPORTS:
            w, h = (int(v) for v in size.split("x"))
            plan += [{"size": [w, h]}, {"wait": 1200}, {"value": f"inv_{size}", "expr": INVENTORY}, {"shot": str(names[size])}]
        plan += [{"size": [1280, 720]}, {"wait": 800}, {"value": "readout", "expr": "__ro()"},
                 {"eval": f"document.querySelector('{X} .jvx-stage').focus()"}, {"key": "?", "shift": True},
                 {"until": f"!!{SHEET}", "ms": 4000, "required": True, "as": "sheet"}, {"wait": 300},
                 {"shot": str(tmp_path / f"{tag}-{sha}-sheet-1280x720.png")}, {"key": "Escape"}, {"until": f"!{SHEET}", "ms": 4000},
                 {"eval": f"{EXPLORER}.run.present('user_presenter')"},
                 {"until": f"!!{EXPLORER}.run.view() && !document.querySelector('{X} .jvx-presenter').hidden", "ms": 30000,
                  "required": True, "as": "run"},
                 {"wait": 2500}, {"value": "inv_run", "expr": INVENTORY}, {"shot": str(tmp_path / f"{tag}-{sha}-run-1280x720.png")},
                 {"eval": f"document.querySelector('{X} [data-act=\"stop_run\"]').click()"},
                 {"until": f"!{EXPLORER}.run.view()", "ms": 15000}]
        result = await run_long(stack.page_url, plan, timeout=500)
    reads = result["reads"]
    assert "failed" not in reads, reads.get("failed")
    folder = _evidence_dir()
    if folder is not None:
        for shot in [*names.values(), tmp_path / f"{tag}-{sha}-run-1280x720.png", tmp_path / f"{tag}-{sha}-sheet-1280x720.png"]:
            if shot.is_file():
                shutil.copy2(shot, folder / shot.name)
        inventory = {k: v for k, v in reads.items() if k.startswith("inv_") or k == "readout"}
        (folder / f"{tag}-{sha}-inventory.json").write_text(_redact(json.dumps(
            {"sha": sha, "tag": tag, "runtime": "headless Chrome over CDP, RemotionStack on free loopback ports, throw-away data root; "
             "the live Jarvis was never contacted", **inventory}, indent=1, ensure_ascii=False)), encoding="utf-8")
    assert readout_problems(reads["readout"], 0) == [], "the time readout is the composition time"


# ---------------------------------------------------------------------------------------------------------------- Slice 10 rework (B1)

THEATER = f"document.querySelector('{X} .jvx-theater')"
IN_FS = f"(document.fullscreenElement==={THEATER})"
#: Is this element drawn and reachable inside the fullscreen stage: in the fullscreen element, not inert, the point at its centre hits it.
SEEN = r"""(sel=>{const e=document.querySelector(sel);if(!e)return null;const fs=document.fullscreenElement;let inert=false;
for(let n=e;n;n=n.parentElement)if(n.inert)inert=true;const r=e.getBoundingClientRect();const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
return {inFs:!!fs&&fs.contains(e),inert,visible:r.width>0&&r.height>0,hit:!!hit&&e.contains(hit)}})"""
TRANSPORT_LIVE = (f"(()=>{{const t=document.querySelector('{X} .jvx-transport');for(let n=t;n;n=n.parentElement)if(n.inert)return false;"
                  "return true})()")


SPY_LOCK = ("window.__locks=[];const k=navigator.keyboard;const l=k.lock.bind(k),u=k.unlock.bind(k);"
            "k.lock=a=>{window.__locks.push(['lock'].concat(a||[]));return l(a)};k.unlock=()=>{window.__locks.push(['unlock']);return u()}")


async def test_in_stage_fullscreen_the_sheet_and_the_overflow_menu_are_drawn_inside_it_and_escape_is_nested(deck):
    """B1: `?` in the stage fullscreen used to mount the sheet outside the fullscreen element (unseen) and make the stage inert.

    The first Échap goes to the overlay: Variants holds the Keyboard Lock on Échap while a menu or a dialog is drawn inside the fullscreen
    stage (so a real browser delivers it instead of leaving fullscreen) and releases it once the overlay is gone. Headless Chrome leaves
    the fullscreen on an injected Échap whatever the lock (measured: the lock resolves, the page receives the key, the fullscreen still
    ends), so here the proof is: the page closes the overlay on that first press, asked for the lock while it was open and released it;
    that the fullscreen survives in a real browser is the Human check."""

    core, url, pid = deck
    focus_stage = {"eval": f"document.querySelector('{X} .jvx-stage').focus()"}
    result = await drive(url, _open_variants(pid) + [
        {"wait": 500}, {"eval": SPY_LOCK}, focus_stage, {"key": "F"},
        {"until": IN_FS, "ms": 6000},
        {"key": "?"}, {"until": f"!!{SHEET}", "ms": 4000}, {"wait": 300},
        {"value": "sheet", "expr": f"{SEEN}('{X} [data-kind=\"shortcuts\"]')"},
        {"value": "transportLiveUnderSheet", "expr": TRANSPORT_LIVE},
        {"value": "locksOpen", "expr": "JSON.stringify(window.__locks)"},
        {"key": "Escape"}, {"wait": 500},
        {"value": "afterFirstEscape", "expr": f"JSON.stringify({{sheet:!!{SHEET},live:{TRANSPORT_LIVE},locks:window.__locks}})"},
        # headless Chrome has left the fullscreen on that Échap (see the docstring): enter it again for « ⋯ »
        {"eval": "document.fullscreenElement&&document.exitFullscreen()"}, {"wait": 300}, focus_stage, {"key": "F"}, {"until": IN_FS, "ms": 6000},
        {"click": f"{X} [aria-label=\"Plus de lecture\"]"}, {"wait": 400},
        {"value": "menu", "expr": f"{SEEN}('{X} .jvx-menu [role=\"menuitem\"]')"},
        {"key": "Escape"}, {"wait": 400},
        {"value": "afterMenuEscape", "expr": f"JSON.stringify({{menu:!!document.querySelector('{X} .jvx-menu')}})"},
        {"value": "open", "expr": f"{EXPLORER}.isOpen()"}])
    reads = _ok(result)
    assert reads["sheet"] == {"inFs": True, "inert": False, "visible": True, "hit": True}, ("the sheet is drawn inside the fullscreen", reads["sheet"])
    assert reads["transportLiveUnderSheet"] is False, "a modal sheet: the transport waits behind it (inert) …"
    assert json.loads(reads["locksOpen"]) == [["lock", "Escape"]], "Échap is held for the overlay while it is open in fullscreen"
    first = json.loads(reads["afterFirstEscape"])
    assert first["sheet"] is False and first["live"] is True, "the first Échap closes the sheet, the transport is live again"
    assert ["unlock"] in first["locks"], "the lock is given back once the overlay is gone"
    assert reads["menu"] == {"inFs": True, "inert": False, "visible": True, "hit": True}, ("« ⋯ » is drawn inside the fullscreen", reads["menu"])
    assert json.loads(reads["afterMenuEscape"]) == {"menu": False}
    assert reads["open"] is True, "Échap never closed Variants while an overlay or the fullscreen was there"


@pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR (with node_modules), node and Chrome")
async def test_in_stage_fullscreen_space_plays_and_pauses_after_the_sheet_is_closed(tmp_path):
    from tests.fakes.remotion_player_stack import RemotionStack
    from tests.unit.presentation_playback_gate_world import make_deck, open_variants, run_long

    phase = f"{EXPLORER}.playback.view().phase"
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, _vid = await make_deck(stack)
        plan = open_variants(pid) + [
            {"wait": 1500}, {"eval": f"document.querySelector('{X} .jvx-stage').focus()"}, {"key": "F"},
            {"until": IN_FS, "ms": 6000, "required": True, "as": "fullscreen"},
            {"key": "?"}, {"until": f"!!{SHEET}", "ms": 4000, "required": True, "as": "sheet"},
            {"value": "sheet", "expr": f"{SEEN}('{X} [data-kind=\"shortcuts\"]')"},
            {"key": "Escape"}, {"until": f"!{SHEET}", "ms": 4000, "required": True, "as": "sheet_closed"},
            {"value": "fsAfterSheet", "expr": IN_FS},
            {"key": " "}, {"until": f"{phase}==='playing'||{phase}==='waiting'", "ms": 20000, "required": True, "as": "plays"},
            {"wait": 1500}, {"key": " "}, {"until": f"{phase}==='paused'", "ms": 8000, "required": True, "as": "pauses"},
            {"value": "fs", "expr": IN_FS}]
        result = await run_long(stack.page_url, plan, timeout=400)
    reads = result["reads"]
    assert "failed" not in reads, reads.get("failed")
    assert reads["sheet"] == {"inFs": True, "inert": False, "visible": True, "hit": True}, reads["sheet"]
    assert reads.get("until:" + f"{phase}==='paused'") is True, "Space played, then paused, once the sheet was closed"
