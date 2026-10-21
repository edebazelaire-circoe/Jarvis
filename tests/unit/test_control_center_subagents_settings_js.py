"""Onglet Réglages « Sous-agents » (jarvis-organic-agent-orchestration, Slice 10).

Le module servi est exécuté par node sur la VRAIE charge utile de `GET /api/subagent-roles` (v2) ; seules les
réponses réseau sont simulées. Contrat : `docs/subagent-roles.md` § 8.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.domain import subagent_roles
from jarvis.runtime.control_center import ControlCenter

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_subagents_settings.js"
HTML = ROOT / "jarvis" / "runtime" / "control_center.html"


def roles_payload(tmp_path: Path, settings: dict | None = None) -> dict:
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    return center._subagent_roles_payload(settings or {})


def run_node(tmp_path: Path, payload: dict, source: str, tasks: dict | None = None, candidates: dict | None = None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "roles.json"
    data.write_text(json.dumps({"roles": payload, "tasks": tasks or {"tasks": []},
                                "candidates": candidates or {"candidates": [], "thresholds": {}}}), encoding="utf-8")
    script = tmp_path / "t.cjs"
    script.write_text(
        "const errors=[],infos=[];console.error=(c,e,x)=>errors.push([c,e&&e.code||null,x||null]);"
        "console.info=(c,d)=>infos.push([c,d]);\n"
        f"require({json.dumps(str(MODULE))});const M=globalThis.JarvisSubagentSettings;\n"
        f"const DATA=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));\n"
        "const host={innerHTML:'',setAttribute(){},querySelectorAll(){return[]},querySelector(){return null}};\n"
        "const calls=[];\n"
        "const reply=async(p,i)=>{calls.push([p,i&&i.method||'GET',i&&i.body?JSON.parse(i.body):null]);"
        "if(p==='/api/subagent-roles')return DATA.roles;if(p==='/api/agent/tasks')return DATA.tasks;"
        "if(p==='/api/work-methods/candidates')return DATA.candidates;"
        "return {mutation:{changed:true},subagent_roles_snapshot:{written:true}}};\n"
        "const quiet={setInterval:()=>null,clearInterval:()=>{}};\n"
        "(async()=>{" + source + "})().catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout else None


def test_every_role_shows_icon_badge_accent_token_and_honest_read_only(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();
const pages={};for(const r of DATA.roles.roles){v.select(r.id);pages[r.id]=host.innerHTML}
process.stdout.write(JSON.stringify({pages,errors,infos}));""")
    assert out["errors"] == []
    assert out["infos"][0][0] == "subagent_settings.loaded"
    for role in subagent_roles.ROLES:
        page = out["pages"][role.id]
        assert f'data-sar-role="{role.id}"' in page
        assert f"--sar-accent:var(--role-accent-{role.visual.accent})" in page
        assert f'<span class="sar-badge">{role.visual.badge}</span>' in page
        assert '<svg class="sar-glyph"' in page
        assert "Capacités" in page and "lecture seule" in page
        # La méthode non éditable est annoncée APRÈS les instructions éditables.
        assert page.index("Vos instructions") < page.index("Work Method par défaut")
        if role.default_work_method:
            assert "s’ajoute <strong>après</strong> vos instructions" in page
        assert f'data-sar-text="{role.id}"' in page
    lead = out["pages"]["research-lead"]
    # Slice 07 : tous les rôles sont proposés au cerveau ; l'avis ne vient que d'un drapeau faux (test suivant).
    assert "pas encore proposé au cerveau" not in lead and "deep-research@1" in lead
    assert "délégation" in lead  # libellé de relation servi par la route, jamais recopié
    assert "[reviewer]" in out["pages"]["qa"] and "alias historique" in out["pages"]["qa"]


def test_a_role_not_offered_to_the_brain_says_so(tmp_path):
    payload = roles_payload(tmp_path)
    for role in payload["roles"]:
        if role["id"] == "qa":
            role["offered_to_brain"] = False
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();v.select('qa');
process.stdout.write(JSON.stringify({page:host.innerHTML,errors}));""")
    assert out["errors"] == [] and "pas encore proposé au cerveau" in out["page"]


def test_accents_are_tokens_mapped_once_to_theme_variables():
    source = MODULE.read_text(encoding="utf-8")
    page = HTML.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source), "aucune couleur dans le module : des jetons seulement"
    for token in subagent_roles.ROLE_ACCENTS:
        assert f"--role-accent-{token}:" in page, token
    # Pictogrammes : la table partagée avec le graphe des tâches (Slice 09), jamais une copie dans l'onglet.
    shared = (MODULE.parent / "control_center_role_identity.js").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", shared), "aucune couleur dans la table partagée"
    for role in subagent_roles.ROLES:
        assert f"{role.visual.icon}:" in shared or f"'{role.visual.icon}':" in shared, role.visual.icon


def test_save_posts_the_canonical_prompt_edit_with_both_revisions(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const drafts={};const v=M.create(host,{fetch:reply,drafts,...quiet});await v.load();
v.select('coder');v.state.drafts.coder='Nouvelles instructions';await v.save('coder');
process.stdout.write(JSON.stringify({calls,drafts,notice:v.state.notice.coder,html:host.innerHTML,errors}));""")
    coder = next(r for r in payload["roles"] if r["id"] == "coder")
    post = [c for c in out["calls"] if c[1] == "POST"]
    assert post == [["/api/prompts/subagent_role.coder", "POST", {
        "action": "edit", "text": "Nouvelles instructions",
        "base_revision": coder["default_revision"], "expected_effective_revision": coder["revision"],
    }]]
    assert out["calls"][-1][0] == "/api/subagent-roles"  # relu après l'écriture
    assert out["drafts"] == {} and out["notice"]["tone"] == "ok" and out["errors"] == []


def test_revision_conflict_keeps_the_text_rereads_and_says_so(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const fetchFn=async(p,i)=>{if(i&&i.method==='POST'){calls.push([p,'POST']);const e=new Error('Prompt override changed; refresh before saving');e.code='prompt_override_concurrent';e.status=400;throw e}return reply(p,i)};
const v=M.create(host,{fetch:fetchFn,...quiet});await v.load();
v.select('concept');v.state.drafts.concept='Mon texte';await v.save('concept');
process.stdout.write(JSON.stringify({calls,draft:v.state.drafts.concept,notice:v.state.notice.concept,html:host.innerHTML,errors,busy:v.state.save}));""")
    assert out["draft"] == "Mon texte" and out["busy"] is None
    assert out["notice"]["code"] == "prompt_override_concurrent" and "modifiées ailleurs" in out["notice"]["text"]
    assert "prompt_override_concurrent" in out["html"] and "data-sar-notice" in out["html"]
    assert [c[0] for c in out["calls"]].count("/api/subagent-roles") == 2
    assert ["subagent_settings_save_failed", "prompt_override_concurrent", {"role_id": "concept", "code": "prompt_override_concurrent"}] in out["errors"]


def test_refused_save_shows_the_server_words_and_unsent_snapshot_is_flagged(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
let n=0;
const fetchFn=async(p,i)=>{if(i&&i.method==='POST'){n++;if(n===1){const e=new Error('Prompt text too large');e.code='agent_settings_behavior_prompt_too_large';throw e}
  return {mutation:{changed:true},subagent_roles_snapshot:{written:false,code:'subagent_roles_snapshot_write_failed',error:'OSError: disque plein'}}}return reply(p,i)};
const v=M.create(host,{fetch:fetchFn,...quiet});await v.load();
v.state.drafts.research='x';await v.save('research');const refused=v.state.notice.research;
await v.save('research');
process.stdout.write(JSON.stringify({refused,snapshot:v.state.notice.research,errors}));""")
    assert out["refused"]["text"] == "Enregistrement refusé. Refus du serveur : « Prompt text too large ». Rien n’a été écrit."
    assert out["refused"]["code"] == "agent_settings_behavior_prompt_too_large"
    assert out["snapshot"]["tone"] == "bad" and out["snapshot"]["code"] == "subagent_roles_snapshot_write_failed"


def test_load_failure_is_visible_logged_and_retryable(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const bad=async()=>{const e=new Error('Settings must be an object');e.code='prompt_settings_invalid';throw e};
const v=M.create(host,{fetch:bad,...quiet});await v.load();
process.stdout.write(JSON.stringify({html:host.innerHTML,errors,phase:v.state.phase}));""")
    assert out["phase"] == "error"
    assert "Registre des rôles illisible" in out["html"] and "prompt_settings_invalid" in out["html"]
    assert "data-sar-retry" in out["html"] and 'role="alert"' in out["html"]
    assert out["errors"][0][:2] == ["subagent_settings_load_failed", "prompt_settings_invalid"]


def test_timeout_has_a_deadline_and_names_it(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
globalThis.fetch=(p,i)=>new Promise((_,reject)=>i.signal.addEventListener('abort',()=>{const e=new Error('aborted');e.name='AbortError';reject(e)}));
const v=M.create(host,{timeoutMs:50,...quiet});await v.load();
process.stdout.write(JSON.stringify({html:host.innerHTML,code:v.state.error.code}));""")
    assert out["code"] == "subagent_settings_timeout" and "Pas de réponse du Control Center après" in out["html"]


def test_loading_state_shows_motion_label_and_live_counter(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
let t=1000;let started=0;
const v=M.create(host,{fetch:()=>new Promise(()=>{}),now:()=>t,setInterval:()=>{started++;return 1},clearInterval:()=>{}});v.load();
t=4200;v.render();
process.stdout.write(JSON.stringify({html:host.innerHTML,started}));""")
    assert "Lecture du registre des rôles…" in out["html"] and "sar-spin" in out["html"]
    assert ">3 s<" in out["html"] and "abandon après 15 s" in out["html"] and out["started"] == 1


def test_empty_registry_and_disabled_role_are_explicit(tmp_path):
    payload = roles_payload(tmp_path)
    empty = {**payload, "roles": []}
    out = run_node(tmp_path, empty, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();process.stdout.write(JSON.stringify({html:host.innerHTML}));""")
    assert "Aucun rôle dans le registre" in out["html"]

    disabled = json.loads(json.dumps(payload))
    disabled["roles"][3]["enabled"] = False
    out = run_node(tmp_path, disabled, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();v.select(DATA.roles.roles[3].id);
process.stdout.write(JSON.stringify({html:host.innerHTML}));""")
    assert "<strong>Rôle désactivé.</strong>" in out["html"], out["html"][-3000:]
    assert re.search(r'class="sar-item[^"]* off"', out["html"])


def test_unknown_accent_token_falls_back_visibly_and_is_logged_once(tmp_path):
    payload = json.loads(json.dumps(roles_payload(tmp_path)))
    payload["roles"][0]["visual"]["accent"] = "magenta"
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();v.render();
process.stdout.write(JSON.stringify({html:host.innerHTML,errors}));""")
    assert "--role-accent-magenta" not in out["html"]
    assert [e[0] for e in out["errors"]].count("subagent_settings_unknown_accent") == 1


def test_instances_resolve_declared_alias_unknown_and_undeclared(tmp_path):
    payload = roles_payload(tmp_path)
    tasks = {"tasks": [
        {"status": "running", "kind": "agent", "role": "coder", "description": "[code] [coder] Corriger"},
        {"status": "running", "kind": "agent", "role": "reviewer", "description": "[code] [reviewer] Relire"},
        {"status": "running", "kind": "agent", "role": "zorg", "description": "[code] [zorg] Explorer"},
        {"status": "running", "kind": "agent", "role": None, "description": "Liste", "ephemeral": True},
        {"status": "completed", "kind": "agent", "role": "coder", "description": "Fini"},
    ]}
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();
const r=m=>v.resolveMarker(m).status;
process.stdout.write(JSON.stringify({html:host.innerHTML,st:[r('coder'),r('reviewer'),r('zorg'),r(null)],qa:v.resolveMarker('reviewer').role.id}));""",
        tasks)
    assert out["st"] == ["declared", "alias", "unknown", "undeclared"] and out["qa"] == "qa"
    html = out["html"]
    assert "via l'alias <code>[reviewer]</code>" in html and "Marqueur hors registre <code>[zorg]</code>" in html
    assert "aucun rôle déclaré" in html and "éphémère" in html and "Fini" not in html


def test_instances_failure_does_not_hide_the_roles(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const fetchFn=async(p,i)=>{if(p==='/api/agent/tasks'){const e=new Error('HTTP 503');e.code='';throw e}return reply(p,i)};
const v=M.create(host,{fetch:fetchFn,...quiet});await v.load();await new Promise(r=>setTimeout(r,0));
process.stdout.write(JSON.stringify({html:host.innerHTML,errors}));""")
    assert "Instances illisibles : HTTP 503" in out["html"] and 'data-sar-role="coder"' in out["html"]
    assert out["errors"][0][0] == "subagent_settings_tasks_failed"


def test_destroyed_view_ignores_a_late_answer(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
let release;const slow=()=>new Promise(r=>{release=()=>r(DATA.roles)});
const v=M.create(host,{fetch:slow,...quiet});const p=v.load();host.innerHTML='other tab';v.destroy();release();await p;
process.stdout.write(JSON.stringify({html:host.innerHTML,errors}));""")
    assert out["html"] == "other tab" and out["errors"] == []


def test_served_page_carries_the_tab_and_the_module(tmp_path):
    served = asyncio.run(ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert "{id:'subagents',label:'Sous-agents',save:false}" in served
    assert "root.JarvisSubagentSettings=Object.freeze" in served
    assert "/*__CONTROL_CENTER_SUBAGENTS_SETTINGS_JS__*/" not in served
    assert 'content=\'<div id="subagentSettingsMount"></div>\'' in served


def test_route_serves_relation_labels_additively(tmp_path):
    payload = roles_payload(tmp_path)
    assert payload["schema_version"] == 2
    assert payload["relation_labels"]["delegation"] == "délégation"
    used = {k for m in payload["work_methods"] for k in m["useful_relations"]}
    assert used <= set(payload["relation_labels"])


def test_route_serves_the_instructions_bound_shown_by_the_counter(tmp_path):
    from jarvis.domain.prompt_registry import MAX_OVERRIDE_TEXT

    payload = roles_payload(tmp_path)
    assert payload["instructions_max_chars"] == MAX_OVERRIDE_TEXT
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();v.select('concept');
const before=host.innerHTML;v.state.drafts.concept='x'.repeat(DATA.roles.instructions_max_chars+1);v.render();
process.stdout.write(JSON.stringify({before,after:host.innerHTML}));""")
    assert re.search(r"\(\d[\d ]* / 8 192 caractères\)", out["before"])
    assert "au-delà de la limite" in out["after"]
    assert re.search(r'data-sar-save="concept" disabled', out["after"])


# --- N1 : l'écriture et la relecture sont deux étapes ---------------------------------------------------

def test_post_succeeds_then_reread_fails_says_saved_and_offers_retry(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
let n=0;
const fetchFn=async(p,i)=>{if(p==='/api/subagent-roles'&&++n>1){const e=new Error('Control Center injoignable : boom');e.code='subagent_settings_unreachable';throw e}return reply(p,i)};
const v=M.create(host,{fetch:fetchFn,...quiet});await v.load();
v.select('concept');v.state.drafts.concept='nouveau texte';await v.save('concept');
const notice=v.state.notice.concept,html=host.innerHTML,draft=v.state.drafts.concept;
n=0;await v.reread('concept');
process.stdout.write(JSON.stringify({notice,html,draft,after:v.state.notice.concept,errors}));""")
    notice = out["notice"]
    assert notice["text"].startswith("Enregistré ; la relecture a échoué : « Control Center injoignable : boom »")
    assert "Rien n" not in notice["text"] and notice["reread"] is True
    assert 'data-sar-reread="concept"' in out["html"] and out.get("draft") is None
    assert out["after"]["tone"] == "ok" and out["after"]["text"] == "Version enregistrée relue."
    assert "subagent_settings_refresh_failed" in [e[0] for e in out["errors"]]


def test_post_timeout_is_an_unknown_outcome_followed_by_a_reread(tmp_path):
    payload = roles_payload(tmp_path)
    saved = json.loads(json.dumps(payload))
    next(r for r in saved["roles"] if r["id"] == "concept")["instructions"] = "nouveau texte"
    out = run_node(tmp_path, payload, """
const saved=JSON.parse(process.env.SAVED);let reads=0;
const timeout=()=>{const e=new Error('Pas de réponse du Control Center après 15 s.');e.code='subagent_settings_timeout';throw e};
const run=async(answer)=>{
  reads=0;const v=M.create(host,{fetch:async(p,i)=>{if(i&&i.method==='POST')timeout();if(p==='/api/subagent-roles'){reads++;return reads>1?answer:DATA.roles}return reply(p,i)},...quiet});
  await v.load();v.select('concept');v.state.drafts.concept='nouveau texte';await v.save('concept');
  return {notice:v.state.notice.concept,reads,draft:v.state.drafts.concept??null};
};
const written=await run(saved),lost=await run(DATA.roles);
process.stdout.write(JSON.stringify({written,lost}));""".replace("process.env.SAVED", json.dumps(json.dumps(saved))))
    for case in (out["written"], out["lost"]):
        assert case["notice"]["text"] == "Résultat inconnu : Pas de réponse du Control Center après 15 s. Relisez avant de réenregistrer."
        assert case["reads"] == 2 and case["notice"]["code"] == "subagent_settings_timeout"
    assert "bien été enregistrée" in out["written"]["notice"]["hint"] and out["written"]["draft"] is None
    assert "n’a pas été enregistrée" in out["lost"]["notice"]["hint"] and out["lost"]["draft"] == "nouveau texte"


# --- N2 : une charge utile partielle ne fige jamais l'écran -------------------------------------------

def test_minimal_unknown_version_payload_renders_with_empty_fields_and_a_warning(tmp_path):
    out = run_node(tmp_path, {"schema_version": 3, "roles": [{"id": "x"}, {"name": "sans id"}]}, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();
process.stdout.write(JSON.stringify({phase:v.state.phase,html:host.innerHTML,errors}));""")
    assert out["phase"] == "ready"
    html = out["html"]
    assert "Version du registre inattendue (<code>3</code>, cet écran lit la version 2)" in html
    assert "1 entrée(s) sans identifiant ignorée(s)" in html and 'data-sar-role="x"' in html
    assert "Fiche incomplète" in html and "<code>instructions</code>" in html
    assert "Révisions absentes de la réponse" in html and 'data-sar-save="x" disabled' in html


def test_role_without_instructions_still_renders(tmp_path):
    payload = json.loads(json.dumps(roles_payload(tmp_path)))
    del payload["roles"][0]["instructions"]
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();
process.stdout.write(JSON.stringify({phase:v.state.phase,html:host.innerHTML}));""")
    assert out["phase"] == "ready" and "sar-detail" in out["html"]


def test_a_rendering_exception_becomes_a_coded_error_with_retry(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const data=DATA.roles;Object.defineProperty(data.roles[0],'mission',{get(){throw new Error('champ piégé')},enumerable:true});
const v=M.create(host,{fetch:async p=>p==='/api/subagent-roles'?data:reply(p),...quiet});await v.load();
process.stdout.write(JSON.stringify({phase:v.state.phase,html:host.innerHTML,errors,code:v.state.error&&v.state.error.code}));""")
    # Le getter piégé lève dès la normalisation : la lecture échoue, codée, avec Réessayer.
    assert out["phase"] == "error" and "data-sar-retry" in out["html"]
    assert out["errors"][0][0] in {"subagent_settings_load_failed", "subagent_settings_render_failed"}

    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();
v.state.payload.roles[0].tools={map(){throw new Error('piège')},length:1};v.render();
process.stdout.write(JSON.stringify({phase:v.state.phase,html:host.innerHTML,errors,code:v.state.error.code}));""")
    assert out["phase"] == "error" and out["code"] == "subagent_settings_render_failed"
    assert "data-sar-retry" in out["html"] and "L’écran n’a pas pu afficher cette réponse" in out["html"]
    assert ["subagent_settings_render_failed", None, {"schema_version": 2}] in out["errors"]


def test_load_error_advice_matches_the_real_cause(tmp_path):
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const fail=code=>async()=>{const e=new Error('Expected versioned prompt overrides');e.code=code;throw e};
const a=M.create(host,{fetch:fail('prompt_override_schema_invalid'),...quiet});await a.load();const schema=host.innerHTML;
const b=M.create(host,{fetch:fail('subagent_settings_unreachable'),...quiet});await b.load();
process.stdout.write(JSON.stringify({schema,net:host.innerHTML}));""")
    assert "Réponse : « Expected versioned prompt overrides »." in out["schema"]
    assert "document des surcharges de prompts" in out["schema"] and "Control Center répond" not in out["schema"]
    assert "Vérifiez que le Control Center répond" in out["net"]


# --- N3 : un alias reste un alias ---------------------------------------------------------------------

def test_alias_to_a_role_missing_from_the_list_resolves_alias_and_prototype_keys_do_not(tmp_path):
    payload = json.loads(json.dumps(roles_payload(tmp_path)))
    payload["aliases"] = {"old": "ghost", "reviewer": "qa"}
    tasks = {"tasks": [{"status": "running", "kind": "agent", "role": "old", "description": "[old] Vieux"}]}
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();
const r=m=>{const x=v.resolveMarker(m);return [x.status,x.roleId,x.role&&x.role.id||null]};
process.stdout.write(JSON.stringify({old:r('old'),ctor:r('constructor'),proto:r('__proto__'),html:host.innerHTML}));""", tasks)
    assert out["old"] == ["alias", "ghost", None]
    assert out["ctor"][0] == "unknown" and out["proto"][0] == "unknown"
    assert "Alias <code>[old]</code> du rôle <code>ghost</code>" in out["html"]


def test_served_page_hides_the_empty_footer_scrolls_the_active_tab_and_links_models(tmp_path):
    served = asyncio.run(ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    # Shell à six catégories (Slice 02 de jarvis-settings-ui-reorganization) : même pied caché pour Sous-agents,
    # même défilement de l'entrée active dans les deux barres.
    assert "footer.hidden=entry?entry.save!=='footer':(!SET.tab||SET.tab==='subagents')" in served
    assert "on.scrollIntoView({block:'nearest',inline:'nearest'})" in served
    assert "openTab:selectTab" in served and "subagent_settings_mount_failed" in served
    payload = roles_payload(tmp_path)
    out = run_node(tmp_path, payload, """
const opened=[];const v=M.create(host,{fetch:reply,openTab:t=>opened.push(t),...quiet});await v.load();
process.stdout.write(JSON.stringify({html:host.innerHTML}));""")
    assert "data-sar-open-cli" in out["html"] and "Agent / CLI › Sous-agents / Modèles" in out["html"]
    assert 'aria-live' not in out["html"]  # la fiche n'est plus une région live


# --- Slice 12 : approches observées et promotion explicite --------------------------------------------

def _candidates() -> dict:
    """La forme servie par `GET /api/work-methods/candidates` (une candidate, une en observation)."""

    draft = {"method_id": "deep-research", "version": 2, "name": "Recherche approfondie", "summary": "Résumé.",
             "role_ids": ["research-lead"], "principles": ["Un principe."], "quality_checks": [],
             "useful_relations": ["delegation", "adversary", "qa"]}
    return {"thresholds": {"min_uses": 3, "min_positive": 2, "min_positive_share": 0.75, "scan_root_missions": 64},
            "candidates": [
                {"candidate_id": "wmc-aaaaaaaaaaaaaaaa", "role_id": "research-lead", "method_id": "deep-research",
                 "relation_kinds": ["delegation", "adversary", "qa"], "status": "candidate", "reason": "thresholds_met",
                 "uses": 3, "positive": 3, "negative": 0, "unrated": 0, "evidence_refs": ["m1", "rq1"],
                 "base_method_key": "deep-research@1", "draft": draft, "promoted_keys": []},
                {"candidate_id": "wmc-bbbbbbbbbbbbbbbb", "role_id": "research-lead", "method_id": "quick-research",
                 "relation_kinds": [], "status": "observing", "reason": "not_enough_quality_evidence",
                 "uses": 4, "positive": 0, "negative": 0, "unrated": 4, "evidence_refs": [],
                 "base_method_key": "quick-research@1", "draft": None, "promoted_keys": []},
            ]}


def test_observed_approaches_are_shown_for_mission_owner_roles_only(tmp_path):
    out = run_node(tmp_path, roles_payload(tmp_path), """
const v=M.create(host,{fetch:reply,...quiet});await v.load();
v.select('research-lead');const lead=host.innerHTML;v.select('research');const research=host.innerHTML;
process.stdout.write(JSON.stringify({lead,research,errors,infos}));""", candidates=_candidates())
    assert out["errors"] == []
    assert "Approches observées" in out["lead"] and "Approches observées" not in out["research"]
    assert 'data-sar-promote="wmc-aaaaaaaaaaaaaaaa"' in out["lead"] and "Promouvoir en deep-research@2" in out["lead"]
    # Pas de bouton sans seuils atteints ; la raison réelle est dite, le silence n'est pas une approbation.
    assert 'data-sar-promote="wmc-bbbbbbbbbbbbbbbb"' not in out["lead"]
    assert "une mission terminée sans verdict QA ne compte pas" in out["lead"]
    assert "Rien n’est promu sans vous" in out["lead"]
    assert any(name == "subagent_settings.candidates_loaded" for name, _ in out["infos"])


def test_a_promotion_is_confirmed_then_posts_the_draft_with_its_revision(tmp_path):
    out = run_node(tmp_path, roles_payload(tmp_path), """
const v=M.create(host,{fetch:reply,...quiet});await v.load();await v.loadCandidates();v.select('research-lead');
v.state.confirmPromote='wmc-aaaaaaaaaaaaaaaa';v.render();const confirming=host.innerHTML;
await v.promote('wmc-aaaaaaaaaaaaaaaa');
process.stdout.write(JSON.stringify({confirming,calls,notice:v.state.promoteNotice,html:host.innerHTML,errors,
  promote:v.state.promote}));""", candidates=_candidates())
    assert "Confirmer la promotion" in out["confirming"] and "<code>deep-research@1</code> reste" in out["confirming"]
    # N5 : la confirmation montre ce qui sera publié, principes et relations compris.
    assert "Principes publiés" in out["confirming"] and "<li>Un principe.</li>" in out["confirming"]
    assert "Relations à envisager publiées" in out["confirming"]
    post = [c for c in out["calls"] if c[1] == "POST"]
    assert post == [["/api/work-methods/promotions", "POST", {
        "candidate_id": "wmc-aaaaaaaaaaaaaaaa", "expected_version": 1, "method": _candidates()["candidates"][0]["draft"]}]]
    assert "promoted_by" not in post[0][2]  # forcé par le serveur, jamais envoyé par la page
    assert out["calls"][-1][0] == "/api/work-methods/candidates"  # relu après l'écriture
    assert out["notice"]["tone"] == "ok" and "deep-research@2" in out["notice"]["text"]
    assert "prochain sous-agent" in out["notice"]["hint"]
    assert out["promote"] is None and out["errors"] == []


def test_a_refused_promotion_shows_the_server_words_and_rereads(tmp_path):
    out = run_node(tmp_path, roles_payload(tmp_path), """
const failing=async(p,i)=>{if(i&&i.method==='POST'){const e=new Error('deep-research is now at version 2, not 1');e.code='work_method_revision_conflict';e.status=409;throw e}return reply(p,i)};
const v=M.create(host,{fetch:failing,...quiet});await v.load();await v.loadCandidates();v.select('research-lead');
await v.promote('wmc-aaaaaaaaaaaaaaaa');
process.stdout.write(JSON.stringify({notice:v.state.promoteNotice,html:host.innerHTML,errors,calls,
  learned:v.state.learned.phase}));""", candidates=_candidates())
    assert out["notice"]["tone"] == "bad" and out["notice"]["code"] == "work_method_revision_conflict"
    assert "deep-research is now at version 2, not 1" in out["notice"]["text"]
    assert "elles sont relues" in out["notice"]["hint"] and out["learned"] == "ready"
    assert "<code>work_method_revision_conflict</code>" in out["html"]
    assert out["errors"][0][0] == "subagent_settings_promotion_failed"


def test_an_unknown_outcome_rereads_and_says_how_to_tell(tmp_path):
    out = run_node(tmp_path, roles_payload(tmp_path), """
const failing=async(p,i)=>{if(i&&i.method==='POST'){const e=new Error('Pas de réponse du Control Center après 15 s.');e.code='subagent_settings_timeout';throw e}return reply(p,i)};
const v=M.create(host,{fetch:failing,...quiet});await v.load();await v.loadCandidates();v.select('research-lead');
await v.promote('wmc-aaaaaaaaaaaaaaaa');
process.stdout.write(JSON.stringify({notice:v.state.promoteNotice}));""", candidates=_candidates())
    assert out["notice"]["text"].startswith("Résultat inconnu")
    assert "« Promue »" in out["notice"]["hint"]


def test_unreadable_candidates_say_so_with_a_retry_and_leave_the_rest_usable(tmp_path):
    out = run_node(tmp_path, roles_payload(tmp_path), """
const failing=async(p,i)=>{if(p==='/api/work-methods/candidates'){const e=new Error('Core injoignable : ConnectionRefusedError');e.code='core_unreachable';e.status=503;throw e}return reply(p,i)};
const v=M.create(host,{fetch:failing,...quiet});await v.load();v.select('research-lead');
process.stdout.write(JSON.stringify({html:host.innerHTML,errors}));""")
    assert "Approches observées illisibles : Core injoignable" in out["html"]
    assert "data-sar-learned-retry" in out["html"] and "<code>core_unreachable</code>" in out["html"]
    assert 'data-sar-text="research-lead"' in out["html"]  # l'éditeur reste là
    assert out["errors"] == [["subagent_settings_candidates_failed", "core_unreachable",
                              {"path": "/api/work-methods/candidates"}]]


def test_a_stale_candidate_is_never_a_silent_button(tmp_path):
    out = run_node(tmp_path, roles_payload(tmp_path), """
const v=M.create(host,{fetch:reply,...quiet});await v.load();await v.loadCandidates();v.select('research-lead');
await v.promote('wmc-bbbbbbbbbbbbbbbb');
process.stdout.write(JSON.stringify({notice:v.state.promoteNotice,calls,errors}));""", candidates=_candidates())
    assert out["notice"]["code"] == "subagent_settings_candidate_stale" and "Rien n’a été écrit" in out["notice"]["text"]
    assert not [c for c in out["calls"] if c[1] == "POST"]
    assert out["errors"][0][0] == "subagent_settings_promotion_failed"


def test_a_promotion_not_yet_handed_to_the_hook_is_said(tmp_path):
    out = run_node(tmp_path, roles_payload(tmp_path), """
const answering=async(p,i)=>{if(i&&i.method==='POST')return {ok:true,method:{method_id:'deep-research',version:2},snapshot:{written:false,code:'PermissionError'}};return reply(p,i)};
const v=M.create(host,{fetch:answering,...quiet});await v.load();await v.loadCandidates();v.select('research-lead');
await v.promote('wmc-aaaaaaaaaaaaaaaa');
process.stdout.write(JSON.stringify({notice:v.state.promoteNotice}));""", candidates=_candidates())
    assert out["notice"]["tone"] == "bad" and out["notice"]["code"] == "PermissionError"
    assert "pas encore transmise aux sous-agents" in out["notice"]["text"]


def test_the_effective_promoted_version_is_marked_and_a_partial_reading_is_said(tmp_path):
    payload = json.loads(json.dumps(roles_payload(tmp_path)))
    for method in payload["work_methods"]:
        if method["method_id"] == "deep-research":
            method["version"] = 2
            method["provenance"] = {"origin": "promoted", "candidate_id": "wmc-aaaaaaaaaaaaaaaa",
                                    "promoted_by": "user", "promoted_at": "2026-10-20T10:00:00+00:00",
                                    "evidence_refs": ["m1"]}
    candidates = {**_candidates(), "scan": {"partial": True}}
    out = run_node(tmp_path, payload, """
const v=M.create(host,{fetch:reply,...quiet});await v.load();await v.loadCandidates();v.select('research-lead');
process.stdout.write(JSON.stringify({html:host.innerHTML}));""", candidates=candidates)
    assert "deep-research@2" in out["html"] and "version promue" in out["html"]
    assert "Lecture partielle" in out["html"]
