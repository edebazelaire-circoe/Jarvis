"""`docs/presentation-studio.md` › *Remotion Studio round trip (Level 3, Slice 12)* and `docs/remotion-studio.md` § 2 bis against the code
(handoff jarvis-remotion-native-studio-playback-fix, Slice 12): every code, route, word the user reads, log key and cited file exists."""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.core import remotion_studio_service as service
from jarvis.domain import remotion_studio_workspace as W
from jarvis.domain.remotion_compile import SCENE_ALLOWED_IMPORTS
from jarvis.domain.remotion_studio import StudioErrorCode as C
from jarvis.runtime import remotion_studio_relay as relay

ROOT = Path(__file__).resolve().parents[2]
PS = (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")
RS = (ROOT / "docs" / "remotion-studio.md").read_text(encoding="utf-8")
DOOR = (ROOT / "jarvis" / "runtime" / "control_center_presentation_studio_explorer_remotion.js").read_text(encoding="utf-8")
CARD = (ROOT / "jarvis" / "runtime" / "control_center_remotion_studio.js").read_text(encoding="utf-8")
SERVICE = Path(service.__file__).read_text(encoding="utf-8")


def section() -> str:
    start = PS.index("### Remotion Studio round trip (Level 3, Slice 12)")
    return PS[start:PS.index("\n### ", start + 10)]


def bis() -> str:
    start = RS.index("## 2 bis.")
    return RS[start:RS.index("\n## 3.", start)]


def test_every_publish_code_is_in_the_process_table_and_has_a_french_sentence():
    for code in (C.UNPUBLISHED_EDITS, C.PUBLISH_CONFIRM_REQUIRED, C.PUBLISH_NOTHING, C.PUBLISH_BASE_MISMATCH, C.PUBLISH_CONFLICT,
                 C.PUBLISH_INVALID_FILE, C.PUBLISH_IMPORT_REFUSED, C.PUBLISH_REFUSED, C.PUBLISH_UNAVAILABLE):
        assert f"| `{code.value.removeprefix('remotion_studio_')}` |" in RS, code
        assert f"{code.value}:" in CARD, code


def test_the_body_fields_and_the_old_sync_path_table_are_the_code():
    text = bis()
    assert W.CONFIRM_FIELD == "confirm_publish" and W.DISCARD_FIELD == "discard_unpublished"
    assert '"confirm_publish": true' in text and "`discard_unpublished: true`" in text
    for row in ("`open` de la même scène", "`open` / `sync` d'une autre version", "`close`, arrêt automatique", "`uninstall`"):
        assert row in text, row
    assert service.STANDING_RESULTS == ("reloaded", "reloaded_state_reset", "repinned", "pending_mount")
    for status in service.STANDING_RESULTS:
        assert f"`{status}`" in text, status
    for name in SCENE_ALLOWED_IMPORTS:
        assert f"`{name}`" in text and f"`{name}`" in section(), name


def test_the_relay_is_page_only_and_documented():
    assert relay._PAGE_ONLY == frozenset({"publish"}) and relay._WRITES["publish"] == relay.START_TIMEOUT_S
    assert "Sec-Fetch-Site: same-origin" in section() and "seulement depuis la page" in RS


def test_the_words_the_user_reads_are_the_ones_the_door_writes():
    text = section()
    assert "pas encore publiés : la variante n'a pas changé" in text and "pas encore ${pub} : la variante n’a pas changé" in DOOR
    for words in ("Publier dans la variante…", "la variante n'a pas changé", "Publication dans la variante…",
                  "Revenir à", "la version d'avant", "Déjà publié", "Fichiers non publiés", "de côté (studio-edits), pas publiés",
                  "Mettre de côté les fichiers non publiés ?"):
        assert words in text, words
        assert words.replace("'", "’") in DOOR + CARD or words in DOOR + CARD, words


def test_the_log_keys_the_section_names_are_emitted():
    text = section()
    for key in re.findall(r"`(remotion_studio_[a-z_]+)`", text):
        if key in {c.value for c in C}:
            continue  # an error code, not a log key
        assert f"'{key}'" in DOOR, key
    for kind in ("publish_started", "published", "publish_refused", "publish_conflict", "publish_rebased", "unpublished_kept",
                 "workspace_kept", "unpublished_saved"):
        assert f'"{kind}"' in SERVICE and kind in RS, kind


def test_the_files_the_section_cites_exist():
    text = section()
    for name in re.findall(r"`((?:tests/unit|jarvis)/[A-Za-z0-9_/.-]+\.(?:py|js))`", text + bis()):
        assert (ROOT / name).is_file(), name
    for name in ("test_remotion_studio_publish.py", "test_remotion_studio_publish_crash.py", "test_remotion_studio_publish_routes.py",
                 "test_variants_remotion_studio_publish_js.py", "test_remotion_studio_publish_docs.py", "test_remotion_studio_roundtrip_real_browser.py"):
        assert name in text and (ROOT / "tests" / "unit" / name).is_file(), name
    assert (ROOT / "tasks" / "jarvis-remotion-native-studio-playback-fix" / "slices" / "12-native-authoring-workspace-roundtrip" / "DESIGN.md").is_file()


def test_no_widening_is_documented_as_a_human_decision():
    assert "HV-RFX-12-01" in section() and "HV-RFX-12-01" in bis() and "HV-RFX-12-01" in W.WIDENING_REFUSAL
    assert "No widening exists" in section() and "Aucun élargissement n'existe" in bis()
