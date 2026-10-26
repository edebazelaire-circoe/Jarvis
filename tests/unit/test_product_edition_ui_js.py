"""Logique pure de l'interface d'édition produit (node, sans navigateur ; jarvis-presentation-edition-v1, Slice 08).

Contrat : `docs/control-center-shell.md` › *Product edition UI*. Ce fichier épingle ce que les modules lisent de la
charge de Core (`ProductEditionPolicy.to_payload()`, servie ici telle que Python la produit) et ce qu'ils en font :
lecture stricte de la charge, choix du type de Board, lignes de la liste, catégories des Réglages, modèle du rail.
Le comportement dans une vraie page est prouvé par `test_presentation_edition_ui_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.product_edition import FULL_EDITION, PRESENTATION_EDITION

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
PRESENTATION = json.dumps(PRESENTATION_EDITION.to_payload())
FULL = json.dumps(FULL_EDITION.to_payload())


def node(script: str):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    req = lambda name: json.dumps(str(RUNTIME / name))  # noqa: E731 - local helper for the require paths
    code = (f"const E=require({req('control_center_product_edition.js')});"
            f"const B=require({req('control_center_boards.js')});"
            f"const R=require({req('control_center_settings_registry.js')});"
            f"const P=require({req('control_center_presentation_rail.js')});"
            f"process.stdout.write(JSON.stringify((()=>{{{script}}})()))")
    done = subprocess.run([exe, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_payload_of_core_is_read_strictly():
    out = node(f"const p=E.parse({PRESENTATION}).model;const f=E.parse({FULL}).model;"
               "return {p:[p.edition,p.defaultKind,p.developerSurfaces,p.available,p.restricts],"
               "f:[f.edition,f.defaultKind,f.developerSurfaces,f.available,f.restricts],"
               "bad:[E.parse(null).ok,E.parse({edition:'x'}).ok,E.parse({edition:'x',board_kinds:[{}]}).ok],"
               "old:E.parse({edition:'full',board_kinds:[{board_kind:'assistant',available:true}]}).model.developerSurfaces}")
    assert out["p"] == ["presentation", "presentation", "hidden", ["presentation"], True]
    assert out["f"] == ["full", "assistant", "visible", ["assistant", "presentation", "meeting"], False]
    assert out["bad"] == [False, False, False], "an unreadable payload is never a guessed model"
    assert out["old"] == "visible", "a Core older than Slice 08 hides nothing"


def test_surfaces_and_retries():
    out = node("return {page:[E.pageSurfaces('hidden'),E.pageSurfaces('__JARVIS_DEVELOPER_SURFACES__'),E.pageSurfaces(null)],"
               "shown:[E.surfaceShown('developer','hidden'),E.surfaceShown('developer','visible'),E.surfaceShown('product','hidden'),E.surfaceShown('developer',null)],"
               "retry:[1,2,3,4,5,9].map(E.retryDelay)}")
    assert out["page"] == ["hidden", None, None]
    assert out["shown"] == [False, True, True, True]
    assert out["retry"] == [2000, 4000, 8000, 16000, 30000, 30000]


def test_the_board_kind_choice_follows_core_and_never_guesses():
    out = node(f"const ready={{status:'ready',model:E.parse({PRESENTATION}).model}};"
               "const kinds=['assistant','presentation','meeting'];"
               "return {ready:kinds.map(k=>B.kindChoiceOf(k,ready).state),"
               "loading:kinds.map(k=>B.kindChoiceOf(k,{status:'loading',model:null,since:1}).state),"
               "none:kinds.map(k=>B.kindChoiceOf(k,null).state),"
               "default:[B.defaultKindOf(ready),B.defaultKindOf(null)],"
               "note:B.kindNoteOf(ready,0),wait:B.kindNoteOf({status:'loading',model:null,since:1000},4200).text,"
               "bad:B.kindNoteOf({status:'error',model:null,error:{code:'core_unreachable',message:'down'}},0),"
               "timeout:B.kindNoteOf({status:'error',model:null,error:{code:'timeout',message:''}},0).text,"
               f"full:B.kindNoteOf({{status:'ready',model:E.parse({FULL}).model}},0)}}")
    assert out["ready"] == ["soon", "available", "soon"]
    assert out["loading"] == ["unknown"] * 3, "nothing is creatable before Core answers"
    assert out["none"] == ["available"] * 3, "without an edition source the control behaves as before"
    assert out["default"] == ["presentation", "assistant"]
    assert out["note"]["tone"] == "info" and out["note"]["text"] == \
        "Cette édition crée des Boards Présentation. Assistant et Réunion arrivent bientôt."
    assert out["wait"] == "Lecture des types de Board auprès de Jarvis… 3 s"
    assert out["bad"]["tone"] == "bad" and out["bad"]["retry"] and "Core ne répond pas" in out["bad"]["text"]
    assert out["bad"]["detail"] == "core_unreachable · down"
    assert "Jarvis n’a pas répondu à temps" in out["timeout"]
    assert out["full"] is None


def test_rows_mark_a_legacy_board_and_only_with_an_edition():
    out = node(f"const ed={{status:'ready',model:E.parse({PRESENTATION}).model}};"
               "const listing={boards:[{board_id:'a',board_kind:'assistant',title:'A'},{board_id:'p',board_kind:'presentation',title:'P'},"
               "{board_id:'z',board_kind:'meeting',title:'Z',status:'archived'}]};const block={available:true,active:{board_id:'p'}};"
               "return {edition:B.rowsOf(listing,block,null,{edition:ed}).map(r=>[r.board_id,r.unavailable]),"
               "archived:B.rowsOf(listing,block,null,{edition:ed,view:'archived'}).map(r=>[r.board_id,r.unavailable]),"
               "before:B.rowsOf(listing,block,null,{}).map(r=>[r.board_id,r.unavailable])}")
    assert out["edition"] == [["a", True], ["p", False]]
    assert out["archived"] == [["z", False]], "an archived Board already never opens; it keeps its own state"
    assert out["before"] == [["a", False], ["p", False]]


def test_settings_show_only_product_categories_and_sections_when_hidden():
    out = node("const reg=R.createRegistry();const m=()=>{};"
               "reg.register({id:'shortcuts',category:'interface_interactions',label:'Raccourcis',save:'self',mount:m});"
               "reg.register({id:'barehands',category:'interface_interactions',label:'Bare Hands',save:'self',surface:'developer',mount:m});"
               "reg.register({id:'providers',category:'connections',label:'Fournisseurs',save:'self',mount:m});"
               "reg.register({id:'prompts',category:'advanced_diagnostics',group:'prompts',label:'Prompts',save:'self',mount:m});"
               "const hidden={developerSurfaces:'hidden'};"
               "const nav=R.shellNavigation(reg,hidden);"
               "let refused=null;try{reg.register({id:'x',category:'connections',label:'X',save:'self',surface:'admin',mount:m})}catch(e){refused=e.code}"
               "return {cats:nav.categories.map(c=>[c.id,c.label,c.items.map(i=>i.id)]),all:R.shellNavigation(reg).categories.length,"
               "shown:['prompts','barehands','shortcuts','advanced_diagnostics','agents_models','voice_audio','nope'].map(t=>R.targetShown(t,reg,hidden)),"
               "visible:R.targetShown('prompts',reg,{developerSurfaces:'visible'}),"
               "cycle:[R.cycleCategory('connections',1,hidden),R.cycleCategory('voice_audio',-1,hidden),R.cycleCategory('connections',1)],"
               "refused}")
    assert out["cats"] == [["voice_audio", "Personnalisation", []], ["memory_knowledge", "Mémoire & Connaissances", []],
                           ["interface_interactions", "Interface & Interactions", ["shortcuts"]],
                           ["connections", "Connexions", ["providers"]]]
    assert out["all"] == 6
    assert out["shown"] == [False, False, True, False, False, True, False]
    assert out["visible"] is True
    assert out["cycle"] == ["voice_audio", "connections", "advanced_diagnostics"]
    assert out["refused"] == "settings_section_invalid"


def test_the_rail_home_and_plain_cards():
    p1 = "pst_" + "1" * 32
    out = node(f"const row={{presentation_id:'{p1}',title:'Bilan',engine:'remotion',type:{{engine:'remotion'}},variant_count:2,work:{{state:'done'}}}};"
               "const slide={...row,engine:'slidecar',type:{engine:'slidecar'}};"
               "const empty=P.modelOf([]);"
               "return {home:[P.shouldShow(empty,{pref:'auto',boardKind:'presentation',home:true}),P.shouldShow(empty,{pref:'auto',boardKind:'assistant',home:true}),"
               "P.shouldShow(empty,{pref:'hidden',boardKind:'presentation',home:true}),P.shouldShow(empty,{pref:'auto',boardKind:'presentation'})],"
               "plain:[P.cardOf(row,0,{plain:true}).type.label,P.cardOf(row,0).type.label,P.cardOf(slide,0,{plain:true}).type.label],"
               "menu:[P.menuModel(row,{developer:false}).map(i=>i.act||i).includes('studio'),P.menuModel(row,{}).map(i=>i.act||i).includes('studio')],"
               "journey:P.JOURNEY.map(s=>[s.step,s.action]),route:P.CREATE_ROUTE}")
    assert out["home"] == [True, False, False, False]
    assert out["plain"] == ["Présentation", "Présentation · Remotion", "Présentation · Slidecar"]
    assert out["menu"] == [False, True]
    assert out["journey"] == [["sources", "dossier"], ["create", "create"], ["scenes", "chat"], ["review", None]]
    assert out["route"] == "/api/presentation-studio/presentations"
