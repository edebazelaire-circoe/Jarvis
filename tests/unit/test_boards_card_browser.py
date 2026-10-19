"""La carte Board du bas-gauche, mesurée dans un vrai navigateur.

Slice 02 de `jarvis-board-ui-wheel-dossier-refactor` : la carte Board a pris la
place (et l'enveloppe) du contrôle de mode d'interaction, retiré avec son
sélecteur. Ce fichier reprend les relevés de l'ancien
`test_interaction_mode_hud_browser.py` qui protégeaient ce coin et ce retour
critique, appliqués à la carte ; ses helpers (`_chrome`, `_served_page`,
`HARNESS`, `_shots`, `_wait`) restent le socle des autres tests navigateur.

**Pourquoi ce fichier existe.** Trois défauts de l'ancien contrôle ont survécu à
des tests qui lisaient la feuille de style comme du texte : la règle y était,
nommait le bon sélecteur, et la cascade faisait le contraire. Ici on ne lit
rien : on compose la page **telle que `ControlCenter.index` la sert**, on la
charge dans Chrome sans tête, on impose une taille, et on relève des rectangles
et des styles **calculés**.

Ce que ce fichier épingle :

- sous 700 px de large, la carte ne recouvre pas la palette Bare Hands (rang 32
  contre 30 : l'outil du bas deviendrait incliquable), ni les infusions, le
  lanceur, le centre d'état ;
- à pleine largeur, la carte est au bord gauche, à 18 px, en bas ;
- la ligne de séance PRESENTATION que Voice rapporte (« Refusé par la voix »,
  séance sourde, entrée ratée) se lit sur la carte, en un battement, sur un
  **vrai** Control Center, avec son code en infobulle ;
- `prefers-reduced-motion` arrête la marque d'écoute et l'ouverture du panneau.

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
def test_sous_700px_la_carte_ne_recouvre_pas_la_palette_bare_hands(tmp_path, width, height):
    """Le défaut que l'ancien bouton de mode avait eu à cette place : 64x46 à 700x600.

    Sous 700 px la colonne Bare Hands devient relative au centre et la hauteur de
    sa palette dépend du nombre d'outils : la carte passe à **droite** de la
    colonne, dont la largeur est fixe. Relevé roue cachée (retour arrière de
    l'orbital UI Slice 04), là où la colonne existe."""

    seen = _drive(tmp_path, [{"width": width, "height": height, "mountPalette": True,
                              "toast": True, "wheelHidden": True}])[0]
    card, palette = seen["card"], seen["palette"]
    assert card, "la carte est bien dessinée"
    assert palette, "la palette est bien montée : sans elle ce test ne prouve rien"
    assert _overlap(card, palette) is None, (card, palette)
    assert card["l"] >= palette["r"], (card, palette)
    for name in ("hint", "toast", "dock", "pills", "bhHud"):
        assert _overlap(card, seen.get(name)) is None, (name, card, seen.get(name))


#: Theme Cosmos, et bandeau GPT-Live affiche avec le Chat ouvert : les deux cas ou la pile du haut (700 px ou moins,
#: S6) etait contree par une autre regle (QA S10, B1 et B2).
COSMOS = "document.documentElement.setAttribute('data-jarvis-theme','cosmos')"
LIVE_AND_CHAT = ("(()=>{document.getElementById('liveBanner').hidden=false;"
                 "document.getElementById('chatTab').click();"
                 "document.getElementById('chatLock').hidden=false;return 'ok'})()")


@pytest.mark.parametrize("theme", [COSMOS, None], ids=["cosmos", "circuit"])
@pytest.mark.parametrize("width", [500, 650])
def test_sous_700px_en_cosmos_la_notification_garde_sa_taille_et_sa_place(tmp_path, width, theme):
    """B1 : une seule notification ne s'étire pas sur toute la hauteur, ni sur la carte Board ni sur le lanceur."""

    seen = _drive(tmp_path, [{"width": width, "height": 700, "setup": theme, "toast": True}])[0]
    toast = seen["toast"]
    assert toast and toast["h"] < 120, toast
    for name in ("card", "chatTab", "dock", "pills"):
        assert _overlap(toast, seen.get(name)) is None, (name, toast, seen.get(name))


def test_sous_700px_bandeau_live_et_chat_ouvert_la_notification_epargne_le_composer(tmp_path):
    """B2 : avec le bandeau GPT-Live, la notification ne se pose ni sur le composer, ni sur la carte Board."""

    seen = _drive(tmp_path, [{"width": 500, "height": 700, "setup": LIVE_AND_CHAT, "toast": True}])[0]
    toast = seen["toast"]
    assert seen["chatPanel"] and seen["liveBanner"], seen
    assert toast and toast["h"] < 120, toast
    for name in ("composer", "chatLock", "chatTab", "card"):
        assert _overlap(toast, seen.get(name)) is None, (name, toast, seen.get(name))


def test_a_pleine_largeur_la_carte_est_au_bord_gauche_sans_rien_recouvrir(tmp_path):
    """La carte reprend l'enveloppe du contrôle retiré : bord gauche à 18 px, en bas ; 236 px au plus sous 1400 px,
    320 px au plus à partir de 1400 px (Slice 08 : le titre n'est plus coupé sur grand écran)."""

    seen = _drive(tmp_path, [{"width": 1440, "height": 900, "mountPalette": True, "toast": True}])[0]
    card = seen["card"]
    assert round(card["l"]) == 18 and card["w"] <= 320, card
    # Le haut-gauche est libre (D05) : la carte est en bas.
    assert card["t"] > 900 / 2, card
    assert seen["wheel"] and not seen.get("palette"), (seen["wheel"], seen.get("palette"))
    for name in ("palette", "bhHud", "wheel", "hint", "toast", "dock", "pills"):
        assert _overlap(card, seen.get(name)) is None, (name, card, seen.get(name))


# ------------------------- la séance PRESENTATION, sur un vrai Control Center
#
# Les tests ci-dessous servent le **vrai** `ControlCenter` sur le bouclage, et la
# page fait son propre sondage à 1 Hz sur le vrai `/api/status`. Core est le vrai
# `InteractionModeService`, branché par le transport factice des tests du plan
# de contrôle (`ServiceReader`). Le relevé de Voice est écrit dans le dossier
# d'exécution par le harnais, comme `VisualSignalBus.presentation` l'écrirait.
#
# Le changement de mode que Core fait sur une bascule de Board (ou une lecture
# du Studio) est simulé par une route **de test**, `POST /__test/board-mode`
# (`BOARD_MODE`), ajoutée à l'application du Control Center servi : elle appelle
# le vrai service en processus, comme `BoardService`. Ce Control Center n'a pas
# de Core Boards : la carte dit « Indisponible », et porte quand même la séance.

#: Route de test : ce que `BoardService` fait à une bascule de Board.
BOARD_MODE = "/__test/board-mode"

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
#: moment du changement, plus la suivante. L'horloge murale n'est qu'un garde-fou.
ONE_POLL = 2
WALL_CAP_MS = 4000


def _within_one_poll(wait: dict) -> bool:
    return wait["ok"] and wait["polls"] <= ONE_POLL and wait["ms"] <= WALL_CAP_MS


HOST = "document.getElementById('boardsHud')"


def _shots(tmp_path: Path) -> Path:
    """Où poser les captures : `JARVIS_BROWSER_SHOTS` pour les garder, sinon le dossier du test."""

    target = Path(os.environ.get("JARVIS_BROWSER_SHOTS") or tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _wait(expr: str, timeout_ms: int = 4000) -> dict:
    return {"a": "wait", "expr": expr, "timeoutMs": timeout_ms}


def _presence_is(state: str) -> dict:
    return _wait(f"{HOST}.getAttribute('data-bd-presence')==={json.dumps(state)}")


@pytest.fixture
async def served(tmp_path, monkeypatch):
    """Un vrai Control Center sur le bouclage, et son dossier d'exécution."""

    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    service = InteractionModeService(events=RecordingBus())
    view = CoreInteractionModeView(ServiceReader(service))
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path, interaction_mode_view=view)

    async def board_mode(request: web.Request) -> web.Response:
        await service.request((await request.json())["mode"], source="board_switch")
        return web.json_response(service.snapshot())

    control._app.router.add_post(BOARD_MODE, board_mode)
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


async def test_la_carte_suit_la_seance_de_la_voix_en_un_battement(served, tmp_path):
    """Le retour critique déplacé, dans un vrai navigateur sur un vrai serveur.

    Le mode suit le type du Board actif (Slice 01b) et rien dans la page ne
    l'écrit : l'ancienne route d'écriture répond 409. Un passage en PRESENTATION
    (côté Core) puis le relevé que Voice publie en entrant : la carte le reflète
    dans un battement. Un retour en SIMPLE fait taire la ligne. Un clic sur la
    carte ouvre le panneau des Boards au-dessus d'elle et ne change ni le mode ni
    la séance. Sous `prefers-reduced-motion`, la marque d'écoute cesse de battre
    et le panneau s'ouvre sans animation."""

    url, runtime = served
    shots = _shots(tmp_path)
    plan = [
        {"width": 1440, "height": 900, "actions": [
            {"a": "eval", "expr": f"{HOST}.getAttribute('data-bd-presence')"},             # 0
            {"a": "post", "path": "/api/interaction-mode", "body": {"mode": "presentation"}},  # 1
            {"a": "post", "path": BOARD_MODE, "body": {"mode": "presentation"}},           # 2
            {"a": "write", "file": ".voice_presentation", "value": REPORTS["listening"]},  # 3
            _presence_is("listening"),                                                     # 4
            {"a": "read"},                                                                 # 5
            {"a": "shot", "path": str(shots / "s02-card-listening-1440.png")},             # 6
            {"a": "click", "selector": "#boardsButton"},                                   # 7
            _wait("!document.getElementById('boardsPanel').hidden"),                       # 8
            {"a": "read"},                                                                 # 9
            {"a": "key", "key": "Escape"},                                                 # 10
            {"a": "post", "path": BOARD_MODE, "body": {"mode": "assistant"}},              # 11
            {"a": "write", "file": ".voice_presentation", "value": REPORTS["left"]},       # 12
            _presence_is("inactive"),                                                      # 13
            {"a": "read"},                                                                 # 14
            {"a": "post", "path": BOARD_MODE, "body": {"mode": "presentation"}},           # 15
            {"a": "write", "file": ".voice_presentation", "value": REPORTS["listening"]},  # 16
        ]},
        {"width": 1440, "height": 900, "reducedMotion": True, "actions": [
            _presence_is("listening"),
            {"a": "click", "selector": "#boardsButton"},
            _wait("!document.getElementById('boardsPanel').hidden"),
            {"a": "read"},
        ]},
    ]
    normal, reduced = await _drive_live(url, runtime, plan)
    actions = normal["actions"]

    # Voice bat mais n'a encore rien publié : aucun relevé, rien n'est dit.
    assert actions[0]["value"] == "none"
    assert actions[1]["status"] == 409, "the mode is never written from the page"
    assert actions[2]["status"] == 200
    assert _within_one_poll(actions[4]), actions[4]
    listening = actions[5]["value"]
    assert (listening["presence"]["hidden"], listening["presence"]["text"], listening["presence"]["clipped"]) == (
        False, "Écoute la salle", False)
    assert listening["presence"]["dot"] == "bdListen"
    # La ligne est dans la carte.
    card, pres = listening["card"], listening["pres"]
    assert card["l"] <= pres["l"] and pres["r"] <= card["r"] and pres["b"] <= card["b"], (card, pres)
    # Le clic ouvre le panneau au-dessus de la carte ; ni le mode ni la séance ne bougent.
    assert actions[8]["ok"], actions[8]
    opened = actions[9]["value"]
    assert (opened["boardsPanel"]["l"], opened["boardsPanel"]["t"]) == (0, 0), opened["boardsPanel"]  # voile plein écran
    assert opened["presence"]["state"] == "listening"
    # Le changement venu d'ailleurs : aucun clic, un battement ; en SIMPLE la ligne se tait.
    assert actions[11]["status"] == 200
    assert _within_one_poll(actions[13]), actions[13]
    assert actions[14]["value"]["presence"]["hidden"] is True
    # Mouvement réduit : la marque d'écoute ne bat plus, le mot reste, le panneau ne glisse pas.
    assert reduced["actions"][0]["ok"], reduced["actions"][0]
    still = reduced["actions"][3]["value"]
    assert still["presence"]["dot"] == "none" and still["presence"]["text"] == "Écoute la salle"
    assert still["motion"]["popAnimation"] == "none", still["motion"]
    assert still["motion"]["buttonTransition"] in ("none", "all 0s ease 0s", ""), still["motion"]


@pytest.mark.parametrize("state,width,height,line,code", [
    ("deaf", 1440, 900, "Sourd à la salle", "presentation_transcription_unavailable"),
    ("deaf", 500, 700, "Sourd à la salle", "presentation_transcription_unavailable"),
    ("refused", 1440, 900, "Refusé par la voix", "presentation_architecture_unsupported"),
    ("refused", 900, 600, "Refusé par la voix", "presentation_architecture_unsupported"),
    ("entry_failed", 1440, 900, "Entrée échouée", "OSError"),
])
async def test_un_releve_force_affiche_sa_ligne_et_son_code(served, tmp_path, state, width, height, line, code):
    """Un `.voice_presentation` forcé donne sa ligne sur la carte, son code dans `title`, sans rien recouvrir."""

    url, runtime = served
    shot = _shots(tmp_path) / f"s02-card-{state}-{width}.png"
    plan = [{"width": width, "height": height, "mountPalette": width < 700, "toast": True, "actions": [
        {"a": "post", "path": BOARD_MODE, "body": {"mode": "presentation"}},
        {"a": "write", "file": ".voice_presentation", "value": REPORTS[state]},
        _presence_is(state),
        {"a": "read"},
        {"a": "shot", "path": str(shot)},
    ]}]
    actions = (await _drive_live(url, runtime, plan))[0]["actions"]

    assert actions[0]["status"] == 200
    assert _within_one_poll(actions[2]), actions[2]
    seen = actions[3]["value"]
    presence = seen["presence"]
    assert (presence["hidden"], presence["text"], presence["title"]) == (False, line, code)
    assert presence["clipped"] is False, presence
    card, pres = seen["card"], seen["pres"]
    assert card["l"] <= pres["l"] and pres["r"] <= card["r"] and pres["b"] <= card["b"], (card, pres)
    for name in ("hint", "toast", "dock", "pills", "palette", "bhHud"):
        assert _overlap(card, seen.get(name)) is None, (name, card, seen.get(name))
    assert shot.is_file()


async def test_clavier_et_lecteur_d_ecran_entendent_la_seance(served, tmp_path):
    """Les noms **calculés** par Chrome (arbre d'accessibilité), avec de vraies frappes.

    Le bouton de la carte annonce ce qu'il montre, puis la séance, puis son
    action ; la flèche ouvre le panneau ; Échap le referme et rend le focus au
    bouton ; la région vivante de la carte a dit la surdité."""

    url, runtime = served
    plan = [{"width": 1440, "height": 900, "actions": [
        {"a": "post", "path": BOARD_MODE, "body": {"mode": "presentation"}},              # 0
        {"a": "write", "file": ".voice_presentation", "value": REPORTS["deaf"]},          # 1
        _presence_is("deaf"),                                                             # 2
        {"a": "focus", "selector": "#boardsButton"},                                      # 3
        {"a": "ax", "selector": "#boardsButton"},                                         # 4
        {"a": "key", "key": "ArrowDown"},                                                 # 5
        _wait("!document.getElementById('boardsPanel').hidden"),                          # 6
        {"a": "key", "key": "Escape"},                                                    # 7
        {"a": "eval", "expr": "document.getElementById('boardsPresenceAnnounce').textContent"},  # 8
        {"a": "eval", "expr": "document.getElementById('boardsButton').getAttribute('aria-expanded')"},  # 9
    ]}]
    actions = (await _drive_live(url, runtime, plan))[0]["actions"]

    assert actions[0]["status"] == 200 and actions[2]["ok"], actions[:3]
    trigger = actions[4]
    assert trigger["role"] == "button"
    # Sans Core Boards, la carte se dit indisponible — et porte quand même la séance.
    assert trigger["name"].startswith("Board indisponible"), trigger
    assert "sourde à la salle" in trigger["name"]
    assert trigger["name"].endswith("Ouvrir la liste des Boards")
    assert actions[6]["ok"], actions[6]
    assert actions[7]["focused"] == "boardsButton"
    assert "sourde à la salle" in actions[8]["value"]
    assert actions[9]["value"] == "false"


async def test_refus_perime_ecarte_et_code_en_infobulle_dans_un_vrai_navigateur(served, tmp_path):
    """Polish Slice 11 (p17, p20), sur la carte, dans Chrome sans tête.

    - p17 : un `refused` laissé par une séance précédente (daté de 30 s avant
      la bascule) ne peint pas de refus ; le refus de **cette** bascule, si ;
    - p20 : la ligne garde le code d'échec en infobulle ; le bord de la carte
      vire au rouge (en plus du mot et du carré : jamais la couleur seule)."""

    url, runtime = served
    stale = {**REPORTS["refused"], "last_failure_code": "presentation_architecture_unsupported"}
    plan = [{"width": 1440, "height": 900, "actions": [
        _wait(f"{HOST}.getAttribute('data-bd-presence')==='none'"),                         # 0
        {"a": "write", "file": ".voice_presentation", "value": stale, "ageS": 30},          # 1
        {"a": "post", "path": BOARD_MODE, "body": {"mode": "presentation"}},                # 2
        _presence_is("inactive"),                                                           # 3
        {"a": "read"},                                                                      # 4
        {"a": "write", "file": ".voice_presentation", "value": REPORTS["refused"]},         # 5
        _presence_is("refused"),                                                            # 6
        {"a": "read"},                                                                      # 7
        {"a": "shot", "path": str(_shots(tmp_path) / "s02-card-refused-1440.png")},         # 8
    ]}]
    actions = (await _drive_live(url, runtime, plan))[0]["actions"]

    assert actions[2]["status"] == 200 and actions[3]["ok"], actions[:4]
    stale_seen = actions[4]["value"]
    assert (stale_seen["presence"]["state"], stale_seen["presence"]["text"]) == ("inactive", "Séance inactive")
    assert "refus" not in stale_seen["button"]["label"].lower()
    assert actions[6]["ok"], actions[6]
    refused = actions[7]["value"]
    assert refused["presence"]["title"] == "presentation_architecture_unsupported"
    assert "refusé" in refused["button"]["label"]
    assert refused["button"]["border"] != stale_seen["button"]["border"], (refused["button"], stale_seen["button"])
