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
- ce que l'utilisateur a **choisi** et ce qui **tourne** peuvent diverger — un
  `REUNION` enregistré reste lisible alors que SIMPLE s'applique (décision 02),
  et l'écran le dit au lieu d'arbitrer ;
- **aucune peinture optimiste** : un échec, un refus 409, un 503 et un délai
  dépassé laissent tous le mode canonique précédent coché, sans rien à défaire ;
- un `503` dit « enregistré, mais pas encore appliqué » et **pas** « échec » :
  la préférence est sur le disque, seule son application est différée ;
- le clavier atteint tout ce que la souris atteint, les flèches déplacent le
  focus **sans choisir** (`menu` / `menuitemradio`, pas `radiogroup`), et l'ARIA
  dit l'état ;
- le rafraîchissement et les onglets multiples suivent le statut canonique :
  deux contrôles nourris du même statut peignent la même chose, et aucun ne
  garde sa propre idée du mode ;
- le module est bien inséré dans la page servie, son emplacement est déclaré
  dans `control_center.html`, ses rangs d'empilement sont au registre, et son
  refus d'installation est **rattrapé** pour ne pas emporter les autres modules.

Seuls le DOM, les minuteries et le réseau sont des doubles — ce que node n'a
pas. Le module, lui, est le fichier même que `ControlCenter.index` insère.

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
  mode:'assistant',label:'SIMPLE',revision:4,epoch:'vie-1',disposition:null,
  source:'core',core_reachable:true,error:null,
  stored:'assistant',stored_label:'SIMPLE',modes:MODES,
},over||{});
const offline=stored=>({
  mode:stored||'assistant',label:(stored||'assistant')==='presentation'?'PRESENTATION':'SIMPLE',
  revision:null,epoch:null,disposition:null,source:'settings',core_reachable:false,
  error:{code:'core_unreachable',message:'Core ne répond pas.'},
  stored:stored||'assistant',stored_label:(stored||'assistant')==='presentation'?'PRESENTATION':'SIMPLE',
  modes:MODES,
});

/* Le réseau : une file de réponses ou de refus, et la trace de ce qui est
   **réellement** parti. « Aucun appel » est une assertion à part entière. */
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
  const journal=[],toasts=[];
  let canonical=opts.status===undefined?status():opts.status;
  const control=M.createModeControl({
    document:doc,host,
    now:()=>clock,
    setInterval:setIntervalD,clearInterval:clearD,
    setTimeout:setTimeoutD,clearTimeout:clearD,
    request:opts.noRequest?undefined:net.request,
    toast:opts.noToast?undefined:spec=>toasts.push(spec),
    /* La relecture du statut canonique : le test décide ce que le serveur dira
       ensuite, et c'est cela — jamais le clic — qui repeint. */
    refresh:async()=>{control.gate(canonical)},
    log:(level,event,data)=>journal.push({level,event,data}),
  });
  control.gate(canonical);
  return {host,control,net,journal,toasts,
    serve(next){canonical=next},
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
          sub:M.subOf(v,0),live:v.live,note:M.noteOf(v,0,'')};};
      out({
        simple:read(status()),
        presentation:read(status({mode:'presentation',label:'PRESENTATION',
          stored:'presentation',stored_label:'PRESENTATION'})),
      });
    """, name="modes")
    assert result["simple"]["tone"] == "assistant"
    assert result["simple"]["selected"] == "assistant"
    assert result["simple"]["label"] == "SIMPLE"
    # Rien à dire quand tout est confirmé et cohérent : un bandeau permanent
    # cesse d'être lu.
    assert result["simple"]["sub"] == ""
    assert result["simple"]["note"] is None
    assert result["presentation"]["tone"] == "presentation"
    assert result["presentation"]["selected"] == "presentation"
    assert result["presentation"]["label"] == "PRESENTATION"
    assert result["presentation"]["live"] is True


def test_core_injoignable_ne_coche_rien_et_dit_que_la_valeur_est_locale(tmp_path):
    """Le repli local est **nommé**, jamais présenté comme la vérité vivante.

    C'est la règle du contrôle Bare Hands appliquée telle quelle : un état que
    l'on subit ne coche aucune pastille. Ici, l'état subi est « Core ne répond
    pas », et la valeur affichée est la préférence enregistrée."""

    result = run_node(tmp_path, """
      const v=M.viewOf(offline('presentation'),null);
      out({tone:v.tone,selected:v.selected,live:v.live,
        reason:v.reason,label:M.captionOf(v),
        sub:M.subOf(v,0),note:M.noteOf(v,0,null)});
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


def test_le_mode_choisi_et_le_mode_en_vigueur_restent_nommes_a_part(tmp_path):
    """Décision 02 : un REUNION enregistré ne disparaît pas de l'écran.

    `stored_label` est ce que l'utilisateur a choisi, `label` ce qui tourne. La
    divergence se lit sans ouvrir le sélecteur."""

    result = run_node(tmp_path, """
      const v=M.viewOf(status({stored:'meeting',stored_label:'REUNION'}),null);
      const chip=v.options.find(o=>o.value==='meeting');
      out({selected:v.selected,diverged:v.diverged,label:M.captionOf(v),
        sub:M.subOf(v,0),storedLabel:v.storedLabel,
        note:M.noteOf(v,0,null),reunionStored:chip.stored,reunionReserved:chip.reserved,
        parle:M.labelOf(v,0)});
    """, name="diverge")
    # Ce qui tourne est coché ; ce qui a été choisi est dit, pas coché.
    assert result["selected"] == "assistant"
    assert result["reunionStored"] is True
    assert result["reunionReserved"] is True
    assert result["diverged"] is True
    assert result["label"] == "SIMPLE"
    assert result["sub"] == "CHOISI : REUNION"
    assert result["storedLabel"] == "REUNION"
    assert "REUNION" in result["note"]["text"] and "SIMPLE" in result["note"]["text"]
    # La phrase du lecteur d'écran porte la même distinction.
    assert "en vigueur" in result["parle"] and "choisi" in result["parle"]


def test_une_demande_en_vol_ne_deplace_pas_la_pastille_et_dit_son_age(tmp_path):
    """RÈGLE ZÉRO, et l'absence d'optimisme, dans la même projection.

    Le mode coché reste celui que le serveur confirme pendant toute l'attente,
    et l'attente porte son compteur — sans quoi « ça travaille » et « c'est
    figé » s'écrivent pareil."""

    result = run_node(tmp_path, """
      const block=status({mode:'presentation',label:'PRESENTATION'});
      const v=M.viewOf(block,{mode:'assistant',since:0});
      out({busy:v.busy,selected:v.selected,pendingLabel:v.pendingLabel,
        sub0:M.subOf(v,0),sub7:M.subOf(v,7),
        note:M.noteOf(v,7,''),parle:M.labelOf(v,7)});
    """, name="pending")
    assert result["busy"] is True
    # La pastille n'a pas bougé : rien ne sera à défaire si la demande échoue.
    assert result["selected"] == "presentation"
    assert result["pendingLabel"] == "SIMPLE"
    assert result["sub0"] == "SIMPLE · 0 S"
    assert result["sub7"] == "SIMPLE · 7 S"
    assert "7 s" in result["note"]["text"]
    assert "7 secondes" in result["parle"]


def test_un_refus_passe_devant_tout_le_reste_et_garde_son_propre_ton(tmp_path):
    """Un refus prime sur un état durable — et il n'est pas forcément rouge.

    Le bandeau peignait tout refus dans le rouge du danger. « Mode enregistré,
    mais pas encore appliqué » (503) et « ce mode est réservé » (409) se
    lisaient donc exactement comme « le changement a échoué », alors que dans
    les deux premiers cas rien n'est cassé et que dans le premier la préférence
    est bel et bien sur le disque."""

    result = run_node(tmp_path, """
      const v=M.viewOf(offline('presentation'),null);
      out({
        panne:M.noteOf(v,0,{text:'Refusé par le serveur.',tone:'bad'}),
        reserve:M.noteOf(v,0,{text:'REUNION est réservé.',tone:'warn'}),
        differe:M.noteOf(v,0,{text:'Enregistré, pas encore appliqué.',tone:'warn'}),
        sansTon:M.noteOf(v,0,{text:'Sans ton.'}),
        sans:M.noteOf(v,0,null),
      });
    """, name="note-order")
    assert result["panne"] == {"tone": "bad", "text": "Refusé par le serveur."}
    # Les deux refus qui ne sont pas des pannes gardent leur propre ton.
    assert result["reserve"]["tone"] == "warn"
    assert result["differe"]["tone"] == "warn"
    # Sans ton déclaré, le sens sûr reste le rouge.
    assert result["sansTon"]["tone"] == "bad"
    assert result["sans"]["tone"] == "wait"


# ------------------------------------------------------- clavier et focus


def test_les_fleches_deplacent_le_focus_sans_jamais_choisir(tmp_path):
    """`menu` + `menuitemradio`, et **pas** `radiogroup`.

    Dans un groupe de radios, traverser les options au clavier choisit en
    passant : chaque flèche aurait changé le mode de Jarvis et déclenché un
    aller-retour serveur. L'assertion qui compte est donc « aucun appel »."""

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
    # Le mode réservé est `aria-disabled`, pas `disabled` : atteignable, donc
    # capable de dire pourquoi il ne se choisit pas.
    assert result["ariaDisabled"] == ["false", "false", "true"]
    assert result["htmlDisabled"] == [False, False, False]


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


# --------------------------------------------------------- choisir un mode


def test_un_changement_attend_le_statut_canonique_au_lieu_de_se_peindre(tmp_path):
    """Aucune peinture optimiste : on demande, puis on **relit**.

    La pastille ne bouge qu'au moment où le statut canonique le dit, et le
    corps envoyé est bien celui du contrat de la Slice 02."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{body:{}}]});
      const avant=m.checked();
      /* Ce que le serveur dira une fois la demande prise. */
      m.serve(status({mode:'presentation',label:'PRESENTATION',revision:5,
        stored:'presentation',stored_label:'PRESENTATION'}));
      const done=await m.control.choose('presentation');
      await settle();
      out({avant,done,apres:m.checked(),label:m.label(),
        appels:m.net.calls,journal:m.journal.map(l=>l.event),
        busy:m.host.getAttribute('data-im-busy'),
        tone:m.host.getAttribute(M.DOM.toneAttribute)});
    """, name="choose")
    assert result["avant"] == ["assistant"]
    assert result["done"] == "presentation"
    # La pastille a suivi le statut canonique, pas le clic.
    assert result["apres"] == ["presentation"]
    assert result["label"] == "PRESENTATION"
    assert result["tone"] == "presentation"
    assert result["busy"] == "false"
    # Une seule écriture, sur la route et dans la forme du contrat.
    assert result["appels"] == [
        {"path": "/api/interaction-mode", "method": "POST", "body": {"mode": "presentation"}}
    ]
    assert "interaction_mode.requested" in result["journal"]


def test_un_statut_qui_contredit_une_ecriture_reussie_gagne(tmp_path):
    """La seule source de cette page est le statut, y compris après un succès.

    Un `POST` accepté dont le statut suivant dit autre chose — quelqu'un d'autre
    a changé le mode dans l'intervalle — doit afficher ce que dit le statut."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{body:{}}]});
      /* L'écriture réussit, mais entre-temps un autre onglet est repassé en
         SIMPLE : c'est cela que l'écran doit montrer. */
      m.serve(status({mode:'assistant',label:'SIMPLE',revision:9}));
      await m.control.choose('presentation');
      await settle();
      out({checked:m.checked(),label:m.label(),sub:m.sub()});
    """, name="contradiction")
    assert result["checked"] == ["assistant"]
    assert result["label"] == "SIMPLE"
    assert result["sub"] == ""


def test_un_echec_laisse_le_mode_canonique_precedent_coche_et_dit_pourquoi(tmp_path):
    """Le critère d'acceptation, et il n'y a rien à défaire.

    Le sélecteur s'était refermé sur le choix ; il se **rouvre** sur la raison,
    là où l'utilisateur vient de cliquer. Une région vivante seule ne parle
    qu'aux lecteurs d'écran, et un contrôle redevenu silencieux après un clic
    est indiscernable d'un contrôle qui n'a rien reçu."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{status:500,message:'Le serveur a explosé.'}]});
      const done=await m.control.choose('presentation');
      await settle();
      out({done,checked:m.checked(),label:m.label(),
        rouvert:m.control.isOpen(),note:m.note(),said:m.said(),
        failure:m.control.failure(),
        journal:m.journal.filter(l=>l.event==='interaction_mode.refused'),
        busy:m.host.getAttribute('data-im-busy')});
    """, name="failure")
    assert result["done"] is None
    # **Le mode canonique précédent, toujours coché.**
    assert result["checked"] == ["assistant"]
    assert result["label"] == "SIMPLE"
    # Le refus se voit : le sélecteur se rouvre sur la raison.
    assert result["rouvert"] is True
    assert "Le serveur a explosé." in result["note"]
    assert "Le serveur a explosé." in result["said"]
    # Une panne franche est rouge, et le reste a son propre ton.
    assert result["failure"]["tone"] == "bad"
    assert result["busy"] == "false"
    # Et il est journalisé sous sa cause réelle, au niveau erreur.
    assert len(result["journal"]) == 1
    assert result["journal"][0]["level"] == "error"
    assert result["journal"][0]["data"]["status"] == 500


def test_un_409_sur_un_mode_annonce_implemente_est_dit_comme_un_conflit(tmp_path):
    """Le catalogue de cette page est une photo vieille d'une seconde.

    Un Core plus ancien peut refuser un mode que cette photo annonce comme
    implémenté. C'est le seul cas où le 409 arrive réellement sur le chemin
    d'écriture — REUNION, lui, est refusé sur place — et il ne doit pas se lire
    comme une panne."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{status:409,code:'interaction_mode_not_implemented',
        message:'Le mode REUNION est annoncé mais n’a pas de comportement.'}]});
      const done=await m.control.choose('presentation');
      await settle();
      out({done,checked:m.checked(),note:m.note(),
        journal:m.journal.filter(l=>l.event==='interaction_mode.refused')});
    """, name="conflict")
    assert result["done"] is None
    assert result["checked"] == ["assistant"]
    # Le texte dit une réserve, pas une panne.
    assert "comportement" in result["note"]
    assert "échoué" not in result["note"]
    # Le code stable est celui de l'en-tête, pas une devinette sur le texte.
    assert result["journal"][0]["data"]["code"] == "interaction_mode_not_implemented"
    assert result["journal"][0]["level"] == "warn"


def test_un_503_dit_enregistre_mais_pas_applique_et_non_echec(tmp_path):
    """La préférence **est** sur le disque : dire « échec » ferait recommencer.

    Et la divergence « choisi / en vigueur » apparaît tout de suite, parce que
    le statut est relu aussi après un refus — sans quoi elle n'arriverait qu'à
    la seconde suivante."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{status:503,code:'core_unreachable',
        message:'Mode PRESENTATION enregistré, mais pas encore appliqué : Core ne répond pas.'}]});
      /* Ce que le serveur dira ensuite : la préférence a bougé, pas le mode. */
      m.serve(status({mode:'assistant',label:'SIMPLE',
        stored:'presentation',stored_label:'PRESENTATION'}));
      const done=await m.control.choose('presentation');
      await settle();
      out({done,checked:m.checked(),label:m.label(),sub:m.sub(),note:m.note(),
        diverged:m.control.presentation().diverged,
        ton:m.control.failure().tone,
        tonRendu:byId(m.host,M.DOM.noteId).getAttribute('data-im-note'),
        journal:m.journal.filter(l=>l.event==='interaction_mode.refused')});
    """, name="saved-not-applied")
    assert result["done"] is None
    # Le mode en vigueur n'a pas bougé — c'est vrai, et c'est ce qui s'affiche.
    assert result["checked"] == ["assistant"]
    assert result["label"] == "SIMPLE"
    # Mais le choix, lui, a été enregistré : la divergence le montre.
    assert result["diverged"] is True
    assert result["sub"] == "CHOISI : PRESENTATION"
    assert "enregistré" in result["note"]
    assert "pas encore appliqué" in result["note"]
    assert "échoué" not in result["note"]
    # **Et ce n'est pas peint comme une panne.** L'argument etait tenu dans le
    # texte et dementi par la couleur, qui est ce que l'on lit en premier.
    assert result["ton"] == "warn"
    assert result["tonRendu"] == "warn"
    # La phrase du serveur n'est pas repetee : elle porte deja ces mots.
    assert result["note"].count("enregistré") == 1
    assert result["journal"][0]["level"] == "warn"


def test_choisir_reunion_ne_part_en_aucun_appel_et_explique_la_reserve(tmp_path):
    """Une réserve assumée ne se déguise pas en aller-retour raté.

    Le serveur répondrait 409 avec le même sens ; faire l'appel ferait passer
    une décision produit pour une panne de transport, et remplirait le journal
    d'erreurs pour un bouton qui fait exactement ce qu'il annonce."""

    result = run_node(tmp_path, """
      const m=mount();
      const done=await m.control.choose('meeting');
      await settle();
      out({done,appels:m.net.calls.length,checked:m.checked(),
        rouvert:m.control.isOpen(),note:m.note(),said:m.said(),
        ton:m.control.failure().tone,
        tonRendu:byId(m.host,M.DOM.noteId).getAttribute('data-im-note'),
        journal:m.journal.map(l=>({event:l.event,level:l.level}))});
    """, name="reserved-click")
    assert result["done"] is None
    # **Zéro appel réseau.**
    assert result["appels"] == 0
    # Et le mode en vigueur n'a pas bougé d'un cheveu.
    assert result["checked"] == ["assistant"]
    # L'explication est visible à l'écran, pas seulement dans une région vivante.
    assert result["rouvert"] is True
    assert "REUNION" in result["note"]
    assert "comportement" in result["note"]
    assert "REUNION" in result["said"]
    # **Et ce n'est pas peint comme une panne.** Une réserve assumée dans le
    # rouge du danger dit le contraire de ce que la phrase dit.
    assert result["ton"] == "warn"
    assert result["tonRendu"] == "warn"
    # Ce n'est pas une erreur : le journal le dit à `info`.
    assert {"event": "interaction_mode.reserved_refused", "level": "info"} in result["journal"]


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


def test_deux_ecritures_qui_se_chevauchent_gardent_chacune_son_echeance(tmp_path):
    """Le defaut qui rendait le controle mort pour la vie de la page.

    L'echeance vivait dans une variable unique. Passe le delai, le premier appel
    rendait la main ; un second partait et posait SA minuterie dans la meme
    variable ; puis le premier, en se terminant enfin, annulait ce qu'il y
    trouvait — l'echeance du second. Le second n'avait alors plus de borne : si
    lui aussi restait sans reponse, le bouton restait occupe indefiniment, toutes
    ses options desactivees et tout nouveau choix refuse.

    Reproduit ici a l'identique : deux ecritures qui ne repondent jamais."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{delay:3600000,body:{}},{delay:3600000,body:{}}]});
      /* Premiere ecriture : elle ne repondra jamais. */
      const premiere=m.control.choose('presentation');
      await settle();
      advance(M.WRITE_DEADLINE_MS);await settle();
      const apresPremiere={busy:m.host.getAttribute('data-im-busy'),
        billets:m.control.waits()};
      /* Deuxieme ecriture, pendant que la premiere est toujours en vol. */
      const seconde=m.control.choose('presentation');
      await settle();
      const pendantSeconde={busy:m.host.getAttribute('data-im-busy'),
        billets:m.control.waits(),appels:m.net.calls.length};
      /* L'echeance de la SECONDE doit tomber, meme si la premiere se termine
         entre-temps. Une heure plus tard, le bouton doit etre rendu. */
      advance(M.WRITE_DEADLINE_MS);await settle();
      const apresSeconde={busy:m.host.getAttribute('data-im-busy'),
        sub:m.sub(),checked:m.checked(),billets:m.control.waits(),
        delais:m.journal.filter(l=>l.event==='interaction_mode.request_timeout').length};
      /* Et une troisieme tentative part encore. */
      const troisieme=await m.control.choose('presentation');
      await settle();
      const relance=m.net.calls.length;
      advance(7200000);await settle();
      await premiere;await seconde;await settle();
      out({apresPremiere,pendantSeconde,apresSeconde,relance,
        finBusy:m.host.getAttribute('data-im-busy'),finSub:m.sub(),
        finChecked:m.checked()});
    """, name="overlap")
    # La premiere a bien rendu la main a 12 s, et son billet est consomme.
    assert result["apresPremiere"]["busy"] == "false"
    assert result["apresPremiere"]["billets"] == 0
    # La seconde part et pose le sien.
    assert result["pendantSeconde"]["busy"] == "true"
    assert result["pendantSeconde"]["billets"] == 1
    assert result["pendantSeconde"]["appels"] == 2
    # **Et elle expire elle aussi.** Sans la correction, le bouton restait ici
    # occupe pour toujours : `PRESENTATION · 3626 S`, options desactivees.
    assert result["apresSeconde"]["busy"] == "false"
    assert result["apresSeconde"]["sub"] == ""
    assert result["apresSeconde"]["checked"] == ["assistant"]
    assert result["apresSeconde"]["billets"] == 0
    assert result["apresSeconde"]["delais"] == 2
    # Le controle est vivant : une troisieme demande part vraiment.
    assert result["relance"] == 3
    # Et les reponses tardives des deux premieres ne peignent rien.
    assert result["finBusy"] == "false"
    assert result["finSub"] == ""
    assert result["finChecked"] == ["assistant"]


def test_un_second_clic_pendant_une_ecriture_ne_part_pas(tmp_path):
    """Le deuxième clic — celui qu'on oublie toujours de tester."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{delay:3000,body:{}},{body:{}}]});
      const first=m.control.choose('presentation');
      await settle();
      const pendantAttente={busy:m.host.getAttribute('data-im-busy'),
        sub:m.sub(),disabled:m.chips().map(c=>!!c.disabled),
        ariaBusy:m.trigger.getAttribute('aria-busy')};
      /* Le second clic, pendant que le premier est en vol. */
      const second=await m.control.choose('assistant');
      advance(3000);await settle();
      await first;
      await settle();
      out({pendantAttente,second,appels:m.net.calls.length,
        corps:m.net.calls.map(c=>c.body.mode)});
    """, name="double-click")
    # Pendant l'attente : tout dit qu'il se passe quelque chose.
    assert result["pendantAttente"]["busy"] == "true"
    assert result["pendantAttente"]["ariaBusy"] == "true"
    assert result["pendantAttente"]["disabled"] == [True, True, True]
    assert result["pendantAttente"]["sub"].startswith("PRESENTATION · ")
    # Le second clic n'est pas parti.
    assert result["second"] is None
    assert result["appels"] == 1
    assert result["corps"] == ["presentation"]


def test_le_compteur_de_l_attente_monte_vraiment(tmp_path):
    """RÈGLE ZÉRO : « ça travaille » et « c'est figé » doivent s'écrire autrement.

    Le compteur est armé par l'état et monte tout seul, sans qu'aucun clic ni
    aucune repeinture extérieure ne s'en mêle."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{delay:6000,body:{}}]});
      const call=m.control.choose('presentation');
      await settle();
      const lectures=[m.sub()];
      for(let i=0;i<4;i+=1){advance(1000);await settle();lectures.push(m.sub())}
      advance(2000);await settle();await call;await settle();
      out({lectures,fin:m.sub()});
    """, name="counter")
    assert result["lectures"] == [
        "PRESENTATION · 0 S", "PRESENTATION · 1 S", "PRESENTATION · 2 S",
        "PRESENTATION · 3 S", "PRESENTATION · 4 S",
    ]
    # Et l'attente s'arrête vraiment.
    assert result["fin"] == ""


def test_une_attente_sans_reponse_finit_par_rendre_la_main(tmp_path):
    """RÈGLE ZÉRO, seconde mesure : aucun état d'attente ne dure pour toujours.

    `fetch` n'a pas de délai ; sans cette borne, un serveur qui ne répond jamais
    laisserait le contrôle désarmé et l'écran sans issue. La réponse tardive,
    quand elle arrive, ne peut plus rien peindre."""

    result = run_node(tmp_path, """
      const m=mount({plan:[{delay:120000,body:{}}]});
      const call=m.control.choose('presentation');
      await settle();
      advance(M.WRITE_DEADLINE_MS);await settle();
      const apresDelai={busy:m.host.getAttribute('data-im-busy'),checked:m.checked(),
        dit:m.control.failure().text,said:m.said(),
        rouvert:m.control.isOpen(),focus:m.focused(),infusions:m.toasts.slice(),
        journal:m.journal.filter(l=>l.event==='interaction_mode.request_timeout')};
      /* Le contrôle est rendu : un nouveau choix repart. */
      const repart=m.control.choose('presentation');
      await settle();
      const relance=m.net.calls.length;
      advance(200000);await settle();
      await call;await repart;await settle();
      out({apresDelai,relance,checkedFinal:m.checked()});
    """, name="deadline")
    assert result["apresDelai"]["busy"] == "false"
    # Le mode canonique n'a pas bougé, et le contrôle dit ce qu'il a attendu.
    assert result["apresDelai"]["checked"] == ["assistant"]
    assert "n’a pas répondu" in result["apresDelai"]["dit"]
    assert "12 s" in result["apresDelai"]["dit"]
    assert result["apresDelai"]["journal"][0]["data"]["waited_s"] == 12
    # **Mais il ne reprend pas le focus.** Douze secondes plus tard l'utilisateur
    # est ailleurs ; rouvrir le sélecteur et y poser le focus lui arracherait ce
    # qu'il est en train de faire. Le refus passe par l'infusion de la page,
    # celle que quatre autres modules utilisent déjà.
    assert result["apresDelai"]["rouvert"] is False
    assert result["apresDelai"]["focus"] is None
    assert len(result["apresDelai"]["infusions"]) == 1
    assert "n’a pas répondu" in result["apresDelai"]["infusions"][0]["sub"]
    assert result["apresDelai"]["infusions"][0]["kind"] == "bad"
    # Et la région vivante l'annonce quand même.
    assert "n’a pas répondu" in result["apresDelai"]["said"]
    # La main est rendue : un second essai part réellement.
    assert result["relance"] == 2
    # Et la réponse tardive du premier appel n'a rien peint.
    assert result["checkedFinal"] == ["assistant"]


def test_une_page_sans_porte_reseau_le_dit_au_lieu_de_ne_rien_faire(tmp_path):
    """« Le bouton n'a rien fait » est le pire des messages."""

    result = run_node(tmp_path, """
      const m=mount({noRequest:true});
      const done=await m.control.choose('presentation');
      await settle();
      out({done,note:m.note(),checked:m.checked(),
        journal:m.journal.map(l=>l.event)});
    """, name="no-gate")
    assert result["done"] is None
    assert "porte réseau" in result["note"]
    assert result["checked"] == ["assistant"]
    assert "interaction_mode.request_gate_missing" in result["journal"]


def test_core_injoignable_ne_fait_pas_disparaitre_le_mode_choisi(tmp_path):
    """Decision 02, au moment ou elle compte le plus.

    « non confirme » sortait avant « choisi », si bien qu'un REUNION enregistre
    disparaissait du bouton des que Core devenait injoignable — c'est-a-dire
    exactement quand le choix de l'utilisateur est la seule chose que l'on sache
    encore. Et le bandeau disait « ceci est la preference enregistree », ce qui
    etait litteralement faux : le serveur rend `behaving(stored)`, donc SIMPLE,
    et les deux ne different que sur REUNION."""

    result = run_node(tmp_path, """
      /* Core injoignable, et REUNION est la preference : le serveur rend donc
         le mode qui s'appliquerait (SIMPLE), pas ce qui est sur le disque. */
      const bloc={mode:'assistant',label:'SIMPLE',revision:null,epoch:null,
        disposition:null,source:'settings',core_reachable:false,
        error:{code:'core_unreachable',message:'Core ne repond pas.'},
        stored:'meeting',stored_label:'REUNION',modes:MODES};
      const m=mount({status:bloc});
      m.control.open();
      const v=m.control.presentation();
      out({label:m.label(),sub:m.sub(),note:m.note(),checked:m.checked(),
        diverged:v.diverged,parle:M.labelOf(v,0),
        etiquettes:m.chips().map(c=>c.getAttribute(M.DOM.storedAttribute))});
    """, name="offline-diverged")
    # Le mode qui s'appliquerait reste lisible…
    assert result["label"] == "SIMPLE"
    # …et le choix de l'utilisateur **aussi**, sur la meme ligne.
    assert result["sub"] == "NON CONFIRMÉ · CHOISI : REUNION"
    # Rien n'est coche : Core ne confirme rien.
    assert result["checked"] == []
    assert result["diverged"] is True
    # Le bandeau ne pretend plus montrer la preference enregistree.
    assert "préférence enregistrée" not in result["note"]
    assert "qui s’appliquerait" in result["note"]
    assert "Choisi : REUNION" in result["note"]
    # La phrase du lecteur d'ecran porte les deux faits.
    assert "non confirmé" in result["parle"]
    assert "REUNION est le mode choisi" in result["parle"]
    # Et la pastille REUNION garde sa marque.
    assert result["etiquettes"] == ["false", "false", "true"]


def test_un_refus_cesse_de_masquer_ce_que_l_on_subit_ensuite(tmp_path):
    """Un refus local ne bouge jamais le mode, donc rien ne l'effacait.

    `gate()` n'efface la phrase de refus que lorsque le mode en vigueur change
    — ce qui est voulu pour le 503, ou le mode ne bouge pas et ou « enregistre,
    pas encore applique » reste vrai. Mais apres un REUNION refuse sur place, le
    mode ne bouge jamais : le selecteur montrait encore la phrase sur REUNION
    alors que Core etait devenu injoignable entre-temps."""

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
      /* Personne n'a cliqué : le mode a changé ailleurs (autre onglet, voix,
         protocole, rattrapage de démarrage). Le sondage l'apporte. */
      const suivant=status({mode:'presentation',label:'PRESENTATION',revision:12,
        stored:'presentation',stored_label:'PRESENTATION'});
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
        stored:'atelier',stored_label:'ATELIER',modes})});
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
    assert f'<div id="{HOST_ID}"></div>' in raw


def test_le_registre_d_empilement_nomme_le_controle_et_ses_deux_rangs(tmp_path):
    """Le registre de `control_center.html` est la seule table des rangs.

    Un élément flottant qui n'y figure pas est un rang que personne ne peut
    vérifier en lisant la page — et c'est exactement ce que ce registre existe
    pour empêcher."""

    raw = PAGE_HTML.read_text(encoding="utf-8")
    registre = raw[raw.index("Registre d'empilement"):raw.index("Thème Cosmos")]
    assert "contrôle de mode d'interaction du bas-gauche 32" in registre
    assert "son sélecteur 36" in registre
    # Et le registre dit *pourquoi* les deux contrôles partagent leurs rangs sans
    # jamais se recouvrir.
    assert "BAS" in registre


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
    et ou la hauteur de sa palette depend du nombre d'outils installes : sur un
    ecran court, elle peut descendre dans cette bande. Ce test dit ce qui est
    vrai et nomme la limite, plutot que de promettre les deux tailles comme la
    version precedente le faisait sans rien asserter de la seconde."""

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
    doc = (ROOT / "docs" / "interaction-mode.md").read_text(encoding="utf-8")
    assert "short viewport" in doc
    # Et le module se fait plus petit la ou l'ecran est le plus court.
    assert "and (max-height:640px)" in module


def test_le_controle_se_hisse_au_dessus_de_l_indication_vocale(tmp_path):
    """L'indication vocale est centree en bas a **toutes** les largeurs.

    La page ne la deplace jamais — elle est absente de son bloc a 700 px — donc
    il existe une fenetre ou elle et ce bouton tiennent chacun une moitie qui se
    recouvrent. Le seuil de relevement se lit sur la page, pas sur une constante
    recopiee : sous le theme Cosmos l'indication descend a 18 px, et un test qui
    aurait grave 22 px n'aurait pas vu le deplacement."""

    css = run_node(tmp_path, "out({style:M.STYLE,geo:M.GEO});", name="lift")
    module, geo = css["style"], css["geo"]
    raw = PAGE_HTML.read_text(encoding="utf-8")
    work = (RUNTIME / "control_center_work.js").read_text(encoding="utf-8")

    bottoms = [int(m) for m in re.findall(r"\.voicehint\{[^}]*?bottom:(\d+)px", raw)]
    bottoms += [int(m) for m in re.findall(
        r'voicehint\{\s*bottom:(\d+)px', work)]
    assert bottoms, "l'indication vocale declare bien un bas quelque part"
    # Elle est centree, et la page ne la deplace a aucune largeur.
    assert ".voicehint{position:absolute;z-index:31;left:50%" in raw
    narrow_block = raw[raw.index("@media(max-width:700px){"):]
    narrow_block = narrow_block[:narrow_block.index(chr(10) + "}")]
    assert "voicehint" not in narrow_block

    lift_below, lift, narrow_below = geo["liftBelow"], geo["lift"], geo["narrowBelow"]
    # Le relevement arrive **avant** le resserrement du rail : la fenetre a
    # risque est 701 → 820, precisement celle que 700 px laissait ouverte.
    assert lift_below > narrow_below
    # Et le bouton passe vraiment au-dessus d'elle : son bas releve doit depasser
    # le SOMMET de l'indication, pas seulement son bas. Celle-ci fait environ
    # 30 px de haut (12 px de texte, 8 px de marge, une bordure).
    assert geo["bottom"] + lift > max(bottoms) + 30
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
    assert "JarvisInteractionModeControl.gate(s.interaction_mode)" in refresh
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

    Ce module n'a aucune contrainte d'ordre — il ne lit `api` et `refreshStatus`
    que par des déclarations de fonction remontées. Il est placé après les
    modules Bare Hands parce que c'est là qu'un lecteur le cherchera, pas parce
    qu'il en dépend."""

    raw = PAGE_HTML.read_text(encoding="utf-8")
    assert raw.index(BAREHANDS_HUD_SCRIPT_MARKER) < raw.index(INTERACTION_MODE_SCRIPT_MARKER)
