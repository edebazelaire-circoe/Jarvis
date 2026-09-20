"""Les deux cartes rapides Bare Hands — Aide / Gestes et Diagnostic —, par node.

Ce que ce fichier épingle :

- l'aide **n'est pas un second contrat de gestes** : tout ce qui peut se lire
  des contrats en est lu, et les gestes que rien n'écoute ne sont jamais
  présentés comme des commandes ;
- la liste des non-liés est **déduite** de `GESTURES`, donc un geste ajouté
  demain arrive « sans effet » au lieu d'arriver promis ;
- le pincement secondaire **est** montré comme lié : il ouvre un vrai menu
  contextuel, et le bloc de réglages qu'on remplace disait le contraire ;
- le diagnostic appelle **exactement** les portes de l'onglet Expérimental
  (`record.start`, `record.stop`, `record.state`), ne change ni ce qui est
  retenu ni ce qui est conservé, et **n'enregistre rien** à l'ouverture ;
- RÈGLE ZÉRO : pendant une capture, la carte dit que ça tourne, quoi, depuis
  combien de temps, combien il reste, et comment en sortir — et elle le dit
  encore quand l'échéance a arrêté la séance sans que personne clique ;
- clavier, focus et Échap.

Les contrats, le moteur et le module de dessin ne sont pas simulés : ce sont
les vrais modules. Seuls le DOM, le réseau et les minuteries sont des doubles.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_barehands_tools_settings_js import BROWSER_HEAD, TIMERS  # noqa: E402
from test_barehands_hud_js import DOM_PATCH, PATCH  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"

TAIL = r"""
delete require.cache[require.resolve(SCRIPT_PATH)];
const CORE=require(SCRIPT_PATH);
delete require.cache[require.resolve(HUD_PATH)];
const H=require(HUD_PATH);
const BAREHANDS=window.JarvisBarehands;
const CARDS=window.JarvisBarehandsHudCards;
const settle=async()=>{for(let i=0;i<12;i+=1)await new Promise(r=>setImmediate(r))};
const cardRoot=document.getElementById(H.DOM.cardsId);
/* Le texte de la carte, à plat : c'est ce qu'un humain lit, et c'est donc ce
   sur quoi porte « aucun geste non lié n'est présenté comme une commande ». */
const textOf=node=>{
  let out='';
  const walk=n=>{
    if(n.textContent&&!(n.children||[]).length)out+=' '+n.textContent;
    if(n.innerHTML)out+=' '+n.innerHTML;
    for(const c of (n.children||[]))walk(c);
  };
  walk(node);
  return out;
};
const buttons=root=>deepAll(root,n=>n.tagName==='BUTTON');
/* Le texte d'un nœud **et de ses enfants**. Une ligne qui mêle un témoin et
   un libellé — le titre de l'enregistrement le fait — porte son texte dans un
   nœud de texte, pas dans le `textContent` du parent. */
const textIn=node=>(node.textContent||'')
  +(node.children||[]).map(c=>textIn(c)).join('');
const recTitle=root=>textIn(deepFind(root,n=>n.className==='bh-rec-title')).trim();
const metersOf=root=>deepAll(root,n=>n.attrs&&n.attrs['data-bh-meter'])
  .map(n=>[n.attrs['data-bh-meter'],
    (deepAll(n,c=>c.className==='bh-rec-value')[0]||{textContent:null}).textContent]);
/* Une carte **non installée par la page**, nourrie d'une surface choisie :
   c'est elle qui décrit un enregistrement en cours sans caméra. Celle de la
   page reste branchée sur le vrai moteur. */
const sandbox=options=>{
  const o=options||{};
  const box=document.createElement('div');
  box.id='barehandsCardsSandbox'+Math.random().toString(36).slice(2);
  document.body.appendChild(box);
  const calls=[],logs=[];
  let state=Object.assign({installed:true,recording:false,frames:0,observed:0,
    dropped:0,elapsedMs:0,remainingMs:0,maxFrames:9000,maxDurationMs:120000,
    seam:['recorder'],last:null},o.state||{});
  const surface={
    SECTION:Object.freeze({settings:'barehandsSettings',record:'barehandsRecord'}),
    showSettings(section){calls.push(['showSettings',section]);
      return Promise.resolve({ok:true,tab:'experimental',section})},
    record:{
      state:()=>Object.assign({},state),
      start(){calls.push(['start']);
        if(o.refuseStart)return Promise.resolve({ok:false,code:o.refuseStart.code,
          reason:o.refuseStart.reason});
        state=Object.assign({},state,{recording:true,frames:0,observed:0,
          elapsedMs:0,remainingMs:state.maxDurationMs});
        return Promise.resolve({ok:true,startedAt:0,
          maxDurationMs:state.maxDurationMs,maxFrames:state.maxFrames});},
      stop(){calls.push(['stop']);
        const frames=state.frames;
        state=Object.assign({},state,{recording:false,remainingMs:0});
        return Promise.resolve({ok:true,recording:false,frames});},
    },
  };
  const cards=H.createQuickCards({document,host:box,
    surface:()=>(o.noSurface?null:surface),
    recorderBounds:()=>(o.noBounds?null:{maxDurationMs:120000,maxFrames:9000}),
    setInterval:global.setInterval,clearInterval:global.clearInterval,
    log:(l,e,d)=>logs.push([l,e,d])});
  return {box,cards,calls,logs,surface,
    /* Faire avancer la séance comme le vrai enregistreur le ferait. */
    advance:over=>{state=Object.assign({},state,over)},
    at:()=>Object.assign({},state)};
};
await settle();
"""


def browser(setup: str = "") -> str:
    return PATCH + BROWSER_HEAD + DOM_PATCH + TIMERS + setup + TAIL


def run_node(tmp_path: Path, source: str, name: str = "cards") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8",
        timeout=180, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ----------------------------------------------------- l'aide (décision 15)


def test_the_help_card_opens_from_the_quick_menu_and_closes_cleanly(tmp_path):
    """**La chaîne entière, du clic droit à la carte.**

    Le menu d'actions rapides de la Slice 02 route « Aide · Gestes… » vers
    `JarvisBarehands.showHelp()` ; cette Slice remplit ce crochet. Aucun
    appelant n'a bougé — c'est exactement ce que la Slice 02 avait prévu — et
    ce test part du menu, pas de la carte, parce que c'est le chemin qu'un
    humain prend.

    Fermer remet le focus là où il était : une carte qui rend la main au haut
    de la page fait recommencer la navigation au clavier."""

    result = run_node(tmp_path, browser() + r"""
      const trigger=document.getElementById(H.DOM.triggerId);
      trigger.focus();
      const before=document.activeElement===trigger;
      /* L'entrée d'aide est choisie **par son acte**, pas par sa position, et
         elle descend par `runQuick` — c'est littéralement ce que le `run` du
         menu de la page appelle (Slice 02), et donc le vrai chemin du clic
         droit jusqu'à la carte. Le `.ctxmenu` lui-même est déjà couvert par la
         Slice 02 ; ce qui est neuf ici commence à `showHelp`. */
      const items=window.JarvisBarehandsHudControl.quickItems().map(i=>i.act);
      const gate=H.QUICK_GATE[H.QUICK.HELP];
      await window.JarvisBarehandsHudControl.runQuick(H.QUICK.HELP);
      await settle();
      const open=cardRoot.attrs[H.DOM.cardAttribute];
      const focused=document.activeElement&&document.activeElement.id;
      const shut=buttons(cardRoot).find(b=>b.id===H.DOM.cardCloseId);
      const title=deepFind(cardRoot,n=>n.id===H.DOM.cardTitleId).textContent;
      const dialog=deepFind(cardRoot,n=>n.id===H.DOM.cardId);
      shut.listeners.click[0]();
      await settle();
      out({before,items,gate,open,focused,title,
        role:dialog.attrs.role,modal:dialog.attrs['aria-modal'],
        labelled:dialog.attrs['aria-labelledby']===H.DOM.cardTitleId,
        closed:cardRoot.attrs[H.DOM.cardAttribute]===undefined,
        /* Refermée, la carte ne laisse **rien** derrière elle : un corps vidé,
           pas une carte cachée qui garderait le focus au clavier. */
        emptied:deepAll(dialog,n=>n.className==='bh-card-block').length,
        restored:document.activeElement===trigger,
        opened:CARDS.opened()});
    """, name="open")

    assert result["before"] is True
    assert result["items"] == ["settings", "calibration", "help", "diagnostics"]
    assert result["gate"] == "showHelp", "l'entrée du menu n'a pas changé de porte"
    assert result["open"] == "help", "la nappe porte le nom de la carte ouverte"
    assert result["title"] == "Aide · Gestes"
    assert result["role"] == "dialog" and result["modal"] == "true"
    assert result["labelled"] is True
    assert result["focused"] == "barehandsCard", "le focus entre dans la carte"
    assert result["closed"] is True and result["emptied"] == 0
    assert result["restored"] is True, "le focus revient au bouton qui a ouvert"
    assert result["opened"] is None


def test_the_help_never_presents_an_unbound_recogniser_as_a_command(tmp_path):
    """**La contrainte dure de cette Slice**, et elle est mesurable.

    Quatre gestes sont reconnus et publiés à chaque image sans que rien ne les
    écoute : main ouverte, poing, double fermeture, claquement. Ils ne sont pas
    cachés — les taire ferait croire que le moteur ne les voit pas — mais ils
    ne sont **jamais** dits comme des commandes : pas de dessin, pas de verbe
    d'action, une seule ligne atténuée dans un bloc qui dit son nom.

    Et la liste n'est pas écrite : elle est `GESTURES` **moins** les liés. Un
    geste ajouté demain au contrat arrive donc ici sans effet annoncé, ce qui
    est la seule valeur par défaut acceptable pour une aide."""

    result = run_node(tmp_path, browser() + r"""
      const model=CARDS.helpModel();
      await BAREHANDS.showHelp();
      await settle();
      const idle=deepFind(cardRoot,n=>n.className==='bh-card-idle');
      const drawn=deepAll(cardRoot,n=>n.attrs&&n.attrs['data-bh-pose'])
        .map(n=>n.attrs['data-bh-pose']);
      out({
        contract:C.GESTURES,
        bound:H.GESTURE_BOUND,
        unbound:model.unbound.map(u=>u.gesture),
        /* La soustraction, refaite ici : la carte ne peut pas avoir de liste
           en dur qui coïncide par hasard. */
        derived:C.GESTURES.filter(g=>H.GESTURE_BOUND.indexOf(g)<0),
        allNamed:model.unbound.every(u=>u.named),
        idleText:idle.textContent+(idle.children||[]).map(c=>c.textContent).join(''),
        /* Aucune posture dessinée pour un geste non lié : les schémas sont
           réservés à ce qui agit. */
        poses:drawn,
      });
    """, name="unbound")

    assert result["bound"] == ["c_pose"], "un seul geste lié, et c'est le réveil"
    assert result["unbound"] == result["derived"] == [
        "open_palm", "fist", "double_close", "clap",
    ]
    assert result["allNamed"] is True, "chaque geste du contrat a sa phrase française"
    idle = result["idleText"]
    assert "aucune action ne leur est liée" in idle
    for name in ("Main ouverte", "Poing", "Double fermeture",
                 "Claquement des deux paumes"):
        assert name in idle, name
    # Les seules postures dessinées sont celles qui agissent : la main au
    # repos (les trois états), le C, et les quatre demi-pincements.
    assert sorted(set(result["poses"])) == [
        "pinch_primary_closed", "pinch_primary_open",
        "pinch_secondary_closed", "pinch_secondary_open",
        "rest", "wake_c",
    ]


def test_the_help_says_what_the_contracts_say_and_not_a_second_version(tmp_path):
    """**Tout ce qui peut être lu du contrat l'est.**

    Les phrases des trois états sont celles du sélecteur de mode, pas une
    seconde rédaction. Les durées viennent de `WAKE_HOLD_MS` et de
    `SLEEP_TIMEOUT_MS`. Les doigts de chaque canal viennent de `PINCH_FINGERS`.
    Les couleurs viennent de `feedbackRole()` **appelée**, pas d'une table
    recopiée — si sa règle change, la carte change avec elle.

    Le retour en veille est dit comme un **défaut**, parce que c'en est un :
    l'utilisateur peut le régler entre 5 s et 600 s, et une aide qui annoncerait
    30 s comme une loi contredirait son propre panneau de réglages."""

    result = run_node(tmp_path, browser() + r"""
      const model=CARDS.helpModel();
      out({
        /* Les mêmes phrases, littéralement les mêmes objets de table. */
        modeHints:model.lifecycle.map(l=>l.hint),
        fromSelector:model.lifecycle.every(l=>l.hint===H.MODE_HINT[l.mode]),
        captions:model.lifecycle.map(l=>l.caption),
        holdMs:model.wake.holdMs,contractHold:C.WAKE_HOLD_MS,
        sleepMs:model.wake.sleepMs,contractSleep:C.SLEEP_TIMEOUT_MS,
        wakeText:model.wake.text,backText:model.wake.back,
        /* Les doigts, construits depuis le contrat. */
        fingers:model.pinch.map(p=>[p.channel,p.subtitle]),
        contractFingers:C.PINCH_CHANNELS.map(ch=>C.PINCH_FINGERS[ch]),
        /* Les couleurs : la carte annonce ce que `feedbackRole` tranche. */
        roles:model.feedback.map(f=>f.role),
        recomputed:H.FEEDBACK_CASES.map(c=>C.feedbackRole(c.region,c.channel)),
        colors:model.feedback.map(f=>f.color),
        tokens:model.feedback.map(f=>
          `var(${C.FEEDBACK_TOKENS[f.role].cssVar},${C.FEEDBACK_TOKENS[f.role].fallback})`),
      });
    """, name="derived")

    assert result["fromSelector"] is True, "une seule rédaction des trois états"
    assert result["captions"] == ["ÉTEINT", "VEILLE", "ACTIF"]
    assert result["holdMs"] == result["contractHold"] == 1000
    assert result["sleepMs"] == result["contractSleep"] == 30000
    assert "tenez 1 seconde" in result["wakeText"]
    assert "30 secondes" in result["backText"]
    assert "par défaut" in result["backText"], "un réglage n'est pas une loi"
    # Pouce-index et pouce-majeur, traduits de `PINCH_FINGERS` et jamais
    # réécrits : si un canal changeait de doigts, la phrase suivrait.
    assert result["fingers"] == [["primary", "pouce et index"],
                                 ["secondary", "pouce et majeur"]]
    assert result["contractFingers"] == [["thumbTip", "indexTip"],
                                         ["thumbTip", "middleTip"]]
    assert result["roles"] == result["recomputed"] == ["body", "zone", "secondary"]
    assert result["colors"] == result["tokens"], "le jeton de thème, jamais un hexa nu"


def test_the_secondary_pinch_is_shown_as_bound_because_it_is(tmp_path):
    """**La staleté que cette Slice corrige.**

    Le bloc de réglages remplacé rangeait le pincement pouce-majeur parmi les
    « reconnus, pas encore agissants ». C'est faux depuis que
    `createInteractionEngine` publie `INTERACTION.CONTEXT` au relâchement d'un
    pincement secondaire, et que le pointeur le dépose en un vrai `contextmenu`
    du DOM — un clic droit, exactement comme une souris.

    Il est donc présenté **comme une commande**, avec ses deux dessins et son
    verbe, au même rang que le primaire. C'est la raison pour laquelle rien de
    l'ancien bloc n'a été recopié."""

    result = run_node(tmp_path, browser() + r"""
      const model=CARDS.helpModel();
      await BAREHANDS.showHelp();
      await settle();
      const rows=deepAll(cardRoot,n=>n.attrs&&n.attrs['data-bh-channel'])
        .map(n=>n.attrs['data-bh-channel']);
      const secondary=model.pinch.find(p=>p.channel===C.PINCH_CHANNEL.SECONDARY);
      const primary=model.pinch.find(p=>p.channel===C.PINCH_CHANNEL.PRIMARY);
      out({rows,
        channels:C.PINCH_CHANNELS,
        secondaryActions:secondary.actions,
        primaryActions:primary.actions,
        secondaryPoses:secondary.poses,
        primaryPoses:primary.poses,
        /* Et il n'est pas non plus dans la liste des non-liés : un geste ne
           peut pas être des deux côtés. */
        inUnbound:model.unbound.some(u=>u.gesture.indexOf('pinch')>=0),
        contextExists:C.INTERACTION.CONTEXT,
      });
    """, name="secondary")

    assert result["rows"] == ["primary", "secondary"], "les deux canaux, au même rang"
    assert result["contextExists"] == "context"
    assert result["secondaryActions"] == [
        "Clic droit : ouvre le menu contextuel, exactement comme une souris.",
    ]
    assert any("Cliquer" in line for line in result["primaryActions"])
    assert any("Glisser et faire défiler" in line for line in result["primaryActions"]), \
        "le glissement et le défilement sont implantés, l'ancien bloc disait le contraire"
    assert result["secondaryPoses"] == ["pinch_secondary_open", "pinch_secondary_closed"]
    assert result["primaryPoses"] == ["pinch_primary_open", "pinch_primary_closed"]
    assert result["inUnbound"] is False


# ------------------------------------------------- le diagnostic (décision 16)


def test_opening_the_diagnostics_card_records_nothing(tmp_path):
    """**Ouvrir n'est pas enregistrer**, et c'est l'invariant que la Slice 02
    avait posé en refusant de démarrer depuis un menu qui se referme.

    La carte ouvre la surface. Aucune capture ne part, aucun réglage n'est
    écrit, et `record.state()` dit toujours la même chose après qu'avant."""

    result = run_node(tmp_path, browser() + r"""
      /* Le modal fermé, sur un autre onglet : l'état d'où le clic droit part. */
      SET.open=false;SET.tab='voice';
      const before=BAREHANDS.record.state();
      const writes=server.calls.filter(c=>c.body).length;
      const outcome=await BAREHANDS.showDiagnostics();
      await settle();
      const after=BAREHANDS.record.state();
      out({outcome,
        card:cardRoot.attrs[H.DOM.cardAttribute],
        recordingBefore:before.recording,recordingAfter:after.recording,
        framesBefore:before.frames,framesAfter:after.frames,
        writes:server.calls.filter(c=>c.body).length-writes,
        /* La carte a bien remplacé le détour par l'onglet : le modal reste
           fermé, ce qui est toute la décision 16. */
        settingsOpen:SET.open,
      });
    """, name="open-diag")

    assert result["outcome"] == {"ok": True, "card": "diagnostics"}
    assert result["card"] == "diagnostics"
    assert result["recordingBefore"] is False and result["recordingAfter"] is False
    assert result["framesBefore"] == result["framesAfter"]
    assert result["writes"] == 0, "aucune écriture de réglage"
    assert result["settingsOpen"] is False, "plus besoin de traverser l'onglet"


def test_the_card_calls_the_very_doors_the_experimental_tab_calls(tmp_path):
    """**Aucune seconde implantation.** `Démarrer` est `record.start`,
    `Arrêter` est `record.stop`, l'affichage est `record.state` — les mêmes
    portes que les deux boutons de l'onglet, qui restent en place.

    Et le refus du moteur arrive **avec sa cause réelle** là où le clic est
    parti. Bare Hands éteint est le cas courant : sa phrase dit déjà où aller
    l'allumer, et la carte ne la réécrit pas."""

    result = run_node(tmp_path, browser() + r"""
      /* Contre le **vrai** moteur, Bare Hands éteint : c'est le refus que
         `startRecording` rend, mot pour mot. */
      await BAREHANDS.showDiagnostics();
      await settle();
      const start=buttons(cardRoot).find(b=>b.attrs['data-bh-rec-act']==='start');
      const direct=await BAREHANDS.record.start();
      await start.listeners.click[0]();
      await settle();
      const shown=deepFind(cardRoot,n=>n.className==='bh-rec-fail');
      out({direct,shown:shown.textContent,hidden:!!shown.hidden,
        recording:BAREHANDS.record.state().recording});
    """, name="doors")

    # La même porte, donc le même refus : la carte n'invente ni code ni phrase.
    assert result["direct"]["ok"] is False
    assert result["direct"]["code"] == "barehands_recorder_disabled"
    assert result["shown"] == result["direct"]["reason"]
    assert result["hidden"] is False, "un refus se voit"
    assert "en haut à gauche" in result["shown"], "il dit où aller rallumer"
    assert result["recording"] is False


def test_a_running_capture_says_all_four_things_rule_zero_demands(tmp_path):
    """**RÈGLE ZÉRO, et c'est la condition pour que ce bouton ait le droit
    d'exister ici.**

    La Slice 02 avait refusé de démarrer une capture depuis un menu qui se
    referme : rien à l'écran ne l'aurait datée ni arrêtée. Ce raisonnement
    tient — la carte le satisfait au lieu de le contourner, en restant ouverte
    pendant la capture et en portant les quatre choses :

    1. **que** ça tourne : un témoin qui bat et une barre qui balaie, marqués
       par `data-bh-rec=on` que la feuille lit ;
    2. **quoi** : « Enregistrement en cours » ;
    3. **depuis combien de temps**, et **combien il reste** : deux compteurs
       rafraîchis à la seconde ;
    4. **comment en sortir** : un bouton Arrêter armé, Échap, et l'échéance qui
       arrête toute seule — annoncée avant même qu'on démarre.
    """

    result = run_node(tmp_path, browser() + r"""
      const box=sandbox();
      box.cards.openDiagnostics();
      const idleRing=deepFind(box.box,n=>n.className==='bh-rec-state').attrs['data-bh-rec'];
      const idleStop=buttons(box.box).find(b=>b.attrs['data-bh-rec-act']==='stop').disabled;
      const idlePrivacy=deepFind(box.box,n=>n.className==='bh-rec-privacy').innerHTML;
      /* Démarrer par le bouton, comme un humain. */
      const start=buttons(box.box).find(b=>b.attrs['data-bh-rec-act']==='start');
      await start.listeners.click[0]();
      await settle();
      const state=deepFind(box.box,n=>n.className==='bh-rec-state');
      const running={
        mark:state.attrs['data-bh-rec'],
        title:recTitle(box.box),
        meters:metersOf(box.box),
        sweep:deepAll(box.box,n=>n.className==='bh-rec-sweep').length,
        led:deepAll(box.box,n=>n.className==='bh-rec-led').length,
        stop:buttons(box.box).find(b=>b.attrs['data-bh-rec-act']==='stop').disabled,
        start:buttons(box.box).find(b=>b.attrs['data-bh-rec-act']==='start').disabled,
      };
      /* Le temps passe : l'enregistreur avance, la carte doit suivre **sans
         qu'on la touche**. C'est le battement d'une seconde. */
      box.advance({frames:120,observed:130,elapsedMs:42000,remainingMs:78000});
      tick();
      const later=metersOf(box.box);
      /* Échap sort. */
      box.box.listeners.keydown[0]({key:'Escape',preventDefault(){}});
      out({idleRing,idleStop,idlePrivacy,running,later,
        closed:box.cards.opened(),
        calls:box.calls.map(c=>c[0])});
    """, name="rulezero")

    assert result["idleRing"] == "off"
    assert result["idleStop"] is True, "rien à arrêter quand rien ne tourne"
    # (4) L'échéance est annoncée **avant** de démarrer, pas découverte après.
    assert "120 s" in result["idlePrivacy"] and "9000 images" in result["idlePrivacy"]

    run = result["running"]
    assert run["mark"] == "on", "(1) la feuille a de quoi montrer que ça tourne"
    assert run["sweep"] == 1 and run["led"] == 1, "(1) une barre et un témoin"
    assert run["title"] == "Enregistrement en cours", "(2) quoi"
    assert run["stop"] is False and run["start"] is True, "(4) une sortie armée"
    # (3) Trois compteurs, dont le temps écoulé et le temps restant.
    assert [key for key, _ in run["meters"]] == ["retenues", "écoulé", "restant"]
    assert dict(run["meters"]) == {"retenues": "0 / 0", "écoulé": "0 s",
                                  "restant": "120 s"}
    # Et ils avancent tout seuls, sans clic : « ça travaille » et « c'est figé »
    # cessent de se ressembler.
    assert dict(result["later"]) == {"retenues": "120 / 130", "écoulé": "42 s",
                                     "restant": "78 s"}
    assert result["closed"] is None, "Échap sort"
    assert result["calls"] == ["start"]


def test_a_capture_that_stops_itself_is_not_still_announced_as_running(tmp_path):
    """**Le cas que le battement existe pour attraper.**

    L'enregistreur s'arrête tout seul : au bout de son échéance, ou quand le
    plafond d'images est atteint. Personne n'a cliqué, et rien ne prévient la
    carte. Sans relecture à la seconde, elle continuerait d'annoncer une
    capture terminée comme si elle durait — c'est-à-dire exactement le mensonge
    que la règle zéro existe pour interdire, à l'envers.

    Ce que l'écran doit montrer ensuite n'est pas du vide : ce que la séance a
    laissé. Un affichage qui redevient blanc après un arrêt se lit comme un
    arrêt qui a tout perdu."""

    result = run_node(tmp_path, browser() + r"""
      const box=sandbox({state:{recording:true,frames:8990,observed:9100,
        elapsedMs:100000,remainingMs:20000}});
      box.cards.openDiagnostics();
      const during=deepFind(box.box,n=>n.className==='bh-rec-state').attrs['data-bh-rec'];
      const duringMeters=metersOf(box.box);
      /* Le plafond d'images tombe : l'enregistreur s'arrête de lui-même. */
      box.advance({recording:false,frames:9000,observed:9100,
        elapsedMs:100400,remainingMs:0,dropped:100});
      tick();
      out({during,duringMeters,
        after:deepFind(box.box,n=>n.className==='bh-rec-state').attrs['data-bh-rec'],
        afterTitle:recTitle(box.box),
        afterMeters:metersOf(box.box),
        stop:buttons(box.box).find(b=>b.attrs['data-bh-rec-act']==='stop').disabled,
        start:buttons(box.box).find(b=>b.attrs['data-bh-rec-act']==='start').disabled,
        said:deepFind(box.box,n=>n.id===H.DOM.cardAnnounceId).textContent,
        /* Et personne n'a appelé `stop` : ce n'est pas la carte qui a arrêté. */
        calls:box.calls.map(c=>c[0])});
    """, name="deadline")

    assert result["during"] == "on"
    assert dict(result["duringMeters"])["restant"] == "20 s"
    assert result["after"] == "off", "la carte a vu l'arrêt qu'elle n'a pas provoqué"
    assert result["afterTitle"] == "Enregistrement de diagnostic"
    assert dict(result["afterMeters"]) == {"dernière séance": "9000 images",
                                           "durée": "100 s", "écartées": "100"}
    assert result["stop"] is True and result["start"] is False
    assert result["said"] == "Enregistrement terminé.", "l'arrêt est annoncé"
    assert result["calls"] == [], "la carte n'a rien arrêté : elle l'a constaté"


def test_the_card_changes_nothing_about_what_is_kept(tmp_path):
    """**La rétention et la confidentialité ne bougent pas d'une ligne.**

    Cette Slice n'a touché ni à ce qui est enregistré, ni à combien de temps,
    ni à ce qui part sur le disque. La preuve tient en deux morceaux :

    - la phrase de confidentialité de la carte est **mot pour mot** celle de
      l'onglet Expérimental, y compris l'énumération de ce qui n'est jamais
      retenu ;
    - les bornes affichées sont celles que l'enregistreur porte
      (`DEFAULTS.maxDurationMs`, `DEFAULTS.maxFrames`), lues chez lui et non
      écrites ici — sans quoi la carte annoncerait « deux minutes » le jour où
      le défaut change.

    Et quand ni l'enregistreur ni une séance ne donnent de bornes, la phrase se
    dit **sans chiffre** plutôt qu'avec un chiffre plausible."""

    result = run_node(tmp_path, browser() + r"""
      const REC=window.JarvisBarehandsRecorder;
      const box=sandbox();
      box.cards.openDiagnostics();
      const said=deepFind(box.box,n=>n.className==='bh-rec-privacy').innerHTML;
      /* Sans bornes connues : aucune invention. */
      const blind=sandbox({noBounds:true,state:{maxDurationMs:0,maxFrames:0}});
      blind.cards.openDiagnostics();
      const vague=deepFind(blind.box,n=>n.className==='bh-rec-privacy').innerHTML;
      out({said,vague,
        sentence:H.RECORD_PRIVACY,
        defaults:{duration:REC.DEFAULTS.maxDurationMs,frames:REC.DEFAULTS.maxFrames,
          sample:REC.DEFAULTS.sampleEveryMs},
        schema:[REC.TRACE_SCHEMA,REC.TRACE_SCHEMA_VERSION],
        /* Le module d'enregistrement n'a pas été touché : sa liste blanche de
           lecture reste celle des scalaires dérivés. */
        readers:['readHand','readCandidate','readEvent','readGesture','readFrame',
          'assertDerivedOnly'].filter(k=>typeof REC[k]==='function').length});
    """, name="retention")

    # La phrase, littéralement celle de l'onglet.
    assert "mesures dérivées" in result["sentence"]
    assert ("jamais une image, une vidéo ni les points de votre main"
            in result["sentence"])
    assert result["sentence"] in result["said"]
    assert result["sentence"] in result["vague"]
    # Les bornes affichées sont celles de l'enregistreur, inchangées.
    assert result["defaults"] == {"duration": 120000, "frames": 9000, "sample": 0}
    assert f"{result['defaults']['frames']} images" in result["said"]
    assert "120 s" in result["said"]
    # Sans bornes, aucun chiffre inventé.
    assert "images" not in result["vague"].replace("une image", "")
    assert "Il s’arrête tout seul" in result["vague"]
    assert result["schema"] == ["jarvis.barehands.trace", 1]
    assert result["readers"] == 6, "la garde de forme dérivée est intacte"


def test_the_card_keeps_the_keyboard_inside_and_hands_it_back(tmp_path):
    """Clavier et focus. Une carte `aria-modal` dont la tabulation sort derrière
    elle n'est modale que pour les voyants : le piège est donc réel, dans les
    deux sens, et il ne compte que les boutons **atteignables**.

    Cliquer à côté ferme, cliquer dedans non — le test porte sur la cible et
    pas sur un calcul de coordonnées qui se tromperait au premier défilement."""

    result = run_node(tmp_path, browser() + r"""
      const box=sandbox();
      box.cards.openDiagnostics();
      const all=buttons(box.box);
      const reachable=all.filter(b=>!b.disabled);
      /* Depuis le dernier, Tab revient au premier ; depuis le premier,
         Maj+Tab va au dernier. */
      reachable[reachable.length-1].focus();
      let stopped=0;
      box.box.listeners.keydown[0]({key:'Tab',preventDefault(){stopped+=1}});
      const wrapped=document.activeElement===reachable[0];
      box.box.listeners.keydown[0]({key:'Tab',shiftKey:true,preventDefault(){stopped+=1}});
      const back=document.activeElement===reachable[reachable.length-1];
      /* Une touche qui n'est ni Tab ni Échap ne fait rien. */
      box.box.listeners.keydown[0]({key:'a',preventDefault(){stopped+=1}});
      const open=box.cards.opened();
      /* Cliquer **dans** la carte ne ferme pas. */
      box.box.listeners.click[0]({target:deepFind(box.box,n=>n.id===H.DOM.cardId)});
      const stillOpen=box.cards.opened();
      /* Cliquer sur la nappe ferme. */
      box.box.listeners.click[0]({target:box.box});
      out({buttons:all.map(b=>b.attrs['data-bh-rec-act']||b.id),
        reachable:reachable.map(b=>b.attrs['data-bh-rec-act']||b.id),
        wrapped,back,stopped,open,stillOpen,closed:box.cards.opened()});
    """, name="keyboard")

    assert result["buttons"] == ["barehandsCardClose", "start", "stop", "settings"]
    # `Arrêter` est désarmé au repos, donc il n'est pas sur le chemin du
    # clavier : un piège qui compterait un bouton mort y ferait buter le focus.
    assert result["reachable"] == ["barehandsCardClose", "start", "settings"]
    assert result["wrapped"] is True and result["back"] is True
    assert result["stopped"] == 2, "seules les deux tabulations sont interceptées"
    assert result["open"] == "diagnostics" and result["stillOpen"] == "diagnostics"
    assert result["closed"] is None


def test_the_advanced_surface_stays_where_it_has_always_been(tmp_path):
    """La carte est un **raccourci**, pas un remplacement. Le rejeu, la
    comparaison et les réglages de l'enregistreur vivent toujours dans l'onglet
    Expérimental, et y renvoyer vaut mieux que les recopier ici à moitié.

    La carte s'efface derrière l'onglet qu'elle vient d'ouvrir : deux surfaces
    du même sujet empilées, et l'on ne saurait plus laquelle répond."""

    result = run_node(tmp_path, browser() + r"""
      const box=sandbox();
      box.cards.openDiagnostics();
      const more=buttons(box.box).find(b=>b.attrs['data-bh-rec-act']==='settings');
      const outcome=await more.listeners.click[0]();
      await settle();
      out({calls:box.calls,closed:box.cards.opened(),
        sections:Object.keys(BAREHANDS.SECTION).sort()});
    """, name="advanced")

    assert result["calls"] == [["showSettings", "barehandsRecord"]]
    assert result["closed"] is None, "la carte s'efface derrière l'onglet"
    assert result["sections"] == ["calibration", "record", "settings"]
