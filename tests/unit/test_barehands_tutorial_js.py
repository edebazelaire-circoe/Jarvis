"""Tutoriel Bare Hands : étapes, coque partagée, points d'entrée de la voix.

Slice 09, architecture §13, décisions 6 et 26. Exécuté par node : les contrats,
le moteur, la coque et le module de tutoriel sont les **vrais** ; seuls le DOM,
l'horloge et le réseau sont des doubles, parce que node n'en a pas.

Ce que ce fichier épingle :

- **le tutoriel n'écrit jamais de paramètre de calibration**, et ce n'est pas
  une promesse : `createTutorial` refuse à la construction toute dépendance
  capable d'écrire, et un parcours **complet** conduit sur la vraie page ne
  touche pas une seule fois la route du profil — assertion en **aller-retour**,
  le profil relu après valant exactement le profil d'avant ;
- **la couture de la décision 32 reste fermée** pendant tout le tutoriel : le
  contrôleur n'a pas d'`onMeasure`, donc aucune mesure de main n'existe ;
- **l'observation est une liste blanche** : une suite de points, une image en
  base64 ou un objet libre n'en ressortent pas, et la garde qui le vérifie
  tourne au chargement du module ;
- **la coque est reprise sans être modifiée** : le tutoriel reçoit exactement
  celle que la calibration reçoit, et les deux parcours ne peuvent pas être
  ouverts en même temps ;
- **deux mécanismes tiennent l'échéance** : la boucle d'images *et* un chien de
  garde, parce qu'une étape que personne ne nourrit doit quand même expirer ;
- **`tutorialSeen` ne peut pas être vrai pour un tutoriel que personne n'a
  traversé** : quitter au milieu n'écrit rien ;
- **`tutorial()` et `exitOverlay()` confirment** au sens du § 12, et le canal
  de la Slice 12 les trouve sans qu'une ligne y change.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_barehands_tools_settings_js import (  # noqa: E402
    CALIBRATION, CAMERA, CONTRACTS, SCENE_INTERACT, SCRIPT, TARGET, TUTORIAL, browser,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACT_DOC = ROOT / "docs" / "barehands-contracts.md"

#: Le double de DOM de la coque est **réutilisé** de la Slice 08, pas recopié :
#: une seconde version dériverait de celle qui tient la coque, et les deux
#: décriraient deux surimpressions différentes sous un seul nom.
from test_barehands_calibration_js import DOM  # noqa: E402


def run_node(tmp_path: Path, source: str, name: str = "tuto") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-tutorial-{name}.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const K=require({json.dumps(str(CALIBRATION))});\n"
        f"const T=require({json.dumps(str(TUTORIAL))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=40, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def run_page(tmp_path: Path, source: str, name: str) -> object:
    """Le **vrai** bloc navigateur du pointeur, avec le double de la Slice 07."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-tutorial-page-{name}.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
        f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};\n"
        f"const TUTORIAL_PATH={json.dumps(str(TUTORIAL))};\n"
        f"const TARGET_PATH={json.dumps(str(TARGET))};\n"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};\n"
        f"const CONTRACTS_PATH={json.dumps(str(CONTRACTS))};\n"
        "const C=require(CONTRACTS_PATH);\n"
        "const G=require(SCENE_INTERACT_PATH);\n"
        "const T=require(TUTORIAL_PATH);\n"
        "const out=v=>process.stdout.write(JSON.stringify(v),()=>process.exit(0));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


#: Des minuteries qu'on peut **déclencher à la main** : le double de la Slice 07
#: rend `setInterval` inerte, ce qui rendrait le chien de garde du tutoriel
#: invisible. Ici il est enregistré, donc observable et exécutable — un double
#: qui ne peut pas faire tourner la vraie horloge ne peut rien prouver d'elle.
TIMERS = r"""
const timers=[];
global.setInterval=(fn,ms)=>{timers.push({fn,ms});return timers.length};
global.clearInterval=id=>{if(id>=1&&timers[id-1])timers[id-1]=null};
global.window.setInterval=global.setInterval;
global.window.clearInterval=global.clearInterval;
const ticks=()=>timers.filter(Boolean).length;
const tick=n=>{for(let i=0;i<(n||1);i+=1)for(const t of timers.slice())if(t)t.fn()};
"""

#: La scène du tutoriel, côté module : une observation neutre qu'on enrichit.
OBSERVE = r"""
const shellOf=()=>K.createFlowOverlay({document,now});
const base=extra=>Object.assign({now:clock,lifecycle:'active',tool:'pointer',
  targetPreview:true,targets:0,hands:1,interactions:[]},extra||{});
const act=(type,extra)=>Object.assign({type,channel:'primary',objectId:null,axes:[]},extra||{});
/* Nourrir **jusqu'à ce que l'étape bouge**, jamais un nombre d'images fixé :
   c'est le parcours qu'on mesure, pas le pas de temps du pilote (leçon de la
   Slice 08). L'horloge avance de son côté, comme dans la vraie page. */
const feedUntil=(flow,make,limit)=>{
  const from=flow.stepId();
  for(let i=0;i<(limit||60);i+=1){
    clock+=100;
    flow.feed(make(i));
    if(flow.stepId()!==from)return true;
  }
  return false;
};
"""


# ------------------------------------------------------------------ le vocabulaire


def test_the_ten_steps_teach_the_whole_v1_vocabulary_and_the_document_says_the_same(tmp_path):
    """**Le contrat de la Slice, étape par étape.** Les dix sujets qu'elle
    exige — réveil, aperçu de cible, clic, clic droit, contenu, étoile, cadre,
    redimensionnement à deux mains, outils, sortie — ont chacun leur étape, dans
    cet ordre, et chacune porte une consigne **et** un moyen de constater.

    La table du contrat (`docs/barehands-contracts.md` § 13) est comparée aux
    identifiants réels : une étape ajoutée d'un côté seulement tombe ici. C'est
    le même épinglage que la bande de réveil du § « ce qui est implémenté » —
    une constante nouvelle sans test de parité est une constante qui dérive."""

    result = run_node(tmp_path, """
      out({ids:T.STEPS.map(s=>s.id),
        titled:T.STEPS.every(s=>s.title&&s.instruction&&s.hint),
        verified:T.STEPS.map(s=>typeof s.verify==='function'),
        manual:T.STEPS.filter(s=>s.manual).map(s=>s.id),
        statuses:T.STATUSES,reasons:T.REASONS,
        presented:T.PRESENTED,shell:K.FLOW_STATUS});
    """, "vocab")

    assert result["ids"] == ["wake", "target", "click_primary", "click_secondary",
                            "content", "object_drag", "frame_move", "frame_resize",
                            "tools", "exit"]
    assert result["titled"], "une étape sans consigne n'enseigne rien"
    assert all(result["verified"]), "une étape sans moyen de constater ne se vérifie pas"
    # Les deux seules étapes qui **expliquent** au lieu de mesurer le disent.
    assert result["manual"] == ["tools", "exit"]
    assert result["statuses"] == ["done", "skipped", "missed"]

    # **Parité avec le document** : la table du § 13 nomme les mêmes étapes.
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    section = text[text.index("## 13. Tutoriel"):]
    section = section[:section.index("\n## ") if "\n## " in section else len(section)]
    # La **première** table du § 13, et elle seule : celle des étapes. Prendre
    # toutes les lignes en `| \`` ramasserait aussi la table des points
    # d'entrée plus bas, et le test dirait n'importe quoi.
    documented: list[str] = []
    for line in section.splitlines():
        if line.startswith("| `"):
            documented.append(line.split("|")[1].strip().strip("`"))
        elif documented:
            break
    assert documented == result["ids"], "le contrat et le module ne nomment pas les mêmes étapes"

    # Et les trois mots que la coque sait dessiner sont ceux vers lesquels le
    # tutoriel traduit les siens — jamais un quatrième.
    assert sorted(result["presented"].values()) == sorted(result["shell"])
    assert set(result["presented"]) == set(result["statuses"])


def test_the_shell_refuses_a_status_it_cannot_draw_instead_of_emitting_a_dead_class(tmp_path):
    """`jf-${status}` fabriquait une classe que la feuille ne définit pas : la
    ligne sortait **sans couleur**, sans erreur et sans avertissement, et
    « réussi » se lisait comme « passé ». Le repli muet sur `skipped` était
    pire : il mentait.

    C'est la porte d'entrée d'un deuxième parcours, donc elle se refuse. Les
    trois mots que la feuille définit sont publiés (`FLOW_STATUS`), et le
    tutoriel y traduit les siens au lieu d'emprunter ceux du profil."""

    result = run_node(tmp_path, DOM + """
      const shell=K.createFlowOverlay({document,now});
      shell.open({title:'t',exit(){}});
      const good=shell.report([{label:'a',status:'ok',detail:'fait'},
        {label:'b',status:'failed',detail:'raté'},{label:'c',status:'skipped',detail:'passée'}]);
      const classes=find(flowRoot(),'jf-ok').length+find(flowRoot(),'jf-failed').length
        +find(flowRoot(),'jf-skipped').length;
      const bad=refused(()=>shell.report([{label:'x',status:'done',detail:'?'}]));
      const empty=refused(()=>shell.report([{label:'x',detail:'?'}]));
      /* La feuille définit exactement ces trois classes, et pas une de plus :
         c'est ce qui rend le refus nécessaire plutôt que décoratif. */
      const styled=K.FLOW_STATUS.filter(s=>K.STYLE.indexOf('.jf-'+s)>=0);
      out({good,classes,bad,empty,styled,vocabulary:K.FLOW_STATUS});
    """, "status")

    assert result["good"] == 3 and result["classes"] == 3
    # `done` est un mot du tutoriel, pas de la coque : il se refuse ici.
    assert result["bad"] == "RangeError"
    # Et l'absence de statut ne retombe plus en silence sur « passé ».
    assert result["empty"] == "RangeError"
    assert result["styled"] == result["vocabulary"] == ["ok", "failed", "skipped"]


# ------------------------------------------------ ce que le tutoriel ne peut pas faire


def test_a_tutorial_cannot_be_given_anything_that_writes_a_calibration_profile(tmp_path):
    """**La garantie centrale de la Slice, et elle est structurelle.**

    « Le tutoriel ne doit jamais écrire de paramètre de calibration » est une
    phrase ; ce qui la tient est que `createTutorial` **refuse à la
    construction** toute dépendance capable d'écrire. Une Slice ultérieure qui
    brancherait un écrivain de profil ici casse à la construction, pas trois
    écrans plus loin — et la garantie survit à celui qui l'a écrite.

    Même espèce qu'`assertDerivedOnly` (§ 10) : une promesse sur ce que du code
    ne fera pas est plus faible qu'une couture qui ne peut pas le transporter."""

    result = run_node(tmp_path, DOM + OBSERVE + """
      const refusals={};
      for(const name of ['save','profile','saveProfile','saveSettings','measure','onMeasure','calibration'])
        refusals[name]=refused(()=>T.createTutorial({overlay:shellOf(),[name]:()=>{}}));
      // La construction ordinaire, elle, passe.
      const ok=!!T.createTutorial({overlay:shellOf()});
      // Et la coque reste obligatoire : un parcours sans écran est un piège.
      const noShell=refused(()=>T.createTutorial({}));
      out({refusals,ok,noShell,
        source:require('fs').readFileSync(process.env.TUTORIAL_SOURCE,'utf8')});
    """.replace("process.env.TUTORIAL_SOURCE", json.dumps(str(TUTORIAL))), "forbidden")

    assert set(result["refusals"]) == {"save", "profile", "saveProfile", "saveSettings",
                                       "measure", "onMeasure", "calibration"}
    for name, code in result["refusals"].items():
        assert code == "barehands_tutorial_cannot_write_profile", name
    assert result["ok"] and result["noShell"] == "RangeError"
    # Et le module ne connaît aucun chemin vers le profil : ni la route, ni les
    # fabriques du contrat qui y mènent.
    for forbidden in ("toProfilePayload", "normalizeProfile", "PROFILE_SCHEMA_VERSION",
                      "/api/barehands", "profileValue", "STAGE_STATUS", "HAND_PROFILE"):
        assert forbidden not in result["source"], forbidden


def test_only_derived_facts_cross_into_a_step_and_the_guard_runs_at_module_load(tmp_path):
    """**Décision 32, deuxième fois et par un autre chemin.** La calibration
    reçoit des scalaires ; le tutoriel reçoit encore moins — des booléens, des
    comptes et des noms d'un vocabulaire fermé.

    La garde est **pilotée par le schéma** et non par un exemple : une
    observation remplie à la main ne dirait rien d'une clé que personne n'aurait
    pensé à remplir. Mesuré ici en présentant à *chaque* clé une suite de
    points, une image en base64 et un objet libre."""

    result = run_node(tmp_path, """
      const landmarks=[{x:.1,y:.2,z:.3},{x:.4,y:.5,z:.6}];
      const image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
      // L'identifiant d'objet devient un **booléen** : le parcours n'a pas
      // besoin de savoir lequel, seulement qu'il y en avait un.
      const kept=T.readObservation({now:5,lifecycle:'active',tool:'pointer',
        targets:2,hands:2,targetPreview:true,
        interactions:[{type:'drag_move',channel:'primary',objectId:'star-42',axes:['x']}]});
      // Ce qu'on essaie de faire passer, clé par clé.
      const leaked={};
      for(const key of ['now','lifecycle','tool','targets','hands','targetPreview','interactions'])
        for(const [name,poison] of [['landmarks',landmarks],['image',image],['frame',{pixels:[1,2]}]]){
          const read=T.readObservation({[key]:poison});
          const value=read[key];
          const bad=value!==null&&value!==undefined&&(typeof value==='object'
            ?(Array.isArray(value)?value.some(v=>typeof v==='object'&&Object.keys(v).some(k=>!['type','channel','onObject','axes'].includes(k))):true)
            :typeof value==='string'&&value.length>32);
          if(bad)leaked[key+'/'+name]=value;
        }
      // Une clé que le schéma ne nomme pas n'atteint jamais une étape.
      const unknown=T.readObservation({landmarks,video:image,secret:'x'});
      out({kept,leaked,unknownKeys:Object.keys(unknown),
        guard:T.assertTeachingOnly()});
    """, "whitelist")

    assert result["kept"] == {"now": 5, "lifecycle": "active", "tool": "pointer",
                              "targetPreview": True, "targets": 2, "hands": 2,
                              "interactions": [{"type": "drag_move", "channel": "primary",
                                                "onObject": True, "axes": 1}]}
    assert result["leaked"] == {}, "une observation ne transporte que des faits dérivés"
    assert result["unknownKeys"] == ["now", "lifecycle", "tool", "targetPreview",
                                     "targets", "hands", "interactions"]
    assert result["guard"] is True


def test_a_leaky_observation_key_makes_the_module_refuse_to_load(tmp_path):
    """La garde est posée **au chargement du module**, comme `assertDerivedOnly`
    (§ 10), et pas seulement disponible : une liste blanche qu'on n'exerce
    jamais est un souhait, et un appel explicite depuis un test prouve la
    fonction, jamais son installation.

    Mesuré comme la Slice 08 l'a mesuré pour le profil : on ajoute au schéma une
    clé qui recopie son entrée, et on regarde si `require()` **refuse**. Sans
    l'appel au chargement, le module se charge et la décision 32 tombe sans
    qu'une ligne change ailleurs."""

    source = TUTORIAL.read_text(encoding="utf-8")
    # Une Slice future qui ajouterait une clé « pratique » recopiée telle
    # quelle : exactement ce que la garde existe pour attraper.
    leaky = source.replace(
        "      hands:count(source.hands),",
        "      hands:count(source.hands),\n      sampleFrames:source.sampleFrames,", 1)
    assert leaky != source, "le point d'insertion du schéma a bougé"
    leaky = leaky.replace(
        "targets:0,hands:0,interactions:[]});",
        "targets:0,hands:0,sampleFrames:null,interactions:[]});", 1)
    copy = tmp_path / "control_center_barehands_tutorial_leaky.js"
    copy.write_text(leaky, encoding="utf-8")

    result = run_node(tmp_path, """
      const refusedLoad=refused(()=>require(%s));
      // Et le vrai module, lui, se charge : la garde refuse la fuite, pas tout.
      out({refusedLoad,real:typeof T.createTutorial==='function',
        message:(()=>{try{require(%s);return ''}catch(e){return String(e&&e.message||e)}})()});
    """ % (json.dumps(str(copy)), json.dumps(str(copy))), "leaky")

    assert result["refusedLoad"] == "RangeError",         "une clé qui recopie son entrée doit faire refuser le chargement"
    assert "sampleFrames" in result["message"], "le refus nomme la clé fautive"
    assert result["real"] is True


def test_the_two_settings_pairs_that_would_miss_every_step_are_refused_at_construction(tmp_path):
    """Douzième et treizième paires dangereuses de la tâche, et de la même
    espèce que les onze précédentes : elles échouent **en silence**, ce qui se
    lit « l'utilisateur s'y prend mal ».

    - `readMs >= stepTimeoutMs` : l'étape expire avant d'avoir commencé à
      écouter, **toutes** les étapes sont manquées, et le récapitulatif accuse
      quelqu'un qui a tout fait correctement ;
    - `watchdogMs >= stepTimeoutMs` : une étape que personne ne nourrit n'est
      déclarée manquée qu'au tour suivant, donc l'écran affiche « 0 s
      restantes » pendant toute une échéance de plus — et « ça attend »
      redevient indiscernable de « c'est bloqué »."""

    result = run_node(tmp_path, """
      const bad=spec=>{try{T.options(spec);return null}catch(e){return e.name}};
      out({
        defaults:T.DEFAULTS,
        readAtDeadline:bad({readMs:T.DEFAULTS.stepTimeoutMs}),
        readOver:bad({readMs:T.DEFAULTS.stepTimeoutMs+1}),
        readNegative:bad({readMs:-1}),
        watchdogAtDeadline:bad({watchdogMs:T.DEFAULTS.stepTimeoutMs}),
        watchdogOver:bad({watchdogMs:T.DEFAULTS.stepTimeoutMs*2}),
        watchdogZero:bad({watchdogMs:0}),
        sane:bad({}),
        // Les valeurs d'usine respectent les deux bornes qu'elles posent.
        ordered:T.DEFAULTS.readMs<T.DEFAULTS.stepTimeoutMs
          &&T.DEFAULTS.watchdogMs<T.DEFAULTS.stepTimeoutMs,
      });
    """, "pairs")

    assert result["sane"] is None and result["ordered"] is True
    for key in ("readAtDeadline", "readOver", "readNegative",
                "watchdogAtDeadline", "watchdogOver", "watchdogZero"):
        assert result[key] == "RangeError", key


# ------------------------------------------------------------------ le parcours


def test_a_full_run_teaches_the_vocabulary_and_each_step_is_verified_by_a_real_event(tmp_path):
    """Chaque étape est franchie par **ce qu'elle enseigne**, pas par un
    drapeau : le cycle de vie pour le réveil, une cible résolue pour l'aperçu,
    un `click` pour le clic, un `context` pour le clic droit, un `scroll` pour
    le contenu, un glissement **portant un objet** pour l'étoile, un `move`
    pour le cadre, un `resize` pour les deux mains.

    Les deux dernières expliquent : celle des outils sait quand même
    reconnaître un vrai changement d'outil, ce qui vaut mieux qu'un
    acquiescement."""

    result = run_node(tmp_path, DOM + OBSERVE + """
      const seen=[];
      const flow=T.createTutorial({overlay:shellOf(),now,onDone:r=>seen.push(r)});
      const started=flow.start();
      const order=[];
      const step=()=>flow.stepId();
      order.push(step());
      // 1. Le réveil : rien tant que le cycle de vie n'est pas `active`.
      const asleep=feedUntil(flow,()=>base({lifecycle:'sleep'}),12);
      order.push([step(),asleep]);
      feedUntil(flow,()=>base());
      order.push(step());
      // 2. L'aperçu : une cible résolue.
      feedUntil(flow,()=>base({targets:1}));
      order.push(step());
      // 3-4. Clic, puis clic droit.
      feedUntil(flow,()=>base({interactions:[act('click')]}));
      order.push(step());
      feedUntil(flow,()=>base({interactions:[act('context',{channel:'secondary'})]}));
      order.push(step());
      // 5. Contenu : un défilement, donc sans objet.
      feedUntil(flow,()=>base({interactions:[act('scroll',{dx:4,dy:0})]}));
      order.push(step());
      // 6. L'étoile : le même glissement, mais **portant un objet**.
      const noObject=feedUntil(flow,()=>base({interactions:[act('drag_move')]}),12);
      order.push([step(),noObject]);
      feedUntil(flow,()=>base({interactions:[act('drag_move',{objectId:'star-7'})]}));
      order.push(step());
      // 7-8. Le cadre, puis les deux mains.
      feedUntil(flow,()=>base({interactions:[act('move',{objectId:'win-1',axes:['x','y']})]}));
      order.push(step());
      feedUntil(flow,()=>base({hands:2,interactions:[act('resize',{objectId:'win-1',axes:['x']})]}));
      order.push(step());
      /* 9. Les outils : le vrai changement d'outil, et il doit être un
         **changement** — l'outil vu pendant qu'on lit la consigne est celui
         d'avant, sinon « il a changé » n'a pas de référent. */
      feedUntil(flow,i=>base({tool:i<14?'pointer':'pan'}),40);
      order.push(step());
      // 10. La sortie : elle explique, donc elle se solde sur son bouton.
      const before=allButtons(flowRoot()).map(b=>b.getAttribute('data-flow-action')).filter(Boolean);
      press(flowRoot(),'understood');
      out({started,order,before,done:seen,
        open:!!flowRoot(),running:flow.isRunning(),
        report:flow.report()});
    """, "run")

    assert result["started"]["ok"] is True
    assert result["started"]["flow"] == "tutorial"
    assert result["started"]["steps"] == 10
    assert result["order"][0] == "wake"
    # Endormi, l'étape du réveil ne bouge pas : c'est bien le cycle de vie
    # qu'elle lit, et pas le simple fait qu'on la nourrisse.
    assert result["order"][1] == ["wake", False]
    assert result["order"][2:7] == ["target", "click_primary", "click_secondary",
                                    "content", "object_drag"]
    # Un glissement **sans** objet ne franchit pas l'étape de l'étoile : le
    # booléen que l'observation porte est bien ce qui les distingue.
    assert result["order"][7] == ["object_drag", False]
    assert result["order"][8:] == ["frame_move", "frame_resize", "tools", "exit"]
    # L'étape qui explique porte un bouton nommé, et deux sorties à côté.
    assert result["before"] == ["understood", "skip", "exit"]
    # Le récapitulatif est atteint : dix étapes faites, aucune manquée.
    assert len(result["done"]) == 1
    assert result["done"][0]["done"] == 10 and result["done"][0]["total"] == 10
    assert {row["status"] for row in result["done"][0]["steps"]} == {"ok"}


def test_a_step_nobody_feeds_still_expires_because_a_clock_watches_it_too(tmp_path):
    """**Deux mécanismes, et c'est la RÈGLE ZÉRO.** La boucle d'images ne tourne
    qu'en ACTIVE et seulement quand une main est vue : une étape quittée par
    l'utilisateur ne serait jamais déclarée manquée, et le compteur resterait
    figé sur « 0 s restantes » — « ça attend » et « c'est bloqué » à nouveau
    identiques à l'écran.

    Ici la main disparaît. La coque dit ce qui manque, puis l'échéance tombe, et
    le motif est **le plus utile** — « aucune main vue » plutôt que « temps
    écoulé », qui est vrai de toutes ces pannes et n'aide personne. Le parcours
    continue : décision 31, appliquée au tutoriel."""

    result = run_node(tmp_path, DOM + OBSERVE + """
      const flow=T.createTutorial({overlay:shellOf(),now,
        options:{stepTimeoutMs:4000,readMs:200,watchdogMs:100}});
      flow.start();
      feedUntil(flow,()=>base());
      const at=flow.stepId();
      // Plus personne devant la caméra : on continue de nourrir, sans main.
      clock+=300;flow.feed(base({hands:0}));
      const saidNoHand=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const stillThere=flow.stepId();
      // L'échéance passe. C'est la seule chose qui bouge.
      clock+=5000;flow.feed(base({hands:0}));
      const after=flow.stepId();
      const carried=text(flowRoot(),C.DOM.flowNoteClass)[0];
      // Et une étape passée en veille est nommée par sa vraie cause.
      const flow2=T.createTutorial({overlay:K.createFlowOverlay({document,now}),now,
        options:{stepTimeoutMs:4000,readMs:200,watchdogMs:100}});
      flow2.start();feedUntil(flow2,()=>base());
      clock+=300;flow2.feed(base());
      clock+=5000;flow2.feed(base({lifecycle:'sleep'}));
      out({at,saidNoHand,stillThere,after,carried,
        report:flow.report(),asleep:flow2.report()});
    """, "expire")

    assert result["at"] == "target" and result["stillThere"] == "target"
    assert "Aucune main" in result["saidNoHand"]
    # L'étape est manquée, et le parcours a continué.
    assert result["after"] == "click_primary"
    assert result["report"]["target"] == {"status": "missed", "reason": "no_hand"}
    # **Le motif survit au changement d'étape** (leçon de la Slice 08) : la
    # phrase est portée dans l'étape suivante, pas effacée par `overlay.step()`.
    assert "aucune main vue" in result["carried"]
    assert "on continue" in result["carried"].lower()
    # Et retourner en veille a sa propre cause, jamais « temps écoulé ».
    assert result["asleep"]["target"] == {"status": "missed", "reason": "not_active"}


def test_quitting_in_the_middle_reaches_no_recap_so_nothing_says_the_tutorial_was_seen(tmp_path):
    """`tutorialSeen` ne peut pas devenir vrai pour un tutoriel que personne n'a
    traversé — la forme exacte que `calibrated: true` a prise ailleurs sur cette
    tâche, où une métrique de qualité comptait pour une mesure.

    Ici le seul écrivain est `onDone`, et `onDone` n'est appelé qu'**à
    l'arrivée sur le récapitulatif**, c'est-à-dire après avoir traversé les dix
    étapes. Trois sorties existent à toutes les étapes ; aucune n'y mène."""

    result = run_node(tmp_path, DOM + OBSERVE + """
      const ways=[];
      for(const how of ['button','escape','api']){
        const done=[],left=[];
        const shell=K.createFlowOverlay({document,now});
        const flow=T.createTutorial({overlay:shell,now,
          onDone:r=>done.push(r),onExit:why=>left.push(why)});
        flow.start();
        feedUntil(flow,()=>base());
        feedUntil(flow,()=>base({targets:1}));
        const at=flow.stepId();
        if(how==='button')press(flowRoot(),'exit');
        else if(how==='escape')document.fire('keydown',{key:'Escape'});
        else flow.exit('voix');
        ways.push({how,at,done:done.length,left,
          running:flow.isRunning(),open:!!flowRoot(),
          /* La page derrière est rendue : le balayage `inert` est défait, et
             la surimpression a quitté l'arbre. */
          inerted:body.children.filter(n=>n.inert).length});
      }
      out({ways});
    """, "quit")

    for way in result["ways"]:
        assert way["at"] == "click_primary", way["how"]
        # Aucun récapitulatif : rien n'a pu écrire « tutoriel vu ».
        assert way["done"] == 0, way["how"]
        assert way["running"] is False and way["open"] is False
        assert way["inerted"] == 0, "la page reste désarmée après une sortie"
    assert [w["left"] for w in result["ways"]] == [["bouton"], ["échap"], ["voix"]]


def test_the_way_out_is_permanent_and_does_not_depend_on_what_a_flow_draws(tmp_path):
    """**Quatrième point de la RÈGLE ZÉRO : comment en sortir.** L'exigence de
    la Slice est « une sortie X / Échap / voix, toujours ».

    Échap et la voix étaient déjà tenus par la coque et par `exitOverlay()`.
    Le troisième ne l'était pas vraiment : les boutons d'une étape sont
    **redessinés à chaque étape**, donc « on peut toujours quitter » dépendait
    de ce que le parcours pensait à dessiner — et le rapport de la calibration,
    par exemple, n'offre que « Annuler ». La coque pose donc une sortie qui ne
    bouge pas, hors de `actions` (que `buttons()` vide), et qu'aucun parcours
    ne peut effacer sans le savoir.

    Vérifié sur les **deux** parcours, à **chaque** étape, récapitulatif
    compris."""

    result = run_node(tmp_path, DOM + OBSERVE + """
      const closes=root=>allButtons(root).filter(n=>n.getAttribute('data-flow-close')!==null);
      const seen=[];
      const left=[];
      const flow=T.createTutorial({overlay:shellOf(),now,onExit:why=>left.push(why)});
      flow.start();
      // Toutes les étapes, en les passant, puis le récapitulatif.
      for(let i=0;i<14;i+=1){
        const root=flowRoot();
        if(!root)break;
        const exit=closes(root)[0];
        seen.push([flow.stepId(),closes(root).length,
          exit?exit.getAttribute('aria-label'):null,exit?exit.textContent:null]);
        const actions=allButtons(root).map(n=>n.getAttribute('data-flow-action')).filter(Boolean);
        if(actions.indexOf('understood')>=0)press(root,'understood');
        else if(actions.indexOf('skip')>=0)press(root,'skip');
        else break;
      }
      const atReport={step:flow.stepId(),
        /* Le récapitulatif ne dessine **ni** « Quitter » **ni** « Passer » : si
           la sortie dépendait du parcours, il n'y en aurait aucune ici. */
        actions:allButtons(flowRoot()).map(n=>n.getAttribute('data-flow-action')).filter(Boolean),
        closes:closes(flowRoot()).length};
      // Et elle **sort** : pressée, la coque se referme et la page est rendue.
      closes(flowRoot())[0].fire('click');
      const after={open:!!flowRoot(),running:flow.isRunning(),left:left.slice(),
        inerted:body.children.filter(n=>n.inert).length};

      /* La même garantie pour la calibration, qui n'a pas changé d'une ligne :
         c'est la coque qui la porte, donc les deux parcours en héritent. */
      const cal=K.createCalibration({overlay:K.createFlowOverlay({document,now}),now,
        save:async()=>{},engineDefaults:{wakeGapMin:.46,wakeGapMax:.85,wakeIndexMin:1.35,
          wakeSoft:.2,wakeScore:.5,releaseRatio:.42}});
      cal.start();
      const calibration=[[cal.stepId(),closes(flowRoot()).length]];
      while(cal.isRunning()&&allButtons(flowRoot())
        .some(n=>n.getAttribute('data-flow-action')==='skip'))press(flowRoot(),'skip');
      calibration.push(['rapport',closes(flowRoot()).length,
        allButtons(flowRoot()).map(n=>n.getAttribute('data-flow-action')).filter(Boolean)]);
      out({seen,atReport,after,calibration});
    """, "exit")

    # Une sortie, une seule, à **chaque** étape — jamais zéro, jamais deux —
    # et une de plus pour le récapitulatif, qui est justement l'écran où aucun
    # parcours ne dessine « Quitter ».
    assert len(result["seen"]) == 11
    assert [row[0] for row in result["seen"]][:10] == ["wake", "target", "click_primary",
        "click_secondary", "content", "object_drag", "frame_move", "frame_resize",
        "tools", "exit"]
    assert result["seen"][10][0] is None, "la onzième lecture est le récapitulatif"
    for step, count, label, glyph in result["seen"]:
        assert count == 1, step
        assert label == "Quitter ce parcours", step
        assert glyph == "×", step
    # Le récapitulatif ne dessine aucune des deux sorties d'étape, et la
    # sortie permanente y est quand même.
    assert result["atReport"]["step"] is None
    assert result["atReport"]["actions"] == ["close", "again"]
    assert result["atReport"]["closes"] == 1
    # Pressée, elle sort vraiment : la coque part, la page est rendue.
    assert result["after"] == {"open": False, "running": False,
                               "left": ["croix"], "inerted": 0}
    # Et la calibration en hérite sans avoir changé : à sa première étape, et
    # sur son rapport, où elle n'offre que « Appliquer » et « Annuler ».
    assert result["calibration"][0] == ["neutral", 1]
    assert result["calibration"][1][1] == 1
    assert result["calibration"][1][2] == ["apply", "discard"]


def test_the_two_flows_share_one_shell_and_neither_can_cover_the_other(tmp_path):
    """**Décision 26, littéralement.** Le tutoriel reçoit la coque que la
    calibration reçoit — la même instance —, et il ne la modifie pas : ce qu'il
    appelle dessus est exactement ce que le § 11 publie.

    Et deux parcours ne peuvent pas être ouverts ensemble : lancer le tutoriel
    pendant une calibration détruirait une minute de mesures sans un mot, et la
    voix est justement l'appelant qui peut le demander sans voir l'écran."""

    result = run_node(tmp_path, DOM + OBSERVE + """
      const countRoots=()=>body.children.filter(n=>n.id===C.DOM.flowRootId).length;
      const shell=shellOf();
      const calib=K.createCalibration({overlay:shell,now,save:async()=>{},
        engineDefaults:B_DEFAULTS});
      const tuto=T.createTutorial({overlay:shell,now});
      // Une seule coque : celle du tutoriel est celle de la calibration.
      calib.start();
      const duringCalibration={roots:countRoots(),calib:calib.isRunning(),tuto:tuto.isRunning()};
      calib.exit('fin');
      tuto.start();
      const duringTutorial={roots:countRoots(),calib:calib.isRunning(),tuto:tuto.isRunning()};
      tuto.exit('fin');
      out({duringCalibration,duringTutorial,after:countRoots(),
        /* Ce que le tutoriel appelle sur la coque, lu dans sa source : rien
           qui ne soit à l'API publiée du § 11. */
        used:[...new Set((require('fs').readFileSync(TUTORIAL_SRC,'utf8')
          .match(/overlay\\.([a-zA-Z]+)/g)||[]).map(s=>s.slice(8)))].sort()});
    """.replace("B_DEFAULTS", "{wakeGapMin:.46,wakeGapMax:.85,wakeIndexMin:1.35,wakeSoft:.2,wakeScore:.5,releaseRatio:.42}")
       .replace("TUTORIAL_SRC", json.dumps(str(TUTORIAL)))
       .replace("const shellOf=", "const countRoots=()=>body.children.filter(n=>n.id===C.DOM.flowRootId).length;\nconst shellOf="),
       "shell")

    # Une seule racine dans l'arbre, quel que soit le parcours ouvert.
    assert result["duringCalibration"] == {"roots": 1, "calib": True, "tuto": False}
    assert result["duringTutorial"] == {"roots": 1, "calib": False, "tuto": True}
    assert result["after"] == 0
    # Le tutoriel n'utilise que l'API publiée de la coque (§ 11) : rien à
    # modifier de son côté, ce qui est la promesse de la décision 26.
    assert set(result["used"]) <= {"open", "step", "progress", "note", "target",
                                   "buttons", "report", "expired", "elapsedMs",
                                   "close", "isOpen"}
    assert {"open", "step", "note", "buttons", "report", "close"} <= set(result["used"])


# ------------------------------------------------------- la page, la voix, le profil


def test_the_tutorial_run_on_the_real_page_never_touches_the_calibration_profile(tmp_path):
    """**L'assertion en aller-retour** que cette tâche a appris à préférer : le
    profil relu après un tutoriel complet vaut *exactement* celui d'avant, et
    la route du profil n'a pas été appelée une seule fois.

    Deux choses de plus, que seule la vraie page peut montrer :

    - la couture `deps.onMeasure` du contrôleur (décision 32) reste **fermée**
      pendant tout le tutoriel — le tutoriel ne mesure rien, donc il n'ouvre
      rien, et le budget d'images est exactement celui d'avant ;
    - `tutorialSeen` est le **seul** réglage écrit, et il l'est par la porte
      unique des réglages."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();
      await settle();
      const before=JSON.stringify(BAREHANDS.profile());
      const callsBefore=server.calls.length;
      const started=await BAREHANDS.tutorial();
      const state=BAREHANDS.tutorialState();
      /* Traverser les dix étapes en les passant : le récapitulatif est
         atteint, donc `tutorialSeen` s'écrit. */
      const walkThrough=async()=>{
        for(let i=0;i<14;i+=1){
          const root=deep(document.body,C.DOM.flowRootId);
          if(!root)break;
          const found=[];
          const walk=n=>{if(n.tag==='button'||n.tagName==='BUTTON')found.push(n);
            for(const c of n.children)walk(c)};
          walk(root);
          /* « J'ai compris » pour les étapes qui expliquent, « Passer » pour
             celles qui attendent un geste, puis « Fermer » sur le
             récapitulatif — sans quoi la coque reste ouverte et un second
             `tutorial()` rendrait simplement `already:true`. */
          const next=found.find(b=>b.getAttribute('data-flow-action')==='understood')
            ||found.find(b=>b.getAttribute('data-flow-action')==='skip')
            ||found.find(b=>b.getAttribute('data-flow-action')==='close');
          if(!next)break;
          next.fire('click');
          await settle();
        }
        await settle();
      };
      await walkThrough();
      const seenWrites=()=>server.calls.filter(c=>c.body&&c.body.tutorial_seen===true).length;
      const firstRun=seenWrites();
      /* **Le relancer ne le réécrit pas.** Le réglage vaut déjà vrai : une
         seconde écriture est une requête pour rien, et si une autre écriture
         est en vol elle repart en « réglage non pris » à l'écran — un toast
         d'échec au moment précis où l'utilisateur vient de finir. */
      await BAREHANDS.tutorial();
      await walkThrough();
      const secondRun=seenWrites();
      const after=JSON.stringify(BAREHANDS.profile());
      const profileCalls=server.calls.filter(c=>String(c.path).endsWith('/profile')
        &&server.calls.indexOf(c)>=callsBefore);
      const writes=server.calls.slice(callsBefore).filter(c=>c.body!==null);
      out({started,state,before,after,same:before===after,
        profileCalls:profileCalls.length,firstRun,secondRun,
        wrote:writes.map(w=>Object.keys(w.body).filter(k=>k!=='schema_version')),
        seen:BAREHANDS.settings().tutorialSeen,
        measuring:BAREHANDS.measuring(),
        timers:ticks()});
    """, "profile")

    assert result["started"]["ok"] is True and result["started"]["flow"] == "tutorial"
    assert result["state"]["running"] is True and result["state"]["steps"] == 10
    # **L'aller-retour** : le profil relu après vaut exactement celui d'avant.
    assert result["same"] is True, (result["before"], result["after"])
    # Et la route du profil n'a pas été appelée du tout.
    assert result["profileCalls"] == 0
    # `tutorialSeen` est le seul réglage écrit, et il est passé sur le fil.
    assert result["wrote"] and all("tutorial_seen" in keys for keys in result["wrote"])
    assert result["seen"] is True
    # Écrit **une fois**, à la première traversée. Le relancer ne le réécrit
    # pas : le réglage vaut déjà vrai, et une écriture pour rien peut repartir
    # en « réglage non pris » au moment précis où l'utilisateur vient de finir.
    assert result["firstRun"] == 1 and result["secondRun"] == 1
    # Et la couture de mesure est restée fermée jusqu'au bout.
    assert result["measuring"] is False


def test_the_measurement_seam_stays_shut_for_the_whole_tutorial(tmp_path):
    """La couture de la décision 32 (`deps.onMeasure`) n'est posée que pendant
    une **calibration** : hors d'elle, le contrôleur teste `typeof
    deps.onMeasure` et ne calcule rien. Un tutoriel qui l'emprunterait ferait
    payer à chaque session le coût d'une mesure que personne n'a demandée, et
    ouvrirait au tutoriel une couture qu'il n'a pas le droit de lire.

    Mesuré sur le **vrai** contrôleur : ce que le tutoriel reçoit est une
    observation construite par la page, et rien n'a été mesuré."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();
      await settle();
      const atRest=BAREHANDS.measuring();
      const started=await BAREHANDS.tutorial();
      /* `measuring()` lit la couture **elle-même** (`deps.onMeasure` du
         contrôleur), pas un drapeau qu'on tient à côté : c'est ce qui fait la
         différence entre « le tutoriel ne mesure pas » et « le tutoriel mesure
         en silence », qui s'écrivaient pareil à l'écran comme à la console. */
      const during={tutorial:BAREHANDS.tutorialState().running,
        calibrating:BAREHANDS.calibration().running,
        measuring:BAREHANDS.measuring()};
      // Le chien de garde existe, et il tourne : c'est le second mécanisme.
      const watchdog=timers.filter(Boolean).map(t=>t.ms);
      tick(3);
      const still=BAREHANDS.tutorialState();
      const closed=await BAREHANDS.exitOverlay();
      const after=timers.filter(Boolean).map(t=>t.ms);
      out({started:started.ok,atRest,during,watchdog,still,closed,after,
        measuringAfter:BAREHANDS.measuring(),
        expected:T.DEFAULTS.watchdogMs,
        /* Et la couture n'a qu'un seul poseur : la calibration. Une seconde
           pose ailleurs rendrait `measuring()` vrai sans qu'un parcours de
           mesure tourne, donc la lecture mentirait. */
        opens:require('fs').readFileSync(SCRIPT_PATH,'utf8').split('startMeasuring();').length-1});
    """, "seam")

    assert result["started"] is True
    # **La couture reste fermée**, avant, pendant et après le tutoriel.
    assert result["atRest"] is False
    assert result["during"] == {"tutorial": True, "calibrating": False, "measuring": False}
    assert result["measuringAfter"] is False
    # Un seul appelant : `startCalibration`. Un second rendrait `measuring()`
    # vrai sans qu'un parcours de mesure tourne, donc la lecture mentirait.
    assert result["opens"] == 1, "la couture de mesure a plus d'un poseur"
    # Le chien de garde tourne à la cadence publiée, et il s'arrête à la sortie.
    assert result["expected"] in result["watchdog"]
    assert result["still"]["running"] is True
    assert result["closed"] == {"ok": True, "flow": "tutorial", "closed": True}
    assert result["expected"] not in result["after"], "le chien de garde survit au parcours"


def test_the_tutorial_is_fed_at_the_frame_rate_and_not_only_by_its_watchdog(tmp_path):
    """**La panne que ce test existe pour empêcher** : `interactions()` ne
    décrit qu'un *instant* — elle est vidée à chaque image. Un tutoriel
    échantillonné à la seule minuterie (500 ms) raterait la quasi-totalité des
    clics : il aurait demandé un geste, l'utilisateur l'aurait fait, et rien ne
    l'aurait enregistré. Pour un parcours d'apprentissage, c'est la pire panne
    possible, et elle est **silencieuse**.

    La couture est donc celle des images (`interactionView.afterFrame`,
    appelée à la fin de `hover`, là où `runCaptures` vient de ranger les
    interactions de l'image), et le chien de garde vient **en plus**, pour les
    étapes que personne ne nourrit. Mesuré ici à travers le **vrai** adaptateur
    d'interaction que le contrôleur appelle, pas un double."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();
      await settle();
      const frames=BAREHANDS.adapters.interaction;
      // Hors parcours, la couture n'est pas branchée : elle ne coûte rien.
      const idle=frames.afterFrame===undefined?'absente':typeof frames.afterFrame;
      const wiredAtRest=frames.afterFrame();
      frames.hover([]);
      const before=BAREHANDS.tutorialState().observed;
      await BAREHANDS.tutorial();
      const atStart=BAREHANDS.tutorialState().observed;
      // Cinq images d'interaction, par la porte que le contrôleur emprunte.
      for(let i=0;i<5;i+=1)frames.hover([]);
      const afterFrames=BAREHANDS.tutorialState().observed;
      // Puis un tour de chien de garde : il compte **en plus**, pas à la place.
      tick(1);
      const afterWatchdog=BAREHANDS.tutorialState().observed;
      const wiredDuring=frames.afterFrame();
      await BAREHANDS.exitOverlay();
      // Sorti, plus rien n'est nourri **et** la couture est déposée : une
      // fermeture qui survivrait au parcours serait appelée à chaque image
      // pour rien, jusqu'au rechargement de la page.
      const wiredAfter=frames.afterFrame();
      for(let i=0;i<5;i+=1)frames.hover([]);
      const afterExit=BAREHANDS.tutorialState().observed;
      /* Et un lecteur qui **lève** ne doit pas emporter la session : un refus
         codé dans la boucle d'images vaut la fin de la session (leçon des
         Slices 02 et 04). Il se dit et se saute. */
      frames.afterFrame(()=>{throw new Error('lecteur cassé')});
      let threw=false;
      try{frames.hover([])}catch(_error){threw=true}
      frames.afterFrame(null);
      out({idle,wiredAtRest,wiredDuring,wiredAfter,before,atStart,afterFrames,
        afterWatchdog,afterExit,threw,
        warned:logged.some(l=>l[0]==='warn'&&l[1].indexOf('lecteur de fin')>=0),
        running:BAREHANDS.tutorialState().running});
    """, "frames")

    assert result["idle"] == "function", "la couture est publiée par l'adaptateur"
    # Elle se relit : branchée pendant le parcours, déposée après.
    assert result["wiredAtRest"] is False
    assert result["wiredDuring"] is True
    assert result["wiredAfter"] is False
    # Hors parcours, une image ne nourrit rien.
    assert result["before"] == 0
    # Le lancement nourrit tout de suite (sinon la première étape attendrait
    # une image pour dire quoi que ce soit).
    assert result["atStart"] == 1
    # **Cinq images, cinq observations** : c'est la cadence des images.
    assert result["afterFrames"] == 6, result
    # Et le chien de garde en ajoute une : deux mécanismes, pas un déguisé.
    assert result["afterWatchdog"] == 7
    # Sorti, la couture est déposée : cinq images de plus ne comptent pas.
    assert result["running"] is False
    assert result["afterExit"] == 7
    # Un lecteur qui lève se dit et se saute : la boucle d'images survit.
    assert result["threw"] is False and result["warned"] is True


def test_the_button_and_the_voice_are_the_same_door_and_both_confirm(tmp_path):
    """Exigence de la Slice : « les actions vocales et d'interface doivent
    appeler les **mêmes** commandes d'exécution plutôt que des implantations
    parallèles ». La preuve n'est pas une lecture de source : le bouton de
    l'onglet et `JarvisBarehands.tutorial()` laissent la page dans le **même**
    état, et le second est exactement ce que le canal de la Slice 12 appelle.

    Et les deux points d'entrée **confirment** au sens du § 12 : `{ok:true}`
    dès que la coque est à l'écran, pas à la fin du parcours — l'échéance du
    canal est de trois secondes et un tutoriel en prend plusieurs minutes."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();
      await settle();
      const open=()=>!!deep(document.body,C.DOM.flowRootId);
      // Le bouton de l'onglet.
      document.getElementById('barehandsTutorialStart').fire('click');
      await settle();
      const byButton={open:open(),state:BAREHANDS.tutorialState()};
      await BAREHANDS.exitOverlay();
      await settle();
      // La même porte, appelée comme le canal l'appelle.
      const answer=await BAREHANDS.tutorial();
      const byVoice={open:open(),state:BAREHANDS.tutorialState()};
      // Un second appel pendant que la coque est ouverte **confirme**.
      const again=await BAREHANDS.tutorial();
      // La calibration est refusée tant que le tutoriel est à l'écran.
      const busy=await BAREHANDS.calibrate();
      const exited=await BAREHANDS.exitOverlay();
      await settle();
      // Rien d'ouvert : sortir confirme quand même — c'est l'état demandé.
      const idle=await BAREHANDS.exitOverlay();
      await settle();
      out({byButton,byVoice,answer,again,busy,exited,idle,
        /* **Trois tutoriels ouverts, trois sorties au milieu, et rien n'a été
           enregistré** : le récapitulatif n'a jamais été atteint. C'est la
           forme que `calibrated` a prise ailleurs sur cette tâche, refusée
           ici sur la vraie page et non seulement dans le module. */
        seen:BAREHANDS.settings().tutorialSeen,
        wroteSeen:server.calls.some(c=>c.body&&'tutorial_seen' in c.body
          &&c.body.tutorial_seen===true),
        confirmed:[answer,again,exited,idle].map(a=>a&&a.ok===true)});
    """, "door")

    assert result["byButton"]["open"] is True
    assert result["byButton"]["state"]["step"] == "wake"
    # Le bouton et la voix laissent la page dans le même état.
    assert result["byVoice"] == result["byButton"]
    assert result["answer"]["ok"] is True and result["answer"]["step"] == "wake"
    # Un second appel confirme au lieu de nier une coque qu'on voit à l'écran.
    assert result["again"] == {"ok": True, "flow": "tutorial", "already": True, "step": "wake"}
    # Une coque déjà ouverte refuse l'autre parcours, **en le disant**.
    assert result["busy"]["ok"] is False and result["busy"]["code"] == "barehands_flow_busy"
    assert "déjà à l’écran" in result["busy"]["reason"]
    assert result["exited"] == {"ok": True, "flow": "tutorial", "closed": True}
    assert result["idle"] == {"ok": True, "flow": None, "closed": False}
    assert all(result["confirmed"]), "le contrat flow_unconfirmed exige une confirmation explicite"
    # Trois parcours ouverts, trois sorties au milieu : « tutoriel vu » n'a
    # jamais été écrit, parce que le récapitulatif n'a jamais été atteint.
    assert result["seen"] is False and result["wroteSeen"] is False


def test_the_tutorial_refuses_with_a_named_cause_instead_of_turning_bare_hands_on(tmp_path):
    """**L'interrupteur appartient à l'utilisateur** (§ 12, et la règle que la
    Slice 08 a posée) : un parcours qui allumerait Bare Hands au passage
    rendrait la décision contournable par un autre nom. Le tutoriel ne réveille
    pas non plus, et c'est sa différence avec la calibration — sa première
    étape *est* le geste de réveil, l'exécuter à la place de l'utilisateur lui
    retirerait ce qu'on prétend lui apprendre.

    Chaque refus est dit **à l'écran** en plus d'être rendu : le canal a une
    liste de codes fermée et rend `barehands_flow_unconfirmed`, dont la phrase
    est vraie mais générique."""

    result = run_page(tmp_path, browser() + TIMERS + """
      await openTab();
      const off=await BAREHANDS.tutorial();
      const stillOff={enabled:BAREHANDS.settings().enabled,
        lifecycle:BAREHANDS.lifecycle(),
        open:!!deep(document.body,C.DOM.flowRootId)};
      const banner=document.getElementById('barehandsStatus').innerHTML;
      out({off,stillOff,toasts,banner,
        said:banner.indexOf('Activer Barehands')>=0});
    """, "refuse")

    assert result["off"]["ok"] is False
    assert result["off"]["code"] == "barehands_tutorial_disabled"
    # Rien n'a été allumé, et aucune coque ne s'est ouverte.
    assert result["stillOff"] == {"enabled": False, "lifecycle": "off", "open": False}
    # Vu à l'écran : bandeau **et** toast, parce que ce chemin s'atteint
    # panneau fermé (c'est celui de la voix).
    assert result["said"] is True
    assert "warn" in result["toasts"]


def test_a_voice_command_leaves_a_trace_on_screen_even_when_it_is_refused(tmp_path):
    """**L'Issue R13 de la Slice 12, refermée ici.** Une commande vocale
    appliquée redessinait bien le panneau, mais rien ne disait qu'elle venait
    de la voix ; et une commande vocale **refusée** ne laissait rien du tout à
    l'écran — un `console.warn`, puis le silence.

    La RÈGLE ZÉRO n'était pas violée (l'utilisateur *entend* JARVIS) : le manque
    était pour l'œil. Trois surfaces, parce qu'aucune seule ne suffit — la
    coque quand un parcours est ouvert (elle recouvre les toasts), un toast
    panneau fermé, et une ligne du panneau qui survit au toast et porte le code
    du refus."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      const empty=document.getElementById('barehandsVoice').innerHTML;
      // Un reçu de refus, tel que le canal le remet (Slice 12, `onReceipt`).
      BAREHANDS.voice.record({name:'tutorial',outcome:'refused',
        code:'barehands_flow_unconfirmed',reason:'JarvisBarehands.tutorial n\\'a pas confirmé le démarrage',
        lifecycle:'off'});
      const refusedLine=document.getElementById('barehandsVoice').innerHTML;
      const afterRefusal=toasts.slice();
      // Puis une commande appliquée : l'écran dit qu'elle vient de la voix.
      BAREHANDS.voice.record({name:'activate',outcome:'applied',code:'',reason:'',lifecycle:'active'});
      const appliedLine=document.getElementById('barehandsVoice').innerHTML;
      // Et pendant qu'un parcours est ouvert, c'est la **coque** qui le dit :
      // elle est au-dessus des toasts, donc c'est la seule qu'on regarde.
      await BAREHANDS.enable();await settle();
      await BAREHANDS.tutorial();
      const beforeShell=toasts.length;
      BAREHANDS.voice.record({name:'calibrate',outcome:'refused',code:'barehands_flow_busy',
        reason:'Le tutoriel est déjà à l’écran.',lifecycle:'sleep'});
      const shellNote=(()=>{const root=deep(document.body,C.DOM.flowRootId);
        const out=[];const walk=n=>{if(String(n.className||'').indexOf(C.DOM.flowNoteClass)>=0)out.push(n.textContent);
          for(const c of n.children)walk(c)};if(root)walk(root);return out})();
      out({empty,refusedLine,appliedLine,afterRefusal,
        shellNote,shellToasts:toasts.length-beforeShell,
        last:BAREHANDS.voice.last()});
    """, "voice")

    assert "Aucune commande vocale" in result["empty"]
    # Le refus est nommé, avec son code et la phrase exacte de la page.
    assert "tutorial" in result["refusedLine"] and "refusée" in result["refusedLine"]
    assert "barehands_flow_unconfirmed" in result["refusedLine"]
    assert "n’a pas confirmé" in result["refusedLine"] or "n'a pas confirmé" in result["refusedLine"]
    assert result["afterRefusal"][-1] == "bad", "un refus vocal se voit sans ouvrir le panneau"
    # Une commande appliquée se voit aussi : c'est ce qui la distingue d'un clic.
    assert "activate" in result["appliedLine"] and "appliquée" in result["appliedLine"]
    # Coque ouverte : la note y va, et **aucun** toast n'est posé dessous.
    assert any("calibrate" in note for note in result["shellNote"])
    assert result["shellToasts"] == 0
    assert result["last"]["name"] == "calibrate" and result["last"]["code"] == "barehands_flow_busy"


def test_the_channel_hands_its_receipt_to_the_screen_without_changing_what_it_reports(tmp_path):
    """Le canal de la Slice 12 n'a pas de surface à lui et n'en aura pas : il
    **donne** son reçu à qui sait dessiner. L'ajout est un dépôt
    (`deps.onReceipt`) et un accesseur (`last()`) ; `state().last` garde sa
    forme `"<commande>:<issue>"`, parce qu'un accesseur dont on change la forme
    casse ses lecteurs.

    Et une sortie qui lève ne mange pas le reçu : le cerveau attend la vérité du
    transport, pas celle de l'écran."""

    from test_barehands_commands_js import NETWORK, SETTLE, run_node as run_channel

    result = run_channel(tmp_path, browser() + NETWORK + SETTLE + """
      await openTab();
      const seen=[];
      let life='sleep';
      const channel=CH.createCommandChannel({surface:()=>({lifecycle:()=>life,
        activate:async()=>{life='active'}}),now:()=>7,sleep:async()=>{},random:()=>0.5,
        request:async()=>({status:200,body:{}}),
        onReceipt:entry=>seen.push(entry),log:()=>{}});
      await channel.apply({id:'a'.repeat(32),name:'activate',remaining_ms:3000});
      const before=channel.state().last;
      // Un puits qui lève : le reçu part quand même, et la panne est journalisée.
      const logs=[];
      let angryLife='sleep';
      const angry=CH.createCommandChannel({surface:()=>({lifecycle:()=>angryLife,
        activate:async()=>{angryLife='active'}}),now:()=>7,sleep:async()=>{},random:()=>0.5,
        request:async()=>({status:200,body:{}}),
        onReceipt:()=>{throw new Error('écran cassé')},
        log:(level,event)=>logs.push([level,event])});
      const outcome=await angry.apply({id:'b'.repeat(32),name:'activate',remaining_ms:3000});
      out({seen,before,last:channel.last(),outcome,logs,
        idle:CH.createCommandChannel({surface:()=>null,now:()=>0,sleep:async()=>{},
          random:()=>0.5,request:async()=>({status:200,body:{}}),log:()=>{}}).last()});
    """, "receipt")

    assert result["seen"] == [{"name": "activate", "outcome": "applied", "code": "",
                               "reason": "", "lifecycle": "active", "at": 7}]
    # `state().last` n'a pas changé de forme.
    assert result["before"] == "activate:applied"
    assert result["last"] == result["seen"][0]
    # `null` tant que rien n'est passé : « jamais » n'est pas « échoué ».
    assert result["idle"] is None
    # Un puits qui lève ne mange pas le reçu, et il est journalisé.
    assert result["outcome"] == "applied"
    assert ["warn", "barehands.receipt_sink_failed"] in result["logs"]


# ------------------------------------------------------------------ l'insertion


def test_the_page_inserts_the_tutorial_after_the_shell_and_before_the_pointer(tmp_path):
    """Constat F3 de la Slice 00 : un module de page ajouté déplace l'ordre
    d'insertion, et l'ordre est un contrat. Le tutoriel lit les contrats et
    **reprend la coque** de la calibration, donc il vient après les deux ; le
    pointeur le lit pour poser `tutorial()` et `exitOverlay()` sur une surface
    **gelée**, donc il vient avant lui.

    Servi, le repère a disparu — une balise laissée en place serait un module
    absent que personne ne verrait, la page n'ayant qu'un seul `<script>`."""

    from jarvis.runtime.control_center import (
        BAREHANDS_CALIBRATION_SCRIPT_MARKER, BAREHANDS_COMMANDS_SCRIPT_MARKER,
        BAREHANDS_CONTRACTS_SCRIPT_MARKER, BAREHANDS_SCRIPT_MARKER,
        BAREHANDS_TARGET_SCRIPT_MARKER, BAREHANDS_TUTORIAL_SCRIPT_MARKER,
        SCENE_PAGE_SCRIPT_MARKER, ControlCenter,
    )

    import asyncio

    raw = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    served = asyncio.run(control.index(None)).text

    order = [BAREHANDS_CONTRACTS_SCRIPT_MARKER, BAREHANDS_TARGET_SCRIPT_MARKER,
             BAREHANDS_CALIBRATION_SCRIPT_MARKER, BAREHANDS_TUTORIAL_SCRIPT_MARKER,
             BAREHANDS_SCRIPT_MARKER, BAREHANDS_COMMANDS_SCRIPT_MARKER,
             SCENE_PAGE_SCRIPT_MARKER]
    places = [raw.index(marker) for marker in order]
    assert places == sorted(places), "l'ordre d'insertion documenté n'est pas celui de la page"
    assert BAREHANDS_TUTORIAL_SCRIPT_MARKER not in served, "le repère n'a pas été remplacé"
    # Le module est bien celui-là, et il est servi entre les deux autres.
    assert served.index("root.JarvisBarehandsCalibration=api") \
        < served.index("root.JarvisBarehandsTutorial=api") \
        < served.index("window.JarvisBarehands=Object.freeze(")


def test_the_brain_is_told_the_three_flows_exist_and_what_a_confirmation_means(tmp_path):
    """La consigne du cerveau disait encore que la calibration et le tutoriel
    « ne sont pas encore implantés » — faux depuis la Slice 08 pour l'un, depuis
    celle-ci pour les deux autres. Une consigne périmée fait refuser au cerveau
    un outil qui marche, et c'est indiscernable d'une panne.

    Elle dit désormais ce qu'une confirmation **signifie** : le parcours a
    démarré, pas qu'il est fini — sans quoi JARVIS annoncerait « c'est
    calibré » devant une surimpression qui vient de s'ouvrir."""

    from jarvis.runtime import claude_local
    from jarvis.domain import barehands_command as vocab

    prompt = claude_local.BRAIN_BAREHANDS_PROMPT
    for command in vocab.COMMANDS:
        assert f"barehands_{command}" in prompt, command
    assert "ne sont pas encore implantés" not in prompt
    assert "n'existent pas encore" not in prompt
    # Ce que le cerveau ne doit pas dire, dit en toutes lettres.
    assert "démarré" in prompt
    assert "l'interrupteur est à lui" in prompt, "décision 6 : l'interrupteur reste à l'utilisateur"
