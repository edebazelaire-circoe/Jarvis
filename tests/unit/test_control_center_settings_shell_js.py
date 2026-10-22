"""Shell des Réglages à six catégories (jarvis-settings-ui-reorganization, Slice 02), exécuté par node.

Contrat : `docs/settings/settings-shell.md`. Ce fichier épingle :

- les primitives visuelles (`JarvisSettingsUI`) : échappement du texte, libellé lié au contrôle, aide liée par
  `aria-describedby`, badge jamais réduit à une couleur, notice vivante au besoin, moments d'application = ceux du
  registre ;
- le cycle de vie d'une section enregistrée montée par le shell : `mount(host, context)`, `destroy` appelé au
  changement ou à la fermeture (`cleanupSettingsSurface`), `context.isCurrent()` faux ensuite, échec de montage
  visible et codé, politique du pied Enregistrer ;
- un refus d'enregistrement est journalisé avec son code et retenu pour être montré ;
- la navigation n'est jamais une liste recopiée : aucun libellé de catégorie écrit dans la page, `ui_tab_next` /
  `ui_tab_prev` passent par `cycleCategory` ;
- la page servie insère les primitives avant `TABS`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    ControlCenter,
    SETTINGS_REGISTRY_SCRIPT_FILE,
    SETTINGS_UI_SCRIPT_FILE,
    SETTINGS_UI_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
REGISTRY = RUNTIME / SETTINGS_REGISTRY_SCRIPT_FILE
UI = RUNTIME / SETTINGS_UI_SCRIPT_FILE
HTML = RUNTIME / "control_center.html"


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "shell.cjs"
    script.write_text(
        f"const R=require({json.dumps(str(REGISTRY))}),UI=require({json.dumps(str(UI))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const noop=()=>{};\n" + body,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def slice_(page: str, start: str, end: str) -> str:
    return page[page.index(start) : page.index(end)]


def test_primitives_escape_text_link_labels_and_never_rely_on_colour_alone(tmp_path):
    out = run(tmp_path, r"""
const tryIt=f=>{try{return f()}catch(e){return 'ERR:'+e.message}};
out({
  intro:UI.intro({id:'catTitle',title:'Voix <b>&</b> audio',description:'« micro »'}),
  section:UI.section({id:'wake_word',title:'Mot d’éveil',description:'Déclencheur',advanced:true,applies:'next_voice_start',body:'<p>corps</p>'}),
  field:UI.field({id:'ww_sens',label:'Sensibilité',hint:'Entre 0 et 1.',control:'<input id="ww_sens" aria-describedby="ww_sens-hint">'}),
  noId:tryIt(()=>UI.field({label:'x',control:''})),badId:tryIt(()=>UI.section({id:'a b',title:'x'})),
  emptyBadge:tryIt(()=>UI.badge('ok','')),badge:UI.badge('nope','État'),
  alert:UI.notice({kind:'bad',live:'assertive',title:'Échec',text:'<script>'}),
  polite:UI.notice({kind:'ok',live:'polite',text:'Enregistré.'}),plain:UI.notice({text:'Info'}),
  advanced:UI.advanced({id:'adv',body:'<p>x</p>'}),actions:UI.actions('<button>Ok</button>'),
  applies:Object.keys(UI.APPLIES_LABELS),registryApplies:R.APPLIES,noApplies:UI.appliesBadge('later'),
});""")
    assert out["intro"] == ('<header class="set-intro"><h2 class="set-intro-title" id="catTitle">Voix &lt;b&gt;&amp;&lt;/b&gt; audio</h2>'
                            '<p class="set-intro-desc">« micro »</p></header>')
    section = out["section"]
    assert 'id="wake_word" aria-labelledby="wake_word-title"' in section and '<h3 id="wake_word-title">Mot d’éveil</h3>' in section
    assert 'set-badge-advanced">Avancé<' in section and "Au prochain démarrage de Voice" in section and "<p>corps</p>" in section
    assert '<label class="set-field-label" for="ww_sens">Sensibilité</label>' in out["field"]
    assert '<p class="set-field-hint" id="ww_sens-hint">Entre 0 et 1.</p>' in out["field"]
    assert out["noId"].startswith("ERR:") and out["badId"].startswith("ERR:") and out["emptyBadge"].startswith("ERR:")
    assert out["badge"] == '<span class="set-badge set-badge-info">État</span>'
    assert 'role="alert"' in out["alert"] and "&lt;script&gt;" in out["alert"] and "<script>" not in out["alert"]
    assert 'role="status"' in out["polite"] and "role=" not in out["plain"]
    assert out["advanced"].startswith('<details class="set-advanced" id="adv"><summary>Réglages avancés</summary>')
    assert out["actions"] == '<div class="set-actions"><button>Ok</button></div>'
    assert out["applies"] == out["registryApplies"] and out["noApplies"] == ""


def _lifecycle_sources(page: str) -> str:
    # De `cleanupSettingsSurface` à `renderTabs` : nettoyage, porte d'enregistrement ; puis le montage.
    return (slice_(page, "function cleanupSettingsSurface()", "function renderTabs()")
            + slice_(page, "function mountRegisteredSection(revision){", "async function renderTab(){"))


def test_registered_section_mounts_is_destroyed_on_leave_and_fails_visibly(tmp_path):
    page = HTML.read_text(encoding="utf-8")
    out = run(tmp_path, f"""
globalThis.window=globalThis;window.JarvisSettingsRegistry=R;window.JarvisSettingsUI=UI;
const errors=[];console.error=(c,x)=>errors.push([c,x]);
const el=()=>({{className:'',dataset:{{}},innerHTML:''}});
globalThis.document={{createElement:el}};
const modalContent={{innerHTML:'',children:[],replaceChildren(...k){{this.children=k}}}},modalSave={{style:{{}}}};
const esc=s=>String(s),said=[];const say=(t,k)=>said.push([t,k]);
const SET={{open:true,section:null,renderRevision:1,sectionView:null,subagentView:null,data:{{v:1}},draft:{{d:1}},dirty:false}};
const destroyAgentCatalog=noop,destroyVoiceCatalog=noop,selectTab=noop,renderTabs=noop;
{_lifecycle_sources(page)}
const log={{mounts:[],destroys:0}};let ctx=null;
const a=registerSettingsSection({{id:'alpha',category:'voice_audio',label:'Alpha',save:'footer',
  mount(host,context){{ctx=context;log.mounts.push([host.dataset.section,context.section,context.isCurrent()]);host.innerHTML='alpha'}},
  destroy(){{log.destroys+=1}}}});
registerSettingsSection({{id:'broken',category:'voice_audio',label:'Cassée',save:'self',mount(){{throw new Error('plus de micro')}}}});
registerSettingsSection({{id:'late',category:'voice_audio',label:'Tardive',save:'readonly',mount(){{return Promise.reject(new Error('réseau'))}}}});
const refused=registerSettingsSection({{id:'seventh',category:'nowhere',label:'7',save:'self',mount:noop}});
(async()=>{{
  SET.section='alpha';mountRegisteredSection(SET.renderRevision);
  const footer=modalSave.style.display,first=ctx.isCurrent(),data=ctx.data(),draft=ctx.draft();ctx.markDirty();
  cleanupSettingsSurface();const afterLeave=ctx.isCurrent();cleanupSettingsSurface();
  SET.section='broken';SET.renderRevision++;mountRegisteredSection(SET.renderRevision);
  const brokenHtml=modalContent.children[0].innerHTML,selfFooter=modalSave.style.display;
  cleanupSettingsSurface();
  SET.section='late';SET.renderRevision++;mountRegisteredSection(SET.renderRevision);await new Promise(r=>setTimeout(r,0));
  const lateHtml=modalContent.children[0].innerHTML;
  SET.section=null;mountRegisteredSection(++SET.renderRevision);
  out({{registered:!!a,refused,footer,selfFooter,first,afterLeave,data,draft,dirty:SET.dirty,said,log,brokenHtml,lateHtml,
    empty:modalContent.innerHTML,rejected:SETTINGS_REJECTED,errors}});
}})();""")
    assert out["registered"] is True and out["refused"] is None
    assert out["log"]["mounts"] == [["alpha", "alpha", True]]
    assert out["footer"] == "" and out["selfFooter"] == "none"  # le bouton Enregistrer seulement pour `save: 'footer'`
    assert out["first"] is True and out["afterLeave"] is False  # une réponse tardive n'écrit plus rien
    assert out["log"]["destroys"] == 1  # une fois, même si le nettoyage est rappelé
    assert out["data"] == {"v": 1} and out["draft"] == {"d": 1} and out["dirty"] is True
    assert out["said"] == [["Modifications non enregistrées.", ""]]
    for html, text in ((out["brokenHtml"], "plus de micro"), (out["lateHtml"], "réseau")):
        assert 'role="alert"' in html and text in html and "<code>settings_section_mount_failed</code>" in html
    assert out["empty"] == '<div class="set-empty">Rien à régler ici pour le moment.</div>'
    assert [r["code"] for r in out["rejected"]] == ["settings_category_unknown"]
    assert out["rejected"][0]["category"] == "advanced_diagnostics"  # montré dans Avancé, jamais perdu
    codes = [e[0] for e in out["errors"]]
    assert codes == ["settings_section_rejected", "settings_section_mount_failed", "settings_section_mount_failed"]
    assert {e[1]["section"] for e in out["errors"][1:]} == {"broken", "late"}


def test_navigation_is_drawn_from_the_registry_and_cycles_categories():
    page = HTML.read_text(encoding="utf-8")
    script = page[page.index("<script>") :]
    # Aucun libellé de catégorie écrit dans la page : ils viennent du registre.
    for label in ("Voix & audio", "Agents & modèles", "Mémoire & connaissances", "Interface & interactions", "Avancé & diagnostic"):
        assert label not in script, label
    render = slice_(page, "function renderTabs(){", "function settingsListKeys(")
    assert "rail.innerHTML=nav.categories.map(" in render and "settingsNavigation()" in render
    keys = page[page.index("if(id==='ui_tab_next'||id==='ui_tab_prev'){") :][:600]
    assert "JarvisSettingsRegistry.cycleCategory(SET.category," in keys and "TABS.findIndex" not in keys
    assert "function settingsTabs(){" in page and "registry.CATEGORIES.map(" in page


async def test_served_page_inlines_the_primitives_after_the_registry(tmp_path: Path):
    page = HTML.read_text(encoding="utf-8")
    assert page.count(SETTINGS_UI_SCRIPT_MARKER) == 1
    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text
    assert SETTINGS_UI_SCRIPT_MARKER not in served
    assert served.index("root.JarvisSettingsRegistry=api") < served.index("root.JarvisSettingsUI=api") < served.index("\nconst SET={")
    for forbidden in ("fetch(", "localStorage", "sessionStorage", "XMLHttpRequest", "document.", "indexedDB"):
        assert forbidden not in UI.read_text(encoding="utf-8"), forbidden
