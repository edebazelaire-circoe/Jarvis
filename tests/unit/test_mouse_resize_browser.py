"""Real CDP pointers/keys in the served Control Center; isolated fetch fixture."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit.test_selection_actions_browser import _obj
from tests.unit.test_status_centre_browser import _drive


SIDES = ("top", "right", "bottom", "left", "top-left", "top-right", "bottom-left", "bottom-right")
OBJECTS = [
    _obj("jobj_w", "window", rep="window", geometry={"x": -90, "y": -45, "w": 45, "h": 30}, payload={"title": "Rapport", "summary": "Document", "items": []}),
    _obj("jobj_c", "artifact", rep="capsule", geometry={"x": 15, "y": -10, "w": 40, "h": 7}, payload={"title": "Image", "summary": "", "items": []}),
    _obj("jobj_p", "agent", rep="point", geometry={"x": 50, "y": -40, "w": 6, "h": 6}, payload={"title": "Analyse", "summary": "", "items": []}),
]
for item in OBJECTS:
    item["origin"] = "user"


def _state():
    return "({selection:JarvisScene.inspect().selection,objects:structuredClone(__sc.objects),bodies:structuredClone(__sc.bodies),holding:JarvisScene.inspect().holding})"


def _node(object_id):
    return f'.sc-node[data-object-id="{object_id}"]'


def test_all_eight_mouse_handles_resize_windows_and_capsules(tmp_path):
    actions = []
    for object_id in ("jobj_w", "jobj_c"):
        for side in SIDES:
            label = object_id + side
            selector = _node(object_id) + f' > .sc-grip[data-resize-sides="{side}"]'
            dx = -12 if "left" in side else 12 if "right" in side else 0
            dy = -10 if "top" in side else 10 if "bottom" in side else 0
            actions += [["eval", label + "before", _state(), 0], ["drag", label, selector, 400, [dx, dy]], ["eval", label + "after", _state(), 0]]
    step = _drive(tmp_path, [{"width": 1920, "height": 1080, "storage": {"orbit": False}, "seed": {"objects": OBJECTS}, "actions": actions}])[0]
    for object_id in ("jobj_w", "jobj_c"):
        for side in SIDES:
            label = object_id + side
            before = next(o["geometry"] for o in step["results"][label + "before"]["objects"] if o["object_id"] == object_id)
            after = next(o["geometry"] for o in step["results"][label + "after"]["objects"] if o["object_id"] == object_id)
            assert after != before, (object_id, side, step["results"][label + "after"])
            assert after["w"] > before["w"] if ("left" in side or "right" in side) else after["h"] > before["h"]
            assert step["results"][label + "after"]["holding"] == []
    initial = len(step["results"]["jobj_wtopbefore"]["bodies"])
    assert len([b for b in step["bodies"][initial:] if b["path"] == "/api/scene/commands" and b["body"].get("op") == "set_geometry"]) == 16
    assert not [c for c in step["console"] if c["type"] in ("error", "exception")]


def test_right_click_keyboard_menu_select_all_and_open_intents(tmp_path):
    actions = [
        ["eval", "initial", _state(), 0],
        ["eval", "listen", "window.__opens=[];document.addEventListener('jarvis:scene-open',e=>__opens.push(e.detail));true", 0],
        ["click", "first", _node("jobj_w"), 150], ["ctrlclick", "second", _node("jobj_c"), 150],
        ["rclick", "context", _node("jobj_w"), 150], ["eval", "kept", _state(), 0],
        ["key", "close", "Escape", 150], ["key", "keyboardMenu", "ContextMenu", 150], ["eval", "keyboardKept", _state(), 0],
        ["key", "close2", "Escape", 150], ["key", "enter", "Enter", 150], ["eval", "opened", "structuredClone(__opens)", 0],
        ["dblclick", "double", _node("jobj_w"), 150], ["eval", "doubleOpened", "structuredClone(__opens)", 0],
        ["rclick", "other", _node("jobj_p"), 150], ["eval", "replaced", _state(), 0], ["key", "close3", "Escape", 150],
        ["key", "all", "a", 150, 2], ["eval", "selectedAll", _state(), 0],
        ["eval", "edit", "const t=document.createElement('input');t.id='mouseTestEdit';t.value='texte';document.body.append(t);t.focus();true", 0],
        ["key", "editAll", "a", 150, 2], ["eval", "editable", "({selection:JarvisScene.inspect().selection,start:mouseTestEdit.selectionStart,end:mouseTestEdit.selectionEnd})", 0],
    ]
    evidence = os.environ.get("JARVIS_MOUSE_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        actions.insert(6, ["shot", "selectionShot", str(Path(evidence) / "mouse-selection.png"), 100])
    step = _drive(tmp_path, [{"width": 1920, "height": 1080, "storage": {"orbit": False}, "seed": {"objects": OBJECTS}, "actions": actions}])[0]
    assert set(step["results"]["kept"]["selection"]) == {"jobj_w", "jobj_c"}
    assert set(step["results"]["keyboardKept"]["selection"]) == {"jobj_w", "jobj_c"}
    assert step["results"]["opened"][-1]["source"] == "keyboard"
    assert set(step["results"]["opened"][-1]["ids"]) == {"jobj_w", "jobj_c"}
    assert step["results"]["doubleOpened"][-1]["source"] == "double-click"
    assert set(step["results"]["doubleOpened"][-1]["ids"]) == {"jobj_w", "jobj_c"}
    assert step["results"]["replaced"]["selection"] == ["jobj_p"]
    assert set(step["results"]["selectedAll"]["selection"]) == {"jobj_w", "jobj_c", "jobj_p"}
    assert step["results"]["editable"]["start"] == 0 and step["results"]["editable"]["end"] == 5
    assert not [b for b in step["bodies"][len(step["results"]["initial"]["bodies"]):] if b["path"] == "/api/scene/commands"]


def test_shift_pointer_resize_rebases_on_press_and_release_and_escape_cancels(tmp_path):
    grip = _node("jobj_w") + ' > .sc-grip[data-resize-sides="bottom-right"]'
    rect = "(()=>{const r=document.querySelector('.sc-node[data-object-id=jobj_w]').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()"
    actions = [
        ["eval", "initial", _state(), 0],
        ["press", "down", grip, 50], ["move", "grow", [724, 468], 100, {"buttons": 1}], ["eval", "free", rect, 0],
        ["keydown", "shiftDown", "Shift", 100, 8], ["eval", "pressed", rect, 0],
        ["move", "lockedMove", [754, 483], 100, {"buttons": 1, "modifiers": 8}], ["eval", "locked", rect, 0],
        ["keyup", "shiftUp", "Shift", 100, 0], ["eval", "released", rect, 0],
        ["key", "cancel", "Escape", 150], ["release", "up", [754, 483], 100], ["eval", "final", _state(), 0],
    ]
    step = _drive(tmp_path, [{"width": 1920, "height": 1080, "storage": {"orbit": False}, "seed": {"objects": OBJECTS}, "actions": actions}])[0]
    results = step["results"]
    assert results["free"] == results["pressed"], results
    assert results["locked"] == results["released"], results
    assert results["locked"]["w"] / results["locked"]["h"] == pytest.approx(results["free"]["w"] / results["free"]["h"], abs=.02)
    assert results["final"]["holding"] == []
    assert not [b for b in step["bodies"][len(results["initial"]["bodies"]):] if b["path"] == "/api/scene/commands" and b["body"].get("op") == "set_geometry"]
    assert results["initial"]["objects"] == results["final"]["objects"]


def test_shift_held_at_start_locks_initial_ratio_then_keyboard_resize_works(tmp_path):
    rect = "(()=>{const r=document.querySelector('.sc-node[data-object-id=jobj_w]').getBoundingClientRect();return {w:r.width,h:r.height}})()"
    actions = [
        ["eval", "initial", rect, 0],
        ["drag", "proportional", _node("jobj_w") + ' > .sc-grip[data-resize-sides="bottom-right"]', 350, [36, 8, 8]],
        ["eval", "resized", rect, 0],
        ["key", "keyboardResize", "ArrowRight", 50, 2], ["key", "modifierReleased", "Control", 150],
        ["eval", "keyboard", rect, 0],
    ]
    step = _drive(tmp_path, [{"width": 1920, "height": 1080, "storage": {"orbit": False}, "seed": {"objects": OBJECTS}, "actions": actions}])[0]
    initial, resized = step["results"]["initial"], step["results"]["resized"]
    assert resized["w"] / resized["h"] == pytest.approx(initial["w"] / initial["h"], abs=.02)
    assert resized["w"] > initial["w"]
    assert step["results"]["keyboard"]["w"] > resized["w"]
