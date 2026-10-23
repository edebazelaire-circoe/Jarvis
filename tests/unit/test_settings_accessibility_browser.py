"""Finitions d'accessibilité et de mise en page des Réglages, dans un vrai Chrome sans tête (passe de finitions avant
la Slice 10 de jarvis-settings-ui-reorganization).

Contrat : `docs/settings/settings-shell.md` (§ 3 liens internes, § 5 accessibilité). Un VRAI Control Center isolé (fixture
`served` de `test_wake_word_settings_browser.py` : runtime temporaire, port libre) sert la page ; le harnais CDP envoie de
vrais clics et de vraies frappes. Ce que ce fichier prouve :

- un lien interne suivi à la SOURIS pose le focus sur sa cible, jamais sur `body`, et son contour se voit
  (`data-settings-landed` : `:focus-visible` ne s'applique pas après un clic) ; un champ hérité garde le contour du shell ;
- « Enregistrer la mémoire » garde le focus pendant et après l'envoi ; changer de catégorie depuis le contenu (Ctrl+→)
  laisse le focus dans le shell ; le lien vers Modèles des sous-agents garde le focus quand les instances arrivent ;
- Connexions : les deux régions vivantes sont les mêmes nœuds d'une action à l'autre, seul leur texte change ;
- mise en page : la ligne de Labs ne commence pas par un filet, « Arrêter » ne s'étire pas, les filtres du catalogue ne
  sont plus coupés à 1366×768 ni à 1093×614, la liste d'Avancé ne défile pas à 1093×614 ;
- états désactivés et lecture seule à 4,5:1 au moins ; mouvement réduit et couleurs forcées de base.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, type_in, wait, open_settings  # noqa: F401

OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), *open_settings(),
    wait("!!document.getElementById('voiceSection_conversation')"),
]

#: Où est le focus, et son contour se voit-il ?
FOCUS = """(()=>{const e=document.activeElement,cs=e&&getComputedStyle(e);
  return {id:e&&e.id||null,tag:e&&e.tagName,inShell:!!e&&document.getElementById('settingsShell').contains(e),
    landed:!!e&&e.hasAttribute('data-settings-landed'),
    outline:!!cs&&cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>=2,
    section:SET.section,key:e&&(e.dataset.shortcut||e.dataset.memSave!==undefined&&'mem_save'||e.dataset.sarOpenModels!==undefined&&'models'||null)}})()"""


async def test_internal_links_followed_with_the_mouse_land_with_a_visible_outline(served):
    # Bloc du mot d'éveil d'une version étrangère : l'état figé montre le lien « Voir le diagnostic » de façon stable
    # (même préparation que `test_wake_word_diagnostic_link_keeps_its_part_in_view_after_voice_fills`).
    served.settings_file.write_text(json.dumps({"wake_word": {"schema_version": 7, "enabled": True, "futur": 1}}),
                                    encoding="utf-8")
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        # Voix › Tours & interruptions › « Modifier dans … » : la touche de Raccourcis.
        click("#modalTabs [data-section=turns_interruptions]"),
        wait("!!document.querySelector('#modalContent [data-voice-open]')", 8000),
        click("#modalContent [data-voice-open]"),
        wait("SET.section==='shortcuts'&&document.activeElement!==document.body"),
        eval_(FOCUS, "shortcut"),
        # Mot d'éveil › « Voir le diagnostic » : la partie du diagnostic (une section, amenée en haut).
        eval_("selectTab('wake_word');true"),
        wait("!!document.querySelector('[data-ww-open-diagnostics]')", 10000),
        click("[data-ww-open-diagnostics]"),
        wait("SET.section==='diagnostics'&&document.activeElement&&document.activeElement.id==='diagnostic_wake_word'", 8000),
        eval_(FOCUS, "diagnostic"),
        # Rappel › « Voir le diagnostic mémoire ».
        eval_("selectTab('recall');true"),
        wait("!!document.querySelector('#modalContent [data-mem-diagnostics]')", 8000),
        click("#modalContent [data-mem-diagnostics]"),
        wait("document.activeElement&&document.activeElement.id==='diagnostic_memory'", 8000),
        eval_(FOCUS, "memory"),
        # Mémoire › « Connexions » (sans cible) : l'entrée ouverte de la liste des sections.
        eval_("selectTab('knowledge_sources');true"),
        wait("!!document.querySelector('#modalContent [data-mem-open]')", 8000),
        click("#modalContent [data-mem-open]"),
        wait("SET.section==='providers'"),
        eval_(FOCUS, "entry"),
        # Agent principal : le champ du modèle (`.field input:focus{outline:none}` hérité) garde le contour du shell.
        eval_("selectTab('main_agent');true"),
        wait("!!document.getElementById('f_cli_model')", 8000),
        click("#f_cli_model"),
        eval_(FOCUS, "field"),
    ]}])
    step = out["steps"][0]
    shortcut, diagnostic, memory, entry, field = (got(step, i) for i in ("shortcut", "diagnostic", "memory", "entry", "field"))
    assert shortcut["key"] == "wake_toggle" and shortcut["landed"] and shortcut["outline"], shortcut
    assert diagnostic["landed"] and diagnostic["outline"] and diagnostic["inShell"], diagnostic
    assert memory["id"] == "diagnostic_memory" and memory["landed"] and memory["outline"], memory
    assert entry["section"] == "providers" and entry["tag"] == "BUTTON" and entry["landed"] and entry["outline"], entry
    assert field["id"] == "f_cli_model" and field["outline"], field
    assert out["console"] == [], out["console"]


EDIT = """(()=>{const i=document.getElementById('mem_recall_max_items');i.value='4';i.dispatchEvent(new Event('change',{bubbles:true}));
  return document.querySelector('[data-mem-save]').getAttribute('aria-disabled')})()"""
#: Le POST mémoire est retenu 600 ms : on lit le focus PENDANT l'envoi, puis après.
SLOW_SAVE = """(()=>{const base=window.fetch;window.fetch=(url,init)=>{const p=base(url,init);
  return init&&init.method==='POST'&&String(url).startsWith('/api/settings')?new Promise(r=>setTimeout(()=>r(p),600)):p};return true})()"""


async def test_saving_memory_keeps_the_focus_on_its_button_during_and_after(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        click("#settingsCategories [data-category=memory_knowledge]"),
        wait("!!document.getElementById('mem_recall_max_items')", 8000),
        eval_(EDIT, "dirty"), eval_(SLOW_SAVE),
        eval_("document.querySelector('[data-mem-save]').focus();true"),
        key("Enter"),
        wait("/Enregistrement…/.test(document.querySelector('[data-mem-save]').textContent)"),
        eval_(FOCUS, "during"),
        wait("/Réglages mémoire enregistrés/.test(document.getElementById('memSection_recall').textContent)"),
        eval_(FOCUS, "after"),
        eval_("document.querySelector('[data-mem-save]').getAttribute('aria-disabled')", "clean"),
        # Clic sur un bouton sans effet (rien à enregistrer) : aucune requête.
        click("[data-mem-reset]"),
    ]}])
    step = out["steps"][0]
    assert got(step, "dirty") is None  # actif dès qu'un champ change
    assert got(step, "during")["key"] == "mem_save", got(step, "during")
    assert got(step, "after")["key"] == "mem_save", got(step, "after")
    assert got(step, "clean") == "true"
    posts = [r for r in out["requests"] if r["method"] == "POST"]
    assert len(posts) == 1, posts
    assert out["console"] == [], out["console"]


async def test_changing_category_from_the_content_keeps_the_focus_in_the_shell(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        click("#settingsCategories [data-category=interface_interactions]"),
        wait("!!document.querySelector('#modalContent [data-shortcut]')||!!document.querySelector('#modalContent button')", 8000),
        eval_("document.querySelector('#modalContent button').focus();document.activeElement.closest('#modalContent')!==null", "in_content"),
        key("ArrowRight", ctrl=True),
        wait("SET.category==='connections'"),
        eval_(FOCUS, "after"),
    ]}])
    step = out["steps"][0]
    assert got(step, "in_content") is True
    after = got(step, "after")
    assert after["inShell"] and after["tag"] == "BUTTON" and after["section"] == "providers", after
    assert after["landed"] and after["outline"], after  # un saut non choisi : son arrivée se voit
    assert out["console"] == [], out["console"]


#: Les instances des sous-agents arrivent 1,2 s après les rôles : le rendu qu'elles déclenchent remplace la liste.
SLOW_TASKS = """(()=>{const base=window.fetch;window.fetch=(url,init)=>{const p=base(url,init);
  return /\\/api\\/(agent\\/)?tasks|subagent-instances|\\/tasks/.test(String(url))?new Promise(r=>setTimeout(()=>r(p),1200)):p};return true})()"""


async def test_the_models_link_keeps_its_focus_when_the_instances_arrive(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_(SLOW_TASKS),
        eval_("selectTab('subagents');true"),
        wait("!!document.querySelector('#modalContent [data-sar-open-models]')", 8000),
        eval_("document.querySelector('#modalContent [data-sar-open-models]').focus();!!document.querySelector('#modalContent .sar-instances')", "rendered"),
        wait("!/Lecture des instances/.test(document.getElementById('modalContent').textContent)", 8000),
        eval_(FOCUS, "after"),
    ]}])
    after = got(out["steps"][0], "after")
    assert after["key"] == "models" and after["inShell"], after
    assert out["console"] == [], out["console"]


#: Une action réelle (une clé factice ajoutée au magasin du runtime temporaire) : les régions vivantes gardent leur
#: nœud, seul leur texte change ; le focus arrive sur la nouvelle clé, contour visible.
LIVE_BEFORE = """(()=>{const s=document.getElementById('connectionsStatus'),e=document.getElementById('connectionsError');
  s.__mark='status';e.__mark='error';return [s.getAttribute('role'),e.getAttribute('role')]})()"""
LIVE_AFTER = """(()=>{const s=document.getElementById('connectionsStatus'),e=document.getElementById('connectionsError');
  return {same:s.__mark==='status'&&e.__mark==='error',status:s.textContent}})()"""


async def test_connections_live_regions_are_stable_nodes(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        click("#settingsCategories [data-category=connections]"),
        wait("!!document.querySelector('form[data-conn-add=openai]')", 8000),
        eval_(LIVE_BEFORE, "roles"),
        eval_("document.querySelector('#connection_openai details.conn-add').open=true;true"),
        type_in("#conn_openai_name", "Essai"),
        type_in("#conn_openai_value", "sk-test-FAKE-finitions-0000"),
        click("form[data-conn-add=openai] button[type=submit]"),
        wait("/ajoutée/.test(document.getElementById('connectionsStatus').textContent)", 8000),
        eval_(LIVE_AFTER, "after"),
        eval_(FOCUS, "focus"),
    ]}])
    step = out["steps"][0]
    assert got(step, "roles") == ["status", "alert"]
    after = got(step, "after")
    assert after["same"] is True and "Essai" in after["status"], after
    focus = got(step, "focus")
    assert focus["landed"] and focus["outline"] and focus["inShell"], focus
    assert out["console"] == [], out["console"]


LAYOUT = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),out={};
  selectTab('architecture_compat');await pause(600);
  const list=document.getElementById('modalTabs'),lr=list.getBoundingClientRect();
  const groups=[...list.querySelectorAll('.set-group')].map(g=>({id:g.dataset.settingsGroup,top:Math.round(g.getBoundingClientRect().top),
    left:g.getBoundingClientRect().left-lr.left}));
  const firstTop=Math.min(...groups.map(g=>g.top));
  out.list={scroll:list.scrollWidth-list.clientWidth,
    lineStarts:groups.filter((g,i)=>i===0||g.top!==groups[i-1].top).map(g=>[g.id,g.left<0]),
    inner:groups.filter((g,i)=>i>0&&g.top===groups[i-1].top).map(g=>[g.id,g.left>=0]),
    hidden:[...list.querySelectorAll('[role=tab]')].filter(b=>b.getBoundingClientRect().right>lr.right+0.5).map(b=>b.dataset.section)};
  selectTab('subagent_models');await pause(3000);
  const f=document.querySelector('#modalContent .catalog-filters');
  out.filters=f?{scroll:f.scrollWidth-f.clientWidth,cut:[...f.children].filter(x=>x.getBoundingClientRect().right>f.getBoundingClientRect().right+1).length,
    count:f.children.length}:null;
  selectTab('barehands_lab');await pause(800);
  const stop=document.getElementById('barehandsRecordStop');out.stop=stop?stop.getBoundingClientRect().width:null;
  const body=document.getElementById('modalContent');out.content=body.scrollWidth-body.clientWidth;
  return out})()"""


@pytest.mark.parametrize(("width", "height"), [(1366, 768), (1093, 614)])
async def test_labs_rule_record_buttons_catalog_filters_and_advanced_list(served, width, height):
    """1093×614 : 1366×768 à 125 % de zoom (QA Slices 04, 06 et 08)."""
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    layout = got(out["steps"][0], "layout")
    lst = layout["list"]
    assert lst["scroll"] <= 0 and lst["hidden"] == [], lst
    # Labs passe à la ligne à ces largeurs : le groupe qui ouvre une ligne a son filet coupé, les autres le gardent.
    assert ["labs", True] in lst["lineStarts"] and all(cut for _, cut in lst["lineStarts"]), lst
    assert lst["inner"] and all(shown for _, shown in lst["inner"]), lst
    filters = layout["filters"]
    assert filters and filters["count"] > 0 and filters["cut"] == 0 and filters["scroll"] <= 0, filters
    assert layout["stop"] is not None and layout["stop"] < 200, layout["stop"]
    assert layout["content"] <= 1, layout
    assert out["console"] == [], out["console"]


CONTRAST_JS = r"""
const parse=c=>{if(!c)return null;let m=c.match(/^rgba?\(([^)]+)\)/);if(m){const p=m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}}
  m=c.match(/^color\(srgb ([^)]+)\)/);if(m){const p=m[1].split(/[ \/]+/).filter(Boolean).map(Number);return {r:p[0]*255,g:p[1]*255,b:p[2]*255,a:p.length>3?p[3]:1}}return null};
const over=(f,b)=>({r:f.r*f.a+b.r*(1-f.a),g:f.g*f.a+b.g*(1-f.a),b:f.b*f.a+b.b*(1-f.a),a:1});
const mix=(x,y,o)=>({r:x.r*o+y.r*(1-o),g:x.g*o+y.g*(1-o),b:x.b*o+y.b*(1-o),a:1});
const lum=c=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b)};
const ratio=(x,y)=>{const a=lum(x),b=lum(y);return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05)};
/* Fond sous le voile des Réglages (page sombre) ; chaque fond d'ancêtre est composé par-dessus. */
const BASE={r:4,g:9,b:13,a:1};
function bgOf(el){const chain=[];for(let e=el;e&&e.nodeType===1;e=e.parentElement)chain.push(e);let bg=BASE;
  for(const e of chain.reverse()){const c=parse(getComputedStyle(e).backgroundColor);if(c&&c.a>0)bg=over(c,bg)}return bg}
function opacityOf(el){let o=1;for(let e=el;e&&e.nodeType===1;e=e.parentElement)o*=Number(getComputedStyle(e).opacity||1);return o}
function measure(el){const parent=bgOf(el.parentElement),own=parse(getComputedStyle(el).backgroundColor);const bgEl=own&&own.a>0?over(own,parent):parent;
  const fg=parse(getComputedStyle(el).color)||{r:255,g:255,b:255,a:1};const text=over(fg,bgEl);const o=opacityOf(el);
  return ratio(mix(text,parent,o),mix(bgEl,parent,o))}
"""
SWEEP = """(async()=>{%s
  const pause=ms=>new Promise(r=>setTimeout(r,ms)),R=window.JarvisSettingsRegistry,out=[];
  for(const c of R.CATEGORY_IDS){for(const s of R.page.sections(c)){selectTab(s.id);await pause(s.id==='diagnostics'?1500:700);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(250);
    const els=[...document.querySelectorAll('#modalContent :disabled, #modalContent [aria-disabled=true], #modalContent output, #modalContent [readonly], #modalContent .routing-off')]
      .filter(e=>e.getClientRects().length&&(e.textContent.trim()||e.tagName==='INPUT'));
    for(const e of els)out.push({section:s.id,tag:e.tagName,text:(e.textContent||e.type||'').trim().slice(0,30),ratio:Math.round(measure(e)*100)/100})}}
  return out})()""" % CONTRAST_JS


async def test_disabled_and_read_only_states_stay_readable(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [*OPEN, eval_(SWEEP, "sweep")]}])
    rows = got(out["steps"][0], "sweep")
    assert len(rows) >= 10, rows  # désactivés et lectures seules vus dans plusieurs sections
    low = [r for r in rows if r["ratio"] < 4.5]
    assert low == [], low


#: Un profil de routage éteint (Avancé › Runtime & CLI › Configuration avancée), absent du banc d'essai au repos : ses
#: aides, ses commandes désactivées et son bloc, mesurés avec toutes les opacités des ancêtres (QA Slice 10, N2/Q8).
ROUTING_OFF = """(async()=>{%s
  const pause=ms=>new Promise(r=>setTimeout(r,ms));
  const block=document.querySelector('#modalContent .routing-off');
  const els=[...block.querySelectorAll('.hint, :disabled, label, h3')].filter(e=>e.getClientRects().length&&(e.textContent.trim()||e.tagName==='INPUT'||e.tagName==='SELECT'||e.tagName==='BUTTON'));
  return {count:els.length,block:Number(getComputedStyle(block).opacity),
    rows:els.map(e=>({tag:e.tagName,cls:e.className,text:(e.textContent||e.type||'').trim().slice(0,30),opacity:Math.round(opacityOf(e)*100)/100,
      ratio:Math.round(measure(e)*100)/100}))}})()""" % CONTRAST_JS


async def test_a_disabled_routing_profile_stays_readable_and_greyed_once(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        eval_("selectTab('runtime_cli');true"),
        wait("!!document.querySelector('#routingAdvanced summary')", 8000),
        click("#routingAdvanced summary"),
        wait("!!document.querySelector('#modalContent [data-routing-profile-enabled]:checked')", 10000),
        click("#modalContent [data-routing-profile-enabled]:checked"),
        wait("!!document.querySelector('#modalContent .routing-off')", 5000),
        eval_(ROUTING_OFF, "off"),
    ]}])
    off = got(out["steps"][0], "off")
    hints = [r for r in off["rows"] if "hint" in r["cls"]]
    assert off["count"] >= 2 and hints, off
    low = [r for r in off["rows"] if r["ratio"] < 4.5]
    assert low == [], low
    # Grisé une seule fois : rien sous 0,7 d'opacité cumulée, les aides à pleine opacité.
    assert all(r["opacity"] >= 0.7 for r in off["rows"]), off["rows"]
    assert all(r["opacity"] == 1 for r in hints), hints
    assert out["console"] == [], out["console"]


MOTION = """(()=>{const cat=getComputedStyle(document.querySelector('.set-cat'));
  const probe=document.createElement('div');probe.style.cssText='animation:set-enter 2s infinite;transition:opacity 3s';
  document.getElementById('modalContent').append(probe);const p=getComputedStyle(probe);
  const out={cat:cat.transitionDuration,anim:p.animationDuration,iterations:p.animationIterationCount,transition:p.transitionDuration};probe.remove();return out})()"""
FORCED = """(()=>{const ref=document.createElement('span');ref.style.cssText='color:Highlight;background:GrayText';document.body.append(ref);
  const hl=getComputedStyle(ref).color,gray=getComputedStyle(ref).backgroundColor;ref.remove();
  const off=document.querySelector('#modalContent :disabled, #modalContent [aria-disabled=true]'),cs=off&&getComputedStyle(off);
  const f=getComputedStyle(document.activeElement);
  return {focus:f.outlineColor===hl&&f.outlineStyle!=='none',disabled:!!cs&&cs.color===gray&&cs.opacity==='1'}})()"""


async def test_reduced_motion_and_forced_colors(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "reducedMotion": True, "actions": [*OPEN, eval_(MOTION, "motion")]},
        {"width": 1440, "height": 900, "forcedColors": True, "actions": [
            *OPEN, eval_("selectTab('recall');true"),
            wait("!!document.querySelector('#modalContent [data-mem-save][aria-disabled=true]')", 8000),
            eval_("document.querySelector('#settingsCategories [aria-selected=true]').focus();true"), key("ArrowDown"),
            eval_(FORCED, "forced")]},
    ])
    motion = got(out["steps"][0], "motion")
    for name in ("cat", "anim", "transition"):
        assert float(motion[name].rstrip("s")) <= 0.001, motion
    assert motion["iterations"] == "1", motion
    forced = got(out["steps"][1], "forced")
    assert forced == {"focus": True, "disabled": True}, forced


#: Les deux bouts réellement atteignables au clavier du shell, calculés ici indépendamment du produit : un descendant
#: d'un `<details>` fermé ne l'est pas (son résumé l'est), alors que Chrome lui donne des boîtes (`getClientRects`), ce
#: que le piège de Tab comptait (QA Slice 10, B1). Chaque bout est marqué pour être reconnu après la frappe.
ENDS = """((which)=>{const ov=document.getElementById('overlay');
  const shut=el=>{for(let d=el.closest('details');d;d=d.parentElement&&d.parentElement.closest('details'))
    if(!d.open&&!(el.tagName==='SUMMARY'&&el.parentElement===d))return true;return false};
  const all=[...ov.querySelectorAll('button,a[href],input,select,textarea,summary,[tabindex]')]
    .filter(el=>!el.disabled&&el.tabIndex>=0&&el.getClientRects().length>0&&!shut(el));
  all.forEach(el=>{delete el.__end});all[0].__end='first';all[all.length-1].__end='last';
  const hidden=[...ov.querySelectorAll('details:not([open]) button')].filter(el=>el.getClientRects().length>0).length;
  const el=which==='first'?all[0]:all[all.length-1];el.focus();
  const shell=document.getElementById('settingsShell');window.__escapes=[];
  if(!window.__escapeWatch){window.__escapeWatch=true;document.addEventListener('focusout',e=>{
    if(!e.relatedTarget||!shell.contains(e.relatedTarget))window.__escapes.push(e.relatedTarget?e.relatedTarget.id||e.relatedTarget.tagName:'body')},true)}
  return {tag:el.tagName,hidden,focused:document.activeElement===el}})"""
#: Où est le focus après la frappe, et est-il passé hors du shell en route (`body` ou la page derrière, même un instant) ?
WHERE = """(()=>{const e=document.activeElement;
  return {end:e&&e.__end||null,tag:e&&e.tagName,inShell:!!e&&document.getElementById('settingsShell').contains(e),
    escapes:window.__escapes||[]}})()"""

#: Contenu au repos : aucun nœud ajouté ni retiré pendant 600 ms (une lecture tardive, comme les instances des
#: sous-agents, redessinerait la liste après le marquage des bouts).
QUIET = """new Promise(r=>{let t;const o=new MutationObserver(()=>{clearTimeout(t);t=setTimeout(done,600)});
  const done=()=>{o.disconnect();r(true)};o.observe(document.getElementById('modalContent'),{subtree:true,childList:true});
  t=setTimeout(done,600)})"""

#: Sections dont le dernier contrôle visible précède un `<details>` fermé qui cache des boutons : Connexions ›
#: Fournisseurs (« Ajouter une clé ») et Agents & modèles › Rôles des sous-agents (« Afficher et modifier les
#: instructions » ; rôles chargés).
TRAP_SECTIONS = [("providers", "!!document.querySelector('#modalContent summary')"),
                 ("subagents", "!!document.querySelector('#modalContent details summary')"
                  "&&!/Lecture des instances/.test(document.getElementById('modalContent').textContent)")]


@pytest.mark.parametrize(("section", "ready"), TRAP_SECTIONS)
async def test_tab_from_the_last_reachable_control_stays_in_the_shell(served, section, ready):
    """QA Slice 10, B1 : vraie frappe Tab depuis le vrai dernier contrôle → le premier du shell ; vraie frappe Maj+Tab
    depuis le premier → le vrai dernier, jamais un bouton caché d'un `<details>` fermé ni la page derrière."""
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        eval_(f"selectTab('{section}');true"),
        wait(ready, 10000),
        eval_(QUIET),
        eval_(f"({ENDS})('last')", "last"),
        key("Tab"),
        eval_(WHERE, "after_tab"),
        eval_(f"({ENDS})('first')", "first"),
        key("Tab", shift=True),
        eval_(WHERE, "after_shift_tab"),
    ]}])
    step = out["steps"][0]
    last = got(step, "last")
    assert last["focused"] and last["hidden"] > 0, last  # le piège existait bien : des boutons cachés suivent
    after_tab, after_shift_tab = got(step, "after_tab"), got(step, "after_shift_tab")
    assert after_tab == {"end": "first", "tag": got(step, "first")["tag"], "inShell": True, "escapes": []}, after_tab
    assert after_shift_tab == {"end": "last", "tag": last["tag"], "inShell": True, "escapes": []}, after_shift_tab
    assert out["console"] == [], out["console"]


#: Une liste de focusables qui se tromperait encore (un bouton caché d'un `<details>` fermé pris pour le dernier,
#: l'erreur d'origine) : le dernier recours du piège ramène quand même le focus dans le shell.
WRONG_LIST = """(()=>{const real=settingsReachable;const ghost=document.querySelector('#overlay details:not([open]) button');
  window.settingsReachable=root=>{const all=real(root);return ghost?[...all,ghost]:all};return !!ghost})()"""


async def test_the_trap_keeps_the_focus_in_the_shell_when_its_list_is_wrong(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        eval_("selectTab('providers');true"),
        wait("!!document.querySelector('#modalContent summary')", 10000),
        eval_(QUIET),
        eval_(WRONG_LIST, "ghost"),
        eval_("(" + ENDS + ")('last')", "last"),
        key("Tab"),
        wait("document.getElementById('settingsShell').contains(document.activeElement)", 2000),
        eval_(WHERE, "after"),
    ]}])
    step = out["steps"][0]
    assert got(step, "ghost") is True
    assert got(step, "after")["inShell"] is True and got(step, "after")["end"] == "first", got(step, "after")


#: Le conteneur du catalogue comparatif défile horizontalement quand sa table est plus large que la colonne (QA Slice
#: 10, N3) : il est atteignable au clavier (Tab depuis le contrôle qui le précède), nommé, et son contour se voit.
CATALOG_WRAP = """(()=>{const w=document.querySelector('#modalContent .catalog-table-wrap'),ends=settingsReachable(document.getElementById('overlay'));
  const i=ends.indexOf(w);if(i>0)ends[i-1].focus();
  return {index:i,role:w.getAttribute('role'),name:w.getAttribute('aria-label'),tabindex:w.getAttribute('tabindex'),
    scroll:w.scrollWidth-w.clientWidth}})()"""
FOCUSED_WRAP = """(()=>{const e=document.activeElement,cs=getComputedStyle(e);const before=e.scrollLeft;e.scrollLeft+=60;
  return {wrap:e.classList.contains('catalog-table-wrap'),outline:cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>=2,
    moved:e.scrollWidth>e.clientWidth?e.scrollLeft>before:null}})()"""


async def test_the_scrolling_catalog_table_is_reachable_and_named(served):
    out = await drive(served.url, [{"width": 1093, "height": 614, "actions": [
        *OPEN,
        eval_("selectTab('subagent_models');true"),
        wait("!!document.querySelector('#modalContent .catalog-table-wrap')", 15000),
        eval_(CATALOG_WRAP, "wrap"),
        key("Tab"),
        eval_(FOCUSED_WRAP, "focused"),
    ]}])
    step = out["steps"][0]
    wrap = got(step, "wrap")
    assert wrap["index"] > 0 and wrap["role"] == "region" and wrap["tabindex"] == "0", wrap
    assert wrap["name"] and wrap["name"].startswith("Catalogue de modèles"), wrap
    focused = got(step, "focused")
    assert focused["wrap"] and focused["outline"], focused
    assert focused["moved"] in (True, None), focused


#: Marque d'arrivée (`data-settings-landed`) retirée quand le focus repart (mutation Q3) : sinon un ancien saut garderait
#: son contour forcé au prochain focus, même à la souris.
LANDED = """(()=>{const t=document.activeElement;window.__landed=t;return t.hasAttribute('data-settings-landed')})()"""


async def test_the_landing_mark_is_removed_when_the_focus_leaves(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        click("#modalTabs [data-section=turns_interruptions]"),
        wait("!!document.querySelector('#modalContent [data-voice-open]')", 8000),
        click("#modalContent [data-voice-open]"),
        wait("SET.section==='shortcuts'&&document.activeElement!==document.body"),
        eval_(LANDED, "landed"),
        key("Tab"),
        eval_("({left:document.activeElement!==window.__landed,mark:window.__landed.hasAttribute('data-settings-landed')})", "after"),
    ]}])
    step = out["steps"][0]
    assert got(step, "landed") is True
    assert got(step, "after") == {"left": True, "mark": False}, got(step, "after")


#: Position d'arrivée (mutation Q6) : une partie (section, région, titre) vient en HAUT de la zone qui défile ; une
#: petite cible défile juste assez (`block:'nearest'`).
ARRIVAL = """(()=>{const t=document.activeElement,c=document.getElementById('modalContent'),box=c.getBoundingClientRect(),r=t.getBoundingClientRect();
  return {id:t.id,top:Math.round(r.top-box.top),height:Math.round(r.height),view:Math.round(box.height),scrolled:c.scrollTop}})()"""


async def test_a_part_reached_by_a_link_comes_to_the_top_of_the_content(served):
    out = await drive(served.url, [{"width": 1366, "height": 768, "actions": [
        *OPEN,
        eval_("selectTab('recall');true"),
        wait("!!document.querySelector('#modalContent [data-mem-diagnostics]')", 8000),
        click("#modalContent [data-mem-diagnostics]"),
        wait("document.activeElement&&document.activeElement.id==='diagnostic_memory'", 8000),
        eval_(ARRIVAL, "memory"),
    ]}])
    memory = got(out["steps"][0], "memory")
    assert memory["scrolled"] > 0, memory
    assert 0 <= memory["top"] <= 40, memory


#: Erreur de Connexions collée en haut de la zone qui défile (mutation Q7) : un refus reste lu quand la liste est
#: longue et que l'on a défilé plus bas.
REFUSE_POST = """(()=>{const real=window.fetch;window.fetch=(u,o)=>o&&o.method&&o.method!=='GET'
  ?Promise.resolve(new Response(JSON.stringify({error:'Refus du banc d essai.',detail:'Refus du banc d essai.'}),{status:400,headers:{'Content-Type':'application/json'}}))
  :real(u,o);return true})()"""
STUCK = """(async()=>{const c=document.getElementById('modalContent');c.scrollTop=c.scrollHeight;await new Promise(r=>setTimeout(r,200));
  const e=document.getElementById('connectionsError'),box=c.getBoundingClientRect(),r=e.getBoundingClientRect();
  return {text:e.textContent,scrolled:c.scrollTop,top:Math.round(r.top-box.top),bottom:Math.round(box.bottom-r.bottom),
    position:getComputedStyle(e).position}})()"""


async def test_a_connections_error_stays_at_the_top_while_scrolling(served):
    out = await drive(served.url, [{"width": 1366, "height": 768, "actions": [
        *OPEN,
        click("#settingsCategories [data-category=connections]"),
        wait("!!document.querySelector('form[data-conn-add=openai]')", 8000),
        eval_(REFUSE_POST),
        eval_("document.querySelector('#connection_openai details.conn-add').open=true;true"),
        type_in("#conn_openai_name", "Essai"),
        type_in("#conn_openai_value", "sk-test-FAKE-finitions-0000"),
        click("form[data-conn-add=openai] button[type=submit]"),
        wait("!!document.getElementById('connectionsError').textContent.trim()", 8000),
        eval_(STUCK, "stuck"),
    ]}])
    stuck = got(out["steps"][0], "stuck")
    assert stuck["text"] and stuck["scrolled"] > 0, stuck
    assert stuck["position"] == "sticky" and -1 <= stuck["top"] <= 40 and stuck["bottom"] > 0, stuck
