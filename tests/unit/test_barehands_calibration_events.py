"""Événements du parcours de calibration analysés par le cerveau (retour utilisateur du 28/09).

La page envoie la revue d'un exercice terminé et le rapport final à
`POST /api/barehands/calibration-event` ; le Control Center fait dire un accusé
de réception tout de suite, puis ouvre un tour du cerveau avec ces résultats et
fait dire sa réponse par la voie des relais (`/api/agent/notices`).

Chaîne réelle : vrai `ControlCenter` servi en HTTP ; seul `agent.ask` est
remplacé (le CLI n'est pas lancé).
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.barehands_command import BarehandsCommandError
from jarvis.runtime.barehands_calibration import (
    CALIBRATION_ANALYSIS_ACK,
    parse_calibration_event,
    render_calibration_event,
)
from jarvis.runtime.control_center import BAREHANDS_CALIBRATION_EVENT_ROUTE

from test_barehands_calibration_agent import SID, declare
from test_barehands_command_channel import running, session, trace  # noqa: F401 - fixtures

REVIEW = {"type": "review", "session": SID, "stage": "pinch_primary", "label": "Pincement pouce-index",
          "status": "ok", "reason": None, "attempt": 2, "held": False,
          "lines": [{"label": "Délai du clic", "text": "92 ms"}, {"label": "Pincements comptés", "text": "5"}]}
REPORT = {"type": "report", "session": SID, "saving": True,
          "stages": [{"label": "Main au repos", "status": "ok", "detail": "mesuré (40 image(s))"}],
          "willSave": ["seuil d’appui du pincement pouce-index (main droite)"], "kept": [], "trials": []}


# ------------------------------------------------------------------ pur

def test_an_event_is_closed_bounded_and_needs_a_session():
    with pytest.raises(BarehandsCommandError):
        parse_calibration_event({"type": "stage", "session": SID})
    with pytest.raises(BarehandsCommandError):
        parse_calibration_event({"type": "review"})
    event = parse_calibration_event({**REVIEW, "lines": [{"label": "x" * 900, "text": "1"}] * 40, "extra": "?"})
    assert len(event["lines"]) == 16 and len(event["lines"][0]["label"]) == 200
    assert "extra" not in event


def test_the_review_prompt_carries_the_results_and_asks_for_a_verdict_and_a_question():
    text = render_calibration_event(parse_calibration_event(REVIEW))
    assert "« Pincement pouce-index » vient de se terminer : réussi (essai n° 2)" in text
    assert "- Délai du clic : 92 ms" in text
    assert CALIBRATION_ANALYSIS_ACK in text, "le cerveau sait que l'accusé est déjà dit"
    assert "sans nom de paramètre" in text and "question" in text
    assert "N'applique aucun essai" in text


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
        assert response.status == 200 and (await response.json()) == {"ok": True, "queued": True}
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
    assert "Mode CALIBRATION" in prompt and "- Délai du clic : 92 ms" in prompt
    assert "exercice à l'écran : pinch_primary" in prompt
    # Un tour que la page ouvre n'est pas une parole de l'utilisateur : il ne
    # peut porter aucun accord de garder un réglage.
    assert control.barehands_calibration._session.utterances == []  # noqa: SLF001
    assert "barehands.calibration_event" in [line["kind"] for line in trace(control)]


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
