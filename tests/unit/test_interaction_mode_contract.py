"""Contrat de vocabulaire du mode d'interaction et de la disposition de sortie.

Slice 01 de `tasks/jarvis-presentation-interaction-mode`. Domaine pur : rien
n'est persisté, servi, affiché ni prononcé ici.
"""
from __future__ import annotations

import ast
import dataclasses
from importlib.util import resolve_name
from pathlib import Path

import pytest

from jarvis.domain.interaction_mode import (
    DEFAULT_INTERACTION_MODE, INTERACTION_MODES, InteractionMode, InteractionModeDescriptor,
    InteractionModeError, InteractionModeStatus, activatable_interaction_modes,
    behaving_interaction_mode, default_disposition, ensure_activatable, is_activatable,
    parse_interaction_mode, parse_interaction_mode_label, stored_interaction_mode,
)
from jarvis.domain.output_disposition import OutputDisposition, parse_output_disposition
from jarvis.domain.presentation_policy import (
    LOCKED_DECISIONS, PRESENTATION_POLICY, PresentationOutputPolicy, PresentationPolicyError,
    PresentationSituation, may_speak, policy_for,
)
from jarvis.domain.speaker import ConversationMode
from jarvis.domain.v2 import SpeechKind
from jarvis.domain.voice_architecture import VoiceArchitectureId
from jarvis.v2_config import VoiceArchitecture

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Le mode lui-meme
# ---------------------------------------------------------------------------


def test_the_three_modes_carry_the_locked_user_labels_and_internal_values():
    assert [(mode.value, mode.label) for mode in InteractionMode] == [
        ("assistant", "SIMPLE"), ("presentation", "PRESENTATION"), ("meeting", "REUNION"),
    ]


def test_the_assistant_mode_is_the_default_of_the_contract():
    assert DEFAULT_INTERACTION_MODE is InteractionMode.ASSISTANT


@pytest.mark.parametrize("stored", [None, "", "   ", "nope", "assistant ", 42, 0, True, [], {}, object()])
def test_a_missing_malformed_or_unknown_stored_value_resolves_to_the_assistant_mode_without_raising(stored):
    assert stored_interaction_mode(stored) is InteractionMode.ASSISTANT


@pytest.mark.parametrize("stored", ["presentation", " PRESENTATION ", InteractionMode.PRESENTATION])
def test_a_readable_stored_value_is_honoured_whatever_its_casing_or_padding(stored):
    assert stored_interaction_mode(stored) is InteractionMode.PRESENTATION


def test_resolution_is_deterministic_and_repeatable_for_the_same_input():
    assert {stored_interaction_mode("garbage") for _ in range(50)} == {InteractionMode.ASSISTANT}


def test_each_mode_declares_the_manifestation_a_turn_defaults_to():
    assert default_disposition(InteractionMode.ASSISTANT) is OutputDisposition.VISUAL_AND_VOICE
    assert default_disposition(InteractionMode.PRESENTATION) is OutputDisposition.VISUAL_ONLY
    assert default_disposition(InteractionMode.MEETING) is OutputDisposition.SILENT


def test_every_mode_is_describable_for_an_interface_that_knows_nothing_of_the_runtime():
    described = {}
    for mode in InteractionMode:
        descriptor = INTERACTION_MODES[mode]
        assert descriptor.mode is mode and descriptor.label == mode.label
        assert descriptor.summary.strip() == descriptor.summary and len(descriptor.summary) > 20
        assert descriptor.implemented is (descriptor.status is InteractionModeStatus.READY)
        described[mode] = descriptor.implemented
    assert described == {
        InteractionMode.ASSISTANT: True, InteractionMode.PRESENTATION: True, InteractionMode.MEETING: False,
    }


def test_a_descriptor_without_a_human_summary_is_refused():
    with pytest.raises(InteractionModeError) as raised:
        InteractionModeDescriptor(mode=InteractionMode.ASSISTANT, status=InteractionModeStatus.READY,
                                  default_disposition=OutputDisposition.SILENT, summary="  ")
    assert raised.value.code == "interaction_mode_summary_missing"


@pytest.mark.parametrize("changes", [
    dict(mode="assistant"), dict(status="ready"), dict(default_disposition="silent"),
    dict(default_disposition=None), dict(mode=VoiceArchitectureId.SIMPLE),
])
def test_a_descriptor_built_from_untyped_values_is_refused(changes):
    base = dict(mode=InteractionMode.ASSISTANT, status=InteractionModeStatus.READY,
                default_disposition=OutputDisposition.SILENT, summary="Un résumé lisible.")
    with pytest.raises(InteractionModeError) as raised:
        InteractionModeDescriptor(**{**base, **changes})
    assert raised.value.code == "interaction_mode_descriptor_invalid"


# ---------------------------------------------------------------------------
# Reunion : connu, affiche, jamais actif
# ---------------------------------------------------------------------------


def test_the_meeting_mode_is_known_and_displayable_but_declares_itself_not_implemented():
    descriptor = INTERACTION_MODES[InteractionMode.MEETING]
    assert descriptor.label == "REUNION" and descriptor.summary
    assert descriptor.status is InteractionModeStatus.PLANNED
    assert descriptor.implemented is False


def test_only_the_assistant_and_presentation_modes_can_be_activated():
    assert activatable_interaction_modes() == (InteractionMode.ASSISTANT, InteractionMode.PRESENTATION)
    assert is_activatable(InteractionMode.MEETING) is False


def test_explicitly_activating_the_reserved_meeting_mode_is_refused_with_a_stable_code():
    with pytest.raises(InteractionModeError) as raised:
        ensure_activatable(InteractionMode.MEETING)
    assert raised.value.code == "interaction_mode_not_implemented"
    assert "REUNION" in str(raised.value)


def test_the_refusal_a_french_user_reads_is_written_in_french():
    """`str(exc)` part tel quel dans la charge utile du Control Center."""
    with pytest.raises(InteractionModeError) as raised:
        ensure_activatable(InteractionMode.MEETING)
    message = str(raised.value)
    assert "réservé" in message and "comportement" in message
    assert raised.value.code.isascii() and " " not in raised.value.code


def test_an_activatable_mode_passes_the_gate_unchanged():
    for mode in activatable_interaction_modes():
        assert ensure_activatable(mode) is mode


def test_a_meeting_value_left_in_storage_stays_displayable_yet_behaves_as_the_assistant():
    assert stored_interaction_mode("meeting") is InteractionMode.MEETING
    assert behaving_interaction_mode("meeting") is InteractionMode.ASSISTANT
    assert behaving_interaction_mode(None) is InteractionMode.ASSISTANT
    assert behaving_interaction_mode("presentation") is InteractionMode.PRESENTATION


def test_the_display_reading_and_the_behaviour_reading_only_diverge_on_the_reserved_mode():
    """Les deux lectures portent des noms distincts parce qu'elles different
    exactement la ou l'erreur couterait le plus cher (Decision 02)."""
    diverging = {value for value in ("assistant", "presentation", "meeting", None, "junk")
                 if stored_interaction_mode(value) is not behaving_interaction_mode(value)}
    assert diverging == {"meeting"}


def test_the_meeting_mode_has_neither_a_policy_row_nor_an_activatable_slot():
    assert InteractionMode.MEETING not in activatable_interaction_modes()
    assert all("meeting" not in situation.value for situation in PresentationSituation)


# ---------------------------------------------------------------------------
# Absence de collision avec les deux axes d'architecture vocale et l'autorisation
# ---------------------------------------------------------------------------


def test_no_interaction_mode_value_collides_with_either_voice_architecture_axis_or_with_authorization():
    modes = {mode.value for mode in InteractionMode}
    assert modes.isdisjoint({item.value for item in VoiceArchitectureId})
    assert modes.isdisjoint({item.value for item in VoiceArchitecture})
    assert modes.isdisjoint({item.value for item in ConversationMode})


def test_no_interaction_mode_member_name_collides_with_either_voice_architecture_axis():
    names = {mode.name for mode in InteractionMode}
    assert names.isdisjoint({item.name for item in VoiceArchitectureId})
    assert names.isdisjoint({item.name for item in VoiceArchitecture})
    assert names.isdisjoint({item.name for item in ConversationMode})


def test_the_simple_label_is_unreachable_as_an_interaction_mode_member():
    """Le piege nomme : `VoiceArchitectureId.SIMPLE` existe, pas `InteractionMode.SIMPLE`."""
    assert VoiceArchitectureId.SIMPLE.name == InteractionMode.ASSISTANT.label
    assert not hasattr(InteractionMode, "SIMPLE")
    assert not hasattr(InteractionMode, "REUNION")
    with pytest.raises(AttributeError):
        InteractionMode.SIMPLE  # noqa: B018 - c'est exactement ce qu'on verrouille


@pytest.mark.parametrize("foreign", [
    "simple", "front_brain", "duplex", "legacy", "continuous_brain", "open_room", "solo_owner",
])
def test_a_value_from_another_axis_never_parses_as_an_interaction_mode(foreign):
    assert parse_interaction_mode(foreign) is None
    assert parse_interaction_mode_label(foreign) is None
    assert stored_interaction_mode(foreign) is DEFAULT_INTERACTION_MODE


def test_the_user_labels_are_read_through_the_label_parser():
    assert parse_interaction_mode_label("SIMPLE") is InteractionMode.ASSISTANT
    assert parse_interaction_mode_label(" REUNION ") is InteractionMode.MEETING
    assert parse_interaction_mode_label("assistant") is None


def test_the_two_labels_that_would_change_meaning_never_pass_through_the_value_door():
    """`PRESENTATION` y designe le meme mode, donc passer est sans effet. Les
    deux autres etiquettes sont refusees cote valeur, et c'est ce qui compte."""
    assert parse_interaction_mode("SIMPLE") is None
    assert parse_interaction_mode("REUNION") is None
    assert parse_interaction_mode("PRESENTATION") is InteractionMode.PRESENTATION


def test_the_label_parser_is_case_exact_so_a_lowercase_foreign_value_cannot_slip_through():
    """`simple` est une valeur d'architecture vocale, pas l'etiquette `SIMPLE`."""
    assert parse_interaction_mode_label("simple") is None
    assert parse_interaction_mode_label("Simple") is None
    assert parse_interaction_mode_label("SIMPLE") is InteractionMode.ASSISTANT


@pytest.mark.parametrize("junk", [None, 7, [], {}, object()])
def test_both_parsers_refuse_anything_that_is_not_a_string_instead_of_guessing(junk):
    assert parse_interaction_mode(junk) is None
    assert parse_interaction_mode_label(junk) is None


def test_the_registry_covers_every_mode_and_nothing_else():
    assert set(INTERACTION_MODES) == set(InteractionMode)


# ---------------------------------------------------------------------------
# Disposition de sortie
# ---------------------------------------------------------------------------


def test_the_four_output_dispositions_are_exactly_the_contracted_ones():
    assert [item.value for item in OutputDisposition] == [
        "silent", "visual_only", "voice_only", "visual_and_voice",
    ]


@pytest.mark.parametrize("disposition, shows, speaks", [
    (OutputDisposition.SILENT, False, False),
    (OutputDisposition.VISUAL_ONLY, True, False),
    (OutputDisposition.VOICE_ONLY, False, True),
    (OutputDisposition.VISUAL_AND_VOICE, True, True),
])
def test_each_disposition_says_exactly_which_channels_it_uses(disposition, shows, speaks):
    assert (disposition.shows, disposition.speaks) == (shows, speaks)


def test_a_silent_disposition_is_a_legitimate_outcome_and_not_a_missing_one():
    assert OutputDisposition.SILENT.speaks is False and OutputDisposition.SILENT.shows is False
    assert parse_output_disposition("silent") is OutputDisposition.SILENT


@pytest.mark.parametrize("junk", [None, "", "quiet", "active", "archived", 3, []])
def test_an_unknown_disposition_is_reported_as_unknown_rather_than_replaced(junk):
    assert parse_output_disposition(junk) is None


def test_the_scene_disposition_vocabulary_never_parses_as_an_output_disposition():
    """`Disposition{ACTIVE, ARCHIVED}` de la scene parle de presence, pas de sortie."""
    from jarvis.domain.scene import Disposition as SceneDisposition

    assert {item.value for item in OutputDisposition}.isdisjoint({item.value for item in SceneDisposition})
    for item in SceneDisposition:
        assert parse_output_disposition(item.value) is None


# ---------------------------------------------------------------------------
# Garde G2 : deux vocabulaires `Disposition` ne cohabitent jamais sans nom complet
# ---------------------------------------------------------------------------


def _resolved(node: ast.ImportFrom, path: Path, root: Path) -> str:
    """Module vise, y compris pour une ecriture relative (`from .scene import ...`).

    Meme logique que `tests/unit/test_v2_architecture.py`, ou elle existe pour
    exactement la meme raison : une frontiere qu'une ecriture relative contourne
    n'est pas une frontiere.
    """
    name = node.module or ""
    if node.level:
        package = ".".join(path.relative_to(root).parent.parts)
        return resolve_name("." * node.level + name, package)
    return name


def _disposition_vocabularies(path: Path, *, root: Path = ROOT) -> tuple[bool, bool]:
    """(`Disposition` importe sans nom complet, vocabulaire de sortie present).

    `utf-8-sig` et non `utf-8` : un fichier du depot porte une BOM
    (`tests/unit/test_third_party_bootstrap.py`), que Python execute tres bien
    mais que `ast.parse` refuse. Une garde qui s'arrete sur le premier fichier
    exotique ne garde rien.
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    bare_disposition = output_vocabulary = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _resolved(node, path, root)
            for alias in node.names:
                # Le nom importe, quel que soit le module d'ou il vient : c'est
                # `Disposition` tout court dans le fichier qui cree l'ambiguite.
                if alias.name == "Disposition" and alias.asname is None:
                    bare_disposition = True
                # Le vocabulaire de sortie arrive aussi par reexport, donc on
                # regarde le nom autant que le module.
                if alias.name.startswith("OutputDisposition") or module.endswith("output_disposition"):
                    output_vocabulary = True
        elif isinstance(node, ast.Import):
            if any(alias.name.endswith("output_disposition") for alias in node.names):
                output_vocabulary = True
    return bare_disposition, output_vocabulary


def test_no_module_ever_holds_both_disposition_vocabularies_at_once():
    """Le piege G2, garde sur les ecritures qui le contourneraient vraiment.

    Absolue ou relative, directe ou par reexport, `import ... as ...` compris :
    un fichier qui dispose du vocabulaire de sortie n'a pas le droit d'importer
    `Disposition` sans le qualifier.
    """
    offenders = []
    for folder in (ROOT / "jarvis", ROOT / "tests"):
        for path in folder.rglob("*.py"):
            bare, output = _disposition_vocabularies(path)
            if bare and output:
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f"ambiguous Disposition vocabulary in {offenders}"


@pytest.mark.parametrize("source", [
    "from jarvis.domain.scene import Disposition\nfrom jarvis.domain.output_disposition import OutputDisposition\n",
    "from .scene import Disposition\nfrom .output_disposition import OutputDisposition\n",
    "from .scene import Disposition\nimport jarvis.domain.output_disposition as od\n",
    "from ..domain.scene import Disposition\nfrom ..domain.interaction_mode import OutputDisposition\n",
    "from jarvis.domain.scene import Visibility, Disposition\nfrom jarvis.domain.interaction_mode import InteractionMode, OutputDisposition\n",
])
def test_the_guard_actually_trips_on_every_spelling_that_would_create_the_ambiguity(tmp_path, source):
    path = tmp_path / "jarvis" / "domain" / "nested" / "probe.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert _disposition_vocabularies(path, root=tmp_path) == (True, True)


@pytest.mark.parametrize("source", [
    "from jarvis.domain.scene import Disposition as SceneDisposition\nfrom jarvis.domain.output_disposition import OutputDisposition\n",
    "from jarvis.domain.scene import Disposition\n",
    "from jarvis.domain.output_disposition import OutputDisposition\n",
])
def test_the_guard_leaves_unambiguous_files_alone(tmp_path, source):
    path = tmp_path / "jarvis" / "domain" / "nested" / "probe.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    bare, output = _disposition_vocabularies(path, root=tmp_path)
    assert not (bare and output)


# ---------------------------------------------------------------------------
# Matrice de presentation
# ---------------------------------------------------------------------------


def test_the_matrix_covers_every_presentation_situation_exactly_once():
    assert set(PRESENTATION_POLICY) == set(PresentationSituation)
    assert len(PRESENTATION_POLICY) == 7
    for situation in PresentationSituation:
        assert policy_for(situation).situation is situation


def test_an_ambient_observation_stays_silent_authorizes_nothing_and_asks_for_no_speech():
    policy = policy_for(PresentationSituation.AMBIENT_OBSERVATION)
    assert policy.disposition is OutputDisposition.SILENT
    assert policy.voice_allowed is False and policy.speech_kinds == ()
    assert policy.authorizes_action is False
    assert policy.may_raise_attention_cue is False
    assert all(may_speak(PresentationSituation.AMBIENT_OBSERVATION, kind) is False for kind in SpeechKind)


def test_a_visual_command_executes_and_shows_without_a_single_word():
    policy = policy_for(PresentationSituation.VISUAL_COMMAND)
    assert policy.disposition is OutputDisposition.VISUAL_ONLY
    assert policy.disposition.speaks is False and policy.voice_allowed is False
    assert policy.authorizes_action is True


def test_a_genuine_question_is_answered_aloud_and_may_lean_on_the_screen():
    policy = policy_for(PresentationSituation.KNOWLEDGE_QUESTION)
    assert policy.disposition is OutputDisposition.VISUAL_AND_VOICE
    assert policy.speech_kinds == (SpeechKind.QUESTION, SpeechKind.RESULT)
    assert may_speak(PresentationSituation.KNOWLEDGE_QUESTION, SpeechKind.RESULT) is True
    assert may_speak(PresentationSituation.KNOWLEDGE_QUESTION, SpeechKind.PROGRESS) is False


def test_an_explicit_request_to_speak_opens_the_whole_speech_range_without_seizing_the_screen():
    policy = policy_for(PresentationSituation.EXPLICIT_SPEAK_REQUEST)
    assert policy.disposition is OutputDisposition.VOICE_ONLY
    assert set(policy.speech_kinds) == set(SpeechKind)


def test_a_successful_command_can_neither_speak_nor_beep_whatever_the_caller_asks():
    """La reussite et l'echec sont deux lignes : la retenue est dans la donnee,
    pas dans la memoire de l'appelant."""
    policy = policy_for(PresentationSituation.COMMAND_CONFIRMATION)
    assert policy.disposition is OutputDisposition.VISUAL_ONLY
    assert policy.voice_allowed is False and policy.speech_kinds == ()
    assert policy.may_raise_attention_cue is False
    assert all(may_speak(PresentationSituation.COMMAND_CONFIRMATION, kind) is False for kind in SpeechKind)


def test_a_failed_command_is_shown_may_be_cued_and_may_be_said_but_only_as_an_error():
    policy = policy_for(PresentationSituation.COMMAND_ERROR)
    assert policy.disposition is OutputDisposition.VISUAL_ONLY
    assert policy.speech_kinds == (SpeechKind.ERROR,)
    assert policy.may_raise_attention_cue is True
    assert may_speak(PresentationSituation.COMMAND_ERROR, SpeechKind.ERROR) is True
    assert may_speak(PresentationSituation.COMMAND_ERROR, SpeechKind.RESULT) is False


def test_a_fact_check_alert_signals_itself_but_never_explains_itself_aloud():
    policy = policy_for(PresentationSituation.FACT_CHECK_ATTENTION)
    assert policy.voice_allowed is False and policy.disposition.speaks is False
    assert policy.may_raise_attention_cue is True
    assert policy.authorizes_action is False


def test_nothing_in_the_matrix_speaks_without_an_explicit_address():
    checked = {situation for situation, policy in PRESENTATION_POLICY.items()
               if not policy.voice_allowed or policy.requires_explicit_address}
    assert checked == set(PresentationSituation)
    assert any(policy.voice_allowed for policy in PRESENTATION_POLICY.values())


def test_nothing_in_the_matrix_authorizes_an_action_without_an_explicit_address():
    checked = {situation for situation, policy in PRESENTATION_POLICY.items()
               if not policy.authorizes_action or policy.requires_explicit_address}
    assert checked == set(PresentationSituation)
    assert any(policy.authorizes_action for policy in PRESENTATION_POLICY.values())


def test_a_speaking_default_always_stays_within_what_the_situation_allows():
    checked = {situation for situation, policy in PRESENTATION_POLICY.items()
               if (not policy.disposition.speaks or policy.voice_allowed)
               and bool(policy.speech_kinds) is policy.voice_allowed}
    assert checked == set(PresentationSituation)
    assert any(policy.disposition.speaks for policy in PRESENTATION_POLICY.values())


def test_every_row_names_a_decision_that_really_exists_in_the_locked_log():
    cited = set()
    for policy in PRESENTATION_POLICY.values():
        assert policy.decisions
        cited.update(policy.decisions)
    assert cited <= LOCKED_DECISIONS
    assert cited == {"D03", "D05", "D09", "D10", "D11"}


def _row(**changes) -> dict:
    base = dict(situation=PresentationSituation.AMBIENT_OBSERVATION, disposition=OutputDisposition.SILENT,
                voice_allowed=False, requires_explicit_address=False, authorizes_action=False,
                speech_kinds=(), may_raise_attention_cue=False, decisions=("D03",))
    return {**base, **changes}


@pytest.mark.parametrize("changes, code", [
    (dict(voice_allowed=True, speech_kinds=(SpeechKind.RESULT,)), "presentation_policy_spontaneous_speech"),
    (dict(authorizes_action=True), "presentation_policy_ambient_authority"),
    (dict(disposition=OutputDisposition.VOICE_ONLY), "presentation_policy_invalid"),
    (dict(speech_kinds=(SpeechKind.RESULT,)), "presentation_policy_invalid"),
    (dict(speech_kinds=("result",)), "presentation_policy_invalid"),
    (dict(decisions=()), "presentation_policy_unjustified"),
    (dict(decisions=("Dfromage",)), "presentation_policy_unjustified"),
    (dict(decisions=("D99",)), "presentation_policy_unjustified"),
    (dict(decisions=("D03", "D42")), "presentation_policy_unjustified"),
    (dict(decisions="D03"), "presentation_policy_unjustified"),
    (dict(voice_allowed=1, speech_kinds=(SpeechKind.RESULT,)), "presentation_policy_invalid"),
])
def test_a_row_contradicting_a_locked_decision_cannot_even_be_constructed(changes, code):
    with pytest.raises(PresentationPolicyError) as raised:
        PresentationOutputPolicy(**_row(**changes))
    assert raised.value.code == code


def test_a_row_cannot_be_relaxed_by_copying_it_either():
    """`dataclasses.replace` rejoue `__post_init__` : le chemin de mutation
    realiste est ferme. Un `object.__setattr__` force reste possible, comme
    partout en Python ; ce n'est pas ce que la table pretend empecher."""
    ambient = policy_for(PresentationSituation.AMBIENT_OBSERVATION)
    with pytest.raises(PresentationPolicyError) as raised:
        dataclasses.replace(ambient, authorizes_action=True)
    assert raised.value.code == "presentation_policy_ambient_authority"


def test_the_matrix_is_read_only_at_runtime():
    with pytest.raises(TypeError):
        PRESENTATION_POLICY[PresentationSituation.AMBIENT_OBSERVATION] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        INTERACTION_MODES[InteractionMode.MEETING] = None  # type: ignore[index]
