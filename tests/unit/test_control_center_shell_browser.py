"""La coque du Control Center, mesurée dans Chrome : deux thèmes, quatre tailles.

Contrat : `docs/control-center-shell.md` (Slice 01 de
jarvis-board-orbital-ui-workspace-rail). `test_control_center_shell_layers.py`
lit les feuilles ; ce fichier relève ce que la cascade **produit** : la page
servie, composée comme `ControlCenter.index` la compose, chargée sans tête à
1440 × 900, 1280 × 720, 900 × 600 et 600 × 800, au thème par défaut
(`circuit-board`) puis au thème Cosmos.

Ce qu'il épingle :

- une seule géométrie : chaque commande est au même endroit et au même rang
  dans les deux thèmes ;
- les commandes que la scène mesure (`JarvisShell.CONTROL_SELECTOR`) comptent
  `#chatTab`, `#interactionModeHud` et `#presentationRail`, et aucune n'en
  recouvre une autre ;
- un panneau latéral ouvert reste sous le lanceur et au-dessus de l'onglet
  Chat ;
- aucune largeur ne fait défiler la page horizontalement.

Harnais : `_interaction_mode_browser.mjs` (CDP, rectangles calculés). Se saute
proprement sans Chrome ni node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_interaction_mode_hud_browser import HARNESS, _chrome, _served_page

VIEWPORTS = ((1440, 900), (1280, 720), (900, 600), (600, 800))
THEMES = ("circuit-board", "cosmos")

#: Monte ce que la page ne montre qu'avec des données : des pastilles, un
#: Board nommé, le rail des présentations (son hôte réel s'il est construit,
#: sinon un hôte posé à sa place et à son rang, avec l'attribut que son module
#: pose). Puis applique le thème.
SETUP = r"""(()=>{
  const theme=%s;
  if(window.JarvisThemeAPI)window.JarvisThemeAPI.activate(theme,{persist:false});
  const pills=document.getElementById('bgPills');
  pills.hidden=false;pills.textContent='';
  for(const [cls,n] of [['bad',3],['warn',5],['ok',12],['',2]]){
    const b=document.createElement('button');b.className=('bgpill '+cls).trim();b.textContent=String(n);pills.appendChild(b)}
  const boards=document.getElementById('boardsHud');
  if(!boards.textContent.trim()){const b=document.createElement('button');b.textContent='BOARD · Présentation Jarvis';boards.appendChild(b)}
  let rail=document.getElementById('presentationRail');
  if(!rail){rail=document.createElement('div');rail.id='presentationRail';rail.setAttribute('data-shell-control','');
    rail.style.cssText='position:fixed;top:76px;left:94px;width:158px;height:120px;z-index:30';document.body.appendChild(rail)}
  rail.hidden=false;
  return document.documentElement.getAttribute('data-jarvis-theme')||'';
})()"""

READ = r"""(()=>{
  const shell=window.JarvisShell;
  const out={selector:shell?shell.CONTROL_SELECTOR:null,controls:[],vw:innerWidth,
    overflowX:document.documentElement.scrollWidth>innerWidth};
  if(!shell)return out;
  for(const el of document.querySelectorAll(shell.CONTROL_SELECTOR)){
    if(el.hidden||el.closest('[hidden]'))continue;
    const cs=getComputedStyle(el);if(cs.display==='none'||cs.visibility==='hidden')continue;
    const r=el.getBoundingClientRect();if(!(r.width>0&&r.height>0))continue;
    out.controls.push({name:el.id?'#'+el.id:'.'+el.classList[0],l:r.left,t:r.top,r:r.right,b:r.bottom});
  }
  const z=s=>{const e=document.querySelector(s);return e?getComputedStyle(e).zIndex:null};
  out.z={topbar:z('.topbar'),dock:z('.dock'),panel:z('#panel'),pills:z('#bgPills'),chat:z('#chatTab'),
    banner:z('.live-banner'),boards:z('#boardsPanel'),tray:z('#boardDropTray')};
  return out;
})()"""

OPEN_PANEL = r"""(()=>{
  const p=document.getElementById('panel');p.classList.add('open');
  const box=e=>{const r=e.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}};
  const out={panel:box(p),dock:box(document.querySelector('.dock')),chat:box(document.getElementById('chatTab')),
    pills:box(document.getElementById('bgPills')),vw:innerWidth};
  p.classList.remove('open');
  return out;
})()"""


def _overlap(a: dict, b: dict) -> bool:
    return min(a["r"], b["r"]) - max(a["l"], b["l"]) > 0.5 and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 0.5


@pytest.fixture(scope="module")
def measured(tmp_path_factory) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    tmp = tmp_path_factory.mktemp("shell")
    page = _served_page(tmp)
    plan = [
        {"width": width, "height": height, "mountPalette": True,
         "actions": [{"a": "eval", "expr": SETUP % json.dumps(theme)},
                     {"a": "eval", "expr": READ},
                     {"a": "eval", "expr": OPEN_PANEL}]}
        for theme in THEMES for width, height in VIEWPORTS
    ]
    done = subprocess.run([node, str(HARNESS), str(page), chrome, json.dumps(plan)],
                          capture_output=True, text=True, encoding="utf-8", timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    steps = json.loads(done.stdout)
    out = {}
    for index, (theme, size) in enumerate((t, s) for t in THEMES for s in VIEWPORTS):
        actions = steps[index]["actions"]
        out[(theme, size)] = {"theme": actions[0]["value"], "read": actions[1]["value"], "panel": actions[2]["value"]}
    return out


@pytest.mark.parametrize("size", VIEWPORTS)
def test_one_geometry_and_one_rank_set_for_both_themes(measured, size):
    circuit, cosmos = measured[("circuit-board", size)], measured[("cosmos", size)]
    assert cosmos["theme"] == "cosmos"
    assert circuit["read"]["z"] == cosmos["read"]["z"]
    assert circuit["read"]["z"] == {"topbar": "31", "dock": "32", "panel": "33", "pills": "40", "chat": "32",
                                    "banner": "35", "boards": "36", "tray": "34"}
    # Les zones : lanceur en haut à droite, onglet Chat en bas à droite, aux
    # mêmes bords dans les deux thèmes (la peau change, la place non).
    for theme in (circuit, cosmos):
        controls = {c["name"]: c for c in theme["read"]["controls"]}
        width = theme["read"]["vw"]
        gutter = 18 if width > 700 else 10
        assert round(width - controls[".dock"]["r"]) == gutter
        assert round(controls[".dock"]["t"]) == gutter
        assert round(width - controls["#chatTab"]["r"]) == gutter


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", VIEWPORTS)
def test_every_control_is_measured_and_none_covers_another(measured, theme, size):
    read = measured[(theme, size)]["read"]
    assert read["selector"] == "[data-shell-control],#sceneLayer>.sc-status"
    names = [c["name"] for c in read["controls"]]
    for required in ("#chatTab", "#interactionModeHud", "#presentationRail", ".dock", "#bgPills",
                     "#barehandsHud", "#barehandsPalette", "#voiceHint", "#boardsHud"):
        assert required in names, (required, names)
    # `#presentationRail` est mesuré (la scène s'arrête contre lui) mais garde sa
    # place héritée sur le bord gauche (left:94px) jusqu'à la Slice 07, qui le
    # range dans la zone de droite : son voisinage n'est pas une promesse de cette
    # Slice, et le rail de capture ne l'évite pas (docs/capture.md).
    placed = [c for c in read["controls"] if c["name"] != "#presentationRail"]
    overlaps = [(a["name"], b["name"]) for i, a in enumerate(placed)
                for b in placed[i + 1:] if _overlap(a, b)]
    assert not overlaps, overlaps
    assert read["overflowX"] is False


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", VIEWPORTS)
def test_an_open_side_panel_stays_under_the_launcher_and_above_the_chat_tab(measured, theme, size):
    seen = measured[(theme, size)]["panel"]
    panel, dock, chat, pills = seen["panel"], seen["dock"], seen["chat"], seen["pills"]
    assert not _overlap(panel, dock), (panel, dock)
    assert not _overlap(panel, chat), (panel, chat)
    assert not _overlap(panel, pills), (panel, pills)
    assert panel["r"] <= seen["vw"]
