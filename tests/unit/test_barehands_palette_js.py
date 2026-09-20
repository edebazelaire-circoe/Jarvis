"""Palette d'outils Bare Hands du bord gauche, exécutée par node.

Ce que ce fichier épingle :

- la palette offre **exactement les outils installés**, lus du contrat
  (`describeTools()`) et jamais d'une liste recopiée ici ou là-bas ;
- un outil **déclaré sans moteur** n'est pas un contrôle : il est barré, il est
  `aria-disabled`, il dit son motif, et le cliquer n'écrit rien ;
- choisir passe par la **porte canonique** (`JarvisBarehands.tool`), donc par
  `saveSettings`, donc par le fil ; aucun magasin d'outils parallèle ;
- la synchronisation est **bidirectionnelle** : un outil changé depuis la
  console ou rendu par le serveur repeint la bande **l'onglet de réglages
  fermé**, ce qui est le chemin que la décision 11 exige et que rien ne portait
  avant la couture d'outil de cette Slice ;
- `pointer` reste le défaut là où les réglages le disent ;
- le clavier atteint les trois outils, les flèches **déplacent sans choisir**,
  et l'outil actif est lisible autrement que par une teinte ;
- Bare Hands éteint, la palette **reste** et **s'atténue** : elle ne disparaît
  pas (on ne la retrouverait pas) et elle ne fait pas semblant d'agir.

Les contrats et le moteur ne sont pas simulés : ce sont les vrais modules.
Seuls le DOM et le réseau sont des doubles — ce que node n'a pas.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import ControlCenter

# Le monde navigateur est **réutilisé**, pas recopié. `BROWSER_HEAD`/`TIMERS`
# viennent de la Slice 07 ; `PATCH`/`DOM_PATCH` du contrôle de cycle de vie de
# la Slice 01, qui a ajouté à ce monde ce que la palette exige aussi : un
# espace de noms SVG, un focus qui se déplace vraiment, `removeAttribute`, une
# horloge qu'on avance, et les deux emplacements que `control_center.html`
# déclare.
from test_barehands_tools_settings_js import BROWSER_HEAD, TIMERS  # noqa: E402
from test_barehands_hud_js import DOM_PATCH, PATCH  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
HUD = RUNTIME / "control_center_barehands_hud.js"


TAIL = r"""
delete require.cache[require.resolve(SCRIPT_PATH)];
const CORE=require(SCRIPT_PATH);
delete require.cache[require.resolve(HUD_PATH)];
const H=require(HUD_PATH);
const BAREHANDS=window.JarvisBarehands;
const settle=async()=>{for(let i=0;i<12;i+=1)await new Promise(r=>setImmediate(r))};
/* `deepFind` / `deepAll` viennent de `DOM_PATCH` : le monde de la Slice 01 les
   a déjà. Le nom de l'emplacement change, lui, parce que `DOM_PATCH` déclare
   déjà `paletteHost` — deux `const` du même nom dans la même portée est une
   erreur de syntaxe, pas une redéfinition. */
const paletteRoot=document.getElementById(H.DOM.paletteId);
/* Les boutons d'outils d'une bande, dans l'ordre du DOM. */
const toolButtons=root=>deepAll(root,n=>n.attrs&&n.attrs[H.DOM.toolAttribute]!==undefined);
const toolButton=(root,id)=>toolButtons(root).find(n=>n.attrs[H.DOM.toolAttribute]===id)||null;
/* Ce que l'écran **peint**, lu sur les attributs et non sur le modèle : les
   deux doivent coïncider, et c'est la seule façon de le vérifier sans pixels. */
const painted=root=>toolButtons(root).map(n=>({
  id:n.attrs[H.DOM.toolAttribute],
  state:n.attrs[H.DOM.toolStateAttribute],
  pressed:n.attrs['aria-pressed'],
  ariaDisabled:n.attrs['aria-disabled'],
  disabled:!!n.disabled,
  tabindex:n.attrs.tabindex,
  title:n.attrs.title,
}));

/* Une palette **non abonnée**, nourrie d'instantanés choisis : c'est elle qui
   décrit une présentation sans faire tourner un moteur. Celle de la page reste
   branchée sur les vraies coutures, et les tests qui parlent d'elle ne touchent
   pas à celle-ci. */
const sandbox=options=>{
  const o=options||{};
  const box=document.createElement('div');
  box.id='barehandsPaletteSandbox'+Math.random().toString(36).slice(2);
  document.body.appendChild(box);
  const calls=[],logs=[];
  let current=o.tool===undefined?'pointer':o.tool;
  const surface={
    /* La **vraie** forme de la porte : `settings({tool})` rend les réglages
       enregistrés, ou `null` quand rien ne l'a été. Un double qui rendrait
       toujours un succès ne pourrait pas tomber comme la vraie chose. */
    tool(value){
      calls.push(value);
      if(o.refuses)return Promise.resolve(null);
      if(o.throws)return Promise.reject(Object.assign(new Error(o.throws),{code:o.throws}));
      current=value;
      /* La couture rapporte **ce que les réglages appliquent**, pas ce qu'on a
         demandé : c'est elle qui repeint, jamais l'optimisme du clic. */
      palette.renderTool({tool:current});
      return Promise.resolve({tool:current});
    },
  };
  const palette=H.createToolPalette({document,host:box,
    surface:()=>(o.noSurface?null:surface),
    log:(level,event,data)=>logs.push([level,event,data])});
  palette.renderTool({tool:current});
  return {box,palette,calls,logs,surface,
    live:snapshot=>palette.renderLifecycle(snapshot),
    at:()=>current};
};
/* La forme exacte que la couture de cycle de vie publie. */
const snap=over=>Object.assign({lifecycle:'off',state:'off',starting:false,
  code:null,title:'',message:'',enabled:false,busy:false},over||{});
/* **La page est laissée chargée.** Le premier `GET /api/barehands` part à
   l'insertion et atterrit une microtâche plus tard ; un test qui lirait avant
   décrirait une page à moitié chargée, et pire, un test qui écrirait avant
   verrait la réponse du serveur écraser son écriture. C'est un artefact de
   node, pas du produit : dans un navigateur, la réponse arrive avant que
   l'utilisateur n'ait vu la bande. Chaque test part donc d'une page posée. */
await settle();
"""


def browser(setup: str = "") -> str:
    """Le monde navigateur, les deux surfaces installées, et un état de serveur
    posé avant le chargement."""

    return PATCH + BROWSER_HEAD + DOM_PATCH + TIMERS + setup + TAIL


def run_node(tmp_path: Path, source: str, name: str = "palette") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


# ------------------------------------------------ ce que la palette contient


def test_the_palette_draws_exactly_the_installed_tools_from_the_contract(tmp_path):
    """Décision 12 : **seulement** pointeur, main, sélection — et parce que le
    contrat le dit, pas parce que ce module l'a recopié.

    Le test lit donc `INSTALLED_TOOLS` d'un côté et les boutons peints de
    l'autre, et il refuse en plus les quatre noms que le non-objectif du README
    nomme explicitement. Sans la seconde moitié, une palette qui aurait recopié
    la bonne liste passerait — et dériverait au premier outil ajouté."""

    result = run_node(tmp_path, browser() + r"""
      const drawn=toolButtons(paletteRoot).map(n=>n.attrs[H.DOM.toolAttribute]);
      /* Le dessin, pas l'étiquette : la décision d'affinage exige des icônes
         en trait, pas des sigles de trois lettres comme le dock. */
      const glyphs=toolButtons(paletteRoot).map(n=>{
        const svg=(n.children||[])[0];
        return svg?{tag:svg.tag,ns:svg.namespaceURI,stroke:svg.attrs.stroke,
          paths:(svg.children||[]).filter(c=>c.tag==='path').length,
          text:String(n.textContent||'')}:null;
      });
      out({drawn,installed:C.INSTALLED_TOOLS,all:C.TOOLS,glyphs,
        labels:C.INSTALLED_TOOLS.map(id=>C.TOOL_LABEL[id]),
        /* La bande a la sémantique d'une barre d'outils, verticale, et **pas**
           celle du groupe de radios que la Slice 02 a sorti des réglages. */
        strip:(()=>{const s=document.getElementById(H.DOM.paletteStripId);
          return {role:s.attrs.role,orientation:s.attrs['aria-orientation'],
            label:s.attrs['aria-label']}})(),
        /* Chaque outil installé a son dessin : la recette d'extension est
           complète ou elle se dit. */
        art:C.INSTALLED_TOOLS.filter(id=>!H.TOOL_ART[id]),
      });
    """, name="content")

    assert result["drawn"] == result["installed"] == ["pointer", "pan", "select"]
    assert result["all"] == ["pointer", "pan", "select"], \
        "le contrat ne déclare rien de plus ; si cela change, la palette doit le montrer grisé"
    assert result["labels"] == ["Pointeur", "Main", "Sélection"]
    # Aucun outil de la couche d'annotation : non-objectif explicite (décision 12).
    for banned in ("highlighter", "draw", "eraser", "ink", "annotate"):
        assert banned not in result["drawn"], banned
    for glyph in result["glyphs"]:
        assert glyph is not None and glyph["tag"] == "svg"
        assert glyph["ns"] == "http://www.w3.org/2000/svg"
        assert glyph["stroke"] == "currentColor", "du trait, dans le vocabulaire de la Slice 01"
        assert glyph["paths"] >= 1
        assert glyph["text"] == "", "une icône, pas un sigle de trois lettres"
    assert result["strip"] == {"role": "toolbar", "orientation": "vertical",
                               "label": "Outils Bare Hands"}
    assert result["art"] == [], "un outil installé sans dessin doit être vu avant l'utilisateur"


def test_the_active_tool_is_said_three_ways_and_not_by_colour_alone(tmp_path):
    """Le critère que l'Humain juge à l'œil : **lequel est choisi** doit se voir
    immédiatement. Trois canaux et non un : l'attribut d'état (donc le halo et
    le fond), le **rail** de forme, et le **nom** écrit sous la bande. Une
    teinte seule aurait échoué en contraste élevé, en veille de palette, et
    pour un œil qui ne sépare pas le bleu du gris."""

    result = run_node(tmp_path, browser() + r"""
      const {box,palette}=sandbox({tool:'pointer'});
      const read=()=>({
        states:painted(box).map(p=>[p.id,p.state,p.pressed]),
        cap:deepFind(box,n=>n.id===H.DOM.paletteCaptionId).textContent,
      });
      const seen={pointer:read()};
      palette.renderTool({tool:'pan'});seen.pan=read();
      palette.renderTool({tool:'select'});seen.select=read();
      out({seen,
        /* L'échelle des trois états est écrite **une seule fois** dans la
           feuille, comme celle des cinq tons de la Slice 01. */
        ladder:{
          active:/data-bh-tool-state=active\]\{[\s\S]{0,400}?--bh-tool-glow:0 0 0 1px/.test(H.STYLE),
          idleNoGlow:/data-bh-tool-state=idle\]\{[\s\S]{0,300}?--bh-tool-glow:none/.test(H.STYLE),
          absentNoGlow:/data-bh-tool-state=absent\]\{[\s\S]{0,300}?--bh-tool-glow:none/.test(H.STYLE),
        },
        /* Le rail : une forme, pas une couleur. */
        rail:/\.bh-tool\[data-bh-tool-state=active\]::before\{content:''/.test(H.STYLE),
        /* Et l'actif n'est pas vert ici non plus : la décision 5 vaut pour
           toute la famille, et le jeton `--ok` ne doit pas revenir par la bande. */
        green:['--ok','#68e0a0'].filter(t=>H.STYLE.includes(t)),
      });
    """, name="active")

    seen = result["seen"]
    assert dict((s[0], s[1]) for s in seen["pointer"]["states"]) == {
        "pointer": "active", "pan": "idle", "select": "idle"}
    assert dict((s[0], s[1]) for s in seen["pan"]["states"])["pan"] == "active"
    assert dict((s[0], s[2]) for s in seen["select"]["states"]) == {
        "pointer": "false", "pan": "false", "select": "true"}
    assert [seen[k]["cap"] for k in ("pointer", "pan", "select")] == [
        "POINTEUR", "MAIN", "SÉLECTION"]
    assert result["ladder"] == {"active": True, "idleNoGlow": True, "absentNoGlow": True}
    assert result["rail"] is True, "l'outil actif porte une marque de forme, pas seulement une teinte"
    assert result["green"] == []


# ------------------------------------- un outil déclaré sans moteur derrière


def test_a_tool_declared_without_an_engine_is_never_an_enabled_control(tmp_path):
    """**La garantie que cette Slice ne doit pas perdre.** Le contrat sait
    déclarer un outil que rien ne sert (`SERVED_CAPABILITIES`), et c'est pour
    cela que `UNAVAILABLE` existait dans les réglages. On écrit donc ici la
    Slice future — les trois étapes de la recette, sans la quatrième — et on
    regarde la palette : l'outil est **dessiné** (il est au contrat, le cacher
    ferait croire qu'il n'existe pas), **barré**, `aria-disabled`, il porte son
    motif, et le cliquer n'appelle **aucune** porte.

    Il reste sur le chemin du clavier, exprès. `moveTool()`, dans les réglages,
    sautait les outils grisés : leur motif n'était alors lisible que par une
    souris qui survole. C'est le choix que la Slice 02 a déjà tranché dans
    l'autre sens pour « Calibrer… » bloqué, et la palette le suit."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    source = CONTRACTS.read_text(encoding="utf-8")
    declared = source.replace(
        "  const TOOL=Object.freeze({POINTER:'pointer',PAN:'pan',SELECT:'select'});",
        "  const TOOL=Object.freeze({POINTER:'pointer',PAN:'pan',SELECT:'select',INK:'ink'});", 1)
    declared = declared.replace(
        "    [TOOL.SELECT]:'select',\n  });",
        "    [TOOL.SELECT]:'select',\n    [TOOL.INK]:'annotate',\n  });", 1)
    declared = declared.replace(
        "    [TOOL.POINTER]:'Pointeur',[TOOL.PAN]:'Main',[TOOL.SELECT]:'Sélection',",
        "    [TOOL.POINTER]:'Pointeur',[TOOL.PAN]:'Main',[TOOL.SELECT]:'Sélection',"
        "[TOOL.INK]:'Encre',", 1)
    assert "[TOOL.INK]:'annotate'" in declared and "[TOOL.INK]:'Encre'" in declared, \
        "les ancres de la recette du contrat doivent exister"
    victim = tmp_path / "ink-contracts.js"
    victim.write_text(declared, encoding="utf-8")

    # Un monde minuscule : la palette prend son document et sa surface par
    # injection, donc elle s'exerce sans moteur, sans réseau et sans page.
    result = run_node(tmp_path, r"""
      const C=require(%(victim)s);
      %(dom)s
      global.JarvisBarehandsContracts=C;
      global.window.JarvisBarehandsContracts=C;
      delete require.cache[require.resolve(%(hud)s)];
      const H=require(%(hud)s);
      const box=document.createElement('div');document.body.appendChild(box);
      const calls=[],logs=[];
      const palette=H.createToolPalette({document,host:box,
        surface:()=>({tool:v=>{calls.push(v);return Promise.resolve({tool:v})}}),
        log:(l,e,d)=>logs.push([l,e,d])});
      palette.renderTool({tool:'pointer'});
      const all=root=>{
        const found=[];
        const walk=n=>{for(const c of (n.children||[])){
          if(c.attrs&&c.attrs[H.DOM.toolAttribute]!==undefined)found.push(c);walk(c)}};
        walk(root);return found;
      };
      const read=()=>all(box).map(n=>({id:n.attrs[H.DOM.toolAttribute],
        state:n.attrs[H.DOM.toolStateAttribute],ariaDisabled:n.attrs['aria-disabled'],
        disabled:!!n.disabled,tabindex:n.attrs.tabindex,title:n.attrs.title}));
      const before=read();
      /* Le clic que la page ferait vraiment : par l'écouteur, pas par `pick`. */
      all(box).find(n=>n.attrs[H.DOM.toolAttribute]==='ink').fire('click');
      await new Promise(r=>setImmediate(r));
      /* Et le clavier : les flèches doivent **pouvoir** s'y arrêter pour que
         le motif soit lisible autrement qu'au survol. */
      palette.focusAt(3);
      out({before,after:read(),calls,logs,
        declared:C.TOOLS,installed:C.INSTALLED_TOOLS,
        cursor:palette.cursor(),
        focused:document.activeElement?document.activeElement.attrs[H.DOM.toolAttribute]:null,
        unavailable:H.UNAVAILABLE,
        failure:palette.failure()});
    """ % {"victim": json.dumps(str(victim)), "hud": json.dumps(str(HUD)),
           "dom": _MINI_DOM}, name="ink")

    assert result["declared"] == ["pointer", "pan", "select", "ink"]
    assert result["installed"] == ["pointer", "pan", "select"]
    drawn = {row["id"]: row for row in result["before"]}
    # Dessiné — il est au contrat — mais jamais présenté comme utilisable.
    assert set(drawn) == {"pointer", "pan", "select", "ink"}
    assert drawn["ink"]["state"] == "absent"
    assert drawn["ink"]["ariaDisabled"] == "true"
    assert drawn["pointer"]["ariaDisabled"] == "false"
    # `aria-disabled` et **pas** `disabled` : sinon le clavier ne l'atteint plus
    # et le motif devient illisible pour un lecteur d'écran.
    assert drawn["ink"]["disabled"] is False
    assert result["unavailable"] in drawn["ink"]["title"]
    assert "Encre" in drawn["ink"]["title"]
    # Cliquer n'écrit rien, et le refus se dit sous un nom cherchable.
    assert result["calls"] == [], "un outil sans moteur n'appelle aucune porte"
    assert result["unavailable"] in result["failure"]
    assert any(row[1] == "barehands.palette_tool_not_installed"
               and row[2]["code"] == "barehands_tool_not_installed" for row in result["logs"])
    # Le clavier s'y arrête, et l'état peint n'a pas bougé.
    assert result["focused"] == "ink" and result["cursor"] == 3
    assert {row["id"]: row["state"] for row in result["after"]} == \
        {"pointer": "active", "pan": "idle", "select": "idle", "ink": "absent"}


# Le DOM minimal des tests qui n'ont besoin ni de moteur ni de réseau : de quoi
# créer des éléments, déplacer un focus et rejouer un clic. Écrit ici parce
# qu'il décrit **moins** que le monde partagé, pas autre chose.
_MINI_DOM = r"""
const mk=(tag,ns)=>{
  const listeners={};
  const node={tag,namespaceURI:ns||null,attrs:{},children:[],parent:null,
    id:'',className:'',textContent:'',disabled:false,hidden:false,listeners,
    style:{setProperty(){}},
    getAttribute(k){return this.attrs[k]===undefined?null:this.attrs[k]},
    setAttribute(k,v){this.attrs[k]=String(v)},
    removeAttribute(k){delete this.attrs[k]},
    appendChild(c){c.parent=this;this.children.push(c);return c},
    remove(){if(!this.parent)return;const at=this.parent.children.indexOf(this);
      if(at>=0)this.parent.children.splice(at,1);this.parent=null},
    addEventListener(t,fn){(listeners[t]=listeners[t]||[]).push(fn)},
    fire(t,e){for(const fn of (listeners[t]||[]).slice())
      fn(Object.assign({target:this,preventDefault(){}},e||{}))},
    focus(){global.document.activeElement=this},
    getBoundingClientRect:()=>({left:0,top:0,right:0,bottom:0,width:0,height:0}),
  };
  return node;
};
global.window={addEventListener(){}};
global.document={createElement:tag=>mk(tag),createElementNS:(ns,tag)=>mk(tag,ns),
  head:mk('head'),body:mk('body'),activeElement:null,
  getElementById(id){
    const walk=n=>{for(const c of (n.children||[])){
      if(c.id===id)return c;const f=walk(c);if(f)return f}return null};
    return walk(this.body);
  }};
"""


# -------------------------------------------- la porte canonique, et elle seule


def test_choosing_on_the_palette_goes_through_the_canonical_settings_door(tmp_path):
    """Le clic **descend sur `JarvisBarehands.tool`**, c'est-à-dire sur
    `saveSettings({tool})`, c'est-à-dire sur le fil — la même porte que la
    console et que l'onglet appelait avant la décision 11.

    On ne le lit pas sur un double : on le lit sur ce que le **serveur reçoit**
    et sur ce que le **moteur applique**. Un magasin d'outils parallèle aurait
    peint la bonne icône sans qu'aucune des deux valeurs ne bouge, et c'est
    exactement la panne qu'aucune assertion d'écran ne voit."""

    result = run_node(tmp_path, browser("global.SET.open=false;") + r"""
      const click=async id=>{
        toolButton(paletteRoot,id).fire('click');
        await settle();
      };
      const start={engine:BAREHANDS.adapters.interaction.tool(),
        setting:BAREHANDS.tool(),painted:painted(paletteRoot)};
      await click('pan');
      const after=  {engine:BAREHANDS.adapters.interaction.tool(),
        setting:BAREHANDS.tool(),painted:painted(paletteRoot)};
      await click('select');
      const then=   {engine:BAREHANDS.adapters.interaction.tool(),
        setting:BAREHANDS.tool(),painted:painted(paletteRoot)};
      out({start,after,then,
        /* Ce que le serveur a vraiment reçu. La palette n'a pas d'autre
           chemin, et si elle en avait un, cette liste serait vide. */
        wire:server.calls.filter(c=>c.body).map(c=>c.body.tool),
        /* L'onglet Expérimental n'a **jamais** été ouvert : la palette ne
           dépend pas des réglages (contrainte explicite du périmètre). */
        tabOpened:SET.open===true});
    """, name="door")

    assert result["start"]["setting"] == "pointer"
    assert result["after"]["setting"] == "pan" and result["after"]["engine"] == "pan"
    assert result["then"]["setting"] == "select" and result["then"]["engine"] == "select"
    assert result["wire"] == ["pan", "select"], "le choix part sur le fil, il n'est pas peint localement"
    assert result["tabOpened"] is False
    active = lambda shot: [p["id"] for p in shot["painted"] if p["state"] == "active"]  # noqa: E731
    assert active(result["start"]) == ["pointer"]
    assert active(result["after"]) == ["pan"]
    assert active(result["then"]) == ["select"]


def test_an_external_tool_change_repaints_the_palette_with_the_tab_closed(tmp_path):
    """**Le chemin qui n'existait pas avant cette Slice.** Jusqu'ici, un outil
    changé ailleurs n'atteignait l'écran que par `refreshPanel()`, qui ne peint
    que l'onglet Expérimental **ouvert** — donc presque jamais. La couture
    d'outil est à l'outil ce que celle de la Slice 01 est au cycle de vie.

    Trois sources extérieures, une seule bande : la console
    (`JarvisBarehands.tool`), une écriture de réglages qui passe par une autre
    clé et **ne doit rien réveiller**, et la réponse du serveur au chargement.
    La dernière est la plus importante : c'est elle qui décide si un outil
    persisté se voit au rechargement ou seulement au premier clic."""

    result = run_node(tmp_path, browser("global.SET.open=false;server.state.tool='select';") + r"""
      const activeNow=()=>painted(paletteRoot).filter(p=>p.state==='active').map(p=>p.id);
      const cap=()=>document.getElementById(H.DOM.paletteCaptionId).textContent;
      /* 1. Au chargement : ce que le serveur a stocké, pas un défaut d'usine. */
      const loaded={active:activeNow(),cap:cap(),setting:BAREHANDS.tool()};
      /* 2. Depuis la « console », sans toucher à la bande. */
      await BAREHANDS.tool('pan');await settle();
      const fromConsole={active:activeNow(),cap:cap()};
      /* 3. Un réglage qui n'est pas l'outil ne republie rien : un abonné ne
            doit pas avoir à distinguer « ça a changé » de « on a repeint ». */
      const before=BAREHANDS.toolSeam().length;
      const seen=[];
      BAREHANDS.openToolSeam('espion',s=>seen.push(s.tool));
      await BAREHANDS.settings({sensitivity:0.6});await settle();
      const quiet=seen.slice();
      await BAREHANDS.tool('pointer');await settle();
      out({loaded,fromConsole,quiet,after:seen.slice(),
        active:activeNow(),cap:cap(),
        seam:BAREHANDS.toolSeam(),status:BAREHANDS.toolStatus(),
        subscribers:before,
        tabOpened:SET.open===true});
    """, name="external")

    # Un outil persisté se voit **au chargement**, sans premier clic.
    assert result["loaded"] == {"active": ["select"], "cap": "SÉLECTION", "setting": "select"}
    assert result["fromConsole"] == {"active": ["pan"], "cap": "MAIN"}
    # L'instantané est rejoué à l'ouverture (d'où `pan`), puis **rien** tant que
    # l'outil ne bouge pas — un curseur de sensibilité ne réveille personne.
    assert result["quiet"] == ["pan"], "une écriture hors outil ne republie pas"
    assert result["after"] == ["pan", "pointer"]
    assert result["active"] == ["pointer"] and result["cap"] == "POINTEUR"
    assert result["status"] == {"tool": "pointer"}
    assert "palette" in result["seam"] and "espion" in result["seam"]
    assert result["subscribers"] == 1, "la palette est abonnée, et elle est la seule de la page"
    assert result["tabOpened"] is False


def test_the_pointer_stays_the_default_where_the_settings_say_so(tmp_path):
    """`pointer` est le défaut du contrat (`TOOL_DEFAULT`) **et** ce que la
    palette montre quand rien n'a été choisi. Un serveur muet, un réglage
    illisible et une installation neuve doivent donner la même chose — et
    surtout pas « aucun outil », qui laisserait la bande sans rail."""

    result = run_node(tmp_path, browser("delete server.state.tool;") + r"""
      const activeNow=()=>painted(paletteRoot).filter(p=>p.state==='active').map(p=>p.id);
      out({fresh:activeNow(),setting:BAREHANDS.tool(),
        contract:C.TOOL_DEFAULT,
        engine:BAREHANDS.adapters.interaction.tool(),
        /* Et le modèle pur : un nom hors table ne se replie pas en silence sur
           « pointeur » — la bande ne coche alors rien plutôt que de cocher un
           outil que personne n'a demandé. */
        unknown:H.paletteOf('ciseaux',H.presentationOf(null)).active,
        unknownCap:H.paletteOf('ciseaux',H.presentationOf(null)).caption});
    """, name="default")

    assert result["contract"] == "pointer"
    assert result["setting"] == "pointer"
    assert result["engine"] == "pointer"
    assert result["fresh"] == ["pointer"]
    assert result["unknown"] is None and result["unknownCap"] == "—"


def test_a_refused_write_leaves_the_palette_on_what_the_settings_actually_hold(tmp_path):
    """Un refus ne se peint pas comme un succès. Le serveur dit non : le réglage
    revient à sa valeur précédente, et la bande **suit le réglage**, pas le
    clic. Une palette qui aurait gardé l'outil cliqué aurait montré un choix
    que rien n'applique — précisément ce que la règle de la Slice 07 interdit."""

    result = run_node(tmp_path, browser() + r"""
      const activeNow=()=>painted(paletteRoot).filter(p=>p.state==='active').map(p=>p.id);
      server.fail='réseau coupé';
      toolButton(paletteRoot,'pan').fire('click');
      await settle();
      out({active:activeNow(),setting:BAREHANDS.tool(),
        engine:BAREHANDS.adapters.interaction.tool()});
    """, name="refused")

    assert result["setting"] == "pointer", "l'écriture refusée rend l'ancienne valeur"
    assert result["engine"] == "pointer", "et le moteur la reprend aussi"
    assert result["active"] == ["pointer"], "la bande suit le réglage, jamais le clic"


# ------------------------------------------------------------------ clavier


def test_the_keyboard_reaches_every_tool_and_the_arrows_move_without_choosing(tmp_path):
    """Le clavier atteint ce que la souris atteint. Un seul arrêt de tabulation
    — le curseur mouvant que `role="toolbar"` promet — les flèches parcourent
    la bande dans les deux axes, `Home`/`End` vont aux bouts.

    **Et les flèches ne choisissent pas.** `moveTool()`, dans les réglages,
    enregistrait à chaque touche : dans un formulaire c'était la sémantique d'un
    groupe de radios, sur l'écran principal c'est une écriture réseau par
    frappe, et le sens de la main qui change sous les doigts. Le sélecteur de
    mode de la Slice 02 a tranché la même question pour la même raison."""

    result = run_node(tmp_path, browser() + r"""
      const key=(id,k,extra)=>toolButton(paletteRoot,id).fire('keydown',
        Object.assign({key:k},extra||{}));
      const focused=()=>document.activeElement
        ?document.activeElement.attrs[H.DOM.toolAttribute]:null;
      const tabs=()=>painted(paletteRoot).map(p=>[p.id,p.tabindex]);
      const seen={start:{tabs:tabs(),focused:focused()}};
      key('pointer','ArrowDown');seen.down={focused:focused(),tabs:tabs()};
      key('pan','ArrowDown');seen.down2={focused:focused()};
      key('select','ArrowDown');seen.wrap={focused:focused()};
      key('pointer','ArrowUp');seen.wrapBack={focused:focused()};
      key('select','Home');seen.home={focused:focused()};
      key('pointer','End');seen.end={focused:focused()};
      /* L'axe horizontal reste accepté : il marchait dans les réglages, et un
         utilisateur qui l'a appris là ne doit pas le voir cesser de marcher. */
      key('select','ArrowLeft');seen.left={focused:focused()};
      const wroteOnArrows=server.calls.filter(c=>c.body).length;
      /* Une touche qui n'est pas une flèche ne fait rien de spécial : c'est le
         navigateur qui transforme Entrée/Espace en clic sur un `<button>`, et
         réimplanter cela ici aurait été une seconde activation. */
      key('pointer','a');
      const untouched=focused();
      /* Puis le vrai chemin d'activation. */
      toolButton(paletteRoot,'pan').fire('click');
      await settle();
      out({seen,wroteOnArrows,untouched,
        afterPick:{tabs:tabs(),wire:server.calls.filter(c=>c.body).map(c=>c.body.tool)}});
    """, name="keyboard")

    seen = result["seen"]
    # Un seul `tabindex=0`, et il est sur l'outil actif tant que le focus est dehors.
    assert seen["start"]["tabs"] == [["pointer", "0"], ["pan", "-1"], ["select", "-1"]]
    assert seen["down"]["focused"] == "pan"
    assert seen["down"]["tabs"] == [["pointer", "-1"], ["pan", "0"], ["select", "-1"]]
    assert seen["down2"]["focused"] == "select"
    assert seen["wrap"]["focused"] == "pointer", "la bande boucle"
    assert seen["wrapBack"]["focused"] == "select"
    assert seen["home"]["focused"] == "pointer"
    assert seen["end"]["focused"] == "select"
    assert seen["left"]["focused"] == "pan"
    assert result["wroteOnArrows"] == 0, \
        "parcourir la palette au clavier ne change pas le sens de la main"
    assert result["untouched"] == "pan", "une touche quelconque ne déplace rien"
    assert result["afterPick"]["wire"] == ["pan"]
    # Le focus n'est plus dans la bande : le curseur redescend sur l'outil actif.
    assert result["afterPick"]["tabs"] == [["pointer", "-1"], ["pan", "0"], ["select", "-1"]]


# ----------------------------------------------- ce que fait la palette éteinte


def test_the_palette_stays_and_dims_when_bare_hands_is_not_holding_the_camera(tmp_path):
    """**Le choix de cette Slice, et son argument.** Le périmètre autorise la
    palette à suivre la disponibilité de Bare Hands ; il n'impose rien.

    Elle ne **disparaît pas** : la décision 11 la veut atteignable sans ouvrir
    les réglages, et une bande qui s'évapore quand Bare Hands est éteint est
    une bande que personne ne retrouve — l'utilisateur qui vient de rallumer
    n'apprendrait jamais qu'elle existe.

    Elle ne fait pas non plus **semblant d'agir** : éteinte, en panne ou en
    démarrage, elle s'atténue et perd le halo — le halo veut dire « quelque
    chose tourne » depuis la Slice 01, et rien ne tourne.

    Elle garde son **rail** et son **nom** : quel outil est choisi reste vrai,
    puisque le réglage est persisté et s'appliquera au réveil. Et elle ne redit
    **pas** le cycle de vie : le contrôle qui le porte est 100 px plus haut,
    dans la même colonne, et son étiquette dit déjà ÉTEINT / INTERROMPU.

    La veille s'arrête à `sleep` : là, la caméra est tenue et la posture en C
    rend la main tout de suite. C'est la ligne que le contrôle du dessus trace
    déjà (« OFF est le seul où le réveil en C ne peut rien »), reprise et non
    réinventée."""

    result = run_node(tmp_path, browser() + r"""
      const {box,palette,calls}=sandbox({tool:'pan'});
      const read=()=>({
        live:box.attrs['data-bh-live'],
        tone:box.attrs['data-bh-tone'],
        drawn:toolButtons(box).length,
        active:painted(box).filter(p=>p.state==='active').map(p=>p.id),
        cap:deepFind(box,n=>n.id===H.DOM.paletteCaptionId).textContent,
        dormant:palette.model().dormant,
        title:painted(box)[0].title,
      });
      const seen={};
      palette.renderLifecycle(snap({lifecycle:'off',state:'off'}));seen.off=read();
      palette.renderLifecycle(snap({lifecycle:'off',state:'starting',starting:true,enabled:true}));
      seen.starting=read();
      palette.renderLifecycle(snap({lifecycle:'error',state:'error',code:'camera_denied',
        title:'Caméra refusée',message:'Autorisez la caméra.'}));seen.error=read();
      palette.renderLifecycle(snap({lifecycle:'sleep',state:'sleep',enabled:true}));seen.sleep=read();
      palette.renderLifecycle(snap({lifecycle:'active',state:'active',enabled:true}));seen.active=read();
      /* Éteinte, la palette reste **utilisable** : l'outil est un réglage
         persisté, le choisir maintenant est vrai et s'appliquera au réveil.
         Le désarmer aurait forcé un détour par les réglages pour préparer sa
         session — exactement ce que la décision 11 supprime. */
      palette.renderLifecycle(snap({lifecycle:'off',state:'off'}));
      toolButton(box,'select').fire('click');
      await new Promise(r=>setImmediate(r));
      const offPick={calls:calls.slice(),active:read().active};
      /* Une écriture en vol, elle, désarme vraiment : c'est une fraction de
         seconde, et un second clic partirait se faire refuser. */
      palette.renderLifecycle(snap({lifecycle:'active',state:'active',enabled:true,busy:true}));
      const busy=painted(box).map(p=>[p.id,p.disabled,p.state]);
      out({seen,offPick,busy,
        dim:/#barehandsPalette\[data-bh-live=false\]\{opacity:/.test(H.STYLE),
        noGlow:/\[data-bh-live=false\] \.bh-tool\[data-bh-tool-state=active\]\{box-shadow:none\}/.test(H.STYLE),
        hides:/#barehandsPalette\[data-bh-live=false\][^}]*display:none/.test(H.STYLE)});
    """, name="dormant")

    seen = result["seen"]
    # Présente dans les cinq présentations : trois outils, toujours.
    assert [seen[k]["drawn"] for k in ("off", "starting", "error", "sleep", "active")] == [3] * 5
    # Atténuée quand rien ne tient la caméra ; vivante en veille et en actif.
    assert [seen[k]["live"] for k in ("off", "starting", "error")] == ["false"] * 3
    assert [seen[k]["live"] for k in ("sleep", "active")] == ["true", "true"]
    # Le rail et le nom survivent : quel outil est choisi reste vrai.
    assert all(seen[k]["active"] == ["pan"] for k in seen)
    assert all(seen[k]["cap"] == "MAIN" for k in seen)
    # Le motif est lisible, et il parle de l'**outil**, pas du cycle de vie.
    for state in ("off", "starting", "error"):
        assert seen[state]["dormant"], state
        assert seen[state]["dormant"] in seen[state]["title"], state
        assert "l’outil reste choisi" in seen[state]["dormant"], state
    assert seen["off"]["dormant"] != seen["error"]["dormant"] != seen["starting"]["dormant"]
    assert seen["sleep"]["dormant"] is None and seen["active"]["dormant"] is None
    # Éteinte mais utilisable : le choix part et s'appliquera au réveil.
    assert result["offPick"]["calls"] == ["select"]
    assert result["offPick"]["active"] == ["select"]
    # Écriture en vol : vraiment désarmée, et l'état peint ne ment pas.
    assert [row[1] for row in result["busy"]] == [True, True, True]
    assert result["dim"] is True and result["noGlow"] is True
    assert result["hides"] is False, "la palette s'atténue, elle ne disparaît pas"


# --------------------------------------------- fixe, verticale, et à sa place


def test_the_palette_is_fixed_vertical_and_stacked_under_the_hand(tmp_path):
    """Décision 13 : **fixe et verticale**. Déplacer, ancrer et pivoter sont
    reportés, donc rien ici n'en esquisse l'affordance — pas de poignée, pas de
    `draggable`, pas de bascule d'orientation. Et la géométrie de la colonne est
    écrite **une seule fois** : la palette calcule sa position depuis la hauteur
    du contrôle du dessus au lieu d'en tenir une seconde copie, sans quoi le
    jour où l'un des deux bouge le symptôme serait une bande par-dessus une
    étiquette — un défaut visuel qu'aucun test de comportement n'attrape."""

    result = run_node(tmp_path, browser() + r"""
      const rule=re=>{const m=re.exec(H.STYLE);return m?m[0]:null};
      out({
        host:rule(/#barehandsPalette\{[^}]*\}/),
        narrow:rule(/#barehandsPalette\{top:calc\(50%[^}]*\}/),
        strip:rule(/#barehandsPalette \.bh-tools\{[^}]*\}/),
        geo:H.GEO,top:H.PALETTE_TOP,narrowTop:H.PALETTE_NARROW_TOP,
        hud:rule(/#barehandsHud\{position:absolute[^}]*\}/),
        hudNarrow:rule(/#barehandsHud\{top:calc\(50%[^}]*\}/),
        /* Aucune affordance de ce qui est reporté. */
        deferred:['draggable','resize:','cursor:move','cursor:grab',
          'aria-orientation="horizontal"','data-bh-dock'].filter(t=>H.STYLE.includes(t)),
        markup:(()=>{const s=document.getElementById(H.DOM.paletteStripId);
          return {draggable:s.attrs.draggable===undefined?null:s.attrs.draggable,
            orientation:s.attrs['aria-orientation']}})(),
      });
    """, name="geometry")

    host = result["host"]
    assert "position:absolute" in host, "fixe dans la page, pas dans le flux"
    assert "z-index:30" in host, "le rang est déclaré, et il est sous le contrôle (32) et son sélecteur (36)"
    assert "flex-direction:column" in result["strip"], "verticale (décision 13)"
    assert f"top:{result['top']}px" in host and f"left:{result['geo']['left']}px" in host
    # La colonne : le contrôle, son étiquette, puis la palette — sans chevauchement.
    geo = result["geo"]
    assert result["top"] == geo["top"] + geo["button"] + geo["gap"] + geo["capLine"] + geo["split"]
    assert result["top"] > geo["top"] + geo["button"], "la palette est sous le bouton, pas dessus"
    # Et au même endroit relatif sous 700 px, du même côté que le contrôle.
    assert result["narrowTop"] == geo["narrowTop"] + geo["button"] + geo["gap"] \
        + geo["capLine"] + geo["split"]
    assert f"top:calc(50% + {result['narrowTop']}px)" in result["narrow"]
    assert f"left:{geo['narrowLeft']}px" in result["narrow"]
    # Le contrôle de la Slice 01 n'a **pas bougé** : sortir ses quatre nombres
    # dans `GEO` était un déplacement de lieu, pas de valeur.
    assert f"top:{geo['top']}px" in result["hud"] and f"left:{geo['left']}px" in result["hud"]
    assert f"width:{geo['button']}px" in result["hud"]
    assert f"top:calc(50% - {-geo['narrowTop']}px)" in result["hudNarrow"]
    assert f"left:{geo['narrowLeft']}px" in result["hudNarrow"]
    assert result["deferred"] == [], "rien n'esquisse ce que la décision 13 reporte"
    assert result["markup"] == {"draggable": None, "orientation": "vertical"}


# -------------------------------------- les refus, confinés et nommés


def test_the_palette_refuses_its_absences_without_taking_the_hand_down(tmp_path):
    """« Un refus codé plutôt qu'un défaut plausible », et **confiné**.

    Les deux surfaces de ce module tombent séparément. L'emplacement de la
    palette manque dans le balisage : la palette ne s'installe pas, sous un nom
    cherchable, et le contrôle de cycle de vie — qui est le plus important des
    deux (décision 1) — reste entier. Un seul `try` pour les deux aurait fait
    d'un `<div>` oublié la perte de la main."""

    result = run_node(tmp_path, PATCH + BROWSER_HEAD + DOM_PATCH + TIMERS + r"""
      /* La page servie à moitié : l'emplacement de la palette a disparu. */
      paletteHost.remove();
      const errors=[];
      const baseError=console.error;
      console.error=(...args)=>{errors.push(args.join(' '))};
    """ + TAIL + r"""
      console.error=baseError;
      out({errors,
        /* La main est là, abonnée, et peint. */
        hud:!!document.getElementById(H.DOM.triggerId),
        hudSeam:BAREHANDS.lifecycleSeam(),
        toolSeam:BAREHANDS.toolSeam(),
        palette:!!document.getElementById(H.DOM.paletteStripId),
        exposed:typeof window.JarvisBarehandsPalette,
        hudExposed:typeof window.JarvisBarehandsHudControl});
    """, name="absent-host")

    assert result["hud"] is True, "la main survit à l'absence de la palette"
    assert result["hudSeam"] == ["hud"], "et elle reste abonnée au cycle de vie"
    assert result["palette"] is False
    assert result["toolSeam"] == [], "personne n'écoute l'outil, et cela se lit"
    assert result["exposed"] == "undefined" and result["hudExposed"] == "object"
    assert any("barehands.palette_not_installed" in line
               and "barehands_palette_host_missing" in line for line in result["errors"]), \
        result["errors"]


def test_a_palette_without_a_surface_says_so_instead_of_painting_a_choice(tmp_path):
    """Une porte absente ou une surface illisible ne se taisent pas. Le refus
    porte le code, il est journalisé, et la bande **ne bouge pas** : peindre
    l'outil cliqué aurait affirmé un choix que rien n'a enregistré."""

    result = run_node(tmp_path, browser() + r"""
      const seen={};
      {
        const {box,palette,logs}=sandbox({noSurface:true,tool:'pointer'});
        toolButton(box,'pan').fire('click');
        await new Promise(r=>setImmediate(r));
        seen.noSurface={active:painted(box).filter(p=>p.state==='active').map(p=>p.id),
          failure:palette.failure(),logs:logs.map(l=>[l[1],l[2].code||null])};
      }
      {
        const {box,palette,logs}=sandbox({throws:'barehands_tool_unknown',tool:'pointer'});
        toolButton(box,'select').fire('click');
        await new Promise(r=>setImmediate(r));
        seen.throws={active:painted(box).filter(p=>p.state==='active').map(p=>p.id),
          failure:palette.failure(),logs:logs.map(l=>[l[1],l[2].code||null])};
      }
      {
        /* Le refus **silencieux** de `saveSettings` : il rend `null` et a déjà
           dit pourquoi par son propre toast. On ne le redit pas une seconde
           fois, mais il reste distinguable de « rien ne s'est passé » au
           journal — c'est la règle que la Slice 02 a posée pour son menu. */
        const {box,palette,logs}=sandbox({refuses:true,tool:'pointer'});
        toolButton(box,'pan').fire('click');
        await new Promise(r=>setImmediate(r));
        seen.refused={active:painted(box).filter(p=>p.state==='active').map(p=>p.id),
          failure:palette.failure(),logs:logs.map(l=>[l[1],l[2].code||null])};
      }
      {
        const {box,palette,logs}=sandbox({tool:'pointer'});
        await palette.pick('ciseaux');
        seen.unknown={active:painted(box).filter(p=>p.state==='active').map(p=>p.id),
          failure:palette.failure(),logs:logs.map(l=>[l[1],l[2].code||null])};
      }
      out(seen);
    """, name="refusals")

    # Dans les quatre cas, la bande reste sur l'outil que les réglages tiennent.
    for case in ("noSurface", "throws", "refused", "unknown"):
        assert result[case]["active"] == ["pointer"], case
    assert "barehands_palette_surface_missing" in str(result["noSurface"]["logs"])
    assert "n’a pas été pris" in result["noSurface"]["failure"]
    assert "barehands_tool_unknown" in str(result["throws"]["logs"])
    # Refus du serveur : journalisé, jamais redit une seconde fois à l'écran.
    assert ["barehands.palette_tool_refused", None] in result["refused"]["logs"]
    assert result["refused"]["failure"] == ""
    assert "barehands_tool_unknown" in str(result["unknown"]["logs"])
    assert "ciseaux" in result["unknown"]["failure"]


def test_a_tool_consumer_that_throws_takes_neither_the_other_nor_the_panel_down(tmp_path):
    """La couture d'outil hérite des garanties de celle du cycle de vie :
    un consommateur qui lève n'emporte ni son voisin, ni le rafraîchissement du
    panneau. Sans cela, une palette en panne rendrait les réglages inutilisables."""

    result = run_node(tmp_path, browser() + r"""
      const warns=[];
      const baseWarn=console.warn;console.warn=(...a)=>warns.push(String(a[0]));
      const seen=[];
      BAREHANDS.openToolSeam('casseur',()=>{throw new Error('boum')});
      BAREHANDS.openToolSeam('temoin',s=>seen.push(s.tool));
      await BAREHANDS.tool('select');await settle();
      console.warn=baseWarn;
      out({seen,
        active:painted(paletteRoot).filter(p=>p.state==='active').map(p=>p.id),
        setting:BAREHANDS.tool(),
        seam:BAREHANDS.toolSeam(),
        warned:warns.filter(w=>w.includes('casseur')).length,
        /* Un consommateur qui n'est pas une fonction est refusé **nommément**. */
        invalid:(()=>{try{BAREHANDS.openToolSeam('vide',null);return null}
          catch(e){return e.code}})(),
        closed:BAREHANDS.closeToolSeam('casseur')});
    """, name="seam")

    assert result["seen"] == ["pointer", "select"], "le témoin reçoit tout malgré le voisin qui lève"
    assert result["active"] == ["select"], "et la palette peint quand même"
    assert result["setting"] == "select"
    assert result["warned"] >= 1, "la levée se dit, elle ne se tait pas"
    assert result["invalid"] == "barehands_tool_seam_invalid"
    assert set(result["seam"]) == {"palette", "casseur", "temoin"}
    assert result["closed"] == 2


# ------------------------------------ étape 7 : les réglages n'ont plus l'outil


def test_the_served_page_puts_the_tools_on_the_palette_and_not_in_the_settings(tmp_path):
    """**Étape 7 du périmètre**, sur le balisage **réellement servi**.

    Deux moitiés, et il faut les deux. Les réglages n'ont plus de contrôle
    d'outil : ni la section, ni le groupe de radios, ni l'attribut, ni la
    fonction qui les dessinait — la Slice 02 les a **supprimés** plutôt que
    laissés morts, et rien ne les a fait revenir. Et l'outil est atteignable
    ailleurs : la page déclare l'emplacement de la palette, le module le
    remplit, et son rang est au registre d'empilement.

    Les noms de la palette sont **distincts** de ceux des réglages exprès : si
    elle avait repris `data-barehands-tool`, ce test ne saurait plus distinguer
    « la palette est là » de « les réglages ont repris la main »."""

    import asyncio

    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    served = asyncio.run(control.index(None)).text

    # 1. Les réglages n'ont plus rien de l'outil, et les implantations sont
    #    parties avec les marqueurs — pas de code mort qui attende son retour.
    for gone in ('id="barehandsTools"', 'role="radiogroup"', "data-barehands-tool=",
                 "function toolsHtml", "function refreshTools", "function moveTool",
                 'aria-label="Outil Bare Hands"'):
        assert gone not in served, gone
    # 2. Mais l'outil reste un **réglage persisté** : sa porte et son
    #    enregistrement n'ont pas bougé de place.
    assert "tool:value=>value===undefined?view.settings.tool:saveSettings({tool:value})" in served
    # 3. Et il est atteignable depuis l'écran principal : l'emplacement est
    #    déclaré dans la page, avec son rang au registre.
    assert '<div id="barehandsPalette"></div>' in served
    assert "palette d'outils Bare Hands 30" in served
    assert served.index('id="barehandsHud"') < served.index('id="barehandsPalette"'), \
        "la main d'abord, ses outils dessous : c'est la colonne que l'Humain a demandée"
    # 4. La palette le remplit, et elle lit le contrat plutôt qu'une liste.
    assert "createToolPalette" in served and "BH.describeTools()" in served
    assert "installJarvisBarehandsPalette" in served
    # 5. La couture d'outil est servie par le moteur, au-dessus du garde-fou de
    #    l'onglet : c'est ce qui rend la palette indépendante des réglages.
    assert "openToolSeam" in served and "publishTools();" in served
    # L'ordre **dans `refreshPanel`**, lu sur le corps de la fonction et non sur
    # la page entière : la couture de cycle de vie reste la toute première
    # ligne (invariant de la Slice 01), l'outil suit, et les deux passent
    # **avant** le garde-fou de l'onglet — sinon la palette ne verrait rien
    # tant que les réglages sont fermés, c'est-à-dire presque toujours.
    import re as _re

    body = served[served.index("function refreshPanel(){"):]
    body = body[:body.index("if(typeof SET==='undefined'")]
    # Les commentaires portent la moitié du raisonnement de ce module ; on les
    # retire pour lire les **instructions**, et rien qu'elles.
    statements = [line.strip() for line in _re.sub(r"/\*.*?\*/", "", body, flags=_re.S).splitlines()
                  if line.strip()]
    assert statements == ["function refreshPanel(){", "publishLifecycle();",
                          "publishTools();"], statements
