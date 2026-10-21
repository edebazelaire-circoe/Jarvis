"""Registre canonique des Réglages (jarvis-settings-ui-reorganization, Slice 01), exécuté par node.

Contrat : `docs/settings/navigation-registry.md`. Ce fichier épingle :

- exactement six catégories, dans l'ordre canonique, figées (aucune septième possible) ;
- refus déterministes (code stable) : section en double, catégorie inconnue, section invalide, alias en conflit ;
- chaque identifiant d'onglet actuel (base + injectés) a une destination déclarée, et aucun nouveau module
  n'injecte d'onglet de premier niveau sans passer par cette table ;
- l'adaptateur du shell actuel (`canonicalSettingsTab`, `openSettingsTab`) résout onglets, redirections,
  catégories et sections cibles sans changer l'onglet affiché pour un identifiant actuel ;
- le module n'écrit aucun réglage (ni réseau ni stockage) et la page servie l'insère avant `TABS`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    ControlCenter,
    SETTINGS_REGISTRY_SCRIPT_FILE,
    SETTINGS_REGISTRY_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / SETTINGS_REGISTRY_SCRIPT_FILE
HTML = RUNTIME / "control_center.html"

CATEGORIES = [
    ("voice_audio", "Voix & audio"),
    ("agents_models", "Agents & modèles"),
    ("memory_knowledge", "Mémoire & connaissances"),
    ("interface_interactions", "Interface & interactions"),
    ("connections", "Connexions"),
    ("advanced_diagnostics", "Avancé & diagnostic"),
]
ALIASES = {
    "voice": ("voice_audio", "conversation"),
    "wakeword": ("voice_audio", "wake_word"),
    "prompts": ("advanced_diagnostics", "prompts"),
    "cli": ("agents_models", "main_agent"),
    "routing": ("advanced_diagnostics", "runtime_cli"),
    "keys": ("connections", "providers"),
    "shortcuts": ("interface_interactions", "shortcuts"),
    "memory": ("memory_knowledge", "recall"),
    "subagents": ("agents_models", "subagents"),
    "appearance": ("interface_interactions", "theme_scene"),
    "experimental": ("advanced_diagnostics", "labs"),
}
#: Modules qui injectent encore un onglet de premier niveau (`TABS.push/splice`), retirés par la Slice 09.
LEGACY_INJECTORS = {"control_center_wake_word.js", "control_center_work.js", "control_center_barehands.js"}


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "registry.cjs"
    script.write_text(
        f"const R=require({json.dumps(str(MODULE))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const codeOf=f=>{try{f();return null}catch(e){return [e.code,e.message]}};\n"
        "const noop=()=>{};\n" + body,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def base_tab_ids() -> list[str]:
    page = HTML.read_text(encoding="utf-8")
    block = page[page.index("\nconst TABS=[") : page.index("\nconst SET=")]
    return re.findall(r"\{id:'(\w+)'", block)


def injected_tab_ids() -> list[str]:
    ids = []
    for name in ("control_center_wake_word.js", "control_center_barehands.js", "control_center_scene_settings.js"):
        ids += re.findall(r"const TAB_ID='(\w+)'", (RUNTIME / name).read_text(encoding="utf-8"))
    ids += re.findall(r"TABS\.splice\([^;]*\{id:'(\w+)'", (RUNTIME / "control_center_work.js").read_text(encoding="utf-8"))
    return ids


def assembled_tabs() -> list[dict]:
    """L'ordre réel du shell : base, `wakeword` après `voice`, `appearance` en fin (pas de `config`), puis `experimental`."""
    ids = base_tab_ids()
    ids.insert(ids.index("voice") + 1, "wakeword")
    ids += ["appearance", "experimental"]
    assert set(ids) == set(base_tab_ids()) | set(injected_tab_ids())
    return [{"id": i, "label": i} for i in ids]


def test_exactly_six_frozen_categories_in_canonical_order(tmp_path):
    out = run(tmp_path, """
const before=R.CATEGORIES.length;
try{R.CATEGORIES.push({id:'seventh',label:'7'})}catch(e){}
try{R.CATEGORIES[0].label='x'}catch(e){}
try{R.CATEGORY_IDS.push('seventh')}catch(e){}
const reg=R.createRegistry();
out({cats:R.CATEGORIES.map(c=>[c.id,c.label]),ids:R.CATEGORY_IDS,before,after:R.CATEGORIES.length,
  frozen:Object.isFrozen(R.CATEGORIES)&&R.CATEGORIES.every(Object.isFrozen)&&Object.isFrozen(R)&&Object.isFrozen(reg),
  api:Object.keys(reg).sort(),seventh:codeOf(()=>reg.register({id:'x',category:'seventh',label:'X',mount:noop,save:'self'})),
  regCats:reg.categories().length,pageIsRegistry:typeof R.page.register==='function'});""")
    assert [tuple(c) for c in out["cats"]] == CATEGORIES
    assert out["ids"] == [c[0] for c in CATEGORIES]
    assert out["before"] == out["after"] == 6 and out["regCats"] == 6
    assert out["frozen"] is True and out["pageIsRegistry"] is True
    # Aucune porte vers une catégorie : un registre n'enregistre que des sections.
    assert out["api"] == ["categories", "register", "resolve", "section", "sections", "snapshot"]
    assert out["seventh"][0] == "settings_category_unknown"


def test_sections_register_into_a_category_and_keep_their_order(tmp_path):
    out = run(tmp_path, """
const reg=R.createRegistry();
reg.register({id:'wake_word',category:'voice_audio',label:'Mot d’éveil',order:50,mount:noop,destroy:noop,save:'self',applies:'next_voice_start',aliases:['wakeword']});
reg.register({id:'conversation',category:'voice_audio',label:'Conversation',order:10,mount:noop,save:'footer',isDirty:()=>false});
reg.register({id:'labs',category:'advanced_diagnostics',label:'Labs',group:'labs',advanced:true,mount:noop,save:'readonly'});
out({voice:reg.sections('voice_audio').map(s=>s.id),snap:reg.snapshot(),
  frozen:Object.isFrozen(reg.section('wake_word')),
  resolve:['voice_audio','conversation','wakeword','voice','labs','experimental','barehandsSettings','nope',42].map(t=>[t,reg.resolve(t)]),
  unknownCat:codeOf(()=>reg.sections('seventh'))});""")
    assert out["voice"] == ["conversation", "wake_word"]
    assert [c["id"] for c in out["snap"]] == [c[0] for c in CATEGORIES]
    assert out["snap"][5]["sections"] == [{"id": "labs", "label": "Labs", "group": "labs", "order": 0, "save": "readonly", "advanced": True}]
    assert out["frozen"] is True
    resolved = dict((t if isinstance(t, str) else str(t), r) for t, r in out["resolve"])
    assert resolved["voice_audio"] == {"category": "voice_audio", "section": None, "source": "category"}
    assert resolved["conversation"] == {"category": "voice_audio", "section": "conversation", "source": "section"}
    assert resolved["wakeword"] == {"category": "voice_audio", "section": "wake_word", "source": "section_alias"}
    assert resolved["voice"] == {"category": "voice_audio", "section": "conversation", "source": "legacy_tab"}
    assert resolved["experimental"] == {"category": "advanced_diagnostics", "section": "labs", "source": "legacy_tab"}
    # Section cible pas encore enregistrée : la catégorie seule, jamais une section devinée.
    assert resolved["barehandsSettings"] == {"category": "interface_interactions", "section": None, "source": "legacy_anchor"}
    assert resolved["nope"] is None and resolved["42"] is None
    assert out["unknownCat"][0] == "settings_category_unknown"


def test_invalid_duplicate_and_conflicting_registrations_fail_deterministically(tmp_path):
    out = run(tmp_path, """
const ok={id:'shortcuts',category:'interface_interactions',label:'Raccourcis',mount:noop,save:'self'};
const cases={
  duplicate:[ok,ok],
  unknown_category:[{...ok,category:'labs'}],
  missing_category:[{...ok,category:undefined}],
  category_as_section:[{...ok,id:'connections'}],
  bad_id:[{...ok,id:'Raccourcis clavier'}],
  unknown_key:[{...ok,tab:'shortcuts'}],
  no_mount:[{...ok,mount:undefined}],
  bad_save:[{...ok,save:true}],
  readonly_dirty:[{...ok,save:'readonly',isDirty:()=>true}],
  bad_applies:[{...ok,applies:'later'}],
  not_object:[null],
  alias_to_category:[{...ok,aliases:['voice_audio']}],
  alias_taken:[ok,{id:'other',category:'interface_interactions',label:'O',mount:noop,save:'self',aliases:['shortcuts']}],
  alias_twice:[{...ok,aliases:['old']},{id:'other',category:'interface_interactions',label:'O',mount:noop,save:'self',aliases:['old']}],
  legacy_alias_elsewhere:[{...ok,aliases:['keys']}],
  id_is_alias:[{...ok,aliases:['other']},{id:'other',category:'interface_interactions',label:'O',mount:noop,save:'self'}],
};
const result={};
for(const [name,specs] of Object.entries(cases)){
  const attempt=()=>{const reg=R.createRegistry();let last=null;for(const s of specs)last=codeOf(()=>reg.register(s));return [last,reg.snapshot().flatMap(c=>c.sections.map(s=>s.id))]};
  result[name]={first:attempt(),second:attempt()};
}
out(result);""")
    expected = {
        "duplicate": "settings_section_duplicate",
        "unknown_category": "settings_category_unknown",
        "missing_category": "settings_category_unknown",
        "category_as_section": "settings_section_invalid",
        "bad_id": "settings_section_invalid",
        "unknown_key": "settings_section_invalid",
        "no_mount": "settings_section_invalid",
        "bad_save": "settings_section_invalid",
        "readonly_dirty": "settings_section_invalid",
        "bad_applies": "settings_section_invalid",
        "not_object": "settings_section_invalid",
        "alias_to_category": "settings_alias_conflict",
        "alias_taken": "settings_alias_conflict",
        "alias_twice": "settings_alias_conflict",
        "legacy_alias_elsewhere": "settings_alias_conflict",
        "id_is_alias": "settings_section_duplicate",
    }
    for name, code in expected.items():
        first, second = out[name]["first"], out[name]["second"]
        assert first[0] is not None and first[0][0] == code, (name, first)
        assert first == second, name  # même code, même message, même état du registre
    # Un refus n'enregistre rien : seule la première section valide reste.
    assert out["duplicate"]["first"][1] == ["shortcuts"]
    assert out["unknown_category"]["first"][1] == []


def test_every_current_tab_id_has_a_declared_destination(tmp_path):
    out = run(tmp_path, "out({aliases:R.LEGACY_TAB_ALIASES,ids:R.CATEGORY_IDS,anchors:R.LEGACY_ANCHORS});")
    assert {k: (v["category"], v["section"]) for k, v in out["aliases"].items()} == ALIASES
    for alias in out["aliases"].values():
        assert alias["category"] in out["ids"]
        assert all(d["category"] in out["ids"] for d in alias["also"])
    current = {t["id"] for t in assembled_tabs()}
    assert current <= set(out["aliases"]), current - set(out["aliases"])
    # `experimental` est partagé par Bare Hands et la scène : ses deux destinations sont déclarées.
    assert {"category": "interface_interactions", "section": "bare_hands"} in out["aliases"]["experimental"]["also"]
    barehands = (RUNTIME / "control_center_barehands.js").read_text(encoding="utf-8")
    section_block = barehands[barehands.index("const SECTION=Object.freeze({") :]
    section_block = section_block[: section_block.index("});")]
    assert set(re.findall(r":'(barehands\w+)'", section_block)) == set(out["anchors"])


def test_no_module_injects_a_new_top_level_tab():
    injectors = {p.name for p in RUNTIME.glob("control_center*.js")
                 if re.search(r"TABS\.(push|splice|unshift)\(", p.read_text(encoding="utf-8"))}
    assert injectors == LEGACY_INJECTORS, "un module ajoute un onglet de premier niveau : enregistrer une section dans le registre"


def test_migration_adapter_maps_targets_to_current_tabs(tmp_path):
    tabs = assembled_tabs()
    out = run(tmp_path, f"""
const T={json.dumps(tabs)};
const targets=['voice','wakeword','cli','routing','keys','memory','experimental','voice_audio','agents_models','memory_knowledge',
  'interface_interactions','connections','advanced_diagnostics','wake_word','runtime_cli','labs','bare_hands','theme_scene','diagnostics',
  'barehandsRecord','nope',null];
out({{map:targets.map(t=>[String(t),R.legacyTabFor(t,T)]),nav:R.navigationFromLegacyTabs(T),
  stray:R.navigationFromLegacyTabs([...T,{{id:'seventh',label:'7'}}]).unassigned,
  cycle:[R.cycleCategory('voice_audio',1),R.cycleCategory('voice_audio',-1),R.cycleCategory('advanced_diagnostics',1),R.cycleCategory('nope',1),R.cycleCategory('nope',-1)]}});""")
    mapped = dict(out["map"])
    for tab in tabs:  # un identifiant actuel reste exactement son onglet
        assert mapped.get(tab["id"], tab["id"]) == tab["id"]
    assert mapped == {
        "voice": "voice", "wakeword": "wakeword", "cli": "cli", "routing": "cli", "keys": "keys", "memory": "memory",
        "experimental": "experimental", "voice_audio": "voice", "agents_models": "cli", "memory_knowledge": "memory",
        "interface_interactions": "shortcuts", "connections": "keys", "advanced_diagnostics": "prompts",
        "wake_word": "wakeword", "runtime_cli": "cli", "labs": "experimental", "bare_hands": "experimental",
        "theme_scene": "appearance", "diagnostics": "voice", "barehandsRecord": "experimental", "nope": None, "null": None,
    }
    nav = out["nav"]
    assert nav["unassigned"] == []
    assert [c["id"] for c in nav["categories"]] == [c[0] for c in CATEGORIES]
    assert {c["id"]: [t["id"] for t in c["tabs"]] for c in nav["categories"]} == {
        "voice_audio": ["voice", "wakeword"],
        "agents_models": ["cli", "subagents"],
        "memory_knowledge": ["memory"],
        "interface_interactions": ["shortcuts", "appearance"],
        "connections": ["keys"],
        "advanced_diagnostics": ["prompts", "experimental"],
    }
    assert out["stray"] == ["seventh"]
    assert out["cycle"] == ["agents_models", "advanced_diagnostics", "voice_audio", "voice_audio", "advanced_diagnostics"]


def test_page_adapter_keeps_current_tabs_and_resolves_new_targets(tmp_path):
    page = HTML.read_text(encoding="utf-8")
    canonical = page[page.index("function canonicalSettingsTab") : page.index("function selectTab")]
    door = page[page.index("function openSettingsTab(tab){") : page.index("function closeSettings(){")]
    out = run(tmp_path, f"""
globalThis.window=globalThis;window.JarvisSettingsRegistry=R;
const TABS={json.dumps(assembled_tabs())};
const SET={{open:false,tab:'voice'}},warn=[],errors=[],selected=[];
console.warn=(c,x)=>warn.push([c,x]);console.error=(c,x)=>errors.push([c,x]);
let opened=0;const openSettings=()=>{{opened++;SET.open=true;return Promise.resolve()}};
const selectTab=id=>{{selected.push(canonicalSettingsTab(id));SET.tab=canonicalSettingsTab(id)}};
{canonical}
{door}
(async()=>{{
  await openSettingsTab('connections');const first=SET.tab;
  await openSettingsTab('memory');await openSettingsTab('routing');await openSettingsTab('labs');await openSettingsTab('nope');
  out({{first,opened,selected,tab:SET.tab,warn,nav:settingsNavigation(),errors,
    tabs:settingsTabs().map(t=>t.id),same:TABS.every(t=>canonicalSettingsTab(t.id)===t.id)}});
}})();""")
    assert out["first"] == "keys" and out["opened"] == 1
    assert out["selected"] == ["memory", "cli", "experimental"]
    assert out["tab"] == "experimental"  # une cible inconnue ne change pas d'onglet…
    assert out["warn"] == [["settings_target_unknown", {"target": "nope"}]]  # … mais se dit
    assert out["same"] is True
    assert out["tabs"] == [t["id"] for t in assembled_tabs()]  # la roue voit les mêmes onglets qu'avant
    assert out["nav"]["unassigned"] == [] and out["errors"] == []


def test_module_writes_no_setting_and_is_served_before_the_tabs():
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("fetch(", "localStorage", "sessionStorage", "XMLHttpRequest", "api(", "document.", "indexedDB"):
        assert forbidden not in source, forbidden
    page = HTML.read_text(encoding="utf-8")
    assert page.count(SETTINGS_REGISTRY_SCRIPT_MARKER) == 1
    assert page.index(SETTINGS_REGISTRY_SCRIPT_MARKER) < page.index("\nconst TABS=[")


async def test_served_page_inlines_the_registry(tmp_path: Path):
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert SETTINGS_REGISTRY_SCRIPT_MARKER not in served
    assert "root.JarvisSettingsRegistry=api" in served
    assert served.index("root.JarvisSettingsRegistry=api") < served.index("\nconst TABS=[")
