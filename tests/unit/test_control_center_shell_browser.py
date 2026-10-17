"""La coque du Control Center, mesurée dans Chrome : deux thèmes, quatre tailles,
puis la matrice d'intégration de la Slice 09 (voir plus bas).

Contrat : `docs/control-center-shell.md` (Slice 01 de
jarvis-board-orbital-ui-workspace-rail). `test_control_center_shell_layers.py`
lit les feuilles ; ce fichier relève ce que la cascade **produit** : la page
servie, composée comme `ControlCenter.index` la compose, chargée sans tête à
1440 × 900, 1280 × 720, 900 × 600 et 600 × 800, au thème par défaut
(`circuit-board`) puis au thème Cosmos.

Ce qu'il épingle :

- une seule géométrie : chaque commande est au même endroit et au même rang
  dans les deux thèmes ;
- les commandes que la scène mesure (`JarvisShell.CONTROL_SELECTOR`) comptent
  `#chatTab`, `#interactionModeHud` et `#presentationRail`, et aucune n'en
  recouvre une autre ;
- un panneau latéral ouvert reste sous le lanceur et au-dessus de l'onglet
  Chat ;
- aucune largeur ne fait défiler la page horizontalement.

Harnais : `_interaction_mode_browser.mjs` (CDP, rectangles calculés). Se saute
proprement sans Chrome ni node.

**Slice 09 (intégration, responsive, accessibilité).** La seconde moitié du
fichier rejoue la matrice de `docs/04-testing-and-quality.md` du handoff
(15 états × 2 thèmes, une capture par état), les parcours clavier seul et
souris seule, le mouvement réduit, les couleurs forcées, axe-core
(`JARVIS_AXE_JS`), le zoom 200 % et les fenêtres étroite (700 px) et basse
(560 px), sur la page servie avec le double `fetch` de
`_status_centre_browser.mjs` (statut, alertes, captures, scène, rail, Boards) ;
l'état Studio / Variantes + rail passe par le vrai Core isolé de
`tests/fakes/explorer_browser.py`. Chaque état audite la même chose : aucune
commande sur une autre, aucune commande couverte en son centre, aucun bouton
sans nom, aucun texte coupé sans son texte entier, aucune commande hors de
l'écran, pas de défilement horizontal, la surface de l'état entière et au
premier plan. Captures : `JARVIS_S09_EVIDENCE_DIR=<dossier>` (sinon `tmp_path`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_interaction_mode_hud_browser import HARNESS, _chrome, _served_page

VIEWPORTS = ((1440, 900), (1280, 720), (900, 600), (600, 800))
THEMES = ("circuit-board", "cosmos")

#: Monte ce que la page ne montre qu'avec des données : des pastilles, un
#: Board nommé, le rail des présentations (son hôte réel, construit par son
#: module, posé dans la zone de droite depuis la Slice 07 ; l'hôte de secours
#: n'existe que si le module manque). Puis applique le thème.
SETUP = r"""(()=>{
  const theme=%s;
  if(window.JarvisThemeAPI)window.JarvisThemeAPI.activate(theme,{persist:false});
  const pills=document.getElementById('bgPills');
  pills.hidden=false;pills.textContent='';
  for(const [cls,n] of [['bad',3],['warn',5],['ok',12],['',2]]){
    const b=document.createElement('button');b.className=('bgpill '+cls).trim();b.textContent=String(n);pills.appendChild(b)}
  const boards=document.getElementById('boardsHud');
  if(!boards.textContent.trim()){const b=document.createElement('button');b.textContent='BOARD · Présentation Jarvis';boards.appendChild(b)}
  let rail=document.getElementById('presentationRail');
  if(!rail){rail=document.createElement('div');rail.id='presentationRail';rail.setAttribute('data-shell-control','');
    rail.style.cssText='position:fixed;top:64px;right:18px;width:300px;height:120px;z-index:30';document.body.appendChild(rail)}
  rail.hidden=false;
  return document.documentElement.getAttribute('data-jarvis-theme')||'';
})()"""

READ = r"""(()=>{
  const shell=window.JarvisShell;
  const out={selector:shell?shell.CONTROL_SELECTOR:null,controls:[],vw:innerWidth,
    overflowX:document.documentElement.scrollWidth>innerWidth};
  if(!shell)return out;
  for(const el of document.querySelectorAll(shell.CONTROL_SELECTOR)){
    if(el.hidden||el.closest('[hidden]'))continue;
    const cs=getComputedStyle(el);if(cs.display==='none'||cs.visibility==='hidden')continue;
    const r=el.getBoundingClientRect();if(!(r.width>0&&r.height>0))continue;
    out.controls.push({name:el.id?'#'+el.id:'.'+el.classList[0],l:r.left,t:r.top,r:r.right,b:r.bottom});
  }
  const z=s=>{const e=document.querySelector(s);return e?getComputedStyle(e).zIndex:null};
  out.z={topbar:z('.topbar'),dock:z('.dock'),panel:z('#panel'),pills:z('#bgPills'),chat:z('#chatTab'),
    banner:z('.live-banner'),boards:z('#boardsPanel'),tray:z('#boardDropTray')};
  return out;
})()"""

OPEN_PANEL = r"""(()=>{
  const p=document.getElementById('panel');p.classList.add('open');
  const box=e=>{const r=e.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}};
  const out={panel:box(p),dock:box(document.querySelector('.dock')),chat:box(document.getElementById('chatTab')),
    pills:box(document.getElementById('bgPills')),vw:innerWidth};
  p.classList.remove('open');
  return out;
})()"""


def _overlap(a: dict, b: dict) -> bool:
    return min(a["r"], b["r"]) - max(a["l"], b["l"]) > 0.5 and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 0.5


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    tmp = tmp_path_factory.mktemp("shell")
    page = _served_page(tmp)
    plan = [
        {"width": width, "height": height, "mountPalette": True,
         "actions": [{"a": "eval", "expr": SETUP % json.dumps(theme)},
                     {"a": "eval", "expr": READ},
                     {"a": "eval", "expr": OPEN_PANEL}]}
        for theme in THEMES for width, height in VIEWPORTS
    ]
    done = subprocess.run([node, str(HARNESS), str(page), chrome, json.dumps(plan)],
                          capture_output=True, text=True, encoding="utf-8", timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    steps = json.loads(done.stdout)
    out = {}
    for index, (theme, size) in enumerate((t, s) for t in THEMES for s in VIEWPORTS):
        actions = steps[index]["actions"]
        out[(theme, size)] = {"theme": actions[0]["value"], "read": actions[1]["value"], "panel": actions[2]["value"]}
    return out


@pytest.mark.parametrize("size", VIEWPORTS)
def test_one_geometry_and_one_rank_set_for_both_themes(measured, size):
    circuit, cosmos = measured[("circuit-board", size)], measured[("cosmos", size)]
    assert cosmos["theme"] == "cosmos"
    assert circuit["read"]["z"] == cosmos["read"]["z"]
    assert circuit["read"]["z"] == {"topbar": "31", "dock": "32", "panel": "33", "pills": "40", "chat": "32",
                                    "banner": "35", "boards": "36", "tray": "34"}
    # Les zones : lanceur en haut à droite, onglet Chat en bas à droite, aux
    # mêmes bords dans les deux thèmes (la peau change, la place non).
    for theme in (circuit, cosmos):
        controls = {c["name"]: c for c in theme["read"]["controls"]}
        width = theme["read"]["vw"]
        gutter = 18 if width > 700 else 10
        assert round(width - controls[".dock"]["r"]) == gutter
        assert round(controls[".dock"]["t"]) == gutter
        assert round(width - controls["#chatTab"]["r"]) == gutter


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", VIEWPORTS)
def test_every_control_is_measured_and_none_covers_another(measured, theme, size):
    read = measured[(theme, size)]["read"]
    assert read["selector"] == "[data-shell-control],#sceneLayer>.sc-status"
    names = [c["name"] for c in read["controls"]]
    for required in ("#chatTab", "#interactionModeHud", "#presentationRail", ".dock", "#bgPills",
                     "#toolWheel", "#boardsHud"):
        assert required in names, (required, names)
    # Slice 06 : la capsule de l'indication vocale n'existe plus (centre d'état du bas).
    assert "#voiceHint" not in names
    # Slice 04 : la roue est visible d'office ; la colonne Bare Hands quitte la vue
    # (Sélection la tient) et le rail de capture n'existe plus.
    for gone in ("#barehandsHud", "#barehandsPalette", "#captureRail"):
        assert gone not in names, (gone, names)
    # Slice 09 (migration close) : depuis la Slice 07 le rail est dans la zone de
    # droite, sous le lanceur et au-dessus de l'onglet Chat ; il n'a plus d'exemption.
    placed = read["controls"]
    overlaps = [(a["name"], b["name"]) for i, a in enumerate(placed)
                for b in placed[i + 1:] if _overlap(a, b)]
    assert not overlaps, overlaps
    assert read["overflowX"] is False


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", VIEWPORTS)
def test_an_open_side_panel_stays_under_the_launcher_and_above_the_chat_tab(measured, theme, size):
    seen = measured[(theme, size)]["panel"]
    panel, dock, chat, pills = seen["panel"], seen["dock"], seen["chat"], seen["pills"]
    assert not _overlap(panel, dock), (panel, dock)
    assert not _overlap(panel, chat), (panel, chat)
    assert not _overlap(panel, pills), (panel, pills)
    assert panel["r"] <= seen["vw"]


# ======================================================================
# Slice 09 : matrice d'intégration, parcours, accessibilité, tailles
# ======================================================================
#
# Une seule page servie, le double `fetch` de `_status_centre_browser.mjs`.
# `AUDIT` relève, pour chaque état, ce qu'un œil relèverait sur la capture.

from tests.unit.test_status_centre_browser import HARNESS as CENTRE_HARNESS  # noqa: E402

EVIDENCE = os.environ.get("JARVIS_S09_EVIDENCE_DIR")
STILL, STILL2, SHOT_ID = "jart_" + "a" * 32, "jart_" + "b" * 32, "jart_" + "c" * 32

#: Le rail aux états mêlés (D10) : travail avec aperçu, à revoir avec aperçu,
#: problème, prête sans aperçu (Slidecar), état inconnu.
RAIL_ROWS = [
    {"title": "Présentation Jarvis", "preview": {"artifact_id": STILL, "kind": "presentation_still", "width": 1280, "height": 720},
     "work": {"state": "working", "label": "presentation_edit", "age_s": 3}},
    {"title": "Bilan trimestriel", "preview": {"artifact_id": STILL2, "kind": "presentation_still", "width": 1280, "height": 720},
     "unreviewed": {"since": "2026-10-16T09:00:00Z", "label": "presentation_edit"}, "work": {"state": "done", "label": "", "age_s": None}},
    {"title": "Roadmap produit", "work": {"state": "problem", "label": "render", "age_s": 40, "message": "rendu interrompu"}},
    {"title": "Notes de recherche", "engine": "slidecar", "type": {"engine": "slidecar"}, "work": {"state": "done", "label": "", "age_s": None}},
    {"title": "Architecture technique", "work": None},
]
#: Les artefacts du Board actif (Stage B) : capture, PowerPoint, Google Slides, vidéo en cours, PDF en échec.
BOARD_ITEMS = [
    {"artifact_id": SHOT_ID, "kind": "screenshot", "state": "complete", "mime_type": "image/png", "has_payload": True, "created_at": "2026-10-16T08:00:00Z"},
    {"artifact_id": "jart_" + "d" * 32, "kind": "upload", "state": "complete", "has_payload": True, "created_at": "2026-10-15T08:00:00Z",
     "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "preview": "Roadmap Q4.pptx"},
    {"artifact_id": "jart_" + "e" * 32, "kind": "link", "state": "complete", "preview": "https://docs.google.com/presentation/d/abc/edit",
     "has_payload": False, "created_at": "2026-10-14T08:00:00Z"},
    {"artifact_id": "jart_" + "f" * 32, "kind": "upload", "state": "pending", "mime_type": "video/mp4", "preview": "demo.mp4",
     "has_payload": True, "created_at": "2026-10-16T10:00:00Z"},
    {"artifact_id": "jart_" + "0" * 31 + "9", "kind": "upload", "state": "failed", "mime_type": "application/pdf", "preview": "contrat.pdf",
     "has_payload": True, "created_at": "2026-10-13T08:00:00Z"},
]
AUDIO = {"capture_id": "jcap_a", "channel": "audio", "mode": "continuous", "state": "active", "device": "default",
         "age_s": 42, "stop_requested_at": None}
VIDEO = {"capture_id": "jcap_s", "channel": "screen", "mode": "continuous", "state": "active", "device": "default",
         "age_s": 65, "stop_requested_at": None}
BOARDS = [{"board_id": "default", "title": "Jarvis", "status": "active"},
          {"board_id": "board_b", "title": "Projet Atlas", "status": "active"},
          {"board_id": "board_c", "title": "Revue trimestrielle", "status": "active"}]
#: Le mode d'interaction tel que Core le publie (sinon le bouton dit « statut indisponible » sur chaque capture).
MODE = {"schema_version": 1, "core_reachable": True, "mode": "assistant", "label": "Assistant", "stored": "assistant", "revision": 1, "error": None,
        "modes": [{"value": "assistant", "label": "Assistant", "implemented": True, "summary": "Conversation et outils"},
                  {"value": "presentation", "label": "Présentation", "implemented": True, "summary": "Pilotage d'une présentation"}]}


def _slide(a: str, b: str, title: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><defs><linearGradient id="g" x1="0" '
            f'y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>'
            f'<rect width="1280" height="720" fill="url(#g)"/><text x="96" y="380" font-family="Segoe UI,sans-serif" font-size="120" '
            f'font-weight="700" fill="#fff">{title}</text></svg>')


PREVIEWS = {STILL: _slide("#1d2b64", "#f8cdda", "JARVIS"), STILL2: _slide("#0f2027", "#2c5364", "Bilan"),
            SHOT_ID: _slide("#134e5e", "#71b280", "Capture")}
MIXED = {"railRows": RAIL_ROWS, "boardArtifacts": BOARD_ITEMS, "boards": BOARDS, "previews": PREVIEWS}
BUSY = {**MIXED, "captures": [AUDIO]}

ANCHOR = "#toolWheel .tw-anchor"
FOCUS_ANCHOR = f"(()=>{{document.querySelector('{ANCHOR}').focus();return 1}})()"
WHEEL_OPEN = [["eval", "focus", FOCUS_ANCHOR, 100], ["key", "open", "ArrowRight", 450]]

#: L'audit d'un état : `keys` = les surfaces de l'état, qui doivent être entières
#: et au premier plan (cinq points chacune) ; un contrôle couvert par l'une
#: d'elles n'est pas un défaut (elle s'ouvre par rang, au-dessus).
AUDIT = r"""(keys=>{
  const vis=el=>!!el&&el.isConnected&&!el.closest('[hidden]')&&el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})
    &&(r=>r.width>0&&r.height>0)(el.getBoundingClientRect());
  const box=el=>{const r=el.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}};
  const desc=el=>{if(!el||el.nodeType!==1)return String(el);const cls=typeof el.className==='string'&&el.className?'.'+el.className.trim().split(/\s+/)[0]:'';
    return (el.id?'#'+el.id:el.tagName.toLowerCase()+cls)+' «'+((el.getAttribute('aria-label')||el.textContent||'').trim().replace(/\s+/g,' ').slice(0,40))+'»'};
  const overlap=(a,b)=>Math.min(a.r,b.r)-Math.max(a.l,b.l)>0.5&&Math.min(a.b,b.b)-Math.max(a.t,b.t)>0.5;
  const sel=window.JarvisShell.CONTROL_SELECTOR;
  const controls=[...document.querySelectorAll(sel)].filter(vis);
  const name=el=>el.id?'#'+el.id:'.'+el.classList[0];
  /* Le panneau latéral s'ouvre sur le rail (33 > 30, registre) ; le bandeau GPT-Live passe sur un panneau (35). */
  const allowed=[['#panel','#presentationRail'],['#chatPanel','#presentationRail'],['#liveBanner','#panel'],['#liveBanner','#chatPanel']];
  const overlaps=[];
  for(let i=0;i<controls.length;i+=1)for(let j=i+1;j<controls.length;j+=1){
    const a=name(controls[i]),b=name(controls[j]);
    if(controls[i].contains(controls[j])||controls[j].contains(controls[i]))continue;
    if(allowed.some(([x,y])=>(x===a&&y===b)||(x===b&&y===a)))continue;
    if(overlap(box(controls[i]),box(controls[j])))overlaps.push([a,b]);
  }
  const keyEls=keys.map(k=>document.querySelector(k));
  const inKey=el=>keyEls.some(k=>k&&k.contains(el));
  const INTERACTIVE='button,[role=button],[role^=menuitem],[role=tab],[role=switch],[role=option],a[href],input:not([type=hidden]),select,textarea,[tabindex]:not([tabindex="-1"])';
  /* Chaque cible interactive d'une commande, en son centre : la commande (ou une surface de l'état) est au premier plan. */
  const covered=[];
  for(const c of controls){
    const targets=[c,...c.querySelectorAll(INTERACTIVE)].filter(t=>vis(t)&&(t!==c||t.matches(INTERACTIVE))&&getComputedStyle(t).pointerEvents!=='none');
    for(const t of targets){
      const r=t.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/2;
      if(x<0||y<0||x>=innerWidth||y>=innerHeight)continue;
      /* Une carte défilée hors de sa liste (défilement propre) n'est pas couverte : elle se fait défiler. */
      let clipped=false;for(let n=t.parentElement;n&&n!==document.body;n=n.parentElement){const cs=getComputedStyle(n);
        if(cs.overflowY!=='visible'||cs.overflowX!=='visible'){const q=n.getBoundingClientRect();if(x<q.left||x>q.right||y<q.top||y>q.bottom){clipped=true;break}}}
      if(clipped)continue;
      const hit=document.elementFromPoint(x,y);
      if(!hit||t.contains(hit)||c.contains(hit)||inKey(hit))continue;
      covered.push({target:desc(t),by:desc(hit)});
    }
  }
  /* Un nom pour chaque commande visible de la page (icône seule comprise). */
  const nameOf=el=>{
    const by=el.getAttribute('aria-labelledby');
    const parts=[el.getAttribute('aria-label'),by?by.split(/\s+/).map(id=>(document.getElementById(id)||{}).textContent||'').join(' '):'',
      el.labels&&el.labels.length?[...el.labels].map(l=>l.textContent).join(' '):'',
      el.matches('input[type=button],input[type=submit]')?el.value:'',el.textContent,el.getAttribute('title'),el.getAttribute('placeholder'),
      [...el.querySelectorAll('img[alt]')].map(i=>i.alt).join(' ')];
    return parts.map(x=>(x||'').trim()).find(Boolean)||'';
  };
  const unnamed=[...document.querySelectorAll(INTERACTIVE)].filter(el=>vis(el)&&!el.closest('#sceneLayer')&&!nameOf(el)).map(desc);
  /* Texte coupé : ce qui déborde de sa boîte sans que son texte entier soit dit ailleurs (title, nom accessible). */
  const scopes=[...controls,...keyEls.filter(Boolean)];
  const clipped=[];const seen=new Set();
  for(const scope of scopes)for(const el of [scope,...scope.querySelectorAll('*')]){
    if(seen.has(el)||!vis(el))continue;seen.add(el);
    const own=[...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim());if(!own)continue;
    /* Texte réservé aux lecteurs d'écran (boîte de 1 px) : il n'est pas montré, donc pas coupé. */
    if(el.clientWidth<=2||el.clientHeight<=2)continue;
    const cs=getComputedStyle(el);
    const cut=(el.scrollWidth>el.clientWidth+1&&cs.overflowX!=='visible')||(el.scrollHeight>el.clientHeight+1&&cs.overflowY!=='visible'&&cs.overflowY!=='auto'&&cs.overflowY!=='scroll');
    if(!cut)continue;
    const text=el.textContent.trim().replace(/\s+/g,' ');const head=text.slice(0,12);
    let said=false;for(let n=el,i=0;n&&i<5;n=n.parentElement,i+=1){
      const words=[n.getAttribute&&n.getAttribute('title'),n.getAttribute&&n.getAttribute('aria-label'),n.getAttribute&&n.getAttribute('aria-description')].join(' ');
      if(words.includes(head)){said=true;break}}
    if(!said)clipped.push({el:desc(el),text:text.slice(0,60),sw:el.scrollWidth,cw:el.clientWidth,sh:el.scrollHeight,ch:el.clientHeight});
  }
  /* Hors écran : une commande qui dépasse le bord (l'ancre de la roue touche le bord gauche par contrat). */
  const offscreen=controls.map(c=>({n:name(c),b:box(c)})).filter(({b})=>b.l<-0.5||b.t<-0.5||b.r>innerWidth+0.5||b.b>innerHeight+0.5).map(x=>x.n);
  const keysOut={};
  keys.forEach((k,i)=>{const el=keyEls[i];if(!el||!vis(el)){keysOut[k]={visible:false};return}
    const b=box(el);const pts=[[(b.l+b.r)/2,(b.t+b.b)/2],[b.l+6,b.t+6],[b.r-6,b.t+6],[b.l+6,b.b-6],[b.r-6,b.b-6]];
    const misses=pts.filter(([x,y])=>x>=0&&y>=0&&x<innerWidth&&y<innerHeight).map(([x,y])=>{const h=document.elementFromPoint(x,y);
      return h&&(el.contains(h)||keyEls.some(o=>o&&o.contains(h)))?null:{x:Math.round(x),y:Math.round(y),by:desc(h)}}).filter(Boolean);
    /* Une forme découpée (demi-disque de la roue) : son centre suffit, les coins tombent hors de la forme. */
    const shaped=getComputedStyle(el).clipPath!=='none'||el.matches('#toolWheel,#toolWheel *');
    keysOut[k]={visible:true,box:b,inside:b.l>=-0.5&&b.t>=-0.5&&b.r<=innerWidth+0.5&&b.b<=innerHeight+0.5,
      misses:shaped?misses.slice(0,1).filter(m=>m&&m.x===Math.round((b.l+b.r)/2)):misses};
  });
  const a=document.activeElement;const acs=a&&a!==document.body?getComputedStyle(a):null;
  const focus=acs?{el:desc(a),visible:vis(a),ring:(acs.outlineStyle!=='none'&&parseFloat(acs.outlineWidth)>0)||(!!acs.boxShadow&&acs.boxShadow!=='none')}:null;
  return {vw:innerWidth,vh:innerHeight,overflowX:document.documentElement.scrollWidth>innerWidth,overlaps,covered,unnamed,clipped,offscreen,keys:keysOut,focus,
    theme:document.documentElement.getAttribute('data-jarvis-theme')||''};
})"""


def _audit(*keys: str) -> str:
    return f"({AUDIT})({json.dumps(list(keys))})"


def _evidence(tmp_path: Path) -> Path:
    target = Path(EVIDENCE) if EVIDENCE else tmp_path / "evidence"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _centre(tmp_path: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    done = subprocess.run([node, str(CENTRE_HARNESS), str(page), chrome, "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=560, check=False)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout)


def _errors(step: dict) -> list:
    return [line for line in step["console"] if line["type"] in ("exception", "error")]


def _clean(audit: dict, label: str) -> None:
    """Ce qu'un œil refuserait sur la capture, quel que soit l'état."""

    assert audit["overflowX"] is False, (label, "la page défile horizontalement")
    assert audit["overlaps"] == [], (label, "commandes l'une sur l'autre", audit["overlaps"])
    assert audit["covered"] == [], (label, "commande couverte en son centre", audit["covered"])
    assert audit["unnamed"] == [], (label, "commande sans nom accessible", audit["unnamed"])
    assert audit["clipped"] == [], (label, "texte coupé sans son texte entier", audit["clipped"])
    assert audit["offscreen"] == [], (label, "commande hors de l'écran", audit["offscreen"])
    for key, seen in audit["keys"].items():
        assert seen["visible"], (label, key, "la surface de l'état n'est pas visible")
        assert seen["inside"], (label, key, "la surface de l'état sort de l'écran", seen["box"])
        assert seen["misses"] == [], (label, key, "la surface de l'état est couverte", seen["misses"])


def _focus_ring(audit: dict, label: str) -> None:
    focus = audit["focus"]
    assert focus and focus["visible"] and focus["ring"], (label, "focus invisible ou sur un élément caché", focus)


#: La matrice : (numéro, nom, largeur, hauteur, options d'étape, actions, surfaces de l'état).
#: Les lectures propres à un état (`extra`) se font après l'audit.
SUB_ITEMS = r"""[...document.querySelectorAll('#toolWheel .tw-sub:not([hidden]) .tw-item')].map(b=>b.textContent.trim())"""
WHEEL_STATE = r"""({open:document.getElementById('toolWheel').hasAttribute('data-open'),
  focus:(document.activeElement&&document.activeElement.getAttribute('data-tw-slot'))||null,
  label:(document.querySelector('#toolWheel .tw-label')||{}).textContent||''})"""
CHIPS = r"""[...document.querySelectorAll('#recIndicators .ri-chip')].map(c=>({key:c.dataset.riKey,text:c.textContent.trim(),
  label:c.getAttribute('aria-label')}))"""
PREVIEW = r"""(()=>{const h=document.getElementById('screenshotPreview');const img=h&&h.querySelector('img');
  return {shown:!!h&&!h.hidden&&!!h.querySelector('.sp-card'),image:(h.querySelector('.sp-thumb')||{}).dataset?h.querySelector('.sp-thumb').dataset.spImage:null,
    loaded:!!img&&img.complete&&img.naturalWidth>0,actions:[...h.querySelectorAll('[data-sp-act]')].map(b=>b.dataset.spAct)}})()"""
RAIL_CARDS = r"""[...document.querySelectorAll('#presentationRail .jvr-item')].map(c=>({state:c.dataset.state||null,ws:'ws' in c.dataset,
  img:!!c.querySelector('.jvr-thumb img'),kind:(c.querySelector('.jvr-thumb')||{dataset:{}}).dataset.kind||null}))"""
OPEN_OF = r"""(s=>{const e=document.querySelector(s);return !!e&&!e.hidden&&e.checkVisibility()})(%s)"""

def _real_badge() -> str:
    """Le badge Bare Hands tel que `control_center_barehands.js` le pose (QA S09 P3) : son texte « actif »
    (`BADGE.active`) et les règles de sa feuille (`#jarvisHands{…}`, `#jarvisHands .jh-badge{…}`), lus
    dans le module et non recopiés."""
    source = (Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_barehands.js").read_text(encoding="utf-8")
    accent = re.search(r"const ACCENT='([^']+)'", source).group(1)
    text = re.search(r"const BADGE=Object\.freeze\(\{[^}]*active:'([^']+)'", source).group(1)
    rules = [re.search(r"^#jarvisHands\{[^}]*\}", source, re.M).group(0),
             re.search(r"^#jarvisHands \.jh-badge\{[^}]*\}", source, re.M).group(0)]
    css = " ".join(r.replace("${ACCENT}", accent).replace("\n", " ") for r in rules)
    return ("(()=>{const st=document.createElement('style');st.textContent=" + json.dumps(css) + ";document.head.append(st);"
            "let h=document.getElementById('jarvisHands');if(!h){h=document.createElement('div');h.id='jarvisHands';document.body.append(h)}"
            "const b=document.createElement('div');b.className='jh-badge';b.textContent=" + json.dumps(text) + ";h.append(b);"
            "const r=b.getBoundingClientRect();return {text:b.textContent,w:Math.round(r.width),h:Math.round(r.height),"
            "fixed:getComputedStyle(b).position==='fixed'}})()")


#: Le vrai badge Bare Hands, puis la scène qui perd Core : sa note « Scène figée · <cause> » passe sur deux
#: lignes ; puis une capture d'écran par la roue (sonde QA S08).
BADGE = _real_badge()
FREEZE = ("(()=>{const f=window.fetch;window.fetch=(p,i)=>String(p).startsWith('/api/scene')?Promise.reject(new TypeError('Failed to fetch'))"
          ":f(p,i);window.__sc.waiters.splice(0).forEach(fn=>fn([]));return 1})()")
NOTE_LINES = "Math.round(document.querySelector('#sceneLayer>.sc-status').getBoundingClientRect().height)"
#: Core perdu : le mode n'est plus confirmé non plus (bouton sur deux lignes, « statut indisponible »), le cas le plus haut.
LOST_MODE = {"seed": {"mode": None}}
DEGRADED_SHOT = [["eval", "badge", BADGE, 300], ["eval", "freeze", FREEZE, 6000], ["eval", "noteH", NOTE_LINES, 50],
                 *WHEEL_OPEN, ["key", "v", "ArrowDown", 120], ["key", "s", "ArrowDown", 120], ["key", "shoot", "Enter", 1600]]

STATES = (
    ("01", "board-wheel-closed", 1440, 900, {}, [], [ANCHOR],
     [["eval", "wheel", WHEEL_STATE, 50]]),
    ("02", "wheel-open-selection-focused", 1440, 900, {}, WHEEL_OPEN, ["#toolWheel .tw-panel"],
     [["eval", "wheel", WHEEL_STATE, 50]]),
    ("03", "selection-submenu", 1440, 900, {}, [*WHEEL_OPEN, ["key", "sub", "Enter", 600]],
     ["#toolWheel .tw-sub .tw-item", "#toolWheel .tw-sub .tw-item:last-of-type"],
     [["eval", "sub", SUB_ITEMS, 50]]),
    ("04", "audio-active", 1440, 900, {"seed": {"captures": [AUDIO]}}, [], ["#recIndicators"],
     [["eval", "chips", CHIPS, 50]]),
    ("05", "video-active", 1440, 900, {"seed": {"captures": [VIDEO]}}, [], ["#recIndicators"],
     [["eval", "chips", CHIPS, 50]]),
    ("06", "screenshot-preview", 1440, 900, {},
     [*WHEEL_OPEN, ["key", "v", "ArrowDown", 120], ["key", "s", "ArrowDown", 120], ["key", "shoot", "Enter", 1600]],
     ["#screenshotPreview"], [["eval", "preview", PREVIEW, 50]]),
    ("07", "alert-popover", 1440, 900, {}, [["click", "pill", '#bgPills [data-bg-cat="failed"]', 900]], ["#bgPop"],
     [["eval", "open", OPEN_OF % json.dumps("#bgPop"), 50]]),
    ("08", "rail-mixed-items", 1440, 900, {"seed": MIXED}, [], ["#presentationRail"],
     [["eval", "cards", RAIL_CARDS, 50]]),
    ("10", "mode-chooser", 1440, 900, {}, [["click", "mode", "#interactionModeButton", 700]], ["#interactionModeHud .im-pop"],
     [["eval", "open", OPEN_OF % json.dumps("#interactionModeHud .im-pop"), 50]]),
    ("11", "board-chooser", 1440, 900, {"seed": {"boards": BOARDS}}, [["click", "boards", "#boardsButton", 900]], ["#boardsPanel"],
     [["eval", "open", OPEN_OF % json.dumps("#boardsPanel"), 50]]),
    ("12", "narrow-800x600", 800, 600, {"seed": BUSY}, [], [], []),
    ("13", "short-1280x540", 1280, 540, {"seed": BUSY}, WHEEL_OPEN, ["#toolWheel .tw-panel"], [["eval", "wheel", WHEEL_STATE, 50]]),
    ("14", "reduced-motion", 1440, 900, {"seed": BUSY, "reducedMotion": True}, WHEEL_OPEN, ["#toolWheel .tw-panel"],
     [["eval", "wheel", WHEEL_STATE, 50],
      ["eval", "dur", "getComputedStyle(document.documentElement).getPropertyValue('--shell-dur').trim()", 50]]),
    ("15", "zoom-200", 720, 450, {"seed": BUSY, "scale": 2}, [], [], []),
    # QA S08 P1 : badge Bare Hands + scène figée (note sur deux lignes au-dessus de 700 px) + capture fraîche, aux quatre largeurs.
    ("16", "badge-frozen-scene-preview-1440", 1440, 900, LOST_MODE, DEGRADED_SHOT, ["#screenshotPreview"], [["eval", "preview", PREVIEW, 50]]),
    ("17", "badge-frozen-scene-preview-1280", 1280, 720, LOST_MODE, DEGRADED_SHOT, ["#screenshotPreview"], [["eval", "preview", PREVIEW, 50]]),
    ("18", "badge-frozen-scene-preview-900", 900, 600, LOST_MODE, DEGRADED_SHOT, ["#screenshotPreview"], [["eval", "preview", PREVIEW, 50]]),
    # QA S09 P2 : à 700 px et moins, sous la vraie pastille, le bouton de mode passe au second barreau du rail.
    ("19", "badge-frozen-scene-preview-600", 600, 800, LOST_MODE, DEGRADED_SHOT, ["#screenshotPreview"], [["eval", "preview", PREVIEW, 50]]),
)


@pytest.fixture(scope="module")
def matrix(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("matrix")
    shots = _evidence(tmp)
    plan, index = [], []
    for theme in THEMES:
        for number, label, width, height, options, actions, keys, extra in STATES:
            options = {**options, "seed": {"mode": MODE, "previews": PREVIEWS, **options.get("seed", {})}}
            step = {"width": width, "height": height, "theme": theme, **options,
                    "actions": [*actions, ["eval", "audit", _audit(*keys), 50], *extra,
                                ["shot", "shot", str(shots / f"matrix-{number}-{label}-{theme}.png"), 50]]}
            plan.append(step)
            index.append((number, theme))
    steps = _centre(tmp, plan)
    return {key: step for key, step in zip(index, steps)}


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("number", [s[0] for s in STATES])
def test_runtime_matrix(matrix, number, theme):
    """Les états de `docs/04-testing-and-quality.md` × deux thèmes (le 9, Studio /
    Variantes + rail, est `test_runtime_matrix_studio_and_rail`) : audit commun,
    puis ce que l'état promet, puis la capture écrite."""

    spec = next(s for s in STATES if s[0] == number)
    label = f"{number}-{spec[1]}-{theme}"
    step = matrix[(number, theme)]
    results = step["results"]
    audit = results["audit"]
    assert isinstance(audit, dict) and "error" not in audit, (label, audit)
    assert audit["theme"] == ("cosmos" if theme == "cosmos" else "circuit-board"), (label, audit["theme"])
    _clean(audit, label)
    assert _errors(step) == [], (label, _errors(step))
    shot = Path(results["shot"])
    assert shot.is_file() and shot.stat().st_size > 20000, (label, shot)
    if number == "01":
        assert results["wheel"]["open"] is False
    if number in ("02", "13", "14"):
        assert results["wheel"]["open"] is True and results["wheel"]["focus"] == "selection", (label, results["wheel"])
        _focus_ring(audit, label)
    if number == "03":
        assert results["sub"] == ["Souris", "Bare Hands"], (label, results["sub"])
        _focus_ring(audit, label)
    if number == "04":
        chips = results["chips"]
        assert len(chips) == 1 and "audio" in chips[0]["label"] and "0:4" in chips[0]["text"], (label, chips)
    if number == "05":
        chips = results["chips"]
        assert len(chips) == 1 and "écran" in chips[0]["label"] and "REC" in chips[0]["text"], (label, chips)
        assert chips[0]["label"].startswith("REC — "), (label, "le nom commence par le mot montré", chips)
    if number in ("16", "17", "18", "19"):
        badge = results["badge"]
        assert badge["text"] == "MAINS · ACTIF" and badge["fixed"] and badge["w"] > 90 and badge["h"] >= 20, (label, badge)
    if number in ("16", "17", "18"):
        assert results["noteH"] >= 40, (label, "la note de la scène figée tient sur deux lignes", results["noteH"])
    if number in ("06", "16", "17", "18", "19"):
        preview = results["preview"]
        assert preview["shown"] and preview["loaded"] and preview["image"] == "ready", (label, preview)
        assert {"open", "send", "delete"} <= set(preview["actions"]), (label, preview)
        assert "POST /api/captures/screenshot" in step["calls"], (label, step["calls"])
    if number in ("07", "10", "11"):
        assert results["open"] is True, label
    if number == "08":
        cards = results["cards"]
        states = [c["state"] for c in cards if not c["ws"]]
        assert states == ["working", "unreviewed", "problem", "done", "unknown"], (label, states)
        assert sum(1 for c in cards if c["ws"]) == len(BOARD_ITEMS), (label, cards)
        assert sum(1 for c in cards if c["img"]) >= 3, (label, "aperçus réels : deux présentations et la capture", cards)
    if number == "14":
        assert results["dur"] == "0ms", (label, results["dur"])
    if number == "15":
        assert (audit["vw"], audit["vh"]) == (720, 450), (label, "fenêtre 1440×900 à 200 %")


async def test_runtime_matrix_studio_and_rail(tmp_path):
    """État 9 : Variantes (Studio) ouvert, fenêtré, sur un vrai Core isolé ; le
    rail est la colonne de droite, à côté, jamais dessous ni dessus ; deux thèmes."""

    from tests.fakes.explorer_browser import ExplorerRig, drive
    from tests.unit.test_presentation_studio_explorer_browser import FRAME_READY, READY, open_api

    shots = _evidence(tmp_path)
    geometry = r"""(()=>{const b=s=>{const e=document.querySelector(s);if(!e||e.hidden)return null;const r=e.getBoundingClientRect();
      return r.width>0?[Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom)]:null};
      return {docked:document.documentElement.classList.contains('jvr-studio'),studio:b('#jvStudioExplorer'),rail:b('#presentationRail'),
        theme:document.documentElement.getAttribute('data-jarvis-theme')||'',overflowX:document.documentElement.scrollWidth>innerWidth,
        titleCut:(t=>!!t&&t.scrollWidth>t.clientWidth+1)(document.querySelector('#presentationRail .jvr-title')),
        gapHits:(()=>{const s=document.getElementById('jvStudioExplorer').getBoundingClientRect(),r=document.getElementById('presentationRail').getBoundingClientRect();
          const out=[];for(let y=4;y<innerHeight;y+=4){const h=document.elementFromPoint((s.right+r.left)/2,y);
            if(h&&h.closest(window.JarvisShell.CONTROL_SELECTOR)&&!h.closest('#presentationRail'))out.push([y,h.id||h.className])}return out.slice(0,6)})()}})()"""
    async with ExplorerRig(tmp_path) as rig:
        for theme in THEMES:
            result = await drive(rig.url, [
                {"eval": f"JarvisThemeAPI.activate({json.dumps(theme)},{{persist:false}})"},
                open_api(rig), READY, FRAME_READY, {"wait": 700},
                {"value": "geo", "expr": geometry},
                {"value": "audit", "expr": _audit("#jvStudioExplorer", "#presentationRail")},
                {"shot": str(shots / f"matrix-09-studio-and-rail-{theme}.png")},
            ], viewport="1440x900")
            reads = result["reads"]
            assert "failed" not in reads, reads.get("failed")
            geo, audit = reads["geo"], reads["audit"]
            assert geo["theme"] == theme and geo["docked"] is True, geo
            assert geo["rail"][0] >= geo["studio"][2] and geo["rail"][2] <= 1440, ("le rail est la colonne de droite, à côté", geo)
            assert geo["overflowX"] is False
            for key in ("#jvStudioExplorer", "#presentationRail"):
                assert audit["keys"][key]["visible"] and audit["keys"][key]["misses"] == [], (theme, key, audit["keys"][key])
            assert audit["unnamed"] == [], (theme, audit["unnamed"])
            assert audit["clipped"] == [], (theme, "texte coupé sans son texte entier", audit["clipped"])
            # QA S09 P7 : l'audit entier, comme les autres états ; le titre du rail n'est pas coupé (« PRÉSENTATION… »).
            assert audit["overlaps"] == [], (theme, "commandes l'une sur l'autre", audit["overlaps"])
            assert audit["covered"] == [], (theme, "commande couverte en son centre", audit["covered"])
            assert audit["offscreen"] == [], (theme, audit["offscreen"])
            assert geo["titleCut"] is False, (theme, "titre du rail coupé", geo)
            assert geo["gapHits"] == [], (theme, "une commande dépasse dans l'interstice Studio / rail", geo["gapHits"])
            assert (shots / f"matrix-09-studio-and-rail-{theme}.png").stat().st_size > 20000


# ------------------------------------------------------------------ parcours complets


def _stops_ok(stops: list, target: str) -> None:
    assert stops and stops[-1]["inside"], (target, "Tab n'atteint jamais la commande", stops[-6:])
    # Un objet de la scène montre son focus par sa sélection (`sc-selected` : anneau et poignée), pas par un contour.
    bad = [s for s in stops if s["name"] != "body" and not (s["visible"] and (s["ring"] or s.get("selected")))]
    assert bad == [], (target, "arrêt de Tab invisible ou sans anneau", bad)


WEDGES_HIT = r"""[...document.querySelectorAll('#toolWheel .tw-wedge')].map(w=>{const r=w.getBoundingClientRect();
  const dot=w.querySelector('.tw-dot')||w;const d=dot.getBoundingClientRect();const h=document.elementFromPoint(d.left+d.width/2,d.top+d.height/2);
  return {slot:w.getAttribute('data-tw-slot'),hit:!!h&&!!h.closest('#toolWheel')}})"""
OPEN = r"""(s=>{const e=document.querySelector(s);return !!e&&!e.hidden&&e.checkVisibility()})"""
ACTIVE = "(()=>{const a=document.activeElement;return a?(a.id||a.getAttribute('data-tw-slot')||a.className||a.tagName):null})()"


def _open(selector: str) -> str:
    return f"{OPEN}({json.dumps(selector)})"


def test_keyboard_only_full_path(tmp_path):
    """Clavier seul, de la page chargée : Board, roue (Sélection, capture),
    mode, lanceur, Chat, alertes, œil, rail — chaque arrêt de Tab visible avec
    son anneau, chaque surface ouverte puis refermée par Échap, le focus jamais
    sur un élément caché."""
    shots = _evidence(tmp_path)
    a = []
    def tab(name, target):
        a.append(["tabto", name, target, 150, 80])
    tab("t_boards", "#boardsHud")
    a += [["key", "k", "Enter", 700], ["eval", "boards_open", _open("#boardsPanel"), 50],
          ["key", "k", "Escape", 400], ["eval", "boards_closed", f"!{_open('#boardsPanel')}", 50], ["eval", "after_boards", ACTIVE, 50]]
    tab("t_wheel", "#toolWheel")
    a += [["key", "k", "ArrowRight", 450], ["eval", "wheel", WHEEL_STATE, 50],
          ["key", "k", "Enter", 600], ["eval", "sub", SUB_ITEMS, 50],
          ["key", "k", "Escape", 300], ["key", "k", "Escape", 400], ["eval", "after_wheel", ACTIVE, 50],
          ["key", "k", "ArrowRight", 450], ["key", "k", "ArrowDown", 120], ["key", "k", "ArrowDown", 120], ["key", "k", "Enter", 1600],
          ["eval", "preview", PREVIEW, 50], ["eval", "after_shot", ACTIVE, 50],
          ["shot", "shot1", str(shots / "keyboard-path-screenshot.png"), 50]]
    tab("t_mode", "#interactionModeHud")
    a += [["key", "k", "Enter", 600], ["eval", "mode_open", _open("#interactionModeHud .im-pop"), 50],
          ["key", "k", "Escape", 400], ["eval", "mode_closed", f"!{_open('#interactionModeHud .im-pop')}", 50]]
    tab("t_more", "#dockMore")
    a += [["key", "k", "Enter", 500], ["eval", "more_open", _open("#dockMorePop"), 50], ["eval", "more_focus", ACTIVE, 50],
          ["key", "k", "Escape", 400], ["eval", "more_closed", f"!{_open('#dockMorePop')}", 50], ["eval", "after_more", ACTIVE, 50]]
    tab("t_chat", "#chatTab")
    a += [["key", "k", "Enter", 800], ["eval", "chat_open", "document.getElementById('chatPanel').classList.contains('open')", 50],
          ["key", "k", "Escape", 600], ["eval", "chat_closed", "!document.getElementById('chatPanel').classList.contains('open')", 50]]
    tab("t_pills", "#bgPills")
    a += [["key", "k", "Enter", 800], ["eval", "pop_open", _open("#bgPop"), 50],
          ["key", "k", "Escape", 400], ["eval", "pop_closed", f"!{_open('#bgPop')}", 50]]
    tab("t_eye", "#hiddenEye")
    a += [["key", "k", "Enter", 600], ["eval", "eye", "document.getElementById('hiddenEye').getAttribute('aria-pressed')", 50]]
    tab("t_rail", "#presentationRail")
    a += [["eval", "rail_focus", ACTIVE, 50], ["shot", "shot2", str(shots / "keyboard-path-rail.png"), 50]]
    step = _centre(tmp_path, [{"width": 1440, "height": 900, "seed": {**MIXED, "mode": MODE, "previews": PREVIEWS}, "actions": a}])[0]
    r = step["results"]
    for name in ("t_boards", "t_wheel", "t_mode", "t_more", "t_chat", "t_pills", "t_eye", "t_rail"):
        assert isinstance(r[name], list), (name, r[name])
    for name, target in (("t_boards", "#boardsHud"), ("t_wheel", "#toolWheel"), ("t_mode", "#interactionModeHud"), ("t_more", "#dockMore"),
                         ("t_chat", "#chatTab"), ("t_pills", "#bgPills"), ("t_eye", "#hiddenEye"), ("t_rail", "#presentationRail")):
        _stops_ok(r[name], target)
    assert r["boards_open"] is True and r["boards_closed"] is True, r
    assert r["wheel"]["open"] and r["wheel"]["focus"] == "selection", r["wheel"]
    assert r["sub"] == ["Souris", "Bare Hands"], r["sub"]
    assert r["after_wheel"] and "tw-anchor" in r["after_wheel"], ("Échap rend le focus à l'ancre", r["after_wheel"])
    assert r["preview"]["shown"] and r["preview"]["loaded"], r["preview"]
    assert "tw-anchor" in r["after_shot"], ("la capture rend le focus à l'ancre, l'aperçu ne le prend pas", r["after_shot"])
    assert r["mode_open"] is True and r["mode_closed"] is True, r
    assert r["more_open"] is True and r["more_closed"] is True and r["after_more"] == "dockMore", r
    assert r["chat_open"] is True and r["chat_closed"] is True, r
    assert r["pop_open"] is True and r["pop_closed"] is True, r
    assert r["eye"] == "true", r["eye"]
    assert "POST /api/captures/screenshot" in step["calls"]
    assert _errors(step) == [], _errors(step)


def test_mouse_only_full_path(tmp_path):
    """Souris seule : survol de l'ancre (la roue s'ouvre), capture par le coin
    Capture d'écran, aperçu et visionneuse, alertes, mode, Board (une bascule),
    « Plus d’outils » et un outil, menu d'une carte du rail, œil, Chat."""
    shots = _evidence(tmp_path)
    a = [["move", "hover", ANCHOR, 600], ["eval", "wheel", WHEEL_STATE, 50],
         ["click", "shoot", '#toolWheel [data-tw-slot="screenshot"]', 1600], ["eval", "preview", PREVIEW, 50],
         ["move", "rehover", ANCHOR, 600], ["eval", "wedges", WEDGES_HIT, 50], ["eval", "beside", _audit("#screenshotPreview"), 50],
         ["move", "leave", ".topbar>.state", 900],
         ["click", "open", '#screenshotPreview [data-sp-act="open"]', 700], ["eval", "lightbox", _open("#screenshotLightbox"), 50],
         ["shot", "s1", str(shots / "mouse-path-lightbox.png"), 50],
         ["click", "lbclose", "#screenshotLightbox .sp-lb-close", 500], ["eval", "lightbox_closed", f"!{_open('#screenshotLightbox')}", 50],
         ["click", "pill", '#bgPills [data-bg-cat="failed"]', 800], ["eval", "pop", _open("#bgPop"), 50],
         ["click", "away", ".topbar>.state", 500], ["eval", "pop_closed", f"!{_open('#bgPop')}", 50],
         ["click", "mode", "#interactionModeButton", 600], ["eval", "mode_open", _open("#interactionModeHud .im-pop"), 50],
         ["click", "mode2", "#interactionModeButton", 500], ["eval", "mode_closed", f"!{_open('#interactionModeHud .im-pop')}", 50],
         ["click", "boards", "#boardsButton", 800], ["eval", "boards_open", _open("#boardsPanel"), 50],
         ["click", "switch", '#boardsList [data-board-id="board_b"][data-bd-action="switch"]', 2500],
         ["eval", "board", "document.getElementById('boardsTitle').textContent", 50],
         ["click", "more", "#dockMore", 500], ["eval", "more_open", _open("#dockMorePop"), 50],
         ["click", "trace", '#dockMorePop [data-panel="trace"]', 900], ["eval", "panel", "document.getElementById('panel').classList.contains('open')", 50],
         ["eval", "more_closed", f"!{_open('#dockMorePop')}", 50],
         ["click", "closepanel", "#closePanel", 500],
         ["rclick", "railmenu", "#presentationRail .jvr-item", 700], ["eval", "menu", _open(".jvr-menu"), 50],
         ["shot", "s2", str(shots / "mouse-path-rail-menu.png"), 50],
         ["click", "away2", ".topbar>.state", 500], ["eval", "menu_closed", f"!{_open('.jvr-menu')}", 50],
         ["click", "eye", "#hiddenEye", 700], ["eval", "eye_on", "document.getElementById('hiddenEye').getAttribute('aria-pressed')", 50],
         ["click", "chat", "#chatTab", 800], ["eval", "chat", "document.getElementById('chatPanel').classList.contains('open')", 50],
         ["click", "chat2", "#chatTab", 600], ["eval", "chat_closed", "!document.getElementById('chatPanel').classList.contains('open')", 50]]
    step = _centre(tmp_path, [{"width": 1440, "height": 900, "seed": {**MIXED, "mode": MODE, "previews": PREVIEWS}, "actions": a}])[0]
    r = step["results"]
    assert r["wheel"]["open"] is True, ("le survol de l'ancre ouvre la roue", r["wheel"])
    assert r["preview"]["shown"] and r["preview"]["loaded"], r["preview"]
    # La roue rouverte pendant l'aperçu : chaque coin reste sous le pointeur, l'aperçu se range à sa droite.
    assert r["wedges"] and all(w["hit"] for w in r["wedges"]), r["wedges"]
    _clean(r["beside"], "mouse-preview-beside-open-wheel")
    assert r["lightbox"] is True and r["lightbox_closed"] is True, r
    assert r["pop"] is True and r["pop_closed"] is True, r
    assert r["mode_open"] is True and r["mode_closed"] is True, r
    assert r["boards_open"] is True and r["board"] == "Projet Atlas", r
    assert [b["body"] for b in step["bodies"] if b["path"] == "/api/boards/switch"] == [{"board_id": "board_b"}]
    assert r["more_open"] is True and r["panel"] is True and r["more_closed"] is True, r
    assert r["menu"] is True and r["menu_closed"] is True, r
    assert r["eye_on"] == "true" and r["chat"] is True and r["chat_closed"] is True, r
    assert "POST /api/captures/screenshot" in step["calls"]
    for value in r.values():
        assert not (isinstance(value, dict) and "error" in value), value
    assert _errors(step) == [], _errors(step)


# ------------------------------------------------------------------ mouvement, couleurs, axe, tailles

#: Tout ce qui bouge encore dans la coque (hors scène et hors Studio) : animations et transitions calculées.
MOVING = r"""(()=>{const out=[];const scope=[...document.querySelectorAll(window.JarvisShell.CONTROL_SELECTOR+',.im-pop,#boardsPanel,.bgpop,#dockMorePop,.toasts')];
  const seen=new Set();for(const host of scope)for(const el of [host,...host.querySelectorAll('*')]){if(seen.has(el))continue;seen.add(el);
    if(el.closest('#sceneLayer'))continue;
    for(const pseudo of [null,'::before','::after']){const cs=getComputedStyle(el,pseudo);
      const anim=cs.animationName!=='none'&&cs.animationName!==''&&cs.animationDuration.split(',').some(d=>parseFloat(d)>0);
      const trans=cs.transitionDuration.split(',').some(d=>parseFloat(d)>0);
      if(anim||trans)out.push((el.id?'#'+el.id:el.tagName.toLowerCase()+'.'+String(el.className).split(' ')[0])+(pseudo||'')+' '+(anim?cs.animationName:'transition '+cs.transitionProperty))}}
  return out})()"""


def test_reduced_motion(tmp_path):
    """Sous `prefers-reduced-motion: reduce`, rien ne bouge dans la coque — roue
    ouverte, rail en travail (anneau pulsant), enregistrement, aperçu, alertes —
    et la roue s'ouvre sans attendre une fin de transition."""
    base = [*WHEEL_OPEN, ["eval", "wheel", WHEEL_STATE, 50], ["eval", "moving_wheel", MOVING, 50],
            ["key", "k", "Escape", 300],
            ["click", "pill", '#bgPills [data-bg-cat="failed"]', 600], ["eval", "moving_pop", MOVING, 50]]
    seed = {**BUSY, "captures": [AUDIO, VIDEO], "mode": MODE, "previews": PREVIEWS}
    reduced, normal = _centre(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "reducedMotion": True, "actions": base},
                                         {"width": 1440, "height": 900, "seed": seed, "actions": base}])
    r = reduced["results"]
    assert r["wheel"]["open"] is True, r["wheel"]
    assert r["moving_wheel"] == [] and r["moving_pop"] == [], (r["moving_wheel"], r["moving_pop"])
    # Sans la préférence, la même coque bouge : le relevé n'est pas vide pour une mauvaise raison.
    assert normal["results"]["moving_wheel"], "aucun mouvement relevé sans la préférence : la mesure ne prouverait rien"


FORCED = r"""(()=>{const pick=s=>[...document.querySelectorAll(s)].filter(e=>e.checkVisibility());
  const border=e=>{const cs=getComputedStyle(e);return cs.borderTopStyle!=='none'&&parseFloat(cs.borderTopWidth)>0&&cs.borderTopColor!=='rgba(0, 0, 0, 0)'};
  const out={forced:matchMedia('(forced-colors: active)').matches,noEdge:[]};
  for(const e of pick('#toolWheel .tw-anchor,#bgPills .bgpill,#hiddenEye,#recIndicators .ri-chip,#interactionModeButton,#chatTab,.dock button,#presentationRail .jvr-item'))
    if(!border(e))out.noEdge.push(e.id||e.className);
  out.pillIcons=pick('#bgPills .bgpill').map(p=>!!p.querySelector('svg'));
  return out})()"""


@pytest.mark.parametrize("theme", THEMES)
def test_forced_colors(tmp_path, theme):
    """Couleurs forcées (contraste élevé de Windows) : chaque commande garde un
    bord visible, les pastilles leur icône (jamais la couleur seule), et
    l'anneau de focus reste visible au clavier."""
    shots = _evidence(tmp_path)
    seed = {**BUSY, "captures": [AUDIO], "mode": MODE, "previews": PREVIEWS}
    step = _centre(tmp_path, [{"width": 1440, "height": 900, "theme": theme, "seed": seed, "forcedColors": True, "actions": [
        ["eval", "read", FORCED, 50], *WHEEL_OPEN, ["eval", "audit", _audit("#toolWheel .tw-panel"), 50],
        ["shot", "shot", str(shots / f"forced-colors-{theme}.png"), 50]]}])[0]
    r = step["results"]
    assert r["read"]["forced"] is True
    assert r["read"]["noEdge"] == [], ("commande sans bord en couleurs forcées", r["read"]["noEdge"])
    assert r["read"]["pillIcons"] and all(r["read"]["pillIcons"]), r["read"]
    _focus_ring(r["audit"], f"forced-{theme}")
    assert r["audit"]["unnamed"] == [] and r["audit"]["overlaps"] == [], r["audit"]


#: Une puce d'enregistrement : tout ce qu'elle montre, hors la durée qui avance (`.ri-time`) et le texte réservé
#: (`.ri-sr`), est dans son nom (« REC », l'écran choisi) ; liste des puces qui y manquent (QA S09 P6).
CHIP_WORDS = r"""(()=>{const norm=t=>t.toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  return [...document.querySelectorAll('#recIndicators .ri-chip')].map(c=>{const k=c.cloneNode(true);
    k.querySelectorAll('.ri-time,.ri-sr,[hidden]').forEach(n=>n.remove());
    return {words:norm(k.textContent),name:norm(c.getAttribute('aria-label')||'')}}).filter(x=>!x.words.split(' ').filter(Boolean).every(w=>x.name.split(' ').includes(w))).map(x=>x.words+' ⊄ '+x.name)})()"""


def test_axe_when_available(tmp_path):
    """axe-core sur la coque (`JARVIS_AXE_JS` : axe.min.js ; ce n'est pas une
    dépendance du dépôt), dans les deux thèmes : état chargé (deux
    enregistrements), roue et sous-arc ouverts, popover d'alertes, sélecteur de
    mode, choix du Board, menu d'une carte du rail, aperçu de capture. Aucune
    violation hors des deux exceptions écrites."""
    axe = os.environ.get("JARVIS_AXE_JS")
    if not axe or not Path(axe).is_file():
        pytest.skip("JARVIS_AXE_JS absent (axe-core n'est pas une dépendance du dépôt)")
    seed = {**MIXED, "captures": [AUDIO, VIDEO], "mode": MODE, "previews": PREVIEWS}
    hosts = ("#toolWheel", "#statusCentre", "#interactionModeHud", ".dock", "#presentationRail", "#boardsHud", "#chatTab")
    actions = [["axe", f"axe:{h}", h, 50, axe] for h in hosts]
    actions += [["eval", "chipWords", CHIP_WORDS, 50],
                *WHEEL_OPEN, ["key", "k", "Enter", 600], ["axe", "axe:wheel-open", "#toolWheel", 50, axe],
                ["key", "k", "Escape", 300], ["key", "k", "Escape", 300],
                ["click", "pill", '#bgPills [data-bg-cat="failed"]', 800], ["axe", "axe:bgPop", "#bgPop", 50, axe],
                ["click", "away", ".topbar>.state", 400],
                ["click", "mode", "#interactionModeButton", 600], ["axe", "axe:mode-open", "#interactionModeHud", 50, axe],
                ["key", "k", "Escape", 400],
                ["click", "boards", "#boardsButton", 900], ["axe", "axe:boardsPanel", "#boardsPanel", 50, axe],
                ["key", "k", "Escape", 400],
                ["rclick", "railmenu", "#presentationRail .jvr-item", 700], ["axe", "axe:railMenu", ".jvr-menu", 50, axe],
                ["key", "k", "Escape", 400], ["click", "away", ".topbar>.state", 400],
                *WHEEL_OPEN, ["key", "v", "ArrowDown", 120], ["key", "s", "ArrowDown", 120], ["key", "shoot", "Enter", 1600],
                ["axe", "axe:preview", "#screenshotPreview", 50, axe]]
    steps = _centre(tmp_path, [{"width": 1440, "height": 900, "theme": theme, "seed": seed, "actions": actions} for theme in THEMES])
    for theme, step in zip(THEMES, steps):
        results = step["results"]
        # « REC » et l'écran choisi sont dans le nom de chaque puce : seule la durée qui avance en reste dehors.
        assert results["chipWords"] == [], (theme, results["chipWords"])
        seen = 0
        for name, violations in results.items():
            if name.startswith("axe:"):
                seen += 1
                assert isinstance(violations, list), (theme, name, violations)
                # Exceptions écrites, une seule règle (WCAG 2.5.3, `label-content-name-mismatch`), deux surfaces
                # (docs/control-center-shell.md › Accessibility) : la puce d'un enregistrement montre une durée qui
                # avance, qu'un nom ne porte jamais (réannoncée chaque seconde) — son nom porte tout le reste de ce
                # qu'elle montre (`chipWords` ci-dessus), la durée passe par `aria-describedby` ; une carte du rail
                # montre titre, moteur, variantes, état et âge, son nom dit le titre (en tête, ce que la commande
                # vocale cherche) puis l'état en clair. Toute autre violation échoue.
                allowed = ('class="ri-chip"', 'class="jvr-item"')
                rest = [v for v in violations if not (v["id"] == "label-content-name-mismatch"
                                                      and all(any(a in h.split(">", 1)[0] for a in allowed) for h in v["html"]))]
                assert rest == [], (theme, name, rest)
        assert seen == 13, (theme, results.keys())


def test_zoom_200(tmp_path):
    """200 % : une fenêtre 1440×900 zoomée laisse 720×450 px CSS à l'échelle 2
    (émulation fidèle du zoom du navigateur, les points d'arrêt étroits
    s'appliquent). Tout reste dans l'écran, rien ne se couvre, la roue s'ouvre
    et tient dans la hauteur, l'aperçu de capture aussi."""
    shots = _evidence(tmp_path)
    seed = {**BUSY, "mode": MODE, "previews": PREVIEWS}
    steps = _centre(tmp_path, [
        {"width": 720, "height": 450, "scale": 2, "theme": theme, "seed": seed, "actions": [
            ["eval", "rest", _audit(), 50],
            *WHEEL_OPEN, ["eval", "open", _audit("#toolWheel .tw-panel"), 50],
            ["key", "v", "ArrowDown", 120], ["key", "s", "ArrowDown", 120], ["key", "shoot", "Enter", 1600],
            ["eval", "shot_audit", _audit("#screenshotPreview"), 50],
            ["shot", "shot", str(shots / f"zoom-200-{theme}.png"), 50]]} for theme in THEMES])
    for theme, step in zip(THEMES, steps):
        r = step["results"]
        for name in ("rest", "open", "shot_audit"):
            _clean(r[name], f"zoom-{theme}-{name}")
        _focus_ring(r["open"], f"zoom-{theme}")
        assert _errors(step) == [], _errors(step)


@pytest.mark.parametrize("size", [(700, 800), (1280, 560), (700, 560)], ids=["narrow-700", "short-560", "narrow-short"])
def test_narrow_700_and_short_560(tmp_path, size):
    """700 px de large (dernier point de la mise en page étroite), 560 px de
    haut, et les deux : commandes toutes dans l'écran, aucune sur une autre,
    roue ouverte entière, alertes et sélecteur de mode ouverts au premier plan,
    dans les deux thèmes."""
    width, height = size
    shots = _evidence(tmp_path)
    seed = {**BUSY, "mode": MODE, "previews": PREVIEWS}
    plan = [{"width": width, "height": height, "theme": theme, "seed": seed, "actions": [
        ["eval", "rest", _audit(), 50],
        *WHEEL_OPEN, ["eval", "wheel", _audit("#toolWheel .tw-panel"), 50], ["key", "k", "Escape", 300],
        ["click", "pill", '#bgPills [data-bg-cat="failed"]', 800], ["eval", "pop", _audit("#bgPop"), 50],
        ["click", "away", ".topbar>.state", 400],
        ["click", "mode", "#interactionModeButton", 600], ["eval", "mode", _audit("#interactionModeHud .im-pop"), 50],
        ["shot", "shot", str(shots / f"size-{width}x{height}-{theme}.png"), 50]]} for theme in THEMES]
    for theme, step in zip(THEMES, _centre(tmp_path, plan)):
        r = step["results"]
        for name in ("rest", "wheel", "pop", "mode"):
            _clean(r[name], f"{width}x{height}-{theme}-{name}")
        assert _errors(step) == [], _errors(step)


# ------------------------------------------------------------------ reliquats S01-S08

#: Bandeau GPT-Live, plateau de dépôt (un envoi) et deux infusions.
LIVE = {"visible": True, "state": "active", "elapsed_seconds": 65}
TRAY = r"""(()=>{const t=document.getElementById('boardDropTray');t.hidden=false;
  const ul=document.getElementById('boardDropList');ul.textContent='';const li=document.createElement('li');
  li.className='board-drop-item';li.dataset.status='uploading';li.textContent='rapport.pdf — envoi 40 %';ul.appendChild(li);return 1})()"""
TOASTS = "(()=>{toast({title:'Tâche terminée',sub:'Résumé prêt',ms:60000});toast({title:'Sous-agent',sub:'Build en échec',ms:60000});return 1})()"
PANEL_OPEN = "(()=>{document.getElementById('panel').classList.add('open');return 1})()"
STACK = r"""(()=>{const box=el=>{if(!el||el.closest('[hidden]')||!el.checkVisibility())return null;const r=el.getBoundingClientRect();
  return r.width>0?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null};const q=s=>document.querySelector(s);
  return {vw:innerWidth,banner:box(q('#liveBanner')),tray:box(q('#boardDropTray')),toasts:[...document.querySelectorAll('#toasts .toast')].map(box).filter(Boolean),
    rail:box(q('#presentationRail')),mode:box(q('#interactionModeButton')),dock:box(q('.dock')),chat:box(q('#chatTab')),panel:box(q('#panel.open')),
    centre:[...document.querySelectorAll('#bgPills .bgpill,#hiddenEye,#recIndicators .ri-chip')].map(box).filter(Boolean),
    topbar:box(q('.topbar'))}})()"""


def _no_overlap(a, b) -> bool:
    return not a or not b or not (min(a["r"], b["r"]) - max(a["l"], b["l"]) > 0.5 and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 0.5)


@pytest.mark.parametrize("theme", THEMES)
def test_banner_tray_toasts_and_rail_never_cover_each_other(tmp_path, theme):
    """QA S01 P1-P3, QA S06/S07/S08 : bandeau GPT-Live, plateau de dépôt,
    infusions et rail (colonne ou onglet) affichés ensemble, panneau fermé puis
    ouvert, aux quatre tailles. Le bandeau reste entre les deux colonnes (sous
    l'onglet du rail à 700 px et moins), le plateau sous le bandeau et sous
    l'onglet, les infusions à gauche du rail et au-dessus du plateau, et un
    panneau ouvert n'est couvert ni par le plateau ni par les infusions."""
    shots = _evidence(tmp_path)
    plan = []
    for (w, h) in VIEWPORTS:
        plan.append({"width": w, "height": h, "theme": theme, "seed": {**MIXED, "live": LIVE, "mode": MODE, "previews": PREVIEWS}, "actions": [
            ["eval", "tray", TRAY, 100], ["eval", "toasts", TOASTS, 500], ["eval", "closed", STACK, 50],
            ["eval", "audit", _audit("#liveBanner", "#boardDropTray"), 50],
            ["shot", "s1", str(shots / f"stack-{theme}-{w}x{h}.png"), 50],
            ["eval", "panel", PANEL_OPEN, 400], ["eval", "opened", STACK, 50],
            ["shot", "s2", str(shots / f"stack-{theme}-{w}x{h}-panel.png"), 50]]})
    for (w, h), step in zip(VIEWPORTS, _centre(tmp_path, plan)):
        r = step["results"]
        c, o = r["closed"], r["opened"]
        where = (theme, w, h)
        assert c["banner"] and c["tray"] and len(c["toasts"]) == 2 and c["rail"], (where, c)
        for name in ("rail", "tray", "dock", "topbar", "mode", "chat"):
            assert _no_overlap(c["banner"], c[name]), (where, "bandeau", name, c["banner"], c[name])
        for name in ("rail", "mode", "chat", "dock"):
            assert _no_overlap(c["tray"], c[name]), (where, "plateau", name, c["tray"], c[name])
        for t in c["toasts"]:
            for name in ("banner", "tray", "rail", "mode", "chat", "dock"):
                assert _no_overlap(t, c[name]), (where, "infusion", name, t, c[name])
            for chip in c["centre"]:
                assert _no_overlap(t, chip), (where, "infusion", "centre d'état", t, chip)
        _clean(r["audit"], f"stack-{theme}-{w}x{h}")
        if w > 700:  # sous 700 px le panneau prend toute la largeur : bandeau et plateau passent dessus par rang (registre)
            assert _no_overlap(o["tray"], o["panel"]), (where, "plateau sur le panneau", o["tray"], o["panel"])
            assert _no_overlap(o["tray"], o["mode"]) and _no_overlap(o["tray"], o["banner"]), (where, o)
            # Sous 940 px, panneau ouvert, la place manque à sa gauche : la pile reste à droite, sur le panneau, le
            # temps d'une infusion (règle d'avant cette tâche, `control_center.html`) ; au-dessus, elle passe à sa gauche.
            for t in o["toasts"]:
                for name in (("panel", "tray", "mode", "dock") if w >= 940 else ("tray", "mode", "dock")):
                    assert _no_overlap(t, o[name]), (where, "infusion, panneau ouvert", name, t, o[name])
        assert _errors(step) == [], _errors(step)


#: Un navigateur sans ancres CSS : chaque déclaration à `anchor(` est retirée par le CSSOM (un parseur qui ne
#: connaît pas `anchor()` la jette entière) ; les règles de repli, séparées, restent.
NO_ANCHOR = r"""(()=>{let n=0;const walk=rules=>{for(const r of rules){if(r.cssRules)walk(r.cssRules);
  if(r.style)for(const p of [...r.style])if(String(r.style.getPropertyValue(p)).includes('anchor(')){r.style.removeProperty(p);n+=1}}};
  for(const s of document.styleSheets){try{walk(s.cssRules)}catch(e){}}return n})()"""


def _inside(box: dict, vw: int, vh: int) -> bool:
    return box["l"] >= -0.5 and box["t"] >= -0.5 and box["r"] <= vw + 0.5 and box["b"] <= vh + 0.5


def test_without_css_anchors_the_fallbacks_hold(tmp_path):
    """QA S09 P1 : un `anchor()` inconnu invalide toute sa déclaration ; la valeur
    de repli vit donc dans une règle séparée, juste avant. Sans aucune
    déclaration à ancre, bandeau GPT-Live, plateau et infusions affichés, panneau
    fermé puis ouvert : rien ne sort de l'écran, le plateau ne passe ni sur le
    lanceur, ni sur l'onglet du rail, ni sur le bandeau (hauteur estimée,
    `--jv-live-fb`), les infusions ni sur eux ni sur le plateau. Sous 700 px le
    panneau ouvert prend toute la largeur : bandeau et plateau passent dessus
    par rang, comme avec les ancres."""
    shots = _evidence(tmp_path)
    sizes = ((500, 700), (600, 800), (900, 600), (1280, 720))
    plan = [{"width": w, "height": h, "theme": "cosmos", "seed": {**MIXED, "live": LIVE, "mode": MODE, "previews": PREVIEWS}, "actions": [
        ["eval", "tray", TRAY, 100], ["eval", "toasts", TOASTS, 500],
        ["eval", "removed", NO_ANCHOR, 300], ["eval", "closed", STACK, 50],
        ["shot", "s1", str(shots / f"no-anchor-{w}x{h}.png"), 50],
        ["eval", "panel", PANEL_OPEN, 400], ["eval", "opened", STACK, 50],
        ["shot", "s2", str(shots / f"no-anchor-{w}x{h}-panel.png"), 50]]} for (w, h) in sizes]
    for (w, h), step in zip(sizes, _centre(tmp_path, plan)):
        r = step["results"]
        assert r["removed"] == 5, ("les cinq déclarations à ancre de control_center.html", r["removed"])
        for state in ("closed", "opened"):
            s = r[state]
            where = (w, h, state)
            assert s["tray"] and len(s["toasts"]) == 2, (where, s)
            for name, box in (("tray", s["tray"]), *(("toast", t) for t in s["toasts"])):
                assert _inside(box, w, h), (where, name, "sort de l'écran", box)
            for name in ("dock", "banner") + (("rail",) if w <= 700 else ()):
                assert _no_overlap(s["tray"], s[name]), (where, "plateau", name, s["tray"], s[name])
            for t in s["toasts"]:
                for name in ("dock", "tray", "banner"):
                    assert _no_overlap(t, s[name]), (where, "infusion", name, t, s[name])
        assert _errors(step) == [], _errors(step)


NODE = '#sceneLayer [data-object-id="jobj_star"]'
NODE_BOX = r"""(()=>{const b=s=>{const e=document.querySelector(s);const r=e.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}};
  return {node:b('%s'),wall:b(%s)}})()"""


@pytest.mark.parametrize("wall", ["#chatTab", "#interactionModeHud .im-btn", "#presentationRail"])
def test_a_held_object_stops_against_the_control(tmp_path, wall):
    """QA S01 P4 : la preuve par un vrai objet tenu, pas par l'appartenance au
    sélecteur. Un vrai glisser souris emmène l'objet au centre de la commande ;
    il s'arrête contre elle (bord à bord, sans la chevaucher) et la place
    commise, rejouée par Core, l'y redessine."""
    step = _centre(tmp_path, [{"width": 1280, "height": 720, "seed": {"mode": MODE}, "actions": [
        ["dragto", "drag", NODE, 1200, wall], ["eval", "after", NODE_BOX % (NODE, json.dumps(wall)), 50]]}])[0]
    r = step["results"]
    node, box = r["after"]["node"], r["after"]["wall"]
    commits = [b["body"] for b in step["bodies"] if b["path"] == "/api/scene/commands" and b["body"].get("op") == "set_geometry"]
    assert len(commits) == 1, ("un lâcher, une place commise", step["bodies"])
    assert _no_overlap(node, box), ("l'objet tenu est entré dans la commande", node, box)
    gap = max(box["l"] - node["r"], node["l"] - box["r"], box["t"] - node["b"], node["t"] - box["b"])
    assert gap <= 4, ("l'objet s'arrête contre la commande, pas avant", gap, node, box)
    assert _errors(step) == [], _errors(step)
