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


def run_node(tmp_path: Path, payload: dict, source: str, tasks: dict | None = None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "roles.json"
    data.write_text(json.dumps({"roles": payload, "tasks": tasks or {"tasks": []}}), encoding="utf-8")
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
    assert "pas encore proposé au cerveau" in lead and "deep-research@1" in lead
    assert "délégation" in lead  # libellé de relation servi par la route, jamais recopié
    assert "[reviewer]" in out["pages"]["qa"] and "alias historique" in out["pages"]["qa"]


def test_accents_are_tokens_mapped_once_to_theme_variables():
    source = MODULE.read_text(encoding="utf-8")
    page = HTML.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source), "aucune couleur dans le module : des jetons seulement"
    for token in subagent_roles.ROLE_ACCENTS:
        assert f"--role-accent-{token}:" in page, token
    for role in subagent_roles.ROLES:
        assert role.visual.icon in source, role.visual.icon


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
    assert "prompt_override_concurrent" in out["html"] and 'role="alert"' in out["html"]
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
    assert "Prompt text too large" in out["refused"]["text"] and "Rien n’a été écrit" in out["refused"]["text"]
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
