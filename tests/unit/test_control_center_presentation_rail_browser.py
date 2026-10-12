"""Le rail des presentations et la fenetre d'une presentation, mesures dans un vrai navigateur (refonte du display du mode presentation).

On compose la page **telle que `ControlCenter.index` la sert**, on la charge dans Chrome sans tete et l'on releve des rectangles, des attributs ARIA
et des styles **calcules**. Le relais `/api/presentation-studio/*` est remplace dans la page par un double en memoire (`_presentation_rail_browser.mjs`) :
la chaine reelle jusqu'a Core est prouvee par `test_presentation_studio_rail.py` (vrai Core, vrai magasin de fichiers).

Ce que ce fichier epingle : placement a droite de la palette, visibilite (Board de presentation, travail, pin), pastilles bleu / vert / orange, menu du
clic droit complet, masquer / afficher, archiver avec confirmation (annulable) et restaurable, renommer, clic = fenetre, Jouer, demandes d'ecran du
cerveau (et une demande perimee jamais rejouee), concentration automatique, rangement a gauche du Studio, echecs dits a l'ecran, petit ecran.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

import jarvis.runtime.control_center as cc

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
HARNESS = Path(__file__).parent / "_presentation_rail_browser.mjs"

CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)

BLUE, GREEN, ORANGE = "rgb(74, 163, 255)", "rgb(67, 214, 140)", "rgb(255, 162, 58)"


def _chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    pytest.skip("Chrome absent")


def _served_page(tmp_path: Path) -> Path:
    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    pairs = [
        (getattr(cc, name), getattr(cc, name.replace("_MARKER", "_FILE")))
        for name in dir(cc)
        if name.endswith("_SCRIPT_MARKER") and hasattr(cc, name.replace("_MARKER", "_FILE"))
    ]
    for marker, filename in pairs:
        html = html.replace(marker, (RUNTIME / filename).read_text(encoding="utf-8"))
    assert not [m for m, _ in pairs if m in html], "marqueurs non remplaces"
    assert "/*__CONTROL_CENTER_PRESENTATION_RAIL_JS__*/" not in html and "/*__CONTROL_CENTER_PRESENTATION_WINDOW_JS__*/" not in html
    html = re.sub(r'<iframe class="face"[^>]*></iframe>', '<div class="face"></div>', html)
    out = tmp_path / "served.html"
    out.write_text(html, encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    tmp = tmp_path_factory.mktemp("rail")
    done = subprocess.run([node, str(HARNESS), str(_served_page(tmp)), _chrome()], capture_output=True, text=True,
                          encoding="utf-8", timeout=420, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def r(run):
    return run["results"]


def names(read):
    return [i["name"] for i in read["items"]]


def test_no_exception_and_every_failure_is_logged(run):
    assert not [line for line in run["console"] if line.startswith("EXCEPTION")], run["console"]


def test_the_rail_stays_quiet_outside_a_presentation_board_when_nothing_works(r):
    assert r["auto_idle"]["visible"] is False and r["auto_idle"]["api"]["pref"] == "auto"


def test_the_rail_sits_right_of_the_palette_and_lists_three_visible_presentations_with_their_dot(r):
    board = r["board"]
    assert board["visible"] is True
    assert board["box"]["l"] >= board["paletteRight"]["r"] + 4, "a droite de la palette d'outils, sans la recouvrir"
    assert board["box"]["t"] >= 60 and board["box"]["b"] <= 900
    assert names(board) == ["Lancement produit aut…", "Bilan", "Roadmap"], "titre court, ordre de Core"
    assert [i["state"] for i in board["items"]] == ["working", "done", "problem"]
    assert [i["dot"] for i in board["items"]] == [BLUE, GREEN, ORANGE]
    assert board["items"][0]["dotAnim"] == "jvr-pulse" and board["items"][1]["dotAnim"] == "none"
    assert "disque plein" in board["items"][2]["full"] and "Lancement produit automne" in board["items"][0]["full"]
    assert [i["thumb"] for i in board["items"]] == ["LP", "BI", "RO"]
    assert board["folds"] == ["▸Masquées (1)", "▸Archivées (1)"] or [f.replace(" ", "") for f in board["folds"]] == ["▸Masquées(1)", "▸Archivées(1)"]
    assert board["voice"] == "listening", "la voix reste visible dans le rail"
    assert "disque plein" not in board["note"], "le message du probleme est dans l'infobulle, pas un bandeau permanent"


def test_the_context_menu_has_every_action_and_hide_moves_the_row_to_the_folded_group(r):
    menu = r["menu"]["menu"]
    assert [i["act"] for i in menu["items"]] == ["open", "edit", "play", "hide", "rename", "archive"]
    assert "Supprimer" in menu["items"][-1]["text"] and menu["head"] == "Bilan"
    assert r["after_hide"]["menu"] is None and "Bilan" not in names(r["after_hide"])
    assert any(w.endswith('/rail {"action":"hide"}') and "pst_" + "2".zfill(32) in w for w in r["after_hide"]["writes"])
    assert r["hidden_fold"]["folds"][0].startswith("▾") and "Bilan" in names(r["hidden_fold"])
    assert [i["dim"] for i in r["hidden_fold"]["items"] if i["name"] in ("Bilan", "Brouillon cache")] == ["true", "true"]


def test_archiving_asks_first_can_be_cancelled_and_is_restorable(r):
    dialog = r["archive_dialog"]["dialog"]
    assert "Roadmap" in dialog["title"] and "restaure" in dialog["text"] and dialog["buttons"] == ["Annuler", "Supprimer"]
    assert r["archive_cancelled"]["dialog"] is None
    assert not [w for w in r["archive_cancelled"]["writes"] if '"archive"' in w], "annuler n'ecrit rien"
    assert "Roadmap" not in names(r["archived"])
    assert any('"action":"archive"' in w for w in r["archived"]["writes"])
    assert r["archived"]["folds"][-1].replace(" ", "").endswith("(2)")


def test_rename_prefills_and_writes_the_trimmed_title(r):
    assert r["rename_dialog"]["dialog"]["input"] == "Bilan" and r["rename_dialog"]["dialog"]["title"] == "Renommer la présentation"
    assert "Bilan 2026" in names(r["renamed"]) and any('"title":"Bilan 2026"' in w for w in r["renamed"]["writes"])


def test_a_click_opens_variants_windowed_on_the_presentation_and_present_starts_a_run(r):
    """Slice 09 (native-studio-playback-fix): the floating window is retired; a click opens Variants, « Présenter » starts a run."""

    opens = r["opened"]["opens"]
    assert len(opens) == 1 and opens[0]["presentation_id"] == "pst_" + "1".zfill(32) and opens[0]["fullscreen"] is False
    assert r["opened"]["windowNode"] is False and r["opened"]["window"] is None, "no floating window in the page"
    assert r["played"]["commands"] and r["played"]["commands"][0]["verb"] == "start"
    assert r["played"]["commands"][0]["body"]["role"] == "user_presenter"


def test_the_brain_can_hide_and_show_the_rail_an_old_open_window_opens_nothing_and_a_stale_request_is_not_replayed(r):
    assert r["brain_open"]["opens"] == 0 and r["brain_open"]["window"] is None, "open_window is retired: the brain opens Variants through MCP"
    assert r["brain_hide"]["visible"] is False and r["brain_hide"]["api"]["pref"] == "hidden"
    assert r["brain_show"]["visible"] is True and r["brain_show"]["api"]["pref"] == "shown"
    assert r["stale_request"] is False


def test_work_on_a_presentation_is_shown_by_its_dot_and_opens_nothing_by_itself(r):
    assert r["focus"]["opens"] == 0 and r["focus"]["window"] is None
    assert r["focus"]["items"][1]["state"] == "working" and r["focus"]["items"][1]["dot"] == BLUE


def test_the_studio_docks_the_rail_to_the_left_and_releases_it(r):
    assert r["studio"]["studioClass"] is True and r["studio"]["box"]["l"] == 8 and r["studio"]["box"]["t"] == 8
    assert r["studio"]["zRail"] == "9100"
    assert r["studio_closed"]["studioClass"] is False and r["studio_closed"]["box"]["l"] > 80


def test_failures_are_said_on_screen_and_a_lost_relay_is_not_hidden(r):
    assert "impossible" in r["write_failed"]["note"] and "presentation_studio_variant_in_playback" in r["write_failed"]["note"]
    assert "injoignable" in r["lost"]["note"]


def test_the_rail_fits_a_narrow_screen(r):
    box = r["narrow"]["box"]
    assert box is not None and box["r"] <= 375 and box["b"] <= 700


def test_the_docked_rail_slims_down_to_tiles_on_a_narrow_screen(r):
    narrow = r["studio_narrow"]
    assert narrow["studioClass"] is True and narrow["slim"] is True and narrow["box"]["w"] <= 50 and narrow["box"]["l"] == 8
    assert r["studio_tiny"]["visible"] is False, "below 900 px the Studio keeps the whole screen"
