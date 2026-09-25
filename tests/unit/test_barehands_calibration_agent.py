"""Agent de calibration, côté serveur (tâche adaptative Bare Hands, Slice 06, décisions 50 à 55).

Chaîne réelle exercée ici : outils MCP `calibration_*` → `BarehandsCommandTools`
→ **vrai** `ControlCenter` servi en HTTP → `BarehandsCommandBroker` → long-poll
→ reçu. Seule la page est remplacée, par un client qui appelle les deux routes
que la vraie page appelle (le comportement de la page est épinglé sous node
dans `test_barehands_calibration_agent_js.py`).

Ce que ce fichier épingle :

- **porte** : hors séance déclarée par la page, une commande `calibration_*`
  est refusée `barehands_calibration_inactive` avant toute attente ; la
  séance échoit sans battement ;
- **transport** : charge utile bornée et validée par un schéma fermé par
  commande, reçu structuré borné et fermé ; les cinq commandes d'avant gardent
  leurs garanties (pas de charge utile, reçu ≤ 1 Ko sans `result`, échéance,
  une commande à la fois) ;
- **accord** : `calibration_accept_trial` exige une citation **dite** par
  l'utilisateur depuis l'essai (tour reçu par `/api/agent/ask`) ;
- **ancrage** : le cerveau ne peut pas écrire de nombre dans une preuve
  (`value` refusé au schéma) ;
- **mode** : la consigne du tour porte le mode calibration pendant une séance,
  et seulement pendant ;
- **réglages** : `settings_set barehands.assistance|sensitivity` refusé
  pendant une séance, permis hors séance.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess

import aiohttp
import pytest

from jarvis.domain import barehands_calibration as cal
from jarvis.domain import barehands_command as vocab
from jarvis.domain.barehands_command import BarehandsCommandError
from jarvis.runtime.barehands_calibration import CalibrationSessionRegistry
from jarvis.runtime.barehands_mcp import (
    CALIBRATION_TOOLS,
    SERVER_NAME,
    BarehandsCommandTools,
    BarehandsMcpTarget,
    BarehandsToolError,
    build_server,
)
from jarvis.runtime.control_center import (
    BAREHANDS_CALIBRATION_SESSION_ROUTE,
    BRIEF_CALIBRATION_MODE,
    READ_GUARDED_ROUTES,
    SETTINGS_ERROR_CODE_HEADER,
    build_agent_brief,
)
from jarvis.runtime.mcp_tool_meta import tool_meta
from jarvis.runtime.prompt_catalog import default_prompt_registry

from test_barehands_command_channel import JsonRequest, running, session, trace  # noqa: F401 - fixtures

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "jarvis" / "runtime" / "control_center_barehands_contracts.js"
COMMANDS_JS = ROOT / "jarvis" / "runtime" / "control_center_barehands_commands.js"
SID = "s6-session-0123456789abcdef"


# ------------------------------------------------------------------ vocabulaire et formes (pur)


def test_legacy_commands_keep_their_exact_wire_and_calibration_commands_are_closed():
    # Les cinq commandes d'avant : aucune charge utile, aucun `result`.
    assert vocab.parse_command_request({"command": "activate"}) == ("activate", None)
    for bad in ({"command": "activate", "payload": {}}, {"command": "calibrate", "payload": None}):
        with pytest.raises(BarehandsCommandError) as caught:
            vocab.parse_command_request(bad)
        assert caught.value.code == vocab.BAD_REQUEST
    legacy = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None}
    assert vocab.parse_command_receipt("activate", legacy)["outcome"] == "applied"
    with pytest.raises(BarehandsCommandError) as caught:
        vocab.parse_command_receipt("activate", {**legacy, "result": {}})
    assert caught.value.code == vocab.BAD_RECEIPT
    # Calibration : la commande sans argument, puis les refus de forme.
    assert vocab.parse_command_request({"command": "calibration_status"}) == ("calibration_status", {})
    refused = [
        {"command": "calibration_status", "payload": {"x": 1}},
        {"command": "calibration_record_feedback", "payload": {"categories": ["ça colle"], "text": "x"}},
        {"command": "calibration_record_feedback", "payload": {"categories": ["fine", "laggy", "wake_hard", "unclear"],
                                                                "text": "x"}},
        {"command": "calibration_record_feedback", "payload": {"categories": ["fine"], "text": ""}},
        {"command": "calibration_apply_trial", "payload": {"hypothesisRef": "hy-1", "patch": {"jitterPx": 3}}},
        {"command": "calibration_apply_trial", "payload": {"hypothesisRef": "hy-1", "patch": {}}},
        {"command": "calibration_apply_trial", "payload": {"hypothesisRef": "ep-1", "patch": {"releaseMs": 30}}},
        {"command": "calibration_apply_trial", "payload": {"hypothesisRef": "hy-1",
                                                            "patch": {key: 1 for key in cal.TRIAL_KEYS[:9]}}},
        {"command": "calibration_propose_hypothesis", "payload": {"cause": "tracking_quality", "confidence": .4,
                                                                   "evidence": [], "feedbackRefs": []}},
        {"command": "calibration_accept_trial", "payload": {"userQuote": " "}},
        {"command": "calibration_status", "payload": {}, "extra": 1},
    ]
    for body in refused:
        with pytest.raises(BarehandsCommandError) as caught:
            vocab.parse_command_request(body)
        assert caught.value.code == vocab.BAD_REQUEST, body


def test_the_brain_cannot_write_a_number_into_evidence_or_an_outcome():
    """**Ancrage** (décision 52) : une preuve cite des mesures, jamais une valeur."""

    base = {"cause": "release_confirmation_too_slow", "confidence": .4, "feedbackRefs": []}
    for evidence in ({"metric": "release_latency_ms", "aggregate": "p95", "sourceRefs": ["ep-1"], "value": 240},
                     {"metric": "release_latency_ms", "aggregate": "p95", "sourceRefs": ["ep-1"], "values": [1]}):
        with pytest.raises(BarehandsCommandError) as caught:
            cal.parse_calibration_payload("calibration_propose_hypothesis", {**base, "evidence": [evidence]})
        assert "clé inconnue" in str(caught.value)
    outcome = {"trialRef": "tr-1", "verdict": "improved", "comparisons": [], "beforeRefs": [], "afterRefs": [],
               "feedbackRefs": []}
    for extra in ({"deltas": []}, {"before": 1}, {"after": 2}):
        with pytest.raises(BarehandsCommandError):
            cal.parse_calibration_payload("calibration_resolve_trial", {**outcome, **extra})
    with pytest.raises(BarehandsCommandError):
        cal.parse_calibration_payload("calibration_resolve_trial",
                                      {**outcome, "comparisons": [{"metric": "release_latency_ms",
                                                                   "aggregate": "p95", "delta": -40}]})


def test_calibration_receipts_are_closed_per_command_and_refusals_carry_named_faults():
    good = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None,
            "result": {"exercise": {"step": "aim", "phase": "intro", "running": True, "finished": False}}}
    assert vocab.parse_command_receipt("calibration_rerun_exercise", good)["result"]["exercise"]["step"] == "aim"
    for broken in ({**good, "result": None},
                   {**good, "result": {"exercise": {"step": "aim", "phase": "intro", "running": True,
                                                    "finished": False, "extra": 1}}},
                   {**good, "code": "barehands_calibration_refused"},
                   {**good, "result": {"exercise": good["result"]["exercise"], "note": "x"}}):
        with pytest.raises(BarehandsCommandError) as caught:
            vocab.parse_command_receipt("calibration_rerun_exercise", broken)
        assert caught.value.code == vocab.BAD_RECEIPT
    refused = {"outcome": "refused", "lifecycle": "active", "code": cal.CALIBRATION_REFUSED,
               "reason": "démentie", "result": {"errors": [{"code": "barehands_calibration_hypothesis_disproven",
                                                          "message": "démentie"}]}}
    assert vocab.parse_command_receipt("calibration_apply_trial", refused)["result"]["errors"][0]["code"] \
        == "barehands_calibration_hypothesis_disproven"
    for bad_code in ("barehands_lifecycle_refused", "barehands_flow_unconfirmed", "n'importe quoi"):
        with pytest.raises(BarehandsCommandError):
            vocab.parse_command_receipt("calibration_apply_trial", {**refused, "code": bad_code})
    with pytest.raises(BarehandsCommandError):
        vocab.parse_command_receipt("calibration_apply_trial",
                                    {**refused, "result": {"errors": [{"code": "rm -rf", "message": "x"}]}})
    # Un trial row avec une clé de trop se refuse (schéma fermé imbriqué).
    applied = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None,
               "result": {"trialRef": "tr-1", "hypothesisRef": "hy-1", "baseRef": None,
                          "applied": {"releaseMs": 30}, "appliedAt": 12}}
    assert vocab.parse_command_receipt("calibration_apply_trial", applied)["result"]["applied"] == {"releaseMs": 30}
    with pytest.raises(BarehandsCommandError):
        vocab.parse_command_receipt("calibration_apply_trial",
                                    {**applied, "result": {**applied["result"], "delta": -3}})


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "parity.cjs"
    script.write_text(f"const C=require({json.dumps(str(CONTRACTS))});\n"
                      f"const M=require({json.dumps(str(COMMANDS_JS))});\n"
                      "process.stdout.write(JSON.stringify((()=>{" + source + "})()));", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30,
                          check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_python_mirrors_equal_the_contract_and_the_page_table(tmp_path):
    """Décision 42 : le miroir a maintenant un lecteur (schéma des outils), donc il est tenu par parité."""

    js = run_node(tmp_path, """return {cats:C.USER_FEEDBACKS,causes:C.HYPOTHESIS_CAUSES,statuses:C.HYPOTHESIS_STATUSES,
      verdicts:C.TRIAL_VERDICTS,aggs:C.METRIC_AGGREGATES,metrics:C.CALIBRATION_METRICS,keys:C.TRIAL_ADVERTISED_KEYS,
      refs:C.SESSION_REF,textMax:C.FEEDBACK_TEXT_MAX,catMax:C.FEEDBACK_CATEGORIES_MAX,
      commands:M.CALIBRATION_COMMANDS,codes:M.CALIBRATION_PAGE_CODES,legacy:M.COMMANDS}""")
    assert tuple(js["cats"]) == cal.FEEDBACK_CATEGORIES
    assert tuple(js["causes"]) == cal.HYPOTHESIS_CAUSES
    assert tuple(js["statuses"]) == cal.HYPOTHESIS_STATUSES
    assert tuple(js["verdicts"]) == cal.TRIAL_VERDICTS
    assert tuple(js["aggs"]) == cal.METRIC_AGGREGATES
    assert tuple(js["metrics"]) == cal.CALIBRATION_METRICS
    assert tuple(js["keys"]) == cal.TRIAL_KEYS
    assert js["textMax"] == cal.FEEDBACK_TEXT_MAX and js["catMax"] == cal.FEEDBACK_CATEGORIES_MAX
    assert set(cal.MEASUREMENT_REF_KINDS) <= set(js["refs"].values())
    assert tuple(js["commands"]) == cal.CALIBRATION_COMMANDS == CALIBRATION_TOOLS
    assert tuple(js["codes"]) == cal.CALIBRATION_PAGE_CODES
    assert tuple(js["legacy"]) == vocab.COMMANDS


# ------------------------------------------------------------------ séance et accord (pur)


def test_the_session_expires_without_heartbeat_and_consent_needs_words_said_after_the_trial():
    now = [100.0]
    registry = CalibrationSessionRegistry(clock=lambda: now[0], ttl_s=30)
    assert registry.active() is False and registry.context() is None
    assert registry.note_user_turn("oui garde ça") is False, "hors séance, rien n'est gardé"
    registry.report(SID, True, "aim")
    assert registry.context() == {"active": True, "exercise": "aim", "trial": None}
    # Accord : pas d'essai → refus nommé.
    assert registry.consent("oui garde")[0] is False
    registry.note_user_turn("Oui, garde-le !")                 # dit AVANT l'essai
    now[0] += 1
    registry.trial_applied("tr-1")
    found, why = registry.consent("oui garde le")
    assert found is False and "rien dit depuis" in why
    now[0] += 1
    registry.note_user_turn("Bon. Oui, garde-le, c'est mieux !")
    assert registry.consent("oui garde le")[0] is True, "ponctuation et casse ne comptent pas"
    assert registry.consent("GARDE-LE, C'EST MIEUX")[0] is True
    assert registry.consent("garde tout")[0] is False, "une citation inventée ne se retrouve pas"
    assert registry.consent("gar")[0] is False, "mot tronqué : frontières de mots"
    registry.trial_closed()
    assert registry.consent("oui garde le")[0] is False
    # Battements : la séance vit tant qu'elle est confirmée, puis échoit.
    now[0] += 25
    registry.report(SID, True, "drag")
    now[0] += 25
    assert registry.active() is True and registry.context()["exercise"] == "drag"
    now[0] += 6
    assert registry.active() is False, "sans battement depuis 30 s, la séance est échue"
    # Une fermeture d'une autre séance (autre onglet) ne ferme pas la sienne.
    registry.report(SID, True)
    registry.report("autre-onglet-0123456789", False)
    assert registry.active() is True
    registry.report(SID, False)
    assert registry.active() is False
    with pytest.raises(BarehandsCommandError):
        registry.report("court", True)


def test_the_brief_carries_the_calibration_mode_only_during_a_session():
    plain = build_agent_brief({"addressing": "direct"}, "salut")
    assert "Mode CALIBRATION" not in plain
    brief = build_agent_brief({"addressing": "direct", "calibration": {"active": True, "exercise": "aim",
                                                                        "trial": "tr-2"}}, "ça colle")
    assert BRIEF_CALIBRATION_MODE in brief and "exercice à l'écran : aim" in brief and "essai en cours : tr-2" in brief
    for needed in ("calibration_status", "calibration_record_feedback", "calibration_propose_hypothesis",
                   "calibration_apply_trial", "calibration_rerun_exercise", "calibration_resolve_trial",
                   "calibration_accept_trial", "user_quote", "settings_set barehands.*", "N'invente",
                   "ne le refais pas sans preuve nouvelle", "hypothèse", "une ou deux phrases courtes"):
        assert needed in BRIEF_CALIBRATION_MODE, needed
    registry = default_prompt_registry()
    assert registry.require("backend.turn.calibration_mode").default_text == BRIEF_CALIBRATION_MODE


def test_the_tool_metadata_is_closed_and_every_calibration_tool_refuses_outside_a_session():
    for name in CALIBRATION_TOOLS:
        meta = tool_meta(SERVER_NAME, name)
        assert any("barehands_calibration_inactive" in rule for rule in meta.parameter_rules), name
        assert meta.output_format == "structured"
    assert tool_meta(SERVER_NAME, "calibration_status").side_effect == "read"
    assert tool_meta(SERVER_NAME, "calibration_accept_trial").side_effect == "write"


# ------------------------------------------------------------------ bout en bout (vrai Control Center)


class FakePage:
    """La page : prend la commande au long-poll et poste le reçu que `answer(command)` construit."""

    def __init__(self, center, session, answer) -> None:  # noqa: ANN001
        self.center, self.session, self.answer = center, session, answer
        self.seen: list[dict] = []

    async def serve_once(self) -> None:
        polled = await self.center.poll(self.session, wait_s=5)
        command = polled["command"]
        assert command is not None
        self.seen.append(command)
        status, body, _ = await self.center.receipt(self.session, command["id"], self.answer(command))
        assert status == 200, body


async def declare(center, session, active: bool = True, exercise: str | None = "aim") -> tuple[int, dict]:  # noqa: ANN001
    async with session.post(center.base + BAREHANDS_CALIBRATION_SESSION_ROUTE,
                            json={"session": SID, "active": active, "exercise": exercise}) as response:
        return response.status, await response.json()


def tools(center) -> BarehandsCommandTools:  # noqa: ANN001
    return BarehandsCommandTools(BarehandsMcpTarget("127.0.0.1", center.port))


EXERCISE = {"step": "aim", "phase": "result", "running": True, "finished": False}


async def test_outside_a_session_every_calibration_tool_is_refused_before_any_wait(running, session):  # noqa: F811
    await running.enable()
    hands = tools(running)
    try:
        for name in CALIBRATION_TOOLS:
            payload = {"calibration_record_feedback": {"categories": ["fine"], "text": "nickel"},
                       "calibration_propose_hypothesis": {"cause": "laggy" and "pointer_filter_too_smooth",
                                                          "confidence": .3, "evidence": [], "feedbackRefs": ["fb-1"]},
                       "calibration_apply_trial": {"hypothesisRef": "hy-1", "patch": {"minCutoffHz": 2}},
                       "calibration_resolve_trial": {"trialRef": "tr-1", "verdict": "inconclusive", "comparisons": [],
                                                     "beforeRefs": [], "afterRefs": [], "feedbackRefs": []},
                       "calibration_accept_trial": {"userQuote": "oui garde"}}.get(name)
            started = asyncio.get_running_loop().time()
            with pytest.raises(BarehandsToolError) as caught:
                await hands.calibrate(name, payload)
            assert caught.value.code == cal.CALIBRATION_INACTIVE, name
            assert asyncio.get_running_loop().time() - started < 1.0, "refus avant toute attente"
            assert "barehands_calibrate" in str(caught.value)
    finally:
        await hands.close()
    assert running.control.barehands_commands._pending is None  # noqa: SLF001
    assert "barehands.calibration_refused" in [line["kind"] for line in trace(running.control)]


async def test_a_declared_session_routes_payloads_and_structured_receipts_end_to_end(running, session):  # noqa: F811
    await running.enable()
    status, body = await declare(running, session)
    assert status == 200 and body["active"] is True
    async with session.get(running.base + BAREHANDS_CALIBRATION_SESSION_ROUTE) as response:
        assert (await response.json())["exercise"] == "aim"

    def answer(command: dict) -> dict:
        if command["name"] == "calibration_record_feedback":
            assert command["payload"] == {"categories": ["release_sticky"], "text": "le release colle"}
            return {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": {
                "feedback": {"ref": "fb-1", "categories": ["release_sticky"], "text": "le release colle",
                             "source": "voice", "t": 1200, "stage": "aim", "exerciseRef": None},
                "suggestedCauses": ["release_threshold_too_far", "release_confirmation_too_slow"]}}
        assert command["name"] == "calibration_apply_trial"
        return {"outcome": "refused", "lifecycle": "active", "code": cal.CALIBRATION_REFUSED,
                "reason": "démentie", "result": {"errors": [{"code": "barehands_calibration_hypothesis_disproven",
                                                           "message": "hy-1 a été démentie par un essai"}]}}

    page = FakePage(running, session, answer)
    hands = tools(running)
    try:
        call = asyncio.create_task(hands.calibrate("calibration_record_feedback",
                                                   {"categories": ["release_sticky"], "text": "le release colle"}))
        await page.serve_once()
        got = await call
        assert got["outcome"] == "applied" and got["feedback"]["ref"] == "fb-1"
        assert got["suggestedCauses"] == ["release_threshold_too_far", "release_confirmation_too_slow"]
        assert "pas un réglage" in got["note"]
        call = asyncio.create_task(hands.calibrate("calibration_apply_trial",
                                                   {"hypothesisRef": "hy-1", "patch": {"releaseMs": 30}}))
        await page.serve_once()
        with pytest.raises(BarehandsToolError) as caught:
            await call
        assert caught.value.code == cal.CALIBRATION_REFUSED
        assert "barehands_calibration_hypothesis_disproven" in str(caught.value), "la faute précise est nommée"
    finally:
        await hands.close()
    # Le journal porte le chemin, jamais la parole de l'utilisateur.
    lines = json.dumps(trace(running.control), ensure_ascii=False)
    assert "le release colle" not in lines


async def test_receipt_bounds_and_schemas_depend_on_the_command(running, session):  # noqa: F811
    await running.enable()
    await declare(running, session)
    control = running.control
    # Un reçu de calibration hors schéma : refusé, le cerveau apprend l'échéance.
    control.barehands_commands.deadline_s = 1.0
    call = asyncio.create_task(control.barehands_commands.request("calibration_status", {}))
    polled = await running.poll(session, wait_s=5)
    status, body, code = await running.receipt(session, polled["command"]["id"], {
        "outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": {"nope": 1}})
    assert status == 400 and code == vocab.BAD_RECEIPT
    with pytest.raises(BarehandsCommandError):
        await call
    # Un reçu de cycle de vie reste borné à 1 Ko, même quand la calibration a droit à 16.
    call = asyncio.create_task(control.barehands_commands.request("activate"))
    polled = await running.poll(session, wait_s=5)
    status, body, code = await running.receipt(session, polled["command"]["id"], {
        "outcome": "applied", "lifecycle": "active", "code": None, "reason": "x" * 1500})
    assert status == 413 and code == vocab.BAD_RECEIPT
    with pytest.raises(BarehandsCommandError):
        await call
    # Une commande à la fois, charge utile ou pas.
    first = asyncio.create_task(control.barehands_commands.request("calibration_status", {}))
    await asyncio.sleep(0.05)
    async with session.post(running.base + "/api/barehands/commands",
                            json={"command": "calibration_status"}) as response:
        assert response.status == 409 and response.headers[SETTINGS_ERROR_CODE_HEADER] == vocab.COMMAND_BUSY
    with pytest.raises(BarehandsCommandError):
        await first
    # Demande de calibration trop grosse : 413 avant toute file.
    async with session.post(running.base + "/api/barehands/commands",
                            data=json.dumps({"command": "calibration_status", "payload": {"x": "y" * 5000}})) as response:
        assert response.status == 413


async def test_accept_needs_the_users_own_words_said_after_the_trial(running, session):  # noqa: F811
    await running.enable()
    await declare(running, session)
    control = running.control
    asked: list[str] = []

    async def fake_ask(text: str, *, timeout_s: float, **_: object) -> dict:
        asked.append(text)
        return {"ok": True, "text": "ok"}

    control.agent.ask = fake_ask  # type: ignore[assignment]
    applied = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": {
        "trialRef": "tr-1", "hypothesisRef": "hy-1", "baseRef": None, "applied": {"releaseMs": 30}, "appliedAt": 900}}
    accepted = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": {
        "trialRef": "tr-1", "accepted": {"releaseMs": 30}, "applied": {"releaseMs": 30},
        "consent": {"source": "voice", "quote": "oui garde-le"}}}
    seen: list[dict] = []

    def answer(command: dict) -> dict:
        seen.append(command)
        return applied if command["name"] == "calibration_apply_trial" else accepted

    page = FakePage(running, session, answer)
    hands = tools(running)
    try:
        await control.agent_ask(JsonRequest({"text": "oui garde-le", "context": {"addressing": "direct"}}))
        call = asyncio.create_task(hands.calibrate("calibration_apply_trial",
                                                   {"hypothesisRef": "hy-1", "patch": {"releaseMs": 30}}))
        await page.serve_once()
        await call
        # Dit avant l'essai : ne compte pas.
        with pytest.raises(BarehandsToolError) as caught:
            await hands.calibrate("calibration_accept_trial", {"userQuote": "oui garde-le"})
        assert caught.value.code == cal.CONSENT_MISSING and "rien dit depuis" in str(caught.value)
        # Un tour incertain (télé, tiers) ne porte pas l'accord.
        await control.agent_ask(JsonRequest({"text": "oui garde-le", "context": {"addressing": "uncertain"}}))
        with pytest.raises(BarehandsToolError):
            await hands.calibrate("calibration_accept_trial", {"userQuote": "oui garde-le"})
        await control.agent_ask(JsonRequest({"text": "c'est mieux, oui garde-le", "context": {"addressing": "direct"}}))
        with pytest.raises(BarehandsToolError) as caught:
            await hands.calibrate("calibration_accept_trial", {"userQuote": "garde tout pour toujours"})
        assert caught.value.code == cal.CONSENT_MISSING
        call = asyncio.create_task(hands.calibrate("calibration_accept_trial", {"userQuote": "Oui, garde-le"}))
        await page.serve_once()
        got = await call
        assert got["accepted"] == {"releaseMs": 30} and got["consent"]["source"] == "voice"
    finally:
        await hands.close()
    # Ce que la page a reçu : l'accord vérifié par le serveur, jamais la phrase brute du cerveau.
    assert seen[-1]["payload"] == {"consent": {"source": "voice", "quote": "Oui, garde-le",
                                               "verifiedBy": "control_center"}}
    # Le tour du cerveau porte le mode calibration pendant la séance.
    assert "Mode CALIBRATION" in asked[0] and "exercice à l'écran : aim" in asked[0]
    assert "essai en cours : tr-1" in asked[-1]
    await declare(running, session, active=False)
    await control.agent_ask(JsonRequest({"text": "merci", "context": {"addressing": "direct"}}))
    assert "Mode CALIBRATION" not in asked[-1], "hors séance, le contexte est celui d'avant"


async def test_the_session_route_is_guarded_and_refused_while_barehands_is_off(running, session):  # noqa: F811
    assert BAREHANDS_CALIBRATION_SESSION_ROUTE in READ_GUARDED_ROUTES
    status, body = await declare(running, session)
    assert status == 409 and body["error"]["code"] == "barehands_disabled"
    await running.enable()
    async with session.post(running.base + BAREHANDS_CALIBRATION_SESSION_ROUTE,
                            json={"session": SID, "active": True},
                            headers={"Origin": "http://evil.example"}) as response:
        assert response.status == 403
        assert response.headers[SETTINGS_ERROR_CODE_HEADER] == vocab.FORBIDDEN_ORIGIN
    async with session.post(running.base + BAREHANDS_CALIBRATION_SESSION_ROUTE,
                            json={"session": SID, "active": True, "trial": "tr-1"}) as response:
        assert response.status == 400


# ------------------------------------------------------------------ outils MCP


async def test_the_calibration_tools_validate_arguments_and_return_their_typed_results():
    from mcp.shared.memory import create_connected_server_and_client_session
    import jsonschema

    calls: list[tuple[str, dict | None]] = []

    class Page:
        async def calibrate(self, tool: str, payload: dict | None = None) -> dict:
            calls.append((tool, payload))
            result = {
                "calibration_status": {"exercise": EXERCISE, "values": {"effective": {}, "saved": {}, "trial": {}},
                                       "measurements": [], "measurementCount": 0, "feedback": [], "evidence": [],
                                       "hypotheses": [], "trials": []},
                "calibration_record_feedback": {"feedback": {}, "suggestedCauses": []},
                "calibration_propose_hypothesis": {"hypothesis": {}, "evidence": []},
                "calibration_apply_trial": {"trialRef": "tr-1", "hypothesisRef": "hy-1", "baseRef": None,
                                            "applied": {"releaseMs": 30}, "appliedAt": 10},
                "calibration_resolve_trial": {"trialRef": "tr-1", "verdict": "worse", "deltas": [], "hypotheses": []},
                "calibration_rollback_trial": {"trialRef": "tr-1", "undone": ["tr-1"], "restored": {}, "active": None},
                "calibration_accept_trial": {"trialRef": "tr-1", "accepted": {}, "applied": {},
                                             "consent": {"source": "voice", "quote": "oui"}},
                "calibration_rerun_exercise": {"exercise": EXERCISE},
                "calibration_next_exercise": {"exercise": EXERCISE},
            }[tool]
            return {"outcome": "applied", "note": "n", **result}

    server = build_server(tools=Page())  # type: ignore[arg-type]
    advertised = {tool.name: tool for tool in await server.list_tools()}
    arguments = {
        "calibration_record_feedback": {"categories": ["release_sticky"], "text": "le release colle"},
        "calibration_propose_hypothesis": {"cause": "release_confirmation_too_slow", "confidence": 0.4,
                                           "evidence": [{"metric": "release_latency_ms", "aggregate": "p95",
                                                         "source_refs": ["ep-1", "ep-2"]}],
                                           "feedback_refs": ["fb-1"]},
        "calibration_apply_trial": {"hypothesis_ref": "hy-1", "patch": {"releaseMs": 30, "releaseFrames": 1}},
        "calibration_resolve_trial": {"trial_ref": "tr-1", "verdict": "worse",
                                      "comparisons": [{"metric": "release_latency_ms", "aggregate": "p95"}],
                                      "before_refs": ["ep-1"], "after_refs": ["ep-3"], "feedback_refs": []},
        "calibration_accept_trial": {"user_quote": "oui garde"},
    }
    async with create_connected_server_and_client_session(server) as client:
        for name in CALIBRATION_TOOLS:
            assert advertised[name].inputSchema["additionalProperties"] is False
            result = await client.call_tool(name, arguments.get(name, {}))
            assert result.isError is False, (name, result.content[0].text)
            jsonschema.validate(result.structuredContent, advertised[name].outputSchema)
        # Refus d'arguments : inconnu, hors vocabulaire, nombre dans une preuve.
        for name, args in (("calibration_status", {"x": 1}),
                           ("calibration_record_feedback", {"categories": ["ça colle"], "text": "x"}),
                           ("calibration_apply_trial", {"hypothesis_ref": "hy-1", "patch": {"jitterPx": 3}}),
                           ("calibration_propose_hypothesis", {"cause": "laggy", "confidence": 2}),
                           ("calibration_propose_hypothesis", {"cause": "pointer_filter_too_smooth", "confidence": .3,
                                                               "evidence": [{"metric": "pointer_lag_ms",
                                                                             "aggregate": "p95", "source_refs": ["ep-1"],
                                                                             "value": 120}]})):
            result = await client.call_tool(name, args)
            assert result.isError is True, (name, args)
            assert "rien n'a été envoyé" in result.content[0].text
    # Ce que la page reçoit : les noms du contrat de séance (camelCase), pas ceux des arguments.
    sent = dict(calls)
    assert sent["calibration_propose_hypothesis"] == {
        "cause": "release_confirmation_too_slow", "confidence": 0.4,
        "evidence": [{"metric": "release_latency_ms", "aggregate": "p95", "sourceRefs": ["ep-1", "ep-2"]}],
        "feedbackRefs": ["fb-1"]}
    assert sent["calibration_resolve_trial"]["afterRefs"] == ["ep-3"]
    assert sent["calibration_accept_trial"] == {"userQuote": "oui garde"}
    assert len(calls) == len(CALIBRATION_TOOLS), "aucun refus d'argument n'a rien envoyé"


# ------------------------------------------------------------------ réglages pendant une séance


async def test_settings_set_refuses_tuning_keys_during_a_session_and_lets_the_switch_through(running, session):  # noqa: F811
    from jarvis.runtime.settings_mcp import ConsoleMcpTarget, ConsoleSettingsTools, ConsoleToolError

    await running.enable()
    console = ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", running.port))
    try:
        out = await console.set("barehands.assistance", 0.7)
        assert out["after"] == 0.7, "hors séance : écrit comme avant"
        await declare(running, session)
        for option in ("barehands.assistance", "barehands.sensitivity"):
            with pytest.raises(ConsoleToolError) as caught:
                await console.set(option, 0.9)
            assert caught.value.code == cal.CALIBRATION_ACTIVE
            assert "calibration_*" in str(caught.value)
        assert (await console.get(["barehands.assistance"]))["settings"]["barehands.assistance"]["value"] == 0.7
        out = await console.set("barehands.sleep_timeout_ms", 60000)
        assert out["after"] == 60000, "le reste passe pendant une séance"
    finally:
        await console.close()
