"""Type d'une étoile d'agent (code ou autre) et titre sans fond.

Demande de l'utilisateur (07/10/2026), dite à la voix : distinguer les étoiles
par type, « code » d'un côté et « tout ce qui n'est pas du code » de l'autre
(recherche, document, recherche web, etc.), et mettre le titre à côté de
l'étoile sans fond. Ce que l'on doit constater : chaque étoile d'agent porte une
petite icône de son type, le titre n'a plus de pastille ni de rectangle derrière
lui et reste lisible.

Ce que le modèle de données porte réellement : la catégorie d'une étoile est
son genre (`agent`, `job`) et le sous-agent n'expose pas d'autre type que le
profil que le cerveau écrit en tête de sa description, entre crochets
(`[code]`, `[desktop]`, `[fast]`, `[general]`, `routing_hook.PROFILE_RULE`).
« Recherche », « document » ou « recherche web » n'existent nulle part dans les
données : ils ne sont pas inventés ici, ils tombent dans « autre ».
"""

from __future__ import annotations

import re

from tests.unit.test_scene_renderer_logic import run_node
from tests.unit.test_scene_task_constellation import SETUP


def test_the_profile_in_the_title_gives_the_type_and_leaves_the_title_readable(tmp_path):
    seen = run_node(tmp_path, SETUP + r"""
      const titled=(id,title,extra)=>star(id,Object.assign({payload:{title,summary:'',items:[]}},extra||{}));
      const s=state([titled('a','[code] Rappels proactifs'),titled('b','[general] Topo des tâches'),titled('c','[desktop] Ouvrir le navigateur'),
        titled('d','[fast] Résumer le mail'),titled('e','Inventaire des états'),titled('f','[inconnu] Autre chose'),titled('g','[CODE]   Casse'),
        obj('claude:j','job',{work_ref:ref('j'),payload:{title:'[code] un job',summary:'',items:[]}})],[]);
      const n=byId(draw(s));
      const pick=id=>({type:n['claude:'+id].type,title:n['claude:'+id].title,label:n['claude:'+id].label});
      return {a:pick('a'),b:pick('b'),c:pick('c'),d:pick('d'),e:pick('e'),f:pick('f'),g:pick('g'),job:n['claude:j'].type,job_title:n['claude:j'].title};
    """)
    kinds = {k: (v["type"] or {}).get("kind") for k, v in seen.items() if isinstance(v, dict)}
    assert kinds == {"a": "code", "b": "general", "c": "desktop", "d": "fast", "e": "other", "f": "other", "g": "code"}
    assert {k: v["type"]["family"] for k, v in seen.items() if isinstance(v, dict)} == {
        "a": "code", "b": "other", "c": "other", "d": "other", "e": "other", "f": "other", "g": "code"}
    # Le marqueur passe de l'étiquette à l'icône ; un texte entre crochets inconnu reste du titre.
    assert seen["a"]["title"] == "Rappels proactifs" and seen["g"]["title"] == "Casse"
    assert seen["f"]["title"] == "[inconnu] Autre chose" and seen["e"]["title"] == "Inventaire des états"
    # Le nom accessible dit le type en toutes lettres (l'icône est décorative).
    assert "code" in seen["a"]["label"].lower() and "poste de travail" in seen["c"]["label"].lower()
    # Un job n'est pas un sous-agent : pas de type.
    assert seen["job"] is None and seen["job_title"] == "[code] un job"


def test_the_page_draws_the_type_icon_and_a_label_without_background():
    from tests.unit.test_scene_view_prefs import PAGE_JS

    page = PAGE_JS.read_text(encoding="utf-8")
    assert "typeIcon(node.type)" in page
    point = page.index("if(node.shape==='point'){")
    capsule = page.index("else if(node.shape==='capsule'){", point)
    assert point < page.index("typeIcon(node.type)", point) < capsule
    assert "node.type" in page[page.index("const content=JSON.stringify"):][:600]  # un changement de type redessine le nœud
    # Le titre : aucun fond, aucune pastille, aucun rectangle ; la lisibilité vient d'un halo sombre.
    rule = re.search(r"\n\.sc-label\{([^}]*)\}", page).group(1)
    for banned in ("background", "box-shadow", "border-radius", "padding"):
        assert banned not in rule, banned
    assert "text-shadow" in rule
    root = re.search(r"\n\.sc-task-root \.sc-label\{([^}]*)\}", page).group(1)
    assert "box-shadow" not in root and "background" not in root
    # L'icône n'emprunte aucune couleur d'état de la scène ni de JARVIS : elle reste à l'encre neutre.
    icon = re.search(r"\n\.sc-typeicon\{([^}]*)\}", page).group(1)
    assert "var(--sc-ink)" in icon and "--sc-done" not in icon and "--sc-fail" not in icon and "--sc-warn" not in icon
