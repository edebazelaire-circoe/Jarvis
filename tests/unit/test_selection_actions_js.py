"""Actions de Sélection de la roue, modèle pur (`control_center_scene_interact.js`, node).

Handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 06. Contrat :
`docs/scene-selection-batch.md` › *Selection actions (wheel)*. Ce fichier tient ce
que le sous-menu Sélection montre selon la sélection (vide, simple, mixte,
au-delà de 20), ce que dit la ligne Ranger selon l'aperçu Dossier et le Board
affiché, les commandes atomiques (jamais de charge) et le compte rendu d'un
Ranger. Le parcours réel dans Chrome : `test_selection_actions_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

INTERACT = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_scene_interact.js"

PRELUDE = r"""
const I=require(%s);
const obj=(id,kind,rep,extra)=>Object.assign({object_id:id,kind,representation:rep,visibility:'visible',
  exec_state:'running',payload:{title:id}},extra||{});
const state=items=>({objects:new Map(items.map(o=>[o.object_id,o]))});
const ids=rows=>rows.map(r=>r.id);
""" % json.dumps(str(INTERACT))


def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run([node, "-e", PRELUDE + f"process.stdout.write(JSON.stringify((()=>{{{body}}})()))"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_no_selection_shows_a_fact_and_the_hidden_count_only():
    out = _node("""
      const s=state([obj('a','agent','point'),obj('h','agent','point',{visibility:'hidden',payload:{title:'Caché'}})]);
      return {some:I.selectionActions(s,[],{hidden:1}),none:I.selectionActions(state([obj('a','agent','point')]),[],{hidden:0}),
        stale:ids(I.selectionActions(s,['gone'],{hidden:1}))};""")
    assert [r["id"] for r in out["some"]] == ["selection-none", "hidden"]
    assert out["some"][0]["status"] is True and out["some"][0]["tone"] == "off"
    hidden = out["some"][1]
    assert hidden["label"] == "Masqués (1)" and hidden["menu"] is True
    assert [r["id"] for r in hidden["rows"]] == ["ghosts", "show-all", "show:h"]
    assert hidden["rows"][0]["toggle"] is True and hidden["rows"][0]["checked"] is False
    assert [r["id"] for r in out["none"]] == ["selection-none", "hidden-none"]
    # Une sélection dont les objets ont disparu vaut une sélection vide.
    assert out["stale"] == ["selection-none", "hidden"]


def test_a_selection_offers_the_four_distinct_gestures_and_says_what_each_does():
    out = _node("""
      const s=state([obj('w','window','window',{payload:{title:'Note'}})]);
      return I.selectionActions(s,['w'],{hidden:0,boardId:'b',backing:{status:'ready',board_active:true,objects:{w:{rangeable:true}}}});""")
    assert [r["id"] for r in out] == ["selection-count", "ranger", "hide", "hidden-none", "form", "remove"]
    rows = {r["id"]: r for r in out}
    assert rows["selection-count"]["label"] == "1 objet sélectionné" and rows["selection-count"]["note"] == "1 fenêtre"
    assert "disabled" not in rows["ranger"] and rows["ranger"]["label"] == "Ranger dans le Dossier"
    # Masquer : temporaire, récupérable, et jamais une entrée du Dossier.
    assert rows["hide"]["label"] == "Masquer" and "rien n’entre dans le Dossier" in rows["hide"]["detail"]
    # Changer la forme : la forme actuelle cochée et inactive, rien n'est copié.
    assert "rien n’est copié" in rows["form"]["detail"]
    assert [(r["label"], r["checked"], r["disabled"]) for r in rows["form"]["rows"]] == [
        ("Étoile", False, False), ("Capsule", False, False), ("Fenêtre", True, True)]
    # Retirer du Board : le libellé dit qu'il retire une représentation, jamais « supprimer ».
    assert rows["remove"]["label"] == "Retirer du Board…" and rows["remove"]["note"] == "archive la représentation"
    assert all("upprim" not in json.dumps(r, ensure_ascii=False) for r in out)


def test_mixed_selection_counts_forms_and_ranger_says_how_many_go():
    out = _node("""
      const s=state([obj('w','window','window',{payload:{title:'Note',source_path:'C:/x/memory/a.md'}}),obj('a','agent','point')]);
      const backing={status:'ready',board_active:true,objects:{w:{rangeable:true},
        a:{rangeable:false,code:'dossier_not_eligible',message:'Cet objet ne se range pas dans le Dossier ; il reste sur le Board.'}}};
      return I.selectionActions(s,['w','a'],{hidden:0,boardId:'b',backing});""")
    rows = {r["id"]: r for r in out}
    assert rows["selection-count"]["label"] == "2 objets sélectionnés"
    assert rows["selection-count"]["note"] == "1 fenêtre · 1 étoile"
    assert rows["ranger"]["note"] == "1 sur 2" and "il reste sur le Board" in rows["ranger"]["detail"]
    assert "disabled" not in rows["ranger"]
    assert rows["form"]["note"] == "mixte" and not any(r["checked"] for r in rows["form"]["rows"])
    # Une source durable (fichier de mémoire) : « la source reste ».
    assert rows["remove"]["note"] == "la source reste" and "reste dans le Dossier" in rows["remove"]["detail"]


def test_ranger_row_never_promises_what_ranger_would_refuse():
    out = _node("""
      const s=state([obj('w','window','window'),obj('a','agent','point')]);
      const ready={status:'ready',board_active:true,objects:{a:{rangeable:false,message:'Cet objet ne se range pas.'}}};
      const big=state(Array.from({length:21},(_,i)=>obj('o'+i,'agent','point')));
      const row=(st,sel,ctx)=>I.selectionActions(st,sel,{hidden:0,...ctx}).find(r=>r.id==='ranger');
      return {
        noBoard:row(s,['w'],{backing:ready}),
        inactive:row(s,['w'],{boardId:'b',backing:{status:'ready',board_active:false,board_message:'Ce Board n’est pas le Board affiché.',objects:{w:{rangeable:true}}}}),
        nothing:row(s,['a'],{boardId:'b',backing:ready}),
        loading:row(s,['w'],{boardId:'b',backing:{status:'loading'}}),
        failed:row(s,['w'],{boardId:'b',backing:{status:'failed',message:'http_503'}}),
        tooMany:row(big,Array.from({length:21},(_,i)=>'o'+i),{boardId:'b',backing:{status:'idle'}}),
        max:I.MAX_RANGER_IDS,
      };""")
    assert out["max"] == 20
    assert out["noBoard"]["disabled"] is True and out["noBoard"]["note"] == "Board actif inconnu"
    # Polish S05 8 : l'aperçu par objet dit « rangeable », le Board non affiché l'emporte.
    assert out["inactive"]["disabled"] is True and out["inactive"]["detail"] == "Ce Board n’est pas le Board affiché."
    assert out["nothing"]["disabled"] is True and out["nothing"]["detail"] == "Cet objet ne se range pas."
    assert out["loading"]["tone"] == "wait" and "disabled" not in out["loading"]
    assert out["failed"]["tone"] == "unknown" and "http_503" in out["failed"]["detail"] and "disabled" not in out["failed"]
    assert out["tooMany"]["disabled"] is True and "20 objets" in out["tooMany"]["detail"]


def test_all_hidden_selection_offers_reafficher_and_run_blocks_remove():
    out = _node("""
      const s=state([obj('h','window','window',{visibility:'hidden'})]);
      return I.selectionActions(s,['h'],{hidden:1,boardId:'b',runBlocked:true,backing:{status:'idle'}});""")
    rows = {r["id"]: r for r in out}
    assert "hide" not in rows and rows["show-selection"]["label"] == "Réafficher"
    # Pendant une lecture de Variantes, la confirmation s'ouvrirait sous le Studio (S02 B1) : refusé, avec la raison.
    assert rows["remove"]["disabled"] is True and "Variantes" in rows["remove"]["detail"]


def test_hidden_list_names_six_then_counts_the_rest():
    out = _node("""
      const s=state(Array.from({length:9},(_,i)=>obj('h'+i,'agent','point',{visibility:'hidden',payload:{title:'Masqué '+i}})));
      return I.selectionActions(s,[],{hidden:9,ghosts:true}).find(r=>r.id==='hidden');""")
    assert out["note"] == "fantômes visibles"
    assert [r["id"] for r in out["rows"]][:2] == ["ghosts", "show-all"] and out["rows"][0]["checked"] is True
    assert len(out["rows"]) == 9 and out["rows"][-1] == {"id": "hidden-more", "label": "… et 3 autres", "status": True,
                                                         "tone": "off", "icon": "eye_off"}


def test_selection_commands_are_atomic_and_carry_no_payload():
    out = _node("""
      return {patch:I.commands.patchSelection(['a','b'],{visibility:'hidden'}),
        rep:I.commands.patchSelection(['a'],{representation:'point'}),archive:I.commands.archiveSelection(['a','b']),
        toggle:I.keyIntent({key:' ',ctrlKey:true}),plain:I.keyIntent({key:' '})};""")
    assert out["patch"] == {"schema_version": 1, "op": "patch_selection", "selection": {"ids": ["a", "b"]},
                            "changes": {"visibility": "hidden"}}
    assert out["rep"]["changes"] == {"representation": "point"} and "payload" not in out["rep"]
    assert out["archive"] == {"schema_version": 1, "op": "archive_selection", "selection": {"ids": ["a", "b"]}}
    assert out["toggle"] == {"type": "toggle"} and out["plain"] is None


def test_ranger_report_says_stored_kept_and_each_refusal():
    out = _node("""
      const body={results:[
        {object_id:'a',status:'stored',archived:true},
        {object_id:'b',status:'stored',archived:false,code:'dossier_changed_meanwhile',message:'Le contenu a changé pendant le rangement.'},
        {object_id:'c',status:'refused',code:'dossier_not_eligible',message:'Cet objet ne se range pas.'}]};
      return {mixed:I.rangerReport(body,id=>'Titre '+id),ok:I.rangerReport({results:[{object_id:'a',status:'stored',archived:true}]}),
        refusedOnly:I.rangerReport({results:[{object_id:'c',status:'refused',message:'Non.'}]}),
        whole:I.RANGER_REQUEST_REFUSALS.dossier_board_not_active};""")
    m = out["mixed"]
    assert m["title"] == "1 objet rangé dans le Dossier · 1 gardé sans retrait · 1 refus"
    assert m["lines"] == ["« Titre b » : Le contenu a changé pendant le rangement.", "« Titre c » : Cet objet ne se range pas."]
    assert (m["removed"], m["kept"], m["refused"], m["kind"]) == (["a"], ["b"], ["c"], "warn")
    assert out["ok"]["kind"] == "ok" and out["ok"]["lines"] == []
    assert out["refusedOnly"]["kind"] == "bad" and out["refusedOnly"]["title"] == "1 refus"
    assert "rien n’a été rangé" in out["whole"]


def test_durable_source_is_a_file_or_a_registry_artifact():
    out = _node("""
      return [I.durableSourceOf(obj('a','window','window',{payload:{registry_artifact_id:'jart_x'}})),
        I.durableSourceOf(obj('b','window','window',{payload:{source_path:'C:/m.md'}})),
        I.durableSourceOf(obj('c','artifact','window'))];""")
    assert out == ["artifact", "file", None]


def test_ranger_says_the_precise_reason_core_gives_for_an_object():
    """QA S06 polish 6 (Slice 08) : la raison de l'objet (`backing.reason`) suit la phrase du code, dans la ligne
    Ranger comme dans le rapport ; une raison déjà dite n'est pas répétée."""
    out = _node("""
      const s=state([obj('g','group','window')]);
      const ready={status:'ready',board_active:true,objects:{g:{rangeable:false,code:'dossier_not_eligible',
        message:'Cet objet ne se range pas dans le Dossier ; il reste sur le Board.',
        reason:"un groupe n'est qu'un cadre : rangez ses objets un par un"}}};
      const row=I.selectionActions(s,['g'],{hidden:0,boardId:'b',backing:ready}).find(r=>r.id==='ranger');
      const report=I.rangerReport({results:[{object_id:'g',status:'refused',code:'dossier_not_eligible',
        message:'Cet objet ne se range pas dans le Dossier ; il reste sur le Board.',
        reason:"un groupe n'est qu'un cadre : rangez ses objets un par un"}]});
      const same=I.selectionActions(s,['g'],{hidden:0,boardId:'b',backing:{status:'ready',board_active:true,
        objects:{g:{rangeable:false,message:'Vide.',reason:'vide'}}}}).find(r=>r.id==='ranger');
      return {row,report,same};""")
    assert out["row"]["disabled"] is True
    assert out["row"]["detail"] == ("Cet objet ne se range pas dans le Dossier ; il reste sur le Board. "
                                    "Un groupe n'est qu'un cadre : rangez ses objets un par un.")
    assert "Un groupe n'est qu'un cadre" in json.dumps(out["report"], ensure_ascii=False)
    assert out["same"]["detail"] == "Vide."


def test_ranger_says_when_it_links_a_registry_artifact_to_this_board():
    """Polish S05 9 (Slice 08) : Ranger d'une fenêtre d'Artifact que ce Board ne liait pas le dit."""
    out = _node("""
      return I.rangerReport({results:[{object_id:'w',status:'stored',archived:true,backing:'artifact',action:'linked'},
        {object_id:'v',status:'stored',archived:true,backing:'artifact',action:'confirmed'}]},id=>id==='w'?'Transcription':'Plan');""")
    assert out["kind"] == "ok" and out["removed"] == ["w", "v"]
    assert out["lines"] == ["« Transcription » : l’Artifact est désormais aussi dans le Dossier de ce Board."]
