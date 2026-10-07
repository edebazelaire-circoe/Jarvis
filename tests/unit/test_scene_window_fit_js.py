"""Ajustement d'une fenêtre du cerveau à son contenu, une seule fois (reprise QA de la Slice 05).

`fitBrainWindows` (control_center_scene_page.js) ramène la géométrie d'une
fenêtre plus haute que son contenu à la hauteur du contenu. Juste après cet
envoi, l'état porte déjà la nouvelle hauteur (aperçu optimiste) alors que le
nœud est encore dessiné à l'ancienne : rapporter l'une à l'autre ré-ajustait
aussitôt une seconde fois, et une fenêtre `jarvis.window` de 300 px dont le
contenu en demandait 217 finissait à 162 px, entrées coupées (vu en preuve
navigateur). La page attend désormais que le dessin corresponde à la géométrie
lue. Exécuté avec node : la vraie fonction de la page, le vrai
`JarvisSceneLayout`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_scene_gesture_shield_js import PAGE_JS, page_function

LAYOUT_JS = PAGE_JS.parent / "control_center_scene_layout.js"

BENCH = r"""
const L=require(PATHS.layout);
const sent=[];
const I={commands:{setGeometry:(id,g)=>({op:'set_geometry',object_id:id,geometry:g})}};
const sendCommand=c=>sent.push(c.geometry.h);
const fitTried=new Set(),userSized=new Set();
const viewportNow=()=>L.viewport(1600,1000);
const el={offsetHeight:300,classList:{contains:n=>n==='sc-window'},dataset:{objectId:'pw'}};
const nodes=new Map([['pw',{el,dragging:false}]]);
let naturalWindowHeight=()=>217;
const item=h=>({object_id:'pw',representation:'window',visibility:'visible',geometry:{x:-140,y:-14,w:56,h}});
let lastState={scene_id:'scene',objects:new Map([['pw',item(60)]])};
"""


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "fit.cjs"
    script.write_text(f"const PATHS={json.dumps({'layout': str(LAYOUT_JS)})};\n" + BENCH
                      + page_function(PAGE_JS.read_text(encoding="utf-8"), "fitBrainWindows")
                      + "\nconsole.log(JSON.stringify((()=>{\n" + body + "\n})()));\n", encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_window_is_fitted_once_and_not_again_before_it_is_redrawn(tmp_path):
    result = run(tmp_path, r"""
      fitBrainWindows();                                   // 300 px dessinés, contenu 217 px
      const first=sent.slice();
      lastState={scene_id:'scene',objects:new Map([['pw',item(first[0])]])};  // aperçu optimiste
      fitBrainWindows();                                   // le nœud a encore 300 px : rien
      const beforeRedraw=sent.slice();
      el.offsetHeight=Math.round(first[0]*5);              // dessiné à la nouvelle hauteur
      fitBrainWindows();
      return {first,beforeRedraw,after:sent.slice()};
    """)
    assert result["first"] == [43.9]
    assert result["beforeRedraw"] == [43.9]
    assert result["after"] == [43.9]


def test_a_stale_drawing_does_not_consume_the_fit(tmp_path):
    result = run(tmp_path, r"""
      el.offsetHeight=250;                                 // dessin d'une autre hauteur que l'état (60 u = 300 px)
      fitBrainWindows();
      const waiting=sent.length;
      el.offsetHeight=300;fitBrainWindows();
      return {waiting,sent};
    """)
    assert result == {"waiting": 0, "sent": [43.9]}


def test_a_short_window_is_never_fitted_below_the_readable_height_a6(tmp_path):
    """Reprise QA S06 F3 : une checklist vidée (contenu de 30 px) ramenait sa fenêtre à 14 unités (70 px) ;
    sous `READABLE.windowHeight` (96 px) la fenêtre se dessine en capsule et son cadre est démonté."""

    result = run(tmp_path, r"""
      const nat=[30,0.5];let natIndex=0;
      naturalWindowHeight=()=>nat[natIndex];
      fitBrainWindows();
      const h=sent[0];
      const vp=viewportNow();
      const drawn=L.nodeGeometry(vp,'window',{x:-140,y:-14,w:56,h});
      return {h,shape:drawn.shape,px:drawn.box.height,readable:L.READABLE.windowHeight,
              direct:L.fitWindowHeight(item(60),30,300),tall:L.fitWindowHeight(item(60),217,300)};
    """)
    assert result["shape"] == "window" and result["px"] >= result["readable"]
    assert result["direct"] == result["h"] and result["tall"] == 43.9  # un contenu lisible garde sa hauteur
