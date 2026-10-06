"""Le contrôle de mode d'interaction, mesuré dans un vrai navigateur.

**Pourquoi ce fichier existe.** Trois défauts de cette Slice ont survécu à des
tests qui lisaient la feuille de style comme du texte : la règle y était,
nommait le bon sélecteur, et la cascade faisait le contraire. Le dernier en date
— le halo qui continuait de respirer sous `prefers-reduced-motion` — perdait par
spécificité contre une règle écrite vingt lignes plus haut, et le test passait
parce que le nom `.im-mark::after` apparaissait bien dans le bloc.

Ici on ne lit rien : on compose la page **telle que `ControlCenter.index` la
sert**, on la charge dans Chrome sans tête, on impose une taille, et on relève
des rectangles et des styles **calculés**. C'est le seul niveau auquel « le
bouton ne recouvre pas la palette » et « le halo s'arrête » veulent dire quelque
chose.

Ce que ce fichier épingle :

- sous 700 px de large, le bouton ne recouvre plus la palette Bare Hands —
  le défaut qui rendait son outil du bas incliquable, puisque le bouton est au
  rang 32 et la palette au rang 30 ;
- à pleine largeur, rien n'a bougé ;
- `prefers-reduced-motion` arrête vraiment le halo, la barre de balayage et les
  transitions.

Le test se saute proprement si Chrome est absent ; il ne se saute pas en
silence si la page ne se compose pas.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from aiohttp import web
import pytest

from jarvis.core.interaction_mode import InteractionModeService
import jarvis.runtime.control_center as cc
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.interaction_mode_view import CoreInteractionModeView
from tests.unit.test_interaction_mode_control_plane import RecordingBus, ServiceReader

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"

#: Chrome, aux emplacements où Windows le pose. Absent, les tests se sautent —
#: mais ils ne mentent pas : rien ici ne « passe » sans navigateur.
CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)


def _chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    pytest.skip("Chrome absent")


def _served_page(tmp_path: Path) -> Path:
    """La page **servie**, composée comme `ControlCenter.index` la compose.

    `index` est une chaîne de remplacements de marqueurs littéraux : la même
    chaîne sur les mêmes fichiers produit le même document, sans serveur. On
    découvre les paires marqueur/fichier depuis le module lui-même, pour qu'un
    module ajouté plus tard entre ici sans que personne n'y pense.
    """

    page = RUNTIME / "control_center.html"
    html = page.read_text(encoding="utf-8")
    pairs = [
        (getattr(cc, name), getattr(cc, name.replace("_MARKER", "_FILE")))
        for name in dir(cc)
        if name.endswith("_SCRIPT_MARKER") and hasattr(cc, name.replace("_MARKER", "_FILE"))
    ]
    assert pairs, "aucun module de page découvert"
    for marker, filename in pairs:
        html = html.replace(marker, (RUNTIME / filename).read_text(encoding="utf-8"))
    left = [marker for marker, _ in pairs if marker in html]
    assert not left, f"marqueurs non remplacés : {left}"
    html = re.sub(r'<iframe class="face"[^>]*></iframe>', '<div class="face"></div>', html)
    out = tmp_path / "served.html"
    out.write_text(html, encoding="utf-8")
    return out


#: Le harnais CDP, en JavaScript parce que c'est là que vit le WebSocket de node.
HARNESS = (Path(__file__).parent / "_interaction_mode_browser.mjs")


def _drive(tmp_path: Path, plan: list) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    done = subprocess.run(
        [node, str(HARNESS), str(page), chrome, json.dumps(plan)],
        capture_output=True, text=True, encoding="utf-8", timeout=180, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _overlap(a: dict, b: dict) -> tuple[int, int] | None:
    if not a or not b:
        return None
    wide = min(a["r"], b["r"]) - max(a["l"], b["l"])
    high = min(a["b"], b["b"]) - max(a["t"], b["t"])
    return (round(wide), round(high)) if wide > 0 and high > 0 else None


@pytest.mark.parametrize("width,height", [(700, 600), (700, 750), (700, 900), (500, 700)])
def test_sous_700px_le_bouton_ne_recouvre_plus_la_palette_bare_hands(tmp_path, width, height):
    """Le défaut mesuré : 64x46 à 700x600, et pas seulement sur un écran court.

    Sous 700 px la colonne Bare Hands devient relative au centre et la hauteur
    de sa palette dépend du nombre d'outils installés : aucune règle verticale
    ne peut calculer ce dégagement, et le relevement du rail rendait la chose
    pire en enfonçant le bouton plus loin dedans. Le bouton étant au rang 32 et
    la palette au rang 30, c'est l'outil du bas qui devenait incliquable — une
    régression de Bare Hands causée par ce contrôle, contre la contrainte
    explicite de cette Slice.

    La sortie est horizontale : on passe à droite d'une colonne dont la largeur,
    elle, est fixe."""

    seen = _drive(tmp_path, [{"width": width, "height": height, "mountPalette": True,
                              "toast": True}])[0]
    button, palette = seen["modeBtn"], seen["palette"]
    assert palette, "la palette est bien montée : sans elle ce test ne prouve rien"
    # **Aucun recouvrement**, ni partiel ni total.
    assert _overlap(button, palette) is None, (button, palette)
    # Et il est bien passé à DROITE d'elle, pas au-dessus : c'est ce qui rend la
    # promesse indépendante du nombre d'outils installés.
    assert button["l"] >= palette["r"], (button, palette)
    # Les autres occupants de ce coin, mesurés aussi : la marque des mains et
    # l'indicateur de scène partagent le rail, l'indication vocale est centrée,
    # les infusions montent depuis le bas.
    for name in ("hint", "toast", "dock", "pills", "bhHud"):
        assert _overlap(button, seen.get(name)) is None, (name, button, seen.get(name))


def test_a_pleine_largeur_le_controle_ne_bouge_pas(tmp_path):
    """La correction est bornée au petit écran ; le grand est déjà mesuré bon."""

    seen = _drive(tmp_path, [{"width": 1440, "height": 900, "mountPalette": True,
                              "toast": True}])[0]
    button = seen["modeBtn"]
    # Toujours sur le rail gauche, à son offset d'origine.
    assert round(button["l"]) == 18
    for name in ("palette", "bhHud", "hint", "toast", "dock", "pills"):
        assert _overlap(button, seen.get(name)) is None, (name, button, seen.get(name))


def test_le_mouvement_reduit_arrete_vraiment_le_halo(tmp_path):
    """La règle existait, nommait le bon sélecteur, et perdait dans la cascade.

    `#hôte[data-im-tone=presentation] .im-mark::after` vaut (1,2,1) ; la règle
    d'arrêt écrite `#hôte .im-mark::after` ne vaut que (1,1,1). Le halo
    continuait donc de respirer sous `prefers-reduced-motion`, pendant qu'un
    test lisant la feuille comme du texte trouvait bien `.im-mark::after` dans
    le bloc et passait. On relève ici l'animation **calculée**."""

    plan = [
        {"width": 1440, "height": 900, "tone": "presentation", "reducedMotion": False},
        {"width": 1440, "height": 900, "tone": "presentation", "reducedMotion": True},
    ]
    normal, reduced = _drive(tmp_path, plan)

    # Au repos, le halo respire vraiment : sans cela l'assertion suivante serait
    # vraie pour la mauvaise raison.
    assert normal["motion"]["halo"] != "none", normal["motion"]
    assert "imBreathe" in normal["motion"]["halo"]
    assert normal["motion"]["sweep"] != "none"

    # Mouvement réduit : les trois s'arrêtent.
    assert reduced["motion"]["halo"] == "none", reduced["motion"]
    assert reduced["motion"]["sweep"] == "none", reduced["motion"]
    assert reduced["motion"]["popAnimation"] == "none", reduced["motion"]
    assert reduced["motion"]["buttonTransition"] in ("none", "all 0s ease 0s", ""), \
        reduced["motion"]


# ------------------------- la séance PRESENTATION, sur un vrai Control Center
#
# Slice 03 de `jarvis-presentation-interaction-mode` (2026-10). Les tests
# ci-dessous ne composent pas la page à la main : ils servent le **vrai**
# `ControlCenter` sur le bouclage, et la page fait son propre sondage à 1 Hz sur
# le vrai `/api/status`. Core est le vrai `InteractionModeService`, branché par
# le transport factice que les tests du plan de contrôle utilisent déjà
# (`ServiceReader`). Le relevé de Voice est écrit dans le dossier d'exécution
# par le harnais, comme `VisualSignalBus.presentation` l'écrirait.

#: Le relevé tel que `PresentationCoordinator.presentation_report` le publie.
LISTENING = {
    "event": "entered", "active": True, "session_id": "pres-cdp", "entered": 1, "entry_failures": 0,
    "left": 0, "last_failure_code": None, "blockers": 0, "blocker_code": None,
    "physical_input_owners": 1, "ambient_deaf": False, "ambient_degraded": False,
    "segments_pending": 0, "analysis_pending": 0, "trigger_latency_s": None, "enrichment_lag_s": None,
    "speculative_in_flight": 0, "speculative_free_explicit_slots": 1, "speculative_staged": 0,
    "attention_live": 0,
}
REPORTS = {
    "listening": LISTENING,
    "deaf": {**LISTENING, "event": "blocked", "blockers": 1, "ambient_deaf": True,
             "blocker_code": "presentation_transcription_unavailable"},
    "refused": {**LISTENING, "event": "refused", "active": False, "session_id": None, "entered": 0,
                "entry_failures": 1, "last_failure_code": "presentation_architecture_unsupported",
                "physical_input_owners": None, "ambient_deaf": None},
    "entry_failed": {**LISTENING, "event": "entry_failed", "active": False, "session_id": None,
                     "entered": 0, "entry_failures": 1, "last_failure_code": "OSError",
                     "physical_input_owners": None, "ambient_deaf": None},
    "left": {**LISTENING, "event": "left", "active": False, "session_id": None, "left": 1},
}
#: « Dans un battement », compté en réponses de `/api/status` que la page a
#: vraiment reçues pendant l'attente : celle qui était peut-être déjà en vol au
#: moment du changement, plus la suivante. L'horloge murale n'est qu'un garde-fou
#: — la page partage ses connexions avec ses autres sondages, et une borne en
#: millisecondes mesurerait la charge de la machine (2 s observées une fois).
ONE_POLL = 2
WALL_CAP_MS = 4000


def _within_one_poll(wait: dict) -> bool:
    return wait["ok"] and wait["polls"] <= ONE_POLL and wait["ms"] <= WALL_CAP_MS


HOST = "document.getElementById('interactionModeHud')"


def _shots(tmp_path: Path) -> Path:
    """Où poser les captures : `JARVIS_BROWSER_SHOTS` pour les garder, sinon le dossier du test."""

    target = Path(os.environ.get("JARVIS_BROWSER_SHOTS") or tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _wait(expr: str, timeout_ms: int = 4000) -> dict:
    return {"a": "wait", "expr": expr, "timeoutMs": timeout_ms}


def _mode_is(mode: str) -> dict:
    return _wait(f"{HOST}.getAttribute('data-im-mode')==={json.dumps(mode)}")


def _presence_is(state: str) -> dict:
    return _wait(f"{HOST}.getAttribute('data-im-presence')==={json.dumps(state)}")


@pytest.fixture
async def served(tmp_path, monkeypatch):
    """Un vrai Control Center sur le bouclage, et son dossier d'exécution."""

    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    view = CoreInteractionModeView(ServiceReader(InteractionModeService(events=RecordingBus())))
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path, interaction_mode_view=view)
    runner = web.AppRunner(control._app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/", runtime
    finally:
        await runner.cleanup()


async def _drive_live(url: str, runtime: Path, plan: list) -> list:
    """Le harnais contre le vrai serveur. Asynchrone : le serveur vit dans cette boucle."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    process = await asyncio.create_subprocess_exec(
        node, str(HARNESS), url, chrome, json.dumps(plan), str(runtime),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(process.communicate(), timeout=180)
    assert process.returncode == 0, err.decode("utf-8", "replace")
    return json.loads(out.decode("utf-8"))


async def test_le_vrai_control_center_bascule_simple_presentation_en_un_battement(served, tmp_path):
    """Le critère d'acceptation, dans un vrai navigateur sur un vrai serveur.

    Un clic sur PRESENTATION, puis le relevé que Voice publie en entrant : la
    séance s'affiche au battement suivant. Puis un changement fait **ailleurs**
    (une écriture directe sur la route, comme le ferait l'outil MCP) ramène
    SIMPLE sans aucun clic : la page le reflète dans un battement, et la
    séance retombe quand Voice publie sa sortie. Une seconde étape, sous
    `prefers-reduced-motion`, vérifie que la marque d'écoute cesse de battre."""

    url, runtime = served
    shots = _shots(tmp_path)
    plan = [
        {"width": 1440, "height": 900, "actions": [
            _mode_is("assistant"),                                                         # 0
            {"a": "eval", "expr": f"{HOST}.getAttribute('data-im-presence')"},             # 1
            {"a": "click", "selector": "#interactionModeButton"},                          # 2
            {"a": "click", "selector": ".im-opt[data-im-mode=presentation]"},              # 3
            _mode_is("presentation"),                                                      # 4
            {"a": "write", "file": ".voice_presentation", "value": REPORTS["listening"]},  # 5
            _presence_is("listening"),                                                     # 6
            {"a": "read"},                                                                 # 7
            {"a": "shot", "path": str(shots / "s03-listening-1440.png")},                  # 8
            {"a": "post", "path": "/api/interaction-mode", "body": {"mode": "assistant"}},  # 9
            _mode_is("assistant"),                                                         # 10
            {"a": "write", "file": ".voice_presentation", "value": REPORTS["left"]},       # 11
            _presence_is("inactive"),                                                      # 12
            {"a": "read"},                                                                 # 13
            {"a": "shot", "path": str(shots / "s03-simple-1440.png")},                     # 14
            {"a": "post", "path": "/api/interaction-mode", "body": {"mode": "presentation"}},  # 15
            {"a": "write", "file": ".voice_presentation", "value": REPORTS["listening"]},  # 16
        ]},
        {"width": 1440, "height": 900, "reducedMotion": True, "actions": [
            _presence_is("listening"),
            {"a": "read"},
        ]},
    ]
    normal, reduced = await _drive_live(url, runtime, plan)
    actions = normal["actions"]

    assert actions[0]["ok"], actions[0]
    # Voice bat mais n'a encore rien publié : aucun relevé, rien n'est dit.
    assert actions[1]["value"] == "none"
    # Le clic : la pastille suit le statut canonique, relu juste après l'écriture.
    assert _within_one_poll(actions[4]), actions[4]
    # Le relevé de Voice arrive par le sondage : dans un battement.
    assert _within_one_poll(actions[6]), actions[6]
    listening = actions[7]["value"]["presence"]
    assert (listening["hidden"], listening["text"], listening["clipped"]) == (False, "Écoute la salle", False)
    assert listening["dot"] == "imListen"
    # Le changement venu d'ailleurs : aucun clic, un battement.
    assert actions[9]["status"] == 200
    assert _within_one_poll(actions[10]), actions[10]
    assert _within_one_poll(actions[12]), actions[12]
    # En SIMPLE, « aucune séance » est l'état ordinaire : il n'est pas affiché.
    assert actions[13]["value"]["presence"]["hidden"] is True
    # Mouvement réduit : la marque d'écoute ne bat plus, le mot reste.
    assert reduced["actions"][0]["ok"], reduced["actions"][0]
    assert reduced["actions"][1]["value"]["presence"]["dot"] == "none"
    assert reduced["actions"][1]["value"]["presence"]["text"] == "Écoute la salle"


@pytest.mark.parametrize("state,width,height,line,code", [
    ("deaf", 1440, 900, "Sourd à la salle", "presentation_transcription_unavailable"),
    ("deaf", 500, 700, "Sourd à la salle", "presentation_transcription_unavailable"),
    ("refused", 1440, 900, "Refusé par la voix", "presentation_architecture_unsupported"),
    ("entry_failed", 1440, 900, "Entrée échouée", "OSError"),
])
async def test_un_releve_force_affiche_sa_ligne_et_son_code(served, tmp_path, state, width, height, line, code):
    """Un `.voice_presentation` forcé donne sa ligne, son code dans `title`, sans rien recouvrir.

    Le contrat de la Slice nommait un relevé `{state: "deaf"}` ; le relevé réel
    n'a pas de clé `state` (le Control Center ne relaie que les clés connues,
    `_PRESENTATION_REPORT_KEYS`). La surdité y est `active` + `ambient_deaf`,
    et c'est cela qui est forcé ici."""

    url, runtime = served
    shot = _shots(tmp_path) / f"s03-{state}-{width}.png"
    plan = [{"width": width, "height": height, "mountPalette": width < 700, "toast": True, "actions": [
        {"a": "post", "path": "/api/interaction-mode", "body": {"mode": "presentation"}},
        _mode_is("presentation"),
        {"a": "write", "file": ".voice_presentation", "value": REPORTS[state]},
        _presence_is(state),
        {"a": "read"},
        {"a": "shot", "path": str(shot)},
    ]}]
    actions = (await _drive_live(url, runtime, plan))[0]["actions"]

    assert actions[0]["status"] == 200
    assert actions[1]["ok"] and actions[3]["ok"], actions
    assert _within_one_poll(actions[3]), actions[3]
    seen = actions[4]["value"]
    presence = seen["presence"]
    assert (presence["hidden"], presence["text"], presence["title"]) == (False, line, code)
    # Le mot se lit en entier : la largeur du bouton le tient.
    assert presence["clipped"] is False, presence
    # La ligne reste dans le bouton, et le bouton ne recouvre aucun voisin.
    button, pres = seen["modeBtn"], seen["pres"]
    assert button["l"] <= pres["l"] and pres["r"] <= button["r"] and pres["b"] <= button["b"], (button, pres)
    for name in ("hint", "toast", "dock", "pills", "palette", "bhHud"):
        assert _overlap(button, seen.get(name)) is None, (name, button, seen.get(name))
    assert shot.is_file()


async def test_clavier_et_lecteur_d_ecran_gardent_leurs_noms(served, tmp_path):
    """Les noms **calculés** par Chrome (arbre d'accessibilité), avec de vraies frappes.

    Le bouton annonce le mode, puis la séance, puis son action ; la flèche ouvre
    le sélecteur et déplace le focus sans rien choisir ; Échap le referme et
    rend le focus au bouton ; la région vivante a dit la surdité."""

    url, runtime = served
    plan = [{"width": 1440, "height": 900, "actions": [
        {"a": "post", "path": "/api/interaction-mode", "body": {"mode": "presentation"}},  # 0
        {"a": "write", "file": ".voice_presentation", "value": REPORTS["deaf"]},          # 1
        _presence_is("deaf"),                                                             # 2
        {"a": "focus", "selector": "#interactionModeButton"},                             # 3
        {"a": "ax", "selector": "#interactionModeButton"},                                # 4
        {"a": "key", "key": "ArrowDown"},                                                 # 5
        {"a": "ax", "selector": ".im-opt[data-im-mode=presentation]"},                    # 6
        {"a": "key", "key": "ArrowDown"},                                                 # 7
        {"a": "eval", "expr": "document.getElementById('interactionModeNote').textContent"},  # 8
        {"a": "shot", "path": str(_shots(tmp_path) / "s03-deaf-chooser-1440.png")},       # 9
        {"a": "key", "key": "Escape"},                                                    # 10
        {"a": "eval", "expr": f"{HOST}.getAttribute('data-im-mode')"},                    # 11
        {"a": "eval", "expr": "document.getElementById('interactionModeAnnounce').textContent"},  # 12
        {"a": "eval", "expr": "document.getElementById('interactionModeButton')"
                              ".getAttribute('aria-expanded')"},                          # 13
    ]}]
    actions = (await _drive_live(url, runtime, plan))[0]["actions"]

    assert actions[0]["status"] == 200 and actions[2]["ok"], actions[:3]
    trigger = actions[4]
    assert trigger["role"] == "button"
    assert trigger["name"].startswith("Mode d’interaction : PRESENTATION.")
    assert "sourde à la salle" in trigger["name"]
    assert trigger["name"].endswith("Ouvrir le choix du mode.")
    # La flèche ouvre et pose le focus sur le mode en vigueur.
    assert actions[5]["focused"] == "presentation"
    option = actions[6]
    assert option["role"] == "menuitemradio"
    assert option["name"] == "PRESENTATION — mode en vigueur"
    assert option["description"], option
    # La flèche suivante déplace le focus sans choisir.
    assert actions[7]["focused"] == "meeting"
    assert actions[8]["value"].endswith("(presentation_transcription_unavailable)")
    # Échap referme et rend le focus ; rien n'a été choisi.
    assert actions[10]["focused"] == "interactionModeButton"
    assert actions[11]["value"] == "presentation"
    assert "sourde à la salle" in actions[12]["value"]
    assert actions[13]["value"] == "false"
