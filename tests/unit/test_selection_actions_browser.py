"""Actions de Sélection de la roue, dans un vrai Chrome sans tête (Slice 06).

Handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 06. Contrat :
`docs/scene-selection-batch.md` › *Selection actions (wheel)*, `docs/dossier.md` ›
*Ranger*. La page est celle que `ControlCenter.index` sert ; `fetch` est le double de
`_status_centre_browser.mjs` (scène : instantané, patchs, commandes atomiques ; Dossier :
`…/dossier/backing` et `…/dossier/ranger` selon la graine ; registre :
`/api/artifacts/{id}`). Ce que ce fichier épingle, par vrais clics, Ctrl-clics et touches :

- atteindre la roue ne défait pas la sélection ; le sous-menu suit la sélection (vide,
  simple, mixte) ;
- **Ranger** : la page attend le résultat par objet — rien n'est retiré d'avance ; un
  objet rangé quitte le Board, un refus reste, avec sa phrase ; un refus de la demande
  entière (Board non affiché) ne touche rien ; « gardé sans retrait » est dit ;
- **Masquer** : un seul `patch_selection {visibility: hidden}`, aucun appel au Dossier ;
- **Changer la forme** : un seul `patch_selection {representation}`, aucune charge ;
- **Retirer du Board** : confirmation qui dit que la source reste dans le Dossier, puis
  un seul `archive_selection` ; aucune suppression (`DELETE`, `memory/delete`) ;
- une fenêtre `registry_artifact_id` se lit dans le registre ; sa charge n'est jamais
  renvoyée ;
- clavier : Ctrl+Espace compose la sélection, la roue au clavier agit sur elle.

Preuves visuelles : `JARVIS_S06_SELECTION_EVIDENCE_DIR=<dossier>` y écrit les captures.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit.test_status_centre_browser import OPEN_SELECTION, ROWS, _drive

EVIDENCE = os.environ.get("JARVIS_S06_SELECTION_EVIDENCE_DIR")
REG = "jart_" + "a" * 32
SIZES = ((1920, 1032), (1280, 720), (600, 800))


def _obj(object_id: str, kind: str, *, rep: str, geometry: dict, payload: dict, visibility: str = "visible") -> dict:
    return {"schema_version": 1, "object_id": object_id, "kind": kind, "category": "dossier" if kind == "window" else kind,
            "exec_state": "running" if kind == "agent" else "unknown", "representation": rep, "geometry": geometry,
            "layer": 220 if rep == "window" else 100, "order": 0, "visibility": visibility, "disposition": "active",
            "constraints": {"placed_by": "user", "pinned_by_user": False}, "origin": "brain", "work_ref": None,
            "payload": {"summary": "", "items": [], **payload}}


OBJECTS = [
    _obj("jobj_note", "window", rep="window", geometry={"x": -50, "y": -20, "w": 34, "h": 22},
         payload={"title": "Note de réunion", "summary": "Décisions : budget validé."}),
    _obj("jobj_doc", "window", rep="window", geometry={"x": 10, "y": -20, "w": 34, "h": 22},
         payload={"title": "Plan", "summary": "Contenu du fichier", "source_path": "C:/data/boards/b/memory/plan.md"}),
    _obj("jobj_reg", "window", rep="window", geometry={"x": -30, "y": 18, "w": 70, "h": 40},
         payload={"title": "Transcription", "registry_artifact_id": REG}),
    _obj("jobj_star", "agent", rep="point", geometry={"x": 60, "y": 30, "w": 6, "h": 6}, payload={"title": "Analyse"}),
    _obj("jobj_hidden", "agent", rep="point", geometry={"x": 40, "y": -34, "w": 6, "h": 6},
         payload={"title": "Recherche masquée"}, visibility="hidden"),
]
REFUSAL = "Cet objet ne se range pas dans le Dossier ; il reste sur le Board."
DOSSIER = {"jobj_note": {"rangeable": True}, "jobj_doc": {"rangeable": True, "backing": "memory"},
           "jobj_reg": {"rangeable": True, "backing": "artifact"},
           "jobj_star": {"rangeable": False, "code": "dossier_not_eligible", "message": REFUSAL}}
REGISTRY = {REG: {"artifact_id": REG, "kind": "transcript", "mime_type": "text/plain", "has_payload": False,
                  "text": "Bonjour, ceci est la transcription du registre.", "text_truncated": False}}
SEED = {"objects": OBJECTS, "dossier": DOSSIER, "registry": REGISTRY}

NODE = '#sceneLayer [data-object-id="{}"]'
DRAWN = "[...document.querySelectorAll('#sceneLayer [data-object-id]')].map(n=>n.dataset.objectId).sort()"
SELECTION = "JarvisScene.inspect().selection"
TOASTS = "[...document.querySelectorAll('#toasts .toast')].map(t=>t.textContent)"
CALLS = "window.__sc.calls"
OPEN_ROW = lambda row: ["click", f"row:{row}", f"#toolWheel .tw-item[data-tw-item='{row}']", 700]  # noqa: E731


def _shot(name: str, size: tuple[int, int]) -> list:
    if not EVIDENCE:
        return []
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    return [["shot", f"shot:{name}", str(Path(EVIDENCE) / f"{name}-{size[0]}x{size[1]}.png"), 100]]


def _commands(step: dict) -> list:
    return [b["body"] for b in step["bodies"] if b["path"] == "/api/scene/commands" and b["body"]["op"] != "set_geometry"]


def _no_errors(step: dict) -> None:
    bad = [line for line in step["console"] if line["type"] in ("error", "exception")]
    assert not bad, bad


def _rows(result: list) -> dict:
    return {row["id"]: row for row in result if row["id"] not in ("mouse", "bare_hands")}


def test_the_selection_submenu_follows_the_selection_and_reaching_the_wheel_keeps_it(tmp_path):
    actions = [
        *OPEN_SELECTION, ["eval", "empty", ROWS, 100], ["key", "esc", "Escape", 300], ["key", "esc2", "Escape", 300],
        ["click", "pick", NODE.format("jobj_note"), 500],
        *OPEN_SELECTION, ["eval", "single", ROWS, 100], ["eval", "kept", SELECTION, 50],
        ["key", "esc3", "Escape", 300], ["key", "esc4", "Escape", 300],
        ["ctrlclick", "add", NODE.format("jobj_star"), 600],
        *OPEN_SELECTION, ["eval", "mixed", ROWS, 1200], ["eval", "kept2", SELECTION, 50],
        ["click", "form", "#toolWheel .tw-item[data-tw-item=form]", 600], ["eval", "forms", ROWS, 100],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": actions}])[0]
    r = step["results"]
    assert list(_rows(r["empty"])) == ["selection-none", "hidden"]
    assert _rows(r["empty"])["hidden"]["text"] == "Masqués (1)"
    single = _rows(r["single"])
    assert list(single) == ["selection-count", "ranger", "hide", "hidden", "form", "remove"]
    assert r["kept"] == ["jobj_note"], "opening the wheel with the mouse keeps the selection"
    mixed = _rows(r["mixed"])
    assert mixed["selection-count"]["text"] == "2 objets sélectionnés"
    assert r["kept2"] == ["jobj_note", "jobj_star"]
    # L'aperçu Dossier est arrivé : 1 sur 2 se range.
    ranger = next(b for b in step["results"]["mixed"] if b["id"] == "ranger")
    assert ranger["disabled"] is None
    assert any("/dossier/backing" in call for call in step["calls"]), step["calls"]
    assert [row["text"] for row in r["forms"]] == ["Étoile", "Capsule", "Fenêtre"]
    _no_errors(step)


def test_ranger_a_mixed_selection_stores_what_it_can_and_explains_each_refusal(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": [
        ["click", "pick", NODE.format("jobj_note"), 400], ["ctrlclick", "add", NODE.format("jobj_star"), 500],
        *OPEN_SELECTION, ["eval", "before", CALLS, 1000],
        OPEN_ROW("ranger"), ["eval", "drawn", DRAWN, 1200], ["eval", "toasts", TOASTS, 50],
        ["eval", "selection", SELECTION, 50],
    ]}])[0]
    r = step["results"]
    ranger = [b for b in step["bodies"] if b["path"].endswith("/dossier/ranger")]
    assert [b["body"] for b in ranger] == [{"object_ids": ["jobj_note", "jobj_star"], "origin": "user"}]
    assert ranger[0]["path"] == "/api/workspace/boards/default/dossier/ranger", "the active Board's Dossier"
    # Durabilité d'abord, par la route : la page n'archive rien elle-même.
    assert _commands(step) == []
    assert "jobj_note" not in r["drawn"] and "jobj_star" in r["drawn"]
    assert any("1 objet rangé dans le Dossier · 1 refus" in t and REFUSAL in t for t in r["toasts"]), r["toasts"]
    assert r["selection"] == ["jobj_star"], "the refused object stays selected, on the Board"
    _no_errors(step)


def test_ranger_refused_whole_or_kept_without_removal_leaves_the_representation(tmp_path):
    kept = {**DOSSIER, "jobj_note": {"rangeable": True, "stored": {"archived": False, "code": "dossier_changed_meanwhile",
            "message": "Le contenu a changé pendant le rangement : la version rangée est gardée, l'objet reste sur le Board."}}}
    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "seed": {**SEED, "rangerStatus": 409}, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], *OPEN_SELECTION, OPEN_ROW("ranger"),
            ["eval", "drawn", DRAWN, 600], ["eval", "toasts", TOASTS, 50]]},
        {"width": 1440, "height": 900, "seed": {**SEED, "dossier": kept}, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], *OPEN_SELECTION, OPEN_ROW("ranger"),
            ["eval", "drawn", DRAWN, 600], ["eval", "toasts", TOASTS, 50]]},
        {"width": 1440, "height": 900, "seed": {**SEED, "dossierActive": False}, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], *OPEN_SELECTION, ["eval", "rows", ROWS, 1000],
            OPEN_ROW("ranger"), ["eval", "open", "JarvisToolWheel.isOpen()", 50]]},
    ])
    whole, changed, inactive = (s["results"] for s in steps)
    assert "jobj_note" in whole["drawn"]
    assert any("Ranger agit seulement sur le Board affiché" in t for t in whole["toasts"]), whole["toasts"]
    assert "jobj_note" in changed["drawn"]
    assert any("gardé sans retrait" in t and "la version rangée est gardée" in t for t in changed["toasts"]), changed["toasts"]
    row = _rows(inactive["rows"])["ranger"]
    # Polish S05 8 : aperçu « rangeable » par objet, mais Board non affiché : rien n'est promis.
    assert row["disabled"] == "true"
    assert inactive["open"] is True and not [b for b in steps[2]["bodies"] if b["path"].endswith("/dossier/ranger")]
    for step in steps:
        _no_errors(step)


def test_masquer_is_one_patch_selection_and_never_reaches_the_dossier(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": [
        ["click", "pick", NODE.format("jobj_note"), 400], ["ctrlclick", "add", NODE.format("jobj_star"), 500],
        *OPEN_SELECTION, OPEN_ROW("hide"), ["eval", "drawn", DRAWN, 1200],
        *OPEN_SELECTION, ["eval", "rows", ROWS, 200],
    ]}])[0]
    r = step["results"]
    assert _commands(step) == [{"schema_version": 1, "op": "patch_selection", "selection": {"ids": ["jobj_note", "jobj_star"]},
                                "changes": {"visibility": "hidden"}}]
    assert not any("/dossier/ranger" in b["path"] for b in step["bodies"]), "Masquer never creates Dossier content"
    assert "jobj_note" not in r["drawn"] and "jobj_star" not in r["drawn"]
    assert _rows(r["rows"])["hidden"]["text"] == "Masqués (3)"
    _no_errors(step)


FOCUSED = "(document.activeElement&&document.activeElement.dataset&&document.activeElement.dataset.objectId)||null"


def test_after_masquer_or_retirer_the_focus_moves_but_nothing_unrelated_is_selected(tmp_path):
    """QA Slice 06, polish 1 : le voisin reçoit le focus, jamais la sélection."""

    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], ["ctrlclick", "add", NODE.format("jobj_star"), 500],
            *OPEN_SELECTION, OPEN_ROW("hide"), ["eval", "drawn", DRAWN, 1200],
            ["eval", "selection", SELECTION, 50], ["eval", "focused", FOCUSED, 50]]},
        {"width": 1440, "height": 900, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_doc"), 400],
            *OPEN_SELECTION, OPEN_ROW("remove"), ["click", "go", "#confirmGo", 1200],
            ["eval", "selection", SELECTION, 50], ["eval", "focused", FOCUSED, 50],
            *OPEN_SELECTION, ["eval", "rows", ROWS, 200]]},
    ])
    hidden, removed = steps[0]["results"], steps[1]["results"]
    assert "jobj_note" not in hidden["drawn"] and "jobj_star" not in hidden["drawn"]
    assert hidden["selection"] == [], "after Masquer the selection is empty, not the neighbour"
    assert hidden["focused"] not in (None, "jobj_note", "jobj_star"), "the focus still moves to a drawn neighbour"
    assert removed["selection"] == [], "after Retirer the selection is empty"
    assert removed["focused"] not in (None, "jobj_doc")
    assert "ranger" not in _rows(removed["rows"]), "the next wheel action has no target"
    for step in steps:
        _no_errors(step)


def test_changing_the_form_of_many_is_one_patch_and_carries_no_payload(tmp_path):
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": [
        ["click", "pick", NODE.format("jobj_note"), 400], ["ctrlclick", "add", NODE.format("jobj_reg"), 500],
        *OPEN_SELECTION, OPEN_ROW("form"), OPEN_ROW("rep:point"), ["eval", "drawn", DRAWN, 1000],
        ["eval", "shapes", "[...document.querySelectorAll('#sceneLayer .sc-point')].map(n=>n.dataset.objectId).sort()", 50],
    ]}])[0]
    sent = _commands(step)
    assert sent == [{"schema_version": 1, "op": "patch_selection", "selection": {"ids": ["jobj_note", "jobj_reg"]},
                     "changes": {"representation": "point"}}]
    assert all("payload" not in b for b in sent), "registry_artifact_id is never sent back"
    assert {"jobj_note", "jobj_reg"} <= set(step["results"]["shapes"])
    _no_errors(step)


def test_retirer_du_board_confirms_the_source_stays_and_archives_only_the_representation(tmp_path):
    dialog = r"""(()=>({title:document.getElementById('confirmTitle').textContent,
      lines:[...document.querySelectorAll('#confirmBody li')].map(l=>l.textContent),go:document.getElementById('confirmGo').textContent}))()"""
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": [
        ["click", "pick", NODE.format("jobj_doc"), 400], ["ctrlclick", "add", NODE.format("jobj_reg"), 500],
        *OPEN_SELECTION, OPEN_ROW("remove"), ["eval", "dialog", dialog, 100],
        ["click", "go", "#confirmGo", 1200], ["eval", "drawn", DRAWN, 100], ["eval", "toasts", TOASTS, 50],
    ]}])[0]
    r = step["results"]
    assert r["dialog"]["title"] == "Retirer 2 objets du Board ?" and r["dialog"]["go"] == "Retirer du Board"
    assert any("Les 2 documents source restent dans le Dossier" in line for line in r["dialog"]["lines"]), r["dialog"]
    assert _commands(step) == [{"schema_version": 1, "op": "archive_selection", "selection": {"ids": ["jobj_doc", "jobj_reg"]}}]
    # Jamais une suppression durable : ni l'Artifact du registre, ni le fichier de mémoire.
    assert not [c for c in step["calls"] if c.startswith("DELETE") or "/memory/" in c], step["calls"]
    assert "jobj_doc" not in r["drawn"] and "jobj_reg" not in r["drawn"]
    assert any("documents source restent dans le Dossier" in t for t in r["toasts"]), r["toasts"]
    _no_errors(step)


def test_a_registry_window_is_read_from_the_registry(tmp_path):
    body = f"(document.querySelector('{NODE.format('jobj_reg')} .sc-summary')||{{}}).textContent||''"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": [["eval", "body", body, 800]]}])[0]
    assert step["results"]["body"] == "Bonjour, ceci est la transcription du registre."
    assert f"GET /api/artifacts/{REG}" in step["calls"]
    _no_errors(step)


def test_keyboard_composes_a_selection_and_the_wheel_acts_on_it(tmp_path):
    focus = f"document.querySelector('{NODE.format('jobj_note')}').focus();document.activeElement.dataset.objectId"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": [
        ["eval", "focus", focus, 200], ["key", "first", " ", 200, 2],
        ["eval", "afterFirst", SELECTION, 50],
        ["eval", "move", f"document.querySelector('{NODE.format('jobj_star')}').focus();1", 200],
        ["eval", "afterMove", SELECTION, 50],
        ["key", "second", " ", 300, 2], ["eval", "afterSecond", SELECTION, 50],
        ["eval", "anchor", "document.querySelector('#toolWheel .tw-anchor').focus();1", 100],
        ["key", "open", "Enter", 300], ["key", "down", "ArrowDown", 200], ["key", "tree", "Enter", 700],
        ["eval", "rows", ROWS, 100], ["eval", "kept", SELECTION, 50],
    ]}])[0]
    r = step["results"]
    assert r["afterFirst"] == ["jobj_note"]
    assert r["afterMove"] == ["jobj_note"], "moving the focus keeps a keyboard selection"
    assert r["afterSecond"] == ["jobj_note", "jobj_star"]
    assert _rows(r["rows"])["selection-count"]["text"] == "2 objets sélectionnés"
    assert r["kept"] == ["jobj_note", "jobj_star"]
    _no_errors(step)


@pytest.mark.skipif(not EVIDENCE, reason="captures de la Slice seulement (JARVIS_S06_SELECTION_EVIDENCE_DIR)")
@pytest.mark.parametrize("size", SIZES)
def test_evidence_captures(tmp_path, size):
    w, h = size
    plan = [
        {"width": w, "height": h, "seed": SEED, "actions": [*OPEN_SELECTION, *_shot("01-selection-empty", size)]},
        {"width": w, "height": h, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], *OPEN_SELECTION, ["eval", "w", "1", 900],
            *_shot("02-selection-single", size)]},
        {"width": w, "height": h, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], ["ctrlclick", "add", NODE.format("jobj_star"), 500],
            *OPEN_SELECTION, ["eval", "w", "1", 900], *_shot("03-selection-mixed", size),
            OPEN_ROW("form"), *_shot("04-selection-form", size)]},
        {"width": w, "height": h, "seed": SEED, "actions": [
            *OPEN_SELECTION, OPEN_ROW("hidden"), *_shot("05-hidden-count", size)]},
        {"width": w, "height": h, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], *OPEN_SELECTION, OPEN_ROW("ranger"),
            ["eval", "w", "1", 600], *_shot("06-ranger-done", size)]},
        {"width": w, "height": h, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_star"), 400], *OPEN_SELECTION, ["eval", "w", "1", 900],
            *_shot("07-ranger-refused-row", size)]},
        {"width": w, "height": h, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_note"), 400], ["ctrlclick", "add", NODE.format("jobj_star"), 500],
            *OPEN_SELECTION, OPEN_ROW("ranger"), ["eval", "w", "1", 600], *_shot("08-ranger-partial-refusal", size)]},
        {"width": w, "height": h, "seed": SEED, "actions": [
            ["click", "pick", NODE.format("jobj_doc"), 400], ["ctrlclick", "add", NODE.format("jobj_reg"), 500],
            *OPEN_SELECTION, OPEN_ROW("remove"), *_shot("09-retirer-confirm", size),
            ["click", "go", "#confirmGo", 1000], *_shot("10-retirer-done", size)]},
    ]
    steps = _drive(tmp_path, plan)
    for step in steps:
        _no_errors(step)


def test_a_bare_hands_pointer_reaching_the_wheel_keeps_the_selection(tmp_path):
    """Bare Hands pilote la roue par un pointeur synthétique (`pointerId` 9001, jamais `isTrusted`) :
    l'appui de la main sur la roue ne défait pas la sélection, son appui dans le vide la vide toujours."""
    press = r"""(sel=>{const el=document.querySelector(sel);const r=el.getBoundingClientRect();
      const o={bubbles:true,cancelable:true,composed:true,pointerId:9001,pointerType:'pen',isPrimary:true,
        clientX:r.left+r.width/2,clientY:r.top+r.height/2,button:0,buttons:1};
      el.dispatchEvent(new PointerEvent('pointerdown',o));el.dispatchEvent(new PointerEvent('pointerup',{...o,buttons:0}));
      return JarvisScene.inspect().selection})"""
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": SEED, "actions": [
        ["click", "pick", NODE.format("jobj_note"), 400],
        ["eval", "onWheel", press + "('#toolWheel .tw-anchor')", 200],
        ["eval", "onVoid", press + "('#sceneLayer')", 200],
    ]}])[0]
    assert step["results"]["onWheel"] == ["jobj_note"]
    assert step["results"]["onVoid"] == []
    _no_errors(step)
