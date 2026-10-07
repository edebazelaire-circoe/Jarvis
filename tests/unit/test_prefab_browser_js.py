"""Comportement de `jarvis.browser@1` (Tool Brain S7, surface de navigation) dans le vrai shim.

Même banc que `test_prefab_base_behaviors_js.py` : gabarit livré dans le faux DOM, `behavior.js` chargé par le
shim, messages de l'hôte réels. Prouve ce que les outils `surface_*` écrivent et que l'utilisateur voit : page
courante, position dans l'historique, zoom, défilement proportionnel, ouverture dans un onglet par l'hôte
(`open_url`), état vide. Contrat : `docs/tool-brain-contracts.md` §15 et `docs/prefabs.md` › *Base catalogue*.
"""

from __future__ import annotations

from tests.fakes.prefab_js import run_node
from tests.unit.test_prefab_base_behaviors_js import BENCH, _bundle, _stored

ID = "jarvis.browser"


def _cases() -> dict:
    manifest, _ = _bundle(ID)
    trail = [{"url": "https://www.sqlite.org/wal.html", "label": "WAL"},
             {"url": "https://www.sqlite.org/pragma.html"},
             {"url": "https://example.com/a"}]
    return {ID: {
        "empty": _stored(manifest, {}, {}),
        "middle": _stored(manifest, {}, {"history": trail, "index": 1, "zoom": 150, "scroll": 50,
                                         "body": "Des **notes**."}),
        "first": _stored(manifest, {}, {"history": trail, "index": 0}),
        "last": _stored(manifest, {"accent": "#ff7a59"}, {"history": trail, "index": 2, "zoom": 100}),
    }}


def _node(tmp_path, body):
    return run_node(tmp_path, BENCH + body, {"bundles": {ID: _bundle(ID)[1]}, "cases": _cases()})


def test_empty_surface_says_so_and_hides_the_page(tmp_path):
    result = _node(tmp_path, r"""
      const f=prefab('jarvis.browser');f.init('empty');
      return {ready:f.msgs[0].type,page:f.hidden('brw-page'),bar:f.hidden('brw-bar'),empty:f.hidden('brw-empty'),
        text:f.el('brw-empty').textContent,errors:f.errors()};
    """)
    assert result == {"ready": "ready", "page": True, "bar": True, "empty": False, "text": "Aucune page ouverte.",
                      "errors": []}


def test_current_page_position_and_zoom_follow_the_data_on_every_update(tmp_path):
    result = _node(tmp_path, r"""
      const f=prefab('jarvis.browser');f.init('middle');
      const middle={host:f.el('brw-host').textContent,url:f.el('brw-url').textContent,nav:f.el('brw-nav').textContent,
        back:f.el('brw-nav').getAttribute('data-back'),fwd:f.el('brw-nav').getAttribute('data-forward'),
        zoom:f.el('brw-zoom').textContent,zoomed:f.el('brw-zoom').getAttribute('data-zoomed'),var:f.el('brw').style.vars['--brw-zoom'],
        accent:f.vars()['--jv-accent'],notes:f.hidden('brw-body')};
      f.update('first');
      const first={host:f.el('brw-host').textContent,nav:f.el('brw-nav').textContent,
        back:f.el('brw-nav').getAttribute('data-back'),fwd:f.el('brw-nav').getAttribute('data-forward'),
        zoomed:f.el('brw-zoom').getAttribute('data-zoomed'),notes:f.hidden('brw-body')};
      f.update('last');
      const last={host:f.el('brw-host').textContent,nav:f.el('brw-nav').textContent,
        fwd:f.el('brw-nav').getAttribute('data-forward'),accent:f.vars()['--jv-accent']};
      f.update('empty');
      return {middle,first,last,emptied:{page:f.hidden('brw-page'),empty:f.hidden('brw-empty')},errors:f.errors()};
    """)
    assert result["middle"] == {"host": "sqlite.org", "url": "https://www.sqlite.org/pragma.html", "nav": "2 / 3",
                                "back": "on", "fwd": "on", "zoom": "150 %", "zoomed": "on", "var": "1.5",
                                "accent": "#6ee7ff", "notes": False}
    assert result["first"] == {"host": "WAL", "nav": "1 / 3", "back": "off", "fwd": "on", "zoomed": "off",
                               "notes": True}
    assert result["last"] == {"host": "example.com", "nav": "3 / 3", "fwd": "off", "accent": "#ff7a59"}
    assert result["emptied"] == {"page": True, "empty": False} and result["errors"] == []


def test_scroll_is_a_percentage_of_the_scrollable_height_and_is_reapplied_on_update(tmp_path):
    result = _node(tmp_path, r"""
      const f=prefab('jarvis.browser');
      const page=f.el('brw-page');
      Object.assign(page,{scrollHeight:1100,clientHeight:100,scrollTop:0});
      f.init('middle');
      const half=page.scrollTop;
      f.update('first');
      const top=page.scrollTop;
      Object.assign(page,{scrollHeight:80,clientHeight:100});   // content shorter than the frame: nothing to scroll
      f.update('middle');
      return {half,top,short:page.scrollTop,errors:f.errors()};
    """)
    assert (result["half"], result["top"], result["short"], result["errors"]) == (500, 0, 0, [])


def test_the_page_opens_in_a_tab_through_the_host_on_click_and_keyboard_only(tmp_path):
    result = _node(tmp_path, r"""
      const f=prefab('jarvis.browser');f.init('middle');
      const link=f.el('brw-open');
      link.click();const enter=link.key('Enter');const space=link.key(' ');const other=link.key('a');
      f.update('empty');link.click();   // no page: nothing to open
      return {opened:f.opened(),prevented:[enter.defaultPrevented,space.defaultPrevented,other.defaultPrevented],
        href:link.hasAttribute('href'),role:link.getAttribute('role'),errors:f.errors()};
    """)
    assert result["opened"] == ["https://www.sqlite.org/pragma.html"] * 3
    assert result["prevented"] == [True, True, False]
    assert result["href"] is False and result["role"] == "link" and result["errors"] == []
