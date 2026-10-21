"""Registre canonique des Réglages (jarvis-settings-ui-reorganization, Slice 01), exécuté par node.

Contrat : `docs/settings/navigation-registry.md`. Ce fichier épingle :

- exactement six catégories, dans l'ordre canonique, figées (aucune septième possible) ;
- refus déterministes (code stable) : section en double, catégorie inconnue, section invalide, alias en conflit ;
- chaque identifiant d'onglet actuel (base + injectés) a une destination déclarée, et aucun nouveau module
  n'injecte d'onglet de premier niveau sans passer par cette table ;
- l'adaptateur des onglets hérités (`canonicalSettingsTab`) garde chaque identifiant actuel sur son onglet, et
  chaque section cible prévue s'ouvre (QA Slice 01) ;
- le shell à six catégories (Slice 02) route catégories, sections, alias et anciens identifiants (`openSettingsTab`,
  `selectTab`), rend les six catégories à la roue (`settingsTabs`) et laisse une section enregistrée remplacer
  l'onglet hérité qu'elle déclare en alias ;
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
# `control_center_wake_word.js` en est sorti (Slice 03) : il enregistre la section `wake_word`.
LEGACY_INJECTORS = {"control_center_work.js", "control_center_barehands.js"}


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
    """L'ordre réel du shell : base, `appearance` en fin (pas de `config`), puis `experimental`. Depuis la Slice 03, ni
    `voice` ni `wakeword` ne sont des onglets : Voix & audio n'a que des sections enregistrées."""
    ids = base_tab_ids()
    ids += ["appearance", "experimental"]
    assert set(ids) == set(base_tab_ids()) | set(injected_tab_ids())
    assert "voice" not in ids and "wakeword" not in ids
    return [{"id": i, "label": i} for i in ids]


def legacy_voice_tabs() -> list[dict]:
    """Fixture historique de l'adaptateur (avant la Slice 03) : `voice` et `wakeword` encore onglets. L'adaptateur reste
    en place pour les onglets que les Slices 04 à 08 n'ont pas encore rehébergés : sa règle est testée sur ce cas."""
    return [{"id": "voice", "label": "voice"}, {"id": "wakeword", "label": "wakeword"}, *assembled_tabs()]


#: Sections enregistrées par la page servie depuis la Slice 03 (`control_center.html`, `control_center_wake_word.js`).
SLICE_03_SECTIONS = (
    ("conversation", "voice_audio", 10, "footer"), ("voice_output", "voice_audio", 20, "footer"),
    ("microphone_sound", "voice_audio", 30, "footer"), ("turns_interruptions", "voice_audio", 40, "footer"),
    ("wake_word", "voice_audio", 50, "self"), ("architecture_compat", "advanced_diagnostics", 10, "footer"),
    ("diagnostics", "advanced_diagnostics", 40, "readonly"),
)
#: Sections enregistrées par la page servie depuis la Slice 04 (`control_center.html` : `AGENT_SECTIONS`,
#: `SUBAGENT_SECTIONS`) ; les onglets `cli` et `subagents` ont disparu.
SLICE_04_SECTIONS = (
    ("main_agent", "agents_models", 10, "footer", ["cli"]), ("agent_behavior", "agents_models", 20, "footer", []),
    ("subagent_models", "agents_models", 30, "footer", []), ("subagents", "agents_models", 40, "self", []),
    ("runtime_cli", "advanced_diagnostics", 30, "footer", ["routing"]), ("work_methods", "advanced_diagnostics", 50, "self", []),
)
REGISTER_SLICE_03 = "".join(
    f"R.page.register({{id:'{i}',category:'{c}',label:'{i}',order:{o},save:'{v}',mount:noop}});" for i, c, o, v in SLICE_03_SECTIONS
) + "".join(
    f"R.page.register({{id:'{i}',category:'{c}',label:'{i}',order:{o},save:'{v}',aliases:{json.dumps(a)},mount:noop}});"
    for i, c, o, v, a in SLICE_04_SECTIONS
)


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
    # Voix & audio n'a plus d'onglet (Slice 03) : ses cibles sont des sections enregistrées, servies par le shell.
    assert mapped == {
        "voice": None, "wakeword": None, "cli": None, "routing": None, "keys": "keys", "memory": "memory",
        "experimental": "experimental", "voice_audio": None, "agents_models": None, "memory_knowledge": "memory",
        "interface_interactions": "shortcuts", "connections": "keys", "advanced_diagnostics": "prompts",
        "wake_word": None, "runtime_cli": None, "labs": "experimental", "bare_hands": "experimental",
        "theme_scene": "appearance", "diagnostics": "memory", "barehandsRecord": "experimental", "nope": None, "null": None,
    }
    nav = out["nav"]
    assert nav["unassigned"] == []
    assert [c["id"] for c in nav["categories"]] == [c[0] for c in CATEGORIES]
    assert {c["id"]: [t["id"] for t in c["tabs"]] for c in nav["categories"]} == {
        "voice_audio": [],
        "agents_models": [],
        "memory_knowledge": ["memory"],
        "interface_interactions": ["shortcuts", "appearance"],
        "connections": ["keys"],
        "advanced_diagnostics": ["prompts", "experimental"],
    }
    assert out["stray"] == ["seventh"]
    assert out["cycle"] == ["agents_models", "advanced_diagnostics", "voice_audio", "voice_audio", "advanced_diagnostics"]


#: Sections cibles prévues (`docs/settings/navigation-registry.md` § 3), enregistrées par les Slices 03 à 08.
PLANNED_SECTIONS = {
    "voice_audio": ["conversation", "voice_output", "microphone_sound", "turns_interruptions", "wake_word"],
    "agents_models": ["main_agent", "agent_behavior", "subagent_models", "subagents"],
    "memory_knowledge": ["recall", "semantic_retrieval", "consolidation", "knowledge_sources", "memory_center"],
    "interface_interactions": ["theme_scene", "shortcuts", "bare_hands"],
    "connections": ["providers"],
    "advanced_diagnostics": ["architecture_compat", "prompts", "runtime_cli", "diagnostics", "work_methods", "labs"],
}


def test_every_planned_target_section_is_served_by_a_current_tab(tmp_path):
    """QA Slice 01 : `voice_output`, `semantic_retrieval`… rendaient `null` ; chaque section cible prévue s'ouvre :
    par un onglet hérité, ou (depuis la Slice 03) parce qu'elle est enregistrée par la page."""
    registered = {i for i, *_ in SLICE_03_SECTIONS} | {i for i, *_ in SLICE_04_SECTIONS}
    out = run(tmp_path, f"""
const T={json.dumps(assembled_tabs())},P={json.dumps(PLANNED_SECTIONS)};
out(Object.fromEntries(Object.values(P).flat().map(s=>[s,R.legacyTabFor(s,T)])));""")
    assert all(v for k, v in out.items() if k not in registered), {k: v for k, v in out.items() if not v}
    assert registered <= {s for sections in PLANNED_SECTIONS.values() for s in sections}
    # Les sections Voix ne sont plus servies par un onglet (`diagnostics` l'est encore par Mémoire, en partie).
    assert {k: out[k] for k in ("conversation", "voice_output", "microphone_sound", "turns_interruptions", "wake_word",
                                "architecture_compat")} == dict.fromkeys(
        ("conversation", "voice_output", "microphone_sound", "turns_interruptions", "wake_word", "architecture_compat"), None)
    assert {k: out[k] for k in ("semantic_retrieval", "consolidation", "knowledge_sources")} == dict.fromkeys(
        ("semantic_retrieval", "consolidation", "knowledge_sources"), "memory")


def _page_routing(page: str) -> str:
    """Les fonctions de la page qui routent une cible : résolution, pose de l'emplacement, ouverture, roue."""
    canonical = page[page.index("function canonicalSettingsTab") : page.index("function destroyAgentCatalog()")]
    door = page[page.index("function openSettingsTab(tab,options){") : page.index("function closeSettings(){")]
    return canonical + door


def test_page_routes_categories_sections_and_legacy_ids_into_the_six_category_shell(tmp_path):
    page = HTML.read_text(encoding="utf-8")
    out = run(tmp_path, f"""
globalThis.window=globalThis;window.JarvisSettingsRegistry=R;
const TABS={json.dumps(assembled_tabs())};
const SET={{open:false,tab:null,category:null,section:null,lastItem:{{}},routingGeneration:0}},warn=[],errors=[];
console.warn=(c,x)=>warn.push([c,x]);console.error=(c,x)=>errors.push([c,x]);
let opened=0,rendered=0;const openSettings=()=>{{opened++;SET.open=true;return Promise.resolve()}};
const renderTabs=()=>{{}},renderTab=()=>{{rendered++}};
{_page_routing(page)}
{REGISTER_SLICE_03}
const at=()=>[SET.category,SET.tab,SET.section];
(async()=>{{
  await openSettingsTab('connections');const first=at();
  const seen={{}};
  for(const target of ['memory','routing','labs','bare_hands','voice','voice_output','semantic_retrieval','barehandsCalibration',
    'appearance','voice_audio','interface_interactions','wake_word'])
    {{await openSettingsTab(target);seen[target]=at()}}
  await openSettingsTab('nope');const afterUnknown=at();
  out({{first,opened,seen,afterUnknown,warn,errors,nav:settingsNavigation(),tabs:settingsTabs(),
    same:TABS.every(t=>canonicalSettingsTab(t.id)===t.id),rendered}});
}})();""")
    assert out["first"] == ["connections", "keys", None] and out["opened"] == 1
    seen = out["seen"]
    assert seen["memory"] == ["memory_knowledge", "memory", None]
    # Slice 04 : `routing` → Runtime & CLI ; `cli` et `subagents` ouvrent leurs sections (test suivant).
    assert seen["routing"] == ["advanced_diagnostics", None, "runtime_cli"]
    assert seen["labs"] == seen["bare_hands"] == seen["barehandsCalibration"] == ["advanced_diagnostics", "experimental", None]
    # La ligne « Réglages de la voix » de la roue (`'voice'`) atterrit sur Voix & audio, section Conversation.
    assert seen["voice"] == ["voice_audio", None, "conversation"]
    assert seen["voice_output"] == ["voice_audio", None, "voice_output"]
    assert seen["semantic_retrieval"] == ["memory_knowledge", "memory", None]
    # Une catégorie seule rouvre la dernière entrée ouverte dans cette catégorie (Apparence), sinon la première.
    assert seen["voice_audio"] == ["voice_audio", None, "voice_output"]
    assert seen["interface_interactions"] == ["interface_interactions", "appearance", None]
    assert seen["wake_word"] == ["voice_audio", None, "wake_word"]
    assert out["afterUnknown"] == seen["wake_word"]  # une cible inconnue ne change rien…
    assert out["warn"] == [["settings_target_unknown", {"target": "nope"}]]  # … mais se dit
    assert out["same"] is True and out["errors"] == []
    # Le sous-menu Paramètres de la roue lit les six catégories du registre.
    assert [(t["id"], t["label"]) for t in out["tabs"]] == CATEGORIES
    nav = out["nav"]
    assert [c["id"] for c in nav["categories"]] == [c[0] for c in CATEGORIES] and nav["unassigned"] == []
    assert {c["id"]: [(i["kind"], i["id"]) for i in c["items"]] for c in nav["categories"]} == {
        "voice_audio": [("section", "conversation"), ("section", "voice_output"), ("section", "microphone_sound"),
                        ("section", "turns_interruptions"), ("section", "wake_word")],
        "agents_models": [("section", "main_agent"), ("section", "agent_behavior"), ("section", "subagent_models"),
                          ("section", "subagents")],
        "memory_knowledge": [("tab", "memory")],
        "interface_interactions": [("tab", "shortcuts"), ("tab", "appearance")],
        "connections": [("tab", "keys")],
        "advanced_diagnostics": [("section", "architecture_compat"), ("section", "runtime_cli"), ("section", "diagnostics"),
                                 ("section", "work_methods"), ("tab", "prompts"), ("tab", "experimental")],
    }
    related = {c["id"]: [r["id"] for r in c["related"]] for c in nav["categories"]}
    assert related["interface_interactions"] == ["experimental"]  # les préférences Bare Hands, encore dans Expérimental
    assert related["advanced_diagnostics"] == ["memory"]
    assert related["voice_audio"] == related["connections"] == []


def test_agent_legacy_ids_open_their_sections(tmp_path):
    """Slice 04 : `cli`, `routing`, `subagents` (onglets disparus) et les sections cibles s'ouvrent ; aucun onglet
    `cli` ni `subagents` dans la navigation."""
    page = HTML.read_text(encoding="utf-8")
    assert not {"cli", "subagents"} & set(base_tab_ids())
    out = run(tmp_path, f"""
globalThis.window=globalThis;window.JarvisSettingsRegistry=R;
const TABS={json.dumps(assembled_tabs())};
const SET={{open:true,tab:null,category:'voice_audio',section:'conversation',lastItem:{{}},routingGeneration:0}},warn=[];
console.warn=(c,x)=>warn.push([c,x]);console.error=noop;
const openSettings=()=>Promise.resolve(),renderTabs=noop,renderTab=noop;
{_page_routing(page)}
{REGISTER_SLICE_03}
const seen={{}};
for(const target of ['cli','routing','subagents','agents_models','subagent_models','work_methods','main_agent','agent_behavior','runtime_cli'])
  {{selectTab(target);seen[target]=[SET.category,SET.tab,SET.section]}}
out({{seen,warn,resolved:['cli','routing','subagents'].map(t=>R.page.resolve(t))}});""")
    seen = out["seen"]
    assert seen["cli"] == ["agents_models", None, "main_agent"]
    assert seen["routing"] == seen["runtime_cli"] == ["advanced_diagnostics", None, "runtime_cli"]
    assert seen["subagents"] == ["agents_models", None, "subagents"]
    assert seen["agents_models"] == ["agents_models", None, "subagents"]  # dernière entrée ouverte de la catégorie
    assert seen["work_methods"] == ["advanced_diagnostics", None, "work_methods"]
    assert seen["subagent_models"][2] == "subagent_models" and seen["agent_behavior"][2] == "agent_behavior"
    assert [r["source"] for r in out["resolved"]] == ["section_alias", "section_alias", "section"]
    assert out["warn"] == []


def test_registered_section_takes_over_its_legacy_tab_and_a_stray_tab_stays_reachable(tmp_path):
    page = HTML.read_text(encoding="utf-8")
    out = run(tmp_path, f"""
globalThis.window=globalThis;window.JarvisSettingsRegistry=R;
const TABS=[...{json.dumps(legacy_voice_tabs())},{{id:'stray',label:'Égaré'}}];
const SET={{open:true,tab:'voice',category:'voice_audio',section:null,lastItem:{{}},routingGeneration:0}},errors=[];
console.warn=noop;console.error=(c,x)=>errors.push([c,x]);
const openSettings=()=>Promise.resolve(),renderTabs=noop,renderTab=noop;
{_page_routing(page)}
R.page.register({{id:'wake_word',category:'voice_audio',label:'Mot d’éveil',mount:noop,save:'self',aliases:['wakeword'],order:50}});
R.page.register({{id:'conversation',category:'voice_audio',label:'Conversation',mount:noop,save:'footer',order:10}});
const nav=settingsNavigation();settingsNavigation();
selectTab('wakeword');const viaAlias=[SET.category,SET.tab,SET.section];
selectTab('voice_audio');const remembered=[SET.category,SET.tab,SET.section];
selectTab('voice');const legacy=[SET.category,SET.tab,SET.section];
selectTab('stray');const stray=[SET.category,SET.tab,SET.section];
out({{voice:nav.categories[0].items.map(i=>[i.kind,i.id]),viaAlias,remembered,legacy,stray,errors,
  advanced:nav.categories[5].items.map(i=>i.id)}});""")
    # Sections enregistrées d'abord (ordre du registre), puis les onglets hérités restants ; `wakeword` est remplacé.
    assert out["voice"] == [["section", "conversation"], ["section", "wake_word"], ["tab", "voice"]]
    assert out["viaAlias"] == ["voice_audio", None, "wake_word"]
    assert out["remembered"] == ["voice_audio", None, "wake_word"]
    # `'voice'` reste l'onglet hérité tant qu'aucune section ne le déclare en alias.
    assert out["legacy"] == ["voice_audio", "voice", None]
    # Un onglet sans alias (module qui a contourné le registre) reste atteignable, et se dit une seule fois.
    assert out["stray"] == ["advanced_diagnostics", "stray", None] and "stray" in out["advanced"]
    assert out["errors"] == [["settings_tab_unassigned", {"tabs": ["stray"]}]]


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
