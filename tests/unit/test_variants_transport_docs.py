"""Conformité doc <-> code du transport de Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 06).

`docs/presentation-studio.md` > *Variants transport (Level 3, Slice 06)* nomme des contrôles, des règles, un propriétaire et des preuves :
ce test vérifie que chacun existe dans le code, et que ce que la section dit retiré de Variantes l'est vraiment.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_continuous_sequencing_docs import section

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "presentation-studio.md"
RUNTIME = ROOT / "jarvis" / "runtime"
TITLE = "### Variants transport (Level 3, Slice 06)"


def test_the_section_names_its_controls_rules_and_proofs_and_they_exist():
    text = DOC.read_text(encoding="utf-8")
    body = section(text, TITLE)
    for needle in ('role="toolbar"', "« Lecture de la vidéo »", "« Scène précédente »", "« Scène suivante »", "« Lire » / « Pause » / « Rejouer »",
                   'role="slider"', "« Position dans la vidéo »", "aria-valuetext", "« Son »", "« Plus de lecture »", 'aria-haspopup="menu"',
                   "« Lire seulement cette scène »", "« Revenir au début »", "embed=variants", "autoplay: false", "`prepare()`", "`seek(kind, value)`",
                   "`playScene()`", "`revise()`", "requestFrame", "« Dernière scène. »", "PX-4", "PX-7", "PX-8", "PX-9", "PX-10", "PX-18", "PX-19",
                   "PX-21", "test_variants_transport_js.py", "test_variants_transport_browser.py", "test_variants_transport_docs.py",
                   "slices/06-player-lifecycle-and-transport/evidence/", "resume after the seek"):
        assert needle in body, needle
    for path in ("tests/unit/test_variants_transport_js.py", "tests/unit/test_variants_transport_browser.py",
                 "tasks/jarvis-remotion-native-studio-playback-fix/slices/06-player-lifecycle-and-transport/evidence/summary.json"):
        assert (ROOT / path).is_file(), path
    assert "**Slice 06** (Player lifecycle), **done**" in text
    assert "« Jouer cette slide » is unchanged until Slices 06/10" not in text


def test_the_named_controls_and_doors_are_in_the_code():
    explorer = (RUNTIME / "control_center_presentation_studio_explorer.js").read_text(encoding="utf-8")
    for needle in ("role:'toolbar','aria-label':'Lecture de la vidéo'", "role:'slider'", "'aria-label':'Position dans la vidéo'",
                   "'aria-label':'Scène précédente'", "'aria-label':'Scène suivante'", "'aria-label':'Son'", "'aria-label':'Plus de lecture','aria-haspopup':'menu'",
                   "'Lire seulement cette scène'", "'Revenir au début'", "'Dernière scène.'", "autoplay:false,embed:'variants'", "requestFrame:frame"):
        assert needle in explorer, needle
    assert "Jouer cette slide" not in explorer and "playFromStudio" not in explorer, "the rehearsal-run entry is gone (PX-21)"
    sequencer = (RUNTIME / "control_center_presentation_studio_sequencer.js").read_text(encoding="utf-8")
    assert "prepare,play,playScene,pause,toggle,seek,seekScene,retry,revise,reset" in sequencer
    frame = (RUNTIME / "control_center_remotion_frame.js").read_text(encoding="utf-8")
    relay = (RUNTIME / "remotion_relay.py").read_text(encoding="utf-8")
    assert "const EMBEDS=Object.freeze(['variants'])" in frame and 'STAGE_EMBEDS = ("variants",)' in relay
    stage = (RUNTIME / "control_center_remotion_stage.js").read_text(encoding="utf-8")
    assert "if(embedded){ui.root.append(ui.host,ui.panel);return}" in stage and "if(!embedded)control('play')" in stage
    host = (RUNTIME / "control_center_prefab_host.js").read_text(encoding="utf-8")
    assert "if(!autoplay)return;" in host
    child = (RUNTIME / "remotion_sandbox_child.js").read_text(encoding="utf-8")
    assert "if(m.frame!==undefined){if(player.isPlaying())player.pause();player.seekTo(m.frame)}" in child
