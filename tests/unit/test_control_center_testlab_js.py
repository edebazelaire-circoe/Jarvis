"""Logique pure du panneau Test Lab (Slice 11), exécutée par node.

Le module servi à la page (`jarvis/runtime/control_center_testlab.js`) est
exécuté tel quel, contre des documents construits par le domaine Python : un
`RunOutcomeSummary`, une `CatalogEntry`, une `RunComparison`, une invite guidée.
Ce que ces tests prouvent :

- l'écran AFFICHE les documents du serveur et n'en redérive aucun verdict ;
- la seule dérivation du fichier, `profileGate`, rend exactement la décision de
  `check_profile_permission` (comparaison cas par cas avec le Python) ;
- une exécution non mesurable, refusée, en panne ou à métrique manquante se lit
  en clair, sans journal ni ligne de commande ;
- AUCUN acquittement ne part sans un clic humain : ni sur un sondage répété, ni
  sur un re-rendu, ni sur un minuteur, ni sur un clic scripté ;
- le compte à rebours guidé affiche le `remaining_s` du serveur et n'impose
  jamais de délai à lui : les boutons restent actifs à zéro.

Contrat : `docs/testlab.md`, sections « Native API, CLI and HTTP » et
« Control Center panel ».
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import TESTLAB_SCRIPT_MARKER, ControlCenter
from jarvis.testlab.api import run_view
from jarvis.testlab.catalog import CatalogEntry, ProfileAvailability
from jarvis.testlab.compare import compare_runs
from jarvis.testlab.diagnostics import AssertionOutcome, AssertionResult
from jarvis.testlab.http import TESTLAB_ROUTE
from jarvis.testlab.implementations import ImplementationEntry
from jarvis.testlab.manifests import DiagnosticManifest
from jarvis.testlab.profiles import (
    Capability,
    ProfileName,
    ResourceGrant,
    check_profile_permission,
)
from jarvis.testlab.runs import ArtifactKind, ArtifactRef, RunFailure, RunStatus
from jarvis.testlab.identity import format_run_id
from tests.fakes.testlab import T0, at, queued_run, self_echo_spec

#: Un second identifiant d'exécution du même instant : seul le nonce change.
OTHER_RUN_ID = format_run_id(T0, "fedcba9876543210")

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_testlab.js"
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"


# ----------------------------------------------------------------- harnais

def run_node(tmp_path: Path, source: str, data: object = None) -> object:
    """Exécuter `source` avec le module chargé sous `L` et les données sous `D`."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data_file = tmp_path / "testlab-data.json"
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "testlab-test.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n"
        "const L=require(MODULE_PATH);\n"
        f"const D=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data_file))},'utf8'));\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const tick=()=>new Promise(r=>setImmediate(r));\n"
        "(async()=>{" + source + "})().then(value=>out(value===undefined?null:value))"
        ".catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


# --------------------------------------------------------------- fixtures

def available(name: ProfileName) -> ImplementationEntry:
    spec = self_echo_spec().profiles[name]
    return ImplementationEntry(spec.implementation, name, factory=lambda **_: None)


def reserved(name: ProfileName) -> ImplementationEntry:
    """Un nom d'implémentation déclaré mais sans fabrique : le « runner réservé »."""
    spec = self_echo_spec().profiles[name]
    return ImplementationEntry(spec.implementation, name, unavailable_reason="reserved_name",
                               detail="this implementation name is reserved and has no runner yet")


def entry(*, reserved_profiles: tuple[ProfileName, ...] = ()) -> CatalogEntry:
    spec = self_echo_spec()
    manifest = DiagnosticManifest(spec)
    return CatalogEntry(manifest, "voice/self_echo.v1.json", manifest.fingerprint(), {
        name: ProfileAvailability(
            name, reserved(name) if name in reserved_profiles else available(name),
            profile.requires, profile.cost)
        for name, profile in spec.profiles.items()})


def declaration() -> dict:
    return entry().to_dict()


def profile_document(name: ProfileName, *, reserved_profiles: tuple[ProfileName, ...] = ()) -> dict:
    entries = entry(reserved_profiles=reserved_profiles).to_dict()["profiles"]
    return next(item for item in entries if item["profile"] == name.value)


def status_document(grant: ResourceGrant, *, devices_free: bool = True, refusal: str | None = None) -> dict:
    """La forme de `GET /api/testlab/status` que l'écran lit (champs utilisés seulement)."""
    return {"config": {"grant": grant.to_dict(), "grant_refusal": refusal,
                       "opt_ins": {"JARVIS_TESTLAB_LIVE": Capability.REALTIME_PROVIDER in grant.capabilities}},
            "contention": {"state": "free" if devices_free else "busy",
                           "available": devices_free, "holder": None if devices_free else "jarvis voice",
                           "reason": "free" if devices_free else
                                     "the live Jarvis voice runtime holds the microphone"},
            "storage": {"runs": 3, "corrupt": 0, "total_bytes": 4096},
            "active_runs": [], "pending_runs": []}


def passed_run() -> dict:
    spec = self_echo_spec()
    run = queued_run(spec, status=RunStatus.PASSED, started_at=at(200), finished_at=at(1400),
                     metrics={"barge_in.false_count": 0, "speech.ready_to_play_ms": 640.0,
                              "output.stopped": True},
                     assertion_results=(
                         AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, 0),
                         AssertionResult("output_stops", AssertionOutcome.PASSED, True, True),
                         AssertionResult("ready_fast", AssertionOutcome.PASSED, False, 640.0)),
                     score=0.82,
                     artifacts=(ArtifactRef(ArtifactKind.METRICS, "metrics.json", "application/json",
                                            "a" * 64, 412),
                                ArtifactRef(ArtifactKind.WORKER_LOG, "logs/worker.log", "text/plain",
                                            "b" * 64, 20480)))
    return {**run_view(run), "declaration": declaration(), "artifacts": [item.to_dict() for item in run.artifacts]}


def inconclusive_run() -> dict:
    """Le résultat le plus probable de ce laboratoire : une mesure qui n'a pas eu lieu."""
    spec = self_echo_spec()
    run = queued_run(spec, status=RunStatus.ERRORED, started_at=at(200), finished_at=at(9000),
                     metrics={"barge_in.false_count": 0},
                     assertion_results=(
                         AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, 0),
                         AssertionResult("output_stops", AssertionOutcome.MISSING, True, None)),
                     failure=RunFailure("assertions_inconclusive",
                                        "no measurement for blocking assertion(s): output_stops"))
    return {**run_view(run), "declaration": declaration(), "artifacts": []}


def refused_run() -> dict:
    run = queued_run(self_echo_spec(), status=RunStatus.ERRORED, finished_at=at(300),
                     profile=ProfileName.LIVE,
                     failure=RunFailure("permission_denied",
                                        "refused by the resource grant: capability_missing realtime_provider"))
    return {**run_view(run), "declaration": declaration(), "artifacts": []}


def crashed_run() -> dict:
    run = queued_run(self_echo_spec(), status=RunStatus.ERRORED, started_at=at(100), finished_at=at(5000),
                     failure=RunFailure("worker_crashed", "the worker exited with code 3221225477"))
    return {**run_view(run), "declaration": declaration(), "artifacts": []}


def running_run() -> dict:
    run = queued_run(self_echo_spec(), status=RunStatus.RUNNING, started_at=at(200),
                     profile=ProfileName.HARDWARE_GUIDED)
    return {**run_view(run), "declaration": declaration(), "artifacts": []}


def prompt_document(remaining_s: float, *, action: str = "say_phrase", sequence: int = 2) -> dict:
    """La forme de `GET /api/testlab/runs/{id}/prompt` (jarvis/testlab/api.py)."""
    return {"run_id": "TLR-x", "sequence": sequence, "shown_at": 1000.0,
            "elapsed_s": round(30.0 - remaining_s, 3), "remaining_s": remaining_s,
            "prompt": {"prompt_id": "say_hello", "action": action,
                       "text": "Dites la phrase pendant que Jarvis parle.",
                       "deadline_s": 30.0, "phrase": "Jarvis, arrête-toi",
                       "expects_voice": True, "strict_timing": True}}


# ------------------------------------------------------- avant l'exécution

def test_the_catalogue_list_keeps_every_profile_and_filters_on_text(tmp_path):
    rows = run_node(tmp_path, "return {all:L.catalogueRows(D,''),voice:L.catalogueRows(D,'ECHO'),none:L.catalogueRows(D,'zzz')};",
                    [declaration()])
    assert len(rows["all"]) == 1 and rows["all"][0]["diagnostic_id"] == "voice.self_echo"
    assert rows["all"][0]["profiles"] == ["virtual", "live", "hardware:guided"]
    assert len(rows["voice"]) == 1 and rows["none"] == []


@pytest.mark.parametrize("profile", sorted(self_echo_spec().profiles, key=lambda item: item.value))
def test_the_profile_gate_says_exactly_what_the_python_permission_gate_says(tmp_path, profile):
    """`profileGate` rejoue `check_profile_permission`, cas par cas, sans le deviner."""

    spec = self_echo_spec()
    grants = [
        ResourceGrant(frozenset(), 0.0, None),
        ResourceGrant(frozenset({Capability.REALTIME_PROVIDER}), 0.0, None),
        ResourceGrant(frozenset({Capability.REALTIME_PROVIDER}), 5.0, None),
        ResourceGrant(frozenset(Capability), 5.0, None),
        ResourceGrant(frozenset(Capability), 5.0, 60.0),
        ResourceGrant(frozenset(Capability), 5.0, 6000.0),
    ]
    cases = []
    for grant in grants:
        decision = check_profile_permission(spec.profiles[profile], grant)
        cases.append({"profile": profile_document(profile), "status": status_document(grant),
                      "expected": decision.allowed,
                      # L'ORDRE est le contrat : capacités dans l'ordre du vocabulaire,
                      # puis l'argent, puis la durée. Un réordonnancement côté Python
                      # doit faire échouer ce test, pas passer inaperçu.
                      "reasons": [denial.reason.value for denial in decision.denials]})
    answers = run_node(tmp_path, "return D.map(c=>{const g=L.profileGate(c.profile,c.status);"
                                 "return {expected:c.expected,reasons:c.reasons,allowed:g.allowed,"
                                 "codes:g.blockers.map(b=>b.code)}});", cases)
    declared = spec.profiles[profile]
    if declared.requires or declared.cost.max_cost_usd:
        # `virtual` est gratuit et sans ressource : il n'a aucun refus à produire.
        assert any(answer["reasons"] for answer in answers), "aucun refus : le test ne prouverait rien"
        assert any(len(answer["reasons"]) > 1 for answer in answers), "aucun refus multiple : l'ordre ne serait pas testé"
    for answer in answers:
        assert answer["allowed"] == answer["expected"], answer
        assert answer["codes"] == answer["reasons"], answer


def test_a_missing_capability_is_named_where_the_profile_is_chosen_with_the_switch_that_lifts_it(tmp_path):
    case = {"profile": profile_document(ProfileName.LIVE),
            "status": status_document(ResourceGrant(frozenset(), 0.0, None))}
    answer = run_node(tmp_path, "const g=L.profileGate(D.profile,D.status);"
                                "return {allowed:g.allowed,blockers:g.blockers,html:L.profileCardHtml(D.profile,D.status,{})};",
                      case)
    assert answer["allowed"] is False
    codes = [item["code"] for item in answer["blockers"]]
    assert "capability_missing" in codes and "cost_budget_exceeded" in codes
    assert "JARVIS_TESTLAB_LIVE=1" in answer["html"]
    # Le refus est à l'endroit du choix, et la case est réellement inerte.
    assert "non exécutable ici" in answer["html"] and "disabled" in answer["html"]


def test_a_reserved_runner_is_refused_in_the_words_of_the_catalogue(tmp_path):
    case = {"profile": profile_document(ProfileName.VIRTUAL, reserved_profiles=(ProfileName.VIRTUAL,)),
            "status": status_document(ResourceGrant(frozenset(Capability), 5.0, None))}
    answer = run_node(tmp_path, "const g=L.profileGate(D.profile,D.status);"
                                "return {allowed:g.allowed,blockers:g.blockers,"
                                "html:L.profileCardHtml(D.profile,D.status,{})};", case)
    assert answer["allowed"] is False
    blocker = answer["blockers"][0]
    # La phrase du catalogue est CITÉE, pas fondue dans l'intitulé français.
    assert blocker["quote"] == "this implementation name is reserved and has no runner yet"
    assert "n’a pas de fabrique enregistrée" in blocker["detail"]
    assert "tlab-quote" in answer["html"]


def test_busy_devices_warn_without_blocking_because_the_supervisor_probes_again(tmp_path):
    case = {"profile": profile_document(ProfileName.HARDWARE_GUIDED),
            "status": status_document(ResourceGrant(frozenset(Capability), 5.0, None), devices_free=False)}
    answer = run_node(tmp_path, "const g=L.profileGate(D.profile,D.status);"
                                "return {allowed:g.allowed,warnings:g.warnings};", case)
    assert answer["allowed"] is True
    assert answer["warnings"][0]["code"] == "device_contention"
    assert answer["warnings"][0]["quote"] == "the live Jarvis voice runtime holds the microphone"


def test_a_grant_reduced_at_startup_is_repeated_where_a_run_is_chosen(tmp_path):
    case = {"profile": profile_document(ProfileName.VIRTUAL),
            "status": status_document(ResourceGrant(frozenset(), 0.0, None),
                                      refusal="JARVIS_TESTLAB_MAX_COST_USD was unreadable; the budget reads 0")}
    answer = run_node(tmp_path, "return L.profileGate(D.profile,D.status).warnings.map(w=>w.quote);", case)
    assert answer == ["JARVIS_TESTLAB_MAX_COST_USD was unreadable; the budget reads 0"]


def test_parameters_are_typed_from_the_declaration_and_only_changes_are_sent(tmp_path):
    answer = run_node(tmp_path, """
      const specs=D.parameters,by=n=>specs.find(s=>s.name===n);
      return {
        int_ok:L.parameterCoerce(by('turns'),'7'),
        int_bad:L.parameterCoerce(by('turns'),'sept'),
        float_comma:L.parameterCoerce(by('echo.level_db'),'-12,5'),
        bool_on:L.parameterCoerce(by('aec'),false),
        empty:L.parameterCoerce(by('label'),'  '),
        request:L.runRequest(D,'virtual',{turns:'7',label:'baseline',mode:'half'}),
        refused:L.runRequest(D,'virtual',{turns:'sept'}),
      };""", declaration())
    assert answer["int_ok"] == {"ok": True, "value": 7}
    assert answer["int_bad"]["ok"] is False and "entier" in answer["int_bad"]["error"]
    assert answer["float_comma"]["value"] == -12.5
    assert answer["bool_on"] == {"ok": True, "value": False}
    assert answer["empty"]["value"] is None
    # `label` vaut déjà sa valeur par défaut : il ne part pas.
    assert answer["request"]["body"]["parameters"] == {"turns": 7, "mode": "half"}
    assert answer["request"]["body"]["diagnostic_id"] == "voice.self_echo"
    assert answer["refused"]["errors"] and "parameters" not in answer["refused"]["body"]


def test_the_prepare_view_shows_what_will_be_measured_before_anything_runs(tmp_path):
    html = run_node(tmp_path, "return L.metricsHtml({run:{metrics:{}},declaration:D})"
                              "+L.assertionsHtml({run:{assertion_results:[]},declaration:D});", declaration())
    assert "barge_in.false_count" in html and "non mesurée" in html
    assert "no_false_barge_in" in html and "bloquante" in html and "Non évaluée" in html


# ------------------------------------------------------ pendant l'exécution

def test_a_running_run_shows_status_elapsed_and_the_open_guided_step(tmp_path):
    data = {"view": running_run(), "prompt": prompt_document(18.0)}
    answer = run_node(tmp_path, """
      const started=Date.parse(D.view.run.started_at);
      return {queued:L.runProgress({run:{...D.view.run,status:'queued',started_at:null}},started+5000,null),
              running:L.runProgress(D.view,started+12000,null),
              guided:L.runProgress(D.view,started+12000,D.prompt)};""", data)
    assert answer["queued"]["step"] == "en attente d’un worker libre"
    assert answer["queued"]["elapsedText"] == "en file depuis 5.2 s"
    assert answer["running"]["elapsedText"] == "12 s écoulées" and answer["running"]["terminal"] is False
    assert answer["running"]["tone"] == "busy"
    assert answer["guided"]["step"] == "étape guidée say_hello · say_phrase"
    assert answer["guided"]["guided"] is True


def test_a_finished_run_reports_the_exact_recorded_duration(tmp_path):
    answer = run_node(tmp_path, "return L.runProgress(D,Date.now(),null);", passed_run())
    assert answer["terminal"] is True and answer["elapsedText"] == "1.2 s de durée"
    assert answer["outcomeLabel"] == "Réussi" and answer["tone"] == "ok"


def test_the_guided_countdown_comes_from_the_server_and_stops_at_zero_without_disabling_anything(tmp_path):
    answer = run_node(tmp_path, """
      return {fresh:L.promptView(D,0),drifted:L.promptView(D,5000),
              expired:L.promptView({...D,remaining_s:0.4},3000),
              clamped:L.promptView({...D,remaining_s:900},0),
              closed:L.promptView({run_id:'TLR-x',prompt:null},0)};""", prompt_document(18.0))
    assert answer["fresh"]["remaining_s"] == 18.0 and answer["fresh"]["ratio"] == 0.6
    assert answer["drifted"]["remaining_s"] == 13.0
    assert answer["expired"]["remaining_s"] == 0 and answer["expired"]["expired"] is True
    assert "Rien n’a été envoyé" in answer["expired"]["note"]
    # Jamais plus que le délai : l'écran ne promet pas du temps que l'exécution n'attendra pas.
    assert answer["clamped"]["remaining_s"] == 30.0
    assert answer["closed"]["open"] is False


def test_every_guided_action_has_its_own_affordance_and_none_is_invented(tmp_path):
    """`GuidedAction` est fermé : « a UI renders one affordance per action »."""

    from jarvis.testlab.hardware.prompts import GuidedAction

    answer = run_node(tmp_path, "return L.GUIDED_ACTIONS;", None)
    assert set(answer) == {item.value for item in GuidedAction}
    for action, affordance in answer.items():
        assert affordance["label"] and affordance["hint"], action
    view = run_node(tmp_path, "return L.promptView(D,0);", prompt_document(12.0))
    assert view["phrase"] == "Jarvis, arrête-toi" and view["strict_timing"] is True
    assert view["text"] == "Dites la phrase pendant que Jarvis parle."
    assert view["hint"] == answer["say_phrase"]["hint"]


# --------------------------------- l'invariant : jamais d'acquittement seul

def test_nothing_short_of_a_human_click_can_acknowledge_a_guided_step(tmp_path):
    """Sondages répétés, re-rendus, minuteurs et clics scriptés : aucun POST."""

    answer = run_node(tmp_path, """
      const posts=[];
      const gate=L.createPromptGate({post:(path,body)=>{posts.push({path,body});return Promise.resolve({ok:true})}});
      /* 200 sondages de la MÊME invite, comme un long poll qui ne change pas. */
      for(let i=0;i<200;i++)gate.observe('TLR-1',D,i*250);
      /* Un re-rendu, un minuteur, une reconnexion : tous passent par observe(). */
      await new Promise(r=>setTimeout(r,30));
      for(let i=0;i<20;i++)gate.observe('TLR-1',D,0);
      const after_reads=posts.length;
      /* Tout ce qui n'est pas un clic humain est refusé, y compris un clic scripté. */
      const refusals=[];
      refusals.push(await gate.answer('ack',null));
      refusals.push(await gate.answer('ack',{}));
      refusals.push(await gate.answer('ack',{isTrusted:false}));
      refusals.push(await gate.answer('ack',{isTrusted:'true'}));
      refusals.push(await gate.answer('nonsense',{isTrusted:true}));
      const after_fakes=posts.length;
      /* Et sans invite ouverte, même un vrai clic ne poste rien. */
      gate.observe('TLR-1',{run_id:'TLR-1',prompt:null},0);
      const closed=await gate.answer('ack',{isTrusted:true});
      return {after_reads,after_fakes,posts:posts.length,
              reasons:refusals.map(r=>r.reason),closed:closed.reason};""", prompt_document(20.0))
    assert answer["after_reads"] == 0 and answer["after_fakes"] == 0 and answer["posts"] == 0
    assert answer["reasons"] == ["not_a_click", "not_a_click", "not_a_click", "not_a_click", "unknown_answer"]
    assert answer["closed"] == "no_prompt"


def test_one_click_sends_exactly_one_answer_and_a_repeated_prompt_never_sends_a_second(tmp_path):
    answer = run_node(tmp_path, """
      const posts=[];
      const gate=L.createPromptGate({post:(path,body)=>{posts.push({path,body});return Promise.resolve({ok:true})}});
      gate.observe('TLR-1',D,0);
      const first=await gate.answer('ack',{isTrusted:true});
      /* Le serveur renvoie la même invite pendant que le worker la consomme. */
      for(let i=0;i<50;i++)gate.observe('TLR-1',D,0);
      const second=await gate.answer('ack',{isTrusted:true});
      const refuse=await gate.answer('refuse',{isTrusted:true});
      /* L'étape suivante est une AUTRE clé : elle peut, elle, être répondue. */
      gate.observe('TLR-1',{...D,sequence:D.sequence+1},0);
      const next=await gate.answer('refuse',{isTrusted:true});
      return {first,second,refuse,next,posts};""", prompt_document(20.0))
    assert answer["first"]["sent"] is True
    assert answer["second"]["reason"] == "already_answered" and answer["refuse"]["reason"] == "already_answered"
    assert answer["next"]["sent"] is True and answer["next"]["refused"] is True
    assert len(answer["posts"]) == 2
    assert answer["posts"][0]["path"] == f"{TESTLAB_ROUTE}/runs/TLR-1/prompt"
    assert answer["posts"][0]["body"] == {"prompt_id": "say_hello", "sequence": 2, "refused": False}
    assert answer["posts"][1]["body"]["sequence"] == 3


def test_a_failed_send_rearms_the_step_so_the_person_can_try_again(tmp_path):
    answer = run_node(tmp_path, """
      let fail=true;const posts=[];
      const gate=L.createPromptGate({post:(path,body)=>{posts.push(body);
        if(fail){fail=false;return Promise.reject(new Error('HTTP 503'))}return Promise.resolve({ok:true})}});
      gate.observe('TLR-1',D,0);
      let thrown=null;
      try{await gate.answer('ack',{isTrusted:true})}catch(e){thrown=e.message}
      const retry=await gate.answer('ack',{isTrusted:true});
      return {thrown,retry,posts:posts.length};""", prompt_document(20.0))
    assert answer["thrown"] == "HTTP 503"
    assert answer["retry"]["sent"] is True and answer["posts"] == 2


# ------------------------------------------------------- après l'exécution

def test_a_passed_run_shows_the_servers_verdict_its_score_and_its_artifacts(tmp_path):
    html = run_node(tmp_path, "return L.evidenceHtml(D);", passed_run())
    assert "Réussi" in html and "score 0.82" in html
    assert "640 ms" in html and "no_false_barge_in" in html and "Vérifiée" in html
    assert f"{TESTLAB_ROUTE}/runs/" in html and "metrics.json" in html and "20 kio" in html


def test_an_inconclusive_run_says_could_not_measure_in_plain_words(tmp_path):
    document = inconclusive_run()
    assert document["outcome"]["outcome"] == "inconclusive"
    html = run_node(tmp_path, "return L.evidenceHtml(D);", document)
    assert "Non mesurable" in html
    assert "rien n’a pu être mesuré" in html
    # La phrase du worker et son code stable, tels quels.
    assert '<span class="tlab-quote">«&nbsp;no measurement for blocking assertion(s): output_stops&nbsp;»</span>' in html
    assert "Code de panne : assertions_inconclusive" in html
    assert "Assertions bloquantes non mesurées" in html and "output_stops" in html


def test_a_run_with_a_missing_metric_names_it_instead_of_hiding_it(tmp_path):
    html = run_node(tmp_path, "return L.metricsHtml(D);", inconclusive_run())
    assert "output.stopped" in html and "non mesurée" in html
    assert "speech.ready_to_play_ms" in html


def test_a_refused_run_says_the_lab_declined_and_nothing_was_learned(tmp_path):
    document = refused_run()
    assert document["outcome"]["outcome"] == "refused"
    html = run_node(tmp_path, "return L.outcomeHtml(D);", document)
    assert "Refusé" in html and "rien n’a été appris sur le produit" in html
    assert "refused by the resource grant: capability_missing realtime_provider" in html


def test_a_crashed_run_is_read_as_a_defect_of_the_lab_not_of_the_product(tmp_path):
    document = crashed_run()
    assert document["outcome"]["outcome"] == "crashed"
    html = run_node(tmp_path, "return L.outcomeHtml(D);", document)
    assert "Panne du labo" in html and "le Test Lab lui-même a cassé" in html
    assert "the worker exited with code 3221225477" in html


def test_an_outcome_this_screen_does_not_know_never_reads_as_still_running(tmp_path):
    """Même repli alarmant que `outcome_of` : un résultat inexplicable n'est pas « en cours ».

    Un panneau plus vieux que le serveur verrait un jour un résultat qu'il ne
    connaît pas. Le lire « En cours » ferait attendre indéfiniment une exécution
    déjà terminée ; il est donc lu comme inconnu, en ton d'alerte.
    """
    document = crashed_run()
    document["outcome"]["outcome"] = "quantum_tunnelled"
    answer = run_node(tmp_path, """
      return {read:L.readOutcome(D.outcome.outcome),absent:L.readOutcome(undefined),
              empty:L.readOutcome(''),html:L.outcomeHtml(D),
              progress:L.runProgress(D,Date.now(),null)};""", document)
    assert answer["read"]["tone"] == "warn"
    assert answer["read"]["label"] == "Résultat inconnu de cet écran"
    assert answer["absent"]["label"] == "En cours" and answer["empty"]["label"] == "En cours"
    assert "Résultat inconnu de cet écran" in answer["html"]
    assert "En cours" not in answer["html"]
    assert answer["progress"]["tone"] == "warn" and answer["progress"]["terminal"] is True
    # Le code brut reste affiché : c'est par lui qu'on retrouve ce que c'était.
    assert "quantum_tunnelled" in answer["html"]


def test_a_run_whose_declaration_left_the_catalogue_still_reads(tmp_path):
    document = {**inconclusive_run(), "declaration": None}
    html = run_node(tmp_path, "return L.evidenceHtml(D);", document)
    assert "Déclaration absente du catalogue" in html
    assert "Non mesurable" in html


def test_the_evidence_escapes_every_string_the_server_hands_it(tmp_path):
    """Un détail de panne et une description de métrique sont du texte, jamais du balisage."""

    document = inconclusive_run()
    document["run"]["failure"]["detail"] = "<img src=x onerror=alert(1)>"
    document["declaration"]["metrics"][0]["description"] = "<script>alert('x')</script>"
    html = run_node(tmp_path, "return L.evidenceHtml(D);", document)
    assert "<img src=x" not in html and "<script>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;" in html


# ------------------------------------------------------------ comparaison

def test_two_comparable_runs_show_per_metric_deltas_with_their_direction(tmp_path):
    spec = self_echo_spec()
    baseline = queued_run(spec, status=RunStatus.PASSED, started_at=at(200), finished_at=at(1400),
                          metrics={"barge_in.false_count": 0, "speech.ready_to_play_ms": 900.0,
                                   "output.stopped": True},
                          assertion_results=(
                              AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, 0),
                              AssertionResult("output_stops", AssertionOutcome.PASSED, True, True),
                              AssertionResult("ready_fast", AssertionOutcome.FAILED, False, 900.0)))
    candidate = queued_run(spec, status=RunStatus.PASSED, started_at=at(200), finished_at=at(1400),
                           run_id=OTHER_RUN_ID,
                           metrics={"barge_in.false_count": 0, "speech.ready_to_play_ms": 600.0,
                                    "output.stopped": True},
                           assertion_results=(
                               AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, 0),
                               AssertionResult("output_stops", AssertionOutcome.PASSED, True, True),
                               AssertionResult("ready_fast", AssertionOutcome.PASSED, False, 600.0)))
    document = compare_runs(baseline, candidate, metrics=spec).to_dict()
    html = run_node(tmp_path, "return L.comparisonHtml(D);", document)
    assert "Comparables" in html
    assert "900 ms" in html and "600 ms" in html and "-300 ms" in html
    assert "Mieux" in html and "ready_fast" in html and "Corrigée" in html


def test_an_incomparable_pair_says_what_is_incomparable_and_why(tmp_path):
    spec = self_echo_spec()
    baseline = queued_run(spec, status=RunStatus.PASSED, started_at=at(200), finished_at=at(1400),
                          metrics={"barge_in.false_count": 0, "output.stopped": True},
                          assertion_results=(
                              AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, 0),
                              AssertionResult("output_stops", AssertionOutcome.PASSED, True, True)))
    candidate = queued_run(spec, status=RunStatus.RUNNING, started_at=at(200),
                           run_id=OTHER_RUN_ID,
                           profile=ProfileName.LIVE)
    document = compare_runs(baseline, candidate, metrics=spec).to_dict()
    assert document["comparable"] is False
    html = run_node(tmp_path, "return L.comparisonHtml(D);", document)
    assert "Partiellement comparables" in html
    assert "les deux exécutions n’ont pas le même profil" in html
    assert "n’a pas encore de preuve" in html
    # Le détail que le serveur a écrit est cité, pas collé à l'intitulé français.
    for detail in [item["detail"] for item in document["incomparable"] if item["detail"]]:
        assert f'<span class="tlab-quote">«&nbsp;{detail}&nbsp;»</span>' in html


def test_a_sweep_summary_point_renders_with_the_same_comparison_template(tmp_path):
    """Le résumé d'un balayage porte le MÊME document par point : un seul gabarit."""

    spec = self_echo_spec()
    baseline = queued_run(spec, status=RunStatus.PASSED, started_at=at(200), finished_at=at(1400),
                          metrics={"barge_in.false_count": 0, "output.stopped": True},
                          assertion_results=(
                              AssertionResult("no_false_barge_in", AssertionOutcome.PASSED, True, 0),
                              AssertionResult("output_stops", AssertionOutcome.PASSED, True, True)))
    candidate = queued_run(spec, status=RunStatus.FAILED, started_at=at(200), finished_at=at(1400),
                           run_id=OTHER_RUN_ID,
                           metrics={"barge_in.false_count": 2, "output.stopped": True},
                           assertion_results=(
                               AssertionResult("no_false_barge_in", AssertionOutcome.FAILED, True, 2),
                               AssertionResult("output_stops", AssertionOutcome.PASSED, True, True)))
    point = {"index": 1, "label": "turns=5",
             "comparison_to_baseline": compare_runs(baseline, candidate, metrics=spec).to_dict()}
    html = run_node(tmp_path, "return L.comparisonHtml(D.comparison_to_baseline);", point)
    assert "Moins bien" in html and "Régression" in html


# ------------------------------------------------------------ état du labo

def test_the_header_says_what_this_process_may_do_and_whether_devices_are_free(tmp_path):
    data = {"free": status_document(ResourceGrant(frozenset(), 0.0, None)),
            "busy": status_document(ResourceGrant(frozenset(Capability), 2.5, None), devices_free=False)}
    answer = run_node(tmp_path, "return {free:L.statusHtml(D.free),busy:L.statusHtml(D.busy),none:L.statusHtml(null)};",
                      data)
    assert "rien (profil virtual seulement)" in answer["free"] and "gratuit" in answer["free"]
    assert "appareils audio libres" in answer["free"]
    assert "appareils audio occupés" in answer["busy"] and "2.50 USD" in answer["busy"]
    assert "holds the microphone" in answer["busy"]
    assert "indisponible" in answer["none"]


# ------------------------------------------------------------ intégration

def test_the_module_parses_with_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    completed = subprocess.run([node, "--check", str(MODULE)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.asyncio
async def test_the_served_page_carries_the_module_and_the_panel(tmp_path):
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    response = await center.index(None)
    html = response.text
    assert TESTLAB_SCRIPT_MARKER not in html, "le repère n'a pas été remplacé"
    assert "const JarvisTestLabCore=" in html
    assert 'id="openTestLab"' in html and 'id="testlab"' in html
    assert 'aria-controls="testlab"' in html
    # Le bloc navigateur du Test Lab vient APRÈS celui de la chronologie, dont
    # il partage la coquille plein écran.
    assert html.index("const JarvisTimelineCore=") < html.index("const JarvisTestLabCore=")


#: Un DOM minimal : assez pour que le bloc navigateur s'installe, ouvre la vue et
#: rende chaque zone. Il n'analyse pas le HTML produit (les tests ci-dessus le
#: font sur la logique pure) ; il prouve que le branchement TOURNE — un nom
#: d'élément faux ou une variable oubliée s'y voit, pas à l'écran d'une personne.
DOM_STUB = r"""
const written={},listeners={};
function node(id){
  const self={id,hidden:false,inert:false,textContent:'',className:'',isConnected:true,
    style:{},dataset:{},tabIndex:0,offsetParent:{},children:[],
    classList:{add(){},remove(){}},setAttribute(){},getAttribute(){return null},
    focus(){},appendChild(){},remove(){},closest(){return null},
    addEventListener(kind,fn){(listeners[id]=listeners[id]||{})[kind]=fn},
    querySelector(selector){return node(id+selector)},
    querySelectorAll(selector){
      if(selector==='button')return ['prepare','runs','compare'].map(tab=>{
        const b=node(id+'.'+tab);b.dataset={tab};return b});
      return [];
    }};
  Object.defineProperty(self,'innerHTML',{set(value){written[id]=(written[id]||'')+value},
    get(){return written[id]||''}});
  return self;
}
const cache={};
const pick=id=>(cache[id]=cache[id]||node(id));
global.window={fetch:()=>{throw new Error('le panneau doit passer par api()')},
  addEventListener(){},requestAnimationFrame(fn){fn()}};
global.requestAnimationFrame=fn=>fn();
global.document={getElementById:pick,body:{children:[]},activeElement:null,addEventListener(){}};
global.toast=()=>{};
const calls=[];
global.api=async(path,options)=>{
  calls.push({path,method:(options&&options.method)||'GET'});
  if(path.endsWith('/status'))return D.status;
  if(path.endsWith('/diagnostics'))return {diagnostics:[D.declaration]};
  if(path.includes('/diagnostics/'))return {diagnostic:D.declaration};
  if(path.includes('/runs?'))return {runs:[D.view],corrupt:[],next_cursor:null};
  if(path.includes('/compare'))return D.comparison;
  if(path.includes('/prompt'))return D.prompt;
  if(path.includes('/runs/'))return D.view;
  if(path.endsWith('/runs'))return {run_id:'tlr-x'};
  throw new Error('route inattendue '+path);
};
"""


def test_the_browser_block_installs_opens_and_renders_every_zone(tmp_path):
    """Le branchement tourne : ouverture, catalogue, en-tête, onglets, preuve."""

    data = {"status": status_document(ResourceGrant(frozenset(), 0.0, None)),
            "declaration": declaration(), "view": passed_run(),
            "comparison": None, "prompt": {"run_id": "tlr-x", "prompt": None}}
    answer = run_node(tmp_path, DOM_STUB + """
      /* Le bloc navigateur ne s'installe que s'il TROUVE un document : le module
         est rechargé une fois le DOM en place. */
      delete require.cache[require.resolve(MODULE_PATH)];
      require(MODULE_PATH);
      const panel=global.window.JarvisTestLab;
      panel.open();
      for(let i=0;i<40;i++)await tick();
      panel.close();
      return {zones:Object.keys(written).filter(k=>written[k].length>0).sort(),
              calls:calls.map(c=>c.path),selected:panel.state.selected,
              profile:panel.state.profile,open:panel.state.open,
              handle:Object.keys(panel).sort(),gate:typeof panel.gate,
              gateView:panel.gateView(),
              prepare:written['testlab#tlabPane']||''};""", data)
    assert answer["selected"] == "voice.self_echo"
    assert answer["profile"] == "virtual"
    assert answer["open"] is False
    assert "/api/testlab/status" in answer["calls"]
    assert "/api/testlab/diagnostics" in answer["calls"]
    assert any(path.startswith("/api/testlab/diagnostics/") for path in answer["calls"])
    # Chaque zone de l'écran a reçu du contenu : liste, en-tête, corps.
    for zone in ("tlabEnv", "tlabList", "tlabHead", "tlabPane"):
        assert any(key.endswith(zone) or key == zone for key in answer["zones"]), answer["zones"]
    # Et l'onglet « Préparer » a bien rendu les profils, les paramètres et le bouton.
    prepare = answer["prepare"]
    assert "hardware:guided" in prepare and "exécutable ici" in prepare
    assert "echo.level_db" in prepare and "Lancer sur virtual" in prepare
    assert "JARVIS_TESTLAB_LIVE=1" in prepare  # le profil live est refusé, et il le dit
    # Le profil virtual ne coûte rien : la phrase le dit, elle ne dit pas « au plus gratuit ».
    assert "aucun coût en argent" in prepare and "au plus gratuit" not in prepare
    # Le portillon n'est PAS joignable depuis la page : `isTrusted` ne veut rien
    # dire sur un objet fabriqué, donc un `gate.answer('ack',{isTrusted:true})`
    # tapé à la console acquitterait une étape sans personne. Seule sa lecture sort.
    assert answer["gate"] == "undefined"
    assert answer["handle"] == ["close", "gateView", "open", "state"]
    assert set(answer["gateView"]) == {"openKey", "answeredKeys", "busy"}
    assert answer["gateView"] == {"openKey": None, "answeredKeys": [], "busy": False}


def test_every_element_the_browser_block_reaches_for_exists_in_the_page():
    """Un identifiant absent de la page rend la vue muette sans lever d'erreur."""

    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisTestLab(){"):]
    html = PAGE.read_text(encoding="utf-8")
    wanted = set(re.findall(r"q\('#([A-Za-z0-9_]+)'\)", browser))
    wanted |= set(re.findall(r"getElementById\('([A-Za-z0-9_]+)'\)", browser))
    # Ceux que le module crée lui-même dans le HTML qu'il rend.
    built = set(re.findall(r'id="(tlab[A-Za-z0-9_]+)"', source))
    missing = sorted(name for name in wanted - built if f'id="{name}"' not in html)
    assert not missing, missing


@pytest.mark.asyncio
async def test_every_route_the_panel_calls_is_a_route_the_server_registers(tmp_path):
    """L'écran n'appelle aucune adresse inventée : chaque gabarit existe côté serveur."""

    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    registered = set()
    for resource in center._app.router.resources():
        info = resource.get_info()
        path = info.get("path") or info.get("formatter")
        if path:
            registered.add(path)
    source = MODULE.read_text(encoding="utf-8")
    called = set()
    for raw in re.findall(r"\$\{(?:T\.)?ROUTE\}([^`'\"?]*)", source):
        # `${encodeURIComponent(x)}` et consorts deviennent le segment variable du gabarit.
        template = re.sub(r"\$\{[^}]*\}", "{x}", raw).rstrip("/")
        called.add(TESTLAB_ROUTE + template)
    assert len(called) >= 9, sorted(called)
    patterns = {re.sub(r"\{[^}]*\}", "{x}", path) for path in registered}
    # Une adresse appelée est connue soit telle quelle, soit comme préfixe d'un
    # gabarit à segment variable (les artefacts : `.../artifacts/{path:.+}`).
    unknown = sorted(path for path in called
                     if path not in patterns and f"{path}/{{x}}" not in patterns)
    assert not unknown, unknown
    assert "/api/testlab/runs/{x}/prompt" in called and "/api/testlab/compare" in called
