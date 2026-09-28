"""Événements de la calibration, numérotés, et analysés par le cerveau (retours utilisateur du 28/09).

La page envoie **chaque événement métier** de la calibration à
`POST /api/barehands/calibration-event`, avec une révision monotone : étape
ouverte, revue prête, décision, proposition, essai appliqué/jugé/défait,
rapport. Le Control Center les garde et les joint à chaque tour du cerveau ;
la revue et le rapport ouvrent en plus un tour d'analyse : accusé de réception
tout de suite, puis la réponse du cerveau par la voie des relais
(`/api/agent/notices`) — sauf si une décision plus récente l'a rendue caduque.

Chaîne réelle : vrai `ControlCenter` servi en HTTP ; seul `agent.ask` est
remplacé (le CLI n'est pas lancé).
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.barehands_command import BarehandsCommandError
from jarvis.runtime.barehands_calibration import (
    CALIBRATION_ANALYSIS_ACK,
    CalibrationSessionRegistry,
    describe_calibration_event,
    parse_calibration_event,
    render_calibration_event,
)
from jarvis.runtime.control_center import BAREHANDS_CALIBRATION_EVENT_ROUTE

from test_barehands_calibration_agent import SID, declare
from test_barehands_command_channel import running, session, trace  # noqa: F401 - fixtures

REVIEW = {"type": "review_ready", "session": SID, "revision": 5, "stage": "c_pose", "label": "Posture de réveil",
          "status": "failed", "reason": "hors de la plage utilisable", "attempt": 2, "held": False,
          "cause": "majeur, annulaire et auriculaire restent dépliés",
          "checks": [{"label": "Écart pouce-index", "word": "correct", "assessment": "good"},
                     {"label": "Repli des trois autres doigts", "word": "trop dépliés", "assessment": "bad"}],
          "lines": [{"label": "Écart pouce-index de votre C", "text": "0,63", "assessment": "good", "word": "Bon"},
                    {"label": "Repli des trois autres doigts", "text": "1,74", "assessment": "bad",
                     "word": "Trop élevé"}],
          "context": {"values": [{"key": "pointingFoldStartPalms", "label": "Repli début", "saved": 1.45,
                                  "effective": 1.45}],
                      "history": [{"decision": "rerun", "status": "failed", "attempt": 1, "reason": None}],
                      "trials": [], "feedback": [{"ref": "fb-1", "text": "je n'arrive pas à replier"}]}}
DECISION = {"type": "decision_committed", "session": SID, "revision": 6, "stage": "c_pose", "decision": "validated",
            "status": "ok", "attempt": 3, "reason": None, "next_stage": "pinch_primary", "source": "ui"}
REPORT = {"type": "report_ready", "session": SID, "revision": 9, "saving": True,
          "stages": [{"label": "Main au repos", "status": "ok", "detail": "mesuré (40 image(s))"}],
          "willSave": ["seuil d’appui du pincement pouce-index (main droite)"], "kept": [], "trials": []}


# ------------------------------------------------------------------ pur

def test_an_event_is_closed_bounded_and_needs_a_session_and_a_revision():
    with pytest.raises(BarehandsCommandError):
        parse_calibration_event({"type": "stage", "session": SID, "revision": 1})
    with pytest.raises(BarehandsCommandError):
        parse_calibration_event({"type": "review_ready", "revision": 1})
    for revision in (None, 0, -1, "3", True):
        with pytest.raises(BarehandsCommandError):
            parse_calibration_event({**REVIEW, "revision": revision})
    event = parse_calibration_event({**REVIEW, "lines": [{"label": "x" * 900, "text": "1", "assessment": "great"}] * 40,
                                     "extra": "?"})
    assert len(event["lines"]) == 16 and len(event["lines"][0]["label"]) == 200
    assert event["lines"][0]["assessment"] == "neutral", "une interprétation hors vocabulaire ne passe pas"
    assert "extra" not in event
    decision = parse_calibration_event({**DECISION, "decision": "magic", "source": "hacker"})
    assert decision["decision"] is None and decision["source"] is None


def test_the_review_prompt_carries_cause_assessments_values_and_asks_to_propose_not_apply():
    text = render_calibration_event(parse_calibration_event(REVIEW))
    assert "« Posture de réveil » (c_pose) vient de se terminer : échoué, essai n° 2" in text
    assert "Cause constatée par le moteur : majeur, annulaire et auriculaire restent dépliés" in text
    assert "- Repli des trois autres doigts : trop dépliés [bad]" in text
    assert "- Écart pouce-index de votre C : 0,63 — Bon [good]" in text
    assert "- Repli des trois autres doigts : 1,74 — Trop élevé [bad]" in text
    assert "- pointingFoldStartPalms (Repli début) : 1,45 → 1,45" in text
    assert "Historique de cet exercice : essai 1 failed → à refaire." in text
    assert "fb-1 « je n'arrive pas à replier »" in text
    assert CALIBRATION_ANALYSIS_ACK in text, "le cerveau sait que l'accusé est déjà dit"
    assert "sans nom de paramètre" in text and "question" in text
    assert "calibration_prepare_trial" in text and "NON appliqué" in text
    assert "Tu n'appliques rien" in text and "ne contredis jamais une interprétation" in text
    assert "Révision de séance : 5." in text


def test_every_event_reads_as_one_line_of_the_thread():
    assert describe_calibration_event(parse_calibration_event(DECISION)) == (
        "r6 · décision : c_pose validé, essai n° 3 ; maintenant : pinch_primary (source : ui)")
    proposal = parse_calibration_event({"type": "proposal_ready", "session": SID, "revision": 7, "stage": "c_pose",
                                        "proposal_ref": "pr-1", "attempt": 2, "summary": "Assouplir le repli",
                                        "keys": [{"key": "pointingFoldStartPalms", "proposed": 1.5,
                                                  "effective": 1.45, "saved": 1.45}], "source": "brain"})
    assert "proposition pr-1 prête, NON appliquée : pointingFoldStartPalms 1.45 → 1.5" in describe_calibration_event(proposal)
    applied = parse_calibration_event({"type": "trial_applied", "session": SID, "revision": 8, "proposal_ref": "pr-1",
                                       "trial_ref": "tr-1", "action": "continue", "verified": True,
                                       "applied": {"pointingFoldStartPalms": 1.5}, "source": "panel"})
    assert describe_calibration_event(applied) == ("r8 · proposition pr-1 appliquée (tr-1, valeurs relues), "
                                                   "gardé sans refaire l'exercice (source : panel)")
    unverified = parse_calibration_event({**DECISION, "decision": "accepted_unverified", "next_stage": "report"})
    assert "réglage accepté par l'utilisateur, non revérifié" in describe_calibration_event(unverified)
    assert "maintenant : rapport final" in describe_calibration_event(unverified)


def test_the_registry_threads_events_and_knows_when_an_analysis_is_stale():
    now = [0.0]
    registry = CalibrationSessionRegistry(clock=lambda: now[0], ttl_s=30)
    assert registry.record_event(parse_calibration_event(REVIEW)) is False, "hors séance, rien n'est gardé"
    registry.report(SID, True, "c_pose")
    registry.record_event(parse_calibration_event(REVIEW))
    assert registry.superseded(5) is False
    registry.record_event(parse_calibration_event({"type": "proposal_ready", "session": SID, "revision": 6,
                                                   "proposal_ref": "pr-1", "summary": "x"}))
    assert registry.superseded(5) is False, "une proposition du cerveau ne périme pas son analyse"
    registry.record_event(parse_calibration_event({**DECISION, "revision": 7}))
    assert registry.superseded(5) is True and registry.superseded(7) is False
    context = registry.context()
    assert context["revision"] == 7 and len(context["events"]) == 3
    assert context["events"][-1].startswith("r7 · décision : c_pose validé")
    for revision in range(8, 30):
        registry.record_event(parse_calibration_event({**DECISION, "revision": revision}))
    assert len(registry.context()["events"]) == 8, "le cerveau lit les derniers, pas toute la séance"


def test_committing_a_proposal_needs_words_said_after_it_was_prepared():
    now = [0.0]
    registry = CalibrationSessionRegistry(clock=lambda: now[0], ttl_s=30)
    registry.report(SID, True, "c_pose")
    registry.note_user_turn("oui vas-y applique")
    assert registry.consent("oui vas-y applique", proposal=True)[0] is False, "aucune proposition"
    now[0] += 1
    registry.proposal_prepared("pr-1")
    found, why = registry.consent("oui vas-y applique", proposal=True)
    assert found is False and "depuis la proposition" in why, "dit avant la proposition"
    now[0] += 1
    registry.note_user_turn("Oui, applique et on refait.")
    assert registry.consent("oui, applique et on refait", proposal=True)[0] is True
    assert registry.consent("applique et on refait", proposal=False)[0] is False, "« applique » ne garde pas un essai"
    registry.note_user_turn("non, n'applique pas")
    assert registry.consent("applique pas", proposal=True)[0] is False
    registry.proposal_closed()
    assert registry.consent("oui, applique et on refait", proposal=True)[0] is False


def test_the_report_prompt_says_what_saving_will_do():
    text = render_calibration_event(parse_calibration_event(REPORT))
    assert "rapport final" in text and "- Main au repos : mesuré (40 image(s))" in text
    assert "« Enregistrer » rangera : seuil d’appui" in text


# ------------------------------------------------------------------ bout à bout

async def notices(control, after: int = 0) -> list[dict]:  # noqa: ANN001
    return await control.agent.wait_notices(after, timeout_s=0)


async def test_a_review_is_acknowledged_at_once_then_analysed_and_spoken(running, session):  # noqa: F811
    await running.enable()
    await declare(running, session, exercise="pinch_primary")
    control = running.control
    asked: list[str] = []
    release = asyncio.Event()

    async def fake_ask(text: str, *, timeout_s: float, **_: object) -> dict:
        asked.append(text)
        await release.wait()
        return {"ok": True, "text": "Tout va bien, le clic part sans retard. On passe à la suite ?"}

    control.agent.ask = fake_ask  # type: ignore[assignment]
    async with session.post(running.base + BAREHANDS_CALIBRATION_EVENT_ROUTE, json=REVIEW) as response:
        assert response.status == 200 and (await response.json()) == {"ok": True, "queued": True, "revision": 5}
    for _ in range(50):
        if asked:
            break
        await asyncio.sleep(0.01)
    early = await notices(control)
    assert [n["text"] for n in early] == [CALIBRATION_ANALYSIS_ACK], "l'accusé part avant l'analyse"
    release.set()
    await control._calibration_event_task  # noqa: SLF001
    spoken = await notices(control)
    assert [n["origin"] for n in spoken] == ["calibration_ack", "calibration_analysis"]
    assert spoken[-1]["text"].startswith("Tout va bien")
    prompt = asked[0]
    assert "Mode CALIBRATION" in prompt and "- Repli des trois autres doigts : 1,74 — Trop élevé [bad]" in prompt
    assert "exercice à l'écran : pinch_primary" in prompt
    # L'événement est aussi dans le fil de séance que le cerveau lit.
    assert "r5 · revue prête : Posture de réveil échoué, essai n° 2" in prompt
    # Un tour que la page ouvre n'est pas une parole de l'utilisateur : il ne
    # peut porter aucun accord de garder un réglage.
    assert control.barehands_calibration._session.utterances == []  # noqa: SLF001
    kinds = [line["kind"] for line in trace(control)]
    assert "barehands.calibration_event" in kinds and "barehands.calibration_event_recorded" in kinds


async def test_a_decision_reaches_the_brain_thread_and_silences_a_stale_analysis(running, session):  # noqa: F811
    await running.enable()
    await declare(running, session, exercise="c_pose")
    control = running.control
    asked: list[str] = []
    release = asyncio.Event()

    async def slow_ask(text: str, *, timeout_s: float, **_: object) -> dict:
        asked.append(text)
        if len(asked) == 1:
            await release.wait()
        return {"ok": True, "text": "Tes doigts restent dépliés : j'assouplis le repli ?"}

    control.agent.ask = slow_ask  # type: ignore[assignment]
    async with session.post(running.base + BAREHANDS_CALIBRATION_EVENT_ROUTE, json=REVIEW) as response:
        assert (await response.json()) == {"ok": True, "queued": True, "revision": 5}
    for _ in range(50):
        if asked:
            break
        await asyncio.sleep(0.01)
    # L'utilisateur valide à l'écran pendant que le cerveau réfléchit.
    async with session.post(running.base + BAREHANDS_CALIBRATION_EVENT_ROUTE, json=DECISION) as response:
        assert (await response.json()) == {"ok": True, "queued": False, "revision": 6}
    release.set()
    await control._calibration_event_task  # noqa: SLF001
    spoken = await notices(control)
    assert [n["origin"] for n in spoken] == ["calibration_ack"], "l'analyse caduque n'est pas dite"
    assert "barehands.calibration_analysis_stale" in [line["kind"] for line in trace(control)]
    # Le tour suivant du cerveau sait, explicitement, ce qui a été décidé.
    context = control.barehands_calibration.context()
    assert context["events"][-1] == "r6 · décision : c_pose validé, essai n° 3 ; maintenant : pinch_primary (source : ui)"


async def test_only_the_page_holding_the_session_can_send_events(running, session):  # noqa: F811
    await running.enable()
    async with session.post(running.base + BAREHANDS_CALIBRATION_EVENT_ROUTE, json=REVIEW) as response:
        assert response.status == 409, "aucune séance"
    await declare(running, session)
    other = {**REVIEW, "session": "another-session-0123456789"}
    async with session.post(running.base + BAREHANDS_CALIBRATION_EVENT_ROUTE, json=other) as response:
        assert response.status == 409, "une autre page"
    async with session.post(running.base + BAREHANDS_CALIBRATION_EVENT_ROUTE, json={"type": "nope"}) as response:
        assert response.status == 400
    assert await notices(running.control) == []


async def test_a_failed_analysis_is_logged_and_says_nothing_more(running, session):  # noqa: F811
    await running.enable()
    await declare(running, session)
    control = running.control

    async def failing_ask(text: str, *, timeout_s: float, **_: object) -> dict:
        return {"ok": False, "text": "", "error": "Claude n'a pas répondu", "code": "claude_timeout"}

    control.agent.ask = failing_ask  # type: ignore[assignment]
    async with session.post(running.base + BAREHANDS_CALIBRATION_EVENT_ROUTE, json=REPORT) as response:
        assert response.status == 200
    await control._calibration_event_task  # noqa: SLF001
    assert [n["origin"] for n in await notices(control)] == ["calibration_ack"]
    assert "barehands.calibration_event_failed" in [line["kind"] for line in trace(control)]


def test_publish_notice_keeps_the_silence_rule(tmp_path):
    from jarvis.runtime.claude_local import ClaudeLocalAgent

    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    assert agent.publish_notice("  ", origin="x") is False
    assert agent.publish_notice("[pas-pour-moi]", origin="x") is False
    assert agent.publish_notice("Bonjour.", origin="x") is True
    assert [n["text"] for n in agent.notices] == ["Bonjour."]
