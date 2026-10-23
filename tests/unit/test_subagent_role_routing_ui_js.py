"""Onglet Sous-agents › « Modèles du rôle » (jarvis-architecture-agents-settings-editor, Slice 06).

Le module servi est exécuté par node sur la VRAIE charge utile de `GET /api/subagent-roles` (v2) et sur
l'instantané figé de `GET /api/subagent-role-routing` (`tests/fixtures/subagent_role_routing.json`, produit par le
code de la Slice 03) ; le serveur du § 10 est simulé par `createFixtureAdapter`, le transport HTTP par un `fetch`
factice. Contrat : `docs/subagent-roles.md` § 8 et § 10.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import ControlCenter

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_subagents_settings.js"
ROUTING = ROOT / "jarvis" / "runtime" / "control_center_subagent_routing.js"
FIXTURE = ROOT / "tests" / "fixtures" / "subagent_role_routing.json"


def roles_payload(tmp_path: Path) -> dict:
    return ControlCenter(runtime_root=tmp_path, project_root=tmp_path)._subagent_roles_payload({})


def routing_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def run(tmp_path: Path, source: str, *, roles: dict | None = None, routing: dict | None = None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"roles": roles or roles_payload(tmp_path), "routing": routing or routing_fixture()}), encoding="utf-8")
    script = tmp_path / "t.cjs"
    script.write_text(
        "const errors=[],infos=[];console.error=(c,e,x)=>errors.push([c,e&&e.code||null,x||null]);"
        "console.info=(c,d)=>infos.push([c,d]);\n"
        f"require({json.dumps(str(MODULE))});const M=globalThis.JarvisSubagentSettings;const R=globalThis.JarvisSubagentRouting;\n"
        f"const DATA=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));\n"
        "const host={innerHTML:'',setAttribute(){},querySelectorAll(){return[]},querySelector(){return null}};\n"
        "const calls=[];\n"
        "const reply=async(p,i)=>{calls.push([p,i&&i.method||'GET']);if(p==='/api/subagent-roles')return DATA.roles;"
        "if(p==='/api/agent/tasks')return {tasks:[]};return {mutation:{changed:true},subagent_roles_snapshot:{written:true}}};\n"
        "const quiet={setInterval:()=>null,clearInterval:()=>{}};\n"
        "const open=async(adapter,extra)=>{const v=M.create(host,{fetch:reply,routing:adapter,openTab:()=>{},...quiet,...(extra||{})});await v.load();await v.routeReady();return v};\n"
        "(async()=>{" + source + "})().catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout else None


def role(snapshot: dict, role_id: str) -> dict:
    return next(r for r in snapshot["roles"] if r["role_id"] == role_id)


def test_every_role_shows_its_models_from_the_served_snapshot(tmp_path):
    fixture = routing_fixture()
    out = run(tmp_path, """
const a=R.createFixtureAdapter(DATA.routing);const v=await open(a);
const pages={};for(const r of DATA.roles.roles){v.select(r.id);pages[r.id]=host.innerHTML}
process.stdout.write(JSON.stringify({pages,errors,infos,list:host.innerHTML}));""")
    assert out["errors"] == []
    assert any(name == "subagent_settings.routing_loaded" for name, _ in out["infos"])
    for entry in fixture["roles"]:
        page = out["pages"][entry["role_id"]]
        assert f'data-sar-route="{entry["role_id"]}"' in page
        assert "Modèles du rôle" in page and "Prochain lancement" in page
        for cand in entry["candidates"]:
            assert cand["label"] in page
        if entry["explicit"]:
            assert "Réglé pour ce rôle" in page
        else:
            assert f"Hérité du profil « {entry['inherited_profile']} »" in page
        assert entry["binding_reason"] in page
    qa = out["pages"]["qa"]
    # Indisponibles visibles avec la raison servie ; l'aperçu nomme le candidat retenu et ceux écartés.
    assert "Indisponible : Ce modèle n&#39;est plus proposé par le fournisseur." in qa
    assert "Indisponible : « codex » est introuvable dans le PATH." in qa
    assert "repli dans la liste du rôle" in qa and "Écarté : claude:disparu" in qa
    assert 'data-sar-route-restore="qa"' in qa and 'data-sar-route-restore="qa" disabled' not in qa
    assert 'data-sar-route-restore="coder" disabled' in out["pages"]["coder"]
    # L'alias reste une métadonnée du rôle, pas un second rôle ; l'ancien renvoi vers « Modèles des sous-agents » part.
    assert "[reviewer]" in qa and 'data-sar-role="reviewer"' not in out["list"]
    assert "data-sar-open-models" not in out["list"]
    # La liste projette le candidat préféré de chaque rôle.
    assert len(re.findall(r'class="sar-item-route[ "]', out["list"])) == len(fixture["roles"])


def test_roles_harnesses_and_models_are_never_hard_coded(tmp_path):
    for path in (MODULE, ROUTING):
        source = path.read_text(encoding="utf-8")
        for word in ("grand", "petit", "gpt", "codex", "opus", "sonnet", "haiku", "Claude Code"):
            assert word not in source.lower() if word.islower() else word not in source, (path.name, word)
        for role_id in ("'coder'", "'qa'", "'research'", "'concept'", "'interviewer'"):
            assert role_id not in source, (path.name, role_id)
    # Un rôle et un harness inconnus de la page s'affichent tels que servis.
    roles = roles_payload(tmp_path)
    extra = copy.deepcopy(next(r for r in roles["roles"] if r["id"] == "concept"))
    extra.update(id="cartographe", marker="cartographe", name="Cartographie", aliases=[])
    roles["roles"].append(extra)
    fixture = routing_fixture()
    mapped = copy.deepcopy(role(fixture, "concept"))
    mapped.update(role_id="cartographe", marker="cartographe", name="Cartographie", explicit=True, provenance="explicit",
                  restorable=True, candidates=[{"agent": "zeta", "model": "z1", "position": 0, "label": "Zêta · Z1",
                                                "available": True, "unavailable_reason": "", "selectable": True,
                                                "selectable_reason": ""}])
    fixture["roles"].append(mapped)
    fixture["harnesses"].append({"id": "zeta", "label": "Zêta", "provider": "x", "capabilities": [], "available": True,
                                 "unavailable_reason": "", "models": [{"model": "z1", "label": "Z1", "available": True,
                                                                       "unavailable_reason": ""}]})
    out = run(tmp_path, """
const v=await open(R.createFixtureAdapter(DATA.routing,{hostAgent:'zeta'}));v.select('cartographe');
process.stdout.write(JSON.stringify({html:host.innerHTML,errors}));""", roles=roles, routing=fixture)
    assert 'data-sar-role="cartographe"' in out["html"] and "Zêta · Z1" in out["html"]
    assert '<option value="zeta"' in out["html"] and out["errors"] == []


def test_editing_one_role_writes_only_that_role_and_keeps_the_other_draft(tmp_path):
    out = run(tmp_path, """
const a=R.createFixtureAdapter(DATA.routing);const v=await open(a);
v.select('qa');v.moveCandidate('qa',1,-1);const qaDraft=JSON.parse(JSON.stringify(v.state.routeDrafts.qa));
v.select('coder');v.addCandidate('coder',{agent:'claude',model:'grand'});v.moveCandidate('coder',1,-1);v.setFallback('coder',false);
const before=host.innerHTML;await v.saveRoute('coder');
process.stdout.write(JSON.stringify({calls:a.calls,qaDraft,drafts:v.state.routeDrafts,before,html:host.innerHTML,
  notice:v.state.routeNotice.coder,snap:a.snapshot,errors,unsaved:v.hasUnsaved()}));""")
    puts = [c for c in out["calls"] if c[0] != "load"]
    assert puts == [["put", "coder", {"base_revision": "rr-1", "allow_general_fallback": False,
                                      "candidates": [{"agent": "claude", "model": "grand"}, {"agent": "claude", "model": "petit"}]}]]
    assert "routage non enregistré" in out["before"] and 'data-sar-route-save="coder"' in out["before"]
    assert out["notice"]["tone"] == "ok" and "ce rôle seul" in out["notice"]["text"]
    # Le brouillon de l'autre rôle est intact ; sa politique servie n'a pas bougé.
    assert out["drafts"] == {"qa": out["qaDraft"]} and out["unsaved"] is True
    assert role(out["snap"], "qa") == role(routing_fixture(), "qa")
    coder = role(out["snap"], "coder")
    assert coder["explicit"] is True and [c["model"] for c in coder["candidates"]] == ["grand", "petit"]
    assert "Réglé pour ce rôle" in out["html"] and out["errors"] == []


def test_a_409_rereads_the_policy_and_keeps_the_draft_then_a_second_save_wins(tmp_path):
    out = run(tmp_path, """
const a=R.createFixtureAdapter(DATA.routing);const v=await open(a);
v.select('concept');v.setFallback('concept',false);
await a.put('research',{base_revision:'rr-1',candidates:[{agent:'claude',model:'petit'}],allow_general_fallback:true}); // écrit ailleurs
await v.saveRoute('concept');
const first={notice:v.state.routeNotice.concept,draft:v.state.routeDrafts.concept,revision:v.state.route.snap.revision,
  research:v.state.route.snap.roles.find(r=>r.role_id==='research').explicit,html:host.innerHTML};
await v.saveRoute('concept');
process.stdout.write(JSON.stringify({first,second:v.state.routeNotice.concept,calls:a.calls,errors}));""")
    first = out["first"]
    assert first["notice"]["code"] == "role_routing_revision_stale" and "changé ailleurs" in first["notice"]["text"]
    assert first["draft"] == {"candidates": [{"agent": "claude", "model": "grand"}], "allow_general_fallback": False}
    assert first["revision"] == "rr-2" and first["research"] is True  # l'instantané du refus fait foi
    assert "<code>role_routing_revision_stale</code>" in first["html"]
    assert out["second"]["tone"] == "ok"
    assert [c[2]["base_revision"] for c in out["calls"] if c[0] == "put" and c[1] == "concept"] == ["rr-1", "rr-2"]
    assert ["subagent_settings_routing_save_failed", "role_routing_revision_stale",
            {"role_id": "concept", "code": "role_routing_revision_stale", "status": 409}] in out["errors"]


def test_a_422_shows_the_server_reason_and_keeps_the_list(tmp_path):
    out = run(tmp_path, """
const a=R.createFixtureAdapter(DATA.routing);const v=await open(a);
v.select('research');v.addCandidate('research',{agent:'codex',model:'gpt-o'});v.removeCandidate('research',0);
await v.saveRoute('research');
process.stdout.write(JSON.stringify({notice:v.state.routeNotice.research,draft:v.state.routeDrafts.research,html:host.innerHTML,errors}));""")
    assert out["notice"]["code"] == "role_routing_no_host_candidate"
    assert out["notice"]["text"].startswith("Enregistrement refusé. Refus du serveur : « Le rôle « Recherche documentaire » doit compter")
    assert "Rien n’a été écrit" in out["notice"]["text"]
    assert out["draft"]["candidates"] == [{"agent": "codex", "model": "gpt-o"}]
    assert "Lançable : vérifié par le serveur à l’enregistrement" in out["html"] or "Indisponible" in out["html"]


def test_an_empty_list_cannot_be_saved_and_says_how_to_go_back(tmp_path):
    out = run(tmp_path, """
const v=await open(R.createFixtureAdapter(DATA.routing));v.select('coder');v.removeCandidate('coder',0);
process.stdout.write(JSON.stringify({html:host.innerHTML}));""")
    assert "Liste vide : le serveur la refuserait" in out["html"]
    assert re.search(r'data-sar-route-save="coder" disabled', out["html"])


def test_a_degraded_snapshot_after_a_write_is_said_and_blocks_writes_until_reread(tmp_path):
    out = run(tmp_path, """
const a=R.createFixtureAdapter(DATA.routing);const v=await open(a);
v.select('coder');v.setFallback('coder',false);a.degradeNext();await v.saveRoute('coder');
const html=host.innerHTML,notice=v.state.routeNotice.coder,stale=v.state.route.stale,roles=v.state.route.snap.roles.length;
await v.rereadRouting('coder');
process.stdout.write(JSON.stringify({html,notice,stale,roles,after:v.state.route.stale,afterHtml:host.innerHTML,errors}));""")
    assert out["notice"]["code"] == "role_routing_snapshot_failed" and out["notice"]["reread"] is True
    assert out["notice"]["text"].startswith("Enregistré, mais la relecture de la politique a échoué")
    assert out["roles"] == 7  # l'instantané vide du serveur n'efface pas l'écran
    assert 'data-sar-route-reread="coder"' in out["html"] and 'data-sar-fallback="coder" disabled' in out["html"].replace(" checked", "")
    assert out["after"] is None and "Réglé pour ce rôle" in out["afterHtml"]
    assert "subagent_settings_routing_degraded" in [e[0] for e in out["errors"]]


def test_an_unknown_outcome_forces_a_reread_and_says_what_it_shows(tmp_path):
    out = run(tmp_path, """
const go=async(writes)=>{const a=R.createFixtureAdapter(DATA.routing);const v=await open(a);v.select('coder');v.setFallback('coder',false);
  a.throwNext('subagent_routing_timeout',{writes});await v.saveRoute('coder');
  return {notice:v.state.routeNotice.coder,draft:v.state.routeDrafts.coder||null,loads:a.calls.filter(c=>c[0]==='load').length}};
const written=await go(true),lost=await go(false);
process.stdout.write(JSON.stringify({written,lost}));""")
    for case in (out["written"], out["lost"]):
        assert case["notice"]["text"].startswith("Résultat inconnu : Pas de réponse du Control Center après 15 s.")
        assert case["loads"] == 2 and case["notice"]["code"] == "subagent_routing_timeout"
    assert "bien été enregistrée" in out["written"]["notice"]["hint"] and out["written"]["draft"] is None
    assert "n’a pas été enregistrée" in out["lost"]["notice"]["hint"] and out["lost"]["draft"]["allow_general_fallback"] is False


def test_restore_is_confirmed_by_the_page_and_returns_the_role_to_its_profile(tmp_path):
    out = run(tmp_path, """
const a=R.createFixtureAdapter(DATA.routing);const v=await open(a);v.select('qa');
await v.restoreRoute('qa');
process.stdout.write(JSON.stringify({calls:a.calls,notice:v.state.routeNotice.qa,html:host.innerHTML,errors}));""")
    assert [c for c in out["calls"] if c[0] == "restore"] == [["restore", "qa", {"base_revision": "rr-1"}]]
    assert out["notice"]["tone"] == "ok" and "profil « general »" in out["notice"]["text"]
    assert "Hérité du profil « general »" in out["html"] and 'data-sar-route-restore="qa" disabled' in out["html"]


def test_a_routing_read_failure_leaves_the_role_sheet_and_instructions_usable(tmp_path):
    out = run(tmp_path, """
const a=R.createFixtureAdapter(DATA.routing);a.failNext({on:'load',status:500,code:'role_routing_snapshot_failed',reason:'Lecture impossible (OSError)'});
const v=await open(a);v.select('coder');const html=host.innerHTML;
await v.loadRouting();
process.stdout.write(JSON.stringify({html,after:host.innerHTML,errors}));""")
    assert "Politique des rôles illisible : Lecture impossible (OSError)" in out["html"]
    assert "data-sar-route-retry" in out["html"] and "<code>role_routing_snapshot_failed</code>" in out["html"]
    assert 'data-sar-text="coder"' in out["html"]  # l'éditeur des instructions reste là
    assert out["errors"][0][:2] == ["subagent_settings_routing_failed", "role_routing_snapshot_failed"]
    assert 'data-sar-route="coder"' in out["after"]


def test_a_candidate_that_cannot_launch_subagents_says_why(tmp_path):
    fixture = routing_fixture()
    qa = role(fixture, "qa")
    qa["candidates"][2].update(available=True, unavailable_reason="", selectable=False,
                               selectable_reason="Seul le CLI hôte lance des sous-agents.")
    out = run(tmp_path, """
const v=await open(R.createFixtureAdapter(DATA.routing));v.select('qa');
process.stdout.write(JSON.stringify({html:host.innerHTML}));""", routing=fixture)
    assert "Non lançable comme sous-agent : Seul le CLI hôte lance des sous-agents." in out["html"]


def test_the_overview_is_a_read_only_projection_of_the_same_snapshot(tmp_path):
    out = run(tmp_path, """
const opened=[];const v=await open(R.createFixtureAdapter(DATA.routing),{openTab:t=>opened.push(t)});
v.select('coder');v.moveCandidate('coder',0,1);v.showOverview(true);const html=host.innerHTML;
process.stdout.write(JSON.stringify({html,opened}));""")
    html = out["html"]
    pane = html[html.index('class="sar-detail-pane"'):]
    assert "Vue d’ensemble du routage" in pane and 'aria-pressed="true"' in html
    for entry in routing_fixture()["roles"]:
        assert f'data-sar-route-goto="{entry["role_id"]}"' in pane
    assert "data-sar-cand-op" not in pane and "<select" not in pane and "data-sar-route-save" not in pane
    assert "1. claude:disparu" in pane  # le libellé servi, tel quel and "Repli général activé" in pane
    # Note de compatibilité lue dans le payload, lien vers Avancé ; aucun sélecteur Auto/Dupliqué.
    assert routing_fixture()["compatibility"]["note"].replace("'", "&#39;") in pane
    assert 'data-settings-open="runtime_cli"' in pane


def test_no_brains_tab_personality_or_delegation_mode_selector(tmp_path):
    out = run(tmp_path, """
const v=await open(R.createFixtureAdapter(DATA.routing));const pages=[];
for(const r of DATA.roles.roles){v.select(r.id);pages.push(host.innerHTML)}v.showOverview(true);pages.push(host.innerHTML);
process.stdout.write(JSON.stringify({all:pages.join('')}));""")
    text = out["all"]
    for word in ("Brains", "créativité", "personnalité", "politesse", "humour", "verbosité", "data-delegation-mode"):
        assert word not in text, word
    assert not re.search(r"<select[^>]*(auto|dupli)", text, re.I)


def test_http_adapter_speaks_the_slice_03_contract(tmp_path):
    out = run(tmp_path, """
const seen=[];
const answers=[{status:200,body:DATA.routing},{status:409,body:{ok:false,code:'role_routing_revision_stale',reason:'La politique a changé.',snapshot:DATA.routing}},
  {status:200,body:{ok:true,applies:'live',snapshot:DATA.routing}}];
const fetch=async(p,i)=>{seen.push([p,i.method,i.body?JSON.parse(i.body):null]);const a=answers.shift();
  return {ok:a.status<400,status:a.status,headers:{get:()=>null},text:async()=>JSON.stringify(a.body)}};
const h=R.createHttpAdapter({fetch});
const snap=await h.load();
const refused=await h.put('qa',{base_revision:'rr-1',candidates:[{agent:'claude',model:'petit'}],allow_general_fallback:true});
const restored=await h.restore('qa',{base_revision:'rr-1'});
const t=R.createHttpAdapter({fetch:(p,i)=>new Promise((_,ko)=>i.signal.addEventListener('abort',()=>{const e=new Error('a');e.name='AbortError';ko(e)})),timeoutMs:30});
let code=null;try{await t.load()}catch(e){code=e.code}
const u=R.createHttpAdapter({fetch:async()=>{throw new Error('ECONNREFUSED')}});
let down=null;try{await u.put('qa',{})}catch(e){down=e.code}
process.stdout.write(JSON.stringify({seen,rev:snap.revision,refused:{...refused,snapshot:!!refused.snapshot},restored:{ok:restored.ok,applies:restored.applies},code,down}));""")
    assert out["seen"] == [
        ["/api/subagent-role-routing", "GET", None],
        ["/api/subagent-role-routing/qa", "PUT", {"base_revision": "rr-1", "candidates": [{"agent": "claude", "model": "petit"}],
                                                  "allow_general_fallback": True}],
        ["/api/subagent-role-routing/qa?base_revision=rr-1", "DELETE", None],
    ]
    assert out["rev"] == "rr-1"
    assert out["refused"] == {"ok": False, "status": 409, "code": "role_routing_revision_stale", "reason": "La politique a changé.", "snapshot": True}
    assert out["restored"] == {"ok": True, "applies": "live"}
    assert out["code"] == "subagent_routing_timeout" and out["down"] == "subagent_routing_unreachable"


def test_without_a_routing_adapter_the_view_is_unchanged(tmp_path):
    out = run(tmp_path, """
const v=M.create(host,{fetch:reply,openTab:()=>{},...quiet});await v.load();
process.stdout.write(JSON.stringify({html:host.innerHTML,phase:v.state.route.phase}));""")
    assert out["phase"] == "off" and "data-sar-open-models" in out["html"]
    assert "Modèles du rôle" not in out["html"] and "data-sar-overview" not in out["html"]


def test_changing_harness_then_adding_picks_the_first_available_model(tmp_path):
    """QA S06 (B1) : changer de harness pose `{agent, model:null}` ; l'ajout doit rester possible."""
    out = run(tmp_path, """
const v=await open(R.createFixtureAdapter(DATA.routing));v.select('coder');
v.state.routeAdd.coder={agent:'codex',model:null};v.render();const codex=host.innerHTML;
v.state.routeAdd.coder={agent:'claude',model:null};v.render();const html=host.innerHTML,sel={...v.state.routeAdd.coder};
const added=v.addCandidate('coder',null);
process.stdout.write(JSON.stringify({codex,html,sel,added,draft:v.state.routeDrafts.coder,errors}));""")
    assert out["sel"] == {"agent": "claude", "model": ""}  # « Modèle par défaut du CLI », premier disponible
    assert 'data-sar-add-model="coder" disabled' not in out["html"] and 'data-sar-add="coder" disabled' not in out["html"]
    assert out["added"] is True and out["draft"]["candidates"] == [{"agent": "claude", "model": "petit"}, {"agent": "claude", "model": ""}]
    # Harness sans modèle disponible : l'option fictive ne collisionne pas avec la valeur "" du défaut du CLI.
    assert '<option value="__none__" selected disabled>Aucun modèle disponible à ajouter</option>' in out["codex"]
    assert out["codex"].count('<option value=""') == 1 and out["errors"] == []


def test_a_models_section_render_error_stays_local_to_the_section(tmp_path):
    out = run(tmp_path, """
const v=await open(R.createFixtureAdapter(DATA.routing));
Object.defineProperty(v.state.route.snap.roles.find(r=>r.role_id==='coder'),'fallback',{get(){throw new Error('piège')}});
v.select('coder');
process.stdout.write(JSON.stringify({phase:v.state.phase,html:host.innerHTML,errors}));""")
    assert out["phase"] == "ready"
    assert "Cette section n’a pas pu afficher la politique servie : piège" in out["html"]
    assert 'data-sar-text="coder"' in out["html"]  # l'éditeur d'instructions reste
    assert "subagent_settings_routing_render_failed" in [e[0] for e in out["errors"]]
