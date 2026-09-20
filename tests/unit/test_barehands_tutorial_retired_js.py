"""Le tutoriel est retiré : une seule surface, un alias honnête, un champ toléré.

Slice 07B ; décisions 10 et 17, architecture §9 (« ne jamais garder deux
parcours »), READINESS §4. Exécuté par node : les contrats, le moteur, la coque
et la calibration sont les **vrais** ; seuls le DOM, l'horloge et le réseau sont
des doubles, parce que node n'en a pas.

Ce fichier **remplace** `test_barehands_tutorial_js.py` (26 tests), supprimé
avec le module qu'il décrivait. La plus grande partie de ces 26 décrivait le
module lui-même — ses dix étapes, sa liste blanche d'observation, ses deux
paires dangereuses, son récapitulatif — et ces assertions meurent à juste titre
avec lui : elles ne portaient sur rien d'autre. Ce qui est repris ici est ce qui
restait vrai du **système** :

- la sortie permanente à chaque écran du parcours (l'ancien
  `test_the_way_out_is_permanent…`, vérifié maintenant sur le seul parcours) ;
- « deux parcours ne peuvent pas se recouvrir » devient « il n'y en a qu'un, et
  rien ne peut en construire un second » ;
- la porte `tutorial()` confirme — mais ce qu'elle confirme a changé, et c'est
  le sujet principal de ce fichier ;
- ses refus, qui portent désormais le nom de ce qui a réellement refusé ;
- la consigne du cerveau, qui doit dire ce que l'outil fait et non ce que son
  nom promet.

Le reçu du canal remis à l'écran (ancien
`test_the_channel_hands_its_receipt_to_the_screen…`) est repris dans
`test_barehands_commands_js.py`, qui possède le canal.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_barehands_tools_settings_js import (  # noqa: E402
    CALIBRATION, CAMERA, CONTRACTS, HAND_ART, RECORDER, SCENE_INTERACT,
    SCRIPT, TARGET, TIMERS, browser,
)
from test_barehands_calibration_js import DOM  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
RETIRED_MODULE = RUNTIME / "control_center_barehands_tutorial.js"


def run_page(tmp_path: Path, source: str, name: str) -> object:
    """Le **vrai** bloc navigateur du pointeur, sans module de tutoriel — il
    n'y en a plus à insérer."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-retired-{name}.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
        f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};\n"
        f"const HAND_ART_PATH={json.dumps(str(HAND_ART))};\n"
        f"const RECORDER_PATH={json.dumps(str(RECORDER))};\n"
        f"const TARGET_PATH={json.dumps(str(TARGET))};\n"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};\n"
        f"const CONTRACTS_PATH={json.dumps(str(CONTRACTS))};\n"
        "const C=require(CONTRACTS_PATH);\n"
        "const G=require(SCENE_INTERACT_PATH);\n"
        "const out=v=>process.stdout.write(JSON.stringify(v),()=>process.exit(0));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ le retrait


def test_no_tutorial_module_exists_and_the_served_page_cannot_build_one():
    """**Le retrait est structurel, pas une intention.**

    L'architecture §9 est catégorique — « ne jamais garder deux parcours » — et
    le contrat de la Slice l'est aussi : pas de seconde machine à états vivante
    derrière l'alias. Une coquille de compatibilité qui exporterait encore
    `createTutorial` laisserait la surimpression **constructible** ; c'est une
    promesse, et une promesse n'est pas un mécanisme.

    Le fichier est donc supprimé. Trois choses le vérifient, parce qu'aucune
    seule ne suffit : le module n'est pas sur le disque, la page servie n'en
    porte ni le repère ni le code, et aucun global ne le publie."""

    assert not RETIRED_MODULE.exists(), (
        "control_center_barehands_tutorial.js est de retour : "
        "il n'y a qu'un parcours guidé, et un second module en est un second"
    )

    from jarvis.runtime import control_center as cc

    assert not hasattr(cc, "BAREHANDS_TUTORIAL_SCRIPT_FILE")
    assert not hasattr(cc, "BAREHANDS_TUTORIAL_SCRIPT_MARKER")
    raw = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    assert "CONTROL_CENTER_BAREHANDS_TUTORIAL_JS" not in raw, (
        "un repère resté en place est un module absent que personne ne voit"
    )


def test_the_page_publishes_no_tutorial_flow_and_the_old_door_lands_in_calibration(tmp_path):
    """**Il y a exactement un parcours guidé.**

    L'ancien `test_the_two_flows_share_one_shell_and_neither_can_cover_the_other`
    prouvait que deux parcours ne pouvaient pas se recouvrir. Il n'y en a plus
    qu'un : ce qui reste à prouver est qu'aucun second ne peut apparaître — pas
    de global à qui en demander un, pas de porte de la surface gelée qui ouvre
    autre chose que la calibration.

    **Ce que node ne peut pas faire ici, et c'est documenté** : le double de
    navigateur ne charge pas MediaPipe, donc la page n'atteint jamais `active`
    et la coque ne s'ouvre jamais pour de vrai (même limite que
    `test_barehands_calibration_js.py::…pageclock`). La preuve prend donc
    l'autre bout : les deux portes, l'héritée et la vraie, échouent **au même
    endroit, avec le même code et la même phrase**. Deux parcours distincts ne
    pourraient pas faire cela. Le succès décoré est épinglé par
    `test_the_alias_confirmation_survives_the_channel_as_a_receipt` et, de bout
    en bout sur le vrai serveur, par `test_barehands_command_channel.py`."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();
      await settle();
      /* Aucun global de tutoriel, ni sur `global` ni sur `window` : rien a qui
         un appelant pourrait demander de construire un parcours. */
      const globals={bare:typeof global.JarvisBarehandsTutorial,
        win:typeof window.JarvisBarehandsTutorial};
      const legacy=await BAREHANDS.tutorial();
      const direct=await BAREHANDS.calibrate();
      out({globals,legacy,direct,
        open:!!deep(document.body,C.DOM.flowRootId),
        surface:Object.keys(BAREHANDS).filter(k=>/tutorial/i.test(k)).sort(),
        state:BAREHANDS.tutorialState()});
    """, "onlyone")

    assert result["globals"] == {"bare": "undefined", "win": "undefined"}
    # **Les deux portes sont la même porte.** Même code, même phrase, même
    # absence de coque : l'héritée n'a pas de parcours à elle.
    assert result["legacy"]["code"] == result["direct"]["code"] == "barehands_calibration_no_camera"
    assert result["legacy"]["reason"] == result["direct"]["reason"]
    assert result["legacy"]["ok"] is False and result["open"] is False
    # Un refus n'est **pas** décoré : sa cause exacte remonte, pas la nôtre.
    assert "deprecated" not in result["legacy"]
    # Deux membres seulement gardent le nom, et ce sont ceux de la surface
    # gelée — pas un troisième arrivé par la bande.
    assert result["surface"] == ["tutorial", "tutorialState"]
    # `tutorialState()` dit le retrait, et non une panne d'insertion.
    assert result["state"] == {"retired": True, "replacedBy": "calibration",
                               "running": False, "seen": False}


def test_the_alias_confirmation_survives_the_channel_as_a_receipt(tmp_path):
    """**Le reçu doit dire ce qui s'est ouvert, pas ce qu'on a demandé.**

    C'est la règle du canal (§ 12) portée au cas où elle mord le plus fort : la
    commande s'appelle `tutorial` et ce qui s'ouvre est une calibration. Une
    confirmation nue (`{ok:true}`) ferait dire à JARVIS « j'ai lancé le
    tutoriel » devant une calibration — le faux récit exact que ce canal existe
    pour empêcher. Jusqu'ici `reason` ne portait que la cause d'un refus ; il
    porte maintenant, pour un succès, ce que le **parcours** dit avoir fait.

    Surface injectée, comme les deux autres cas que node ne peut pas atteindre
    sur le vrai pointeur (`SURFACE` de `test_barehands_commands_js`) : sa forme
    est épinglée sur la vraie par `test_what_a_brain_sees_today_…`, et la phrase
    exacte est relue **dans la source de la page**, donc les deux ne peuvent pas
    diverger en silence."""

    from test_barehands_commands_js import BROWSER, NETWORK, SURFACE
    from test_barehands_commands_js import run_node as run_channel

    page = SCRIPT.read_text(encoding="utf-8")
    assert "startTutorialAlias" in page
    assert "tutorial:()=>startTutorialAlias()" in page, (
        "la surface gelée doit router `tutorial` vers l'alias, pas vers un parcours"
    )
    said = ("Commande dépréciée : le parcours de tutoriel a été retiré, "
            "c’est la calibration qui a été ouverte.")
    # La phrase est construite en deux morceaux dans la page ; les deux y sont.
    for piece in said.split(", "):
        assert piece.strip() in page, piece

    result = run_channel(tmp_path, BROWSER + NETWORK + SURFACE + """
      const said=""" + json.dumps(said) + """;
      /* Ce que `startTutorialAlias` rend quand la calibration s'ouvre : la
         reponse de `startCalibration()`, plus les trois champs de l'alias. */
      const made=makeSurface('active',{tutorial:{ok:true,flow:'calibration',step:'neutral',
        steps:6,screens:7,deprecated:true,reason:said}});
      const applied=await drive(made,'tutorial');
      // Un second appel devant une coque deja ouverte : `duplicate`, pas
      // « je l'ai ouverte », et la phrase reste.
      const twice=makeSurface('active',{tutorial:{ok:true,flow:'calibration',
        already:true,deprecated:true,reason:said}});
      const dup=await drive(twice,'tutorial');
      // Un parcours qui ne dit rien laisse `reason` nul : le canal ne fabrique
      // aucune phrase, il ne fait que recopier celle qu'on lui donne.
      const silent=makeSurface('active',{calibrate:{ok:true,flow:'calibration'}});
      const bare=await drive(silent,'calibrate');
      // Et il la **borne** comme le domaine Python (200 caracteres) : ce que
      // la page croit avoir dit est ce que le cerveau lira.
      const long=makeSurface('active',{tutorial:{ok:true,reason:'z'.repeat(400)}});
      const cut=await drive(long,'tutorial');
      out({applied,dup,bare,cut:cut.reason.length,called:made.calls});
    """, "aliasReceipt")

    assert result["applied"]["outcome"] == "applied"
    assert result["applied"]["code"] is None
    # **La phrase traverse le canal**, et c'est elle qui empêche le cerveau
    # d'annoncer un tutoriel.
    assert result["applied"]["reason"] == said
    assert "calibration" in result["applied"]["reason"]
    # `already` reste `duplicate`, et la phrase reste : « rien à faire » et
    # « c'est ouvert » ne se disent pas pareil, mais les deux disent quoi.
    assert result["dup"]["outcome"] == "duplicate"
    assert result["dup"]["reason"] == said
    # Rien n'est inventé pour un parcours muet.
    assert result["bare"]["reason"] is None
    assert result["cut"] == 200
    # La porte appelée est bien celle de la table, pas `calibrate` en douce :
    # c'est la page qui décide ce qui s'ouvre, pas le transport.
    assert result["called"] == ["tutorial"]


def test_the_deprecated_door_inherits_the_calibration_refusals_under_their_own_codes(tmp_path):
    """**Un refus garde le nom de ce qui a refusé.**

    L'appelant a demandé `tutorial` et a obtenu la calibration. Quand elle
    refuse, le code est `barehands_calibration_*`. Le renommer en
    `barehands_tutorial_*` cacherait **lequel** des parcours a échoué. L'ancien
    `test_the_tutorial_refuses_with_a_named_cause_instead_of_turning_bare_hands_on`
    vérifiait la même chose sous l'ancien code ; c'est sa suite, et il garde son
    exigence principale — l'interrupteur appartient à l'utilisateur, et un
    parcours ne l'allume pas au passage."""

    off = run_page(tmp_path, browser() + TIMERS + """
      await openTab();
      const refused=await BAREHANDS.tutorial();
      const still={enabled:BAREHANDS.settings().enabled,lifecycle:BAREHANDS.lifecycle(),
        open:!!deep(document.body,C.DOM.flowRootId)};
      const banner=document.getElementById('barehandsStatus').innerHTML;
      out({refused,still,toasts,said:banner.indexOf('bouton à icône de main')>=0});
    """, "refuseOff")

    assert off["refused"]["ok"] is False
    # Slice 08 : la cause « Bare Hands éteint » a son propre code, distinct du
    # réglage décoché. L'alias en hérite tel quel — c'est tout son contrat.
    assert off["refused"]["code"] == "barehands_calibration_lifecycle_off"
    # **Rien n'a été allumé.** L'interrupteur appartient à l'utilisateur (§ 12) ;
    # l'alias n'est pas un autre nom pour le contourner.
    assert off["still"] == {"enabled": False, "lifecycle": "off", "open": False}
    # Vu à l'écran, pas seulement rendu : bandeau **et** toast, parce que ce
    # chemin s'atteint panneau fermé — c'est celui de la voix.
    assert off["said"] is True
    assert "warn" in off["toasts"]
    assert "deprecated" not in off["refused"]


def test_the_deprecated_door_wakes_bare_hands_because_calibration_needs_the_camera(tmp_path):
    """**Le réveil, et pourquoi la différence héritée disparaît.**

    `startTutorial()` ne réveillait délibérément pas : sa première étape *était*
    le geste de réveil, et l'exécuter à la place de l'utilisateur lui retirait
    ce qu'on prétendait lui apprendre. Cette étape n'existe plus. Ce qui s'ouvre
    maintenant est une calibration, qui ne peut rien mesurer sans voir des
    mains ; garder la non-veille protégerait une garantie sans objet et ferait
    refuser toute commande vocale `tutorial` sur une caméra jamais démarrée.

    **La preuve est le code de refus.** L'ancien tutoriel n'avait pas de refus
    « pas de caméra » — c'était écrit noir sur blanc dans son point d'entrée, et
    délibéré. Recevoir `barehands_calibration_no_camera` prouve donc que l'alias
    est allé jusqu'à `setAwake(true)` puis a relu le cycle de vie : c'est le
    seul chemin qui produit ce code."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();await settle();
      const before=BAREHANDS.lifecycle();
      const answer=await BAREHANDS.tutorial();
      out({before,after:BAREHANDS.lifecycle(),answer,
        tried:logged.filter(l=>String(l[1]||'').indexOf('tutorial_deprecated')>=0).length});
    """, "wake")

    assert result["answer"]["code"] == "barehands_calibration_no_camera"
    assert "caméra" in result["answer"]["reason"]
    # La dépréciation est dite dans la console à chaque appel : un fait de la
    # page, journalisé là où la page se lit.
    assert result["tried"] == 1


# ------------------------------------------------- ce qui reste à l'écran


def test_no_tutorial_control_remains_in_the_settings_panel_or_the_quick_menu(tmp_path):
    """**Aucune entrée Tutoriel nulle part.**

    Les Slices 02 et 04 avaient retiré la section de lancement des réglages ;
    le menu du clic droit n'en a jamais eu (décision 9). Restait une case
    « Tutoriel déjà vu », dernière occurrence visible du mot, retirée ici : une
    case qui interroge l'utilisateur sur l'achèvement d'un parcours qui
    n'existe plus n'est pas un réglage.

    Vérifié sur le **rendu**, pas sur la source : la page servie concatène ses
    modules dans une seule balise `<script>`, commentaires compris, et un
    commentaire qui explique un retrait n'est pas un contrôle."""

    result = run_page(tmp_path, browser() + TIMERS + """
      await openTab();
      const html=modalContent.innerHTML;
      out({html,
        words:/[Tt]utoriel|[Tt]utorial/.test(html),
        checkbox:/bh_tutorialSeen/.test(html),
        section:/id="barehandsTutorial"/.test(html)});
    """, "panel")

    assert "Réglages" in result["html"], "le panneau doit être dessiné pour que l'absence dise quelque chose"
    assert result["checkbox"] is False, "la case « Tutoriel déjà vu » est retirée"
    assert result["section"] is False
    assert result["words"] is False, (
        "plus aucun mot « tutoriel » dans l'onglet : la calibration enseigne (décision 17)"
    )

    # Le menu du clic droit : quatre entrées, et le mot y est banni depuis la
    # Slice 02. Relu ici à la source du modèle plutôt que dupliqué en test node.
    hud = (RUNTIME / "control_center_barehands_hud.js").read_text(encoding="utf-8")
    assert "QUICK_ORDER" in hud
    for banned in ("'tutorial'", '"tutorial"', "Tutoriel…", "Tutoriel :"):
        assert banned not in hud, banned


def test_the_only_flow_keeps_a_way_out_on_every_screen_it_draws(tmp_path):
    """**Quatrième point de la RÈGLE ZÉRO : comment en sortir**, repris de
    l'ancien `test_the_way_out_is_permanent_and_does_not_depend_on_what_a_flow_draws`.

    Les boutons d'une étape sont redessinés à chaque étape, donc « on peut
    toujours quitter » dépendrait de ce que le parcours pense à dessiner — et
    le rapport, par exemple, n'offre que « Annuler ». La coque pose donc une
    sortie qui ne bouge pas, hors de `actions`, qu'aucun parcours ne peut
    effacer sans le savoir.

    L'ancien test le vérifiait sur les **deux** parcours ; il n'y en a plus
    qu'un, et c'est sur celui-là qu'il est vérifié — à chaque écran, rapport
    compris."""

    from test_barehands_calibration_js import DRIVER, run_node as run_calibration

    result = run_calibration(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      const closes=root=>allButtons(root).filter(n=>n.getAttribute('data-flow-close')!==null);
      const seen=[];
      for(let i=0;i<12;i+=1){
        const root=flowRoot();
        if(!root)break;
        const exit=closes(root)[0];
        seen.push([cal.stepId(),closes(root).length,
          exit?exit.getAttribute('aria-label'):null]);
        if(!skipStep(cal))break;
      }
      out({seen,screens:seen.length});
    """, name="wayOut")

    assert result["screens"] >= 7, (
        "les six exercices et le rapport doivent tous être traversés : "
        f"{result['seen']}"
    )
    for step, count, label in result["seen"]:
        # **Exactement une** sortie permanente, à chaque écran. Zéro est la
        # panne que la RÈGLE ZÉRO interdit ; deux serait un parcours qui en a
        # dessiné une de plus et que la coque ne contrôle pas.
        assert count == 1, (step, count)
        assert label, step


# ------------------------------------------------- le réglage persisté


def test_the_stale_tutorial_seen_setting_is_tolerated_and_nothing_writes_it_any_more(tmp_path):
    """**Migration choisie : conservation explicite, pas de montée de schéma.**

    Le champ `tutorial_seen` / `tutorialSeen` reste dans le schéma
    (`SCHEMA_VERSION = 2`) et n'est plus écrit par personne. Le supprimer
    exigerait de monter `SCHEMA_VERSION` **et** `SETTINGS_SCHEMA_VERSION` dans
    le même changement, et ferait refuser `validate()` (« champ inconnu ») sur
    toute sauvegarde venue d'une page ouverte avant le déploiement — une panne
    à 400 pour gagner un booléen inerte. C'est le même arbitrage que pour la
    commande, et il tombe du même côté.

    Ce que ce test épingle : la valeur **survit** à un aller-retour (rien ne la
    jette en silence), et **rien ne l'écrit** — ni l'ouverture du parcours, ni
    sa traversée, ni sa fermeture."""

    result = run_page(tmp_path, CAMERA + browser("""
      // Des réglages d'une installation où l'ancien tutoriel avait été vu.
      server.state=Object.assign(C.toServerPayload({tutorialSeen:true}),
        {stored_schema_version:2,unreadable:false,archived:[]});
    """) + TIMERS + """
      await openTab();
      const loaded=BAREHANDS.settings().tutorialSeen;
      await BAREHANDS.enable();await settle();
      await BAREHANDS.tutorial();
      await BAREHANDS.exitOverlay();
      await settle();
      out({loaded,after:BAREHANDS.settings().tutorialSeen,
        // Personne n'écrit ce champ : aucune requête ne le porte à `true`.
        wrote:server.calls.filter(c=>c.body&&'tutorial_seen' in c.body)
          .map(c=>c.body.tutorial_seen),
        state:BAREHANDS.tutorialState()});
    """, "stale")

    # **Rien n'est jeté en silence** : la valeur stockée revient telle quelle.
    assert result["loaded"] is True
    assert result["after"] is True
    # Le parcours ouvert puis fermé n'a rien écrit de nouveau ; et si une
    # sauvegarde a eu lieu pour une autre raison, elle a recopié la valeur lue,
    # jamais inventé un `true`.
    assert all(value is True for value in result["wrote"]), result["wrote"]
    # Et l'accesseur public le dit honnêtement, retrait compris.
    assert result["state"] == {"retired": True, "replacedBy": "calibration",
                               "running": False, "seen": True}


def test_the_settings_schema_still_carries_the_field_on_both_sides():
    """Les deux miroirs du schéma portent encore le champ, **et le disent**.

    Un champ de compatibilité non documenté est une dette invisible : la règle
    du dépôt veut une entrée `docs/legacy/*.md`, un commentaire d'implantation
    et une condition de suppression. Les trois sont vérifiés ici, parce qu'un
    commentaire qu'aucun test ne lit disparaît au premier nettoyage."""

    from jarvis.runtime import barehands_test_mode as mode

    assert mode.SCHEMA_VERSION == 2, "aucune montée de schéma n'était nécessaire ici"
    assert "tutorial_seen" in mode.SETTINGS_DEFAULTS
    assert mode.SETTINGS_DEFAULTS["tutorial_seen"] is False

    legacy = ROOT / "docs" / "legacy" / "barehands-tutorial-retirement.md"
    assert legacy.exists(), "un champ de compatibilité sans entrée `docs/legacy` est une dette invisible"
    text = legacy.read_text(encoding="utf-8")
    assert "Condition de suppression" in text
    assert "tutorial_seen" in text

    source = (RUNTIME / "barehands_test_mode.py").read_text(encoding="utf-8")
    assert "barehands-tutorial-retirement.md" in source, (
        "le commentaire d'implantation doit pointer sa condition de suppression"
    )
    contracts = (RUNTIME / "control_center_barehands_contracts.js").read_text(encoding="utf-8")
    assert "barehands-tutorial-retirement.md" in contracts


# ------------------------------------------------- ce que le cerveau lit


def test_the_brain_is_told_the_tutorial_tool_is_deprecated_and_opens_calibration():
    """**Une consigne qui promet autre chose que ce que l'outil fait est un
    faux succès en attente.**

    L'ancien `test_the_brain_is_told_the_three_flows_exist…` épinglait que la
    consigne ne disait plus « pas encore implantés ». Elle ne doit pas non plus
    annoncer un tutoriel : le cerveau qui lirait « lance le tutoriel →
    barehands_tutorial » dirait « j'ouvre le tutoriel » et l'utilisateur
    verrait une calibration."""

    from jarvis.domain import barehands_command as vocab
    from jarvis.runtime import claude_local

    prompt = claude_local.BRAIN_BAREHANDS_PROMPT
    # Le vocabulaire est toujours couvert en entier : l'alias reste une commande.
    for command in vocab.COMMANDS:
        assert f"barehands_{command}" in prompt, command
    assert "tutorial" in vocab.COMMANDS, "l'alias reste au contrat (READINESS §4)"
    # Ce que la consigne doit dire, en toutes lettres.
    assert "déprécié" in prompt
    assert "un seul parcours guidé" in prompt
    assert "démarré" in prompt
    assert "l'interrupteur est à lui" in prompt, "décision 6 : l'interrupteur reste à l'utilisateur"
    # Et ce qu'elle ne doit plus dire : router « montre-moi comment faire » vers
    # le tutoriel, ou promettre deux parcours concurrents.
    assert "ne sont pas encore implantés" not in prompt
    assert "tu as fini le tutoriel" not in prompt
    assert "Un seul parcours à la fois" not in prompt


def test_the_mcp_tool_description_says_it_opens_calibration():
    """La description de l'outil est la seule chose que le cerveau lit avant de
    choisir. « Lancer le tutoriel de Bare Hands » était vrai jusqu'ici ; elle
    doit maintenant dire la dépréciation et la calibration, sans quoi la
    consigne et l'outil se contrediraient — et c'est l'outil qui gagne."""

    from jarvis.runtime import barehands_mcp

    # La parité tient toujours : c'est elle qui rend la suppression coûteuse,
    # et donc l'alias raisonnable.
    assert barehands_mcp.TOOL_COMMANDS["barehands_tutorial"] == "tutorial"
    assert tuple(barehands_mcp.TOOL_COMMANDS.values()) == barehands_mcp.COMMANDS

    source = (RUNTIME / "barehands_mcp.py").read_text(encoding="utf-8")
    start = source.index("async def barehands_tutorial")
    description = source[max(0, start - 1400):start]
    assert "Déprécié" in description
    assert "CALIBRATION" in description
    assert "barehands_calibration_" in description, (
        "le cerveau doit savoir que les refus portent le nom de la calibration"
    )
