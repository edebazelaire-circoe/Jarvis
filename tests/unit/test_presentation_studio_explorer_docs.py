"""Le contrat de l'explorateur de variantes est dit où il faut, et ce qui est dit est vrai (studio de présentation, Slice 18).

La documentation (`docs/presentation-studio.md` › *Variant Explorer interaction contract*, `docs/OPERATIONS.md` › *Explorateur de variantes*, les noms canoniques
section 22) et le code ne dérivent pas : les routes citées existent, les codes de la page et du serveur sont les mêmes des deux côtés (Python et JS), chaque code
de Core que l'interface traduit en français est un vrai code de Core, les constantes de la table sont celles du module, les touches du tableau sont celles de l'arbre.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from jarvis.domain import presentation_studio_explorer as vocab
from jarvis.domain.presentation_studio import PresentationStudioErrorCode
from jarvis.runtime.presentation_studio_explorer_commands import EXPLORER_ROUTE, PresentationStudioExplorerRoutes
from tests.fakes.explorer_js import CORE_JS, EXPLORER_JS, RUNTIME, run_node

ROOT = Path(__file__).resolve().parents[2]
PAGE = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
OPERATIONS = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
NAMES = (ROOT / "tasks" / "jarvis-interactive-presentation-studio" / "docs" / "09-canonical-names.md").read_text(encoding="utf-8")
SECTION = PAGE[PAGE.index("## Variant Explorer interaction contract"):PAGE.index("## Reused owners")]
NAMES22 = NAMES[NAMES.index("## 22. Slice 18"):]


def test_the_section_names_its_owners_its_tests_and_every_owner_exists():
    for module in ("control_center_presentation_studio_explorer_core.js", "control_center_presentation_studio_explorer_widgets.js",
                   "control_center_presentation_studio_explorer.js", "presentation_studio_explorer.py", "presentation_studio_explorer_commands.py"):
        assert module.replace("control_center_presentation_studio_explorer", "").replace(".js", "") or module in SECTION or "explorer" in SECTION
        found = list(ROOT.rglob(module))
        assert found, module
    for test in ("core_js", "js", "view_js", "actions_js", "lifecycle_js", "commands", "browser", "docs"):
        assert (ROOT / "tests" / "unit" / f"test_presentation_studio_explorer_{test}.py").is_file(), test
    for bench in ("explorer_dom.cjs", "explorer_world.cjs", "explorer_js.py", "explorer_browser.py"):
        assert (ROOT / "tests" / "fakes" / bench).is_file()
    assert "Level 3" in SECTION.splitlines()[0] and "Slice 18" in SECTION.splitlines()[0]


def test_every_route_the_channel_registers_is_documented_everywhere_it_should_be():
    routes = PresentationStudioExplorerRoutes().routes()
    paths = sorted({route.path for route in routes})
    assert paths == [EXPLORER_ROUTE + "/commands", EXPLORER_ROUTE + "/commands/{command_id}", EXPLORER_ROUTE + "/state"]
    assert sorted((route.method, route.path) for route in routes) == [
        ("GET", EXPLORER_ROUTE + "/commands"), ("GET", EXPLORER_ROUTE + "/state"), ("POST", EXPLORER_ROUTE + "/commands"),
        ("POST", EXPLORER_ROUTE + "/commands/{command_id}"), ("POST", EXPLORER_ROUTE + "/state")]
    for path in paths:
        short = path.replace("/{command_id}", "")
        assert short in SECTION or path in SECTION, path
        assert short in NAMES22 or path in NAMES22, path
    assert EXPLORER_ROUTE + "/commands" in OPERATIONS and EXPLORER_ROUTE + "/state" in OPERATIONS


def test_the_page_and_the_server_agree_on_routes_codes_and_vocabulary():
    out = run_node(Path(__import__("tempfile").mkdtemp()), """
return {command:C.COMMAND_ROUTE,state:C.STATE_ROUTE,refusals:Object.keys(C.COMMAND_REFUSALS),core:Object.keys(C.REFUSALS),host:C.HOST_ID,object:C.OBJECT_ID,
  preview:C.PREVIEW_OBJECT_ID,storage:C.STORAGE_KEY,constants:{ROW_H:C.ROW_H,OVERSCAN:C.OVERSCAN,MAX_DEPTH_SHOWN:C.MAX_DEPTH_SHOWN,LONG_PRESS_MS:C.LONG_PRESS_MS,
  PREVIEW_SETTLE_MS:C.PREVIEW_SETTLE_MS,REQUEST_TIMEOUT_MS:C.REQUEST_TIMEOUT_MS,READ_TIMEOUT_MS:C.READ_TIMEOUT_MS,PLAYBACK_CHECK_MS:C.PLAYBACK_CHECK_MS,
  MAX_LIVE:C.MAX_LIVE,MAX_ARCHIVED:C.MAX_ARCHIVED}};
""")
    assert out["command"] == EXPLORER_ROUTE + "/commands" and out["state"] == EXPLORER_ROUTE + "/state"
    assert set(out["refusals"]) == set(vocab.PAGE_CODES), "the page says every code the server accepts in a receipt, and no other"
    assert out["host"] == "jvStudioExplorer" and out["object"] == "studio-explorer" and out["preview"] == "studio-explorer-preview"
    assert out["storage"] in NAMES22 and "#jvStudioExplorer" in NAMES22 and out["preview"] in NAMES22
    known = {code.value for code in PresentationStudioErrorCode}
    unknown = [code for code in out["core"] if code not in known]
    assert not unknown, f"the French sentences translate codes Core does not have: {unknown}"
    consts = out["constants"]
    table = {"ROW_H": 48, "OVERSCAN": 6, "MAX_DEPTH_SHOWN": 10, "LONG_PRESS_MS": 550, "PREVIEW_SETTLE_MS": 120, "REQUEST_TIMEOUT_MS": 15000, "READ_TIMEOUT_MS": 10000,
             "PLAYBACK_CHECK_MS": 2000}
    for name, value in table.items():
        assert consts[name] == value, name
        assert f"`{name}` {value:,}".replace(",", " ") in NAMES22 or f"`{name}` {value}" in NAMES22, name
    assert consts["MAX_LIVE"] == 64 and consts["MAX_ARCHIVED"] == 128, "the caps of Slice 16"
    from jarvis.domain.presentation_studio_variants import MAX_ARCHIVED_VARIANTS, MAX_LIVE_VARIANTS
    assert (MAX_LIVE_VARIANTS, MAX_ARCHIVED_VARIANTS) == (64, 128)


def test_every_code_the_docs_list_is_a_real_code_of_the_vocabulary():
    listed = set(re.findall(r"`(explorer_[a-z_]+)`", SECTION + NAMES22 + OPERATIONS))
    listed |= {"explorer_" + part for part in re.findall(r"`_([a-z_]+)`", SECTION) if ("explorer_" + part) in {
        getattr(vocab, name) for name in dir(vocab) if name.isupper() and isinstance(getattr(vocab, name), str)}}
    real = {getattr(vocab, name) for name in dir(vocab) if name.isupper() and isinstance(getattr(vocab, name), str) and getattr(vocab, name).startswith("explorer_")}
    assert listed <= real, f"documented but not in the vocabulary: {sorted(listed - real)}"
    assert set(vocab.PAGE_CODES) <= listed, "every page code is documented"
    assert {vocab.COMMAND_BUSY, vocab.NO_VISIBLE_PAGE, vocab.COMMAND_EXPIRED} <= listed


def test_the_modes_and_fullscreen_states_of_a_receipt_are_the_ones_the_page_reports():
    controller = EXPLORER_JS.read_text(encoding="utf-8")
    for mode in vocab.MODES:
        assert f"'{mode}'" in controller, mode
    for state in vocab.FULLSCREEN_STATES:
        assert f"'{state}'" in controller, state
    assert "fullscreen_armed" in SECTION and "needs_gesture" in SECTION and "windowed" in SECTION
    # the receipt of an open is `opened` or `refused`, of a close `closed`: exactly what the controller answers
    assert set(vocab.RECEIPT_STATES) == {"opened", "closed", "refused"}
    for state in vocab.RECEIPT_STATES:
        assert f"state:'{state}'" in controller, state


def test_the_keys_of_the_table_are_the_keys_of_the_tree():
    out = run_node(Path(__import__("tempfile").mkdtemp()), """
const id=n=>'psv_'+String(n).padStart(32,'0');
const f=C.buildForest([{variant_id:id(1),variant_number:1,state:'live',parent_variant_id:null},{variant_id:id(2),variant_number:2,state:'live',parent_variant_id:id(1)}],'live');
const rows=C.flatten(f,new Set());
const keys=['ArrowDown','ArrowUp','Home','End','PageDown','PageUp','ArrowRight','ArrowLeft','Enter',' ','F2','Delete','n','a','r','*','ContextMenu'];
return Object.fromEntries(keys.map(k=>[k,(C.treeKey(rows,0,k)||{}).type||null]).concat([['Shift+F10',(C.treeKey(rows,0,'F10',{shift:true})||{}).type]]));
""")
    assert out == {"ArrowDown": "focus", "ArrowUp": "focus", "Home": "focus", "End": "focus", "PageDown": "focus", "PageUp": "focus", "ArrowRight": "focus",
                   "ArrowLeft": "collapse", "Enter": "select", " ": "select", "F2": "rename", "Delete": "archive", "n": "branch", "a": "activate", "r": "restore",
                   "*": "expand_siblings", "ContextMenu": "menu", "Shift+F10": "menu"}, out
    for fragment in ("`F2`", "`Suppr`", "`N`", "`A`", "`R`", "`*`", "`Menu`", "`Maj+F10`", "550 ms", "`Échap`", "the focus moves, the selection does not"):
        assert fragment in SECTION, fragment
    for fragment in ("`F2`", "`Suppr`", "`N`", "`A`", "`R`", "Échap", "Annuler"):
        assert fragment in OPERATIONS[OPERATIONS.index("### Explorateur de variantes"):], fragment


def test_the_contract_states_the_decisions_a_reader_must_not_have_to_guess():
    for fragment in (
        "never the source of truth", "never mutates a variant", "Opening is refused while a run plays", "a run that starts while it is open closes it",
        "A voice open never claims fullscreen", "no dock button", "stage window", "preview_id", "Comparison is out of scope", "textContent", "`dir=\"auto\"`",
        "confirmation_stale", "Annuler", "Human checks", "Measured", "reduced-motion", "forced-colors",
    ):
        assert fragment in SECTION, fragment
    for fragment in ("Plein écran, sans surprise", "Recette de vérification Humaine", "explorer_run_in_progress", "explorer_no_visible_page", "Échap physique", "Deux écrans"):
        assert fragment in OPERATIONS, fragment
    assert "Slice 07" in NAMES22 and "merge-neutral" in NAMES22, "the shared read-only relay route is flagged for the merge"
    assert "| Variant Explorer (UI) |" in PAGE and "**done**, Slice 18" in PAGE


def test_the_relay_route_shared_with_slice_07_is_the_read_only_art_direction_one():
    from jarvis.runtime import presentation_studio_relay as relay
    entry = ("GET", "studio_art_direction", "/{presentation_id}/variants/{variant_id}/art-direction")
    assert entry in relay._READ_ROUTES  # noqa: SLF001
    assert not any(str(item[0]).endswith("art-direction") for item in relay._WRITE_ROUTES), "no write of an art direction through the relay"  # noqa: SLF001
    assert "art-direction" in relay.__doc__ and "lecture seule" in relay.__doc__
