"""Graphe des tâches dans un vrai Chrome sans tête : rôles, relations typées, tableau de communication (Slice 09).

Handoff `jarvis-organic-agent-orchestration`, Slice 09. Contrat : `docs/scene-model.md` › *Interface : rôles et
relations*. La page est celle que `ControlCenter.index` sert (`_served_page`) ; `fetch` est le double de
`_status_centre_browser.mjs` : instantané de scène (étoiles `agent` avec `role_ref`, relations d'agent avec leur
`ref`, comme la Slice 08 les projette), la VRAIE charge de `GET /api/subagent-roles` (calculée par
`ControlCenter._subagent_roles_payload`), `GET /api/missions/relations/{id}` et `GET /api/missions/{id}` (formes des
routes de Core). Ce que ce fichier épingle :

- HV-ORG-09-01 : chaque étoile porte la pastille de son rôle (icône + badge + accent), le responsable de mission
  son drapeau et l'origine de la mission, le nom accessible dit le rôle ;
- HV-ORG-09-02 : les cinq relations ont chacune une figure (trait, flèche, double rail, pastille) ; confrontation et
  contrôle qualité ne partagent ni trait, ni marqueur, ni forme, ni pictogramme ;
- HV-ORG-09-03 : la pastille d'un échange ouvre, au clavier, le bon tableau ; flèches entre messages, Échap rend
  le focus ; états chargement (compteur), erreur (code, Réessayer, journal), vide ;
- HV-ORG-09-04 : rien n'est dessiné qui n'existe pas (une relation dont une étoile manque n'a ni fil ni pastille) ;
- HV-ORG-09-05 : graphe dense à 200 % de zoom et couleurs forcées ;
- échappement : un message ou un titre hostile reste du texte.

Captures : `JARVIS_S09_EVIDENCE_DIR=<dossier>` y écrit les captures de référence. Se saute sans Chrome ni node.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
import tempfile

from jarvis.runtime.control_center import ControlCenter
from tests.unit.test_status_centre_browser import _drive

EVIDENCE = os.environ.get("JARVIS_S09_EVIDENCE_DIR")
MISSION = "mis_root"
NOW = "2026-10-20T14:02:00+00:00"


def _shot(name: str) -> list:
    if not EVIDENCE:
        return []
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot_" + name, str(Path(EVIDENCE) / f"{name}.png"), 150]]


def _star(object_id: str, title: str, role: str, x: float, y: float, *, owner: bool = False, state: str = "running",
          mission: str = MISSION) -> dict:
    return {"schema_version": 1, "object_id": object_id, "kind": "agent", "category": "agent", "exec_state": state,
            "representation": "point", "geometry": {"x": x, "y": y, "w": 6, "h": 6}, "layer": 100, "order": 0,
            "visibility": "visible", "disposition": "active",
            "constraints": {"placed_by": "user", "pinned_by_user": False}, "origin": "runtime",
            "work_ref": {"source": "claude_code", "external_id": "tool_" + object_id},
            "role_ref": {"role_id": role, "instance_id": "ins_" + object_id, "mission_id": mission, "mission_owner": owner},
            "payload": {"title": title, "summary": "", "items": []}}


def _parent(a: str, b: str) -> dict:
    """Filiation d'exécution (`parent_of`, projetée par le runtime depuis Work State), sans `ref`."""
    return {"relation_id": f"parent_of!{a}~{b}", "kind": "parent_of", "from_id": a, "to_id": b, "layer": 0}


def _link(kind: str, rel: str, a: str, b: str, *, state: str = "open", outcome: str | None = None,
          peer: bool = False) -> dict:
    relation_id = f"{kind}!{rel}!ins_{a}~ins_{b}" if peer else f"{kind}!{rel}"
    ref = {"relation_id": rel, "mission_id": MISSION, "state": state, **({"outcome": outcome} if outcome else {})}
    return {"relation_id": relation_id, "kind": kind, "from_id": a, "to_id": b, "layer": 0, "ref": ref}


def _instance(object_id: str, role: str, label: str, *, owner: bool = False, status: str | None = "running") -> dict:
    return {"instance_id": "ins_" + object_id, "work_source": "claude_code", "work_external_id": "tool_" + object_id,
            "role_id": role, "created_at": NOW, "role_marker": role, "ephemeral": False, "mission_id": MISSION,
            "mission_owner": owner, "parent_instance_id": None, "label": label, "ephemeral_lowered": False,
            "role_known": True, "declaration": None, "work_status": status}


STARS = [
    ("lead", "Comparer trois bases", "research-lead", 0, -48, True),
    ("dev_a", "Prototype Postgres", "coder", -92, 6, False),
    ("dev_b", "Prototype SQLite", "coder", -40, 34, False),
    ("dev_c", "Prototype MySQL", "coder", 14, 40, False),
    ("web", "Benchmarks publiés", "web-research", 86, -12, False),
    ("doc", "Documentation officielle", "research", 112, 30, False),
    ("qa", "Relecture du prototype", "qa", -122, 52, False),
    ("next", "Synthèse finale", "research-lead", 64, 62, False),
]
ROLE_OF = {star[0]: star[2] for star in STARS}
LABEL_OF = {star[0]: star[1] for star in STARS}

#: Messages du tableau de l'échange : délibérés seulement (D13). Le quatrième est hostile : il doit rester du texte.
COMM_MESSAGES = [
    {"seq": 1, "message_id": "msg_1", "relation_id": "rel_comm", "author_instance_id": "ins_web", "type": "proposal",
     "text": "Je prends les benchmarks TPC publiés depuis 2024.", "created_at": NOW, "audience": [], "artifact_refs": [],
     "reply_to_message_id": None},
    {"seq": 2, "message_id": "msg_2", "relation_id": "rel_comm", "author_instance_id": "ins_doc", "type": "message",
     "text": "Je couvre les limites documentées (verrous, tailles).", "created_at": NOW, "audience": [],
     "artifact_refs": [], "reply_to_message_id": "msg_1"},
    {"seq": 3, "message_id": "msg_3", "relation_id": "rel_comm", "author_instance_id": "ins_lead", "type": "decision",
     "text": "Gardez Postgres et SQLite ; MySQL seulement si le coût diffère.", "created_at": NOW, "audience": [],
     "artifact_refs": [], "reply_to_message_id": None},
    {"seq": 4, "message_id": "msg_4", "relation_id": "rel_comm", "author_instance_id": "ins_web", "type": "critique",
     "text": "<img src=x onerror=\"window.__xss=1\"><b>gras</b> & « guillemets »", "created_at": NOW, "audience": [],
     "artifact_refs": [], "reply_to_message_id": None},
]


def _relation(rel: str, kind: str, participants: list[tuple[str, str]], purpose: str, *, status: str = "open",
              outcome: str | None = None) -> dict:
    return {"relation_id": rel, "kind": kind, "mission_id": MISSION,
            "participants": [{"instance_id": "ins_" + who, "position": pos} for who, pos in participants],
            "purpose": purpose, "created_at": NOW, "created_by_instance_id": "ins_lead", "sub_mission_id": None,
            "target_refs": [], "handoff": None, "status": status, "closed_at": None, "outcome": outcome,
            "outcome_summary": "", "winner_instance_id": None, "closed_by_instance_id": None}


@functools.cache
def _roles() -> dict:
    """La vraie charge de `GET /api/subagent-roles` (v2), calculée par le Control Center sur un dossier jetable."""
    with tempfile.TemporaryDirectory() as tmp:
        return ControlCenter(runtime_root=Path(tmp), project_root=Path(tmp))._subagent_roles_payload({})


def _seed(*, comm_messages: list | None = None, live_unknown: bool = False, dense: int = 0, extra: dict | None = None) -> dict:
    roles = _roles()
    objects = [_star(oid, title, role, x, y, owner=owner) for oid, title, role, x, y, owner in STARS]
    # La Recherche documentaire porte une sous-mission déléguée (D04) : elle en est la responsable.
    objects[5]["role_ref"].update(mission_id="mis_sub", mission_owner=True)
    links = [_parent("lead", who) for who in ("dev_a", "dev_b", "dev_c", "web", "doc", "qa", "next")]
    links += [_link("delegation", "rel_dlg_doc", "lead", "doc")]
    links += [_link("communication", "rel_comm", a, b, peer=True) for a, b in (("lead", "web"), ("lead", "doc"), ("web", "doc"))]
    links += [_link("adversary", "rel_adv", a, b, peer=True) for a, b in (("dev_a", "dev_b"), ("dev_a", "dev_c"), ("dev_b", "dev_c"))]
    links += [_link("qa", "rel_qa", "qa", "dev_a", state="closed", outcome="findings"),
              _link("handoff", "rel_hof", "lead", "next", state="closed", outcome="transferred"),
              # D15 : relation vers une étoile qui n'existe pas (instance jamais observée) — ni fil ni pastille.
              _link("delegation", "rel_dlg_ghost", "lead", "never_seen")]
    for i in range(dense):
        oid = f"dn{i}"
        x, y = -150 + (i % 10) * 32, -80 + (i // 10) * 30
        objects.append(_star(oid, f"Recherche {i}", ("web-research", "research", "coder", "qa", "concept")[i % 5], x, y))
        links.append(_parent("lead", oid))
        if i % 4 == 0:
            links.append(_link("delegation", f"rel_dlg_{oid}", "lead", oid))
        if i % 2:
            links.append(_link("communication", f"rel_c_{oid}", oid, f"dn{i - 1}", peer=True))
        if i % 3 == 0 and i:
            links.append(_link("qa", f"rel_q_{oid}", oid, f"dn{i - 1}"))
    instances = [_instance(oid, ROLE_OF[oid], LABEL_OF[oid], owner=oid == "lead") for oid in ROLE_OF]
    reads = {
        "rel_comm": {"relation": _relation("rel_comm", "communication", [("lead", "member"), ("web", "member"), ("doc", "member")],
                                           "Se répartir les sources sans doublon"),
                     "messages": COMM_MESSAGES if comm_messages is None else comm_messages,
                     "participants": [i for i in instances if i["instance_id"] in ("ins_lead", "ins_web", "ins_doc")]},
        "rel_adv": {"relation": _relation("rel_adv", "adversary", [("dev_a", "producer"), ("dev_b", "producer"), ("dev_c", "producer")],
                                          "Trois prototypes concurrents"),
                    "messages": [], "participants": [i for i in instances if i["instance_id"] in ("ins_dev_a", "ins_dev_b", "ins_dev_c")]},
        "rel_qa": {"relation": _relation("rel_qa", "qa", [("qa", "reviewer"), ("dev_a", "reviewed")], "Relire le prototype Postgres",
                                         status="closed", outcome="findings"),
                   "messages": [], "participants": [i for i in instances if i["instance_id"] in ("ins_qa", "ins_dev_a")]},
    }
    tree = {"root_mission_id": MISSION, "missions": [
        {"mission_id": MISSION, "objective": "Choisir une base de données pour le projet", "owner_instance_id": "ins_lead",
         "created_at": NOW, "parent_mission_id": None, "root_mission_id": MISSION, "dossier_path": None,
         "origin_kind": "general", "status": "open", "closed_at": None, "live_unknown": live_unknown},
        {"mission_id": "mis_sub", "objective": "Relever les limites documentées", "owner_instance_id": "ins_doc",
         "created_at": NOW, "parent_mission_id": MISSION, "root_mission_id": MISSION, "dossier_path": None,
         "origin_kind": "general", "status": "open", "closed_at": None, "live_unknown": False}],
        "instances": instances, "relations": [], "ownership": [], "truncated": False}
    missions = {MISSION: tree, "mis_sub": tree}
    seed = {"objects": objects, "relations": links, "roles": roles, "relationReads": reads, "missions": missions}
    seed.update(extra or {})
    return seed


READ = """(()=>{
  const nodes=[...document.querySelectorAll('#sceneLayer .sc-node')];
  const role=id=>{const n=document.querySelector(`#sceneLayer .sc-node[data-object-id="${id}"]`);if(!n)return null;
    const p=n.querySelector('.sc-role');return {label:n.getAttribute('aria-label'),badge:p&&p.querySelector('b')?p.querySelector('b').textContent:null,
      owner:!!(p&&p.classList.contains('sc-role-owner')),flag:!!(p&&p.querySelector('.sc-role-flag')),glyph:!!(p&&p.querySelector('.sc-role-glyph')),
      extra:p?[...p.querySelectorAll('i')].map(i=>i.textContent).join(' '):'',accent:n.style.getPropertyValue('--sc-role'),
      color:p?getComputedStyle(p).color:null,hasRole:n.classList.contains('sc-has-role')}};
  const lines=[...document.querySelectorAll('#sceneLayer .sc-links line')].map(l=>{const cs=getComputedStyle(l);
    return {cls:l.getAttribute('class'),dash:cs.strokeDasharray,marker:cs.markerEnd,width:cs.strokeWidth,stroke:cs.stroke}});
  const marks=[...document.querySelectorAll('#sceneLayer .sc-relmark')].map(b=>{const r=b.getBoundingClientRect(),cs=getComputedStyle(b);
    return {id:b.dataset.relationId,kind:b.dataset.relationKind,cls:b.className,label:b.getAttribute('aria-label'),tab:b.tabIndex,
      radius:cs.borderRadius,border:cs.borderStyle,closedMark:getComputedStyle(b,'::after').content,w:r.width,h:r.height,l:r.left,t:r.top,r:r.right,b:r.bottom,
      glyph:b.querySelector('svg')?b.querySelector('svg').innerHTML.length:0}});
  const orbit={nodes:Object.fromEntries([...document.querySelectorAll('#sceneLayer .sc-node')].map(n=>[n.dataset.objectId,n.classList.contains('sc-orbit')])),
    marks:Object.fromEntries([...document.querySelectorAll('#sceneLayer .sc-relmark')].map(b=>[b.dataset.relationId,b.classList.contains('sc-orbit')]))};
  return {orbit,nodes:nodes.length,roles:Object.fromEntries(['lead','dev_a','web','doc','qa','next'].map(id=>[id,role(id)])),lines,marks,
    vw:innerWidth,vh:innerHeight};
})()"""

BOARD = """(()=>{const p=document.getElementById('relationBoard');if(!p)return null;
  const msgs=[...p.querySelectorAll('.rb-msg')];
  return {hidden:p.hidden,open:p.classList.contains('open'),kind:p.dataset.kind,relation:p.dataset.relationId,
    title:(p.querySelector('#relationBoardTitle')||{}).textContent||'',text:p.querySelector('.rb-body').innerText,
    messages:msgs.map(m=>m.querySelector('.rb-msg-text').textContent),tabs:msgs.map(m=>m.tabIndex),
    focus:document.activeElement&&(document.activeElement.dataset.seq||document.activeElement.id||document.activeElement.className),
    imgs:p.querySelectorAll('img').length,xss:window.__xss===1,error:!!p.querySelector('.rb-error'),
    state:(p.querySelector('[data-rb-state]')||{}).textContent||'',empty:(p.querySelector('.rb-empty')||{}).textContent||'',
    rect:(()=>{const r=p.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}})()};})()"""


#: Attendre que le tableau ait lu (ou dit son échec), au plus 8 s : jamais une attente fixe sous la charge.
WAIT_BOARD = ("new Promise(r=>{const t0=Date.now();const f=()=>{const p=document.getElementById('relationBoard');"
              "if((p&&p.querySelector('.rb-section,.rb-error'))||Date.now()-t0>8000)r(Date.now()-t0);else setTimeout(f,50)};f()})")


def _no_errors(step: dict, allowed: tuple[str, ...] = ()) -> None:
    bad = [line for line in step["console"] if line["type"] in ("exception", "error")
           and not any(code in line["text"] for code in allowed)]
    assert bad == [], bad


# ------------------------------------------------------------------ HV-ORG-09-01 : rôles d'un coup d'œil


def test_every_role_star_carries_its_registry_identity_and_the_owner_its_flag_and_origin(tmp_path):
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": _seed(),
                                "actions": [["eval", "read", READ, 300], *_shot("01-roles-relations-circuit")]}])
    _no_errors(step)
    seen = step["results"]["read"]
    roles = seen["roles"]
    # Badges du registre (jamais devinés d'un titre) : DEV, WEB, DOC, QA, DIR.
    assert {k: v["badge"] for k, v in roles.items()} == {"lead": "DIR", "dev_a": "DEV", "web": "WEB", "doc": "DOC",
                                                         "qa": "QA", "next": "DIR"}
    assert all(v["glyph"] and v["hasRole"] for v in roles.values())
    # Accent du registre en variable de thème, jamais une couleur écrite.
    assert roles["dev_a"]["accent"] == "var(--role-accent-amber)" and roles["web"]["accent"] == "var(--role-accent-sky)"
    assert roles["dev_a"]["color"] != roles["web"]["color"]
    # Responsable : drapeau + origine de la mission ; le successeur d'un même rôle n'a pas le drapeau.
    assert roles["lead"]["owner"] and roles["lead"]["flag"] and "général" in roles["lead"]["extra"]
    assert not roles["next"]["owner"] and not roles["next"]["flag"]
    # Le nom accessible dit le rôle (pas la couleur seule).
    assert "rôle Développement" in roles["dev_a"]["label"] and "rôle Recherche web" in roles["web"]["label"]
    assert "rôle Recherche documentaire" in roles["doc"]["label"] and "rôle Contrôle qualité" in roles["qa"]["label"]
    assert "responsable de la mission" in roles["lead"]["label"] and "origine général" in roles["lead"]["label"]
    assert any(call == "GET /api/subagent-roles" for call in step["calls"])
    assert step["calls"].count("GET /api/subagent-roles") == 1, step["calls"]


# ------------------------------------------------------------------ HV-ORG-09-02 : cinq relations distinctes


def test_each_relation_kind_has_its_own_figure_and_adversary_never_looks_like_qa(tmp_path):
    seed = _seed()
    # Confrontation close ET contrôle qualité clos : l'état ne doit pas effacer la forme de la nature (QA S09, M5).
    for link in seed["relations"]:
        if link["kind"] == "adversary":
            link["ref"].update(state="closed", outcome="winner")
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": [["eval", "read", READ, 200]]}])
    seen = step["results"]["read"]
    by_kind: dict[str, list] = {}
    for line in seen["lines"]:
        for kind in ("delegation", "communication", "adversary-gap", "adversary", "qa", "handoff"):
            if f"sc-link-{kind}" in line["cls"].split():
                by_kind.setdefault(kind, []).append(line)
                break
    assert len(by_kind["delegation"]) == 1          # rel_dlg_ghost : son étoile n'existe pas (D15)
    assert len(by_kind["communication"]) == 3 and len(by_kind["adversary"]) == 3 and len(by_kind["adversary-gap"]) == 3
    assert len(by_kind["qa"]) == 1 and len(by_kind["handoff"]) == 1
    figure = {k: (v[0]["dash"], v[0]["marker"], v[0]["width"]) for k, v in by_kind.items()}
    assert len({figure[k] for k in ("delegation", "communication", "adversary", "qa", "handoff")}) == 5, figure
    adv, qa = by_kind["adversary"][0], by_kind["qa"][0]
    assert qa["dash"] not in ("none", "") and adv["dash"] in ("none", "")
    assert "sc-mk-qa" in qa["marker"] and adv["marker"] == "none" and "sc-mk-delegation" in figure["delegation"][1]
    assert "sc-mk-handoff" in figure["handoff"][1] and figure["communication"][1] == "none"
    assert adv["stroke"] != qa["stroke"]
    # Une pastille par relation (la confrontation à trois n'en a qu'une), aucune pour la relation fantôme.
    marks = {m["id"]: m for m in seen["marks"]}
    assert set(marks) == {"rel_dlg_doc", "rel_comm", "rel_adv", "rel_qa", "rel_hof"}
    assert marks["rel_adv"]["border"] == "double" and marks["rel_qa"]["border"] == "solid", (marks["rel_adv"], marks["rel_qa"])
    assert marks["rel_adv"]["radius"] != marks["rel_qa"]["radius"]
    assert "✓" in marks["rel_adv"]["closedMark"] and "✓" in marks["rel_qa"]["closedMark"]
    assert marks["rel_comm"]["closedMark"] in ("none", "normal", "")       # ouverte : pas de coche
    assert marks["rel_adv"]["glyph"] and marks["rel_qa"]["glyph"]
    assert marks["rel_adv"]["label"].startswith("Confrontation : entre ") and marks["rel_qa"]["label"].startswith("Contrôle qualité : ")
    assert "relit" in marks["rel_qa"]["label"] and "close, remarques" in marks["rel_qa"]["label"]
    assert "passe le relais à" in marks["rel_hof"]["label"]
    # Un seul arrêt de tabulation pour toutes les pastilles.
    assert sorted(m["tab"] for m in seen["marks"]).count(0) == 1


# ------------------------------------------------------------------ HV-ORG-09-03 : tableau au clavier


def test_the_communication_mark_opens_its_board_from_the_keyboard_and_escape_returns_focus(tmp_path):
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": _seed(), "actions": [
        ["eval", "focus", "(()=>{const b=document.querySelector('.sc-relmark-communication');b.focus();return document.activeElement===b})()", 100],
        ["key", "enter", "Enter", 100],
        ["eval", "waitBoard", WAIT_BOARD, 50],
        ["eval", "board", BOARD, 50],
        ["eval", "expanded", "document.querySelector('.sc-relmark-communication').getAttribute('aria-expanded')", 50],
        ["key", "tab", "Tab", 120],
        ["eval", "afterTab", "document.activeElement.className", 50],
        *_shot("03-board-open-keyboard"),
        ["eval", "toFirst", "(()=>{document.querySelector('.rb-msg').focus();return document.activeElement.dataset.seq})()", 50],
        ["key", "down", "ArrowDown", 80],
        ["key", "down2", "ArrowDown", 80],
        ["eval", "afterDown", "document.activeElement.dataset.seq", 50],
        ["key", "end", "End", 80],
        ["eval", "afterEnd", "document.activeElement.dataset.seq", 50],
        ["key", "home", "Home", 80],
        ["eval", "afterHome", "document.activeElement.dataset.seq", 50],
        ["key", "esc", "Escape", 200],
        ["eval", "closed", BOARD, 50],
        ["eval", "back", "(()=>{const a=document.activeElement;return {mark:a&&a.classList.contains('sc-relmark-communication'),expanded:a&&a.getAttribute('aria-expanded')}})()", 50],
    ]}])
    _no_errors(step)
    r = step["results"]
    assert r["focus"] is True
    board = r["board"]
    assert board["open"] and not board["hidden"] and board["kind"] == "communication" and board["relation"] == "rel_comm"
    assert "Tableau" in board["title"] and "Échange entre agents" in board["title"]
    assert board["focus"] == "relationBoardTitle"
    assert "Se répartir les sources sans doublon" in board["text"]
    assert "Choisir une base de données pour le projet" in board["text"] and "général" in board["text"]
    assert "Recherche web « Benchmarks publiés »" in board["text"] and "Direction de recherche" in board["text"]
    assert board["messages"][0] == COMM_MESSAGES[0]["text"] and len(board["messages"]) == 4
    assert board["tabs"].count(0) == 1
    assert r["expanded"] == "true"
    assert r["afterDown"] == "3" and r["afterEnd"] == "4" and r["afterHome"] == "1"
    assert r["closed"]["hidden"] and r["back"] == {"mark": True, "expanded": "false"}
    assert "GET /api/missions/relations/rel_comm" in step["calls"] and f"GET /api/missions/{MISSION}" in step["calls"]
    # Aucune écriture : le tableau ne fait que lire.
    assert not [c for c in step["calls"] if "/api/missions" in c and not c.startswith("GET ")], step["calls"]


def test_hostile_text_in_a_message_stays_text(tmp_path):
    hostile = _seed()
    hostile["objects"][4]["payload"]["title"] = "<script>window.__xss=1</script>Benchmarks"
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": hostile, "actions": [
        ["click", "open", ".sc-relmark-communication", 100],
        ["eval", "waitBoard", WAIT_BOARD, 50],
        ["eval", "board", BOARD, 50],
        ["eval", "mark", "document.querySelector('.sc-relmark-communication').getAttribute('aria-label')", 50],
        ["eval", "scripts", "document.querySelectorAll('#sceneLayer script,#relationBoard script').length", 50],
    ]}])
    board = step["results"]["board"]
    assert board["imgs"] == 0 and board["xss"] is False
    assert COMM_MESSAGES[3]["text"] in board["messages"]
    assert "<script>window.__xss=1</script>Benchmarks" in step["results"]["mark"]
    assert step["results"]["scripts"] == 0


def test_board_states_loading_counter_error_with_code_and_retry_then_empty(tmp_path):
    seed_slow = _seed(extra={"relationDelayMs": 2600})
    seed_fail = _seed(extra={"relationFail": {"rel_comm": {"status": 503, "code": "mission_history_unavailable",
                                                            "message": "Historique des missions indisponible (magasin fermé)."}}})
    seed_empty = _seed(comm_messages=[])
    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "seed": seed_slow, "actions": [
            ["click", "open", ".sc-relmark-communication", 1300],
            ["eval", "loading", BOARD, 50], *_shot("04-board-loading"),
            ["eval", "wait", "new Promise(r=>setTimeout(r,1800))", 50],
            ["eval", "loaded", BOARD, 50]]},
        {"width": 1440, "height": 900, "seed": seed_fail, "actions": [
            ["click", "open", ".sc-relmark-communication", 100],
            ["eval", "waitBoard", WAIT_BOARD, 50],
            ["eval", "failed", BOARD, 50], *_shot("05-board-error"),
            ["eval", "heal", "(()=>{delete window.__sc.relationFail;document.querySelector('.rb-error .rb-btn').click();return 1})()", 100],
            ["eval", "waitHealed", "new Promise(r=>{const t0=Date.now();const f=()=>{if(document.querySelectorAll('#relationBoard .rb-msg').length||Date.now()-t0>8000)r(1);else setTimeout(f,50)};f()})", 50],
            ["eval", "healed", BOARD, 50]]},
        {"width": 1440, "height": 900, "seed": seed_empty, "actions": [
            ["click", "open", ".sc-relmark-communication", 100],
            ["eval", "waitBoard", WAIT_BOARD, 50],
            ["eval", "empty", BOARD, 50], *_shot("06-board-empty")]},
    ])
    slow, fail, empty = (s["results"] for s in steps)
    assert "Lecture du tableau…" in slow["loading"]["state"] and " s (échéance 15 s)" in slow["loading"]["state"]
    assert slow["loaded"]["state"] == "" and len(slow["loaded"]["messages"]) == 4
    assert fail["failed"]["error"] and "Historique des missions indisponible (magasin fermé)." in fail["failed"]["text"]
    assert "Code : mission_history_unavailable" in fail["failed"]["text"]
    assert any("mission_history_unavailable" in line["text"] for line in steps[1]["console"] if line["type"] == "error")
    assert not fail["healed"]["error"] and len(fail["healed"]["messages"]) == 4
    assert "Aucun message délibéré n’a encore été publié" in empty["empty"]["empty"]


def test_a_live_unknown_mission_reads_unknown_never_running(tmp_path):
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": _seed(live_unknown=True), "actions": [
        ["eval", "read", READ, 50],
        ["click", "open", ".sc-relmark-communication", 100],
        ["eval", "waitBoard", WAIT_BOARD, 50],
        ["eval", "board", BOARD, 50], *_shot("07-live-unknown")]}])
    lead = step["results"]["read"]["roles"]["lead"]
    assert "état inconnu" in lead["extra"] and "mission : état inconnu" in lead["label"]
    text = step["results"]["board"]["text"]
    assert "État de la mission\nétat inconnu" in text or "État de la mission\tétat inconnu" in text, text
    assert "ouverte" not in text.split("État de la mission")[1].splitlines()[1]


# ------------------------------------------------------------------ HV-ORG-09-04 : exécution réelle seulement


def test_nothing_is_drawn_that_the_scene_does_not_hold(tmp_path):
    seed = _seed()
    seed["objects"] = [o for o in seed["objects"] if o["object_id"] not in ("dev_c", "next")]
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": [["eval", "read", READ, 200]]}])
    seen = step["results"]["read"]
    assert seen["nodes"] == len(seed["objects"])
    ids = {m["id"] for m in seen["marks"]}
    assert "rel_hof" not in ids and "rel_dlg_ghost" not in ids
    # La confrontation n'a plus que la paire dont les deux étoiles existent : un fil, une pastille.
    assert sum("sc-link-adversary" in line["cls"].split() for line in seen["lines"]) == 1 and "rel_adv" in ids


# ------------------------------------------------------------------ HV-ORG-09-05 : dense, 200 %, couleurs forcées


def _overlap(a: dict, b: dict) -> float:
    return max(0.0, min(a["r"], b["r"]) - max(a["l"], b["l"])) * max(0.0, min(a["b"], b["b"]) - max(a["t"], b["t"]))


def test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable(tmp_path):
    steps = _drive(tmp_path, [
        {"width": 720, "height": 450, "scale": 2, "seed": _seed(dense=30), "actions": [
            ["eval", "read", READ, 50], *_shot("08-dense-200pct"),
            ["click", "open", '.sc-relmark[data-relation-id="rel_comm"]', 100],
            ["eval", "waitBoard", WAIT_BOARD, 50],
            ["eval", "board", BOARD, 50], *_shot("09-dense-200pct-board")]},
        {"width": 1440, "height": 900, "forcedColors": True, "seed": _seed(), "actions": [
            ["eval", "read", READ, 50],
            ["eval", "mark", "getComputedStyle(document.querySelector('.sc-relmark-qa')).borderTopColor", 50],
            *_shot("10-forced-colours")]},
        {"width": 1440, "height": 900, "theme": "cosmos", "seed": _seed(), "actions": [
            ["eval", "read", READ, 50], *_shot("02-roles-relations-cosmos")]},
    ])
    dense, forced, cosmos = (s["results"] for s in steps)
    marks = dense["read"]["marks"]
    assert len(marks) > 25
    inside = [m for m in marks if m["l"] >= 0 and m["t"] >= 0 and m["r"] <= dense["read"]["vw"] and m["b"] <= dense["read"]["vh"]]
    assert len(inside) >= 0.8 * len(marks), (len(inside), len(marks))
    # Écartées à la pose ; une pastille dont un seul bout tourne glisse ensuite avec le champ (orbite) : au plus
    # deux paires se recouvrent à moitié à l'instant de la mesure, aucune ne disparaît sous une autre.
    pairs = sorted(((_overlap(a, b) / (a["w"] * a["h"]), a["id"], b["id"]) for i, a in enumerate(marks) for b in marks[i + 1:]),
                   reverse=True)
    assert not pairs or pairs[0][0] < 0.85, pairs[:3]
    assert sum(1 for pair in pairs if pair[0] >= 0.5) <= 2, pairs[:5]
    board = dense["board"]
    assert board["open"] and board["rect"]["l"] >= 0 and board["rect"]["r"] <= dense["read"]["vw"] + 0.5
    assert all(line["stroke"] in ("rgb(0, 0, 0)", "rgb(255, 255, 255)", "canvastext") or "rgb" in line["stroke"]
               for line in forced["read"]["lines"])
    assert forced["mark"]
    assert {k: v["badge"] for k, v in cosmos["read"]["roles"].items()}["dev_a"] == "DEV"
    for s in steps:
        _no_errors(s)


def test_tab_reaches_the_relation_marks_with_a_visible_ring(tmp_path):
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": _seed(), "actions": [
        ["tabto", "stops", ".sc-relmarks", 120, 80]]}])
    stops = step["results"]["stops"]
    assert stops and stops[-1]["inside"], stops[-6:]
    assert stops[-1]["visible"] and stops[-1]["ring"], stops[-1]


def test_without_the_role_registry_stars_say_their_raw_role_and_the_failure_is_logged(tmp_path):
    seed = _seed(extra={"rolesFail": {"status": 500, "code": "prompt_overrides_invalid", "message": "Surcharges illisibles."}})
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": [["eval", "read", READ, 200]]}])
    roles = step["results"]["read"]["roles"]
    assert roles["dev_a"]["badge"] == "COD" and "rôle coder" in roles["dev_a"]["label"]
    assert any("prompt_overrides_invalid" in line["text"] for line in step["console"]), step["console"]


def test_a_live_refresh_appends_new_messages_without_moving_the_keyboard_focus(tmp_path):
    add = ("(()=>{window.__sc.relationReads.rel_comm.messages.push({seq:5,message_id:'msg_5',relation_id:'rel_comm',"
           "author_instance_id:'ins_doc',type:'result_summary',text:'Limites relevées : trois.',created_at:'" + NOW + "',"
           "audience:[],artifact_refs:[],reply_to_message_id:null});return 1})()")
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": _seed(), "actions": [
        ["click", "open", ".sc-relmark-communication", 100],
        ["eval", "waitBoard", WAIT_BOARD, 50],
        ["eval", "focus", "(()=>{const m=document.querySelectorAll('.rb-msg')[1];m.focus();return m.dataset.seq})()", 50],
        ["eval", "idle", "new Promise(r=>setTimeout(()=>r(document.activeElement.dataset.seq),5600))", 50],
        ["eval", "add", add, 50],
        ["eval", "after", "new Promise(r=>setTimeout(()=>r({seq:document.activeElement.dataset.seq,count:document.querySelectorAll('.rb-msg').length,"
                          "live:document.querySelector('#relationBoard .rb-sr').textContent}),5600))", 50],
    ]}])
    r = step["results"]
    assert r["focus"] == "2" and r["idle"] == "2"
    assert r["after"] == {"seq": "2", "count": 5, "live": "Un nouveau message."}
    reads = [c for c in step["calls"] if c == "GET /api/missions/relations/rel_comm"]
    assert len(reads) >= 3
    _no_errors(step)


RACE = ("(()=>{const f=window.fetch;window.__slow=0;window.fetch=function(u,o){if(String(u).includes('/api/missions/relations/'))"
        "{window.__slow++;return new Promise(r=>setTimeout(r,1500)).then(()=>f.call(this,u,o))}return f.call(this,u,o)};"
        "const a=document.querySelector('.sc-relmark-communication'),b=document.querySelector('.sc-relmark-adversary');"
        "a.click();setTimeout(()=>b.click(),300);return [a.dataset.relationId,b.dataset.relationId]})()")
BOARD_STATE = ("(()=>{const s=JarvisRelationBoard.instance.state;return {phase:s.phase,rel:s.relationId,inflight:s.inflight,"
               "slow:window.__slow,title:document.getElementById('relationBoardTitle').textContent}})()")


def test_opening_another_relation_during_a_read_never_leaves_the_board_loading(tmp_path):
    """QA S09 B1 (plan `race.json`) : deux pastilles ouvertes à 300 ms d'écart pendant des lectures lentes."""
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": _seed(), "actions": [
        ["eval", "race", RACE, 50],
        ["eval", "settle", "new Promise(r=>setTimeout(r,4500))", 50],
        ["eval", "state", BOARD_STATE, 50], *_shot("11-race-fixed"),
    ]}])
    first, second = step["results"]["race"]
    state = step["results"]["state"]
    assert (first, second) == ("rel_comm", "rel_adv")
    assert state["phase"] == "ready" and state["rel"] == "rel_adv" and state["inflight"] is False, state
    assert state["slow"] >= 2 and "Confrontation" in state["title"]
    _no_errors(step)


def test_a_read_that_never_answers_ends_in_the_error_state(tmp_path):
    [step] = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": _seed(extra={"relationHang": True}), "actions": [
        ["click", "open", ".sc-relmark-communication", 100],
        ["eval", "wait", "new Promise(r=>setTimeout(r,16500))", 50],
        ["eval", "board", BOARD, 50]]}])
    board = step["results"]["board"]
    assert board["error"] and "Pas de réponse après 15 s." in board["text"] and "relation_board_timeout" in board["text"]


OVERLAPS = """(()=>{
  const rect=e=>{const r=e.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}};
  const marks=[...document.querySelectorAll('#sceneLayer .sc-relmark')].map(b=>({id:b.dataset.relationId,...rect(b)}));
  const pills=[...document.querySelectorAll('#sceneLayer .sc-role')].map(p=>({id:p.closest('.sc-node').dataset.objectId,...rect(p)}));
  const labels=[...document.querySelectorAll('#sceneLayer .sc-task-root > .sc-label')].map(p=>({id:'label:'+p.closest('.sc-node').dataset.objectId,...rect(p)}));
  const area=(a,b)=>Math.max(0,Math.min(a.r,b.r)-Math.max(a.l,b.l))*Math.max(0,Math.min(a.b,b.b)-Math.max(a.t,b.t));
  const hits=[];
  marks.forEach((m,i)=>{
    for(const o of [...pills,...labels])if(area(m,o)>0.5)hits.push([m.id,o.id,Math.round(area(m,o))]);
    for(const o of marks.slice(i+1))if(area(m,o)>0.5)hits.push([m.id,o.id,Math.round(area(m,o))]);
  });
  const pillHits=[];
  pills.forEach((p,i)=>{for(const o of pills.slice(i+1))if(area(p,o)>0.5)pillHits.push([p.id,o.id])});
  return {marks:marks.length,pills:pills.length,hits,pillHits};
})()"""


def _fresh_team() -> dict:
    """Une équipe neuve : aucune place enregistrée, le résolveur de la page pose chaque étoile."""
    seed = _seed()
    for item in seed["objects"]:
        item["geometry"] = None
    return seed


def test_a_fresh_team_at_100_percent_has_no_mark_on_a_pill_a_label_or_another_mark(tmp_path):
    steps = _drive(tmp_path, [
        {"width": 1440, "height": 900, "seed": _fresh_team(), "storage": {"orbit": False},
         "actions": [["eval", "wait", "new Promise(r=>setTimeout(r,1500))", 50], ["eval", "o", OVERLAPS, 50],
                     *_shot("12-fresh-team-100pct")]},
        {"width": 1920, "height": 1032, "seed": _fresh_team(), "storage": {"orbit": False},
         "actions": [["eval", "wait", "new Promise(r=>setTimeout(r,1500))", 50], ["eval", "o", OVERLAPS, 50]]},
        # Gravitation allumée (réglage par défaut) : le tour est une rotation d'ensemble, rien ne se rapproche.
        {"width": 1440, "height": 900, "seed": _fresh_team(),
         "actions": [["eval", "wait", "new Promise(r=>setTimeout(r,3000))", 50], ["eval", "o", OVERLAPS, 50]]},
    ])
    for index, step in enumerate(steps):
        seen = step["results"]["o"]
        assert seen["marks"] == 5 and seen["pills"] == 8, seen
        assert seen["pillHits"] == [], seen["pillHits"]
        # Champ immobile : aucun recouvrement. Champ qui tourne : la place est recalculée chaque seconde et la
        # pastille glisse entre deux places ; au plus un liseré de 2 px pendant la glissade.
        tolerance = 0 if index < 2 else 2 * 24
        assert [hit for hit in seen["hits"] if hit[2] > tolerance] == [], seen["hits"]
