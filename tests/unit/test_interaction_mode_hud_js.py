"""Contrôle de mode d'interaction du bas-gauche, exécuté par node.

Slice 03 de `jarvis-presentation-interaction-mode`. Ce que ce fichier épingle :

- **une présentation par état**, et quatre alors qu'il n'y a que trois modes :
  `assistant` et `presentation` sont des modes en vigueur, `unconfirmed` (Core
  injoignable) et `unknown` (sondage tombé) sont des états que l'on subit et
  qu'**aucune pastille ne coche** — parce que cocher présenterait une valeur
  locale comme autoritaire ;
- `REUNION` est **annoncé** partout et choisissable nulle part, et cela se
  décide sur la donnée (`implemented` / `status` du catalogue `modes`), jamais
  sur son nom ;
- le mode que désigne le **type du Board** et ce qui **tourne** peuvent
  diverger — un Board Réunion garde `REUNION` lisible alors que SIMPLE
  s'applique (décision 02), et l'écran le dit au lieu d'arbitrer ;
- **aucun chemin d'écriture** (Slice 01b de `jarvis-board-ui-wheel-dossier-refactor`) :
  choisir une pastille n'envoie rien, dit que le mode suit le type du Board
  actif (la phrase même du refus serveur) et le journalise ; toutes les
  pastilles sont `aria-disabled` ;
- le clavier atteint tout ce que la souris atteint, les flèches déplacent le
  focus (`menu` / `menuitemradio`), et l'ARIA dit l'état ;
- le rafraîchissement et les onglets multiples suivent le statut canonique :
  deux contrôles nourris du même statut peignent la même chose, et aucun ne
  garde sa propre idée du mode ;
- le module est bien inséré dans la page servie, son emplacement est déclaré
  dans `control_center.html`, ses rangs d'empilement sont au registre, et son
  refus d'installation est **rattrapé** pour ne pas emporter les autres modules.

Seuls le DOM, les minuteries et le réseau sont des doubles — ce que node n'a
pas. Le double réseau est **offert** au contrôle et ne doit jamais être appelé. Le module, lui, est le fichier même que `ControlCenter.index` insère.

**Pourquoi un double de DOM local plutôt que celui des suites Bare Hands.**
`test_barehands_target_js.ELEMENTS` fait dériver `getAttribute('aria-label')`
d'un champ de fixture au lieu de ce que `setAttribute` a écrit : toutes les
assertions ARIA de cette Slice y seraient devenues vraies sans rien prouver. Et
`test_barehands_tools_settings_js.BROWSER_HEAD` construit ses nœuds en analysant
le balisage de l'onglet Expérimental et suppose une caméra. Réutiliser l'un ou
l'autre aurait fait mentir les tests ; le double ci-dessous est petit, et il
échoue là où le navigateur échoue.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    BAREHANDS_HUD_SCRIPT_MARKER,
    INTERACTION_MODE_SCRIPT_FILE,
    INTERACTION_MODE_SCRIPT_MARKER,
    ControlCenter,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE_HTML = RUNTIME / "control_center.html"
MODULE = RUNTIME / INTERACTION_MODE_SCRIPT_FILE

#: L'emplacement déclaré dans la page, et les deux rangs d'empilement que le
#: registre de `control_center.html` lui attribue.
HOST_ID = "interactionModeHud"
BUTTON_RANK = 32
CHOOSER_RANK = 36


# --------------------------------------------------------------- le monde

#: Un DOM juste assez réel pour **échouer** comme le vrai : les écouteurs se
#: déclenchent, le focus se déplace vraiment, `getAttribute` rend ce que
#: `setAttribute` a écrit, et vider un nœud le vide. Un double qui ne peut pas
#: échouer comme le navigateur ne prouve rien.
WORLD = r"""
const M=require(MODULE_PATH);
const out=v=>process.stdout.write(JSON.stringify(v));

const nodes=[];
const makeNode=tag=>{
  const listeners={};
  const el={
    tag,tagName:String(tag).toUpperCase(),id:'',className:'',textContent:'',
    hidden:false,disabled:false,attrs:{},children:[],parent:null,listeners,
    style:{setProperty(k,v){this[k]=v}},
    get firstChild(){return el.children.length?el.children[0]:null},
    setAttribute(k,v){el.attrs[k]=String(v)},
    getAttribute(k){return el.attrs[k]===undefined?null:el.attrs[k]},
    removeAttribute(k){delete el.attrs[k]},
    appendChild(c){if(c.parent)c.parent.removeChild(c);c.parent=el;el.children.push(c);return c},
    removeChild(c){const i=el.children.indexOf(c);if(i>=0){el.children.splice(i,1);c.parent=null}return c},
    remove(){if(el.parent)el.parent.removeChild(el)},
    addEventListener(t,fn){(listeners[t]=listeners[t]||[]).push(fn)},
    fire(t,extra){
      const event={target:el,key:'',shiftKey:false,defaultPrevented:false};
      event.preventDefault=()=>{event.defaultPrevented=true};
      Object.assign(event,extra||{});
      for(const fn of (listeners[t]||[]).slice())fn(event);
      return event;
    },
    focus(){doc.activeElement=el},
    blur(){if(doc.activeElement===el)doc.activeElement=null},
  };
  nodes.push(el);
  return el;
};
const doc={
  activeElement:null,
  createElement:tag=>makeNode(tag),
  createElementNS:(ns,tag)=>makeNode(tag),
  getElementById(id){for(const n of nodes)if(n.id===id)return n;return null},
};
doc.head=makeNode('head');

/* Chercher dans l'arbre comme un test le ferait dans un navigateur. */
const walk=(root,seen)=>{seen.push(root);for(const c of root.children)walk(c,seen);return seen};
const all=root=>walk(root,[]);
const byId=(root,id)=>all(root).find(n=>n.id===id)||null;
const byClass=(root,cls)=>all(root).filter(n=>String(n.className).split(/\s+/).includes(cls));
const chips=host=>byClass(host,'im-opt');

/* Une horloge que l'on avance à la main : sans elle, « l'attente dit depuis
   combien de temps elle dure » ne se vérifie pas. */
let clock=0,seq=1;
const timers=[];
const setTimeoutD=(fn,ms)=>{const id=seq++;timers.push({id,fn,at:clock+(ms||0),every:0});return id};
const setIntervalD=(fn,ms)=>{const id=seq++;timers.push({id,fn,at:clock+ms,every:ms});return id};
const clearD=id=>{const i=timers.findIndex(t=>t.id===id);if(i>=0)timers.splice(i,1)};
const advance=ms=>{
  const end=clock+(ms||0);
  for(let guard=0;guard<10000;guard+=1){
    let due=null;
    for(const t of timers)if(t.at<=end&&(!due||t.at<due.at))due=t;
    if(!due)break;
    clock=due.at;
    if(due.every)due.at=clock+due.every;else clearD(due.id);
    due.fn();
  }
  clock=end;
};
/* Laisser les promesses déjà résolues finir, comme le ferait une frappe
   suivante dans un navigateur. */
const settle=async()=>{for(let i=0;i<8;i+=1)await Promise.resolve()};

/* Le catalogue que `/api/status` publie, tel quel : REUNION y est annoncé et
   marqué non implémenté. Aucun mode n'est écrit en dur dans le module. */
const MODES=[
  {value:'assistant',label:'SIMPLE',status:'ready',implemented:true,
   default_disposition:'visual_and_voice',summary:'Jarvis répond et parle.'},
  {value:'presentation',label:'PRESENTATION',status:'ready',implemented:true,
   default_disposition:'visual_only',summary:'Jarvis montre et se tait.'},
  {value:'meeting',label:'REUNION',status:'planned',implemented:false,
   default_disposition:'silent',summary:'Prévu, sans comportement.'},
];
const status=over=>Object.assign({
  mode:'assistant',label:'SIMPLE',revision:4,epoch:'vie-1',
  source:'core',core_reachable:true,error:null,
  board_mode:'assistant',board_mode_label:'SIMPLE',modes:MODES,
},over||{});
const offline=board=>({
  mode:board||'assistant',label:(board||'assistant')==='presentation'?'PRESENTATION':'SIMPLE',
  revision:null,epoch:null,source:'local',core_reachable:false,
  error:{code:'core_unreachable',message:'Core ne répond pas.'},
  board_mode:board||'assistant',board_mode_label:(board||'assistant')==='presentation'?'PRESENTATION':'SIMPLE',
  modes:MODES,
});

/* Le réseau : la trace de ce qui est **réellement** parti. Le contrôle le
   reçoit (comme la page lui offrirait `api`) et ne doit jamais s'en servir :
   « aucun appel » est une assertion à part entière. */
const makeNet=plan=>{
  const calls=[];
  return {calls,request:async(path,init)=>{
    calls.push({path,method:(init&&init.method)||'GET',
      body:init&&init.body?JSON.parse(init.body):null});
    const step=(plan||[]).shift();
    if(!step)return {};
    if(step.delay)await new Promise(resolve=>{setTimeoutD(resolve,step.delay)});
    if(step.status){
      const error=new Error(step.message||'refus');
      error.status=step.status;error.code=step.code||null;
      throw error;
    }
    return step.body||{};
  }};
};

/* Le montage complet : un contrôle branché sur un statut que le test pilote,
   exactement comme `refreshStatus` le fait une fois par seconde. */
const mount=options=>{
  const opts=options||{};
  const host=makeNode('div');host.id=M.DOM.hostId;
  const net=makeNet(opts.plan||[]);
  const journal=[];
  let canonical=opts.status===undefined?status():opts.status;
  /* Le relevé `presentation` du même statut (Slice 10, P7). Absent : Voice
     hors ligne, exactement ce que `/api/status` rend alors. */
  let report=opts.report===undefined?null:opts.report;
  const control=M.createModeControl({
    document:doc,host,
    now:()=>clock,
    setTimeout:setTimeoutD,
    /* Offerts comme une page d'avant les offrait : ils ne doivent servir à rien. */
    request:net.request,
    refresh:async()=>{control.gate(canonical,report)},
    log:(level,event,data)=>journal.push({level,event,data}),
  });
  control.gate(canonical,report);
  return {host,control,net,journal,
    serve(next,nextReport){canonical=next;if(nextReport!==undefined)report=nextReport},
    presence:()=>{const n=byId(host,M.DOM.presenceId);
      return {shown:!n.hidden,text:n.hidden?'':n.children[1].textContent,
        state:host.getAttribute(M.DOM.presenceAttribute),title:n.getAttribute('title')}},
    trigger:byId(host,M.DOM.triggerId),
    label:()=>byId(host,M.DOM.labelId).textContent,
    sub:()=>byId(host,M.DOM.subId).textContent,
    note:()=>{const n=byId(host,M.DOM.noteId);return n.hidden?'':n.textContent},
    hint:()=>byId(host,M.DOM.hintId).textContent,
    said:()=>byId(host,M.DOM.announceId).textContent,
    chips:()=>chips(host),
    checked:()=>chips(host).filter(c=>c.getAttribute('aria-checked')==='true')
      .map(c=>c.getAttribute(M.DOM.modeAttribute)),
    tabbable:()=>chips(host).filter(c=>c.getAttribute('tabindex')==='0')
      .map(c=>c.getAttribute(M.DOM.modeAttribute)),
    focused:()=>{const at=doc.activeElement;
      return at?(at.getAttribute(M.DOM.modeAttribute)||at.id||at.tag):null},
  };
};
"""


def run_node(tmp_path: Path, source: str, name: str = "mode") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"interaction-mode-{name}.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n"
        + WORLD
        + "(async()=>{"
        + source
        + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8",
        timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


# ------------------------------------------------- la projection, sans DOM


def test_chaque_mode_en_vigueur_a_sa_presentation_et_sa_pastille(tmp_path):
    """Les deux modes activables se peignent chacun sous leur propre ton."""

    result = run_node(tmp_path, """
      const read=block=>{const v=M.viewOf(block,null);
        return {tone:v.tone,selected:v.selected,label:M.captionOf(v),
          sub:M.subOf(v,0),live:v.live,note:M.noteOf(v,'')};};
      out({
        simple:read(status()),
        presentation:read(status({mode:'presentation',label:'PRESENTATION',
          board_mode:'presentation',board_mode_label:'PRESENTATION'})),
      });
    """, name="modes")
    assert result["simple"]["tone"] == "assistant"
    assert result["simple"]["selected"] == "assistant"
    assert result["simple"]["label"] == "SIMPLE"
    # Rien d'urgent quand tout est confirmé et cohérent : la ligne de repos
    # rappelle seulement d'où vient le mode.
    assert result["simple"]["sub"] == ""
    assert result["simple"]["note"]["tone"] == "info"
    assert "type du Board actif" in result["simple"]["note"]["text"]
    assert result["presentation"]["tone"] == "presentation"
    assert result["presentation"]["selected"] == "presentation"
    assert result["presentation"]["label"] == "PRESENTATION"
    assert result["presentation"]["live"] is True


def test_core_injoignable_ne_coche_rien_et_dit_que_la_valeur_est_locale(tmp_path):
    """Le repli local est **nommé**, jamais présenté comme la vérité vivante.

    C'est la règle du contrôle Bare Hands appliquée telle quelle : un état que
    l'on subit ne coche aucune pastille. Ici, l'état subi est « Core ne répond
    pas », et la valeur affichée est le comportement du type du Board."""

    result = run_node(tmp_path, """
      const v=M.viewOf(offline('presentation'),null);
      out({tone:v.tone,selected:v.selected,live:v.live,
        reason:v.reason,label:M.captionOf(v),
        sub:M.subOf(v,0),note:M.noteOf(v,null)});
    """, name="offline")
    assert result["tone"] == "unconfirmed"
    # Aucune pastille cochée : personne ne garantit cette valeur.
    assert result["selected"] is None
    # `live` est faux, et c'est ce qui porte tout : la projection ne garde plus
    # ni `source` ni `revision`, qui n'étaient rendus nulle part — le fait utile
    # est « Core ne confirme pas », plus le code qui dit pourquoi.
    assert result["live"] is False
    assert result["reason"] == "core_unreachable"
    # Le libellé reste lisible — on ne cache pas la préférence — mais la ligne
    # du dessous dit ce qu'elle vaut.
    assert result["label"] == "PRESENTATION"
    assert result["sub"] == "NON CONFIRMÉ"
    assert "injoignable" in result["note"]["text"]
    # **Pas** « ceci est la préférence enregistrée » : le serveur rend le mode
    # qui s'appliquerait, et les deux diffèrent précisément sur REUNION.
    assert "qui s’appliquerait" in result["note"]["text"]
    assert "préférence enregistrée" not in result["note"]["text"]
    assert "core_unreachable" in result["note"]["text"]
    # Plus aucune promesse d'appliquer un choix : le mode suivra le type du Board.
    assert "Un choix sera conservé" not in result["note"]["text"]
    assert "suivra le type du Board actif" in result["note"]["text"]


def test_un_statut_illisible_ne_retombe_sur_aucun_mode_plausible(tmp_path):
    """Ne rien savoir s'affiche comme tel, jamais comme le mode par défaut.

    Retomber sur SIMPLE serait le mensonge le moins visible et le plus grave :
    un écran qui affirme le défaut quand il ne sait rien est indiscernable d'un
    écran qui sait."""

    result = run_node(tmp_path, """
      const cases={};
      for(const [name,block] of [['null',null],['array',[]],['texte','assistant'],
          ['vide',{}],['sansMode',{core_reachable:true,modes:MODES}],
          ['nombre',42],['modeVide',{mode:'',core_reachable:true,modes:MODES}]]){
        const v=M.viewOf(block,null);
        cases[name]={tone:v.tone,selected:v.selected,label:M.captionOf(v),
          sub:M.subOf(v,0),options:v.options.length};
      }
      out(cases);
    """, name="garbage")
    for name, seen in result.items():
        assert seen["selected"] is None, name
        assert seen["tone"] == "unknown", name
        assert seen["label"] == "MODE ?", name
        assert seen["sub"] == "STATUT INDISPONIBLE", name
    assert result["null"]["options"] == 0


def test_un_catalogue_illisible_laisse_le_mode_visible_et_dit_qu_il_n_y_a_rien_a_choisir(tmp_path):
    """Le mode effectif et le catalogue sont **deux** faits, pas un.

    Un `modes` illisible n'invalide pas le champ `mode`, qui vient de Core et
    reste vrai : cacher le mode en vigueur parce que la liste des choix est
    cassée retirerait de l'écran la seule information encore fiable. Mais rien
    n'est coché — on ne sait pas si ce mode est choisissable — et le sélecteur
    dit pourquoi il est vide, au lieu de s'ouvrir sur rien."""

    result = run_node(tmp_path, """
      const m=mount({status:status({mode:'presentation',label:'PRESENTATION',modes:'oui'})});
      m.control.open();
      const v=m.control.presentation();
      out({tone:v.tone,selected:v.selected,label:m.label(),
        options:v.options.length,pastilles:m.chips().length,note:m.note()});
    """, name="no-catalog")
    # Le mode reste lisible : c'est Core qui le dit, et il ne dépend pas du
    # catalogue.
    assert result["tone"] == "presentation"
    assert result["label"] == "PRESENTATION"
    # Mais rien n'est coché et rien n'est proposé.
    assert result["selected"] is None
    assert result["options"] == 0
    assert result["pastilles"] == 0
    # Et le sélecteur ne s'ouvre pas sur un silence.
    assert "aucun mode" in result["note"]


def test_reunion_est_presente_partout_et_choisissable_nulle_part(tmp_path):
    """L'affordance vient de la **donnée**, pas du nom du mode.

    Le catalogue porte `implemented` et `status` ; c'est lui qui décide. Un test
    qui chercherait la chaîne « meeting » passerait alors même que le module
    aurait codé la réserve en dur — et le jour où REUNION sera implémenté, rien
    ne tomberait."""

    result = run_node(tmp_path, """
      const v=M.viewOf(status(),null);
      const byValue=Object.fromEntries(v.options.map(o=>[o.value,o]));
      /* Le même catalogue, REUNION passé implémenté : le module doit le rendre
         choisissable sans qu'une ligne change. */
      const ouvert=M.viewOf(status({modes:MODES.map(m=>m.value==='meeting'
        ?Object.assign({},m,{implemented:true,status:'ready'}):m)}),null);
      /* Et l'inverse : SIMPLE déclaré non implémenté doit cesser de l'être. */
      const ferme=M.viewOf(status({modes:MODES.map(m=>m.value==='assistant'
        ?Object.assign({},m,{implemented:false,status:'planned'}):m)}),null);
      out({
        ordre:v.options.map(o=>o.value),
        reunion:{reserved:byValue.meeting.reserved,
          status:byValue.meeting.status,label:byValue.meeting.label,
          summary:byValue.meeting.summary},
        reunionOuverte:!ouvert.options.find(o=>o.value==='meeting').reserved,
        simpleFerme:!ferme.options.find(o=>o.value==='assistant').reserved,
        simpleFermeCoche:ferme.selected,
      });
    """, name="reunion")
    # Les trois modes sont présentés, dans l'ordre du serveur.
    assert result["ordre"] == ["assistant", "presentation", "meeting"]
    assert result["reunion"]["label"] == "REUNION"
    assert result["reunion"]["reserved"] is True
    assert result["reunion"]["status"] == "planned"
    # Le texte qui explique la réserve vient du serveur, pas d'une table recopiée.
    assert result["reunion"]["summary"]
    # La donnée gouverne, dans les deux sens.
    assert result["reunionOuverte"] is True
    assert result["simpleFerme"] is False
    # Un mode effectif que le catalogue dit réservé n'est pas cru.
    assert result["simpleFermeCoche"] is None


def test_le_mode_du_type_du_board_et_le_mode_en_vigueur_restent_nommes_a_part(tmp_path):
    """Décision 02 : un Board Réunion ne fait pas disparaître REUNION de l'écran.

    `board_mode_label` est le mode que désigne le type du Board, `label` ce qui
    tourne. La divergence se lit sans ouvrir le détail."""

    result = run_node(tmp_path, """
      const v=M.viewOf(status({board_mode:'meeting',board_mode_label:'REUNION'}),null);
      const chip=v.options.find(o=>o.value==='meeting');
      out({selected:v.selected,diverged:v.diverged,label:M.captionOf(v),
        sub:M.subOf(v),boardLabel:v.boardLabel,
        note:M.noteOf(v,null),reunionBoard:chip.board,reunionReserved:chip.reserved,
        parle:M.labelOf(v)});
    """, name="diverge")
    # Ce qui tourne est coché ; ce que désigne le type du Board est dit, pas coché.
    assert result["selected"] == "assistant"
    assert result["reunionBoard"] is True
    assert result["reunionReserved"] is True
    assert result["diverged"] is True
    assert result["label"] == "SIMPLE"
    assert result["sub"] == "BOARD : REUNION"
    assert result["boardLabel"] == "REUNION"
    assert "Type du Board : REUNION" in result["note"]["text"] and "SIMPLE" in result["note"]["text"]
    # La phrase du lecteur d'écran porte la même distinction, sans « choisi ».
    assert "en vigueur" in result["parle"] and "type du Board" in result["parle"]
    assert "choisi" not in result["parle"]


def test_un_refus_passe_devant_tout_le_reste_et_garde_son_propre_ton(tmp_path):
    """Une explication prime sur un état durable — et elle n'est pas forcément rouge.

    « Le mode suit le type du Board » est une règle assumée : peinte dans le
    rouge du danger, elle se lirait comme « le changement a échoué »."""

    result = run_node(tmp_path, """
      const v=M.viewOf(offline('presentation'),null);
      out({
        panne:M.noteOf(v,{text:'Refusé par le serveur.',tone:'bad'}),
        reserve:M.noteOf(v,{text:'REUNION est réservé.',tone:'warn'}),
        derive:M.noteOf(v,{text:M.DERIVED,tone:'warn'}),
        sansTon:M.noteOf(v,{text:'Sans ton.'}),
        sans:M.noteOf(v,null),
      });
    """, name="note-order")
    assert result["panne"] == {"tone": "bad", "text": "Refusé par le serveur."}
    # Les deux refus qui ne sont pas des pannes gardent leur propre ton.
    assert result["reserve"]["tone"] == "warn"
    assert result["derive"]["tone"] == "warn"
    # Sans ton déclaré, le sens sûr reste le rouge.
    assert result["sansTon"]["tone"] == "bad"
    assert result["sans"]["tone"] == "wait"


# ------------------------------------------------------- clavier et focus


def test_les_fleches_deplacent_le_focus_sans_jamais_choisir(tmp_path):
    """`menu` + `menuitemradio` : les flèches déplacent le focus, rien ne part.

    L'assertion qui compte est « aucun appel », et toutes les pastilles sont
    inertes (`aria-disabled`) sans cesser d'être atteignables."""

    result = run_node(tmp_path, """
      const m=mount();
      const roles={pop:byId(m.host,M.DOM.chooserId).getAttribute('role'),
        chips:m.chips().map(c=>c.getAttribute('role'))};
      /* Flèche bas sur le bouton : le sélecteur s'ouvre et le focus entre. */
      m.trigger.fire('keydown',{key:'ArrowDown'});
      const ouvert=m.control.isOpen();
      const parcours=[m.focused()];
      const chips=m.chips();
      chips[0].fire('keydown',{key:'ArrowDown'});parcours.push(m.focused());
      chips[1].fire('keydown',{key:'ArrowDown'});parcours.push(m.focused());
      /* Jusque sur REUNION, qui reste atteignable — c'est tout le propos
         d'`aria-disabled` plutôt que `disabled`. */
      chips[2].fire('keydown',{key:'ArrowDown'});parcours.push(m.focused());
      chips[0].fire('keydown',{key:'End'});parcours.push(m.focused());
      chips[2].fire('keydown',{key:'Home'});parcours.push(m.focused());
      await settle();
      const apres={checked:m.checked(),tabbable:m.tabbable(),appels:m.net.calls.length};
      chips[0].fire('keydown',{key:'Escape'});
      out({roles,ouvert,parcours,apres,ferme:!m.control.isOpen(),
        focusApresEchap:m.focused(),
        expanded:m.trigger.getAttribute('aria-expanded'),
        ariaDisabled:m.chips().map(c=>c.getAttribute('aria-disabled')),
        htmlDisabled:m.chips().map(c=>!!c.disabled)});
    """, name="keyboard")
    # Le vocabulaire ARIA, littéralement.
    assert result["roles"]["pop"] == "menu"
    assert result["roles"]["chips"] == ["menuitemradio"] * 3
    assert result["ouvert"] is True
    # Le focus descend, boucle, et Home/End vont aux extrémités.
    assert result["parcours"] == [
        "assistant", "presentation", "meeting", "assistant", "meeting", "assistant",
    ]
    # **Six déplacements de focus, zéro appel réseau et zéro changement coché.**
    assert result["apres"]["appels"] == 0
    assert result["apres"]["checked"] == ["assistant"]
    # Un seul arrêt de tabulation dans le menu : le curseur.
    assert len(result["apres"]["tabbable"]) == 1
    assert result["ferme"] is True
    assert result["focusApresEchap"] == "interactionModeButton"
    assert result["expanded"] == "false"
    # Toutes les pastilles sont `aria-disabled`, pas `disabled` : atteignables,
    # donc capables de dire pourquoi elles ne se choisissent pas (Slice 01b).
    assert result["ariaDisabled"] == ["true", "true", "true"]
    assert result["htmlDisabled"] == [False, False, False]


def test_refermer_le_selecteur_remet_le_bandeau_sur_le_mode_courant(tmp_path):
    """Rouvert, le detail decrivait un autre mode que celui en vigueur.

    Le bandeau du bas garde le resume de la derniere option survolee ou
    focalisee. Apres un Escape, il continuait donc de decrire REUNION alors que
    le mode en vigueur etait SIMPLE — une description qui ne correspond a rien
    de ce que l'ecran montre."""

    result = run_node(tmp_path, """
      const m=mount();
      m.control.open();
      const chips=m.chips();
      const depart=m.hint();
      /* L'utilisateur parcourt jusqu'a REUNION, puis renonce. */
      chips[2].fire('mouseenter');
      const survole=m.hint();
      chips[2].fire('keydown',{key:'Escape'});
      const apresEchap=m.hint();
      m.control.open();
      out({depart,survole,apresEchap,aLOuverture:m.hint()});
    """, name="hint-reset")
    # Au depart, le bandeau decrit le mode en vigueur.
    assert result["depart"] == "Jarvis répond et parle."
    # Il suit le survol…
    assert result["survole"].startswith("Prévu, sans comportement.")
    # …et **revient** au mode courant des que le selecteur se referme.
    assert result["apresEchap"] == "Jarvis répond et parle."
    assert result["aLOuverture"] == "Jarvis répond et parle."


def test_le_curseur_de_tabulation_vaut_le_mode_courant_au_repos(tmp_path):
    """Un seul arrêt de tabulation, et c'est le mode en vigueur."""

    result = run_node(tmp_path, """
      const m=mount({status:status({mode:'presentation',label:'PRESENTATION'})});
      const repos=m.tabbable();
      /* Aucun mode en vigueur (Core injoignable) : le curseur ne disparaît pas
         pour autant — un menu sans arrêt de tabulation est inatteignable. */
      m.control.gate(offline('presentation'));
      out({repos,horsLigne:m.tabbable(),coches:m.checked()});
    """, name="roving")
    assert result["repos"] == ["presentation"]
    assert len(result["horsLigne"]) == 1
    assert result["coches"] == []


# --------------------------------------------------------- choisir un mode (inerte)


def test_choisir_un_mode_n_envoie_rien_et_dit_que_le_mode_suit_le_type_du_board(tmp_path):
    """Slice 01b : aucun chemin d'écriture. Le choix est **expliqué**, journalisé, et rien ne bouge.

    Chaque pastille, cliquée : zéro appel réseau (la porte offerte n'est jamais
    prise), le mode coché reste celui du statut, le détail se rouvre sur la
    phrase du refus serveur, la région vivante la dit, et la console la garde
    sous un nom cherchable avec le code stable."""

    result = run_node(tmp_path, """
      const m=mount();
      const seen={};
      for(const value of ['assistant','presentation','meeting']){
        const done=await m.control.choose(value);
        await settle();
        seen[value]={done,checked:m.checked(),rouvert:m.control.isOpen(),note:m.note(),
          said:m.said(),ton:m.control.failure().tone,
          tonRendu:byId(m.host,M.DOM.noteId).getAttribute('data-im-note')};
        m.control.close({focus:false});
      }
      out({seen,appels:m.net.calls.length,derived:M.DERIVED,
        journal:m.journal.map(l=>({event:l.event,level:l.level,code:l.data.code,mode:l.data.mode,
          board:l.data.board_mode}))});
    """, name="choose-inert")
    from jarvis.domain.interaction_mode import INTERACTION_MODE_DERIVED_MESSAGE

    # La phrase de l'écran est celle du serveur, mot pour mot.
    assert result["derived"] == INTERACTION_MODE_DERIVED_MESSAGE
    # **Zéro appel réseau**, pour les trois.
    assert result["appels"] == 0
    for value, seen in result["seen"].items():
        assert seen["done"] is None, value
        assert seen["checked"] == ["assistant"], value
        assert seen["rouvert"] is True, value
        assert seen["note"].endswith(INTERACTION_MODE_DERIVED_MESSAGE), value
        assert seen["said"].endswith(INTERACTION_MODE_DERIVED_MESSAGE), value
        # Une règle assumée, pas une panne.
        assert (seen["ton"], seen["tonRendu"]) == ("warn", "warn"), value
    # REUNION dit en plus sa réserve.
    assert result["seen"]["meeting"]["note"].startswith("REUNION est réservé")
    assert result["journal"] == [
        {"event": "interaction_mode.choice_derived", "level": "info", "code": "interaction_mode_derived",
         "mode": value, "board": "assistant"}
        for value in ("assistant", "presentation", "meeting")
    ]


def test_un_mode_inconnu_du_catalogue_est_refuse_bruyamment(tmp_path):
    """Un appel programmatique hors catalogue lève sous un code cherchable."""

    result = run_node(tmp_path, """
      const m=mount();
      let code=null;
      try{await m.control.choose('fromage')}catch(e){code=e.code}
      out({code,appels:m.net.calls.length});
    """, name="unknown-mode")
    assert result["code"] == "interaction_mode_hud_unknown"
    assert result["appels"] == 0


def test_core_injoignable_ne_fait_pas_disparaitre_le_mode_du_type_du_board(tmp_path):
    """Decision 02, au moment ou elle compte le plus.

    Un Board Reunion ne doit pas disparaitre du bouton des que Core devient
    injoignable. Le serveur rend alors le comportement du type (SIMPLE), et le
    bandeau dit ce que cette valeur est."""

    result = run_node(tmp_path, """
      /* Core injoignable sur un Board Reunion : le serveur rend le mode qui
         s'appliquerait (SIMPLE). */
      const bloc={mode:'assistant',label:'SIMPLE',revision:null,epoch:null,
        source:'local',core_reachable:false,
        error:{code:'core_unreachable',message:'Core ne repond pas.'},
        board_mode:'meeting',board_mode_label:'REUNION',modes:MODES};
      const m=mount({status:bloc});
      m.control.open();
      const v=m.control.presentation();
      out({label:m.label(),sub:m.sub(),note:m.note(),checked:m.checked(),
        diverged:v.diverged,parle:M.labelOf(v),
        etiquettes:m.chips().map(c=>c.getAttribute(M.DOM.boardAttribute))});
    """, name="offline-diverged")
    # Le mode qui s'appliquerait reste lisible…
    assert result["label"] == "SIMPLE"
    # …et le type du Board **aussi**, sur la meme ligne.
    assert result["sub"] == "NON CONFIRMÉ · BOARD : REUNION"
    # Rien n'est coche : Core ne confirme rien.
    assert result["checked"] == []
    assert result["diverged"] is True
    # Le bandeau ne pretend plus montrer la preference enregistree.
    assert "préférence enregistrée" not in result["note"]
    assert "qui s’appliquerait" in result["note"]
    assert "Type du Board : REUNION" in result["note"]
    # La phrase du lecteur d'ecran porte les deux faits.
    assert "non confirmé" in result["parle"]
    assert "REUNION est le mode du type du Board" in result["parle"]
    # Et la pastille REUNION garde sa marque.
    assert result["etiquettes"] == ["false", "false", "true"]


def test_un_refus_cesse_de_masquer_ce_que_l_on_subit_ensuite(tmp_path):
    """Une explication locale ne bouge jamais le mode, donc `gate()` ne l'efface pas.

    La fermeture l'efface : sinon le detail montrerait encore la phrase sur
    REUNION alors que Core est devenu injoignable entre-temps."""

    result = run_node(tmp_path, """
      const m=mount();
      await m.control.choose('meeting');
      await settle();
      const apresRefus={note:m.note(),ouvert:m.control.isOpen()};
      /* L'utilisateur referme : le refus a ete lu. */
      m.control.close({focus:false});
      /* Puis Core tombe. */
      m.control.gate(offline('assistant'));
      m.control.open();
      out({apresRefus,apresFermeture:m.note(),failure:m.control.failure(),
        sub:m.sub()});
    """, name="stale-failure")
    assert "REUNION" in result["apresRefus"]["note"]
    assert result["apresRefus"]["ouvert"] is True
    # **Le refus a expire avec la fermeture**, et l'etat que l'on subit reprend
    # sa place dans le bandeau.
    assert "REUNION" not in result["apresFermeture"]
    assert "injoignable" in result["apresFermeture"]
    assert result["failure"] == ""
    assert result["sub"] == "NON CONFIRMÉ"


# ------------------------------------------- le sondage, les onglets, l'ARIA


def test_un_changement_venu_d_ailleurs_repeint_le_bouton_sans_clic(tmp_path):
    """Le rafraîchissement et les onglets multiples suivent le statut canonique.

    C'est la couture de cette Slice : `refreshStatus` remet le bloc
    `interaction_mode` une fois par seconde, et c'est le **seul** chemin par
    lequel le mode affiché change. Deux contrôles nourris du même statut
    peignent donc la même chose, sans se parler."""

    result = run_node(tmp_path, """
      const a=mount(),b=mount();
      const depart=[a.label(),b.label()];
      /* Personne n'a cliqué : le mode a changé ailleurs (bascule de Board,
         lecture du Studio). Le sondage l'apporte. */
      const suivant=status({mode:'presentation',label:'PRESENTATION',revision:12,
        board_mode:'presentation',board_mode_label:'PRESENTATION'});
      a.control.gate(suivant);b.control.gate(suivant);
      const apres=[a.label(),b.label(),a.checked(),b.checked()];
      /* Et l'onglet qui n'a rien reçu ne garde pas sa propre idée. */
      a.control.gate(status({mode:'assistant',label:'SIMPLE',revision:13}));
      out({depart,apres,retour:{a:a.checked(),b:b.checked()},
        appels:a.net.calls.length+b.net.calls.length});
    """, name="tabs")
    assert result["depart"] == ["SIMPLE", "SIMPLE"]
    assert result["apres"] == ["PRESENTATION", "PRESENTATION",
                               ["presentation"], ["presentation"]]
    # Chaque contrôle suit *son* statut, sans mémoire propre.
    assert result["retour"]["a"] == ["assistant"]
    assert result["retour"]["b"] == ["presentation"]
    # Aucun des deux n'a sondé de son côté : une seule source, celle de la page.
    assert result["appels"] == 0


def test_un_sondage_tombe_cesse_d_afficher_une_valeur_que_rien_ne_confirme(tmp_path):
    """`statusLost` : garder la dernière valeur connue serait la présenter comme
    vivante alors que plus rien ne la garantit."""

    result = run_node(tmp_path, """
      const m=mount({status:status({mode:'presentation',label:'PRESENTATION'})});
      const avant={label:m.label(),checked:m.checked()};
      m.control.statusLost();
      const apres={label:m.label(),sub:m.sub(),checked:m.checked(),
        tone:m.host.getAttribute(M.DOM.toneAttribute),said:m.said()};
      /* Et le sondage qui repart reprend la main. */
      m.control.gate(status({mode:'presentation',label:'PRESENTATION'}));
      out({avant,apres,retour:m.checked()});
    """, name="status-lost")
    assert result["avant"] == {"label": "PRESENTATION", "checked": ["presentation"]}
    assert result["apres"]["label"] == "MODE ?"
    assert result["apres"]["sub"] == "STATUT INDISPONIBLE"
    assert result["apres"]["checked"] == []
    assert result["apres"]["tone"] == "unknown"
    assert "illisible" in result["apres"]["said"]
    assert result["retour"] == ["presentation"]


def test_l_aria_dit_l_etat_et_la_region_vivante_ne_se_repete_pas(tmp_path):
    """Ce que le lecteur d'écran entend, et seulement quand ça change."""

    result = run_node(tmp_path, """
      const m=mount();
      const announce=byId(m.host,M.DOM.announceId);
      const statique={role:announce.getAttribute('role'),
        live:announce.getAttribute('aria-live'),
        haspopup:m.trigger.getAttribute('aria-haspopup'),
        controls:m.trigger.getAttribute('aria-controls'),
        expanded:m.trigger.getAttribute('aria-expanded'),
        type:m.trigger.getAttribute('type')};
      const premier=m.said();
      /* Trois repeintures identiques : la région ne doit pas rabâcher. */
      m.control.gate(status());m.control.gate(status());
      const inchange=m.said()===premier;
      announce.textContent='—';
      m.control.gate(status());
      const silence=announce.textContent;
      m.control.gate(status({mode:'presentation',label:'PRESENTATION'}));
      const change=m.said();
      m.control.open();
      out({statique,premier,inchange,silence,change,
        expandedOuvert:m.trigger.getAttribute('aria-expanded'),
        etiquetteChip:m.chips().map(c=>c.getAttribute('aria-label'))});
    """, name="aria")
    assert result["statique"] == {
        "role": "status", "live": "polite", "haspopup": "menu",
        "controls": "interactionModeChooser", "expanded": "false", "type": "button",
    }
    assert "SIMPLE" in result["premier"]
    assert result["inchange"] is True
    # Une repeinture qui ne change rien n'écrit rien : la région reste telle quelle.
    assert result["silence"] == "—"
    assert "PRESENTATION" in result["change"]
    assert result["expandedOuvert"] == "true"
    # Chaque pastille dit ce qu'elle est, au-delà de sa couleur.
    assert "réservé" in result["etiquetteChip"][2]
    assert "en vigueur" in result["etiquetteChip"][1]


def test_le_texte_qui_explique_chaque_mode_vient_du_serveur(tmp_path):
    """Deux descriptions du même mode finiraient par se contredire."""

    result = run_node(tmp_path, """
      const m=mount();
      const chips=m.chips();
      chips[1].fire('mouseenter');const presentation=m.hint();
      chips[2].fire('mouseenter');const reunion=m.hint();
      out({presentation,reunion});
    """, name="hints")
    assert result["presentation"] == "Jarvis montre et se tait."
    # La réserve est ajoutée à la phrase du serveur, elle ne la remplace pas.
    assert result["reunion"].startswith("Prévu, sans comportement.")
    assert "réservé" in result["reunion"]


# ------------------------------------------ l'installation dans la vraie page


def test_le_module_refuse_son_absence_d_emplacement_sans_emporter_la_page(tmp_path):
    """La page sert tous ses modules dans une seule balise `<script>`.

    Une levée qui remonterait emporterait la scène, la chronologie et le Test
    Lab avec elle. Le refus est donc rattrapé, et il se dit."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "install.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n"
        + WORLD
        + r"""
      const errors=[],infos=[];
      const realError=console.error,realInfo=console.info;
      console.error=line=>errors.push(String(line));
      console.info=line=>infos.push(String(line));
      global.window={setInterval:setIntervalD,clearInterval:clearD,
        setTimeout:setTimeoutD,clearTimeout:clearD};
      global.document=doc;
      /* L'emplacement n'existe pas : le module doit refuser et se taire ensuite. */
      let leve=false;
      try{delete require.cache[require.resolve(MODULE_PATH)];require(MODULE_PATH)}
      catch(e){leve=true}
      const sansHote={leve,errors:errors.slice(),
        installe:typeof global.window.JarvisInteractionModeControl};
      /* Le même module, l'emplacement présent : il s'installe et le dit. */
      errors.length=0;
      const host=makeNode('div');host.id='interactionModeHud';
      global.api=async()=>({});
      global.refreshStatus=async()=>{};
      delete require.cache[require.resolve(MODULE_PATH)];
      require(MODULE_PATH);
      const control=global.window.JarvisInteractionModeControl;
      control.gate(status());
      const avecHote={errors:errors.slice(),infos:infos.slice(),
        portes:Object.keys(control).sort(),
        label:byId(host,'interactionModeLabel').textContent};
      console.error=realError;console.info=realInfo;
      process.stdout.write(JSON.stringify({sansHote,avecHote}));
    """,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    # Sans emplacement : aucune levée ne sort du module, et la console dit pourquoi.
    assert result["sansHote"]["leve"] is False
    assert result["sansHote"]["installe"] == "undefined"
    assert any("interaction_mode.install_failed" in line for line in result["sansHote"]["errors"])
    assert any("interaction_mode_host_missing" in line for line in result["sansHote"]["errors"])
    # Avec emplacement : il s'installe, ne se plaint de rien, et peint.
    assert result["avecHote"]["errors"] == []
    assert any("interaction_mode.hud_installed" in line for line in result["avecHote"]["infos"])
    assert result["avecHote"]["label"] == "SIMPLE"
    # Les deux portes du sondage à 1 Hz, du même nom que celles de la scène.
    assert "gate" in result["avecHote"]["portes"]
    assert "statusLost" in result["avecHote"]["portes"]


def test_un_mode_inconnu_de_cette_page_ne_se_peint_pas_comme_simple(tmp_path):
    """Un serveur plus recent peut annoncer un mode que cette page ignore.

    Il est en vigueur, donc il n'est pas desature ; mais le peindre comme SIMPLE
    serait affirmer qu'il se comporte comme SIMPLE, ce que personne ne peut
    soutenir. Le ton existait et ne peignait rien : aucune regle ne le lisait."""

    result = run_node(tmp_path, """
      const modes=MODES.concat([{value:'atelier',label:'ATELIER',status:'ready',
        implemented:true,default_disposition:'visual_only',summary:'Un mode neuf.'}]);
      const m=mount({status:status({mode:'atelier',label:'ATELIER',
        board_mode:'atelier',board_mode_label:'ATELIER',modes})});
      out({tone:m.host.getAttribute(M.DOM.toneAttribute),label:m.label(),
        checked:m.checked(),pastilles:m.chips().length,
        aUneRegle:M.STYLE.indexOf('[data-im-tone=other]')>=0,
        commeSimple:m.control.presentation().tone===M.TONE.ASSISTANT});
    """, name="other-tone")
    assert result["tone"] == "other"
    assert result["commeSimple"] is False
    # Il est bien en vigueur : son libelle s'affiche et sa pastille est cochee.
    assert result["label"] == "ATELIER"
    assert result["checked"] == ["atelier"]
    assert result["pastilles"] == 4
    # Et la feuille a une regle pour lui, sans quoi le ton ne serait qu'un mot.
    assert result["aUneRegle"] is True


def test_le_libelle_visible_et_le_libelle_lu_ne_peuvent_pas_diverger(tmp_path):
    """Le nom etait grave a la construction, l'etiquette ARIA refaite a chaque
    peinture. Un libelle change cote serveur les faisait se contredire — la meme
    faute que la projection perimee que les tests avaient deja trouvee."""

    result = run_node(tmp_path, """
      const m=mount();
      const avant={noms:m.chips().map(c=>byClass(c,'im-opt-name')[0].textContent),
        aria:m.chips().map(c=>c.getAttribute('aria-label'))};
      /* Le serveur renomme un mode, sans rien changer d'autre. */
      m.control.gate(status({modes:MODES.map(x=>x.value==='presentation'
        ?Object.assign({},x,{label:'PRÉSENTATION PUBLIQUE',
            summary:'Jarvis se tait devant une salle.'}):x)}));
      out({avant,noms:m.chips().map(c=>byClass(c,'im-opt-name')[0].textContent),
        aria:m.chips().map(c=>c.getAttribute('aria-label')),
        decrits:m.chips().map(c=>c.getAttribute('aria-describedby')),
        descriptions:m.chips().map(c=>byClass(c,'im-sr')[0].textContent)});
    """, name="labels")
    assert result["avant"]["noms"] == ["SIMPLE", "PRESENTATION", "REUNION"]
    # Le nom visible suit le serveur…
    assert result["noms"] == ["SIMPLE", "PRÉSENTATION PUBLIQUE", "REUNION"]
    # …et il dit la meme chose que ce qu'un lecteur d'ecran entend.
    assert "PRÉSENTATION PUBLIQUE" in result["aria"][1]
    # Chaque pastille porte SA description, et elle dit ce que le mode fait —
    # ce que le bandeau visible ne transmettait a personne.
    assert result["decrits"] == [
        "interactionModeDesc-assistant",
        "interactionModeDesc-presentation",
        "interactionModeDesc-meeting",
    ]
    assert result["descriptions"][1] == "Jarvis se tait devant une salle."
    assert result["descriptions"][0] == "Jarvis répond et parle."
    # Le mode reserve dit aussi pourquoi il ne se choisit pas.
    assert "réservé" in result["descriptions"][2]


# ---------------------------------------- la page servie et son registre


def test_le_module_est_reellement_insere_dans_la_page_servie(tmp_path):
    """Le fichier est **inséré**, pas servi à part : la page reste un document
    unique sans ressource externe, donc sans cache capable d'en servir une autre
    version que celle du serveur."""

    page = PAGE_HTML.read_text(encoding="utf-8")
    module = MODULE.read_text(encoding="utf-8")
    # Le marqueur est dans la page…
    assert INTERACTION_MODE_SCRIPT_MARKER in page
    # …et `ControlCenter.index` le remplace par le contenu du fichier.
    source = Path(ControlCenter.index.__code__.co_filename).read_text(encoding="utf-8")
    assert "INTERACTION_MODE_SCRIPT_MARKER" in source
    assert "INTERACTION_MODE_SCRIPT_FILE" in source
    served = page.replace(INTERACTION_MODE_SCRIPT_MARKER, module)
    assert INTERACTION_MODE_SCRIPT_MARKER not in served
    assert "JarvisInteractionMode" in served


def test_l_emplacement_est_declare_dans_la_page_et_hors_des_autres_commandes(tmp_path):
    """Le rang d'empilement vit dans le registre de la page, pas dans un script.

    Et le contrôle n'entre ni dans le dock (qui reste six boutons de texte à
    droite), ni dans la barre du haut (dont les événements de pointeur sont
    coupés), ni dans la colonne Bare Hands."""

    raw = PAGE_HTML.read_text(encoding="utf-8")
    assert f'id="{HOST_ID}"' in raw
    dock = raw[raw.index('<nav class="dock"'):raw.index("</nav>")]
    assert HOST_ID not in dock
    topbar = raw[raw.index('<div class="topbar">'):]
    assert HOST_ID not in topbar[:topbar.index("</div>")]
    # L'emplacement est un frère des trois emplacements Bare Hands, pas un enfant.
    # `data-keep-live="run"` (native-studio-playback-fix Slice 09) : vivant au-dessus de Variantes pendant une présentation.
    assert re.search(rf'<div id="{HOST_ID}" data-keep-live="run"[^>]*></div>', raw)


def test_le_registre_d_empilement_nomme_le_controle_et_ses_deux_rangs(tmp_path):
    """Le registre de `control_center.html` est la seule table des rangs.

    Un élément flottant qui n'y figure pas est un rang que personne ne peut
    vérifier en lisant la page — et c'est exactement ce que ce registre existe
    pour empêcher."""

    # Depuis la Slice 01 de l'orbital UI, le registre est `docs/control-center-shell.md`
    # (comparé aux feuilles réelles par `test_control_center_shell_layers.py`), avec
    # un miroir en tête de page.
    raw = PAGE_HTML.read_text(encoding="utf-8")
    registre = (ROOT / "docs" / "control-center-shell.md").read_text(encoding="utf-8")
    assert "| 32 | `#interactionModeHud` | `control_center_interaction_mode.js` | `#${DOM.hostId} .im-btn` |" in registre
    assert "| 36 | `.im-pop` | `control_center_interaction_mode.js` | `#${DOM.hostId} .im-pop` | mode chooser |" in registre
    # Et il dit *pourquoi* les deux contrôles partagent leurs rangs sans jamais se
    # recouvrir : chacun sa zone, le haut du bord gauche et le bas-gauche.
    assert "| `bottom-left` | `#interactionModeHud`" in registre and "| `left-edge` |" in registre
    # Pendant une présentation dans Variantes (9000) : 9150, au-dessus du rail (9100), sous son menu (9300).
    assert "| 9150 | `html.jvx-run #interactionModeHud` |" in registre
    assert re.search(r"@shell-layer 9150: html\.jvx-run #interactionModeHud", raw)


def test_les_rangs_du_module_sont_exactement_ceux_du_registre(tmp_path):
    """Le registre et la feuille doivent dire la même chose.

    Le registre est de la prose ; la feuille est ce qui s'applique. Les laisser
    diverger rendrait le registre trompeur plutôt qu'absent, ce qui est pire."""

    module = MODULE.read_text(encoding="utf-8")
    assert f".im-btn{{position:relative;z-index:{BUTTON_RANK};" in module
    assert f".im-pop{{position:absolute;z-index:{CHOOSER_RANK};" in module
    # **Aucun rang sur l'emplacement lui-même** : un contexte d'empilement y
    # enfermerait le sélecteur (36) sous le rang du bouton (32), donc derrière
    # le panneau (33) et la bannière (35) qu'il doit recouvrir.
    host_rule = module[module.index("#${DOM.hostId}{position:absolute"):]
    assert "z-index" not in host_rule[:host_rule.index("}")]


def test_le_bas_gauche_est_un_rail_partage_et_le_controle_s_y_efface(tmp_path):
    """Le bas-gauche **n'est pas libre**, et ce module l'a d'abord cru.

    Trois elements y vivent deja, tous poses par des feuilles injectees depuis
    du JS — donc invisibles a un audit qui ne lit que `control_center.html`, ce
    qui est exactement l'erreur commise : la pastille Bare Hands, le mot d'un
    geste etouffe, et l'indicateur de scene. Le depot avait deja une convention
    d'evitement pour ce rail ; ce test epingle que ce module la rejoint au lieu
    d'inventer un second decalage."""

    # La feuille est un gabarit : ses selecteurs sont interpoles depuis `GEO`,
    # donc c'est la feuille **produite** qu'il faut lire, pas la source.
    css = run_node(tmp_path, "out({style:M.STYLE,geo:M.GEO});", name="rail")
    module, geo = css["style"], css["geo"]
    barehands = (RUNTIME / "control_center_barehands.js").read_text(encoding="utf-8")
    scene = (RUNTIME / "control_center_scene_page.js").read_text(encoding="utf-8")

    # Les trois occupants sont bien la, au meme offset gauche que ce controle.
    assert "#jarvisHands .jh-badge{position:fixed;left:18px;bottom:18px" in barehands
    assert "#jarvisHands .jh-note{position:fixed;left:18px;bottom:46px" in barehands
    assert ".sc-status{position:absolute;left:18px;bottom:18px" in scene
    # Et la convention d'evitement qui les gouverne.
    assert "body:has(#jarvisHands .jh-badge) .sc-status{bottom:52px}" in scene

    # Ce module emploie la MEME mecanique, et pour les memes selecteurs.
    for rule in (
        "body:has(#jarvisHands .jh-badge) #interactionModeHud{--im-rail:52px}",
        "body:has(.sc-status:not([hidden])) #interactionModeHud{--im-rail:52px}",
        "body:has(#jarvisHands .jh-badge):has(.sc-status:not([hidden]))"
        " #interactionModeHud{--im-rail:86px}",
        "body:has(#jarvisHands .jh-note) #interactionModeHud{--im-rail:86px}",
    ):
        assert rule in module, rule
    # L'echelle monte : un occupant, puis deux. Jamais un barreau plus bas que
    # le repos, ce qui rentrerait dans la pile au lieu d'en sortir.
    rest, one, two = geo["bottom"], geo["railOne"], geo["railTwo"]
    assert rest < one < two
    # La pastille monte a 42 et l'indicateur decale a 76 : chaque barreau les
    # depasse vraiment.
    assert one >= 18 + 24
    assert two >= 52 + 24


def test_le_controle_et_la_colonne_bare_hands_ne_se_croisent_pas(tmp_path):
    """Bare Hands tient le HAUT du bord gauche, ce controle le BAS.

    Vrai a pleine largeur, ou la colonne Bare Hands est ancree par le haut.
    **Faux en dessous de 700 px de large**, ou elle devient relative au centre
    et ou la hauteur de sa palette depend du nombre d'outils installes : elle
    descendait alors dans cette bande, a toutes les hauteurs mesurees. La sortie
    n'est pas verticale mais horizontale — on passe a droite d'une colonne dont
    la largeur, elle, est fixe — et c'est
    `test_interaction_mode_hud_browser.py` qui le mesure dans un vrai
    navigateur, parce que c'est le seul niveau ou cette promesse veut dire
    quelque chose."""

    module = MODULE.read_text(encoding="utf-8")
    hud = (RUNTIME / "control_center_barehands_hud.js").read_text(encoding="utf-8")

    # Pleine largeur : eux par le haut, lui par le bas.
    assert "top:${GEO.top}px;left:${GEO.left}px" in hud
    assert "top:${PALETTE_TOP}px;left:${GEO.left}px" in hud
    assert "bottom:calc(var(--im-rail) + var(--im-lift))" in module
    # Le selecteur s'ouvre vers le haut, et il peut defiler : sinon son sommet
    # sortirait de l'ecran sans retour possible.
    assert ".im-pop{position:absolute;z-index:36;bottom:100%;left:0" in module
    assert "max-height:calc(100vh - var(--im-rail) - var(--im-lift) - 96px)" in module
    assert "overflow-y:auto" in module

    # Sous 700 px la colonne Bare Hands devient relative au centre : c'est la
    # limite, et elle est ecrite dans le module et dans la doc.
    assert "#${DOM.hostId}{top:calc(50% - ${-GEO.narrowTop}px);left:${GEO.narrowLeft}px}" in hud
    assert "#${DOM.paletteId}{top:calc(50% + ${PALETTE_NARROW_TOP}px)" in hud
    assert "devient relative au centre" in module
    # Le degagement est horizontal, et il ne depend pas de la hauteur de la
    # palette : on se place a droite d'une colonne de largeur fixe.
    narrow_left = int(module.split("narrowLeft:")[1].split(",")[0])
    their_left = int(hud.split("narrowLeft:")[1].split(",")[0])
    their_width = int(hud.split("button:")[1].split(",")[0])
    assert narrow_left >= their_left + their_width + 8, (narrow_left, their_left, their_width)
    doc = (ROOT / "docs" / "interaction-mode.md").read_text(encoding="utf-8")
    assert "right of the Bare Hands column" in doc


def test_le_controle_se_hisse_au_dessus_de_l_indication_vocale(tmp_path):
    """Le centre d'etat du bas (orbital-ui Slice 06, qui remplace l'indication
    vocale `.voicehint`) est centre en bas a **toutes** les largeurs.

    Au-dessus de 820 px il garde la largeur de ce bouton de chaque cote ; en
    dessous il ne reserve plus que l'onglet Chat, et ce bouton doit passer
    au-dessus de la rangee. Son bas et sa hauteur se lisent sur la page (jetons
    de la coque `--shell-bottom` et `--shell-status-h`), pas sur une constante
    recopiee : aucun theme ne la deplace."""

    css = run_node(tmp_path, "out({style:M.STYLE,geo:M.GEO});", name="lift")
    module, geo = css["style"], css["geo"]
    raw = PAGE_HTML.read_text(encoding="utf-8")
    work = (RUNTIME / "control_center_work.js").read_text(encoding="utf-8")

    # L'ancienne capsule n'existe plus ; la rangee est posee sur les jetons de la coque.
    assert "voicehint" not in raw and "voicehint" not in work
    assert ".status-centre{position:absolute;left:calc(var(--shell-gutter) + 254px);right:calc(var(--shell-gutter) + 254px);bottom:var(--shell-bottom);min-height:var(--shell-status-h);" in raw
    assert "@media(max-width:820px){.status-centre{left:calc(var(--shell-gutter) + 64px);right:calc(var(--shell-gutter) + 64px)}}" in raw
    assert not re.search(r"status-centre\{[^}]*bottom:", work), "un thème déplace le centre d'état"
    bottom = int(re.search(r"--shell-bottom:(\d+)px", raw).group(1))
    height = int(re.search(r"--shell-status-h:(\d+)px", raw).group(1))
    # Au-dessus de 820 px la marge laterale couvre le bouton le plus large.
    # (marge = gouttière 18 + 254 ; bord droit du bouton = left + maxWidth ; 12 px d air.)
    assert 18 + 254 >= geo["left"] + geo["maxWidth"] + 12, geo

    lift_below, lift, narrow_below = geo["liftBelow"], geo["lift"], geo["narrowBelow"]
    # Le relevement arrive **avant** le resserrement du rail, et au seuil ou la
    # rangee cesse de reserver la largeur du bouton.
    assert lift_below == 820 and lift_below > narrow_below
    # Et le bouton passe vraiment au-dessus d'elle : son bas releve depasse le
    # SOMMET de la rangee (bas + hauteur), pas seulement son bas.
    assert geo["bottom"] + lift > bottom + height
    assert f"@media(max-width:{lift_below}px)" in module
    assert "--im-lift:%dpx" % lift in module


def test_le_sondage_a_1hz_remet_le_bloc_au_controle_et_dit_quand_il_tombe(tmp_path):
    """La couture choisie par cette Slice, vérifiée sur la page servie.

    Deux portes, du même nom que celles de la scène et du canal de commandes :
    `gate` à chaque battement, `statusLost` quand le sondage échoue. Sans la
    seconde, la page garderait à l'écran un mode que plus rien ne confirme."""

    raw = PAGE_HTML.read_text(encoding="utf-8")
    refresh = raw[raw.index("async function refreshStatus()"):]
    refresh = refresh[:refresh.index("\n")]
    # Le relevé PRESENTATION du même battement voyage avec le bloc du mode.
    assert "JarvisInteractionModeControl.gate(s.interaction_mode,s.presentation)" in refresh
    assert "JarvisInteractionModeControl.statusLost()" in refresh
    # Le module est rangé dans son propre `try` : un module qui lève ne doit pas
    # emporter le reste du rafraîchissement, comme pour la scène et Bare Hands.
    before = refresh[:refresh.index("JarvisInteractionModeControl.gate")]
    assert before.endswith("try{if(window.JarvisInteractionModeControl)")
    # Et la page ne sonde pas le mode une seconde fois de son côté.
    assert raw.count("/api/interaction-mode") == 0


def test_le_module_ne_depend_d_aucun_autre_module_de_page(tmp_path):
    """Il lit le statut, rien d'autre.

    Ni `JarvisBarehands`, ni `openLifecycleSeam`, ni la scène : une dépendance
    d'insertion ici aurait couplé le mode d'interaction au cycle de vie d'une
    caméra, et un ordre de `<script>` cassé aurait fait disparaître le mode.

    La nuance qui compte : sa **feuille de style** nomme bien les sélecteurs de
    Bare Hands et de la scène, parce qu'ils partagent le rail du bas-gauche et
    que c'est la convention d'évitement du dépôt. Ce n'est pas une dépendance
    d'exécution — aucun de ces modules n'a besoin d'exister pour que celui-ci
    s'installe et peigne — et la dérive de ces sélecteurs est prise par
    `test_barehands_contracts_js.py`, pas par du code."""

    module = MODULE.read_text(encoding="utf-8")
    # Les commentaires **citent** les modules voisins pour expliquer pourquoi ce
    # module ne s'y branche pas ; ce qui compte est le code.
    code = re.sub(r"/\*.*?\*/", "", module, flags=re.S)
    for foreign in ("JarvisBarehands", "openLifecycleSeam", "JarvisScene", "JarvisSceneClient"):
        assert foreign not in code, foreign
    # Et il ne se donne pas une seconde mémoire du mode : la seule écriture de
    # `block` vient des deux portes du sondage.
    assert code.count("block=") == 3  # déclaration, `gate`, `statusLost`


def test_le_marqueur_du_module_est_apres_ceux_dont_il_partage_la_colonne(tmp_path):
    """Rien ne l'exige, et c'est dit : il est rangé près de ses voisins d'écran.

    Ce module n'a aucune contrainte d'ordre — il ne lit rien de la page hors de
    ce que `refreshStatus` lui remet. Il est placé après les
    modules Bare Hands parce que c'est là qu'un lecteur le cherchera, pas parce
    qu'il en dépend."""

    raw = PAGE_HTML.read_text(encoding="utf-8")
    assert raw.index(BAREHANDS_HUD_SCRIPT_MARKER) < raw.index(INTERACTION_MODE_SCRIPT_MARKER)


# ------------------------------------- la séance PRESENTATION (Slice 03, 2026-10)

#: Le relevé que Voice publie (`PresentationCoordinator.presentation_report`),
#: dans la forme que `ControlCenter._presentation_report` relaie : les clés
#: réelles, rien d'inventé.
REPORT = r"""
const report=over=>Object.assign({
  event:'entered',active:true,session_id:'pres-1',entered:1,entry_failures:0,left:0,
  last_failure_code:null,blockers:0,blocker_code:null,physical_input_owners:1,
  ambient_deaf:false,ambient_degraded:false,segments_pending:0,analysis_pending:0,
  trigger_latency_s:null,enrichment_lag_s:null,speculative_in_flight:0,
  speculative_free_explicit_slots:1,speculative_staged:0,attention_live:0,ts:1,
},over||{});
const PRES=status({mode:'presentation',label:'PRESENTATION',board_mode:'presentation',
  board_mode_label:'PRESENTATION'});
"""


def test_presentation_status_line_per_state(tmp_path):
    """Cinq états et `null`, dérivés des clés réelles du relevé.

    Chaque cas est servi **comme le statut le sert** — le bloc du mode et le
    relevé du même battement — puis lu sur ce que le bouton peint : la ligne,
    l'attribut d'état, le `title` (le code d'échec), le nom accessible et le
    bandeau du sélecteur."""

    result = run_node(tmp_path, REPORT + """
      const cases={
        listening:[PRES,report()],
        deaf:[PRES,report({event:'blocked',blockers:1,ambient_deaf:true,
          blocker_code:'presentation_transcription_unavailable'})],
        refused:[PRES,report({event:'refused',active:false,session_id:null,entered:0,
          entry_failures:1,last_failure_code:'presentation_architecture_unsupported',
          physical_input_owners:null,ambient_deaf:null})],
        entry_failed:[PRES,report({event:'entry_failed',active:false,session_id:null,entered:0,
          entry_failures:1,last_failure_code:'OSError',physical_input_owners:null,ambient_deaf:null})],
        inactive_presentation:[PRES,report({event:'left',active:false,session_id:null,left:1})],
        inactive_simple:[status(),report({event:'left',active:false,session_id:null,left:1})],
        /* Le relevé garde `refused` après le retour en SIMPLE : le coordinateur
           ne republie pas quand il n'a pas de séance à fermer. */
        stale_refusal_in_simple:[status(),report({event:'refused',active:false,
          last_failure_code:'presentation_architecture_unsupported'})],
        voice_offline:[PRES,null],
      };
      const seen={};
      for(const [name,[block,rep]] of Object.entries(cases)){
        const m=mount({status:block,report:rep});
        m.control.open();
        seen[name]={...m.presence(),label:m.trigger.getAttribute('aria-label'),
          note:m.note(),said:m.said(),
          pure:(M.presenceOf(rep,block.mode)||{state:null}).state};
      }
      out(seen);
    """, name="presence-states")

    expected = {
        "listening": ("listening", True, "Écoute la salle", "Séance PRESENTATION : Jarvis écoute la salle."),
        "deaf": ("deaf", True, "Sourd à la salle", "presentation_transcription_unavailable"),
        "refused": ("refused", True, "Refusé par la voix", "presentation_architecture_unsupported"),
        "entry_failed": ("entry_failed", True, "Entrée échouée", "OSError"),
        "inactive_presentation": ("inactive", True, "Séance inactive",
                                  "Aucune séance PRESENTATION ne tourne encore."),
        "inactive_simple": ("inactive", False, "", None),
        "stale_refusal_in_simple": ("inactive", False, "", None),
        "voice_offline": ("none", False, "", None),
    }
    for name, (state, shown, text, title) in expected.items():
        seen = result[name]
        assert (seen["state"], seen["shown"], seen["text"], seen["title"]) == (state, shown, text, title), (name, seen)
        assert seen["pure"] == (None if state == "none" else state), (name, seen)

    # Le nom accessible porte la séance quand elle est dite, avant l'action.
    assert "sourde à la salle" in result["deaf"]["label"]
    assert result["deaf"]["label"].endswith("Ouvrir le détail du mode.")
    assert "refusé" in result["refused"]["label"]
    assert "Séance" not in result["inactive_simple"]["label"]
    assert result["voice_offline"]["label"] == "Mode PRESENTATION : mode d’interaction en vigueur. Ouvrir le détail du mode."
    # La région vivante la dit aussi : un refus d'entrée s'entend.
    assert "refusé" in result["refused"]["said"]
    # Le bandeau du sélecteur dit refus, échec et surdité, code compris.
    assert result["refused"]["note"].endswith("(presentation_architecture_unsupported)")
    assert result["entry_failed"]["note"].endswith("(OSError)")
    assert result["deaf"]["note"].endswith("(presentation_transcription_unavailable)")
    # Rien d'urgent : la ligne de repos seulement.
    assert result["listening"]["note"].startswith("Le mode suit le type du Board actif.")
    assert result["stale_refusal_in_simple"]["note"].startswith("Le mode suit le type du Board actif.")


def test_status_never_optimistic_after_click(tmp_path):
    """Un clic ne peint ni le mode ni la séance, et n'envoie rien.

    La séance reste celle du **dernier statut** tant que Voice n'a pas publié
    autre chose. Le mode ne change qu'avec le statut qui le porte (une bascule
    de Board faite ailleurs) ; puis un refus d'entrée publié ensuite remplace
    l'écoute — et le retour critique de présence reste visible."""

    result = run_node(tmp_path, REPORT + """
      const m=mount({report:report({event:'left',active:false,session_id:null,left:1})});
      const steps=[];
      const read=tag=>steps.push({tag,checked:m.checked(),...m.presence(),
        mode:m.host.getAttribute('data-im-mode'),appels:m.net.calls.length});
      read('repos');
      await m.control.choose('presentation');
      await settle();
      read('apres_clic');
      /* Le battement suivant apporte le mode d'un Board Présentation ouvert ailleurs. */
      m.control.gate(PRES,report({event:'left',active:false,session_id:null,left:1}));
      read('mode_confirme');
      m.control.gate(PRES,report());
      read('seance_ouverte');
      /* Puis Voice rapporte un refus : il remplace l'écoute. */
      m.control.gate(PRES,report({event:'refused',active:false,
        last_failure_code:'presentation_architecture_unsupported'}));
      read('refus');
      out(steps);
    """, name="presence-not-optimistic")

    by = {step["tag"]: step for step in result}
    assert by["repos"]["checked"] == ["assistant"] and by["repos"]["state"] == "inactive"
    # Après le clic : rien n'a bougé, ni le mode ni la séance, et rien n'est parti.
    assert by["apres_clic"]["checked"] == ["assistant"]
    assert (by["apres_clic"]["state"], by["apres_clic"]["shown"]) == ("inactive", False)
    assert all(step["appels"] == 0 for step in result)
    # Mode confirmé par le statut ; la séance dit qu'aucune ne tourne encore.
    assert by["mode_confirme"]["checked"] == ["presentation"]
    assert (by["mode_confirme"]["state"], by["mode_confirme"]["text"]) == ("inactive", "Séance inactive")
    assert by["seance_ouverte"]["state"] == "listening"
    assert (by["refus"]["state"], by["refus"]["text"], by["refus"]["title"]) == (
        "refused", "Refusé par la voix", "presentation_architecture_unsupported")


def test_no_new_settings_surface(tmp_path):
    """La séance est **lue**, jamais réglée, et le mode non plus (Slice 01b).

    Vérification statique : le module n'a **aucune** porte réseau (il ne nomme
    que `/api/status`, qu'il ne fait que recevoir), le Control Center n'expose
    aucune route `presentation`, et aucun module de réglages ne connaît le relevé."""

    module = MODULE.read_text(encoding="utf-8")
    # `/api/status` seulement, que le module nomme sans l'appeler — le relevé y arrive.
    assert set(re.findall(r"/api/[a-z0-9/_-]*", module)) <= {"/api/status"}
    assert "request(" not in module and "fetch(" not in module and "deps.request" not in module
    assert "/api/settings" not in module and "localStorage" not in module

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    paths = {route.resource.canonical for route in control._app.router.routes() if route.resource is not None}
    # Le Studio de presentation (jarvis-interactive-presentation-studio) a ses routes propres sous
    # `/api/presentation-studio/` : ce n'est pas la surface du mode PRESENTATION que ce test garde.
    studio = "/api/presentation-studio"
    # Les lectures Board des sources de présentation (jarvis-remotion-presentation-integration, Slice 08) sont des
    # routes du Workspace : elles montrent source → copie figée → rendus, elles ne règlent pas le mode.
    workspace = ("/api/workspace/presentation-sources/", "/api/workspace/boards/{board_id}/presentation-sources")
    assert not [path for path in paths
                if ("presentation" in path or "presence" in path)
                and not (path == studio or path.startswith(studio + "/")
                         or path.startswith(workspace[0]) or path == workspace[1])], paths

    assert not (RUNTIME / "interaction_mode_settings.py").exists()
    for name in ("voice_settings_schema.py", "settings_mcp.py"):
        source = (RUNTIME / name).read_text(encoding="utf-8")
        for word in ("voice_presentation", "ambient_deaf", "presence"):
            assert word not in source, (name, word)

    # La page ne sonde rien de plus : le relevé voyage dans l'appel existant.
    page = PAGE_HTML.read_text(encoding="utf-8")
    assert page.count("JarvisInteractionModeControl.gate(") == 1


# --------------------------------------------- polish Slice 11 (p17, p18, p20)

REFUSED = "report({event:'refused',active:false,session_id:null,entered:0,entry_failures:1," \
          "last_failure_code:'presentation_architecture_unsupported',physical_input_owners:null," \
          "ambient_deaf:null,ts:TS})"


def test_un_refus_ecrit_avant_la_bascule_est_ecarte(tmp_path):
    """p17 : un `refused` daté d'avant le dernier battement SIMPLE confirmé ne peint pas de refus.

    La borne est ce battement-là moins la marge, **pas** le battement qui montre
    PRESENTATION : Voice écrit son refus en quelques millisecondes, souvent
    avant le sondage suivant, et ce refus-là doit rester visible."""

    result = run_node(tmp_path, REPORT + """
      const refused=TS=>""" + REFUSED + """;
      const seen={};
      // Battement SIMPLE confirmé à t=100 s, puis la bascule.
      const at=(simpleAt,ts)=>{clock=simpleAt*1000;const m=mount();
        clock+=1000;m.control.gate(PRES,refused(ts));return m.presence()};
      seen.stale=at(100,90);              // écrit 10 s avant le dernier battement SIMPLE
      seen.marginEdge=at(100,99);         // dans la marge : cru
      seen.afterSwitch=at(100,100.5);     // écrit entre le battement SIMPLE et celui-ci
      // Page ouverte directement en PRESENTATION : rien pour dater, le relevé est cru.
      clock=100000;seen.noAnchor=mount({status:PRES,report:refused(1)}).presence();
      // Un battement non confirmé par Core ne pose pas de borne.
      clock=100000;{const m=mount({status:offline('assistant')});clock+=1000;
        m.control.gate(PRES,refused(50));seen.unconfirmedAnchor=m.presence()}
      // L'échec d'entrée suit la même règle.
      clock=100000;{const m=mount();clock+=1000;
        m.control.gate(PRES,report({event:'entry_failed',active:false,last_failure_code:'OSError',ts:10}));
        seen.staleFailure=m.presence()}
      out({seen,margin:M.STALE_REPORT_MARGIN_S,
        pure:M.freshReport(report({event:'refused',ts:1}),10).event,
        pureFresh:M.freshReport(report({event:'refused',ts:9}),10).event,
        pureListening:M.freshReport(report({ts:1}),10).event});
    """, name="stale-refusal")
    seen = result["seen"]
    assert result["margin"] == 2
    assert (seen["stale"]["state"], seen["stale"]["text"]) == ("inactive", "Séance inactive"), seen["stale"]
    assert seen["staleFailure"]["state"] == "inactive", seen["staleFailure"]
    for name in ("marginEdge", "afterSwitch", "noAnchor", "unconfirmedAnchor"):
        assert seen[name]["state"] == "refused", (name, seen[name])
        assert seen[name]["title"] == "presentation_architecture_unsupported", (name, seen[name])
    assert (result["pure"], result["pureFresh"], result["pureListening"]) == ("stale", "refused", "entered")


def test_le_pied_du_selecteur_ne_contredit_pas_le_bandeau(tmp_path):
    """p18 : sourd, refusé ou raté, le pied dit d'abord ce qui se passe, puis ce que fait le mode."""

    result = run_node(tmp_path, REPORT + """
      const refused=TS=>""" + REFUSED + """;
      const cases={
        listening:report(),
        deaf:report({event:'blocked',blockers:1,ambient_deaf:true,blocker_code:'presentation_transcription_unavailable'}),
        refused:refused(1),
        entry_failed:report({event:'entry_failed',active:false,last_failure_code:'OSError'}),
      };
      const seen={};
      for(const [name,rep] of Object.entries(cases)){
        const m=mount({status:PRES,report:rep});m.control.open();
        const chips=m.chips();
        const own=m.hint();
        chips[0].fire('mouseenter');const other=m.hint();
        seen[name]={own,other,note:m.note()};
      }
      out(seen);
    """, name="footer")
    assert result["listening"]["own"] == "Jarvis montre et se tait."
    assert result["deaf"]["own"] == ("En ce moment : la séance est sourde à la salle, seul ce qui est adressé "
                                     "à Jarvis est entendu. Quand sa séance tourne : Jarvis montre et se tait.")
    assert result["refused"]["own"].startswith("En ce moment : aucune séance ne tourne, la voix a refusé PRESENTATION.")
    assert result["entry_failed"]["own"].startswith(
        "En ce moment : aucune séance ne tourne, le micro partagé n’a pas pu s’ouvrir.")
    for name in ("deaf", "refused", "entry_failed"):
        assert result[name]["note"], name  # le bandeau dit toujours l'état
        assert result[name]["other"] == "Jarvis répond et parle.", name  # les autres modes : leur résumé seul


def test_l_infobulle_du_bouton_est_courte_et_garde_le_code(tmp_path):
    """p20 : `title` ne recopie pas un `aria-label` long ; le code d'échec y reste."""

    result = run_node(tmp_path, REPORT + """
      const refused=TS=>""" + REFUSED + """;
      const read=m=>({title:m.trigger.getAttribute('title'),label:m.trigger.getAttribute('aria-label')});
      out({simple:read(mount()),listening:read(mount({status:PRES,report:report()})),
        refused:read(mount({status:PRES,report:refused(1)}))});
    """, name="title")
    assert result["simple"]["title"] == "Mode : SIMPLE"
    assert result["listening"]["title"] == "Mode : PRESENTATION · Écoute la salle"
    assert result["refused"]["title"] == \
        "Mode : PRESENTATION · Refusé par la voix (presentation_architecture_unsupported)"
    for name, seen in result.items():
        assert seen["title"] != seen["label"], name
        assert len(seen["title"]) < len(seen["label"]), name
