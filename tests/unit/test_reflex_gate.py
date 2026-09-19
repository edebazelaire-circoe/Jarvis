"""Task06 policy replay controls; timings/IDs are explicitly synthetic."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from jarvis.domain.errors import ConfigurationError
from jarvis.domain.reflex_policy import ReflexAction, conversational_wait_reason, decide_reflex
from jarvis.runtime import voice_stack
from jarvis.v2_config import (DEFAULT_REFLEX_DELAY_MS, REFLEX_DELAY_ENV, REFLEX_ENABLED_ENV,
                              REFLEX_REQUIRE_WORK_ENV, reflex_delay_s, reflex_enabled,
                              reflex_requires_confirmed_work)
from jarvis.domain.v2 import ProtocolEnvelope, SpeechRequest
from jarvis.runtime.output_admission import OutputAdmission, OutputAdmissionState
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from tests.fakes.speech_context import source, context
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.unit.test_voice_duplex import ControllableSession, EmptyCore, RecordingJournal


@pytest.mark.parametrize("text, reason", [
    ("OK", "acknowledgement_only"), ("non c’est bon", "acknowledgement_only"),
    ("attends je réfléchis", "user_continuing"),
    ("Ce que je voulais voir avec toi c'était... Attends je réfléchis.", "user_continuing"),
    ("Non pas le premier, le second", "correction"),
])
def test_wait_controls(text, reason):
    decision = decide_reflex(text=text, enabled=True, admitted=True, user_speaking=False,
        useful_ready=False, work_confirmed=True, work_terminal=False, noticeable_wait=True, already_used=False, stale=False)
    assert decision.action is ReflexAction.WAIT and decision.reason == reason


def test_ok_prefix_does_not_hide_a_real_request():
    assert conversational_wait_reason("OK, très bien, peux-tu comparer les prix ?") is None


@pytest.mark.parametrize("changes, reason", [({"admitted": False}, "not_admitted"), ({"user_speaking": True}, "user_speaking"),
    ({"work_confirmed": False, "require_work": True}, "work_unconfirmed"), ({"noticeable_wait": False}, "answer_may_arrive_quickly"),
    ({"work_terminal": True}, "work_terminal"), ({"stale": True}, "stale"), ({"useful_ready": True}, "useful_content_ready")])
def test_context_controls(changes, reason):
    args = dict(text="Compare les prix", enabled=True, admitted=True, user_speaking=False, useful_ready=False,
                work_confirmed=True, work_terminal=False, noticeable_wait=True, already_used=False, stale=False)
    args.update(changes)
    assert decide_reflex(**args).reason == reason


def _policy(**changes):
    args = dict(text="Compare les prix entre ces architectures", enabled=True, admitted=True, user_speaking=False,
                useful_ready=False, work_confirmed=False, work_terminal=False, noticeable_wait=True,
                already_used=False, stale=False)
    args.update(changes)
    return decide_reflex(**args)


def test_silence_alone_permits_the_preamble_no_declared_work_required():
    """Le declencheur est temporel : le cerveau se tait, donc la surface parle.

    C'est la porte de `f0aec10` qui est relachee ici. Elle exigeait un
    `brain.work.started` correle, que le cerveau n'emet pas quand il repond
    lui-meme -- c'est-a-dire presque toujours -- et le reflexe n'a plus rien dit
    du 13 au 18 septembre 2026.
    """
    decision = _policy()

    assert decision.action is ReflexAction.PREAMBLE and decision.reason == "brain_silent_wait"
    # Un travail declare reste distingue dans le motif, pour la relecture des traces.
    assert _policy(work_confirmed=True).reason == "confirmed_work_wait"


def test_the_old_gate_remains_reachable_as_a_rollback():
    assert _policy(require_work=True).action is ReflexAction.WAIT
    assert _policy(require_work=True).reason == "work_unconfirmed"
    assert _policy(require_work=True, work_confirmed=True).action is ReflexAction.PREAMBLE


@pytest.mark.parametrize("changes, reason", [
    ({"useful_ready": True}, "useful_content_ready"),   # Le cerveau a deja de quoi parler.
    ({"work_terminal": True}, "work_terminal"),         # Le travail est fini, la reponse arrive.
    ({"already_used": True}, "already_used"),           # Un seul preambule par tour.
    ({"noticeable_wait": False}, "answer_may_arrive_quickly"),  # L'echeance n'est pas atteinte.
    ({"user_speaking": True}, "user_speaking"),
    ({"stale": True}, "stale"),
    ({"enabled": False}, "disabled"),
    ({"text": "OK"}, "acknowledgement_only"),
    ({"text": "Non pas le premier, le second"}, "correction"),
])
def test_relaxing_the_gate_keeps_every_other_guard(changes, reason):
    """Ce que la porte evitait, les controles qui l'entouraient l'evitent encore."""
    decision = _policy(**changes)

    assert decision.reason == reason and decision.action is not ReflexAction.PREAMBLE


def work(kind="started", correlation="c", work_id="work"):
    return ProtocolEnvelope(message_type=f"brain.work.{kind}", payload={"conversation_id": "conversation", "correlation_id": correlation, "work_id": work_id})


def scheduler(session=None, *, require_work=False):
    selected = SpeechScheduler(core=EmptyCore(), conversation_id="conversation", session=session or ControllableSession(),
                               journal=RecordingJournal(), reflex_delay_s=.01, reflex_require_work=require_work)
    selected.update_speech_context(context("conversation", "c"))
    selected._running = True
    return selected


def due(selected):
    selected._reflex.due = asyncio.get_running_loop().time() - .001
    selected._reflex.next_check = selected._reflex.due


async def test_work_before_request_permits_only_one_preamble():
    selected = scheduler()
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    due(selected)
    await selected._maybe_speak_reflex()
    assert len(selected.session.reflexes) == 1
    selected.request_reflex("Compare les prix", correlation_id="c")
    assert selected._reflex is None
    assert selected._live_reflex.admission.state is OutputAdmissionState.RESERVED
    assert not selected._reflex_cancelled
    await selected.stop()


async def test_duplicate_after_expiry_cannot_create_a_new_deadline():
    selected = scheduler()
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    due(selected)
    selected._reflex.expires = asyncio.get_running_loop().time() - .001
    await selected._maybe_speak_reflex()
    assert selected._reflex is None
    selected.request_reflex("Compare les prix", correlation_id="c")
    assert selected._reflex is None and not selected.session.reflexes
    await selected.stop()


async def test_work_after_request_releases_wait_without_resetting_deadline():
    """Retour arriere (`JARVIS_REFLEX_REQUIRE_WORK`) : l'attestation tardive ne redate rien."""
    selected = scheduler(require_work=True)
    selected.request_reflex("Compare les prix", correlation_id="c")
    original = selected._reflex
    due(selected)
    await selected._maybe_speak_reflex()
    assert selected.session.reflexes == []
    await selected.handle_core_event(work())
    assert selected._reflex is original
    await selected._maybe_speak_reflex()
    assert len(selected.session.reflexes) == 1
    await selected.stop()


async def test_a_silent_brain_that_declares_nothing_still_gets_a_preamble():
    """Cerveau lent, aucune tache declaree : le reflexe DOIT parler.

    C'est le tour ordinaire -- le cerveau repond lui-meme, sans travail de fond --
    et c'est exactement celui que la porte `work_unconfirmed` faisait taire.
    """
    selected = scheduler()
    selected.request_reflex("Compare les prix entre ces architectures", correlation_id="c")
    assert selected._reflex is not None, "le candidat doit survivre a l'absence de travail declare"
    due(selected)

    await selected._maybe_speak_reflex()

    assert len(selected.session.reflexes) == 1
    assert selected._reflex_decisions["c"].reason == "brain_silent_wait"
    await selected.stop()


async def test_a_brain_that_answers_before_the_deadline_gets_no_preamble():
    """Cerveau qui repond tout de suite : le reflexe ne doit PAS parler.

    Ni par-dessus, ni derriere : la reponse utile arrivee avant l'echeance
    retire le candidat, et rien n'est demande au fournisseur.
    """
    selected = scheduler()
    selected.request_reflex("Compare les prix entre ces architectures", correlation_id="c")
    selected._enqueue(SpeechRequest("conversation", "La reponse du cerveau", correlation_id="c", source=source("c")))

    # La reponse arrivee avant l'echeance retire le candidat sur-le-champ :
    # il n'y a plus rien a dire au fournisseur quand l'echeance tombe.
    assert selected._reflex is None
    await selected._maybe_speak_reflex()

    assert selected.session.reflexes == []
    assert selected._reflex_decisions["c"].reason == "useful_content_ready"
    await selected.stop()


async def test_a_preamble_is_cancelled_when_the_answer_arrives_before_it_plays():
    """Le cerveau ne doit jamais etre double : sortie reservee, puis invalidee."""
    selected = scheduler()
    selected.request_reflex("Compare les prix entre ces architectures", correlation_id="c")
    due(selected)
    await selected._maybe_speak_reflex()
    output = selected._live_reflex.output_id
    assert selected.output_admission(output).state is OutputAdmissionState.RESERVED

    selected._enqueue(SpeechRequest("conversation", "La reponse du cerveau", correlation_id="c", source=source("c")))

    assert selected.output_admission(output).state is OutputAdmissionState.INVALIDATED
    assert output in selected._reflex_cancelled
    await selected.stop()


async def test_at_most_one_preamble_per_turn_without_declared_work():
    selected = scheduler()
    selected.request_reflex("Compare les prix entre ces architectures", correlation_id="c")
    due(selected)
    await selected._maybe_speak_reflex()
    await selected._maybe_speak_reflex()
    selected.request_reflex("Compare les prix entre ces architectures", correlation_id="c")

    assert len(selected.session.reflexes) == 1 and selected._reflex is None
    await selected.stop()


async def test_a_disabled_reflex_delay_keeps_the_legacy_silence():
    """Le mode legacy recoit toujours `reflex_delay_s=0` : rien ne doit partir."""
    selected = SpeechScheduler(core=EmptyCore(), conversation_id="conversation", session=ControllableSession(),
                               journal=RecordingJournal(), reflex_delay_s=0.0)
    selected.update_speech_context(context("conversation", "c"))
    selected._running = True
    selected.request_reflex("Compare les prix entre ces architectures", correlation_id="c")

    assert selected._reflex is None and selected._reflex_decisions["c"].reason == "disabled"
    await selected._maybe_speak_reflex()
    assert selected.session.reflexes == []
    await selected.stop()


@pytest.mark.parametrize("kind", ["completed", "failed"])
async def test_terminal_work_cancels_pending_preamble(kind):
    selected = scheduler()
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    await selected.handle_core_event(work(kind))
    await selected.handle_core_event(work())  # Reordered/duplicate start is not resurrection.
    assert selected._reflex is None
    selected.request_reflex("Compare les prix", correlation_id="c")
    assert selected._reflex is None and selected.session.reflexes == []
    await selected.stop()


async def test_wait_never_discards_a_real_core_answer():
    selected = scheduler()
    selected.request_reflex("OK", correlation_id="c")
    request = SpeechRequest("conversation", "Useful confirmed answer", correlation_id="c", source=source("c"))
    selected._enqueue(request)
    assert selected._pending == [request]
    assert selected.session.reflexes == []
    await selected.stop()


async def test_revision_gap_and_stream_gap_forget_work_attestation():
    selected = scheduler(require_work=True)
    await selected.handle_core_event(work())
    selected.request_reflex("Compare les prix", correlation_id="c")
    selected._note_revision(1)
    selected._note_revision(3)
    assert selected._reflex is None and not selected._reflex_work
    await selected.handle_core_event(work())
    selected._forget_reflex_work("stream_gap")
    selected.request_reflex("Compare les prix", correlation_id="new-c")
    due(selected)
    await selected._maybe_speak_reflex()
    assert selected.session.reflexes == []
    await selected.stop()


async def test_wait_decisions_and_work_memory_are_bounded_without_raw_text_logs():
    selected = scheduler()
    for number in range(180):
        await selected.handle_core_event(work(correlation=str(number), work_id=str(number)))
        selected.request_reflex("OK", correlation_id=str(number))
    assert len(selected._reflex_work) == len(selected._reflex_decisions) == 128
    assert not selected._reflex_admissions and not selected.session.reflexes
    assert all(event["message"] != "OK" for event in selected.journal.events)
    await selected.stop()


def test_expiration_is_checked_on_device_worker_without_an_asyncio_tick():
    admission = OutputAdmission(expires_at=time.monotonic() - 1)
    assert not admission.begin_write()
    assert admission.state is OutputAdmissionState.INVALIDATED


def test_native_write_reservation_cannot_be_rewritten_as_unplayed():
    admission = OutputAdmission()
    assert admission.begin_write()
    assert not admission.invalidate()
    assert admission.state is OutputAdmissionState.WRITE_STARTED
    admission.finish_write(succeeded=True)
    assert admission.state is OutputAdmissionState.WRITTEN


async def test_synthetic_replay_reduces_filler_and_retains_both_long_work_preambles(tmp_path):
    # Source-inspired text shapes; IDs, timing, completion and attestation are synthetic.
    # Baseline counterfactual: previous >=4 words, admitted, no useful answer yet.
    cases = [
        ("OK", True, False, False),
        ("non c est bon", True, True, False),
        ("Je voulais voir ça... attends je réfléchis", True, True, False),
        ("Non pas le premier mais le second", True, True, False),
        ("Tu peux me passer le sel", False, False, False),
        ("Explique la différence entre ces architectures", True, False, False),
        ("Donne-moi rapidement la valeur exacte", True, True, True),
        ("Compare les prix entre ces architectures", True, True, False),
        ("OK, très bien, peux-tu comparer les prix ?", True, True, False),
    ]
    baseline = observed = 0
    journal = RuntimeJournal(tmp_path)
    for index, (text, admitted, attested, ready) in enumerate(cases):
        selected = scheduler()
        selected.journal = journal
        correlation = f"replay-{index}"
        baseline += int(admitted and not ready and len(text.split()) >= 4)
        if attested:
            await selected.handle_core_event(work(correlation=correlation))
        if ready:
            selected._enqueue(SpeechRequest("conversation", "Useful answer", correlation_id=correlation, source=source(correlation)))
        if admitted:  # Existing owner/address gate remains authoritative.
            selected.request_reflex(text, correlation_id=correlation)
            if selected._reflex is not None:
                due(selected)
                await selected._maybe_speak_reflex()
        assert len(selected.session.reflexes) == int(index in (5, 7, 8))
        observed += len(selected.session.reflexes)
        await selected.stop()
    # Half the counterfactual, not a third: the unattested request (index 5) now
    # speaks too, which is exactly the turn the work gate used to silence.
    assert (baseline, observed) == (6, 3)
    events = read_jsonl_tail(journal.trace_path, limit=100)
    decisions = [event for event in events if event["kind"] == "voice.reflex.decided"]
    assert decisions and all(event["level"] == "info" for event in decisions)
    assert all(event["data"]["elapsed_ms"] >= 0 and event["data"]["correlation_id"].startswith("replay-") for event in decisions)
    assert all(text not in json.dumps(decisions, ensure_ascii=False) for text, *_ in cases)
    assert not journal.error_path.exists()


async def test_retention_saturation_stays_silent_without_forgetting_old_correlations():
    selected = scheduler()
    selected._reflex_requested.update(str(number) for number in range(4096))
    selected.request_reflex("Compare les prix", correlation_id="new")
    assert len(selected._reflex_requested) == 4096 and selected._reflex is None
    await selected.stop()


@pytest.mark.parametrize("text, correlation, avoid", [("x" * 8193, "c", ()), ("text", "bad\nID", ()), ("text", "c", ("x",) * 17)])
async def test_candidate_payload_is_bounded_before_retention(text, correlation, avoid):
    selected = scheduler()
    with pytest.raises(ValueError):
        selected.request_reflex(text, correlation_id=correlation, avoid=avoid)
    assert not selected._reflex_requested
    await selected.stop()


# --------------------------------------------------------------------------
# Activation et delai : le Control Center d'abord, la variable en secours


@pytest.fixture
def clean_env(monkeypatch):
    for name in (REFLEX_ENABLED_ENV, REFLEX_DELAY_ENV, REFLEX_REQUIRE_WORK_ENV):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_defaults_are_the_values_that_were_already_in_place(clean_env):
    """Rien d'introduit ici ne change une installation qui ne pose aucune variable."""
    assert reflex_enabled() is True
    assert reflex_delay_s() == DEFAULT_REFLEX_DELAY_MS / 1000.0 == 1.2
    assert reflex_requires_confirmed_work() is False


@pytest.mark.parametrize("raw, expected", [("0", False), ("false", False), ("non", False),
                                           ("1", True), ("oui", True), ("", True)])
def test_the_environment_is_the_fallback_switch(clean_env, raw, expected):
    clean_env.setenv(REFLEX_ENABLED_ENV, raw)
    assert reflex_enabled() is expected


def test_the_control_center_setting_wins_over_the_environment(clean_env):
    """Meme precedence que `voice_arch` : l'interface passe devant le `.env`."""
    clean_env.setenv(REFLEX_ENABLED_ENV, "0")
    clean_env.setenv(REFLEX_DELAY_ENV, "400")

    assert reflex_enabled(True) is True          # Case cochee dans l'interface.
    assert reflex_enabled(False) is False
    assert reflex_delay_s(2500) == 2.5
    assert reflex_delay_s(0) == 0.0              # « 0 = jamais » reste une valeur, pas un vide.
    # Jamais enregistre : la variable decide, puis le defaut.
    assert reflex_enabled(None) is False and reflex_delay_s(None) == .4


def test_the_delay_and_the_rollback_read_their_own_variables(clean_env):
    clean_env.setenv(REFLEX_DELAY_ENV, "800")
    clean_env.setenv(REFLEX_REQUIRE_WORK_ENV, "1")

    assert reflex_delay_s() == .8
    assert reflex_requires_confirmed_work() is True


@pytest.mark.parametrize("resolve, raw", [(reflex_delay_s, "-1"), (reflex_delay_s, "abc"),
                                          (reflex_delay_s, True), (reflex_enabled, "peut-etre")])
def test_an_unusable_setting_is_refused_rather_than_silently_replaced(clean_env, resolve, raw):
    with pytest.raises(ConfigurationError):
        resolve(raw)


def test_the_control_center_exposes_the_switch_next_to_the_delay():
    """L'utilisateur doit pouvoir couper le reflexe sans toucher au code ni au `.env`."""
    keys = [item.key for item in voice_stack.OPENAI_REALTIME.fields]
    assert "reflex_enabled" in keys and keys.index("reflex_enabled") == keys.index("ack_delay_ms") - 1

    field = next(item for item in voice_stack.OPENAI_REALTIME.fields if item.key == "reflex_enabled")
    assert field.kind == "toggle" and field.default is True
    # Le formulaire accepte les deux etats, et les range sous la pile OpenAI.
    assert voice_stack.coerce(voice_stack.OPENAI_REALTIME, {"reflex_enabled": False}) == {"reflex_enabled": False}
    settings = {}
    voice_stack.store_for(settings, voice_stack.OPENAI_REALTIME.id, {"reflex_enabled": False})
    assert settings["voice_stack_settings"]["openai_realtime"]["reflex_enabled"] is False
    assert voice_stack.settings_for(settings, voice_stack.OPENAI_REALTIME.id)["reflex_enabled"] is False


def test_an_unsaved_switch_is_not_the_same_as_a_saved_default():
    """Sans cette difference, la variable d'environnement ne servirait jamais."""
    assert voice_stack.stored_for({}, voice_stack.OPENAI_REALTIME.id) == {}
    assert voice_stack.settings_for({}, voice_stack.OPENAI_REALTIME.id)["reflex_enabled"] is True

    saved = {"voice_stack_settings": {"openai_realtime": {"reflex_enabled": True, "inconnu": 1}}}
    assert voice_stack.stored_for(saved, voice_stack.OPENAI_REALTIME.id) == {"reflex_enabled": True}
