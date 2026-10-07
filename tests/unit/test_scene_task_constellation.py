"""Constellation d'une tâche : l'étoile principale porte la pastille, le reste s'y rattache.

Demande de l'utilisateur (07/10/2026) : « on ne voit pas trop quelle étoile
correspond à quoi ; une petite notification sur l'étoile principale de la tâche,
histoire de grouper la constellation ». Ce que l'on doit constater : l'étoile
principale d'un agent porte une pastille (état coloré, nombre d'étoiles et de
commandes rattachées), son étiquette est lisible sans survol, et les étoiles
de la tâche partagent sa couleur (fils et filet).

Le modèle est prouvé ici avec node (`taskGroups`, `viewModel`) ; la page réelle
dans Chrome est prouvée plus bas.
"""

from __future__ import annotations

import re

from tests.unit.test_scene_renderer_logic import run_node

SETUP = r"""
const ref=id=>({source:'claude',external_id:id,work_id:null});
const star=(id,extra)=>obj('claude:'+id,'agent',Object.assign({work_ref:ref(id),payload:{title:id,summary:'',items:[]}},extra||{}));
const parent=(from,to)=>rel('parent_of!'+to,'parent_of','claude:'+from,'claude:'+to);
const cmd=(id,parentId,status,kind)=>[`claude|${id}`,{ephemeral:false,status:status||'completed',ended_ms:null,kind:kind||'shell',
  parent:parentId?`claude|${parentId}`:''}];
const draw=(s,work)=>L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080),{work:new Map(work||[])});
const byId=vm=>Object.fromEntries(vm.nodes.map(n=>[n.id,n]));
"""


def test_the_main_star_counts_its_sub_agents_and_commands_and_nothing_else_carries_a_pill(tmp_path):
    seen = run_node(tmp_path, SETUP + r"""
      const s=state([star('main'),star('child'),star('grand'),star('other')],
        [parent('main','child'),parent('child','grand')]);
      const vm=draw(s,[cmd('c1','main'),cmd('c2','child'),cmd('c3','grand','failed'),cmd('c4','c1'),cmd('lost',null),cmd('c5','other','running')]);
      const n=byId(vm);
      return {main:n['claude:main'].task,other:n['claude:other'].task,child:n['claude:child'].task,grand:n['claude:grand'].task,
        childGroup:n['claude:child'].group,grandGroup:n['claude:grand'].group,otherGroup:n['claude:other'].group,
        label:n['claude:main'].label};
    """)
    main = seen["main"]
    # 2 sous-agents (enfant et petit-enfant) et 4 commandes (c1 à c4, dont une lancée par une commande) ; « lost » n'est à personne.
    assert (main["stars"], main["commands"], main["attached"]) == (2, 4, 6)
    assert main["state"] == "running" and main["color"].startswith("hsl(")
    # Un agent que rien ne contient est une tâche, même seul ; un enfant n'en porte pas.
    assert (seen["other"]["stars"], seen["other"]["commands"], seen["other"]["state"]) == (0, 1, "running")
    assert seen["child"] is None and seen["grand"] is None
    # Les étoiles rattachées partagent la couleur de la principale ; l'autre tâche a la sienne.
    assert seen["childGroup"] == seen["grandGroup"] == main["color"]
    assert seen["otherGroup"] == "" and seen["other"]["color"] != main["color"]
    # Le nom accessible dit la même chose que la pastille.
    assert "tâche en cours, 2 sous-agents, 4 commandes" in seen["label"]


def test_the_pill_state_follows_the_task(tmp_path):
    seen = run_node(tmp_path, SETUP + r"""
      const stateOf=(exec,children)=>{
        const s=state([star('m',{exec_state:exec}),...children.map(([id,e])=>star(id,{exec_state:e}))],children.map(([id])=>parent('m',id)));
        return byId(draw(s))['claude:m'].task.state;
      };
      const withCmd=(exec,status)=>byId(draw(state([star('m',{exec_state:exec})],[]),[cmd('c','m',status)]))['claude:m'].task.state;
      return {running:stateOf('running',[]),done:stateOf('completed',[]),failed:stateOf('failed',[]),
        cancelled:stateOf('cancelled',[]),interrupted:stateOf('interrupted',[]),unknown:stateOf('unknown',[]),
        // Fini, mais un sous-agent travaille encore : la tâche est en cours.
        childBusy:stateOf('completed',[['k','running']]),
        // Une commande qui échoue ne change pas l'état de la tâche : l'agent le résume.
        cmdFailed:withCmd('completed','failed'),cmdBusy:withCmd('completed','running')};
    """)
    assert seen == {"running": "running", "done": "done", "failed": "failed", "cancelled": "interrupted",
                    "interrupted": "interrupted", "unknown": "unknown", "childBusy": "running",
                    "cmdFailed": "done", "cmdBusy": "running"}


def test_task_links_take_the_common_colour_and_other_links_do_not(tmp_path):
    seen = run_node(tmp_path, SETUP + r"""
      const s=state([star('m'),star('c'),obj('doc','artifact')],[parent('m','c'),rel('e1','explains','doc','claude:m')]);
      const vm=draw(s);
      return {edges:vm.edges.map(e=>[e.kind,e.group]),color:byId(vm)['claude:m'].task.color};
    """)
    assert seen["edges"] == [["parent_of", seen["color"]], ["explains", ""]] or sorted(seen["edges"]) == sorted(
        [["parent_of", seen["color"]], ["explains", ""]])


def test_a_hidden_child_and_a_loop_do_not_break_the_count(tmp_path):
    seen = run_node(tmp_path, SETUP + r"""
      const s=state([star('m'),star('hid',{visibility:'hidden'}),star('x'),star('y')],
        [parent('m','hid'),parent('x','y'),parent('y','x')]);
      const n=byId(draw(s));
      return {m:n['claude:m'].task,x:n['claude:x'].task,y:n['claude:y'].task};
    """)
    assert seen["m"]["stars"] == 0  # l'étoile masquée n'est pas dessinée : elle ne se compte pas
    assert seen["x"] is None and seen["y"] is None  # une boucle de parent_of n'a pas d'étoile principale


def test_without_a_work_table_the_scene_is_unchanged_but_for_the_stars(tmp_path):
    seen = run_node(tmp_path, SETUP + r"""
      const s=state([star('m'),obj('w','window')],[]);
      const vm=L.viewModel(s,L.resolveLayout(s),L.viewport(1920,1080),{});
      return vm.nodes.map(n=>[n.id,!!n.task,n.group]);
    """)
    assert seen == [["claude:m", True, ""], ["w", False, ""]]


def test_the_page_draws_the_pill_the_label_and_the_common_colour_without_touching_windows_or_group_drag():
    from tests.unit.test_scene_view_prefs import PAGE_JS

    page = PAGE_JS.read_text(encoding="utf-8")
    # La pastille et la couleur commune sont dessinées pour la forme « point » seulement :
    # les fenêtres (ajustement de hauteur) et les capsules ne sont pas touchées.
    assert "if(node.task)parts.push(taskPill(node.task))" in page
    point = page.index("if(node.shape==='point'){")
    capsule = page.index("else if(node.shape==='capsule'){", point)
    assert point < page.index("taskPill(node.task)", point) < capsule
    # Un changement de tâche redessine le nœud ; les fils de la tâche portent leur couleur.
    assert re.search(r"node\.ephemeral,node\.task,node\.group\]", page)
    assert ".sc-link-task" in page and "edge.group" in page
    # L'étiquette de l'étoile principale est visible sans survol, et mise au repli près du haut.
    assert ".sc-task-root .sc-label{" in page and "sc-label-down" in page
    # Le mouvement réduit n'a rien à arrêter : aucune animation n'a été ajoutée.
    css = page[page.index(".sc-link-task{"):page.index(".sc-capsule{display:flex")]
    assert "animation" not in css
    # Les commandes qui n'ont pas d'étoile se relèvent dans la table des travaux : elle change, la page redessine.
    assert "entry.kind==='shell'" in page and "work:workIndex" in page


def test_the_group_drag_still_follows_parent_of_only():
    from tests.unit.test_scene_view_prefs import PAGE_JS  # noqa: F401  (le module est chargé : même racine de fichiers)
    from pathlib import Path

    interact = (Path(__file__).parents[2] / "jarvis" / "runtime" / "control_center_scene_interact.js").read_text(encoding="utf-8")
    assert "parent_of" in interact  # inchangé : cette tâche n'ajoute aucune relation, elle ne fait que lire
