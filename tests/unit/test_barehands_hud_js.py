"""Contrôle de cycle de vie Bare Hands de la barre du haut, exécuté par node.

Ce que ce fichier épingle :

- **une présentation par état**, et cinq et non trois : `off` gris atténué,
  `sleep` bleu ordinaire, `active` bleu plus clair **avec halo** — jamais vert —
  plus les deux que l'on subit, `starting` et `error`, qu'aucune pastille ne
  coche ;
- le sélecteur choisit les trois modes **directement** et les fait descendre sur
  les portes autoritaires (`disable` / `sleep` / `enable` / `activate`), dans
  l'ordre exact qui ne laisse pas le contrôleur en démarrage ;
- choisir « Éteint » écrit l'interrupteur maître à faux et rend la caméra ;
- **la couture** : une transition venue d'ailleurs repeint le bouton alors que
  l'onglet de réglages est fermé — c'est le seul chemin qui n'existait pas avant
  cette Slice, et c'est celui que la décision 7 exige ;
- un réveil en C et le retour en veille après 30 s, produits par le **vrai**
  moteur, peignent bien `sleep → active` et `active → sleep` ;
- un reçu de commande vocale laisse l'écran et le moteur d'accord ;
- le clavier atteint tout ce que la souris atteint, et l'ARIA dit l'état.

Les contrats et le moteur ne sont pas simulés : ce sont les vrais modules.
Seuls le DOM et le réseau sont des doubles — ce que node n'a pas.

**Ce que node ne permet pas, dit ici plutôt que caché.** Le bloc navigateur
charge MediaPipe par un `import()` d'une URL servie par Jarvis ; sous node il
échoue, et le contrôleur réel de la page ne dépasse donc jamais `starting` puis
`error`. Les présentations `sleep` et `active` sont par conséquent décrites sur
le **vrai contrôle** nourri d'instantanés issus du **vrai moteur**
(`test_a_c_wake_and_the_idle_timeout_paint_the_button`, qui fait tourner le
contrôleur de la Slice 02 avec sa caméra injectée), et la jonction entre les
deux — « tout statut émis atteint la couture » — est prouvée en vivant, à
l'onglet fermé, par `test_an_external_transition_repaints_the_button`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    BAREHANDS_HUD_SCRIPT_FILE,
    BAREHANDS_HUD_SCRIPT_MARKER,
    BAREHANDS_SCRIPT_MARKER,
    ControlCenter,
)

# Le monde navigateur de la Slice 07 est **réutilisé**, pas recopié : une
# seconde version décrirait une seconde page, et les deux divergeraient en
# silence. Seul ce qui manque à ce contrôle-là lui est ajouté ci-dessous.
from test_barehands_tools_settings_js import BROWSER_HEAD, TIMERS  # noqa: E402
from test_barehands_lifecycle_js import WORLD  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE_HTML = RUNTIME / "control_center.html"
SCRIPT = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
HUD = RUNTIME / BAREHANDS_HUD_SCRIPT_FILE
COMMANDS = RUNTIME / "control_center_barehands_commands.js"
TARGET = RUNTIME / "control_center_barehands_target.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
TUTORIAL = RUNTIME / "control_center_barehands_tutorial.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
SCENE_INTERACT = RUNTIME / "control_center_scene_interact.js"

#: Ce que le double de navigateur de la Slice 07 n'a pas, parce que l'onglet
#: Expérimental n'en a pas eu besoin : un espace de noms SVG (l'icône de main
#: est du trait, pas du texte), un focus qui se déplace vraiment (sans lui,
#: aucune assertion de clavier ne veut dire quoi que ce soit), le retrait d'un
#: attribut, et une horloge qu'on avance à la main.
PATCH = r"""
const SCRIPT_PATH=%(script)s,CONTRACTS_PATH=%(contracts)s,HUD_PATH=%(hud)s;
const COMMANDS_PATH=%(commands)s;
const TARGET_PATH=%(target)s,CALIBRATION_PATH=%(calibration)s;
const TUTORIAL_PATH=%(tutorial)s,RECORDER_PATH=%(recorder)s;
const SCENE_INTERACT_PATH=%(scene)s;
const C=require(CONTRACTS_PATH);
""" % {
    "script": json.dumps(str(SCRIPT)),
    "contracts": json.dumps(str(CONTRACTS)),
    "hud": json.dumps(str(HUD)),
    "commands": json.dumps(str(COMMANDS)),
    "target": json.dumps(str(TARGET)),
    "calibration": json.dumps(str(CALIBRATION)),
    "tutorial": json.dumps(str(TUTORIAL)),
    "recorder": json.dumps(str(RECORDER)),
    "scene": json.dumps(str(SCENE_INTERACT)),
}

DOM_PATCH = r"""
/* Le SVG et le focus, que l'onglet Expérimental n'exerçait pas. Un double qui
   ne peut pas déplacer le focus ne peut rien prouver d'un menu au clavier. */
const baseCreate=global.document.createElement;
const enrich=node=>{
  node.focus=function(){global.document.activeElement=this};
  node.blur=function(){if(global.document.activeElement===this)global.document.activeElement=null};
  node.removeAttribute=function(key){delete this.attrs[key]};
  return node;
};
global.document.createElement=tag=>enrich(baseCreate(tag));
global.document.createElementNS=(ns,tag)=>{
  const node=enrich(baseCreate(tag));
  node.namespaceURI=ns;
  return node;
};
/* L'horloge du démarrage se lit sur `Date.now()` : sous node elle doit
   s'avancer à la main, sinon « depuis combien de temps » ne se teste pas. */
global.clockMs=0;
Date.now=()=>global.clockMs;
const deepFind=(root,test)=>{
  for(const child of (root&&root.children)||[]){
    if(test(child))return child;
    const found=deepFind(child,test);
    if(found)return found;
  }
  return null;
};
const deepAll=(root,test)=>{
  const out=[];
  for(const child of (root&&root.children)||[]){
    if(test(child))out.push(child);
    for(const nested of deepAll(child,test))out.push(nested);
  }
  return out;
};
/* L'emplacement que `control_center.html` déclare. Le module refuse de
   s'installer sans lui, exprès : un contrôle posé au hasard du `body` sortirait
   du registre d'empilement sans que rien ne le dise. */
const hudHost=global.document.createElement('div');
hudHost.id='barehandsHud';
global.document.body.appendChild(hudHost);
"""

TAIL = r"""
delete require.cache[require.resolve(SCRIPT_PATH)];
const CORE=require(SCRIPT_PATH);
delete require.cache[require.resolve(HUD_PATH)];
const H=require(HUD_PATH);
const BAREHANDS=window.JarvisBarehands;
const settle=async()=>{for(let i=0;i<12;i+=1)await new Promise(r=>setImmediate(r))};
const host=document.getElementById(H.DOM.hostId);
const trigger=()=>document.getElementById(H.DOM.triggerId);
const caption=()=>document.getElementById(H.DOM.captionId);
const toneOf=node=>node.getAttribute(H.DOM.toneAttribute);
const modeButtons=root=>deepAll(root,n=>n.attrs&&n.attrs[H.DOM.modeAttribute]!==undefined);
const modeButton=(root,mode)=>modeButtons(root).find(n=>n.attrs[H.DOM.modeAttribute]===mode)||null;
/* Une seconde instance, **non abonnée** à la couture : c'est elle qu'on nourrit
   d'instantanés choisis pour décrire une présentation sans passer par un
   moteur. Celle de la page reste branchée sur la vraie couture, et les tests
   qui parlent d'elle ne touchent pas à celle-ci. */
const sandbox=()=>{
  const box=document.createElement('div');
  box.id='barehandsHudSandbox'+Math.random().toString(36).slice(2);
  document.body.appendChild(box);
  const calls=[];
  const surface={
    disable(){calls.push('disable');return Promise.resolve(null)},
    enable(){calls.push('enable');return Promise.resolve(null)},
    activate(){calls.push('activate');return Promise.resolve(null)},
    sleep(){calls.push('sleep');return Promise.resolve(null)},
  };
  const control=H.createHudControl({document,host:box,
    surface:()=>surface,now:()=>global.clockMs,
    setInterval:global.window.setInterval,clearInterval:global.window.clearInterval,
    setTimeout:global.window.setTimeout,log:()=>{}});
  return {box,control,calls,surface};
};
/* La forme exacte que la couture publie. Écrite une fois ici pour que les
   tests de présentation décrivent un instantané et non une page. */
const snap=over=>Object.assign({lifecycle:'off',state:'off',starting:false,
  code:null,title:'',message:'',enabled:false,busy:false},over||{});
"""


def browser(setup: str = "") -> str:
    """Le monde navigateur, le contrôle installé, et un état de serveur posé
    avant le chargement (comme la Slice 07 : le serveur ne change pas d'avis
    entre le chargement de la page et la première image)."""

    return PATCH + BROWSER_HEAD + DOM_PATCH + TIMERS + setup + TAIL


def run_node(tmp_path: Path, source: str, name: str = "hud") -> object:
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


# ------------------------------------------------------------ présentations


def test_the_button_paints_one_presentation_for_each_lifecycle(tmp_path):
    """Décisions 3, 4 et 5, et le refus qu'elles impliquent.

    `off` gris, `sleep` bleu ordinaire, `active` bleu plus clair **et entouré**.
    `starting` et `error` ne sont pas des modes : aucune pastille n'y est
    cochée, sans quoi une caméra refusée se lirait « l'utilisateur l'a voulu »,
    exactement ce que l'état `ERROR` existe pour empêcher (contrat § 1)."""

    result = run_node(tmp_path, browser() + r"""
      const {box,control}=sandbox();
      const read=()=>({
        tone:toneOf(box),
        caption:caption?null:null,
        cap:deepFind(box,n=>n.id===H.DOM.captionId).textContent,
        checked:modeButtons(box).map(n=>[n.attrs[H.DOM.modeAttribute],n.attrs['aria-checked']]),
        label:deepFind(box,n=>n.id===H.DOM.triggerId).attrs['aria-label'],
        busy:deepFind(box,n=>n.id===H.DOM.triggerId).attrs['aria-busy'],
      });
      const seen={};
      control.render(snap({lifecycle:'off',state:'off'}));seen.off=read();
      control.render(snap({lifecycle:'sleep',state:'sleep',enabled:true}));seen.sleep=read();
      control.render(snap({lifecycle:'active',state:'active',enabled:true}));seen.active=read();
      control.render(snap({lifecycle:'off',state:'starting',starting:true,enabled:true}));seen.starting=read();
      control.render(snap({lifecycle:'error',state:'error',code:'camera_denied',
        title:'Caméra refusée',message:'Autorisez la caméra puis réessayez.'}));seen.error=read();
      out({seen,
        /* La feuille est lue telle quelle : l'échelle des trois tons y est
           écrite une seule fois et le halo n'appartient qu'à l'actif. */
        glow:{
          activeHasGlow:/data-bh-tone=active\][\s\S]{0,400}?--bh-hud-glow:0 0 0 1px/.test(H.STYLE),
          sleepNoGlow:/data-bh-tone=sleep\],[\s\S]{0,400}?--bh-hud-glow:none/.test(H.STYLE),
          offNoGlow:/data-bh-tone=off\],[\s\S]{0,300}?--bh-hud-glow:none/.test(H.STYLE),
        },
        /* L'actif n'est pas vert, et l'idée retirée ne doit pas revenir par la
           bande : ni le jeton `--ok`, ni sa valeur, ni le mot. */
        green:['--ok','#68e0a0','green'].filter(token=>H.STYLE.includes(token)),
      });
    """, name="presentation")

    seen = result["seen"]
    assert [seen[k]["tone"] for k in ("off", "sleep", "active", "starting", "error")] == [
        "off", "sleep", "active", "starting", "error"
    ]
    assert seen["off"]["cap"] == "ÉTEINT"
    assert seen["sleep"]["cap"] == "VEILLE"
    assert seen["active"]["cap"] == "ACTIF"
    assert seen["error"]["cap"] == "INTERROMPU"
    assert seen["starting"]["cap"].startswith("DÉMARRAGE ")
    # Un mode coché par état d'usage, et **aucun** hors des trois.
    assert dict(seen["off"]["checked"]) == {"off": "true", "sleep": "false", "active": "false"}
    assert dict(seen["sleep"]["checked"])["sleep"] == "true"
    assert dict(seen["active"]["checked"])["active"] == "true"
    assert set(dict(seen["error"]["checked"]).values()) == {"false"}
    assert set(dict(seen["starting"]["checked"]).values()) == {"false"}
    # La panne dit son motif ; le démarrage dit comment en sortir (RÈGLE ZÉRO).
    assert "camera_denied" in seen["error"]["label"]
    assert "Éteint" in seen["starting"]["label"] and "annuler" in seen["starting"]["label"]
    assert seen["starting"]["busy"] == "true" and seen["sleep"]["busy"] == "false"
    assert result["glow"] == {"activeHasGlow": True, "sleepNoGlow": True, "offNoGlow": True}
    assert result["green"] == [], "l'actif est bleu électrique, pas vert (décision 5)"


def test_the_chooser_is_three_times_the_same_hand_and_selects_directly(tmp_path):
    """Décision 6 : un sélecteur **visuel**, fait du même motif de main dans ses
    trois variantes, directement cliquable. Ni liste déroulante, ni cycle
    aveugle — et pas trois dessins différents, sinon « la même main » n'aurait
    servi à rien."""

    result = run_node(tmp_path, browser() + """
      const {box,control}=sandbox();
      control.render(snap({lifecycle:'sleep',state:'sleep',enabled:true}));
      const chooser=deepFind(box,n=>n.id===H.DOM.chooserId);
      const before=chooser.hidden;
      control.open();
      const options=modeButtons(box);
      const iconOf=node=>deepAll(node,n=>n.tag==='path'||n.tag==='circle')
        .map(n=>n.tag+':'+(n.attrs.d||(n.attrs.cx+','+n.attrs.cy)));
      const trig=deepFind(box,n=>n.id===H.DOM.triggerId);
      out({
        before,after:chooser.hidden,
        /* Pas une liste déroulante : aucun `select`, aucune `option`. */
        selects:deepAll(box,n=>n.tag==='select'||n.tag==='option').length,
        modes:options.map(n=>n.attrs[H.DOM.modeAttribute]),
        roles:[chooser.attrs.role].concat(options.map(n=>n.attrs.role)),
        /* Le même dessin partout : les trois pastilles portent exactement le
           tracé du bouton, seul le ton change. */
        sameHand:options.every(n=>JSON.stringify(iconOf(n))===JSON.stringify(iconOf(trig))),
        chipTones:options.map(n=>deepFind(n,c=>c.attrs&&c.attrs[H.DOM.toneAttribute])
          .attrs[H.DOM.toneAttribute]),
        captions:options.map(n=>deepAll(n,c=>c.className==='bh-hud-cap').map(c=>c.textContent)),
      });
    """, name="chooser")

    assert result["before"] is True and result["after"] is False
    assert result["selects"] == 0, "un sélecteur visuel, pas une liste déroulante"
    assert result["modes"] == ["off", "sleep", "active"]
    assert result["roles"] == ["menu", "menuitemradio", "menuitemradio", "menuitemradio"]
    assert result["sameHand"] is True
    assert result["chipTones"] == ["off", "sleep", "active"]
    assert result["captions"] == [["ÉTEINT"], ["VEILLE"], ["ACTIF"]]


def test_each_mode_drives_the_authoritative_entry_points_in_order(tmp_path):
    """Architecture § 1, littéralement. `OFF` écrit l'interrupteur maître à faux
    et rend la caméra ; `SLEEP` et `ACTIVE` s'assurent d'abord que Bare Hands
    est allumé.

    L'**ordre** compte et se teste : `enable()` avant `activate()` laisserait le
    contrôleur en démarrage, état où `activate()` rend la main tout de suite
    sans rien réveiller — c'est la panne que la Slice 02 a déjà payée une fois
    (commentaire de `LIFECYCLE_LABEL`)."""

    result = run_node(tmp_path, browser() + """
      const pick=async(mode,from)=>{
        const {box,control,calls}=sandbox();
        control.render(snap(from));
        control.open();
        await modeButton(box,mode).fire('click');
        await settle();
        return {calls,open:control.isOpen()};
      };
      out({
        off:await pick('off',{lifecycle:'active',state:'active',enabled:true}),
        sleepFromActive:await pick('sleep',{lifecycle:'active',state:'active',enabled:true}),
        sleepFromOff:await pick('sleep',{lifecycle:'off',state:'off'}),
        activeFromOff:await pick('active',{lifecycle:'off',state:'off'}),
        activeFromSleep:await pick('active',{lifecycle:'sleep',state:'sleep',enabled:true}),
        activeFromError:await pick('active',{lifecycle:'error',state:'error',code:'camera_busy'}),
      });
    """, name="mapping")

    # Éteindre, c'est `disable()` — l'écriture du maître **et** la caméra rendue.
    # Jamais `sleep()`, qui garderait l'objectif ouvert.
    assert result["off"]["calls"] == ["disable"]
    # Endormir depuis l'interaction : on endort, puis on persiste le maître.
    assert result["sleepFromActive"]["calls"] == ["sleep", "enable"]
    # Depuis l'extinction, `enable()` seul arme le guetteur : rien à endormir.
    assert result["sleepFromOff"]["calls"] == ["enable"]
    # Activer : la chaîne complète d'abord, la persistance ensuite.
    assert result["activeFromOff"]["calls"] == ["activate", "enable"]
    assert result["activeFromSleep"]["calls"] == ["activate", "enable"]
    assert result["activeFromError"]["calls"] == ["activate", "enable"]
    # Un choix referme le sélecteur : il n'y a rien d'autre à y faire.
    for key in result:
        assert result[key]["open"] is False, key


def test_choosing_off_writes_the_master_switch_and_releases_the_camera(tmp_path):
    """« Éteint » doit être le seul mode où la posture en C ne peut rien. Deux
    choses le tiennent, et le test les prouve là où chacune est observable.

    Sur la **vraie page** : l'interrupteur maître part réellement à faux sur le
    serveur, donc il survit au rechargement, et plus rien n'est tenu.

    Sur le **vrai contrôleur** (le monde injecté de la Slice 02, le seul endroit
    où une caméra existe sous node) : le chemin que `disable()` emprunte quand
    quelque chose *est* tenu rend l'objectif, la vidéo, le modèle et la
    surimpression. Le bloc navigateur ne peut pas être poussé jusque-là — node
    n'a pas de caméra — et ce fichier préfère le dire que le simuler.

    Épinglé au passage : **une panne ne devient pas un « éteint » choisi.**
    Sous node, allumer échoue ; choisir « Éteint » écrit bien le maître à faux,
    mais le cycle de vie reste `error` et le bouton continue de montrer le
    motif. C'est la règle du contrat § 1 — on sort d'`ERROR` en rallumant, pas
    en repeignant — et non un oubli."""

    result = run_node(tmp_path, browser("server.state.enabled=true;") + WORLD + """
      await settle();
      const before={life:BAREHANDS.lifecycleStatus().lifecycle,enabled:BAREHANDS.state().enabled};
      const control=window.JarvisBarehandsHudControl;
      control.open();
      await modeButton(host,'off').fire('click');
      await settle();

      /* Le vrai contrôleur, avec sa caméra injectée : ce que « Éteint » rend
         quand il y a quelque chose à rendre. */
      const w=world({});
      const c=CORE.createController(w.deps);
      await c.enable();
      await c.activate();
      const held=[c.state(),w.track.stopped];
      c.disable();
      out({
        before,
        /* Ce que le serveur a **reçu**, pas ce que l'écran croit. */
        writes:server.calls.filter(c2=>c2.body).map(c2=>c2.body.enabled),
        enabled:BAREHANDS.state().enabled,
        life:BAREHANDS.lifecycleStatus().lifecycle,
        tone:toneOf(host),
        code:BAREHANDS.lifecycleStatus().code,
        /* `isEngagedState` est la question « quelque chose est-il tenu et à
           rendre ? » : après « Éteint », la réponse doit être non. */
        holding:CORE.isEngagedState(BAREHANDS.state().controller),
        held,released:[c.state(),w.track.stopped],
        log:w.log.filter(line=>['track.stop','video.dispose','model.close','overlay.unmount']
          .includes(line)),
      });
    """, name="off")

    assert result["before"]["enabled"] is True
    assert result["writes"][-1] is False, "l'interrupteur maître part à faux sur le serveur"
    assert result["enabled"] is False
    assert result["holding"] is False, "plus rien n'est tenu"
    # Une panne reste une panne : elle ne se repeint pas en « éteint » choisi.
    assert result["life"] == "error" and result["tone"] == "error"
    assert result["code"] == "camera_unsupported"
    # Et là où quelque chose est tenu, « Éteint » rend tout.
    assert result["held"] == ["active", False]
    assert result["released"] == ["off", True], "la caméra est rendue"
    assert sorted(set(result["log"])) == [
        "model.close", "overlay.unmount", "track.stop", "video.dispose"
    ]


# ------------------------------------------------------------- la couture


def test_an_external_transition_repaints_the_button_with_the_panel_closed(tmp_path):
    """**Le test de la couture.** Avant cette Slice, un changement de cycle de
    vie n'atteignait l'écran que par `refreshPanel()`, qui ne peint que l'onglet
    Expérimental **ouvert**. Ici l'onglet est fermé et la transition vient de la
    surface publique — celle qu'appellent la voix, le canal MCP et le panneau :
    le bouton doit suivre quand même.

    C'est aussi la preuve que la publication précède le garde-fou du panneau :
    placée après, elle n'aurait atteint personne."""

    result = run_node(tmp_path, browser("global.SET.open=false;") + """
      await settle();
      const start=[toneOf(host),caption().textContent];
      /* Une sonde **derrière** le contrôle : les consommateurs sont servis dans
         l'ordre d'inscription et le contrôle s'est inscrit au chargement, donc
         chaque relevé lit le bouton **déjà repeint**. C'est ce qui permet de
         décrire la suite des états traversés et pas seulement le dernier. */
      const tones=[];
      BAREHANDS.openLifecycleSeam('probe',()=>tones.push(toneOf(host)));
      await BAREHANDS.enable();
      await settle();
      const after=[toneOf(host),BAREHANDS.lifecycleStatus().lifecycle,
        BAREHANDS.lifecycleStatus().code];
      await BAREHANDS.disable();
      await settle();
      out({
        /* Le contrôle est inscrit sous son nom : « le bouton écoute » ne doit
           pas s'écrire comme « personne n'écoute ». */
        seam:BAREHANDS.lifecycleSeam(),
        panelClosed:SET.open,
        start,tones,after,
        back:[toneOf(host),BAREHANDS.lifecycleStatus().lifecycle,
          BAREHANDS.state().enabled],
        /* Et l'écran est d'accord avec le moteur, pas seulement plausible. */
        agreed:window.JarvisBarehandsHudControl.presentation().lifecycle
          ===BAREHANDS.lifecycleStatus().lifecycle,
      });
    """, name="seam")

    assert result["seam"] == ["hud", "probe"]
    assert result["panelClosed"] is False, "l'onglet de réglages est bien fermé"
    assert result["start"] == ["off", "ÉTEINT"]
    # Le bouton a suivi **chaque** étape, l'onglet fermé : l'attente de
    # démarrage, puis la panne. Sous node il n'y a pas de caméra, donc allumer
    # finit mal — ce qui est décrit ici n'est pas l'issue, c'est que chaque
    # étape **arrive** au bouton sans que personne n'ait ouvert les réglages.
    assert result["tones"][0] == "off", "l'instantané courant est rejoué à l'inscription"
    assert "starting" in result["tones"], "le démarrage se voit passer"
    assert result["tones"][-1] == "error"
    assert result["after"] == ["error", "error", "camera_unsupported"]
    # Éteindre écrit bien le maître à faux, mais une panne ne se repeint pas en
    # « éteint » choisi : on sort d'`ERROR` en rallumant (contrat § 1).
    assert result["back"] == ["error", "error", False]
    assert result["agreed"] is True


def test_the_seam_replays_the_current_state_and_refuses_a_consumer_that_is_not_one(tmp_path):
    """La couture rejoue l'instantané courant à l'ouverture — sans quoi un
    contrôle installé après la dernière transition partirait d'un état d'usine,
    c'est-à-dire, au rechargement, indéfiniment. Un instantané inchangé ne se
    republie pas, et un consommateur qui n'est pas une fonction est refusé sous
    un code stable plutôt qu'inscrit sur rien."""

    result = run_node(tmp_path, browser() + """
      await settle();
      const heard=[];
      const opened=BAREHANDS.openLifecycleSeam('probe',s=>heard.push(JSON.stringify(s)));
      const replayed=heard.map(line=>JSON.parse(line).lifecycle);
      /* Une écriture de réglage : elle repeint le panneau plusieurs fois — au
         départ, pendant l'attente, au retour — sans que le cycle de vie bouge
         à chaque fois. L'abonné ne doit jamais recevoir deux fois de suite le
         même instantané, sinon « ça a changé » et « on a repeint » s'écrivent
         pareil chez lui. */
      await BAREHANDS.settings({assistance:C.SETTINGS_DEFAULTS.assistance});
      await settle();
      await BAREHANDS.disable();
      await settle();
      const repeats=heard.filter((line,at)=>at>0&&line===heard[at-1]).length;
      const closed=BAREHANDS.closeLifecycleSeam('probe');
      const before=heard.length;
      await BAREHANDS.enable();
      await settle();
      let refusal=null;
      try{BAREHANDS.openLifecycleSeam('broken',null)}
      catch(error){refusal=error.code}
      out({opened,replayed,repeats,closed,
        seamAfterClose:BAREHANDS.lifecycleSeam(),
        deafAfterClose:heard.length===before,
        refusal,
        /* La forme publiée, en entier : ce que tout abonné peut lire. */
        shape:Object.keys(BAREHANDS.lifecycleStatus()).sort(),
      });
    """, name="seamapi")

    assert result["opened"] == 2, "le contrôle de la page, plus la sonde"
    assert result["replayed"] == ["off"], "l'instantané courant est rejoué tout de suite"
    assert result["repeats"] == 0, "un instantané identique ne se republie jamais"
    assert result["closed"] == 1
    assert result["seamAfterClose"] == ["hud"], "fermer un nom ne ferme que celui-là"
    assert result["deafAfterClose"] is True
    assert result["refusal"] == "barehands_lifecycle_seam_invalid"
    assert result["shape"] == [
        "busy", "code", "enabled", "lifecycle", "message", "starting", "state", "title"
    ]


def test_a_c_wake_and_the_idle_timeout_paint_the_button(tmp_path):
    """Le réveil en C et le retour en veille après 30 s, produits par le **vrai**
    contrôleur de la Slice 02 avec sa caméra injectée, puis peints par le
    **vrai** contrôle.

    Rien n'est inventé entre les deux : les instantanés proviennent des statuts
    que le moteur émet sur `onStatus`, c'est-à-dire exactement ce que la couture
    transporte en vivant (prouvé à l'onglet fermé par le test précédent). Le
    bloc navigateur ne peut pas être poussé jusque-là sous node — MediaPipe n'y
    est pas chargeable — et ce fichier préfère le dire que le simuler."""

    result = run_node(tmp_path, browser() + WORLD + """
      const w=world({});
      const c=CORE.createController(w.deps);
      const statuses=[];
      w.deps.onStatus=s=>statuses.push(s);
      await c.enable();
      /* Le guetteur voit le C, le tient une seconde, et réveille. */
      w.state.result=C_POSE;
      for(let i=0;i<40;i+=1)w.step(50);
      const woke=statuses[statuses.length-1];
      /* Plus de main exploitable : au bout de SLEEP_TIMEOUT_MS on rendort. */
      w.state.result=NO_HAND;
      for(let i=0;i<40;i+=1)w.step(1000);
      const dozed=statuses[statuses.length-1];

      const {box,control}=sandbox();
      const paint=status=>{
        control.render(snap({lifecycle:C.lifecycleOfControllerState(status.state),
          state:status.state,code:status.code,title:status.title,
          message:status.message,enabled:true}));
        return {tone:toneOf(box),
          cap:deepFind(box,n=>n.id===H.DOM.captionId).textContent,
          checked:modeButtons(box).filter(n=>n.attrs['aria-checked']==='true')
            .map(n=>n.attrs[H.DOM.modeAttribute])};
      };
      /* L'ordre compte : veille, puis réveil, puis retour en veille. */
      const asleep=paint(statuses.find(s=>s.code==='sleep'));
      const awake=paint(woke);
      const again=paint(dozed);
      out({codes:[statuses.find(s=>s.code==='sleep').code,woke.code,dozed.code],
        states:[woke.state,dozed.state],asleep,awake,again});
    """, name="wake")

    # Le moteur a bien produit un réveil en C puis un rendormissement d'inactivité.
    assert result["codes"] == ["sleep", "woken", "idle_sleep"]
    assert result["states"] == ["active", "sleep"]
    # Et l'écran les peint : veille → actif → veille.
    assert [result["asleep"]["tone"], result["awake"]["tone"], result["again"]["tone"]] == [
        "sleep", "active", "sleep"
    ]
    assert [result["asleep"]["cap"], result["awake"]["cap"], result["again"]["cap"]] == [
        "VEILLE", "ACTIF", "VEILLE"
    ]
    assert result["awake"]["checked"] == ["active"]
    assert result["again"]["checked"] == ["sleep"]


def test_a_voice_receipt_leaves_the_screen_and_the_engine_agreed(tmp_path):
    """Le canal de commandes du cerveau (Slice 12) remet la commande au **même**
    point d'entrée que le bouton. Ce que la page constate doit donc se retrouver
    à l'écran sans qu'aucune ligne du canal ne parle du bouton."""

    result = run_node(tmp_path, browser() + """
      delete require.cache[require.resolve(COMMANDS_PATH)];
      const CMD=require(COMMANDS_PATH);
      await settle();
      const control=window.JarvisBarehandsHudControl;
      const before=[toneOf(host),control.presentation().lifecycle];
      const said=[];
      const channel=CMD.createCommandChannel({
        request:async()=>({status:200,body:{}}),
        surface:()=>window.JarvisBarehands,
        now:()=>global.clockMs,sleep:async()=>{},random:()=>0,
        onReceipt:entry=>said.push(entry),log:()=>{}});
      await channel.apply({name:'activate',id:'v'.repeat(40),remaining_ms:5000});
      await settle();
      out({
        before,
        /* Le reçu dit ce que la page a **constaté**, jamais ce qu'on a demandé. */
        receipt:{outcome:said[0].outcome,lifecycle:said[0].lifecycle},
        engine:BAREHANDS.lifecycleStatus().lifecycle,
        painted:control.presentation().lifecycle,
        tone:toneOf(host),
        cap:caption().textContent,
        /* Le motif du refus reste lisible à l'écran, pas seulement au reçu. */
        code:BAREHANDS.lifecycleStatus().code,
        spoken:deepFind(host,n=>n.id===H.DOM.announceId).textContent,
      });
    """, name="voice")

    assert result["before"] == ["off", "off"]
    # Sous node il n'y a pas de caméra : la commande vocale échoue. Ce qui est
    # décrit ici n'est pas l'issue, c'est que l'écran la reprenne.
    assert result["receipt"]["outcome"] == "refused"
    assert result["receipt"]["lifecycle"] == "error"
    assert result["painted"] == result["engine"] == result["receipt"]["lifecycle"]
    assert result["tone"] == "error" and result["cap"] == "INTERROMPU"
    assert result["code"] == "camera_unsupported"
    assert "camera_unsupported" in result["spoken"]


# ------------------------------------------------------------ clavier, ARIA


def test_the_keyboard_reaches_everything_the_mouse_reaches(tmp_path):
    """Tout ce que la souris atteint, le clavier l'atteint — et **rien de plus**
    ne se déclenche en chemin.

    Les flèches déplacent le focus sans choisir : un groupe de radios choisirait
    en passant dessus, et traverser ce sélecteur-là au clavier ouvrirait puis
    rendrait la caméra à chaque touche. C'est pourquoi c'est un menu
    (`menuitemradio`) et non un `radiogroup`."""

    result = run_node(tmp_path, browser() + """
      const {box,control,calls}=sandbox();
      control.render(snap({lifecycle:'sleep',state:'sleep',enabled:true}));
      const trig=deepFind(box,n=>n.id===H.DOM.triggerId);
      const opts=modeButtons(box);
      const at=()=>opts.findIndex(n=>n===document.activeElement);
      const steps=[];
      /* Flèche bas sur le bouton : le menu s'ouvre sur le mode courant. */
      trig.fire('keydown',{key:'ArrowDown'});
      steps.push(['open',control.isOpen(),at()]);
      /* Les flèches font le tour, dans les deux sens, sans rien choisir. */
      opts[at()].fire('keydown',{key:'ArrowRight'});steps.push(['right',control.isOpen(),at()]);
      opts[at()].fire('keydown',{key:'ArrowRight'});steps.push(['wrap',control.isOpen(),at()]);
      opts[at()].fire('keydown',{key:'ArrowLeft'});steps.push(['left',control.isOpen(),at()]);
      opts[at()].fire('keydown',{key:'Home'});steps.push(['home',control.isOpen(),at()]);
      opts[at()].fire('keydown',{key:'End'});steps.push(['end',control.isOpen(),at()]);
      const movedWithoutChoosing=calls.slice();
      /* Un seul arrêt de tabulation dans le menu : celui du curseur. */
      const tabstops=opts.map(n=>n.attrs.tabindex);
      /* Entrée/Espace : le bouton natif émet son clic, qui choisit. */
      opts[at()].fire('click');
      await settle();
      const chosen=calls.slice();
      const focusBack=document.activeElement===trig;
      /* Échap referme et **rend le focus** : sinon il reste sur un nœud caché. */
      control.open();
      document.activeElement=opts[0];
      opts[0].fire('keydown',{key:'Escape'});
      const escaped=[control.isOpen(),document.activeElement===trig];
      /* Le focus qui part ailleurs referme aussi — sans quoi le menu resterait
         ouvert derrière ce que l'on vient de cliquer. */
      control.open();
      document.activeElement=null;
      opts[0].fire('focusout');
      tick();
      out({steps,movedWithoutChoosing,tabstops,chosen,focusBack,escaped,
        outsideClosed:control.isOpen()});
    """, name="keyboard")

    # Ouverture sur le mode courant (veille = index 1), puis tour complet.
    assert result["steps"] == [
        ["open", True, 1], ["right", True, 2], ["wrap", True, 0],
        ["left", True, 2], ["home", True, 0], ["end", True, 2],
    ]
    assert result["movedWithoutChoosing"] == [], "une flèche déplace le focus, elle ne choisit pas"
    assert result["tabstops"] == ["-1", "-1", "0"], "un seul arrêt de tabulation : le curseur"
    assert result["chosen"] == ["activate", "enable"], "le clic clavier choisit, lui"
    assert result["focusBack"] is True, "le focus revient au bouton après un choix"
    assert result["escaped"] == [False, True], "Échap referme et rend le focus"
    assert result["outsideClosed"] is False


def test_the_control_says_its_state_to_a_screen_reader(tmp_path):
    """Les équivalents ARIA de tout ce que la couleur dit. Un contrôle dont
    l'état ne vit que dans une teinte n'existe pas pour qui ne la voit pas."""

    result = run_node(tmp_path, browser() + """
      const {box,control}=sandbox();
      const trig=deepFind(box,n=>n.id===H.DOM.triggerId);
      const chooser=deepFind(box,n=>n.id===H.DOM.chooserId);
      const announcer=deepFind(box,n=>n.id===H.DOM.announceId);
      control.render(snap({lifecycle:'sleep',state:'sleep',enabled:true}));
      const closed=[trig.attrs['aria-expanded'],chooser.hidden];
      const spokenSleep=announcer.textContent;
      control.open();
      const opened=[trig.attrs['aria-expanded'],chooser.hidden];
      control.close({focus:true});
      control.render(snap({lifecycle:'active',state:'active',enabled:true}));
      const spokenActive=announcer.textContent;
      /* Une repeinture identique ne doit pas re-parler : une région vivante qui
         répète le même mot cesse d'être écoutée. */
      announcer.textContent='';
      control.render(snap({lifecycle:'active',state:'active',enabled:true}));
      const repeated=announcer.textContent;
      control.render(snap({lifecycle:'error',state:'error',code:'camera_busy',
        title:'Caméra occupée',message:'Une autre application l’utilise.'}));
      out({
        trigger:{haspopup:trig.attrs['aria-haspopup'],controls:trig.attrs['aria-controls'],
          type:trig.attrs.type,id:trig.id},
        chooserId:chooser.id,chooserRole:chooser.attrs.role,
        chooserLabel:chooser.attrs['aria-label'],
        live:{role:announcer.attrs.role,polite:announcer.attrs['aria-live']},
        closed,opened,spokenSleep,spokenActive,repeated,
        spokenError:announcer.textContent,
        /* Une écriture en vol désarme les pastilles et se dit. */
        busy:(()=>{control.render(snap({lifecycle:'sleep',state:'sleep',enabled:true,busy:true}));
          return [trig.attrs['aria-busy'],modeButtons(box).map(n=>n.disabled)]})(),
      });
    """, name="aria")

    assert result["trigger"] == {
        "haspopup": "menu", "controls": "barehandsHudChooser",
        "type": "button", "id": "barehandsHudButton",
    }
    assert result["chooserId"] == "barehandsHudChooser"
    assert result["chooserRole"] == "menu" and result["chooserLabel"] == "Mode Bare Hands"
    assert result["live"] == {"role": "status", "polite": "polite"}
    assert result["closed"] == ["false", True] and result["opened"] == ["true", False]
    assert result["spokenSleep"] == "Bare Hands : Veille."
    assert result["spokenActive"] == "Bare Hands : Actif."
    assert result["repeated"] == "", "le même état ne se redit pas"
    assert "camera_busy" in result["spokenError"]
    assert result["busy"] == ["true", [True, True, True]]


def test_a_start_that_can_last_says_how_long_it_has_lasted(tmp_path):
    """RÈGLE ZÉRO. Le démarrage attend `getUserMedia`, donc une invite de
    permission qu'aucune horloge ne borne. Sans compteur, « ça travaille » et
    « c'est figé » sont le même écran — et la sortie doit rester atteignable."""

    result = run_node(tmp_path, browser() + r"""
      const {box,control}=sandbox();
      const cap=()=>deepFind(box,n=>n.id===H.DOM.captionId).textContent;
      const trig=deepFind(box,n=>n.id===H.DOM.triggerId);
      global.clockMs=1000;
      control.render(snap({lifecycle:'off',state:'starting',starting:true,enabled:true}));
      const at0=cap();
      global.clockMs=4000;tick();
      const at3=cap();
      global.clockMs=12000;tick();
      const at11=cap();
      const armed=ticks();
      /* La sortie reste atteignable pendant l'attente : le sélecteur s'ouvre et
         « Éteint » annule un démarrage en vol. */
      control.open();
      const note=deepFind(box,n=>n.id===H.DOM.noteId);
      const escape=[control.isOpen(),note.hidden,note.textContent];
      control.close({focus:false});
      /* Le démarrage finit : le compteur se désarme de lui-même. */
      global.clockMs=13000;
      control.render(snap({lifecycle:'sleep',state:'sleep',enabled:true}));
      tick();
      out({at0,at3,at11,armed,escape,settled:cap(),
        label:trig.attrs['aria-label'],
        /* Mouvement coupé : le compteur, lui, ne s'arrête pas. */
        reducedMotionKeepsTheClock:/prefers-reduced-motion[\s\S]*animation:none/.test(H.STYLE),
      });
    """, name="starting")

    assert result["at0"] == "DÉMARRAGE 0 S"
    assert result["at3"] == "DÉMARRAGE 3 S"
    assert result["at11"] == "DÉMARRAGE 11 S"
    assert result["armed"] >= 1, "une minuterie d'affichage est bien armée"
    # Le sélecteur reste ouvrable et dit comment sortir.
    assert result["escape"][0] is True and result["escape"][1] is False
    assert "Éteint" in result["escape"][2]
    assert result["settled"] == "VEILLE", "le compteur se retire quand l'attente finit"
    assert result["reducedMotionKeepsTheClock"] is True


# --------------------------------------------------------------- la page


async def test_the_page_serves_the_pointer_before_the_hud_that_subscribes_to_it(tmp_path):
    """Constat F3 : un module de page est un repère substitué par le serveur, et
    son rang est porteur. Celui-ci lit `window.JarvisBarehands` **et** la couture
    de cycle de vie que le pointeur pose dessus — une surface **gelée**, donc
    impossible à compléter après coup. Servi trop tôt, le contrôle ne s'installe
    pas ; l'ordre est donc asserté par index dans la page servie, pas par la
    seule présence des repères."""

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    raw = PAGE_HTML.read_text(encoding="utf-8")

    assert BAREHANDS_HUD_SCRIPT_MARKER in raw, "le repère vit dans la page"
    assert raw.index(BAREHANDS_SCRIPT_MARKER) < raw.index(BAREHANDS_HUD_SCRIPT_MARKER)
    assert BAREHANDS_HUD_SCRIPT_MARKER not in html, "le repère a été remplacé"
    assert "root.JarvisBarehandsHud=api" in html
    assert html.index("window.JarvisBarehands=Object.freeze") < html.index(
        "function installJarvisBarehandsHud"
    )
    # L'emplacement est déclaré dans la page : c'est lui qui porte le rang
    # d'empilement du registre, et le module refuse de s'installer sans lui.
    assert 'id="barehandsHud"' in raw
    assert "contrôle Bare Hands du haut-gauche 32" in raw, "le registre d'empilement le nomme"
    # Le contrôle n'entre pas dans le dock : le dock reste six boutons de texte.
    dock = raw[raw.index('<nav class="dock"'):raw.index("</nav>")]
    assert "barehandsHud" not in dock


def test_the_control_refuses_by_name_rather_than_guessing(tmp_path):
    """« Un refus codé plutôt qu'un défaut plausible » (contrat, § en tête).

    Trois absences possibles, trois refus nommés et confinés : sans la surface,
    sans la couture, sans l'emplacement. Et confinés veut dire confinés — la
    page servie n'a qu'une balise `<script>`, donc une levée qui remonterait
    emporterait la scène, la chronologie et le Test Lab avec elle."""

    result = run_node(tmp_path, PATCH + BROWSER_HEAD + DOM_PATCH + TIMERS + """
      const codes=[];
      const realError=console.error;
      console.error=line=>codes.push(String(line));
      const load=()=>{delete require.cache[require.resolve(HUD_PATH)];require(HUD_PATH)};
      /* 1. Aucun pointeur : la surface n'existe pas. */
      delete window.JarvisBarehands;
      load();
      /* 2. Une surface, mais pas de couture : le contrôle ne se tairait pas —
            il refuserait, parce qu'un bouton qui n'apprend jamais rien est
            indiscernable d'un bouton qui marche. */
      window.JarvisBarehands=Object.freeze({state:()=>({})});
      load();
      /* 3. La couture, mais pas l'emplacement déclaré par la page. */
      window.JarvisBarehands=Object.freeze({state:()=>({}),
        openLifecycleSeam:()=>1,lifecycleSeam:()=>[]});
      hudHost.remove();
      load();
      console.error=realError;
      out({installed:typeof window.JarvisBarehandsHud==='object',
        control:typeof window.JarvisBarehandsHudControl,
        named:codes.every(line=>line.includes('barehands.hud_not_installed')),
        codes:codes.map(line=>{
          const at=line.indexOf('{');
          return at<0?line:JSON.parse(line.slice(at)).code;
        })});
    """, name="refusals")

    # Le module s'expose quand même : c'est son **installation** qui refuse, pas
    # sa définition — la page servie n'a qu'une balise `<script>`, donc une levée
    # qui remonterait emporterait la scène, la chronologie et le Test Lab.
    assert result["installed"] is True
    assert result["control"] == "undefined", "aucun contrôle posé sur un refus"
    assert result["named"] is True, "le refus part sous un nom cherchable"
    assert result["codes"] == [None, "barehands_hud_seam_missing", "barehands_hud_host_missing"]
