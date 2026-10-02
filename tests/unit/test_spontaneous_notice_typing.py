"""Relais spontanés typés, par le vrai chemin du Control Center jusqu'à Core.

Tests ROUGES de la Slice 01 (reprise QA, tâche
`jarvis-voice-stale-speech-presentation`), que la Slice 03 doit faire passer.

T6a/T6b (`test_speech_presentation_revalidation.py`) appellent
`BrainOrchestrator.announce_notice` directement : ils ne passent pas par le lieu
réel du défaut. Celui-ci est le Control Center :

    ControlCenter._analyse_calibration_event
        agent.publish_notice(CALIBRATION_ANALYSIS_ACK, origin="calibration_ack")   # l'accusé
        agent.publish_notice(<analyse>, origin="calibration_analysis")             # l'analyse
    -> file des relais de l'agent, servie par GET /api/agent/notices
       (`ControlCenter.agent_notices`)
    -> ControlCenterBrainBackend.next_notices (Core)             : ne rend que des textes
    -> JarvisCoreApplication._brain_notice_loop -> announce_notice : RESULT, sans TTL ni clé
    -> brain.speech.requested sur le bus de Core

Contrat visé (`docs/02-architecture.md` de la tâche, Slice 03) : l'accusé est
transitoire (ACK ou PROGRESS) avec une durée de vie, l'analyse est un RESULT, et
les deux partagent `supersedes_key = "calibration:<id de l'évènement>"`. Aucun
relais sans genre.

Couplage volontairement borné : les tests ne supposent aucune signature (ni de
`publish_notice`, ni d'`announce_notice`). Ils lisent ce qui ARRIVE à Core — la
charge utile servie par `/api/agent/notices` (champs `kind`, `supersedes_key`,
`ttl_s` ou `expires_at`) — et ce que Core ÉMET — la `SpeechRequest` publiée
(`kind`, `supersedes_key`, `expires_at`).

Seul le transport HTTP est remplacé : le client Core (`next_notices`) appelle le
vrai gestionnaire de route en processus. Tout tourne en temps virtuel.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
from jarvis.core.brain_service import BRAIN_SPEECH_REQUESTED
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import BrainTurnInput, SpeechKind
from jarvis.runtime import barehands_test_mode as barehands
from jarvis.runtime.barehands_calibration import CALIBRATION_ANALYSIS_ACK, parse_calibration_event
from jarvis.runtime.control_center import ControlCenter
from tests.fakes.virtual_time_loop import run_virtual
from tests.unit.test_speech_presentation_revalidation import ScriptedBrain

SID = "s6-session-0123456789abcdef"
REVIEW = {"type": "review_ready", "session": SID, "revision": 5, "stage": "c_pose", "label": "Posture de réveil",
          "status": "failed", "reason": "hors de la plage utilisable", "attempt": 2, "held": False,
          "cause": "majeur, annulaire et auriculaire restent dépliés",
          "checks": [{"label": "Repli des trois autres doigts", "word": "trop dépliés", "assessment": "bad"}],
          "lines": [{"label": "Repli des trois autres doigts", "text": "1,74", "assessment": "bad",
                     "word": "Trop élevé"}]}
REPORT = {"type": "report_ready", "session": SID, "revision": 9, "saving": True,
          "stages": [{"label": "Main au repos", "status": "ok", "detail": "mesuré (40 image(s))"}],
          "willSave": [], "kept": [], "trials": []}
ANALYSIS = "Tes trois derniers doigts restent dépliés : j'assouplis le repli ?"
RELAY = "Le sous-agent a fini : le transcript est prêt."
TRANSIENT = {SpeechKind.ACK.value, SpeechKind.PROGRESS.value}
KINDS = {kind.value for kind in SpeechKind}
CALIBRATION_PREFIX = "calibration:"


def kind_of(value: object) -> str | None:
    """`kind` tel que déclaré, en minuscules (`"ack"`, `SpeechKind.ACK`, `"ACK"`)."""
    if value is None:
        return None
    return str(getattr(value, "value", value)).lower()


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


class QueryRequest:
    def __init__(self, **query: str) -> None:
        self.query = query


class InProcessNoticeRoute:
    """Le transport HTTP de `next_notices`, remplacé par le vrai gestionnaire de route."""

    def __init__(self, control: ControlCenter) -> None:
        self.control = control

    def get(self, url: str, *, params: dict[str, str]):
        assert url.endswith("/api/agent/notices"), url
        return _Reply(self.control, params)


class _Reply:
    def __init__(self, control: ControlCenter, params: dict[str, str]) -> None:
        self.control, self.params = control, params

    async def __aenter__(self):
        response = await self.control.agent_notices(QueryRequest(**self.params))
        self.status, self._body = response.status, response.text
        return self

    async def __aexit__(self, *exc) -> bool:  # noqa: ANN002
        return False

    async def json(self) -> object:
        return json.loads(self._body)


async def calibration_center(tmp_path) -> ControlCenter:
    """Vrai Control Center (sans HTTP ni CLI), Bare Hands actif, séance de calibration ouverte."""
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    await control.save_barehands(JsonRequest({"enabled": True}))
    control.barehands_calibration.report(SID, True, "c_pose")

    async def ask(text: str, *, timeout_s: float, **_: object) -> dict:
        del text, timeout_s
        return {"ok": True, "text": ANALYSIS}

    control.agent.ask = ask  # type: ignore[assignment] - le CLI n'est pas lancé
    return control


async def analyse(control: ControlCenter, body: dict) -> dict:
    event = parse_calibration_event(body)
    control.barehands_calibration.record_event(event)
    await control._analyse_calibration_event(event)  # noqa: SLF001 - le lieu réel du défaut
    return event


async def served_notices(control: ControlCenter) -> list[dict]:
    """Ce que `/api/agent/notices` sert à Core depuis le début de la file."""
    response = await control.agent_notices(QueryRequest(after="0", wait="0", epoch=str(control.agent.notice_epoch)))
    return json.loads(response.text)["notices"]


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv(barehands.VENDOR_ENV, raising=False)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)


def test_the_calibration_notices_reach_core_typed_with_a_shared_key(tmp_path, clean_env):
    """T6c — chemin réel du Control Center : la charge servie à Core pour l'accusé
    est transitoire (ACK/PROGRESS) avec une durée de vie ; celle de l'analyse est
    un RESULT ; les deux portent la même `supersedes_key` `calibration:<évènement>`,
    et un autre évènement en porte une autre."""

    async def scenario():
        control = await calibration_center(tmp_path)
        try:
            await analyse(control, REVIEW)
            await analyse(control, REPORT)
            return await served_notices(control)
        finally:
            control.barehands_commands.close()

    notices = run_virtual(scenario())
    assert [notice["text"] for notice in notices] == [CALIBRATION_ANALYSIS_ACK, ANALYSIS] * 2, notices
    review_ack, review_analysis, report_ack, report_analysis = notices
    assert kind_of(review_ack.get("kind")) in TRANSIENT, f"l'accusé n'arrive pas transitoire à Core : {review_ack}"
    assert review_ack.get("ttl_s") or review_ack.get("expires_at"), f"l'accusé n'a pas de durée de vie : {review_ack}"
    assert kind_of(review_analysis.get("kind")) == SpeechKind.RESULT.value, (
        f"l'analyse n'arrive pas en RESULT : {review_analysis}")
    key = review_ack.get("supersedes_key")
    assert isinstance(key, str) and key.startswith(CALIBRATION_PREFIX) and len(key) > len(CALIBRATION_PREFIX), (
        f"l'accusé n'a pas de supersedes_key calibration:<évènement> : {review_ack}")
    assert review_analysis.get("supersedes_key") == key, (
        f"l'accusé et l'analyse du même évènement ne partagent pas leur clé : {review_ack} / {review_analysis}")
    assert report_ack.get("supersedes_key") == report_analysis.get("supersedes_key") != key, (
        f"deux évènements de calibration partagent une clé, ou un évènement n'en a pas : {notices}")


def test_no_notice_reaches_core_without_an_explicit_kind(tmp_path, clean_env):
    """T6e — « aucun relais sans genre » : tout ce que `/api/agent/notices` sert à
    Core — accusé et analyse de calibration, relais de fin de sous-agent — porte
    un `kind` explicite du vocabulaire `SpeechKind`."""

    async def scenario():
        control = await calibration_center(tmp_path)
        try:
            await analyse(control, REVIEW)
            # Relais de fin de sous-agent : le tour que le CLI ouvre de lui-même.
            control.agent._push_notice({"type": "result", "subtype": "success", "result": RELAY,  # noqa: SLF001
                                        "session_id": "sid", "origin": {"kind": "task-notification"}})
            return await served_notices(control)
        finally:
            control.barehands_commands.close()

    notices = run_virtual(scenario())
    assert [notice["text"] for notice in notices] == [CALIBRATION_ANALYSIS_ACK, ANALYSIS, RELAY], notices
    untyped = [notice for notice in notices if kind_of(notice.get("kind")) not in KINDS]
    assert untyped == [], f"relais servis à Core sans genre explicite : {untyped}"


def test_core_emits_the_calibration_notices_typed(tmp_path, clean_env):
    """T6d — de bout en bout jusqu'à Core : le vrai client (`next_notices`) et la
    vraie boucle de relais de `JarvisCoreApplication` ; les `SpeechRequest` que
    Core publie portent le genre, l'échéance et la clé partagée."""

    async def scenario():
        control = await calibration_center(tmp_path)
        client = ControlCenterBrainBackend(base_url="http://control-center.invalid")
        route = InProcessNoticeRoute(control)

        async def in_process_session():
            return route

        client._session = in_process_session  # noqa: SLF001 - seul le transport est remplacé
        brain = ScriptedBrain()
        brain.next_notices = client.next_notices  # capacité détectée structurellement par Core
        core = JarvisCoreApplication(data_root=tmp_path / "core", brain_backend=brain)
        await core.start()
        queue = core.events.subscribe()
        try:
            # La conversation de la Session ouverte : celle qui a la parole, où va un
            # relais qui ne nomme pas la sienne (Boards, `docs/boards.md`).
            conversation_id = (await core.sessions.current()).binding.conversation_id
            # Un tour silencieux installe l'intention courante que les relais empruntent.
            await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Je lance la calibration."))
            while core.brain.active_turn_count:
                await asyncio.sleep(0.01)
            # Le premier appel de `next_notices` fixe le curseur sans rien rejouer.
            await asyncio.sleep(2.0)
            await analyse(control, REVIEW)
            speeches: list[dict] = []
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 60.0
            while len(speeches) < 2 and loop.time() < deadline:
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=deadline - loop.time())
                except TimeoutError:
                    break
                if envelope.message_type == BRAIN_SPEECH_REQUESTED:
                    speeches.append(dict(envelope.payload))
            return speeches
        finally:
            core.events.unsubscribe(queue)
            await core.stop()
            control.barehands_commands.close()

    speeches = run_virtual(scenario())
    assert [speech["text"] for speech in speeches] == [CALIBRATION_ANALYSIS_ACK, ANALYSIS], (
        f"Core n'a pas publié l'accusé puis l'analyse : {speeches}")
    ack, analysis = speeches
    assert kind_of(ack["kind"]) in TRANSIENT and ack.get("expires_at"), (
        f"Core publie l'accusé comme une parole durable sans échéance : kind={ack['kind']} "
        f"expires_at={ack.get('expires_at')} supersedes_key={ack.get('supersedes_key')}")
    assert kind_of(analysis["kind"]) == SpeechKind.RESULT.value, analysis
    key = ack.get("supersedes_key")
    assert isinstance(key, str) and key.startswith(CALIBRATION_PREFIX) and analysis.get("supersedes_key") == key, (
        f"accusé et analyse ne partagent pas une clé calibration:<évènement> : {ack.get('supersedes_key')} / "
        f"{analysis.get('supersedes_key')}")
