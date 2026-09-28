"""Glisser de plusieurs objets : une commande `translate_selection` (Slice 03, handoff jarvis-mcp-semantic-batch-inspector).

Contrat : `docs/scene-selection-batch.md` §5.2 et §6. Prouvé avec node sur le
fichier même que la page reçoit (`control_center_scene_interact.js`) :

- `groupDelta` = `group_delta` du domaine (parité sur des cas tirés au sort) ;
- `groupMove` garde les écarts enregistrés, écarte les non placés ;
- `commitTranslation` poste **une** commande pour N membres emmenés, pose une
  couche optimiste par membre placé, confirme tout ou défait tout ;
- la page passe par ce chemin pour un glisser de groupe, et garde
  `commitUserGeometry` pour un seul objet.
"""

from __future__ import annotations

import random
import re

from jarvis.domain.scene import SceneGeometry
from jarvis.domain.scene_batch import group_clamp
from tests.unit.test_scene_interaction_logic import PAGE_JS, run_node


def test_the_page_group_delta_is_the_domain_group_delta(tmp_path):
    rng = random.Random(20260925)
    cases = [
        {"boxes": [[0, 0, 20, 10], [30, 15, 10, 10], [-40, -20, 10, 10]], "dx": 10_000, "dy": 0},
        {"boxes": [[200, 0, 10, 10]], "dx": 5, "dy": 0},
        {"boxes": [[200, 0, 10, 10]], "dx": -30, "dy": 0},
        {"boxes": [[-200, 0, 10, 10], [190, 0, 10, 10]], "dx": 50, "dy": 4},
        {"boxes": [[0, 0, 10.05, 10]], "dx": 1_000, "dy": 0},
        {"boxes": [[0, 0, 10, 10]], "dx": 2.37, "dy": -2.37},
        {"boxes": [], "dx": 3, "dy": 3},
        {"boxes": [[0, 0, 10, 10]], "dx": 0.05, "dy": 0},
    ]
    for _ in range(300):
        boxes = [[round(rng.uniform(-300, 300), 1), round(rng.uniform(-200, 200), 1),
                  round(rng.uniform(1, 120), 1), round(rng.uniform(1, 80), 1)] for _ in range(rng.randint(1, 6))]
        cases.append({"boxes": boxes, "dx": rng.uniform(-400, 400), "dy": rng.uniform(-400, 400)})

    result = run_node(tmp_path, """
      return D.map(c=>I.groupDelta(c.boxes.map(([x,y,w,h])=>({x,y,w,h})),c.dx,c.dy));
    """, cases)

    for case, page in zip(cases, result):
        expected = group_clamp([SceneGeometry(*box) for box in case["boxes"]], case["dx"], case["dy"])
        assert (page["dx"], page["dy"], page["clamped"]) == expected, case


def test_a_group_move_keeps_recorded_offsets_and_leaves_unplaced_members_behind(tmp_path):
    result = run_node(tmp_path, """
      return I.groupMove([
        {id:'a',geometry:{x:0,y:0,w:20,h:10}},
        {id:'loose',geometry:null},
        {id:'b',geometry:{x:30,y:15,w:10,h:10}},
      ],7.5,-3);
    """)
    assert result["delta"] == {"dx": 7.5, "dy": -3, "clamped": False}
    assert result["ids"] == ["a", "b"] and result["unplaced"] == ["loose"]
    assert result["targets"] == [{"id": "a", "box": {"x": 7.5, "y": -3, "w": 20, "h": 10}},
                                 {"id": "b", "box": {"x": 37.5, "y": 12, "w": 10, "h": 10}}]


def test_dragging_n_objects_posts_one_translate_selection_and_confirms_every_layer(tmp_path):
    result = run_node(tmp_path, """
      const members=[];
      for(let i=0;i<12;i++)members.push({id:'n'+i,geometry:{x:-100+i*15,y:0,w:10,h:10}});
      members.push({id:'loose',geometry:null});
      const move=I.groupMove(members,4,2);
      const P=I.createPending(30000);const posted=[];let beganWith=null;
      const send=async command=>{posted.push(JSON.parse(JSON.stringify(command)));
        return I.classifyResponse(200,{outcome:'applied',reason:null,revision:9,
          batch:{changed_ids:move.ids,matched_ids:move.ids,unchanged_ids:[],skipped:[],refused:[]}})};
      const running=I.commitTranslation({move,send,pending:P,now:0,began:()=>{beganWith=P.size()}});
      const layersBeforeAnswer=P.size();
      const done=await running;
      const drawn=P.overlay(state([obj('n0','window',{geometry:{x:-100,y:0,w:10,h:10}})],[],8));
      const pruned=P.prune({revision:9},1);
      return {posted,layersBeforeAnswer,beganWith,ok:done.ok,revision:done.revision,batch:done.result.batch.changed_ids.length,
        drawn:drawn.objects.get('n0').geometry,pinned:drawn.objects.get('n0').constraints.pinned_by_user,
        prunedCount:pruned.length,left:P.size()};
    """)
    assert len(result["posted"]) == 1, "un glisser de groupe = une commande"
    command = result["posted"][0]
    assert command == {"schema_version": 1, "op": "translate_selection",
                       "selection": {"ids": [f"n{i}" for i in range(12)]}, "delta": {"dx": 4, "dy": 2}, "pin": True}
    # Couches posées avant la réponse (pas de retour visuel à l'ancienne place).
    assert result["layersBeforeAnswer"] == 12 and result["beganWith"] == 12
    assert result["ok"] is True and result["revision"] == 9 and result["batch"] == 12
    assert result["drawn"] == {"x": -96, "y": 2, "w": 10, "h": 10} and result["pinned"] is True
    assert result["prunedCount"] == 12 and result["left"] == 0


def test_a_refused_group_move_rolls_every_layer_back_and_nothing_moving_sends_nothing(tmp_path):
    result = run_node(tmp_path, """
      const move=I.groupMove([{id:'a',geometry:{x:0,y:0,w:5,h:5}},{id:'b',geometry:{x:10,y:0,w:5,h:5}}],3,3);
      const P=I.createPending(30000);const posted=[];
      const send=async command=>{posted.push(command.op);
        return I.classifyResponse(200,{outcome:'invalid',reason:'unknown_object',revision:4,
          batch:{refused:[{id:'b',reason:'unknown_object',field:'ids'}],matched_ids:[],changed_ids:[],unchanged_ids:[],skipped:[]}})};
      const refused=await I.commitTranslation({move,send,pending:P,now:0});
      const still=I.groupMove([{id:'a',geometry:{x:128,y:0,w:10,h:10}}],50,0);
      const none=await I.commitTranslation({move:still,send,pending:P,now:0});
      const alone=await I.commitTranslation({move:I.groupMove([{id:'loose',geometry:null}],5,5),send,pending:P,now:0});
      return {posted,ok:refused.ok,message:refused.result.message,left:P.size(),stillDelta:still.delta,
        noneSent:none.sent,aloneSent:alone.sent};
    """)
    assert result["posted"] == ["translate_selection"]
    assert result["ok"] is False and result["message"] == "refusé : l'objet n'est plus dans la scène"
    assert result["left"] == 0, "un refus défait toutes les couches"
    # Déjà au bord droit : l'écart borné est nul, rien ne part.
    assert result["stillDelta"] == {"dx": 0, "dy": 0, "clamped": True} and result["noneSent"] is False
    assert result["aloneSent"] is False


def test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged():
    page = PAGE_JS.read_text(encoding="utf-8")
    up = page[page.index("function onPointerUp(event){"):page.index("function cancelGesture(){")]
    group = up[up.index("if(g.mode==='move'&&g.carried.length>1){"):up.index("const sent=[];")]
    assert "commitGroupMove(g.move)" in group and "commitUserGeometry" not in group and "placeOf" not in group
    # Un seul objet : le chemin d'avant, dé-tour de l'orbite compris.
    single = up[up.index("const sent=[];"):]
    assert "placeOf(member.preview,member.node)" in single and "commitUserGeometry(member.id,box,g.mode)" in single
    commit = page[page.index("async function commitGroupMove(move){"):page.index("cadres tenus à mains nues")]
    assert re.search(r"I\.commitTranslation\(\{move,send:sendCommand,pending", commit)
    assert "scene.user_drag_unplaced_skipped" in commit and "reportRefusal(" in commit
    move = page[page.index("function onPointerMove(event){"):page.index("function endGesture(g){")]
    assert "I.groupMove(" in move and "representation:member.representation" in move  # le tour de chacun borne l'écart
    # Refus : le fautif nommé par Core, pas le premier objet emmené.
    assert "batch.refused[0]" in commit and "first_ids:move.ids.slice(0,5)" in commit


def test_a_group_pushed_into_a_corner_keeps_every_orbiting_member_on_screen(tmp_path):
    """Reprise runtime (D1, amendement de l'agent 0 au §5.2) : poussé dans le coin haut gauche, un groupe
    d'objets qui tournent s'arrêtait à la zone sûre, et leur tour sortait de l'écran. L'écart commun
    s'arrête maintenant quand le premier membre toucherait le bord de son tour — le même pour tous."""

    result = run_node(tmp_path, """
      const members=[
        {id:'a',geometry:{x:-10,y:-6,w:6,h:6},representation:'point'},
        {id:'b',geometry:{x:10,y:4,w:40,h:8},representation:'capsule'},
        {id:'c',geometry:{x:-30,y:10,w:6,h:6},representation:'point'},
      ];
      const move=I.groupMove(members,-10000,-10000);
      const safeOnly=I.groupDelta(members.map(m=>m.geometry),-10000,-10000);
      const fits=move.targets.map(t=>I.orbitFits(t.box,members.find(m=>m.id===t.id).representation));
      const offsets=move.targets.map((t,i)=>[t.box.x-members[i].geometry.x,t.box.y-members[i].geometry.y]);
      const windows=I.groupMove(members.map(m=>({...m,representation:'window'})),-10000,-10000);
      /* Un membre posé avant ce contrat, déjà hors de son tour : il ne s'éloigne pas, le groupe peut revenir. */
      const legacy=[{id:'far',geometry:{x:-150,y:-70,w:6,h:6},representation:'point'}];
      const worse=I.groupMove(legacy,-5,-5),back=I.groupMove(legacy,20,10);
      return {delta:move.delta,safeOnly,fits,offsets,windows:windows.delta,worse:worse.delta,back:back.delta};
    """)
    assert all(result["fits"]), "chaque membre qui tourne tient sur son tour après l'écart"
    dx, dy = result["delta"]["dx"], result["delta"]["dy"]
    assert all(offset == [dx, dy] for offset in result["offsets"]), "un seul écart pour tous"
    assert dx < 0 and dy < 0 and result["delta"]["clamped"] is True, "le groupe va vers le coin tant qu'il tient"
    assert (dx, dy) != (result["safeOnly"]["dx"], result["safeOnly"]["dy"]), "le tour borne plus tôt que la zone sûre"
    assert round(dx * 10) == dx * 10 and round(dy * 10) == dy * 10, "au dixième"
    # Des fenêtres ne tournent pas : la zone sûre seule, comme le domaine.
    assert result["windows"] == result["safeOnly"]
    assert result["worse"] == {"dx": 0, "dy": 0, "clamped": True}
    assert result["back"]["dx"] > 0 and result["back"]["dy"] > 0
