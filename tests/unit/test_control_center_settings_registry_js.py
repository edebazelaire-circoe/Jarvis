"""Registre canonique des Réglages (jarvis-settings-ui-reorganization, Slices 01 et 09), exécuté par node.

Contrat : `docs/settings/navigation-registry.md`. Ce fichier épingle :

- exactement six catégories, dans l'ordre canonique, figées (aucune septième possible) ;
- refus déterministes (code stable) : section en double, catégorie inconnue, section invalide, ID pris par un alias ;
- les alias hérités encore servis sont une table explicite (`LEGACY_TAB_ALIASES`), chacun vers sa section déclarée et
  gardé par un appelant du dépôt ; les anciens ID retirés à la Slice 09 ne résolvent plus rien ;
- l'ancien système d'onglets n'existe plus (aucun `TABS`, `TABS.push/splice`, `SET.tab`, adaptateur) ;
- le shell à six catégories route catégories, sections et alias (`openSettingsTab`, `selectTab`) ; une cible inconnue
  se dit (`settings_target_unknown`) et `openSettingsTab` ouvre alors la catégorie par défaut ; la roue lit les six
  catégories (`settingsTabs`) ;
- le module n'écrit aucun réglage (ni réseau ni stockage) et la page servie l'insère avant l'état des Réglages.
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
    ("voice_audio", "Personnalisation"),
    ("agents_models", "Architecture & Agents"),
    ("memory_knowledge", "Mémoire & Connaissances"),
    ("interface_interactions", "Interface & Interactions"),
    ("connections", "Plugins & MCP"),
    ("advanced_diagnostics", "Avancé & Diagnostics"),
]
#: Alias hérités encore servis après la Slice 09, et l'appelant du dépôt qui les garde.
ALIASES = {
    "memory": ("memory_knowledge", "recall"),
    # refonte-ui-settings, Slice 05 : sections fondues dans l'onglet Mémoire.
    "semantic_retrieval": ("memory_knowledge", "recall"),
    "consolidation": ("memory_knowledge", "recall"),
    # jarvis-architecture-agents-settings-editor, Slice 07 : sections retirées, liens durables redirigés.
    "main_agent": ("agents_models", "architecture"),
    "subagent_models": ("agents_models", "subagents"),
}
#: Appelant de chaque alias, chemin depuis la racine du dépôt : un module de la page, ou le document durable qui
#: publie l'ancien identifiant (`docs/legacy/settings-tab-aliases.md`).
ALIAS_CALLERS = {
    "memory": ("docs/legacy/settings-tab-aliases.md", "| `memory` | `memory_knowledge` / `recall` |"),
    "semantic_retrieval": ("docs/legacy/settings-tab-aliases.md", "| `semantic_retrieval` | `memory_knowledge` / `recall` |"),
    "consolidation": ("docs/legacy/settings-tab-aliases.md", "| `consolidation` | `memory_knowledge` / `recall` |"),
    "main_agent": ("docs/legacy/settings-tab-aliases.md", "| `main_agent` | alias →"),
    "subagent_models": ("docs/legacy/settings-tab-aliases.md", "| `subagent_models` | alias →"),
}
#: Anciens ID d'onglet et ancres retirés à la Slice 09 (plus aucun appelant ni document durable) : inconnus.
RETIRED_IDS = ("voice", "wakeword", "cli", "routing", "keys", "appearance", "experimental",
               "barehandsSettings", "barehandsCalibration", "barehandsRecord", "barehandsBenchmarkSection")
#: Anciens ID d'onglet qui sont l'ID même de leur section (pas des alias) : ils s'ouvrent comme toute section.
SECTION_IDS_FROM_OLD_TABS = {
    "prompts": ("advanced_diagnostics", "prompts"),
    "shortcuts": ("interface_interactions", "shortcuts"),
    "subagents": ("agents_models", "subagents"),
}
#: Les cinq groupes déclarés d'Avancé & diagnostic (Slice 08), dans l'ordre d'affichage.
ADVANCED_GROUPS = [
    ("architecture_compat", "Architecture & compatibilité"),
    ("prompts", "Prompts & instructions"),
    ("runtime_cli", "Runtime & CLI"),
    ("diagnostics", "Diagnostics"),
    ("labs", "Labs & outils de test"),
]
#: Groupe déclaré de chaque section d'Avancé enregistrée par la page servie (Slices 03-08).
ADVANCED_SECTION_GROUP = {
    "architecture_compat": "architecture_compat", "memory_advanced": "architecture_compat", "prompts": "prompts",
    "runtime_cli": "runtime_cli",
    "diagnostics": "diagnostics", "scene_gate": "labs", "work_methods": "labs", "barehands_lab": "labs",
}


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


#: Sections enregistrées par la page servie (Slices 03 à 08) : `(id, catégorie, order, save)`. Aucune ne déclare d'alias
#: depuis la Slice 09.
SLICE_03_SECTIONS = (
    ("conversation", "voice_audio", 10, "footer"), ("voice_output", "voice_audio", 20, "footer"),
    ("microphone_sound", "voice_audio", 30, "footer"), ("turns_interruptions", "voice_audio", 40, "footer"),
    ("wake_word", "voice_audio", 50, "self"), ("architecture_compat", "advanced_diagnostics", 10, "footer"),
    ("diagnostics", "advanced_diagnostics", 40, "readonly"),
)
SLICE_04_SECTIONS = (
    ("agent_behavior", "voice_audio", 8, "footer"), ("subagents", "agents_models", 20, "self"),
    ("runtime_cli", "advanced_diagnostics", 30, "footer"), ("work_methods", "advanced_diagnostics", 50, "self"),
)
SLICE_05_SECTIONS = (
    ("recall", "memory_knowledge", 10, "self"), ("knowledge_sources", "memory_knowledge", 40, "self"),
    ("memory_center", "memory_knowledge", 50, "readonly"), ("memory_advanced", "advanced_diagnostics", 20, "self"),
)
SLICE_06_SECTIONS = (
    ("theme_scene", "voice_audio", 5, "self"), ("shortcuts", "interface_interactions", 20, "self"),
    ("bare_hands", "interface_interactions", 30, "self"), ("barehands_lab", "advanced_diagnostics", 60, "self"),
)
SLICE_07_SECTIONS = (("mcp_plugins", "connections", 5, "readonly"), ("providers", "connections", 10, "self"))
#: jarvis-architecture-agents-settings-editor, Slice 07 : les deux onglets d'Architecture & Agents.
ARCHITECTURE_AGENTS_SECTIONS = (("architecture", "agents_models", 10, "self"),)
SLICE_08_SECTIONS = (
    ("prompts", "advanced_diagnostics", 10, "self"), ("scene_gate", "advanced_diagnostics", 40, "self"),
)
ALL_SECTIONS = (*SLICE_03_SECTIONS, *SLICE_04_SECTIONS, *SLICE_05_SECTIONS, *SLICE_06_SECTIONS, *SLICE_07_SECTIONS,
                *SLICE_08_SECTIONS, *ARCHITECTURE_AGENTS_SECTIONS)


def _group(section_id: str) -> str:
    return f"group:'{ADVANCED_SECTION_GROUP[section_id]}'," if section_id in ADVANCED_SECTION_GROUP else ""


REGISTER_PAGE_SECTIONS = "".join(
    f"R.page.register({{id:'{i}',category:'{c}',{_group(i)}label:'{i}',order:{o},save:'{v}',mount:noop}});"
    for i, c, o, v in ALL_SECTIONS
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
reg.register({id:'wake_word',category:'voice_audio',label:'Mot d’éveil',order:50,mount:noop,destroy:noop,save:'self',applies:'next_voice_start'});
reg.register({id:'conversation',category:'voice_audio',label:'Conversation',order:10,mount:noop,save:'footer',isDirty:()=>false});
reg.register({id:'scene_gate',category:'advanced_diagnostics',label:'Scène',group:'labs',advanced:true,mount:noop,save:'readonly'});
out({voice:reg.sections('voice_audio').map(s=>s.id),snap:reg.snapshot(),
  frozen:Object.isFrozen(reg.section('wake_word')),
  resolve:['voice_audio','conversation','memory','wakeword','voice','labs','experimental','barehandsSettings','nope',42].map(t=>[t,reg.resolve(t)]),
  unknownCat:codeOf(()=>reg.sections('seventh'))});""")
    assert out["voice"] == ["conversation", "wake_word"]
    assert [c["id"] for c in out["snap"]] == [c[0] for c in CATEGORIES]
    assert out["snap"][5]["sections"] == [{"id": "scene_gate", "label": "Scène", "group": "labs", "order": 0, "save": "readonly", "advanced": True}]
    assert out["snap"][5]["groups"] == [g for g, _ in ADVANCED_GROUPS] and out["snap"][0]["groups"] == []
    assert out["frozen"] is True
    resolved = dict((t if isinstance(t, str) else str(t), r) for t, r in out["resolve"])
    assert resolved["voice_audio"] == {"category": "voice_audio", "section": None, "source": "category"}
    assert resolved["conversation"] == {"category": "voice_audio", "section": "conversation", "source": "section"}
    # Alias dont la section cible n'est pas enregistrée dans ce registre : la catégorie seule, jamais une section devinée.
    assert resolved["memory"] == {"category": "memory_knowledge", "section": None, "source": "alias"}
    # Anciens ID retirés à la Slice 09 : inconnus, comme un groupe.
    assert resolved["wakeword"] is None and resolved["voice"] is None and resolved["experimental"] is None
    assert resolved["barehandsSettings"] is None and resolved["labs"] is None
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
  aliases_field:[{...ok,aliases:['old']}],
  no_mount:[{...ok,mount:undefined}],
  bad_save:[{...ok,save:true}],
  readonly_dirty:[{...ok,save:'readonly',isDirty:()=>true}],
  bad_applies:[{...ok,applies:'later'}],
  not_object:[null],
  id_is_legacy_alias:[{...ok,id:'memory',category:'memory_knowledge'}],
  advanced_without_group:[{...ok,id:'probe',category:'advanced_diagnostics'}],
  advanced_unknown_group:[{...ok,id:'probe',category:'advanced_diagnostics',group:'misc'}],
  group_in_ungrouped_category:[{...ok,group:'labs'}],
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
        "aliases_field": "settings_section_invalid",  # Slice 09 : les alias ne sont plus déclarés par les sections
        "no_mount": "settings_section_invalid",
        "bad_save": "settings_section_invalid",
        "readonly_dirty": "settings_section_invalid",
        "bad_applies": "settings_section_invalid",
        "not_object": "settings_section_invalid",
        "id_is_legacy_alias": "settings_alias_conflict",
        "advanced_without_group": "settings_section_group",
        "advanced_unknown_group": "settings_section_group",
        "group_in_ungrouped_category": "settings_section_group",
    }
    for name, code in expected.items():
        first, second = out[name]["first"], out[name]["second"]
        assert first[0] is not None and first[0][0] == code, (name, first)
        assert first == second, name  # même code, même message, même état du registre
    # Un refus n'enregistre rien : seule la première section valide reste.
    assert out["duplicate"]["first"][1] == ["shortcuts"]
    assert out["unknown_category"]["first"][1] == []


def test_every_remaining_alias_is_explicit_data_with_a_caller_and_its_declared_destination(tmp_path):
    """Slice 09 : la table est la seule source des alias, figée ; chaque alias restant vise une section que la page
    enregistre et garde un appelant réel du dépôt ; les ID retirés ne sont plus dans la table."""
    out = run(tmp_path, f"""{REGISTER_PAGE_SECTIONS}
out({{aliases:R.LEGACY_TAB_ALIASES,frozen:Object.isFrozen(R.LEGACY_TAB_ALIASES)&&Object.values(R.LEGACY_TAB_ALIASES).every(Object.isFrozen),
  resolved:Object.fromEntries(Object.keys(R.LEGACY_TAB_ALIASES).map(a=>[a,R.page.resolve(a)])),
  retired:{json.dumps(list(RETIRED_IDS))}.map(t=>[t,R.page.resolve(t),R.legacyAlias(t)]),
  oldTabSections:Object.fromEntries({json.dumps(list(SECTION_IDS_FROM_OLD_TABS))}.map(t=>[t,R.page.resolve(t)])),
  default:R.DEFAULT_CATEGORY,anchors:'LEGACY_ANCHORS' in R}});""")
    assert {k: (v["category"], v["section"]) for k, v in out["aliases"].items()} == ALIASES
    assert all(set(v) == {"category", "section"} for v in out["aliases"].values())  # ni `also` ni `tab`
    assert out["frozen"] is True
    for alias, (category, section) in ALIASES.items():
        assert out["resolved"][alias] == {"category": category, "section": section, "source": "alias"}
        name, call = ALIAS_CALLERS[alias]
        assert call in (ROOT / name).read_text(encoding="utf-8"), (alias, name)
    assert all(hit is None and legacy is None for _t, hit, legacy in out["retired"]), out["retired"]
    assert {k: (v["category"], v["section"], v["source"]) for k, v in out["oldTabSections"].items()} == {
        k: (*v, "section") for k, v in SECTION_IDS_FROM_OLD_TABS.items()}
    assert out["default"] == "voice_audio" and out["anchors"] is False


def test_no_legacy_tab_machinery_is_left_in_the_repository():
    """Slice 09 : l'ancien système d'onglets n'existe plus, nulle part dans le code du dépôt."""
    offenders = []
    for path in [*(ROOT / "jarvis").rglob("*.js"), *(ROOT / "jarvis").rglob("*.html"), *(ROOT / "jarvis").rglob("*.py")]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bTABS\.(push|splice|unshift)\(", text):
            offenders.append(path.name)
    assert offenders == [], "un module ajoute un onglet de premier niveau : enregistrer une section dans le registre"
    page = HTML.read_text(encoding="utf-8")
    served = [page, *(p.read_text(encoding="utf-8") for p in RUNTIME.glob("control_center*.js") if p.name != "control_center_memory.js")]
    code = [re.sub(r"/\*.*?\*/", "", text, flags=re.S) for text in served]
    for forbidden in ("const TABS=", "TABS.", "SET.tab", "bindTab", "canonicalSettingsTab", "legacyTabFor",
                      "navigationFromLegacyTabs", "LEGACY_ANCHORS", "modalSub", "settingsRelated", "data-related",
                      "settings_tab_unassigned", "kind==='tab'"):
        assert not [i for i, text in enumerate(code) if forbidden in text], forbidden
    # Le Memory Center a ses propres onglets internes (`TABS` local figé), sans rapport avec les Réglages.
    assert "const TABS=Object.freeze([" in (RUNTIME / "control_center_memory.js").read_text(encoding="utf-8")


def test_category_cycle_wraps_in_canonical_order(tmp_path):
    out = run(tmp_path, """out([R.cycleCategory('voice_audio',1),R.cycleCategory('voice_audio',-1),R.cycleCategory('advanced_diagnostics',1),
  R.cycleCategory('nope',1),R.cycleCategory('nope',-1)]);""")
    assert out == ["agents_models", "advanced_diagnostics", "voice_audio", "voice_audio", "advanced_diagnostics"]


#: Sections cibles prévues (`docs/settings/navigation-registry.md` § 3), enregistrées par les Slices 03 à 08.
PLANNED_SECTIONS = {
    "voice_audio": ["theme_scene", "agent_behavior", "conversation", "voice_output", "microphone_sound",
                    "turns_interruptions", "wake_word"],
    "agents_models": ["architecture", "subagents"],  # exactement deux onglets (D02)
    "memory_knowledge": ["recall", "knowledge_sources", "memory_center"],  # trois onglets (refonte-ui-settings S05)
    "interface_interactions": ["shortcuts", "bare_hands"],
    "connections": ["mcp_plugins", "providers"],
    "advanced_diagnostics": ["architecture_compat", "memory_advanced", "prompts", "runtime_cli", "diagnostics", "scene_gate",
                             "work_methods", "barehands_lab"],
}


def test_every_planned_target_section_is_registered():
    registered = {(i, c) for i, c, *_ in ALL_SECTIONS}
    assert registered == {(s, c) for c, sections in PLANNED_SECTIONS.items() for s in sections}


def _page_routing(page: str) -> str:
    """Les fonctions de la page qui routent une cible : résolution, pose de l'emplacement, ouverture, roue."""
    routing = page[page.index("function settingsTarget(id,nav){") : page.index("function destroyAgentCatalog()")]
    door = page[page.index("function openSettingsTab(tab,options){") : page.index("function closeSettings(){")]
    return routing + door


def _routing_script(page: str, *, open_: bool, body: str) -> str:
    state = ("{open:true,category:'voice_audio',section:'conversation',lastItem:{},routingGeneration:0}" if open_
             else "{open:false,category:null,section:null,lastItem:{},routingGeneration:0}")
    return f"""
globalThis.window=globalThis;window.JarvisSettingsRegistry=R;
const SET={state},warn=[],errors=[];
console.warn=(c,x)=>warn.push([c,x]);console.error=(c,x)=>errors.push([c,x]);
let opened=0,rendered=0;const openSettings=()=>{{opened++;SET.open=true;return Promise.resolve()}};
const renderTabs=()=>{{}},renderTab=()=>{{rendered++}};
{_page_routing(page)}
{REGISTER_PAGE_SECTIONS}
const at=()=>[SET.category,SET.section];
{body}"""


def test_page_routes_categories_sections_and_aliases_into_the_six_category_shell(tmp_path):
    page = HTML.read_text(encoding="utf-8")
    out = run(tmp_path, _routing_script(page, open_=False, body="""
(async()=>{
  await openSettingsTab('connections');const first=at();
  const seen={};
  for(const target of ['memory','scene_gate','prompts','bare_hands','voice_output','semantic_retrieval','theme_scene',
    'voice_audio','interface_interactions','providers','wake_word'])
    {await openSettingsTab(target);seen[target]=at()}
  out({first,opened,seen,warn,errors,nav:settingsNavigation(),tabs:settingsTabs(),rendered});
})();"""))
    assert out["first"] == ["connections", "mcp_plugins"] and out["opened"] == 1
    seen = out["seen"]
    assert seen["memory"] == ["memory_knowledge", "recall"]  # le seul alias restant (Memory Center › Réglages)
    assert seen["scene_gate"] == ["advanced_diagnostics", "scene_gate"]
    assert seen["prompts"] == ["advanced_diagnostics", "prompts"]
    assert seen["bare_hands"] == ["interface_interactions", "bare_hands"]
    assert seen["voice_output"] == ["voice_audio", "voice_output"]
    assert seen["semantic_retrieval"] == ["memory_knowledge", "recall"]  # alias (refonte-ui-settings S05)
    assert seen["theme_scene"] == ["voice_audio", "theme_scene"]  # Personnalisation (hub du 2026-10-23)
    # Une catégorie seule rouvre la dernière entrée ouverte dans cette catégorie, sinon la première.
    assert seen["voice_audio"] == ["voice_audio", "theme_scene"]
    assert seen["interface_interactions"] == ["interface_interactions", "bare_hands"]
    assert seen["providers"] == ["connections", "providers"]
    assert seen["wake_word"] == ["voice_audio", "wake_word"]
    assert out["warn"] == [] and out["errors"] == []
    # Le shell ouvert, chaque entrée se redessine (la pose de l'emplacement puis `renderTab`).
    assert out["rendered"] == 11
    # Le sous-menu Paramètres de la roue lit les six catégories du registre.
    assert [(t["id"], t["label"]) for t in out["tabs"]] == CATEGORIES
    nav = out["nav"]
    assert list(nav) == ["categories"]  # ni `unassigned` ni onglets : la navigation n'a plus que des sections
    assert [c["id"] for c in nav["categories"]] == [c[0] for c in CATEGORIES]
    assert all("related" not in c for c in nav["categories"])
    assert {c["id"]: [(i["kind"], i["id"]) for i in c["items"]] for c in nav["categories"]} == {
        "voice_audio": [("section", "theme_scene"), ("section", "agent_behavior"), ("section", "conversation"),
                        ("section", "voice_output"), ("section", "microphone_sound"),
                        ("section", "turns_interruptions"), ("section", "wake_word")],
        "agents_models": [("section", "architecture"), ("section", "subagents")],
        "memory_knowledge": [("section", "recall"), ("section", "knowledge_sources"), ("section", "memory_center")],
        "interface_interactions": [("section", "shortcuts"), ("section", "bare_hands")],
        "connections": [("section", "mcp_plugins"), ("section", "providers")],
        # Slice 08 : rangées par groupe déclaré (ordre de `CATEGORY_GROUPS`), puis `order` dans le groupe.
        "advanced_diagnostics": [("section", "architecture_compat"), ("section", "memory_advanced"), ("section", "prompts"),
                                 ("section", "runtime_cli"),
                                 ("section", "diagnostics"), ("section", "scene_gate"), ("section", "work_methods"),
                                 ("section", "barehands_lab")],
    }
    advanced = next(c for c in nav["categories"] if c["id"] == "advanced_diagnostics")
    assert [(g["id"], g["label"]) for g in advanced["groups"]] == ADVANCED_GROUPS
    assert {i["id"]: i["group"] for i in advanced["items"]} == ADVANCED_SECTION_GROUP
    assert advanced["notice"].startswith("Outils d’opérateur")
    assert all(c["groups"] == [] and c["notice"] == "" for c in nav["categories"] if c["id"] != "advanced_diagnostics")


@pytest.mark.parametrize("open_", [False, True], ids=["closed", "open"])
def test_an_unknown_or_retired_id_is_logged_and_opens_the_default_category(tmp_path, open_):
    """Slice 09 : `openSettingsTab` d'une cible inconnue (ou d'un ancien ID retiré) le journalise
    (`settings_target_unknown`) et ouvre le shell sur sa catégorie par défaut, Voix & audio ; réglages fermés, ils
    s'ouvrent ; ouverts, l'emplacement passe à cette catégorie."""
    page = HTML.read_text(encoding="utf-8")
    out = run(tmp_path, _routing_script(page, open_=open_, body="""
(async()=>{
  const seen={};
  for(const target of ['nope','voice','experimental','keys','barehandsRecord']){
    if(!SET.open){SET.category='connections';SET.section='providers'}
    else selectTab('providers');
    await openSettingsTab(target);seen[target]=at();
  }
  const before=at();selectTab('nope2');const afterSelect=at();
  out({seen,opened,warn,errors,before,afterSelect});
})();"""))
    for target in ("nope", "voice", "experimental", "keys", "barehandsRecord"):
        assert out["seen"][target] == ["voice_audio", "theme_scene"], (target, out["seen"][target])
    assert out["opened"] == (0 if open_ else 1)
    assert out["warn"][:5] == [["settings_target_unknown", {"target": t}] for t in
                               ("nope", "voice", "experimental", "keys", "barehandsRecord")]
    # Un lien interne inconnu (`selectTab`) se dit aussi, mais ne déplace rien.
    assert out["warn"][5:] == [["settings_target_unknown", {"target": "nope2"}]]
    assert out["afterSelect"] == out["before"]
    assert out["errors"] == []


def test_advanced_groups_are_declared_once_and_every_page_registration_names_one(tmp_path):
    """Slice 08 : cinq groupes déclarés (donnée du registre, figée) ; chaque enregistrement d'Avancé dans le code servi
    porte un groupe déclaré, explicitement (aucune déduction) ; la fixture dit ce que la page enregistre vraiment."""
    out = run(tmp_path, """out({groups:R.CATEGORY_GROUPS,frozen:Object.isFrozen(R.CATEGORY_GROUPS)&&Object.isFrozen(R.CATEGORY_GROUPS.advanced_diagnostics)
      &&R.CATEGORY_GROUPS.advanced_diagnostics.every(Object.isFrozen),fn:R.groups('advanced_diagnostics').map(g=>g.id),none:R.groups('voice_audio')});""")
    assert list(out["groups"]) == ["advanced_diagnostics"]
    assert [(g["id"], g["label"]) for g in out["groups"]["advanced_diagnostics"]] == ADVANCED_GROUPS
    assert all(g["description"] for g in out["groups"]["advanced_diagnostics"])
    assert out["frozen"] is True and out["fn"] == [g for g, _ in ADVANCED_GROUPS] and out["none"] == []
    declared = {g for g, _ in ADVANCED_GROUPS}
    found = {}
    for path in [HTML, *RUNTIME.glob("control_center*.js")]:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\{id:([\w.']+),category:'advanced_diagnostics',(group:'(\w+)',)?", text):
            assert match.group(3) in declared, (path.name, match.group(0))
            found[match.group(1).strip("'")] = match.group(3)
    # Bare Hands nomme ses entrées par `SETTINGS_ENTRY.lab`, la scène par `SECTION_ENTRY` ; les autres par leur ID.
    assert found == {"runtime_cli": "runtime_cli", "work_methods": "labs", "architecture_compat": "architecture_compat",
                     "memory_advanced": "architecture_compat",
                     "diagnostics": "diagnostics", "prompts": "prompts", "SETTINGS_ENTRY.lab": "labs",
                     "SECTION_ENTRY": "labs"}
    scene = (RUNTIME / "control_center_scene_settings.js").read_text(encoding="utf-8")
    assert "const SECTION_ENTRY='scene_gate';" in scene and "aliases:" not in scene  # Slice 09 : plus d'alias de section
    assert "registerSettingsSection({id:SECTION_ENTRY,category:'advanced_diagnostics',group:'labs',order:40,save:'self'" in scene
    page = HTML.read_text(encoding="utf-8")
    assert ("const PROMPTS_SECTION={id:'prompts',category:'advanced_diagnostics',group:'prompts',order:10,advanced:true,"
            "save:'self',") in page and "registerSettingsSection(PROMPTS_SECTION)" in page


def test_advanced_sections_are_ordered_by_declared_group_before_their_order(tmp_path):
    """Le groupe l'emporte sur `order` : une section de Labs d'ordre 1 reste après une section d'Architecture d'ordre
    99 ; dans un groupe, `order` puis l'ordre d'enregistrement."""
    out = run(tmp_path, """
const reg=R.createRegistry(),add=(id,group,order)=>reg.register({id,category:'advanced_diagnostics',group,order,label:id,mount:noop,save:'self'});
add('lab_b','labs',5);add('lab_a','labs',1);add('diag','diagnostics',0);add('arch','architecture_compat',99);add('lab_c','labs',5);
add('prompt','prompts',-3);add('cli','runtime_cli',7);
out(reg.sections('advanced_diagnostics').map(s=>s.id));""")
    assert out == ["arch", "prompt", "cli", "diag", "lab_a", "lab_b", "lab_c"]


def test_page_connections_section_matches_the_registered_fixture():
    """La fixture `SLICE_07_SECTIONS` dit ce que la page enregistre vraiment (`CONNECTIONS_SECTION`)."""
    page = HTML.read_text(encoding="utf-8")
    assert ("const CONNECTIONS_SECTION={id:'providers',category:'connections',order:10,save:'self',"
            "label:'Fournisseurs',") in page
    assert "registerSettingsSection(CONNECTIONS_SECTION)" in page


def test_agent_sections_open_and_their_retired_ids_do_not(tmp_path):
    """Slice 04 : les sections Agents & modèles et leurs sections d'Avancé s'ouvrent ; Slice 09 : `cli` et `routing` ne
    sont plus des alias (aucun appelant), `subagents` est l'ID de la section des rôles."""
    page = HTML.read_text(encoding="utf-8")
    out = run(tmp_path, _routing_script(page, open_=True, body="""
const seen={};
for(const target of ['subagents','agents_models','subagent_models','work_methods','main_agent','agent_behavior','runtime_cli','cli','routing'])
  {selectTab(target);seen[target]=at()}
out({seen,warn,resolved:['cli','routing','subagents'].map(t=>R.page.resolve(t))});"""))
    seen = out["seen"]
    assert seen["subagents"] == ["agents_models", "subagents"]
    assert seen["agents_models"] == ["agents_models", "subagents"]  # dernière entrée ouverte de la catégorie
    assert seen["work_methods"] == ["advanced_diagnostics", "work_methods"]
    # Slice 07 (jarvis-architecture-agents-settings-editor) : les sections retirées sont des alias vers les onglets.
    assert seen["main_agent"] == ["agents_models", "architecture"]
    assert seen["subagent_models"] == ["agents_models", "subagents"] and seen["agent_behavior"][1] == "agent_behavior"
    assert seen["runtime_cli"] == ["advanced_diagnostics", "runtime_cli"]
    # Un ID retiré ne déplace rien (`selectTab`) et se dit.
    assert seen["cli"] == seen["routing"] == ["advanced_diagnostics", "runtime_cli"]
    assert out["warn"] == [["settings_target_unknown", {"target": "cli"}], ["settings_target_unknown", {"target": "routing"}]]
    assert out["resolved"] == [None, None, {"category": "agents_models", "section": "subagents", "source": "section"}]


def test_memory_alias_opens_recall_and_every_memory_section(tmp_path):
    """Slice 05 : `memory` (onglet disparu, Memory Center › Réglages) ouvre l'onglet Mémoire (`recall`), comme les
    anciennes sections `semantic_retrieval` et `consolidation` (refonte-ui-settings S05) ; chaque onglet s'ouvre ; la
    catégorie rouvre le dernier onglet ouvert."""
    page = HTML.read_text(encoding="utf-8")
    out = run(tmp_path, _routing_script(page, open_=True, body="""
const seen={};
for(const target of ['memory','semantic_retrieval','consolidation','knowledge_sources','memory_center','voice_audio','memory_knowledge'])
  {selectTab(target);seen[target]=at()}
const nav=settingsNavigation().categories.find(c=>c.id==='memory_knowledge');
out({seen,warn,resolved:R.page.resolve('memory'),items:nav.items.map(i=>[i.kind,i.id,i.save])});"""))
    seen = out["seen"]
    assert seen["memory"] == ["memory_knowledge", "recall"]
    for alias in ("semantic_retrieval", "consolidation"):
        assert seen[alias] == ["memory_knowledge", "recall"]
    for section in ("knowledge_sources", "memory_center"):
        assert seen[section] == ["memory_knowledge", section]
    assert seen["memory_knowledge"] == ["memory_knowledge", "memory_center"]  # dernière entrée ouverte
    assert out["resolved"] == {"category": "memory_knowledge", "section": "recall", "source": "alias"}
    assert out["items"] == [["section", "recall", "self"], ["section", "knowledge_sources", "self"],
                            ["section", "memory_center", "readonly"]]
    assert out["warn"] == []


def test_page_memory_sections_match_the_registered_fixture():
    """La fixture `SLICE_05_SECTIONS` dit ce que la page enregistre vraiment (`MEMORY_SECTIONS`) ; aucun alias déclaré."""
    page = HTML.read_text(encoding="utf-8")
    block = page[page.index("const MEMORY_SECTIONS=[") : page.index("function memorySettingsStore()")]
    assert "aliases" not in block
    found = re.findall(r"\{id:'([a-z_]+)',category:'([a-z_]+)',(?:group:'\w+',)?order:(\d+),label:'[^']+'((?:,mode:'\w+')?)((?:,save:'\w+')?)", block)
    assert [(i, c, int(o), save[7:-1] if save else "self") for i, c, o, _m, save in found] == list(SLICE_05_SECTIONS)


def test_module_writes_no_setting_and_is_served_before_the_settings_state():
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("fetch(", "localStorage", "sessionStorage", "XMLHttpRequest", "api(", "document.", "indexedDB"):
        assert forbidden not in source, forbidden
    page = HTML.read_text(encoding="utf-8")
    assert page.count(SETTINGS_REGISTRY_SCRIPT_MARKER) == 1
    assert page.index(SETTINGS_REGISTRY_SCRIPT_MARKER) < page.index("\nconst SET={")


async def test_served_page_inlines_the_registry(tmp_path: Path):
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert SETTINGS_REGISTRY_SCRIPT_MARKER not in served
    assert "root.JarvisSettingsRegistry=api" in served
    assert served.index("root.JarvisSettingsRegistry=api") < served.index("\nconst SET={")


def test_page_interface_sections_match_the_registered_fixture():
    """La fixture `SLICE_06_SECTIONS` dit ce que les modules enregistrent vraiment (Slice 06)."""
    page = HTML.read_text(encoding="utf-8")
    work = (RUNTIME / "control_center_work.js").read_text(encoding="utf-8")
    barehands = (RUNTIME / "control_center_barehands.js").read_text(encoding="utf-8")
    assert ("const THEME_SCENE_SECTION={id:'theme_scene',category:'voice_audio',order:5,"
            "save:'self',\n    label:'Thème & scène visuelle',") in work
    assert "const SHORTCUTS_SECTION={id:'shortcuts',category:'interface_interactions',order:20,save:'self'" in page
    assert "registerSettingsSection({id:SETTINGS_ENTRY.ordinary,category:'interface_interactions',order:30,save:'self'" in barehands
    assert "registerSettingsSection({id:SETTINGS_ENTRY.lab,category:'advanced_diagnostics',group:'labs',order:60,save:'self'" in barehands
    assert "const SETTINGS_ENTRY=Object.freeze({ordinary:'bare_hands',lab:'barehands_lab',diagnostic:'barehands'});" in barehands


def test_no_registered_section_declares_an_alias():
    """Slice 09 : les alias ne sont plus une propriété des sections (la table du registre est la seule source)."""
    for path in [HTML, *RUNTIME.glob("control_center*.js")]:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(registerSettingsSection\(\{|_SECTIONS?=\[?\{|_SECTION=\{)", text):
            window = text[match.start(): match.start() + 600]
            assert "aliases:[" not in window.split("mount")[0], (path.name, window[:120])
