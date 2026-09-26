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
                          "applied": {"releaseMs": 30}, "appliedAt": 12,
                          "exercises": ["pinch_primary", "pinch_secondary"]}}
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
    assert registry.consent("oui")[0] is False
    registry.note_user_turn("Garde-le !")                      # dit AVANT l'essai
    now[0] += 1
    registry.trial_applied("tr-1")
    found, why = registry.consent("garde-le")
    assert found is False and "rien dit depuis" in why
    now[0] += 1
    registry.note_user_turn("C'est parfait, garde ce réglage !")
    assert registry.consent("garde ce réglage")[0] is True, "une proposition entière, ponctuation ignorée"
    assert registry.consent("GARDE CE RÉGLAGE")[0] is True
    assert registry.consent("garde tout pour toujours")[0] is False, "une citation inventée ne se retrouve pas"
    assert registry.consent("ce réglage")[0] is False, "un morceau de proposition n'est pas un accord"
    assert registry.consent("parfait")[0] is False, "un accord d'un mot doit être toute la phrase"
    # Après l'acceptation, la fenêtre est fermée : plus rien à garder.
    registry.trial_closed()
    assert registry.consent("garde ce réglage") == (False, "aucun essai appliqué dans cette séance : il n'y a rien à garder")
    # Battements : la séance vit tant qu'elle est confirmée, puis échoit.
    now[0] += 25
    registry.report(SID, True, "drag")
    now[0] += 25
    assert registry.active() is True and registry.context()["exercise"] == "drag"
    now[0] += 6
    assert registry.active() is False, "sans battement depuis 30 s, la séance est échue"
    with pytest.raises(BarehandsCommandError):
        registry.report("court", True)
    with pytest.raises(BarehandsCommandError):
        registry.report(SID, True, trial="ep-1")


#: Tableau de la QA (deux passes) : ce qui **ne doit jamais** passer pour un
#: accord — refus, doute, retour à l'ancien, indifférence, plaisanterie,
#: constat sans demande, question —, plus quelques cas de cette reprise.
FORGERIES = [
    ("non, ne le garde surtout pas", "le garde"),
    ("oui mais c'est pire, annule-le", "oui"),
    ("ok non annule", "ok"),
    ("je ne veux pas garder ce réglage", "garder ce réglage"),
    ("peut-être, garde ce réglage", "garde ce réglage"),
    ("bof, garde-le si tu veux", "garde-le"),
    ("attends, garde ce réglage", "garde ce réglage"),
    ("génial, garde ce réglage", "génial"),
    ("nan, garde-le pas", "garde le"),
    ("nan c'est nul", "c'est nul"),
    ("nan, on garde l'ancien", "on garde l'ancien"),
    ("laisse tomber, on garde l'ancien", "on garde l'ancien"),
    ("laisse tomber", "laisse tomber"),
    ("no, garde-le", "garde le"),
    ("stop, c'est top", "c'est top"),
    ("surtout pas", "surtout pas"),
    ("n'y touche plus, remets comme avant", "remets comme avant"),
    ("N'importe quoi, garde l'ancien réglage", "garde l'ancien réglage"),
    ("ne le garde pas", "le garde"),
    ("je le garde pas", "je le garde"),
    ("je veux pas le garder", "le garder"),
    ("c'est pire, garde l'autre", "garde l'autre"),
    ("ANNULÉ, garde rien", "garde rien"),
    ("annulle, ça va pas", "ça va"),
    ("reviens en arrière, on garde l'ancien", "on garde l'ancien"),
    ("oublie ça, on garde comme avant", "on garde comme avant"),
    ("oublie, c'est mieux avant", "c'est mieux avant"),
    ("c'était mieux avant", "c'était mieux avant"),
    ("garde l'ancien", "garde l'ancien"),
    ("c'est moins bien, on garde l'ancien", "on garde l'ancien"),
    ("j'aime pas trop mais garde-le", "garde le"),
    ("peut-être, garde-le", "garde le"),
    ("oui non", "oui"),
    ("oui... enfin non", "oui"),
    ("hmm oui garde", "hmm oui garde"),
    ("oui garde-le, non attends", "oui garde le"),
    ("garde-le si tu veux, moi je m'en fiche", "garde le si tu veux"),
    ("c'est mieux mais garde pas", "c'est mieux"),
    ("c'est mieux", "c'est mieux"),
    ("ça colle toujours", "ça colle toujours"),
    ("c'est pareil", "c'est pareil"),
    ("tu peux garder, je rigole", "tu peux garder"),
    ("garde-le. Non !", "garde le"),
    ("c'est bon ? non", "c'est bon"),
    ("c'est bon ?", "c'est bon"),
    ("garde-le comme tu veux", "garde-le comme tu veux"),
    ("euh, oui", "oui"),
    ("oui c'est bien mieux", "oui"),
]

#: Accords ordinaires qui **doivent** passer, avec la citation qu'un cerveau
#: soigneux recopie (au moins une par phrase ; toutes celles listées ici passent).
AGREEMENTS = [
    ("oui", "oui"),
    ("Oui.", "oui"),
    ("ok", "ok"),
    ("GARDE-LE !!!", "garde le"),
    ("garde-le", "garde-le"),
    ("c'est parfait, garde ce réglage", "garde ce réglage"),
    ("c'est mieux et garde ce réglage", "garde ce réglage"),
    ("d'accord", "d'accord"),
    ("vas-y", "vas-y"),
    ("oui c'est bien mieux", "oui c'est bien mieux"),
    ("garde ça", "garde ça"),
    ("c'est top, on garde", "on garde"),
    ("c'est top, on garde", "c'est top, on garde"),
    ("vas-y garde-le", "vas-y garde-le"),
    ("parfait !", "parfait"),
    ("Bon. Oui, garde-le, c'est mieux !", "Oui, garde-le"),
    ("Bon. Oui, garde-le, c'est mieux !", "garde-le"),
    ("Bon. Oui, garde-le, c'est mieux !", "oui"),
    ("Bon. Oui, garde-le, c'est mieux !", "Bon. Oui, garde-le, c'est mieux !"),
    ("ouais garde", "ouais garde"),
    ("super, garde ce réglage", "garde ce réglage"),
    ("c'est beaucoup mieux, garde-le", "garde-le"),
    ("oui oui, garde", "garde"),
    ("d'accord, on le garde", "on le garde"),
    ("oui, c'est bon", "c'est bon"),
    ("oui, c'est bon", "oui"),
    ("oui, tu peux garder", "tu peux garder"),
    ("garde-le, c'est pas mal", "garde-le"),
    ("ça marche mieux, garde-le", "garde-le"),
    ("oui, enregistre", "enregistre"),
    ("valide", "valide"),
    ("c'est nickel, on garde ça", "on garde ça"),
    ("Jarvis, garde ce réglage", "garde ce réglage"),
    ("ok garde-le", "ok garde-le"),
    ("allez, garde-le", "garde-le"),
    ("oui garde le réglage", "oui garde le réglage"),
    ("garde-le, rien à redire", "garde-le"),
    ("on garde, ça ne colle plus", "on garde"),
    ("conserve ce réglage, plus de clics fantômes", "conserve ce réglage"),
    ("c'est mieux qu'avant, garde-le", "garde-le"),
]


@pytest.mark.parametrize(("said", "quote"), FORGERIES)
def test_a_refusal_a_doubt_or_a_mere_remark_never_reads_as_consent(said, quote):
    assert cal.consent_found(quote, [said])[0] is False


@pytest.mark.parametrize(("said", "quote"), AGREEMENTS)
def test_a_plain_agreement_is_found(said, quote):
    assert cal.consent_found(quote, [said]) == (True, "")


def test_the_consent_lists_are_closed_and_documented():
    assert {"non", "nan", "ne", "pas", "jamais", "annule", "retire", "enlève", "remets", "pire", "bof", "attends",
            "oublie", "ancien", "hmm", "rigole", "fiche", "pareil"} <= cal.REFUSAL_MARKERS
    assert {"peut être", "laisse tomber", "comme avant", "moins bien", "si tu veux"} <= set(cal.REFUSAL_PHRASES)
    assert {"rien à redire", "pas mal", "ne colle plus", "plus de clics fantômes"} <= set(cal.POSITIVE_IDIOMS)
    assert {"mais", "et", "sauf"} <= cal.CLAUSE_BREAKERS
    assert {"garde", "oui", "ok", "d'accord", "valide", "enregistre", "adopte", "parfait", "nickel"} <= cal.KEEP_WORDS
    assert {"c'est bon", "vas y"} <= set(cal.KEEP_PHRASES)
    assert cal.clauses("oui mais c'est pire, annule-le") == ["oui", "c'est pire", "annule le"]
    assert cal.clauses("bien par contre garde ce réglage") == ["bien", "garde ce réglage"]
    assert cal.refusal_marker("je n'aime pas") == "n"
    assert cal.refusal_marker("c'est pas mal, rien à redire") is None, "tournures positives neutralisées"
    assert cal.refusal_marker("c'est bon ?") == "?"
    # Les motifs disent ce qui manque.
    assert "ne demande pas de garder" in cal.consent_found("c'est mieux", ["c'est mieux"])[1]
    assert "« nan »" in cal.consent_found("on garde l'ancien", ["nan, on garde l'ancien"])[1] \
        or "« ancien »" in cal.consent_found("on garde l'ancien", ["nan, on garde l'ancien"])[1]
    # Le minimum de citation : un caractère ne passe ni le schéma ni la recherche.
    with pytest.raises(BarehandsCommandError):
        cal.parse_calibration_payload("calibration_accept_trial", {"userQuote": "o"})
    assert cal.consent_found("o", ["o"])[0] is False


def test_the_window_survives_a_re_registration_only_forward_and_a_second_tab_is_refused():
    now = [0.0]
    registry = CalibrationSessionRegistry(clock=lambda: now[0], ttl_s=30)
    registry.report(SID, True, "aim")
    registry.trial_applied("tr-1")
    now[0] += 1
    # Seconde page : refusée, nommée — la première garde sa séance et sa fenêtre.
    with pytest.raises(BarehandsCommandError) as caught:
        registry.report("second-tab-0123456789abcdef", True, "aim")
    assert caught.value.code == cal.SESSION_BUSY and caught.value.status == 409
    assert registry.status()["trial"] == "tr-1"
    # Échéance, puis la page revient avec son essai en cours : la fenêtre se
    # rouvre à cet instant, jamais avant (les phrases d'avant ne comptent pas).
    registry.note_user_turn("oui")
    now[0] += 40
    assert registry.active() is False
    registry.report(SID, True, "aim", trial="tr-1")
    assert registry.status()["trial"] == "tr-1"
    assert registry.consent("oui")[0] is False, "une phrase dite avant la reprise ne compte pas"
    now[0] += 1
    registry.note_user_turn("oui")
    assert registry.consent("oui")[0] is True
    # Le battement dit « plus d'essai » : la fenêtre se ferme.
    registry.report(SID, True, "aim", trial=None)
    assert registry.consent("oui")[0] is False


def test_the_brief_carries_the_calibration_mode_only_during_a_session():
    plain = build_agent_brief({"addressing": "addressed"}, "salut")
    assert "Mode CALIBRATION" not in plain
    brief = build_agent_brief({"addressing": "addressed", "calibration": {"active": True, "exercise": "aim",
                                                                        "trial": "tr-2"}}, "ça colle")
    assert BRIEF_CALIBRATION_MODE in brief and "exercice à l'écran : aim" in brief and "essai en cours : tr-2" in brief
    for needed in ("calibration_status", "calibration_record_feedback", "calibration_propose_hypothesis",
                   "calibration_apply_trial", "calibration_rerun_exercise", "calibration_resolve_trial",
                   "calibration_accept_trial", "user_quote", "ni settings_get ni settings_set", "ni Read, ni Grep, ni Bash", "DEUX phrases au plus", "jamais arrondi",
                   "ne le refais pas sans preuve nouvelle", "hypothèse", "vingt-cinq mots au plus",
                   "sous-agent d'arrière-plan", "« annule »", "reste à juger", "proposition entière",
                   "demande de garder", "« c'est mieux » constate"):
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


async def holder_poll(center, session, sid: str | None = SID, wait_s: float = 5) -> dict:  # noqa: ANN001
    """Le long-poll de la page qui **tient** la séance : elle présente son identifiant."""

    query = f"?wait_s={wait_s}" + (f"&calibration={sid}" if sid else "")
    async with session.get(f"{center.base}/api/barehands/commands{query}") as response:
        assert response.status == 200, await response.text()
        return await response.json()


class FakePage:
    """La page : prend la commande au long-poll et poste le reçu que `answer(command)` construit."""

    def __init__(self, center, session, answer) -> None:  # noqa: ANN001
        self.center, self.session, self.answer = center, session, answer
        self.seen: list[dict] = []

    async def serve_once(self) -> None:
        polled = await holder_poll(self.center, self.session)
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
    polled = await holder_poll(running, session)
    status, body, code = await running.receipt(session, polled["command"]["id"], {
        "outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": {"nope": 1}})
    assert status == 400 and code == vocab.BAD_RECEIPT
    with pytest.raises(BarehandsCommandError):
        await call
    # Un reçu de cycle de vie reste borné à 1 Ko, même quand la calibration a droit à 16.
    call = asyncio.create_task(control.barehands_commands.request("activate"))
    polled = await holder_poll(running, session)
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
        "trialRef": "tr-1", "hypothesisRef": "hy-1", "baseRef": None, "applied": {"releaseMs": 30}, "appliedAt": 900,
        "exercises": ["pinch_primary"]}}
    accepted = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": {
        "trialRef": "tr-1", "accepted": {"releaseMs": 30}, "applied": {"releaseMs": 30},
        "basis": "measured", "consent": {"source": "voice", "quote": "garde ce réglage"}}}
    seen: list[dict] = []

    def answer(command: dict) -> dict:
        seen.append(command)
        return applied if command["name"] == "calibration_apply_trial" else accepted

    async def refused_code(quote: str) -> str:
        with pytest.raises(BarehandsToolError) as caught:
            await asyncio.wait_for(hands.calibrate("calibration_accept_trial", {"userQuote": quote}), 1.0)
        return caught.value.code

    page = FakePage(running, session, answer)
    hands = tools(running)
    try:
        await control.agent_ask(JsonRequest({"text": "garde ce réglage", "context": {"addressing": "addressed"}}))
        call = asyncio.create_task(hands.calibrate("calibration_apply_trial",
                                                   {"hypothesisRef": "hy-1", "patch": {"releaseMs": 30}}))
        await page.serve_once()
        await call
        # Dit avant l'essai : ne compte pas.
        assert await refused_code("garde ce réglage") == cal.CONSENT_MISSING
        # Un tour incertain, ambiant ou ouvert par Core lui-même ne porte pas l'accord : refus **nommé**.
        await control.agent_ask(JsonRequest({"text": "garde ce réglage", "context": {"addressing": "uncertain"}}))
        assert await refused_code("garde ce réglage") == cal.CONSENT_MISSING
        await control.agent_ask(JsonRequest({"text": "garde ce réglage", "context": {"addressing": "ambient"}}))
        assert await refused_code("garde ce réglage") == cal.CONSENT_MISSING
        await control.agent_ask(JsonRequest({"text": "garde ce réglage",
                                             "context": {"addressing": "addressed", "source": "system"}}))
        assert await refused_code("garde ce réglage") == cal.CONSENT_MISSING
        # Une phrase qui refuse, même si la citation y figure.
        await control.agent_ask(JsonRequest({"text": "je ne veux pas garder ce réglage",
                                             "context": {"addressing": "addressed"}}))
        assert await refused_code("garder ce réglage") == cal.CONSENT_MISSING
        # Sans contexte (panneau du navigateur) : adressé par défaut.
        await control.agent_ask(JsonRequest({"text": "c'est mieux, garde ce réglage"}))
        assert await refused_code("garde tout pour toujours") == cal.CONSENT_MISSING
        call = asyncio.create_task(hands.calibrate("calibration_accept_trial", {"userQuote": "garde ce réglage"}))
        await page.serve_once()
        got = await call
        assert got["accepted"] == {"releaseMs": 30} and got["consent"]["source"] == "voice"
        # Gardé : la fenêtre est fermée, un second « garder » est refusé.
        assert await refused_code("garde ce réglage") == cal.CONSENT_MISSING
    finally:
        await hands.close()
    # Ce que la page a reçu : l'accord vérifié par le serveur, jamais la phrase brute du cerveau.
    accepts = [c for c in seen if c["name"] == "calibration_accept_trial"]
    assert len(accepts) == 1
    assert accepts[0]["payload"] == {"consent": {"source": "voice", "quote": "garde ce réglage",
                                                 "verifiedBy": "control_center"}}
    # Le tour du cerveau porte le mode calibration pendant la séance.
    assert "Mode CALIBRATION" in asked[0] and "exercice à l'écran : aim" in asked[0]
    assert "essai en cours : tr-1" in asked[-1]
    await declare(running, session, active=False)
    await control.agent_ask(JsonRequest({"text": "merci", "context": {"addressing": "addressed"}}))
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
                            json={"session": SID, "active": True, "extra": 1}) as response:
        assert response.status == 400
    async with session.post(running.base + BAREHANDS_CALIBRATION_SESSION_ROUTE,
                            data="[" * 5000 + "]" * 5000) as response:
        assert response.status in (400, 413)
    # Deux onglets : le second est refusé, nommé.
    assert (await declare(running, session))[0] == 200
    async with session.post(running.base + BAREHANDS_CALIBRATION_SESSION_ROUTE,
                            json={"session": "second-tab-0123456789abcdef", "active": True}) as response:
        assert response.status == 409
        assert response.headers[SETTINGS_ERROR_CODE_HEADER] == cal.SESSION_BUSY
    # Éteindre Bare Hands ferme la séance **tout de suite**.
    await running.enable(False)
    assert running.control.barehands_calibration.active() is False
    kinds = [line["kind"] for line in trace(running.control)]
    assert "barehands.calibration_session_closed" in kinds


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
                                       "hypotheses": [], "trials": [], "reviews": [],
                                       "truncated": {"measurements": 0, "feedback": 0, "evidence": 0, "trials": 0}},
                "calibration_record_feedback": {"feedback": {}, "suggestedCauses": []},
                "calibration_propose_hypothesis": {"hypothesis": {}, "evidence": []},
                "calibration_apply_trial": {"trialRef": "tr-1", "hypothesisRef": "hy-1", "baseRef": None,
                                            "applied": {"releaseMs": 30}, "appliedAt": 10, "exercises": ["pinch_primary"]},
                "calibration_resolve_trial": {"trialRef": "tr-1", "verdict": "worse", "basis": "measured", "deltas": [], "hypotheses": []},
                "calibration_rollback_trial": {"trialRef": "tr-1", "undone": ["tr-1"], "restored": {}, "active": None},
                "calibration_accept_trial": {"trialRef": "tr-1", "accepted": {}, "applied": {},
                                             "basis": None, "consent": {"source": "voice", "quote": "oui"}},
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


async def test_settings_set_refuses_engine_keys_during_a_session_and_lets_the_switch_through(running, session):  # noqa: F811
    from jarvis.runtime.settings_mcp import (
        CALIBRATION_GUARDED_OPTIONS,
        ConsoleMcpTarget,
        ConsoleSettingsTools,
        ConsoleToolError,
    )

    await running.enable()
    console = ConsoleSettingsTools(ConsoleMcpTarget("127.0.0.1", running.port))
    try:
        out = await console.set("barehands.assistance", 0.7)
        assert out["after"] == 0.7, "hors séance : écrit comme avant"
        await declare(running, session)
        values = {"barehands.assistance": 0.9, "barehands.sensitivity": 2, "barehands.target_preview": False,
                  "barehands.sleep_timeout_ms": 60000, "barehands.tool": "pan"}
        assert set(values) == CALIBRATION_GUARDED_OPTIONS
        for option, value in values.items():
            with pytest.raises(ConsoleToolError) as caught:
                await console.set(option, value)
            assert caught.value.code == cal.CALIBRATION_ACTIVE, option
            assert "calibration_*" in str(caught.value)
        assert (await console.get(["barehands.assistance"]))["settings"]["barehands.assistance"]["value"] == 0.7
        out = await console.set("barehands.diagnostics", True)
        assert out["after"] is True, "ce qui ne touche pas au geste passe pendant une séance"
    finally:
        await console.close()


async def test_a_rejected_receipt_ends_the_command_at_once_with_a_named_code(running, session):  # noqa: F811
    """**Plus d'« issue inconnue »** : la page a répondu, son reçu est refusé, le
    cerveau l'apprend tout de suite, nommé, avec l'instruction de relire."""

    await running.enable()
    await declare(running, session)
    hands = tools(running)
    try:
        # Clé de trop au premier niveau.
        call = asyncio.create_task(hands.calibrate("calibration_rerun_exercise"))
        polled = await holder_poll(running, session)
        started = asyncio.get_running_loop().time()
        status, _, code = await running.receipt(session, polled["command"]["id"], {
            "outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "extra": 1,
            "result": {"exercise": EXERCISE}})
        assert status == 400 and code == vocab.BAD_RECEIPT
        with pytest.raises(BarehandsToolError) as caught:
            await call
        assert caught.value.code == vocab.RECEIPT_INVALID
        assert "peut-être agi" in str(caught.value) and "calibration_status" in str(caught.value)
        assert asyncio.get_running_loop().time() - started < 1.0, "pas d'attente de l'échéance"
        # Reçu trop gros : nommé aussi.
        call = asyncio.create_task(hands.calibrate("calibration_status"))
        polled = await holder_poll(running, session)
        async with session.post(f"{running.base}/api/barehands/commands/{polled['command']['id']}",
                                data=b"{" + b" " * 20000 + b"}") as response:
            assert response.status == 413
        with pytest.raises(BarehandsToolError) as caught:
            await call
        assert caught.value.code == vocab.RECEIPT_TOO_LARGE
        # JSON imbriqué à l'extrême : illisible, pas une panne.
        call = asyncio.create_task(hands.calibrate("calibration_status"))
        polled = await holder_poll(running, session)
        async with session.post(f"{running.base}/api/barehands/commands/{polled['command']['id']}",
                                data="[" * 7000 + "]" * 7000) as response:
            assert response.status == 400
        with pytest.raises(BarehandsToolError) as caught:
            await call
        assert caught.value.code == vocab.RECEIPT_INVALID
    finally:
        await hands.close()
    assert "barehands.receipt_rejected" in [line["kind"] for line in trace(running.control)]


async def test_lifecycle_commands_keep_their_one_kilobyte_request_limit(running, session):  # noqa: F811
    await running.enable()
    body = '{"command": "activate"' + " " * 1500 + "}"  # valide, mais au-delà d'1 Ko
    async with session.post(running.base + "/api/barehands/commands", data=body) as response:
        assert response.status == 413
        assert response.headers[SETTINGS_ERROR_CODE_HEADER] == vocab.BAD_REQUEST


def test_core_marks_its_own_turns_so_they_never_carry_consent():
    from jarvis.adapters.control_center_brain import _turn_context
    from jarvis.domain.v2 import AddressingDecision, BrainTurnInput, BrainTurnSource

    system = BrainTurnInput(conversation_id="c", text="réveil", source=BrainTurnSource.SYSTEM,
                            addressing=AddressingDecision.ADDRESSED)
    spoken = BrainTurnInput(conversation_id="c", text="oui garde-le")
    assert _turn_context(system, None)["source"] == "system"
    assert _turn_context(spoken, None) == {"addressing": "addressed"}, "un tour ordinaire garde son contexte d'avant"



def test_a_heartbeat_that_sees_another_trial_reopens_the_window_now_never_earlier():
    """Mutant « antidater » : la fenêtre d'un nouvel essai vu par le battement
    s'ouvre à l'instant du battement ; ce qui a été dit avant ne compte pas."""

    now = [0.0]
    registry = CalibrationSessionRegistry(clock=lambda: now[0], ttl_s=30)
    registry.report(SID, True, "aim", trial="tr-1")
    now[0] += 1
    registry.note_user_turn("oui, garde-le")
    now[0] += 1
    registry.report(SID, True, "aim", trial="tr-2")
    assert registry.status()["trial"] == "tr-2"
    assert registry.consent("garde-le")[0] is False, "dit sous tr-1, ne garde pas tr-2"
    now[0] += 1
    registry.note_user_turn("garde-le")
    assert registry.consent("garde-le")[0] is True


async def test_a_switch_turned_off_elsewhere_closes_the_session_at_the_next_turn(running, session):  # noqa: F811
    """Mutant « contexte sans fermeture » : l'interrupteur éteint par un autre
    écrivain (fichier, variable d'environnement) ferme la séance au premier tour."""

    await running.enable()
    await declare(running, session)
    control = running.control
    asked: list[str] = []

    async def fake_ask(text: str, *, timeout_s: float, **_: object) -> dict:
        asked.append(text)
        return {"ok": True, "text": "ok"}

    control.agent.ask = fake_ask  # type: ignore[assignment]
    control.barehands_commands.gate = lambda: False
    await control.agent_ask(JsonRequest({"text": "oui", "context": {"addressing": "addressed"}}))
    assert "Mode CALIBRATION" not in asked[-1]
    assert control.barehands_calibration._session is None, "fermée, pas seulement masquée"  # noqa: SLF001
    assert "barehands.calibration_session_closed" in [line["kind"] for line in trace(control)]


async def test_the_page_beacon_is_a_simple_text_body_the_server_reads_strictly(running, session):  # noqa: F811
    await running.enable()
    await declare(running, session)
    body = json.dumps({"session": SID, "active": False, "exercise": None, "trial": None})
    async with session.post(running.base + BAREHANDS_CALIBRATION_SESSION_ROUTE, data=body,
                            headers={"Content-Type": "text/plain;charset=UTF-8"}) as response:
        assert response.status == 200 and (await response.json())["active"] is False
    assert running.control.barehands_calibration.active() is False
    async with session.post(running.base + BAREHANDS_CALIBRATION_SESSION_ROUTE, data="session=x&active=false",
                            headers={"Content-Type": "text/plain;charset=UTF-8"}) as response:
        assert response.status == 400, "le contenu reste du JSON strict"
    page = (Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_barehands.js").read_text(
        encoding="utf-8")
    assert "{type:'text/plain;charset=UTF-8'}" in page and "application/json'})" not in page



async def test_calibration_commands_go_only_to_the_page_holding_the_session(running, session):  # noqa: F811
    """Constat de la QA réelle : un second onglet **inactif** prenait les
    commandes de calibration et les refusait. Elles ne vont plus qu'au
    long-poll qui présente l'identifiant de la séance tenue ; une commande de
    cycle de vie va toujours au premier long-poll venu."""

    await running.enable()
    await declare(running, session)
    control = running.control
    idle = asyncio.create_task(holder_poll(running, session, sid=None, wait_s=2))
    stranger = asyncio.create_task(holder_poll(running, session, sid="another-tab-0123456789ab", wait_s=2))
    await asyncio.sleep(0.1)
    call = asyncio.create_task(control.barehands_commands.request("calibration_status", {}))
    assert (await idle)["command"] is None and (await stranger)["command"] is None, "ni l'onglet inactif ni un autre"
    got = await holder_poll(running, session, wait_s=2)
    assert got["command"]["name"] == "calibration_status" and got["command"]["payload"] == {}
    await running.receipt(session, got["command"]["id"], {
        "outcome": "applied", "lifecycle": "active", "code": None, "reason": None,
        "result": {"exercise": {"step": "aim", "phase": None, "running": True, "finished": False}}})
    with pytest.raises(BarehandsCommandError):
        await call  # schéma incomplet pour status : refus nommé, pas une échéance
    # Cycle de vie : le premier long-poll venu, même sans séance.
    idle = asyncio.create_task(holder_poll(running, session, sid=None, wait_s=2))
    await asyncio.sleep(0.1)
    call = asyncio.create_task(control.barehands_commands.request("activate"))
    polled = await idle
    assert polled["command"]["name"] == "activate"
    await running.receipt(session, polled["command"]["id"],
                          {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None})
    assert (await call)["outcome"] == "applied"
    # Un identifiant hors forme au long-poll est ignoré, jamais une erreur.
    async with session.get(f"{running.base}/api/barehands/commands?wait_s=0&calibration=%3Cx%3E") as response:
        assert response.status == 200 and (await response.json())["command"] is None


def test_the_exercise_to_rerun_is_a_closed_word_and_trials_carry_theirs():
    assert cal.parse_calibration_payload("calibration_rerun_exercise", {}) == {}
    assert cal.parse_calibration_payload("calibration_rerun_exercise", {"exercise": "pinch_primary"}) == {
        "exercise": "pinch_primary"}
    for bad in ({"exercise": "pincement"}, {"exercise": None}, {"step": "aim"}):
        with pytest.raises(BarehandsCommandError):
            cal.parse_calibration_payload("calibration_rerun_exercise", bad)
    applied = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None,
               "result": {"trialRef": "tr-1", "hypothesisRef": "hy-1", "baseRef": None,
                          "applied": {"releaseMs": 30}, "appliedAt": 12}}
    with pytest.raises(BarehandsCommandError):
        vocab.parse_command_receipt("calibration_apply_trial", applied)  # exercises absent


def test_calibration_tool_calls_are_not_counted_as_work_to_delegate(tmp_path):
    """La consigne exige des appels `calibration_*` faits dans le tour : ils ne
    signalent pas une régression de la règle de délégation."""

    from jarvis.runtime import claude_local
    from jarvis.runtime.journal import read_jsonl_tail
    from test_brain_delegation import _assistant_tool, _result, _running_agent

    assert claude_local.CALIBRATION_TOOLS == {f"mcp__jarvis-barehands__{name}" for name in CALIBRATION_TOOLS}
    agent = _running_agent(tmp_path)
    agent.turn_budget_s = 8.0
    for name in ("calibration_status", "calibration_record_feedback", "calibration_apply_trial"):
        agent._audit_turn(_assistant_tool(f"mcp__jarvis-barehands__{name}"))
    agent._audit_turn(_result("J'essaie.", uuids=["u1"], duration_ms=22_000))
    agent._audit_turn(_assistant_tool("mcp__jarvis-barehands__calibration_status"))
    agent._audit_turn(_assistant_tool("WebSearch"))
    agent._audit_turn(_result("Voilà.", uuids=["u2"], duration_ms=22_000))
    flags = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.turn_over_budget"]
    assert [f["level"] for f in flags] == ["info", "warning"]
    assert flags[0]["data"]["inline_tools"] == {} and flags[1]["data"]["inline_tools"] == {"WebSearch": 1}


def test_the_stage_mirror_equals_the_contract(tmp_path):
    js = run_node(tmp_path, "return {stages:C.STAGES}")
    assert tuple(js["stages"]) == cal.STAGES


def test_a_calibration_turn_is_never_reported_over_budget_whatever_it_calls(tmp_path):
    """Round 5 : la durée seule signalait encore les tours de calibration. Un
    tour envoyé avec la consigne du mode calibration n'est pas mesuré."""

    from jarvis.runtime import claude_local
    from jarvis.runtime.journal import read_jsonl_tail
    from test_brain_delegation import _assistant_tool, _result, _running_agent

    assert BRIEF_CALIBRATION_MODE.startswith(claude_local.CALIBRATION_TURN_MARKER)
    agent = _running_agent(tmp_path)
    agent.turn_budget_s = 8.0
    agent._calibration_turns.add("u-cal")  # noqa: SLF001 - ce que `ask` fait d'un texte qui porte la consigne
    agent._audit_turn(_assistant_tool("WebSearch"))  # noqa: SLF001
    agent._audit_turn(_result("J'essaie.", uuids=["u-cal"], duration_ms=40_000))  # noqa: SLF001
    agent._audit_turn(_assistant_tool("WebSearch"))  # noqa: SLF001
    agent._audit_turn(_result("Voilà.", uuids=["u-other"], duration_ms=40_000))  # noqa: SLF001
    flags = [e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.turn_over_budget"]
    assert len(flags) == 1 and flags[0]["level"] == "warning", "seul le tour ordinaire est mesuré"
    assert agent._calibration_turns == set()  # noqa: SLF001


async def test_ask_marks_a_turn_that_carries_the_calibration_brief(tmp_path):
    from test_brain_delegation import _running_agent

    agent = _running_agent(tmp_path)
    seen: list[str] = []

    async def fake_send(text, *, message_uuid, **_):  # noqa: ANN001, ANN003
        seen.append(message_uuid)
        agent._pending_result.set_result({"ok": True, "text": "ok"})  # noqa: SLF001

    agent.send = fake_send  # type: ignore[method-assign]
    await agent.ask(build_agent_brief({"addressing": "addressed", "calibration": {"active": True}}, "ça colle"),
                    timeout_s=5)
    await agent.ask("bonjour", timeout_s=5)
    assert agent._calibration_turns == {seen[0]}  # noqa: SLF001


def test_measurement_and_trial_rows_carry_their_effective_state():
    # Slice 07 adaptative (décision 58) : chaque ligne porte son instant de
    # séance, sur l'horloge des retours et des essais ; `reviews` rapporte les
    # décisions de revue.
    row = {"ref": "ep-1", "stage": "pinch_primary", "exerciseRef": None, "trialRef": None, "stateId": 2,
           "t": 1520, "metrics": {"release_latency_ms": 120}}
    status = {"exercise": EXERCISE, "values": {"effective": {}, "saved": {}, "trial": {}}, "measurements": [row],
              "measurementCount": 1, "feedback": [], "evidence": [], "hypotheses": [],
              "trials": [{"ref": "tr-1", "hypothesisRef": "hy-1", "baseRef": None, "patch": {}, "applied": {},
                          "state": "active", "verdict": None, "deltas": [], "appliedAt": 1,
                          "exercises": ["pinch_primary"], "baseStateId": 0, "stateId": 1, "basis": None}],
              "reviews": [{"stage": "pinch_primary", "decision": "skipped", "status": "failed",
                           "reason": "later", "attempt": 2, "t": 1800}],
              "truncated": {"measurements": 0, "feedback": 0, "evidence": 0, "trials": 0}}
    receipt = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": status}
    assert vocab.parse_command_receipt("calibration_status", receipt)["result"]["trials"][0]["stateId"] == 1
    broken = json.loads(json.dumps(receipt))
    del broken["result"]["trials"][0]["baseStateId"]
    with pytest.raises(BarehandsCommandError):
        vocab.parse_command_receipt("calibration_status", broken)
