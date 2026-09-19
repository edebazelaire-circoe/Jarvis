"""Le canal de commandes **dans la page** (Slice 12), par node.

Ce que ce fichier épingle :

- **la voix et le bouton passent par le même point d'entrée**, et la preuve
  n'est pas une lecture de code : les deux chemins sont exécutés sur le **vrai**
  bloc navigateur de `control_center_barehands.js`, depuis le même état de
  départ, et laissent la page dans un état **identique** — même cycle de vie,
  même bloc `#barehandsLifecycle` redessiné, même bandeau. Un canal qui
  réimplanterait « réveiller » ne redessinerait pas le panneau, parce que c'est
  `setAwake` qui finit par `refreshPanel()` ;
- **on rapporte ce que la page constate** : sous node il n'y a pas de caméra,
  donc le vrai `activate()` finit en `error`, et le reçu dit `refused` /
  `barehands_lifecycle_refused` / `error`. C'est un refus honnête de bout en
  bout, pas une mise en scène ;
- **ce qu'un cerveau voit aujourd'hui** pour la calibration, le tutoriel et la
  sortie de panneau : leurs points d'entrée sont **absents de la vraie
  surface**, ce que le test lit sur l'objet réel, donc `barehands_flow_absent` ;
- **rien ne tourne quand Bare Hands est éteint**, et la boucle s'arrête aussi
  quand l'onglet est caché.

Le contrat, le pointeur et le canal ne sont pas simulés : ce sont les vrais
modules. Seuls le DOM et le réseau sont des doubles — ce que node n'a pas.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain import barehands_command as vocab

# Le double de DOM de l'onglet Expérimental est **réutilisé**, pas recopié : il
# exécute le vrai bloc navigateur du pointeur, et une seconde version dériverait
# de celle que la Slice 07 tient.
from test_barehands_tools_settings_js import BROWSER, CONTRACTS, SCENE_INTERACT, SCRIPT, TARGET  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
COMMANDS = RUNTIME / "control_center_barehands_commands.js"

#: Ce que le canal a besoin de trouver et que le double de la Slice 07 n'a pas :
#: de vraies minuteries (le double exécute `setTimeout` tout de suite, ce qui
#: avorterait chaque requête et rendrait chaque attente nulle), la visibilité de
#: l'onglet, et un réseau.
NETWORK = r"""
/* Les vraies minuteries, prises AVANT que le double les remplace par une
   exécution immédiate : le canal lit `window.setTimeout`, le pointeur lit
   `setTimeout`. Les deux gardent ce dont ils ont besoin. */
window.setTimeout=REAL_SET_TIMEOUT;
window.clearTimeout=REAL_CLEAR_TIMEOUT;
window.addEventListener=()=>{};
document.visibilityState='visible';
document.addEventListener=(type,fn)=>{(docListeners[type]=docListeners[type]||[]).push(fn)};
const network={polls:0,receipts:[],queue:[],parked:0};
const parked=[];
const resumeParked=()=>{
  while(parked.length){
    const resolve=parked.shift();
    const body=network.queue.length?{command:network.queue.shift()}:{command:null};
    resolve({status:200,text:async()=>JSON.stringify(body)});
  }
};
global.fetch=async(url,init)=>{
  const text=String(url);
  if(text.indexOf('/api/barehands/commands?')===0){
    network.polls++;
    if(network.queue.length)return {status:200,text:async()=>JSON.stringify({command:network.queue.shift()})};
    /* Plus rien à remettre : le long-poll **attend**, comme le vrai. Une
       réponse vide immédiate ferait tourner la boucle à vide dans le test et
       ne ressemblerait à rien de ce que le serveur fait. `resumeParked()` est
       la main du test sur ce que le serveur ferait à l'arrivée d'une commande. */
    network.parked++;
    return new Promise(resolve=>parked.push(resolve));
  }
  if(/\/api\/barehands\/commands\//.test(text)){
    network.receipts.push(JSON.parse(init.body));
    return {status:200,text:async()=>JSON.stringify({command:'x',id:'y'})};
  }
  throw new Error('requête inattendue : '+text);
};
delete require.cache[require.resolve(COMMANDS_PATH)];
const CH=require(COMMANDS_PATH);
const CHANNEL=window.JarvisBarehandsCommandChannel;
const idOf=n=>String(n).repeat(32).slice(0,32);
const queue=(name,id)=>network.queue.push({id:id||idOf(name[0]),name,remaining_ms:3000});
"""


def run_node(tmp_path: Path, source: str, name: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-commands-{name}.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
        f"const TARGET_PATH={json.dumps(str(TARGET))};\n"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};\n"
        f"const CONTRACTS_PATH={json.dumps(str(CONTRACTS))};\n"
        f"const COMMANDS_PATH={json.dumps(str(COMMANDS))};\n"
        "const REAL_SET_TIMEOUT=setTimeout,REAL_CLEAR_TIMEOUT=clearTimeout;\n"
        "const docListeners={};\n"
        "const C=require(CONTRACTS_PATH);\n"
        # Le vrai bloc navigateur arme de **vraies** minuteries (démarrage vidéo
        # de 10 s) dès qu'on l'active : sans sortie explicite, node attendrait
        # qu'elles retombent et chaque cas coûterait une trentaine de secondes.
        # La sortie est prise après le vidage de stdout, jamais avant.
        "const out=v=>process.stdout.write(JSON.stringify(v),()=>process.exit(0));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Après l'installation, laisser la boucle tourner jusqu'à ce qu'elle se gare.
SETTLE = """
const settleLong=async()=>{for(let i=0;i<40;i+=1)await new Promise(r=>REAL_SET_TIMEOUT(r,1))};
"""


# ------------------------------------------- le même point d'entrée que le bouton


def _observed(tmp_path: Path, drive: str, name: str) -> dict:
    """Ouvrir l'onglet, exécuter `drive`, et rendre ce que la page **montre**."""

    return run_node(tmp_path, BROWSER + NETWORK + SETTLE + """
      await openTab();
      const show=id=>{const n=document.getElementById(id);return n?n.innerHTML:'(absent)'};
      const before={lifecycle:BAREHANDS.lifecycle(),life:show('barehandsLifecycle')};
      """ + drive + """
      out({before,after:{lifecycle:BAREHANDS.lifecycle(),life:show('barehandsLifecycle'),
        status:show('barehandsStatus')},
        receipts:network.receipts,polls:network.polls,
        /* Les points d'entrée que le canal nomme, lus sur la **vraie** surface. */
        present:Object.keys(CH.ENTRY_POINTS).map(k=>[k,CH.ENTRY_POINTS[k].method,
          typeof BAREHANDS[CH.ENTRY_POINTS[k].method]==='function'])});
    """, name)


def test_the_button_and_the_voice_leave_the_page_in_the_same_state(tmp_path):
    """**La règle centrale de la Slice** : un seul point d'entrée par action.

    Les deux chemins partent du même état, sur le vrai bloc navigateur, et
    arrivent au même — même cycle de vie, même bloc de cycle de vie redessiné,
    même bandeau. Ce n'est pas une lecture de source : `#barehandsLifecycle`
    n'est réécrit que par `refreshPanel()`, que seul `setAwake` appelle. Une
    implantation parallèle du réveil laisserait ce bloc intact.

    Et sous node il n'y a pas de caméra : les deux chemins finissent donc en
    `error` (`camera_unsupported`). C'est exactement ce qui rend le test
    probant — un refus réel, identique des deux côtés."""

    button = _observed(tmp_path, """
      document.getElementById('barehandsWake').fire('click');
      await settle();await settleLong();
    """, "button")
    voice = _observed(tmp_path, """
      queue('activate');
      CHANNEL.gate({enabled:true});
      await settleLong();await settle();await settleLong();
    """, "voice")

    assert button["before"] == voice["before"], "même état de départ, sinon la comparaison ne dit rien"
    assert button["before"]["lifecycle"] == "off"
    # Le bouton a bien fait quelque chose : sans ça, l'égalité serait vide.
    assert button["after"]["lifecycle"] == "error" != button["before"]["lifecycle"]
    assert button["after"]["life"] != button["before"]["life"], "le panneau a été redessiné"
    # Et la voix laisse la page **exactement** dans cet état-là.
    assert voice["after"] == button["after"]
    assert "camera_unsupported" in button["after"]["life"]

    # Le bouton n'envoie aucun reçu ; la voix en envoie un, et il rapporte ce
    # que la page a constaté, pas ce qui a été demandé.
    assert button["receipts"] == [] and button["polls"] == 0
    assert voice["receipts"] == [{
        "outcome": "refused", "lifecycle": "error", "code": vocab.LIFECYCLE_REFUSED,
        "reason": "état error au lieu de active",
    }]


def test_what_a_brain_sees_today_for_calibration_tutorial_and_overlay(tmp_path):
    """Lu sur la **vraie** surface : `activate` et `sleep` existent, les trois
    parcours des Slices 08 et 09 n'existent pas. Le transport les porte quand
    même, et refuse avec un code qui dit précisément ça."""

    observed = _observed(tmp_path, """
      queue('calibrate');queue('tutorial');queue('exit_overlay');
      CHANNEL.gate({enabled:true});
      await settleLong();await settle();await settleLong();
    """, "flows")
    assert observed["present"] == [
        ["activate", "activate", True],
        ["deactivate", "sleep", True],
        ["calibrate", "calibrate", False],
        ["tutorial", "tutorial", False],
        ["exit_overlay", "exitOverlay", False],
    ]
    assert [r["code"] for r in observed["receipts"]] == [vocab.FLOW_ABSENT] * 3
    assert [r["outcome"] for r in observed["receipts"]] == ["refused"] * 3
    assert observed["receipts"][0]["reason"] == "JarvisBarehands.calibrate n'existe pas dans cette version"
    # La page n'a pas bougé : un parcours absent ne touche à rien.
    assert observed["after"]["lifecycle"] == observed["before"]["lifecycle"] == "off"


#: Une surface injectée, dont le contrat est **épinglé sur la vraie** par
#: `test_what_a_brain_sees_today_...` : `lifecycle()` rend une chaîne du cycle
#: de vie, et les points d'entrée rendent une promesse qui ne rejette pas.
#: Elle sert aux deux cas que node ne peut pas atteindre sur le vrai pointeur —
#: il n'y a pas de caméra, donc `active` est hors de portée.
SURFACE = r"""
const makeSurface=(life,answers)=>{
  const calls=[];
  const surface={lifecycle:()=>life,
    activate:async()=>{calls.push('activate');life=answers.activate===undefined?life:answers.activate},
    sleep:async()=>{calls.push('sleep');life=answers.sleep===undefined?life:answers.sleep}};
  for(const name of ['calibrate','tutorial','exitOverlay'])
    if(Object.prototype.hasOwnProperty.call(answers,name))
      surface[name]=async()=>{calls.push(name);return answers[name]};
  return {surface,calls,life:()=>life};
};
const drive=async(made,name)=>{
  const channel=CH.createCommandChannel({surface:()=>made.surface,now:()=>0,
    sleep:async()=>{},random:()=>0.5,request:async()=>({status:200,body:{}}),log:()=>{}});
  return await channel.dispatch(name);
};
"""


def test_a_flow_that_does_not_confirm_is_refused_not_announced(tmp_path):
    """La leçon que la QA de la Slice 07 vient de payer ailleurs : un appel qui
    ne lève pas n'est **pas** une preuve. `tool('scissors')` normalise vers
    `pointer`, enregistre et rend un succès ; un canal qui lirait « pas
    d'exception = fait » relaierait ce mensonge à la voix.

    Les Slices 08 et 09 héritent donc d'un contrat : confirmer, ou être
    refusées. C'est la seule marche qui sépare « le tutoriel est ouvert » de
    « on a appelé une fonction »."""

    result = run_node(tmp_path, BROWSER + NETWORK + SURFACE + """
      const cases={};
      for(const [label,answer] of [['undefined',undefined],['null',null],['false',false],
                                   ['muet',{}],['ok-faux',{ok:false}],
                                   ['vrai',true],['ok-vrai',{ok:true}]]){
        const made=makeSurface('sleep',{calibrate:answer});
        cases[label]=await drive(made,'calibrate');
        cases[label].called=made.calls;
      }
      out({cases,confirmed:[CH.confirmed(true),CH.confirmed({ok:true}),CH.confirmed(undefined),
        CH.confirmed(null),CH.confirmed(false),CH.confirmed({}),CH.confirmed({ok:'oui'})]});
    """, "confirm")
    assert result["confirmed"] == [True, True, False, False, False, False, False]
    for label in ("undefined", "null", "false", "muet", "ok-faux"):
        case = result["cases"][label]
        assert case["outcome"] == "refused", label
        assert case["code"] == vocab.FLOW_UNCONFIRMED, label
        # Le parcours a bien été appelé : c'est un refus de confirmation, pas
        # un refus d'appel — et le cerveau doit pouvoir dire la différence.
        assert case["called"] == ["calibrate"], label
    for label in ("vrai", "ok-vrai"):
        assert result["cases"][label]["outcome"] == "applied", label
        assert result["cases"][label]["code"] is None


def test_an_already_reached_state_is_a_duplicate_not_a_change(tmp_path):
    """« Active les mains » alors qu'elles le sont déjà est un succès, et le
    cerveau doit pouvoir le dire autrement que « voilà, c'est fait » — sinon
    l'utilisateur croit avoir changé quelque chose. Et un état visé **atteint**
    reste `applied` : c'est la distinction que la Slice porte au cerveau."""

    result = run_node(tmp_path, BROWSER + NETWORK + SURFACE + """
      const already=await drive(makeSurface('active',{activate:'active'}),'activate');
      const changed=await drive(makeSurface('sleep',{activate:'active'}),'activate');
      const refused=await drive(makeSurface('sleep',{activate:'error'}),'activate');
      const slept=await drive(makeSurface('active',{sleep:'sleep'}),'deactivate');
      const sleptTwice=await drive(makeSurface('sleep',{sleep:'sleep'}),'deactivate');
      out({already,changed,refused,slept,sleptTwice});
    """, "duplicate")
    assert result["already"] == {"outcome": "duplicate", "lifecycle": "active", "code": None, "reason": None}
    assert result["changed"] == {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None}
    assert result["refused"]["outcome"] == "refused"
    assert result["refused"]["code"] == vocab.LIFECYCLE_REFUSED
    assert result["refused"]["reason"] == "état error au lieu de active"
    assert result["slept"]["outcome"] == "applied" and result["slept"]["lifecycle"] == "sleep"
    assert result["sleptTwice"]["outcome"] == "duplicate"


def test_the_channel_never_touches_the_switch_the_settings_or_the_tool(tmp_path):
    """Quatre portes de la surface restent hors de la table, et c'est une
    décision. `enable`/`disable` appartiennent à l'utilisateur. `tool` et
    `settings` mentent aujourd'hui : la QA de la Slice 07 a mesuré que
    `tool('scissors')` normalise vers `pointer`, enregistre et **rend un
    succès**, si bien que le refus `barehands_tool_unknown` du serveur est
    inatteignable par la page. Router une commande d'outil par là ferait dire à
    JARVIS que c'est fait pendant que la main change d'outil pour un autre."""

    result = run_node(tmp_path, BROWSER + NETWORK + """
      out({methods:Object.keys(CH.ENTRY_POINTS).map(k=>CH.ENTRY_POINTS[k].method),
        source:require('fs').readFileSync(COMMANDS_PATH,'utf8')});
    """, "doors")
    methods = set(result["methods"])
    assert methods == {"activate", "sleep", "calibrate", "tutorial", "exitOverlay"}
    assert methods.isdisjoint({"enable", "disable", "settings", "tool", "targetPreview", "targetAssistance"})
    # Et le module n'appelle aucune de ces portes par un autre chemin.
    for door in ("surface.tool", "surface.enable", "surface.disable", "surface.settings"):
        assert door not in result["source"]


def test_nothing_runs_until_the_switch_is_true_and_the_tab_is_visible(tmp_path):
    """Éteint, aucune requête ne part — c'est ce qui rend le canal *inerte*
    quand Bare Hands est éteint, et pas seulement silencieux."""

    result = run_node(tmp_path, BROWSER + NETWORK + SETTLE + """
      await openTab();
      const idle=network.polls;
      CHANNEL.gate({enabled:false});
      await settleLong();
      const afterOff=network.polls;
      CHANNEL.gate({enabled:true});
      await settleLong();
      const afterOn=network.polls;
      const runningOn=CHANNEL.state().running;
      /* Onglet caché : la boucle sort. Une fenêtre en arrière-plan ne doit pas
         prendre une commande qu'elle ne peut pas honorer (rAF gelé, caméra
         suspendue) — le serveur dira « aucune page visible », ce qui est vrai. */
      document.visibilityState='hidden';
      for(const fn of (docListeners.visibilitychange||[]))fn({});
      await settleLong();
      /* Le long-poll garé rend la main : la boucle doit **sortir** au lieu de
         repartir. C'est la seule façon de le voir — tant qu'elle est garée,
         une boucle arrêtée et une boucle vivante se ressemblent. */
      resumeParked();
      await settleLong();
      const hidden=CHANNEL.state();
      const pollsHidden=network.polls;
      CHANNEL.statusLost();
      out({idle,afterOff,afterOn,runningOn,hidden,pollsHidden,
        state:CHANNEL.state(),stats:CHANNEL.stats()});
    """, "gate")
    assert result["idle"] == 0 and result["afterOff"] == 0, "éteint, rien ne part"
    assert result["afterOn"] == 1 and result["runningOn"] is True
    assert result["hidden"]["visible"] is False
    assert result["hidden"]["running"] is False, "onglet caché : la boucle sort, elle ne se gare pas"
    assert result["pollsHidden"] == 1, "et elle ne rouvre pas de long-poll"
    # Statut perdu : on ne suppose pas que l'interrupteur est resté vrai.
    assert result["state"]["enabled"] is False
    assert result["stats"]["received"] == 0


def test_the_module_refuses_to_install_without_the_surface_it_drives(tmp_path):
    """Constat F3, rendu exécutable : l'ordre d'insertion doit casser **à
    l'insertion**, pas trois clics plus tard. Sans cette levée, un module servi
    trop tôt s'installerait, ne trouverait jamais de surface, et Bare Hands
    serait allumé avec un canal muet — une panne que rien à l'écran n'annonce."""

    result = run_node(tmp_path, """
      global.window={};global.document={addEventListener(){},visibilityState:'visible'};
      let refused=null;
      try{require(COMMANDS_PATH)}catch(error){refused=String(error&&error.message||error)}
      /* Le bloc pur, lui, s'est chargé : c'est ce qui permet à node de le
         tester sans page, et à la levée de ne viser que l'installation. */
      out({refused,pureLoaded:typeof window.JarvisBarehandsCommands==='object',
        channelInstalled:typeof window.JarvisBarehandsCommandChannel!=='undefined'});
    """, "install")
    assert "control_center_barehands.js doit être inséré avant ce module" in (result["refused"] or "")
    assert result["pureLoaded"] is True
    assert result["channelInstalled"] is False


def test_closing_and_reopening_the_gate_while_parked_leaves_a_live_channel(tmp_path):
    """La panne que la campagne de mutations a fait apparaître, et qui était
    un vrai défaut, pas un trou de test.

    Fermer puis rouvrir l'interrupteur pendant que la boucle est garée sur un
    long-poll : au retour, la boucle doit **continuer**. Une version qui
    comptait les générations sortait ici alors que la porte était rouverte, et
    `running` valant encore vrai, personne ne la relançait. Bare Hands allumé,
    canal mort, et le cerveau n'aurait eu pour seul indice que
    `barehands_no_visible_page` devant une fenêtre bien visible."""

    result = run_node(tmp_path, BROWSER + NETWORK + SETTLE + """
      await openTab();
      /* Le premier sondage se gare : plus rien dans la file. */
      CHANNEL.gate({enabled:true});
      await settleLong();
      const parkedOnce=[network.polls,CHANNEL.state().running];
      CHANNEL.gate({enabled:false});
      CHANNEL.gate({enabled:true});
      await settleLong();
      /* Toujours **une** boucle : rouvrir pendant qu'une boucle est garée ne
         doit pas en démarrer une seconde, sinon deux long-polls se disputent
         la même commande et la page l'appliquerait deux fois. */
      const pollsAfterReopen=network.polls;
      /* La commande arrive maintenant : c'est elle qui dit si le canal vit. */
      queue('deactivate');
      resumeParked();
      await settleLong();await settle();await settleLong();
      out({parkedOnce,pollsAfterReopen,state:CHANNEL.state(),receipts:network.receipts,polls:network.polls});
    """, "reopen")
    assert result["parkedOnce"] == [1, True]
    assert result["pollsAfterReopen"] == 1, "rouvrir la porte ne démarre pas une seconde boucle"
    assert result["state"]["enabled"] is True and result["state"]["running"] is True
    # Le canal a bien repris et répondu : une seule boucle, toujours vivante.
    assert len(result["receipts"]) == 1
    assert result["receipts"][0]["code"] == vocab.LIFECYCLE_REFUSED  # pas de caméra sous node
    assert result["state"]["last"] == "deactivate:refused"


def test_the_page_table_and_the_python_vocabulary_name_the_same_commands(tmp_path):
    """Deux moitiés d'un même vocabulaire. Une commande ajoutée d'un seul côté
    serait un outil qui part et une page qui ne sait pas répondre — et le
    cerveau attendrait l'échéance pour apprendre une faute de frappe."""

    result = run_node(tmp_path, BROWSER + NETWORK + """
      out({commands:CH.COMMANDS,codes:CH.PAGE_CODES,route:CH.ROUTE,wait:CH.POLL_WAIT_S});
    """, "parity")
    assert tuple(result["commands"]) == vocab.COMMANDS
    assert set(result["codes"]) == set(vocab.PAGE_CODES)
    assert result["route"] == "/api/barehands/commands"
    assert 0 < result["wait"] <= vocab.MAX_POLL_WAIT_S


def test_a_command_the_page_does_not_know_is_refused_rather_than_ignored(tmp_path):
    """Défense en profondeur : le serveur a déjà fermé le vocabulaire. Mais un
    consommateur qui ne sait pas répondre doit le **dire** — se taire ferait
    attendre au cerveau son échéance pour apprendre une divergence de version,
    et il lirait « aucune page visible », ce qui serait faux."""

    result = run_node(tmp_path, BROWSER + NETWORK + SETTLE + """
      await openTab();
      queue('danser');
      CHANNEL.gate({enabled:true});
      await settleLong();await settle();await settleLong();
      out({receipts:network.receipts,stats:CHANNEL.stats()});
    """, "unknown")
    assert result["receipts"] == [{
        "outcome": "refused", "lifecycle": "off", "code": vocab.COMMAND_UNKNOWN,
        "reason": "la page ne connaît pas la commande danser",
    }]
    assert result["stats"]["refused"] == 1


def test_a_malformed_command_is_dropped_and_counted_not_dispatched(tmp_path):
    """Un identifiant hors forme est un défaut de serveur, pas une commande à
    tenter : on ne poste pas de reçu sur un identifiant qu'on vient de refuser."""

    result = run_node(tmp_path, BROWSER + NETWORK + SETTLE + """
      await openTab();
      network.queue.push({id:'trop-court',name:'activate',remaining_ms:3000});
      CHANNEL.gate({enabled:true});
      await settleLong();await settle();await settleLong();
      out({receipts:network.receipts,stats:CHANNEL.stats(),lifecycle:BAREHANDS.lifecycle()});
    """, "invalid")
    assert result["receipts"] == [] and result["stats"]["invalid"] == 1
    assert result["stats"]["received"] == 0
    assert result["lifecycle"] == "off", "rien n'a été remis à la surface"


def test_a_poll_failure_backs_off_instead_of_hammering_the_server(tmp_path):
    result = run_node(tmp_path, BROWSER + NETWORK + """
      const delays=[0,1,2,3,10].map(n=>CH.backoffDelay(n,()=>0.5));
      out({delays,base:CH.BACKOFF_BASE_MS,max:CH.BACKOFF_MAX_MS,
        valid:[CH.validCommand(null),CH.validCommand({id:'a'.repeat(32),name:'activate',remaining_ms:0}),
               CH.validCommand({id:'a'.repeat(32),name:'activate',remaining_ms:-1})]});
    """, "backoff")
    assert result["delays"][0] == result["base"], "un premier échec attend la base, pas zéro"
    assert result["delays"] == sorted(result["delays"]), "l'attente croît"
    assert result["delays"][-1] == result["max"], "et se plafonne"
    assert result["valid"] == [False, True, False]
