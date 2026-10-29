"""Centre d'état du bas, mesuré dans un vrai Chrome sans tête (orbital UI, Slice 06).

Contrat : `docs/control-center-shell.md` › *Status centre* ; architecture
résolue du handoff `jarvis-board-orbital-ui-workspace-rail`, D8 et §7 (D9).
La page est celle que `ControlCenter.index` sert ; seul `fetch` est un double
(`_status_centre_browser.mjs`) : statut (pastilles, scène allumée), alertes et
acquittement, captures, scène (instantané, patchs, commandes), rail. Ce que ce
fichier épingle :

- les pastilles disent les mêmes catégories et les mêmes comptes que le résumé
  `background` du statut, dans l'ordre du registre, et ouvrent le même
  popover, dont l'acquittement efface la catégorie ;
- chaque pastille porte une icône SVG, un compte et un nom accessible : jamais
  la couleur seule, jamais un émoji ;
- un enregistrement se lit en haut à gauche (Slice 04 de la refonte roue/dossier), loin
  des pastilles, distinct d'un compteur, et s'arrête d'un geste ;
- aucune commande du centre d'état ne recouvre la carte Board (bas-gauche
  depuis la Slice 02 de jarvis-board-ui-wheel-dossier-refactor), le rail,
  l'onglet Chat ou le plateau de dépôt, dans les deux thèmes, à 1440×900,
  1280×720, 900×600 et 600×800 ; un panneau Chat ouvert ne le couvre pas ;
- plus de capsule « F9 · DÉMARRER » ni de ligne d'état : la touche se lit dans le
  sous-menu JARVIS de la roue (Slice 04), et reste la touche de Voice ;
- l'œil permanent est **absent** du centre d'état (D06) ; sa mécanique vit
  dans la roue › Sélection › « Masqués (N) » (Slice 06 de la
  refonte roue/dossier) : « Voir en fantômes » coché ou non, fantômes sans
  écriture, la liste des masqués, « Réafficher » = un seul `set_visibility`,
  « Tout réafficher » = un seul `patch_selection` ; un réglage `showHidden`
  resté allumé dessine ses fantômes, puisque Sélection peut les éteindre.

Preuves visuelles : `JARVIS_S06_EVIDENCE_DIR=<dossier>` y écrit les captures.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.explicit_address import ExplicitAddressSource
from jarvis.runtime.voice_v2 import activation_source_for_label
from tests.unit.test_boards_card_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_status_centre_browser.mjs"
VIEWPORTS = ((1440, 900), (1280, 720), (900, 600), (600, 800))
THEMES = ("circuit-board", "cosmos")
EVIDENCE = os.environ.get("JARVIS_S06_EVIDENCE_DIR")

#: Rectangles calculés de ce que le centre d'état et ses voisins occupent.
BOXES = r"""(()=>{
  const box=el=>{if(!el||el.hidden||el.closest('[hidden]'))return null;const cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden')return null;const r=el.getBoundingClientRect();
    if(!(r.width>0&&r.height>0))return null;return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}};
  const q=s=>document.querySelector(s);
  const items=[...document.querySelectorAll('#recIndicators .ri-chip, #bgPills .bgpill, #hiddenEye')].map(el=>({id:el.id||el.dataset.bgCat||el.dataset.riKey,box:box(el)})).filter(i=>i.box);
  return {vw:innerWidth,vh:innerHeight,items,eyeHost:!!q('#hiddenEye'),
    card:box(q('#boardsButton')),chatTab:box(q('#chatTab')),rail:box(q('#presentationRail')),
    railTab:box(q('#presentationRailTab')),railDock:box(q('#railDock')),tray:box(q('#boardDropTray')),chatPanel:box(q('#chatPanel')),
    wheel:box(q('#toolWheel .tw-anchor')),scStatus:box(q('#sceneLayer>.sc-status')),toasts:box(q('#toasts .toast')),
    dock:box(q('.dock')),liveBanner:box(q('#liveBanner')),
    overflowX:document.documentElement.scrollWidth>innerWidth,
    z:{pills:getComputedStyle(q('#bgPills')).zIndex,rec:getComputedStyle(q('#recIndicators')).zIndex},
    theme:document.documentElement.getAttribute('data-jarvis-theme')||''};
})()"""

#: La roue › Sélection (Slice 06) : ouvrir l'arbre, puis « Masqués (N) ».
OPEN_SELECTION = [["click", "wheelOpen", "#toolWheel .tw-anchor", 400],
                  ["click", "selectionTree", "#toolWheel [data-tw-slot=selection] .tw-dot", 500]]
OPEN_HIDDEN = [*OPEN_SELECTION, ["click", "hiddenRow", "#toolWheel .tw-item[data-tw-item=hidden]", 500]]
#: « Voir en fantômes » : un choix, qui referme la roue.
TOGGLE_GHOSTS = [*OPEN_HIDDEN, ["click", "ghosts", "#toolWheel .tw-item[data-tw-item=ghosts]", 900]]
#: Les lignes du sous-menu ouvert.
ROWS = r"""[...document.querySelectorAll('#toolWheel .tw-item')].map(b=>({id:b.dataset.twItem||null,
  text:(b.querySelector('.tw-text')||{}).textContent||'',checked:b.getAttribute('aria-checked'),
  disabled:b.getAttribute('aria-disabled'),kind:b.dataset.twKind||null}))"""

#: Un plateau de dépôt réel (son hôte, sa feuille) avec un envoi, pour le mesurer.
TRAY = r"""(()=>{const t=document.getElementById('boardDropTray');t.hidden=false;
  const ul=document.getElementById('boardDropList');ul.textContent='';const li=document.createElement('li');
  li.className='board-drop-item';li.dataset.status='uploading';li.textContent='rapport.pdf — envoi 40 %';ul.appendChild(li);return 1})()"""

PILLS = r"""[...document.querySelectorAll('#bgPills .bgpill')].map(p=>({cat:p.dataset.bgCat,label:p.getAttribute('aria-label'),
  title:p.title,count:(p.querySelector('.bgn')||{}).textContent||null,text:p.textContent,svg:!!p.querySelector('svg'),
  paths:[...p.querySelectorAll('svg path')].map(x=>x.getAttribute('d')).join('|'),w:p.getBoundingClientRect().width,
  h:p.getBoundingClientRect().height,cls:p.className,expanded:p.getAttribute('aria-expanded')}))"""

SCREEN_CAPTURE = {"capture_id": "jcap_s", "channel": "screen", "mode": "continuous", "state": "active",
                  "device": "default", "age_s": 65, "stop_requested_at": None}


def _drive(tmp_path: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), chrome, "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=420, check=False)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout)


def _shot(name: str) -> list:
    if not EVIDENCE:
        return []
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot", str(Path(EVIDENCE) / f"{name}.png"), 100]]


def _overlap(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return min(a["r"], b["r"]) - max(a["l"], b["l"]) > 0.5 and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 0.5


def _no_errors(step: dict) -> None:
    bad = [line for line in step["console"] if line["type"] in ("exception", "error")]
    assert bad == [], bad


# ------------------------------------------------------------------ pastilles


def test_same_counts_and_categories_as_status_summary(tmp_path):
    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "actions": [["eval", "pills", PILLS, 100]]},
        {"width": 1440, "height": 900, "seed": {"counts": {"failed": 0, "attention": 12, "done": 0, "said": 2}},
         "actions": [["eval", "pills", PILLS, 100]]},
    ])
    first, second = steps[0]["results"]["pills"], steps[1]["results"]["pills"]
    # Les quatre catégories canoniques, dans l'ordre du registre, avec le compte du résumé.
    assert [(p["cat"], p["count"]) for p in first] == [("failed", "2"), ("attention", "1"), ("done", "3"), ("said", "1")]
    assert [p["label"] for p in first] == ["Arrière-plan · 2 échecs", "Arrière-plan · 1 point à vérifier",
                                           "Arrière-plan · 3 tâches terminées", "Arrière-plan · 1 résultat non dit"]
    # Une catégorie à zéro n'a pas de pastille ; au-delà de 9, « 9+ » dans le badge, le compte exact dans le nom.
    assert [(p["cat"], p["count"]) for p in second] == [("attention", "9+"), ("said", "2")]
    assert second[0]["label"] == "Arrière-plan · 12 points à vérifier"
    for step in steps:
        _no_errors(step)


def test_click_opens_same_popover_and_ack_clears(tmp_path):
    pop = r"""(()=>{const p=document.getElementById('bgPop');const r=p.getBoundingClientRect();
      const pill=document.querySelector('#bgPills [data-bg-cat="attention"]');const pr=pill&&pill.getBoundingClientRect();
      return {open:!p.hidden,cls:p.className,title:(p.querySelector('header strong')||{}).textContent||null,
        items:[...p.querySelectorAll('.bgitem .emsg')].map(e=>e.textContent),svg:p.querySelectorAll('.bgitem .ico svg').length,
        rect:{l:r.left,t:r.top,r:r.right,b:r.bottom},pill:pr?{l:pr.left,t:pr.top,r:pr.right,b:pr.bottom}:null,
        expanded:pill?pill.getAttribute('aria-expanded'):null,focus:document.activeElement&&document.activeElement.className}})()"""
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "actions": [
        ["click", "open", '#bgPills [data-bg-cat="attention"]', 900],
        ["eval", "pop", pop, 100],
        *_shot("status-centre-popover-1280x720"),
        ["click", "ack", "#bgPop [data-bg-ack]", 1800],
        ["eval", "after", PILLS, 100],
        ["eval", "popHidden", "document.getElementById('bgPop').hidden", 100],
    ]}])[0]
    seen = step["results"]["pop"]
    assert seen["open"] and "warn" in seen["cls"] and seen["title"] == "1 point à vérifier"
    assert seen["items"] == ["Point à vérifier : diapositive 3 1"] and seen["svg"] == 1
    assert seen["expanded"] == "true"
    # Le popover s'ouvre AU-DESSUS de la pastille (le centre d'état est en bas), à l'écran.
    assert seen["rect"]["b"] <= seen["pill"]["t"] and seen["rect"]["t"] >= 0
    assert seen["rect"]["l"] >= 0 and seen["rect"]["r"] <= 1280
    # L'acquittement : la même route, cette catégorie seulement, puis la pastille part.
    assert [a["category"] for a in step["acks"]] == ["attention"]
    assert step["results"]["popHidden"] is True
    assert [p["cat"] for p in step["results"]["after"]] == ["failed", "done", "said"]
    _no_errors(step)


#: Notifications telles que `background_events._present` les écrit (retour du 23/10/2026).
NOTICES = [
    {"seq": 3, "ts": "2026-10-23T08:12:00+00:00", "category": "failed", "kind": "core.brain.turn_failed",
     "label": "le backend cerveau a rendu un échec", "title": "Le cerveau n'a pas pu répondre",
     "family": "brain", "issue": "unavailable", "detail": "Claude indisponible",
     "body": "Le service Claude n'a pas répondu (réseau, quota ou panne du fournisseur).",
     "facts": [{"label": "Erreur", "value": "claude_unavailable"}], "task_id": "", "unread": True},
    {"seq": 2, "ts": "2026-10-23T08:02:00+00:00", "category": "failed", "kind": "agent.subagent.finished",
     "label": "Sous-agent tué après 35 s : [code] Scène Réunion", "title": "Scène Réunion",
     "family": "subagent", "issue": "stopped", "detail": "Arrêté de force en 35 s · Opus 5.5 · code",
     "body": "", "facts": [{"label": "Modèle", "value": "Opus 5.5"}], "task_id": "a62", "unread": True},
    {"seq": 1, "ts": "2026-10-23T07:50:00+00:00", "category": "said", "kind": "voice.speech.abandoned",
     "label": "Réponse du cerveau soldée sans avoir été dite", "title": "Réponse non prononcée",
     "family": "speech", "issue": "stale", "detail": "devenue obsolète avant d'être dite",
     "body": "C'est lancé, Monsieur. Un agent Opus s'en occupe.", "facts": [], "task_id": "", "unread": True},
]


def test_a_notification_row_says_what_happened_and_opens_its_detail(tmp_path):
    """Retour du 23/10/2026 : un titre en clair, une icône du type, et un détail au clic."""
    rows = r"""[...document.querySelectorAll('#bgPop .bgitem')].map(b=>({title:b.querySelector('.emsg').textContent,
      meta:b.querySelector('.emeta').textContent,svg:b.querySelectorAll('.ico svg').length}))"""
    detail = r"""(()=>{const d=document.getElementById('ntDetail'),back=document.getElementById('ntDetailBack');
      return {open:!back.hidden,cls:d.className,title:(d.querySelector('h2')||{}).textContent||null,
        kind:(d.querySelector('.ntkind')||{}).textContent||'',body:[...d.querySelectorAll('.nttext')].map(e=>e.textContent),
        facts:[...d.querySelectorAll('.ntmain > section dt')].map(e=>e.textContent),
        focusInside:d.contains(document.activeElement),z:getComputedStyle(back).zIndex}})()"""
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "seed": {
        "counts": {"failed": 2, "attention": 0, "done": 0, "said": 1}, "seq": 3, "events": NOTICES}, "actions": [
        ["click", "open", '#bgPills [data-bg-cat="failed"]', 900],
        ["eval", "rows", rows, 100],
        *_shot("notifications-popover-1280x720"),
        ["click", "row", "#bgPop .bgitem", 700],
        ["eval", "detail", detail, 100],
        *_shot("notifications-detail-1280x720"),
        ["key", "escape", "Escape", 400],
        ["eval", "closed", "document.getElementById('ntDetailBack').hidden", 100],
    ]}])[0]
    assert step["results"]["rows"] == [
        {"title": "Le cerveau n'a pas pu répondre", "meta": step["results"]["rows"][0]["meta"], "svg": 1},
        {"title": "Scène Réunion", "meta": step["results"]["rows"][1]["meta"], "svg": 1}]
    assert step["results"]["rows"][0]["meta"].endswith(" · Claude indisponible")
    seen = step["results"]["detail"]
    assert seen["open"] and "bad" in seen["cls"] and seen["title"] == "Le cerveau n'a pas pu répondre"
    assert "Échec" in seen["kind"] and "Cerveau" in seen["kind"] and "Service indisponible" in seen["kind"]
    assert seen["body"] == ["Le service Claude n'a pas répondu (réseau, quota ou panne du fournisseur)."]
    assert seen["facts"] == ["Erreur"] and seen["focusInside"] and seen["z"] == "84"
    # Ouvrir le détail marque cette notification vue, elle seule.
    assert {"event": 3} in step["acks"]
    assert step["results"]["closed"] is True
    _no_errors(step)


def test_icons_have_label_and_count_not_colour_only(tmp_path):
    eye = r"""(()=>{const e=document.getElementById('hiddenEye');if(!e)return null;const r=e.getBoundingClientRect();
      return {label:e.getAttribute('aria-label'),title:e.title,pressed:e.getAttribute('aria-pressed'),w:r.width,h:r.height,
        svgs:e.querySelectorAll('svg').length,text:e.textContent.trim()}})()"""
    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "theme": theme, "actions": [["eval", "pills", PILLS, 100], ["eval", "eye", eye, 100]]}
        for theme in THEMES
    ])
    for step in steps:
        pills = step["results"]["pills"]
        paths = set()
        for pill in pills:
            assert pill["svg"], pill
            # Le texte visible n'est que le compte (aucun émoji) ; le nom et l'infobulle disent le reste.
            assert pill["text"] == pill["count"] and pill["count"].rstrip("+").isdigit(), pill
            assert pill["label"] == pill["title"] and pill["count"].rstrip("+") in pill["label"]
            assert pill["w"] >= 32 and pill["h"] >= 32, pill
            paths.add(pill["paths"])
        assert len(paths) == len(pills), "chaque catégorie a sa forme, pas seulement sa couleur"
        # D06 (Slice 02 de jarvis-board-ui-wheel-dossier-refactor) : plus d'œil permanent au centre d'état.
        assert step["results"]["eye"] is None
        _no_errors(step)


def test_recording_indicator_distinct_from_counters_and_stops(tmp_path):
    chip = r"""(()=>{const c=document.querySelector('#recIndicators .ri-chip');if(!c)return null;const r=c.getBoundingClientRect();
      const pills=document.getElementById('bgPills').getBoundingClientRect();
      const rail=document.getElementById('presentationRail');
      return {railLeft:rail&&!rail.hidden?rail.getBoundingClientRect().left:null,label:c.getAttribute('aria-label'),text:c.textContent.replace(/\s+/g,' ').trim(),cls:c.className,state:c.dataset.riState,
        bgpill:c.classList.contains('bgpill'),left:r.left,right:r.right,top:r.top,bottom:r.bottom,pillsTop:pills.top,inCentre:!!c.closest('#statusCentre'),
        desc:c.getAttribute('aria-describedby')?document.getElementById(c.getAttribute('aria-describedby')).textContent:null}})()"""
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": {"captures": [SCREEN_CAPTURE]}, "actions": [
        ["eval", "chip", chip, 1200],
        ["eval", "chip2", chip, 100],
        *_shot("status-centre-recording-1440x900"),
        ["click", "stop", "#recIndicators .ri-chip", 2500],
        ["eval", "after", chip, 100],
        ["eval", "pills", PILLS, 100],
    ]}])[0]
    first, second = step["results"]["chip"], step["results"]["chip2"]
    assert first and not first["inCentre"] and not first["bgpill"]
    assert first["state"] == "active" and "REC" in first["text"]
    # Slice 04 de la refonte roue/dossier (docs/06 › E), puis refonte du 2026-10-29 : en haut à DROITE (le lanceur est en haut à
    # gauche), loin des pastilles du bas ; un enregistrement ne se lit pas comme un compteur.
    assert round(1440 - first["right"]) == 18 + (round(1440 - first["railLeft"]) if first["railLeft"] else 0) and round(first["top"]) == 18 and first["bottom"] < first["pillsTop"] / 2
    # Le nom ne bouge pas avec le temps ; la durée est la description (et ce que l'œil lit).
    assert first["label"] == second["label"] and not any(ch.isdigit() for ch in first["label"])
    assert first["desc"].startswith("en cours depuis 1:0")
    # L'activer arrête **cette** capture ; elle part, les pastilles restent.
    assert "POST /api/captures/jcap_s/stop" in step["calls"]
    assert step["results"]["after"] is None
    assert [p["cat"] for p in step["results"]["pills"]] == ["failed", "attention", "done", "said"]
    _no_errors(step)


# ------------------------------------------------------------------ géométrie


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("status-centre")
    plan = []
    for theme in THEMES:
        for width, height in VIEWPORTS:
            name = f"status-centre-{theme}-{width}x{height}"
            plan.append({"width": width, "height": height, "theme": theme, "seed": {"captures": [SCREEN_CAPTURE]},
                         "actions": [["eval", "tray", TRAY, 300], ["eval", "boxes", BOXES, 100], *_shot(name)]})
    steps = _drive(tmp, plan)
    out = {}
    index = 0
    for theme in THEMES:
        for size in VIEWPORTS:
            out[(theme, size)] = steps[index]
            index += 1
    return out


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", VIEWPORTS)
def test_no_overlap_with_board_card_rail_chat_tab_tray_at_1440_1280_900_600(measured, theme, size):
    step = measured[(theme, size)]
    seen = step["results"]["boxes"]
    assert seen["theme"] == ("cosmos" if theme == "cosmos" else seen["theme"])
    every = seen["items"]
    ids = [i["id"] for i in every]
    # L'enregistrement (haut-droite depuis le 2026-10-29), quatre pastilles ; au rang 40. Plus d'œil (D06).
    assert ids == ["jcap_s", "failed", "attention", "done", "said"], ids
    rec = every[0]["box"]
    gutter = 18 if seen["vw"] > 700 else 10
    beside = (seen["vw"] - seen["rail"]["l"]) if seen["rail"] and seen["vw"] > 700 else 0
    assert round(seen["vw"] - rec["r"]) == gutter + beside and round(rec["t"]) == gutter, (rec, "à gauche de la bande du rail ouverte")
    for name in ("card", "chatTab", "rail", "railTab", "railDock", "wheel", "dock", "tray", "scStatus"):
        assert not _overlap(rec, seen[name]), ("enregistrement", name, rec, seen[name])
    # Le centre d'état du bas ne tient plus que les pastilles.
    items = every[1:]
    assert seen["eyeHost"] is False
    assert seen["z"] == {"pills": "40", "rec": "40"}
    others = {name: seen[name] for name in ("card", "chatTab", "rail", "railTab", "railDock", "wheel")}
    assert others["card"] and others["chatTab"] and others["railTab"] and others["railDock"], others
    for item in items:
        box = item["box"]
        assert 0 <= box["l"] and box["r"] <= seen["vw"] and box["b"] <= seen["vh"], item
        for name, other in others.items():
            assert not _overlap(box, other), (item["id"], name, box, other)
        # Le plateau de dépôt est au-dessus de la rangée (ou en haut, sur un écran étroit).
        assert not _overlap(box, seen["tray"]), (item["id"], box, seen["tray"])
    tray = seen["tray"]
    assert tray, "le plateau est mesuré"
    top = min(item["box"]["t"] for item in items)
    assert tray["b"] <= top or tray["t"] < 200
    # Les pastilles sont sur une seule rangée centrée, en bas.
    rows = {round(item["box"]["t"]) for item in items if item["id"] != "jcap_s"}
    assert len(rows) == 1, rows
    assert not seen["overflowX"]
    _no_errors(step)


@pytest.mark.parametrize("size", VIEWPORTS)
def test_status_centre_clears_open_chat_panel(tmp_path, size):
    width, height = size
    step = _drive(tmp_path, [{"width": width, "height": height, "seed": {"captures": [SCREEN_CAPTURE]}, "actions": [
        ["click", "open", "#chatTab", 900],
        ["eval", "boxes", BOXES, 100],
        *_shot(f"status-centre-chat-open-{width}x{height}"),
    ]}])[0]
    seen = step["results"]["boxes"]
    panel = seen["chatPanel"]
    assert panel, "le panneau Chat est ouvert"
    items = seen["items"]
    assert "hiddenEye" not in [i["id"] for i in items] and len(items) == 5, items
    for item in items:
        assert not _overlap(item["box"], panel), (item["id"], item["box"], panel)
    if width >= 1100:
        # Assez de place : la rangée se recentre dans l'espace libre, à gauche du panneau.
        assert max(item["box"]["r"] for item in items) < panel["l"]
    _no_errors(step)


def test_no_voicehint_and_f9_still_wakes(tmp_path):
    """Ni capsule (orbital-ui S06) ni ligne d'état (Slice 02, D05) ; depuis la Slice 04 de la refonte, la touche
    se lit dans le sous-menu JARVIS de la roue (`test_jarvis_wheel_browser.py`), plus dans un `#wakeHint` caché."""
    state = r"""(()=>({hint:!!document.getElementById('voiceHint')||!!document.querySelector('.voicehint'),
        stateLine:!!document.querySelector('.topbar,.state'),wakeHint:!!document.getElementById('wakeHint'),
        text:window.JarvisRuntimeWheel.wakeHint()}))()"""
    steps = _drive(tmp_path, [
        {"width": 1280, "height": 720, "actions": [["eval", "state", state, 100]]},
        {"width": 1280, "height": 720, "seed": {"wakeKey": "f10"}, "actions": [["eval", "state", state, 100]]},
    ])
    assert steps[0]["results"]["state"] == {"hint": False, "stateLine": False, "wakeHint": False, "text": "F9 · DÉMARRER"}
    # Le texte suit la touche réglée, à chaque statut.
    assert steps[1]["results"]["state"]["text"] == "F10 · DÉMARRER"
    # La touche elle-même est le raccourci global de Voice : la page n'y est pour rien, et rien n'a bougé.
    assert activation_source_for_label("f9") is ExplicitAddressSource.MANUAL_KEY
    assert activation_source_for_label("F10", manual_key="f10") is ExplicitAddressSource.MANUAL_KEY


# ------------------------------------------------------------------ les masqués
#
# Slice 02 de jarvis-board-ui-wheel-dossier-refactor (D06) : la page ne déclare plus
# l'œil. Slice 06 : sa mécanique vit dans la roue › Sélection › « Masqués (N) ».


def test_a_stored_ghost_view_draws_ghosts_that_selection_can_turn_off(tmp_path):
    """Un navigateur qui avait allumé la vue garde `showHidden: true` : la roue › Sélection peut les
    éteindre (Slice 06), donc les fantômes se dessinent ; aucun œil ne revient dans la coque."""
    ghosts = r"""[...document.querySelectorAll('#sceneLayer [data-object-id]')].map(n=>({id:n.dataset.objectId,
      ghost:n.classList.contains('sc-ghost')}))"""
    stored = "(()=>{try{return JSON.parse(localStorage.getItem('jarvis.scene.view')||'null')}catch(_){return 'refused'}})()"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "storage": {"version": 1, "view": {"showHidden": True}},
                              "actions": [["eval", "nodes", ghosts, 1500], ["eval", "stored", stored, 100],
                                          ["eval", "eye", "!!document.getElementById('hiddenEye')", 50],
                                          *OPEN_HIDDEN, ["eval", "rows", ROWS, 100]]}])[0]
    r = step["results"]
    assert r["eye"] is False
    nodes = {n["id"]: n["ghost"] for n in r["nodes"]}
    assert nodes == {"jobj_star": False, "jobj_hidden": True, "jobj_hidden_win": True}, r["nodes"]
    assert r["stored"]["view"]["showHidden"] is True
    assert r["rows"][0] == {"id": "ghosts", "text": "Voir en fantômes", "checked": "true", "disabled": None, "kind": None}
    assert not any("scene.hidden_view_withheld" in line["text"] for line in step["console"]), step["console"]
    _no_errors(step)


def test_selection_hidden_row_counts_toggles_ghosts_and_lists_hidden(tmp_path):
    """Slice 06 : « Masqués (3) » dans Sélection (jamais dans la coque) ; « Voir en
    fantômes » allume la vue de ce navigateur sans rien écrire ; la liste nomme les masqués ; un fantôme
    se réaffiche d'un seul `set_visibility` ; le compte suit (2) et la vue s'éteint du même endroit."""
    ghosts = r"""[...document.querySelectorAll('#sceneLayer [data-object-id]')].map(n=>({id:n.dataset.objectId,
      ghost:n.classList.contains('sc-ghost'),label:n.getAttribute('aria-label')}))"""
    menu = r"""(()=>{const m=document.getElementById('ctxMenu');return m.hidden?null:{title:(m.querySelector('.mhead')||{}).textContent,
      items:[...m.querySelectorAll('button[role=menuitem]')].map(b=>b.textContent)}})()"""
    stored = "(()=>{try{return JSON.parse(localStorage.getItem('jarvis.scene.view')||'null')}catch(_){return 'refused'}})()"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        *OPEN_SELECTION,
        ["eval", "first", ROWS, 100],
        ["click", "hiddenRow", "#toolWheel .tw-item[data-tw-item=hidden]", 500],
        ["eval", "list", ROWS, 100],
        ["eval", "nodesBefore", ghosts, 100],
        ["click", "ghosts", "#toolWheel .tw-item[data-tw-item=ghosts]", 900],
        ["eval", "nodesOn", ghosts, 100],
        ["eval", "stored", stored, 100],
        ["eval", "eye", "!!document.getElementById('hiddenEye')", 50],
        ["rclick", "ghostMenu", '#sceneLayer [data-object-id="jobj_hidden_win"]', 500],
        ["eval", "ghostList", menu, 100],
        ["eval", "sentBefore", "window.__sc.bodies.filter(b=>b.path==='/api/scene/commands').length", 100],
        ["click", "reveal", '#ctxMenu [data-act="reveal"]', 2500],
        ["eval", "nodesAfter", ghosts, 100],
        *OPEN_HIDDEN,
        ["eval", "after", ROWS, 100],
        ["click", "ghostsOff", "#toolWheel .tw-item[data-tw-item=ghosts]", 900],
        ["eval", "nodesOff", ghosts, 100],
    ]}])[0]
    r = step["results"]
    first = [row for row in r["first"] if row["id"] not in ("mouse", "bare_hands")]
    # Sans sélection : un fait, puis le compte des masqués (une entrée qui ouvre sa liste).
    assert [row["id"] for row in first] == ["selection-none", "hidden"], first
    assert first[1]["text"] == "Masqués (3)"
    assert [row["text"] for row in r["list"]] == ["Voir en fantômes", "Tout réafficher (3)", "Réafficher « Recherche masquée »",
                                                  "Réafficher « Rapport masqué »", "Réafficher « Sans place »"]
    assert r["list"][0]["checked"] == "false"
    assert [n["id"] for n in r["nodesBefore"]] == ["jobj_star"]
    # Allumé : deux fantômes (le masqué sans place n'en a pas), dits « masqué ».
    ghosts_on = {n["id"]: n for n in r["nodesOn"]}
    assert set(ghosts_on) == {"jobj_star", "jobj_hidden", "jobj_hidden_win"}
    assert ghosts_on["jobj_hidden"]["ghost"] and ghosts_on["jobj_hidden_win"]["ghost"] and not ghosts_on["jobj_star"]["ghost"]
    assert ghosts_on["jobj_hidden_win"]["label"].endswith("masqué")
    # Une décision de vue de ce navigateur : stockée là, rien d'envoyé à Core, aucun œil dans la coque.
    assert r["stored"]["view"]["showHidden"] is True and r["eye"] is False
    # Un fantôme : « Réafficher » seulement, et c'est un seul `set_visibility visible`.
    assert r["ghostList"]["items"] == ["Réafficher"]
    assert r["sentBefore"] == 0
    sent = [b["body"] for b in step["bodies"] if b["path"] == "/api/scene/commands"]
    assert [b for b in sent if b["op"] == "set_visibility"] == [
        {"schema_version": 1, "op": "set_visibility", "object_id": "jobj_hidden_win", "visibility": "visible"}]
    assert {b["op"] for b in sent} <= {"set_visibility", "set_geometry"}
    after = {n["id"]: n for n in r["nodesAfter"]}
    assert after["jobj_hidden_win"]["ghost"] is False
    # Le compte a baissé ; la vue est cochée, et s'éteint du même endroit.
    assert r["after"][0]["checked"] == "true" and r["after"][1]["text"] == "Tout réafficher (2)"
    assert sorted(n["id"] for n in r["nodesOff"]) == ["jobj_hidden_win", "jobj_star"]
    _no_errors(step)


def test_show_all_hidden_is_one_atomic_patch_selection(tmp_path):
    """« Tout réafficher (3) » : un seul `patch_selection {visibility: visible}` sur les trois, la même
    opération que l'outil du cerveau `scene_update_many` (Slice 06)."""
    count = "document.querySelectorAll('#sceneLayer [data-object-id]').length"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        *OPEN_HIDDEN, ["click", "showAll", "#toolWheel .tw-item[data-tw-item=show-all]", 2000],
        ["eval", "drawn", count, 100], *OPEN_SELECTION, ["eval", "rows", ROWS, 100]]}])[0]
    r = step["results"]
    sent = [b["body"] for b in step["bodies"] if b["path"] == "/api/scene/commands" and b["body"]["op"] != "set_geometry"]
    assert sent == [{"schema_version": 1, "op": "patch_selection",
                     "selection": {"ids": ["jobj_hidden", "jobj_hidden_win", "jobj_nowhere"]},
                     "changes": {"visibility": "visible"}}], sent
    assert r["drawn"] == 4
    # Plus aucun masqué (le premier réaffiché a reçu le focus, donc la sélection : peu importe ici).
    assert "hidden-none" in [row["id"] for row in r["rows"]] and "hidden" not in [row["id"] for row in r["rows"]]
    _no_errors(step)


def test_selection_says_no_hidden_object_and_offers_nothing_without_scene(tmp_path):
    visible_only = [{"schema_version": 1, "object_id": "jobj_star", "kind": "agent", "category": "agent", "exec_state": "running",
                     "representation": "point", "geometry": {"x": -60, "y": -30, "w": 6, "h": 6}, "layer": 100, "order": 0,
                     "visibility": "visible", "disposition": "active", "constraints": {"placed_by": "user", "pinned_by_user": False},
                     "origin": "runtime", "work_ref": None, "payload": {"title": "Analyse", "summary": "", "items": []}}]
    steps = _drive(tmp_path, [
        {"width": 1280, "height": 720, "seed": {"objects": visible_only}, "actions": [
            *OPEN_SELECTION, ["eval", "rows", ROWS, 100],
            ["click", "inert", "#toolWheel .tw-item[data-tw-item=hidden-none]", 400],
            ["eval", "open", "JarvisToolWheel.isOpen()", 50]]},
        {"width": 1280, "height": 720, "seed": {"sceneOn": False}, "actions": [*OPEN_SELECTION, ["eval", "rows", ROWS, 100]]},
    ])
    rows = {row["id"]: row for row in steps[0]["results"]["rows"]}
    # Aucun masqué : une ligne d'état (lisible, focalisable, elle n'agit pas et ne ferme pas la roue).
    assert rows["hidden-none"] == {"id": "hidden-none", "text": "Aucun objet masqué", "checked": None,
                                   "disabled": "true", "kind": "status"}
    assert steps[0]["results"]["open"] is True
    # Scène éteinte : Sélection ne propose que la méthode (Souris / Bare Hands).
    assert [row["id"] for row in steps[1]["results"]["rows"]] == ["mouse", "bare_hands"]
    for step in steps:
        _no_errors(step)


@pytest.mark.parametrize("size", [(1000, 700), (1440, 900)])
def test_toasts_never_cover_the_capture_note_or_its_close(tmp_path, size):
    """QA S04 P4 : à 1000×700 et 1440×900 les infusions couvraient les puces
    d'indicateurs et le × de la note d'un refus. La note s'ouvre désormais
    au-dessus du centre d'état, et les infusions montent au-dessus d'elle tant
    qu'elle est là."""

    width, height = size
    read = r"""(()=>{const box=el=>{if(!el||el.hidden)return null;const r=el.getBoundingClientRect();
        return r.width?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null};
      const close=document.querySelector('#recIndicatorsNote .ri-note-close');const c=close&&close.getBoundingClientRect();
      const hit=c?document.elementFromPoint(c.left+c.width/2,c.top+c.height/2):null;
      return {note:box(document.getElementById('recIndicatorsNote')),toasts:[...document.querySelectorAll('#toasts .toast')].map(box),
        closeHit:!!(hit&&close.contains(hit)),items:[...document.querySelectorAll('#bgPills .bgpill')].map(box),
        text:(document.querySelector('#recIndicatorsNote span')||{}).textContent||''}})()"""
    step = _drive(tmp_path, [{"width": width, "height": height, "actions": [
        ["eval", "start", "window.JarvisCaptureRail.act('audio');1", 1500],
        ["eval", "toast", "toast({title:'Notification',sub:'Une notification de hauteur ordinaire, sur deux lignes au moins pour la mesure.'});"
                          "toast({title:'Seconde',sub:'Une autre.'});1", 600],
        ["eval", "seen", read, 100],
        *_shot(f"status-centre-note-and-toasts-{width}x{height}"),
    ]}])[0]
    seen = step["results"]["seen"]
    assert seen["note"] and "non démarré" in seen["text"], seen
    assert seen["toasts"] and all(seen["toasts"])
    for toast in seen["toasts"]:
        assert not _overlap(toast, seen["note"]), (toast, seen["note"])
        for item in seen["items"]:
            assert not _overlap(toast, item), (toast, item)
    assert seen["closeHit"] is True, "le × de la note reçoit le clic"
    # La note est au-dessus de la rangée, jamais dessus.
    for item in seen["items"]:
        assert not _overlap(item, seen["note"]) and seen["note"]["b"] <= item["t"]


# ------------------------------------------------- S06 rework (QA S06 : B1, P1, P2)

#: La lecture de la scène échoue (Control Center injoignable) : la scène se fige et le dit.
BREAK_SCENE = r"""(()=>{const f=window.fetch;window.fetch=(p,i)=>String(p).startsWith('/api/scene')
  ?Promise.reject(new TypeError('Failed to fetch')):f(p,i);window.__sc.waiters.splice(0).forEach(fn=>fn([]));return 1})()"""

NOTES = r"""(()=>{const box=el=>{if(!el)return null;const r=el.getBoundingClientRect();return r.width>0?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null};
  return {notes:[...document.querySelectorAll('#sceneLayer>.sc-status .sc-note')].map(n=>{const m=n.querySelector('.sc-note-main');
    return {text:n.textContent,main:m.textContent,title:n.title,fits:m.scrollWidth<=m.clientWidth,box:box(n)}}),
    mode:box(document.getElementById('boardsButton')),
    centre:[...document.querySelectorAll('#recIndicators .ri-chip, #bgPills .bgpill')].map(box).filter(Boolean),
    rail:box(document.getElementById('presentationRail')),chatTab:box(document.getElementById('chatTab'))}})()"""


@pytest.mark.parametrize("size", ((1440, 900), (1280, 720)), ids=lambda s: f"{s[0]}x{s[1]}")
def test_degraded_scene_note_reads_whole_cause_without_overlap(tmp_path, size):
    """B1 : au-dessus de 820 px, la note « Scène figée · <cause> » était plafonnée à
    246 px et la cause disparaissait dans les points de suspension. Elle se lit en
    entier, son `title` porte le texte entier, et elle ne touche ni la carte
    Board (ex-bouton de mode, même place) ni le centre d'état."""
    width, height = size
    step = _drive(tmp_path, [{"width": width, "height": height, "actions": [
        ["eval", "break", BREAK_SCENE, 6000],
        ["eval", "seen", NOTES, 100],
        *_shot(f"s06-rework-degraded-note-{width}x{height}"),
    ]}])[0]
    seen = step["results"]["seen"]
    frozen = [n for n in seen["notes"] if n["main"].startswith("Scène")]
    assert frozen, seen["notes"]
    for note in seen["notes"]:
        assert note["fits"], note
        assert note["title"] and note["title"].startswith(note["main"]), note
        for other in [seen["mode"], seen["rail"], seen["chatTab"], *seen["centre"]]:
            assert not _overlap(note["box"], other), (note, other)
    assert "injoignable" in frozen[0]["main"].lower(), frozen[0]


def test_eye_announces_ghosts_and_ghosts_never_move(tmp_path):
    """P1 : l'œil annonce les fantômes dessinés (2 : le masqué sans place n'en a
    pas), et le nombre de la liste (3). P2 : glisser un fantôme ou le pousser au
    clavier (Maj+flèches) n'envoie aucune commande — garde explicite `node.ghost`."""
    live = "(document.querySelector('#sceneLayer .sc-sr-actions')||{}).textContent||''"
    sent = "window.__sc.bodies.filter(b=>b.path==='/api/scene/commands').length"
    ghost = '#sceneLayer [data-object-id="jobj_hidden_win"]'
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        *TOGGLE_GHOSTS,
        ["eval", "said", live, 100],
        ["drag", "drag", ghost, 1200, [140, 90]],
        ["eval", "afterDrag", sent, 100],
        ["eval", "focus", f"document.querySelector('{ghost}').focus();document.activeElement.dataset.objectId", 100],
        ["key", "k1", "ArrowRight", 150, True],
        ["key", "k2", "ArrowDown", 150, True],
        ["key", "k3", "ArrowRight", 1500],
        ["eval", "afterKeys", sent, 100],
        ["eval", "keySaid", live, 100],
    ]}])[0]
    r = step["results"]
    assert r["said"] == "2 objets masqués affichés en fantômes ; 3 dans Sélection › Masqués.", r["said"]
    assert r["focus"] == "jobj_hidden_win"
    assert r["afterDrag"] == 0 and r["afterKeys"] == 0, r
    assert "réaffichez-le" in r["keySaid"], r["keySaid"]
    _no_errors(step)


def test_a_ghost_is_never_pressed_into_a_gesture_nor_held(tmp_path):
    """QA S08 P4, le comportement que les gardes `node.ghost` protègent, de
    bout en bout : un vrai appui tenu sur un fantôme n'ouvre aucun geste
    (`JarvisScene.inspect().gesture` reste vide) alors que le même appui sur un
    objet visible en ouvre un ; la main (couture `JarvisScene.frames.begin`,
    qui passe par `holdTarget`) ne prend pas un fantôme alors qu'elle prend un
    objet visible ; rien ne part à Core. Le focus qui suit l'appui sélectionne
    le fantôme, comme au clavier (S06 : il reste focalisable pour « Réafficher »).

    Mutation (Slice 09, LOG) : retirer UNE des deux gardes ne fait pas tomber
    ce test, car un fantôme n'a pas de boîte dessinée (`drawnBox` vide : il
    n'entre pas dans la disposition résolue) et `onPointerDown` comme
    `holdTarget` s'arrêtent aussi sur elle. Les gardes sont une seconde serrure
    explicite ; ce test tient la première et la seconde ensemble."""
    ghost = '#sceneLayer [data-object-id="jobj_hidden_win"]'
    gesture = "JSON.stringify(JarvisScene.inspect().gesture)"
    hold = ("(()=>{const g=JarvisScene.frames.begin('jobj_hidden_win');const held=JarvisScene.inspect().holding.slice();"
            "const v=JarvisScene.frames.begin('jobj_star');const both=JarvisScene.inspect().holding.slice();"
            "if(v)JarvisScene.frames.cancel('jobj_star');return {ghost:g,heldAfterGhost:held,visible:!!v,heldAfterVisible:both}})()")
    sent = "window.__sc.bodies.filter(b=>b.path==='/api/scene/commands').length"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        *TOGGLE_GHOSTS,
        ["press", "down", ghost, 200],
        ["eval", "pressed", gesture, 50],
        ["release", "up", ghost, 400],
        ["press", "down2", '#sceneLayer [data-object-id="jobj_star"]', 200],
        ["eval", "pressedVisible", gesture, 50],
        ["release", "up2", '#sceneLayer [data-object-id="jobj_star"]', 600],
        ["eval", "hold", hold, 300],
        ["eval", "sent", sent, 100],
    ]}])[0]
    r = step["results"]
    assert r["pressed"] == "null", ("aucun geste sur un fantôme", r["pressed"])
    assert '"id":"jobj_star"' in r["pressedVisible"], ("le même appui sur un objet visible ouvre un geste", r["pressedVisible"])
    assert r["hold"]["ghost"] is None and r["hold"]["heldAfterGhost"] == [], r["hold"]
    assert r["hold"]["visible"] is True and r["hold"]["heldAfterVisible"] == ["jobj_star"], r["hold"]
    assert r["sent"] == 0, r
    _no_errors(step)


def test_a_lost_status_says_the_pill_counts_are_unconfirmed(tmp_path):
    """Polish S04 P4 (Slice 08) : statut perdu, les pastilles gardaient leurs comptes comme s'ils tenaient. Elles
    disent maintenant qu'ils ne sont plus confirmés, puis reviennent au battement suivant qui réussit."""
    mark = "document.getElementById('bgPills').hasAttribute('data-unconfirmed')"
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        ["eval", "before", PILLS, 100], ["eval", "lose", "window.__sc.statusFail=true;1", 2200],
        ["eval", "lostMark", mark, 50], ["eval", "lost", PILLS, 50],
        ["eval", "heal", "window.__sc.statusFail=false;1", 2200], ["eval", "backMark", mark, 50], ["eval", "back", PILLS, 50],
    ]}])[0]
    r = step["results"]
    assert r["lostMark"] is True and r["backMark"] is False
    assert [p["count"] for p in r["lost"]] == [p["count"] for p in r["before"]], "the last counts stay, said unconfirmed"
    assert all(p["label"].endswith("compte non confirmé : Jarvis ne répond pas") for p in r["lost"]), r["lost"]
    assert [p["label"] for p in r["back"]] == [p["label"] for p in r["before"]]


def test_settings_hub_opens_from_the_wheel_enters_a_category_and_closes_back(tmp_path):
    """Hub des Réglages (2026-10-23) : roue › Paramètres ouvre six cartes 3 × 2 de même taille, sans sous-menu ;
    une carte ouvre sa catégorie, ← (en haut à gauche de la page) ramène au hub, Échap ferme et rend le focus à la roue.
    Retours Human du 25/10 : plus de phrase sous « Paramètres », une grande icône devant, l'ensemble centré verticalement."""
    state = r"""(()=>{const o=document.getElementById('overlay');
      return {view:o.dataset.view||null,open:o.classList.contains('open'),submenu:!!document.querySelector('#toolWheel .tw-item'),
        cards:[...document.querySelectorAll('.set-hub-card')].map(c=>{const r=c.getBoundingClientRect();
          return {name:c.querySelector('.set-hub-name').textContent,desc:c.querySelector('.set-hub-desc').textContent,
            l:Math.round(r.left),t:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)}}),
        title:(document.getElementById('settingsHubTitle')||{}).textContent,lead:!!document.getElementById('settingsHubLead'),
        icon:!!document.querySelector('#settingsHubIcon svg'),described:document.getElementById('settingsHub').getAttribute('aria-describedby'),
        gapTop:Math.round(document.querySelector('.set-hub-head').getBoundingClientRect().top),
        gapBottom:Math.round(innerHeight-document.querySelector('#settingsHubGrid').getBoundingClientRect().bottom),
        focus:document.activeElement&&document.activeElement.className,overflowX:document.documentElement.scrollWidth>innerWidth}})()"""
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "actions": [
        ["click", "wheel", "#toolWheel .tw-anchor", 400],
        ["click", "settings", "#toolWheel [data-tw-slot=settings] .tw-dot", 700],
        ["eval", "hub", state, 100],
        *_shot("settings-hub-1440x900"),
        ["click", "card", "[data-hub-category=agents_models]", 900],
        ["eval", "shell", "({view:document.getElementById('overlay').dataset.view,title:(document.getElementById('settingsCategoryTitle')||{}).textContent})", 100],
        # Architecture & Agents s'ouvre en page pleine (refonte-ui-settings, Slice 07) : ← en haut à gauche.
        ["click", "back", "#settingsBack", 600],
        ["eval", "back", "document.getElementById('overlay').dataset.view", 100],
        ["key", "esc", "Escape", 500],
        ["eval", "closed", "({open:document.getElementById('overlay').classList.contains('open'),focus:document.activeElement&&document.activeElement.className})", 100],
    ]}])[0]
    hub = step["results"]["hub"]
    assert hub["view"] == "hub" and hub["open"] and not hub["submenu"] and hub["title"] == "Paramètres"
    assert hub["lead"] is False and hub["described"] is None and hub["icon"] is True, hub
    assert abs(hub["gapTop"] - hub["gapBottom"]) <= 40, ("titre et cartes centrés verticalement", hub["gapTop"], hub["gapBottom"])
    assert [c["name"] for c in hub["cards"]] == ["Personnalisation", "Architecture & Agents", "Mémoire & Connaissances",
                                                 "Interface & Interactions", "Plugins & MCP", "Avancé & Diagnostics"]
    assert all(c["desc"] for c in hub["cards"])
    # 3 × 2, cartes identiques.
    assert len({(c["w"], c["h"]) for c in hub["cards"]}) == 1
    assert len({c["t"] for c in hub["cards"]}) == 2 and len({c["l"] for c in hub["cards"]}) == 3
    assert "set-hub-card" in hub["focus"] and not hub["overflowX"]
    assert step["results"]["shell"] == {"view": "shell", "title": "Architecture & Agents"}
    assert step["results"]["back"] == "hub"
    assert step["results"]["closed"]["open"] is False and "tw-anchor" in step["results"]["closed"]["focus"]
    _no_errors(step)
