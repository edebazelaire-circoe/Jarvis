"""Le rail des presentations et la fenetre d'une presentation, mesures dans un vrai navigateur (refonte du display du mode presentation).

On compose la page **telle que `ControlCenter.index` la sert**, on la charge dans Chrome sans tete et l'on releve des rectangles, des attributs ARIA
et des styles **calcules**. Le relais `/api/presentation-studio/*` est remplace dans la page par un double en memoire (`_presentation_rail_browser.mjs`) :
la chaine reelle jusqu'a Core est prouvee par `test_presentation_studio_rail.py` (vrai Core, vrai magasin de fichiers).

Ce que ce fichier epingle : une BANDE pleine hauteur au bord droit (refonte du 2026-10-29 : largeur fixe, repliee = disparue, un bouton dans `#railDock`,
cartes = vignette + titre, archives cachees par defaut, suppression definitive de tout element, deux bandes avec le Chat toujours a droite), cartes avec
apercu ou vignette typee, etat par marque a forme propre, visibilite (Board de presentation, travail, pin), pastilles bleu / vert / orange, menu du
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

#: The shell's semantic tokens (docs/control-center-shell.md › Tokens, Slice 07): --sem-working, --sem-done (= --ok), --sem-problem, --sem-review.
BLUE, GREEN, ORANGE, YELLOW = "rgb(77, 163, 255)", "rgb(104, 224, 160)", "rgb(255, 106, 77)", "rgb(255, 209, 102)"


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


def test_the_rail_is_a_full_height_band_at_the_right_edge_and_lists_three_visible_presentations_with_their_dot(r):
    """2026-10-29 : plus une carte flottante : une bande de 272 px, du haut au bas de l'ecran, au bord droit ; une carte = vignette + titre."""

    board = r["board"]
    assert board["visible"] is True
    assert board["box"]["l"] >= board["paletteRight"]["r"] + 4, "never over the left column"
    assert board["box"]["r"] == 1440 and board["box"]["w"] == 272 and board["box"]["t"] == 0 and board["box"]["b"] == 900, "full-height band, --shell-rail-w"
    assert names(board) == ["Lancement produit automne", "Bilan", "Roadmap"], "titre court (40), ordre de Core"
    assert [i["state"] for i in board["items"]] == ["working", "done", "problem"]
    assert [i["dot"] for i in board["items"]] == [BLUE, GREEN, ORANGE]
    assert board["items"][0]["dotAnim"] == "jvr-pulse" and board["items"][1]["dotAnim"] == "none"
    assert "disque plein" in board["items"][2]["full"] and "Lancement produit automne" in board["items"][0]["full"]
    assert "problème" in board["items"][2]["label"] and "terminé" in board["items"][1]["label"], "the state is said by the ARIA label, not by a line of text"
    assert [i["texts"] for i in board["items"]] == [["jvr-name"]] * 3, "a card is its thumbnail and its title, nothing else"
    assert [i["thumb"] for i in board["items"]] == [{"kind": "placeholder", "badge": "Remotion", "img": None}] * 3, "no render: typed placeholder"
    assert [f.replace(" ", "") for f in board["folds"]] == ["▸Masquées(1)"], "archived presentations are not a fold any more: hidden by default"
    assert board["archBtn"] == {"text": "Afficher les archivés (1)", "pressed": "false"}
    assert "disque plein" not in board["note"], "le message du probleme est dans l'infobulle, pas un bandeau permanent"


def test_the_context_menu_has_every_action_and_hide_moves_the_row_to_the_folded_group(r):
    menu = r["menu"]["menu"]
    assert [i["act"] for i in menu["items"]] == ["open", "studio", "edit", "play", "hide", "rename", "archive", "delete"]  # « Remotion Studio… » (Slice 11)
    assert menu["items"][-2]["text"] == "Archiver…" and menu["items"][-1]["text"] == "Supprimer définitivement…" and menu["head"] == "Bilan"
    assert r["after_hide"]["menu"] is None and "Bilan" not in names(r["after_hide"])
    assert any(w.endswith('/rail {"action":"hide"}') and "pst_" + "2".zfill(32) in w for w in r["after_hide"]["writes"])
    assert r["hidden_fold"]["folds"][0].startswith("▾") and "Bilan" in names(r["hidden_fold"])
    assert [i["dim"] for i in r["hidden_fold"]["items"] if i["name"] in ("Bilan", "Brouillon cache")] == ["true", "true"]


def test_archiving_asks_first_in_the_page_dialog_can_be_cancelled_and_is_restorable(r):
    dialog = r["archive_dialog"]["confirm"]
    assert "Roadmap" in dialog["title"] and "restaure" in dialog["text"] and dialog["buttons"] == ["Annuler", "Archiver"], "the page's .cdialog, never confirm()"
    assert r["archive_dialog"]["dialog"] is None, "the rail's own dialog is only a fallback"
    assert r["archive_cancelled"]["confirm"] is None
    assert not [w for w in r["archive_cancelled"]["writes"] if '"archive"' in w], "annuler n'ecrit rien"
    assert "Roadmap" not in names(r["archived"])
    assert any('"action":"archive"' in w for w in r["archived"]["writes"])
    assert r["archived"]["archBtn"]["text"] == "Afficher les archivés (2)", "an archived presentation is hidden until the footer button shows it"


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


def test_studio_docks_left_of_rail(r):
    """Slice 07 (D10): the docking is mirrored. The rail is the right column beside Variants (rank 9100), Variants stops at its left edge."""

    assert r["studio"]["studioClass"] is True and r["studio"]["box"]["r"] == 1440 - 8 and r["studio"]["box"]["t"] == 8
    assert r["studio"]["zRail"] == "9100" and r["studio"]["density"] == "compact"
    assert r["studio_closed"]["studioClass"] is False and r["studio_closed"]["box"]["r"] == 1440 and r["studio_closed"]["box"]["t"] == 0
    for theme in ("circuit-board", "cosmos"):
        studio = r["studio_" + theme]
        assert studio["explorer"]["l"] == 0 and studio["explorer"]["r"] <= studio["box"]["l"], (theme, studio["explorer"], studio["box"])
        assert studio["box"]["r"] == 1440 - 8 and [i["state"] for i in studio["items"]][:3] == ["working", "unreviewed", "problem"]


def test_failures_are_said_on_screen_and_a_lost_relay_is_not_hidden(r):
    assert "impossible" in r["write_failed"]["note"] and "presentation_studio_variant_in_playback" in r["write_failed"]["note"]
    assert "injoignable" in r["lost"]["note"]


def test_the_rail_fits_a_narrow_screen(r):
    box = r["narrow"]["box"]
    assert box is not None and box["r"] <= 375 and box["b"] <= 700
    assert r["narrow"]["density"] == "full" and box["r"] - box["l"] == 272, "no tab, no strip: the band keeps its fixed width"


def test_at_700_px_and_below_the_rail_stays_folded_until_the_user_opens_it(r):
    assert r["narrow_auto"]["visible"] is False and r["narrow_auto"]["tab"]["expanded"] == "false", "no automatic band over a phone-sized scene"
    assert r["zones"]["600x800_auto"]["rail"] is None and r["zones"]["600x800"]["rail"] is not None, "the button opens it"


def test_the_docked_rail_keeps_its_compact_column_on_a_narrow_screen(r):
    narrow = r["studio_narrow"]
    assert narrow["studioClass"] is True and narrow["density"] == "compact" and narrow["box"]["w"] <= 172 and narrow["box"]["r"] == 1000 - 8
    assert r["studio_tiny"]["visible"] is False, "below 900 px the Studio keeps the whole screen"


# ------------------------------------------------------------------ Slice 07 (handoff orbital, D10) : rail actif a droite


def _overlap(a, b) -> bool:
    return bool(a and b) and min(a["r"], b["r"]) - max(a["l"], b["l"]) > 0.5 and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 0.5


def test_rail_band_overlaps_neither_the_launcher_nor_the_buttons_nor_the_left_column(r):
    zones = r["zones"]
    for size in ("1440x900", "1280x720", "900x600", "600x800"):
        z = zones[size]
        for other in ("dock", "railDock", "pills", "palette", "wheel"):
            assert not _overlap(z["rail"], z[other]), (size, other, z["rail"], z[other])
        # 700 px et moins : de `--shell-panel-top` (88) à `--shell-panel-bottom` (68), comme un panneau latéral ; au-dessus, toute la hauteur.
        full = z["vw"] > 700
        assert z["rail"]["r"] == z["vw"] and z["rail"]["t"] == (0 if full else 88) and z["rail"]["b"] == (z["vh"] if full else z["vh"] - 68), (size, "at the right edge", z["rail"])
        assert z["rail"]["r"] - z["rail"]["l"] == 272, (size, "fixed width")
        assert z["density"] == "full" and z["radius"] == "0px" and z["resize"] == "none", (size, "a band, not a rounded floating card")
        assert z["scroll"]["overflowY"] == "auto", "one scrolling list"
        # les boutons des rails restent atteignables : a gauche de la bande, hors d'elle
        assert z["railDock"]["r"] <= z["rail"]["l"] and z["railDock"]["l"] > z["vw"] / 3, (size, z["railDock"], z["rail"])
        assert z["dock"]["l"] == 18 and z["dock"]["t"] == 18 if z["vw"] > 700 else z["dock"]["l"] == 10, (size, "the launcher is top-left", z["dock"])


def test_folded_means_gone_the_button_unfolds_and_the_choice_is_remembered(r):
    assert r["open_before"]["visible"] is True and r["open_before"]["tab"]["expanded"] == "true"
    folded = r["folded"]
    assert folded["visible"] is False and folded["box"] is None and folded["hiddenAttr"] is True, "folded: the band disappears entirely"
    assert folded["tab"]["expanded"] == "false" and folded["tab"]["box"] is not None and folded["railDock"]["r"] > 1440 - 60, "only the button remains, at the right edge"
    assert "Déplier" in folded["tab"]["label"] and folded["store"]["open"] is False
    assert r["folded_reload"]["visible"] is False, "remembered across a reload (it would otherwise reopen: a presentation Board)"
    assert r["unfolded"]["visible"] is True and r["unfolded"]["tab"]["expanded"] == "true" and r["unfolded"]["store"]["open"] is True
    assert r["unfolded"]["box"]["r"] == 1440 and r["unfolded"]["railDock"]["r"] <= r["unfolded"]["box"]["l"], "the buttons step left of the open band"
    assert r["refolded"]["visible"] is False and r["refolded"]["tab"]["expanded"] == "false"


def test_two_bands_side_by_side_with_the_chat_always_rightmost(r):
    both = r["two_rails"]
    chat, rail, tab, chat_tab = both["chatBox"], both["box"], both["tab"], both["chatTab"]
    assert both["visible"] is True and both["chatPanel"] is not None
    assert chat["r"] == 1440 and chat["l"] == 1440 - 500 and chat["t"] == 0 and chat["b"] == 900, "the Chat is a full-height band at the right edge"
    assert rail["r"] == chat["l"] and rail["l"] == chat["l"] - 272 and rail["t"] == 0 and rail["b"] == 900, "the rail sits just left of the Chat"
    assert chat["radius"] == "0px", "the same band skin, no rounded card"
    assert both["railDock"]["r"] <= rail["l"], "the two buttons stay left of the leftmost band"
    assert tab["box"]["t"] < chat_tab["box"]["t"] and abs(tab["box"]["l"] - chat_tab["box"]["l"]) < 1, "Présentations above, Chat just below"
    assert chat_tab["expanded"] == "true" and tab["expanded"] == "true" and chat_tab["text"] == "", "an icon button, no « CHAT » text"
    assert r["chat_closed"]["chatPanel"] is None and r["chat_closed"]["box"]["r"] == 1440, "closing the Chat puts the rail back at the edge"
    only = r["chat_only"]
    assert only["visible"] is False and only["chatPanel"] is not None and only["chatPanel"]["r"] == 1440, "Chat alone, rail folded"
    # étroit : une seule bande à la fois
    assert r["narrow_rail"]["visible"] is True and r["narrow_rail"]["chatPanel"] is None
    assert r["narrow_chat"]["visible"] is False and r["narrow_chat"]["chatPanel"] is not None, "under 900 px opening the Chat folds the rail"
    assert r["narrow_rail_again"]["visible"] is True and r["narrow_rail_again"]["chatPanel"] is None, "and opening the rail closes the Chat"


def test_archived_presentations_are_hidden_until_the_footer_button_shows_them(r):
    hidden = r["archived_hidden"]
    assert hidden["domCards"] == 0 and "Ancienne" not in names(hidden) and hidden["archived"] == [] and hidden["archivedHead"] is None
    assert hidden["archBtn"] == {"text": "Afficher les archivés (1)", "pressed": "false"}
    shown = r["archived_shown"]
    assert shown["archived"] == ["Ancienne"] and shown["archivedHead"] == "Archivés (1)", "a section « Archivés »"
    assert shown["archBtn"] == {"text": "Masquer les archivés", "pressed": "true"}
    assert [i["dim"] for i in shown["items"] if i["name"] == "Ancienne"] == ["true"], "an archived card is drawn dim, in its own section"
    again = r["archived_hidden_again"]
    assert again["archived"] == [] and again["archBtn"]["pressed"] == "false"


def test_a_presentation_is_deleted_for_good_after_the_page_dialog_archive_plan_and_purge(r):
    assert [i["act"] for i in r["delete_menu"]["menu"]["items"]][-2:] == ["archive", "delete"]
    dialog = r["delete_dialog"]["confirm"]
    assert dialog["title"] == "Supprimer définitivement « Roadmap » ?" and dialog["danger"] is True
    assert dialog["buttons"] == ["Annuler", "Supprimer définitivement"] and "Irréversible" in dialog["text"]
    assert r["delete_dialog"]["dialog"] is None, "the page's .cdialog, never confirm() / alert()"
    cancelled = r["delete_cancelled"]
    assert cancelled["confirm"] is None and cancelled["rows"] == 5 and cancelled["purges"] == [] and not [w for w in cancelled["writes"] if '"archive"' in w]
    deleted = r["deleted"]
    pid = "pst_" + "3".zfill(32)
    assert "Roadmap" not in names(deleted) and "Roadmap" not in deleted["rows"]
    steps = [w for w in deleted["writes"] if "purge" in w or '"archive"' in w]
    assert steps[0].endswith('/rail {"action":"archive"}') and steps[1].startswith("/rail/purge-plan ") and steps[2].startswith("/rail/purge "), steps
    assert deleted["purges"][0] == "plan " + json.dumps({"presentation_ids": [pid]}, separators=(",", ":"))
    assert deleted["purges"][1].startswith("purge ") and '"confirmed":true' in deleted["purges"][1] and '"confirmation":"ppk_' in deleted["purges"][1]
    assert "Supprimée définitivement" in deleted["note"]


def test_a_refused_deletion_is_said_and_leaves_the_presentation_archived_and_restorable(r):
    failed = r["delete_failed"]
    assert "Suppression impossible" in failed["note"] and "lecture" in failed["note"] and "archivée" in failed["note"], failed["note"]
    assert ["Bilan", True] in failed["rows"], "the archive step happened, the purge did not: nothing is lost"


def test_delete_key_and_the_trash_of_an_archived_card_use_the_same_confirmation(r):
    key = r["delete_key"]["confirm"]
    assert key and key["title"].startswith("Supprimer définitivement « Bilan"), "Delete on a focused card asks first"
    trash = r["trash_archived"]
    assert "Bilan" not in trash["rows"] and "Ancienne" in trash["rows"], "only the chosen archived card is purged"
    steps = [w for w in trash["writes"] if "purge" in w]
    assert steps and steps[-1].startswith("/rail/purge ") and steps[-2].startswith("/rail/purge-plan "), steps
    assert all(i["del"] for i in r["cards_cosmos"]["items"]), "every card carries its trash button"


def test_every_workspace_element_is_deletable_with_a_confirmation_and_a_cascade_when_needed(r):
    dialog = r["ws_delete_dialog"]["confirm"]
    assert dialog["title"] == "Supprimer définitivement « Capture d’écran » ?" and dialog["danger"] is True and "Irréversible" in dialog["text"]
    assert r["ws_delete_cancelled"]["confirm"] is None and r["ws_delete_cancelled"]["wsDeletes"] == [], "annuler ne supprime rien"
    assert r["ws_deleted"]["wsDeletes"] == ["DELETE /api/artifacts/jart_" + "c" * 32]
    assert [i["name"] for i in r["ws_deleted"]["wsItems"]] == ["Roadmap Q4.pptx", "docs.google.com", "demo.mp4", "contrat.pdf"], "the image is gone from the rail"
    assert [i["act"] for i in r["ws_menu"]["menu"]["items"]][-1] == "ws-delete" and r["ws_menu"]["menu"]["items"][-1]["text"] == "Supprimer définitivement…"
    again = r["ws_dependents_dialog"]["confirm"]
    assert again["title"] == "Supprimer aussi ce qui en dérive ?" and again["buttons"][1] == "Tout supprimer", "a second consent for the derived ones"
    assert r["ws_cascaded"]["wsDeletes"][-2:] == ["DELETE /api/artifacts/jart_" + "d" * 32,
                                                  "DELETE /api/artifacts/jart_" + "d" * 32 + "?cascade=true"]
    assert len(r["ws_cascaded"]["wsItems"]) == 3
    assert "encore en cours d’acquisition" in r["ws_refused"]["note"] and len(r["ws_refused"]["wsItems"]) == 3, "a refusal is said and nothing disappears"


def test_cards_show_real_preview_typed_placeholder_and_every_state_in_both_themes(r):
    for theme in ("circuit-board", "cosmos"):
        cards = r["cards_" + theme]
        assert cards["theme"] == theme
        items = {i["name"]: i for i in cards["items"]}
        assert [i["state"] for i in cards["items"]] == ["working", "unreviewed", "problem", "done", "unknown"]
        assert all(i["texts"] == ["jvr-name"] for i in cards["items"]), "a card is a thumbnail and a title"
        words = ("travaille", "revoir", "problème", "terminé", "inconnu")
        assert [w in i["label"] for w, i in zip(words, cards["items"])] == [True] * 5, "each state is said in words by the ARIA label"
        assert [i["dot"] for i in cards["items"][:4]] == [BLUE, YELLOW, ORANGE, GREEN] and cards["items"][4]["dotBorder"] == "dashed"
        assert items["Roadmap"]["dotShape"].startswith("polygon"), "problem keeps its own shape, never a yellow review dot"
        assert items["Lancement produit automne"]["thumb"] == {"kind": "image", "badge": "Remotion", "img": {"ok": True, "payload": True}}
        assert items["Bilan"]["thumb"]["img"]["ok"] is True
        assert items["Notes de recherche"]["thumb"] == {"kind": "placeholder", "badge": "Slidecar", "img": None}
        assert "Remotion" in items["Architecture technique"]["label"] and "Modifiée il y a" in items["Bilan"]["full"], "type and age live in the tooltip, not on the card"
        assert all(i["more"] for i in cards["items"])
        # the presentations' stills (and, Stage B, the Board's screenshot): only the bounded payload route is read
        assert {"jart_" + "a" * 32, "jart_" + "b" * 32} <= set(cards["payloads"]) <= {"jart_" + "a" * 32, "jart_" + "b" * 32, "jart_" + "c" * 32}
    narrow = r["narrow_cosmos"]
    assert narrow["density"] == "full" and narrow["box"]["w"] == 272, "at 1000 px the band is unchanged: no 72 px strip"


def test_an_unreadable_preview_falls_back_to_the_typed_placeholder_and_is_logged(run, r):
    thumbs = [i["thumb"]["kind"] for i in r["broken_preview"]["items"]]
    assert thumbs == ["placeholder"] * 5
    assert [line for line in run["console"] if "preview_failed" in line], "the failure is in the journal"


def test_context_actions_preserved(r):
    assert [i["act"] for i in r["more_menu"]["menu"]["items"]] == ["open", "studio", "edit", "play", "hide", "rename", "archive", "delete"], "« ⋯ » opens the same menu"
    assert r["more_menu"]["menu"]["box"]["r"] <= r["more_menu"]["box"]["l"] + 8, "the menu opens left of the right rail"
    assert [i["act"] for i in r["review_menu"]["menu"]["items"]] == ["open", "studio", "edit", "play", "hide", "rename", "review", "archive", "delete"]
    assert [w for w in r["reviewed"]["writes"] if '"review"' in w] == ['/presentations/pst_' + "2".zfill(32) + '/rail {"action":"review"}']
    assert [i["state"] for i in r["reviewed"]["items"]][1] == "done", "seen: green again, re-read from Core"
    opened = r["open_reviews"]
    assert opened["opens"][-1]["presentation_id"] == "pst_" + "2".zfill(32)
    assert len([w for w in opened["writes"] if '"review"' in w]) == 2, "opening from the rail is reviewing it (one more write)"


def test_brain_show_hide_rail_and_display_state(r):
    assert r["brain_hide"]["visible"] is False and r["brain_hide"]["api"]["pref"] == "hidden"
    assert r["brain_hide"]["reports"][-1]["rail_visible"] is False, "the page reports what it shows"
    assert r["brain_show"]["visible"] is True and r["brain_show"]["api"]["pref"] == "shown"
    assert r["brain_show"]["reports"][-1]["rail_visible"] is True and r["brain_show"]["reports"][-1]["applied_seq"] == 3


# ------------------------------------------------------------------ Slice 07, etape B : Artifacts du Board actif (adaptateur pur)


def test_board_linked_artifacts_are_typed_cards_and_a_board_switch_drops_them(r):
    items = r["board_items"]["wsItems"]
    assert r["board_items"]["wsHead"].replace(" ", "") == "▾SurceBoard(5)"
    assert [(i["name"], i["state"], i["thumb"]["kind"], i["thumb"]["badge"]) for i in items] == [
        ("Capture d’écran", "done", "image", "Capture"),
        ("Roadmap Q4.pptx", "done", "placeholder", "PowerPoint"),
        ("docs.google.com", "done", "placeholder", "Google Slides"),
        ("demo.mp4", "working", "placeholder", "Vidéo"),
        ("contrat.pdf", "problem", "placeholder", "PDF")], "no yellow for Board artifacts"
    assert items[0]["thumb"]["img"]["ok"] is True and [i["dot"] for i in items] == [GREEN, GREEN, GREEN, BLUE, ORANGE]
    assert r["board_items"]["wsCalls"] == ["b"] and len(r["board_items"]["items"]) == 5, "presentations are still listed apart"
    # Slice 05 : l'aperçu des captures est servi, une image s'ouvre dans SA visionneuse (même route bornée), pas dans l'inspecteur.
    assert r["board_open"] == [], "an image opens the Slice 05 lightbox, not the detail"
    assert r["board_lightbox"] == {"open": True, "href": "/api/artifacts/jart_" + "c" * 32 + "/payload"}
    assert [i["act"] for i in r["board_menu"]["menu"]["items"]] == ["ws-open", "ws-link", "ws-delete"]
    assert r["board_switched_now"]["wsItems"] == [] and r["board_switched_now"]["wsCalls"] == ["b", "c"], "the previous Board's items leave at once"
    assert r["board_switched"]["wsItems"] == [] and r["board_switched"]["wsHead"] is None


# ------------------------------------------------------------------ Slice 07 rework (QA) : focus de toute carte, forme par etat, infobulle


def test_focus_survives_polls_on_board_and_folded_cards_and_escape_returns_to_the_board_card(r):
    assert r["focus_board"] == {"active": "jart_" + "c" * 32, "polls": r["focus_board"]["polls"]} and r["focus_board"]["polls"] >= 2
    assert r["focus_folded"]["active"] == "pst_" + "5".zfill(32) and r["focus_folded"]["polls"] >= 2
    assert r["menu_open_active"] == "menu"
    assert r["focus_after_menu"] == "jart_" + "c" * 32, "Escape returns focus to the card, re-rendered meanwhile"


SHAPES = {"working": ("none", "radial-gradient"), "problem": ("polygon(50% 0px, 100% 100%, 0px 100%)", "none"),
          "unreviewed": ("polygon(50% 0px, 100% 50%, 50% 100%, 0px 50%)", "none"), "done": ("polygon(0px 52%", "none"),
          "unknown": ("none", "none")}


def test_every_state_has_its_own_shape_in_every_density(r):
    for read in (r["cards_circuit-board"], r["cards_cosmos"], r["narrow_cosmos"], r["narrow_circuit-board"]):
        seen = set()
        for item in read["items"]:
            clip, mask = SHAPES[item["state"]]
            assert item["dotShape"].startswith(clip) and (mask in item["dotMask"]), (read["density"], item["state"], item["dotShape"], item["dotMask"])
            seen.add((item["dotShape"], item["dotMask"][:20], item["dotBorder"]))
        assert len(seen) == 5, "five states, five distinct shapes (status never by colour alone)"


def test_the_tooltip_says_the_review_in_words_never_a_tool_identifier(r):
    bilan = next(i for i in r["cards_cosmos"]["items"] if i["state"] == "unreviewed")
    assert "Modifiée par Jarvis — à revoir" in bilan["full"] and "presentation_edit" not in bilan["full"]
    assert "presentation_edit" not in bilan["label"]
