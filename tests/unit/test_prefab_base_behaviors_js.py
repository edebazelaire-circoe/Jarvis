"""Comportement des prefabs de base dans le shim (prefab-foundation, Slice 05).

Chaque prefab livré (`jarvis/prefabs/base/<id>/1/`) est exécuté tel quel :
son gabarit est posé dans le faux DOM, son `behavior.js` est chargé par le vrai
shim (`createShim`), et l'hôte lui parle avec les vrais messages
(`JarvisPrefabProtocol.hostMessage`, blocs markdown calculés par
`markdownBlocksOf`, l'analyseur unique de la page). Les valeurs envoyées sont
celles que Core stocke : validées et complétées de leurs défauts par
`validate_value`. Cas vides, un élément, beaucoup ; markdown par blocs ; accent
appliqué depuis les props ; pagination clavier du document ; `row_selected` du
tableau au clic et au clavier. Contrat : `docs/prefabs.md` › *Base catalogue*.
"""

from __future__ import annotations

import json
from pathlib import Path

import jarvis
from jarvis.domain.prefab import MAX_MANIFEST_BYTES, decode_json_text, parse_bundle, validate_value
from tests.fakes.prefab_js import run_node

PACKAGE = Path(jarvis.__file__).resolve().parent / "prefabs" / "base"

BENCH = r"""
/* Un cadre : gabarit livré dans le faux DOM, comportement livré chargé par le shim. */
function prefab(id){
  const B=D.bundles[id];
  const doc=new FakeDocument();
  parseTemplate(doc.body,B.template);
  const msgs=[];let deliver=null;
  const shim=Shim.createShim({post:(m)=>msgs.push(JSON.parse(JSON.stringify(m))),listen:(fn)=>{deliver=fn},document:doc});
  const win=new FakeWindow();
  const behavior=new Function('jarvis','document','window','requestAnimationFrame',B.behavior);
  shim.load((api)=>behavior(api,doc,win,undefined));
  const fields=(c)=>({props:c.props,data:c.data,theme:H.DEFAULT_THEME,blocks:P.markdownBlocksOf(B.manifest,c.props,c.data)});
  return {
    doc,win,msgs,
    init(name){deliver(P.hostMessage('init',Object.assign({instance:{object_id:'o1',prefab:{id,version:1},mode:'scene'}},fields(D.cases[id][name]))))},
    update(name){deliver(P.hostMessage('update',fields(D.cases[id][name])))},
    el:(elId)=>doc.getElementById(elId),
    hidden:(elId)=>doc.getElementById(elId).hasAttribute('hidden'),
    vars:()=>doc.documentElement.style.vars,
    errors:()=>msgs.filter(m=>m.type==='error'),
    events:()=>msgs.filter(m=>m.type==='event').map(m=>[m.name,m.payload]),
    opened:()=>msgs.filter(m=>m.type==='open_url').map(m=>m.url),
  };
}
const texts=(nodes)=>nodes.map(n=>n.textContent);
"""


def _bundle(prefab_id: str):
    folder = PACKAGE / prefab_id / "1"
    text = {name: (folder / name).read_text(encoding="utf-8")
            for name in ("manifest.json", "template.html", "style.css", "behavior.js")}
    manifest = json.loads(text["manifest.json"])
    bundle = parse_bundle(decode_json_text(text["manifest.json"], MAX_MANIFEST_BYTES, "manifest"),
                          text["template.html"], text["style.css"], text["behavior.js"])
    return bundle.manifest, {"manifest": manifest, "template": text["template.html"], "behavior": text["behavior.js"]}


def _stored(manifest, props, data):
    """Ce que Core stocke pour une instance : valeurs validées, défauts appliqués."""

    props, problems = validate_value(manifest.props, props, "props")
    data, more = validate_value(manifest.data, data, "data")
    assert problems + more == (), problems + more
    return {"props": props, "data": data}


LONG_DOC = "\n\n".join(f"## Partie {n}\n\n" + ("Une phrase assez longue pour passer à la ligne dans une fenêtre. " * 6)
                       for n in range(1, 25))


def cases() -> dict:
    window, _ = _bundle("jarvis.window")
    document, _ = _bundle("jarvis.document")
    table, _ = _bundle("jarvis.table")
    many_items = [{"label": f"Entrée {n} " + "avec un libellé long qui passe à la ligne " * (n % 3), "ref": f"r{n}",
                   **({"url": f"https://www.example.com/p/{n}"} if n % 4 == 0 else {})} for n in range(64)]
    columns = [{"label": f"Col {n}", "align": ("left", "right", "center")[n % 3]} for n in range(8)]
    return {
        "jarvis.window": {
            "empty": _stored(window, {}, {}),
            "one": _stored(window, {"accent": "#ff7a59"}, {"items": [{"label": "Seule entrée"}]}),
            "many": _stored(window, {"density": "compact"}, {"body": "**Gras** et `code`\n\n- un\n- deux",
                                                              "items": many_items}),
            "linked": _stored(window, {}, {"items": [{"label": "Doc", "url": "https://www.sqlite.org/wal.html",
                                                      "ref": "WAL"}]}),
            "sample": _stored(window, window.sample_props, window.sample_data),
        },
        "jarvis.document": {
            "empty": _stored(document, {}, {"body": ""}),
            "one": _stored(document, {"scale": "l", "accent": "#6fe3a4"}, {"body": "Un seul paragraphe."}),
            "many": _stored(document, {"scale": "s"}, {"body": LONG_DOC}),
            "bogus_scale": {"props": {"scale": "xl", "accent": "#6ee7ff"}, "data": {"body": "x"}},
        },
        "jarvis.table": {
            "empty": _stored(table, {}, {"columns": [{"label": "Nom"}]}),
            "one": _stored(table, {"accent": "#c6a0ff"}, {"columns": [{"label": "Nom"}, {"label": "Taille", "align":
                                                                                            "right"}],
                                                            "rows": [["a.txt"]]}),
            "many": _stored(table, {"zebra": False},
                            {"columns": columns, "rows": [[f"r{r}c{c}" for c in range(8)] for r in range(64)]}),
            "fewer": _stored(table, {}, {"columns": [{"label": "Nom"}], "rows": [["x"], ["y"]]}),
            "paths": _stored(table, {}, {"columns": [{"label": "Fichier"}, {"label": "Statut"}],
                                         "rows": [["jarvis/prefabs/base/module_01.py", "modifié"],
                                                  ["https://example.com/a?b=c", "ok"]]}),
        },
    }


def node(tmp_path, body):
    bundles = {prefab_id: _bundle(prefab_id)[1] for prefab_id in ("jarvis.window", "jarvis.document", "jarvis.table")}
    return run_node(tmp_path, BENCH + body, {"bundles": bundles, "cases": cases()})


def test_every_base_prefab_loads_announces_ready_and_follows_the_accent_prop(tmp_path):
    result = node(tmp_path, r"""
      const out={};
      for(const [id,name,accent] of [['jarvis.window','one','#ff7a59'],['jarvis.document','one','#6fe3a4'],['jarvis.table','one','#c6a0ff']]){
        const f=prefab(id);f.init(name);
        out[id]={ready:f.msgs[0].type,accent:f.vars()['--jv-accent'],prop:f.vars()['--jv-prop-accent'],errors:f.errors()};
      }
      const d=prefab('jarvis.window');d.init('empty');
      out.defaulted=d.vars()['--jv-accent'];
      return out;
    """)
    for prefab_id, accent in (("jarvis.window", "#ff7a59"), ("jarvis.document", "#6fe3a4"), ("jarvis.table", "#c6a0ff")):
        assert result[prefab_id] == {"ready": "ready", "accent": accent, "prop": accent, "errors": []}
    assert result["defaulted"] == "#6ee7ff"


def test_window_renders_empty_one_and_many_with_markdown_through_blocks(tmp_path):
    result = node(tmp_path, r"""
      const f=prefab('jarvis.window');
      f.init('empty');
      const empty={body:f.hidden('win-body'),items:f.hidden('win-items'),empty:f.hidden('win-empty'),
        text:f.el('win-empty').textContent,density:f.el('win').getAttribute('data-density')};
      f.update('one');
      const one={body:f.hidden('win-body'),items:f.hidden('win-items'),empty:f.hidden('win-empty'),
        labels:texts(f.el('win-items').byClass('win-label')),refs:f.el('win-items').byClass('win-ref').length};
      f.update('many');
      const list=f.el('win-items');
      const md=f.el('win-body');
      const many={rows:list.children.length,links:list.byClass('win-link').length,refs:list.byClass('win-ref').length,
        hosts:[...new Set(texts(list.byClass('win-host')))],density:f.el('win').getAttribute('data-density'),
        mdClass:md.className,strong:md.find(n=>n.tagName==='STRONG').textContent,code:md.byClass('jv-md-code').length,
        list:md.find(n=>n.tagName==='UL').children.length,body:f.hidden('win-body'),empty:f.hidden('win-empty')};
      f.update('empty');
      const again={rows:f.el('win-items').children.length,items:f.hidden('win-items'),empty:f.hidden('win-empty')};
      return {empty,one,many,again,errors:f.errors()};
    """)
    assert result["empty"] == {"body": True, "items": True, "empty": False, "text": "Aucun contenu.",
                               "density": "comfortable"}
    assert result["one"] == {"body": True, "items": False, "empty": True, "labels": ["Seule entrée"], "refs": 0}
    many = result["many"]
    assert (many["rows"], many["links"], many["refs"], many["hosts"]) == (64, 16, 64, ["example.com"])
    assert many["density"] == "compact" and "jv-md" in many["mdClass"].split()
    assert (many["strong"], many["code"], many["list"], many["body"], many["empty"]) == ("Gras", 1, 2, False, True)
    assert result["again"] == {"rows": 0, "items": True, "empty": False}
    assert result["errors"] == []



def test_window_reports_its_natural_height_and_fades_body_and_entries_like_the_legacy_window(tmp_path):
    """Reprise QA S05 F4 : `.win` remplit le cadre (corps qui défile, entrées en bas) ; la cale `win-sizer`
    porte la hauteur naturelle, mesurée sous `data-measure` (sans flex ni plafond), à chaque rendu et à
    chaque changement de taille du cadre ; `data-more` sur le corps et la liste tant qu'il en reste."""

    result = node(tmp_path, r"""
      const f=prefab('jarvis.window');
      const root=f.el('win'),body=f.el('win-body'),list=f.el('win-items'),empty=f.el('win-empty'),sizer=f.el('win-sizer');
      const measured=[];
      const natural={'win-body':120,'win-items':300,'win-empty':18};
      for(const el of [body,list,empty])Object.defineProperty(el,'offsetHeight',{get(){
        measured.push([el.id,root.hasAttribute('data-measure')]);return natural[el.id]}});
      Object.assign(body,{scrollHeight:400,clientHeight:100,scrollTop:0});
      Object.assign(list,{scrollHeight:300,clientHeight:150,scrollTop:0});
      root.clientHeight=250;                               // le cadre est plus court que le contenu
      f.init('many');
      const first={sizer:sizer.style.height,measuring:root.hasAttribute('data-measure'),
        clamped:root.hasAttribute('data-clamped'),bodyNatural:root.style.getPropertyValue('--win-body-natural'),
        allMeasured:measured.every(m=>m[1]),bodyMore:body.hasAttribute('data-more'),listMore:list.hasAttribute('data-more')};
      body.scrollTop=300;list.scrollTop=150;
      for(const el of [body,list])for(const fn of el.listeners.scroll||[])fn({type:'scroll'});
      const scrolled={bodyMore:body.hasAttribute('data-more'),listMore:list.hasAttribute('data-more')};
      natural['win-items']=260;root.clientHeight=380;      // fenêtre agrandie : plus rien n'est plafonné
      for(const fn of f.win.listeners.resize||[])fn({type:'resize'});
      const resized=[sizer.style.height,root.hasAttribute('data-clamped')];
      f.update('empty');
      const emptied={sizer:sizer.style.height,listMore:list.hasAttribute('data-more')};
      return {first,scrolled,resized,emptied,resizeListeners:f.win.count('resize'),errors:f.errors()};
    """)
    assert result["first"] == {"sizer": "420px", "measuring": False, "clamped": True, "bodyNatural": "120px",
                               "allMeasured": True, "bodyMore": True, "listMore": True}
    assert result["scrolled"] == {"bodyMore": False, "listMore": False}
    assert result["resized"] == ["380px", False]
    assert result["emptied"] == {"sizer": "18px", "listMore": False}
    assert result["resizeListeners"] == 1 and result["errors"] == []


def test_window_entries_open_their_url_through_the_host_on_click_and_keyboard(tmp_path):
    result = node(tmp_path, r"""
      const f=prefab('jarvis.window');f.init('linked');
      const link=f.el('win-items').byClass('win-link')[0];
      const click=link.click();
      const enter=link.key('Enter');const space=link.key(' ');const other=link.key('a');
      return {opened:f.opened(),prevented:[click.defaultPrevented,enter.defaultPrevented,space.defaultPrevented,other.defaultPrevented],
        href:link.hasAttribute('href'),role:link.getAttribute('role'),tab:link.getAttribute('tabindex'),
        label:link.getAttribute('aria-label'),host:link.byClass('win-host')[0].textContent,ref:f.el('win-items').byClass('win-ref')[0].textContent};
    """)
    assert result["opened"] == ["https://www.sqlite.org/wal.html"] * 3
    assert result["prevented"] == [True, True, True, False]
    assert result["href"] is False and result["role"] == "link" and result["tab"] == "0"
    assert result["host"] == "sqlite.org" and result["ref"] == "WAL"
    assert result["label"].startswith("Doc — sqlite.org")


def test_document_renders_empty_one_and_a_long_text_with_its_scale(tmp_path):
    result = node(tmp_path, r"""
      const f=prefab('jarvis.document');
      f.init('empty');
      const empty={doc:f.hidden('doc'),empty:f.hidden('doc-empty'),text:f.el('doc-empty').textContent};
      f.update('one');
      const one={doc:f.hidden('doc'),empty:f.hidden('doc-empty'),scale:f.el('doc').getAttribute('data-scale'),
        paragraphs:f.el('doc').byClass('jv-md-p').length,text:f.el('doc').textContent};
      f.update('many');
      const many={scale:f.el('doc').getAttribute('data-scale'),headings:f.el('doc').byClass('jv-md-h2').length,
        paragraphs:f.el('doc').byClass('jv-md-p').length,chars:f.el('doc').textContent.length};
      f.update('bogus_scale');
      return {empty,one,many,bogus:f.el('doc').getAttribute('data-scale'),errors:f.errors()};
    """)
    assert result["empty"] == {"doc": True, "empty": False, "text": "Document vide."}
    assert result["one"] == {"doc": False, "empty": True, "scale": "l", "paragraphs": 1, "text": "Un seul paragraphe."}
    assert result["many"]["scale"] == "s" and result["many"]["headings"] == 24 and result["many"]["paragraphs"] == 24
    assert result["many"]["chars"] > 9000
    assert result["bogus"] == "m" and result["errors"] == []


def test_document_pages_with_the_keyboard_and_shows_the_reading_position(tmp_path):
    result = node(tmp_path, r"""
      const f=prefab('jarvis.document');
      const root=f.doc.documentElement;
      root.scrollHeight=5000;root.clientHeight=400;root.scrollTop=0;
      f.init('many');
      const seen=[];
      const press=(key,mods)=>{const ev=f.doc.dispatch('keydown',Object.assign({key},mods||{}));
        seen.push([key,root.scrollTop,ev.defaultPrevented,f.el('doc-progress').style.transform])};
      press('PageDown');press('PageDown');press('PageUp');press('End');press('PageDown');press('Home');press('PageUp');
      press('PageDown',{ctrlKey:true});press('ArrowDown');
      root.scrollTop=2300;f.doc.dispatch('scroll');
      const scrolled=f.el('doc-progress').style.transform;
      const on=f.el('doc-track').getAttribute('data-on');
      root.scrollHeight=400;f.win.listeners.resize.forEach(fn=>fn({type:'resize'}));
      return {seen,scrolled,on,off:f.el('doc-track').getAttribute('data-on')};
    """)
    assert [step[:3] for step in result["seen"]] == [
        ["PageDown", 340, True], ["PageDown", 680, True], ["PageUp", 340, True], ["End", 4600, True],
        ["PageDown", 4600, True], ["Home", 0, True], ["PageUp", 0, True],
        ["PageDown", 0, False], ["ArrowDown", 0, False]]
    assert result["seen"][3][3] == "scaleX(1.0000)" and result["seen"][5][3] == "scaleX(0.0000)"
    assert result["scrolled"] == "scaleX(0.5000)" and result["on"] == "1" and result["off"] == "0"


def test_table_renders_empty_one_and_eight_by_sixty_four(tmp_path):
    result = node(tmp_path, r"""
      const f=prefab('jarvis.table');
      f.init('empty');
      const empty={head:texts(f.el('tbl-head').children),rows:f.el('tbl-body').children.length,empty:f.hidden('tbl-empty'),
        foot:f.el('tbl-foot').textContent};
      f.update('one');
      const one={head:texts(f.el('tbl-head').children),cells:texts(f.el('tbl-body').children[0].children),
        aligns:f.el('tbl-body').children[0].children.map(c=>c.getAttribute('data-align')),empty:f.hidden('tbl-empty'),
        zebra:f.el('tbl').getAttribute('data-zebra'),th:f.el('tbl-head').children[0].className,foot:f.el('tbl-foot').textContent};
      f.update('many');
      const body=f.el('tbl-body');
      const many={rows:body.children.length,cols:body.children.map(r=>r.children.length),last:body.children[63].children[7].textContent,
        aligns:f.el('tbl-head').children.map(c=>c.getAttribute('data-align')),zebra:f.el('tbl').getAttribute('data-zebra'),
        tabstops:body.children.filter(r=>r.getAttribute('tabindex')==='0').length,foot:f.el('tbl-foot').textContent};
      return {empty,one,many,errors:f.errors()};
    """)
    assert result["empty"] == {"head": ["Nom"], "rows": 0, "empty": False, "foot": "0 ligne · 1 colonne"}
    one = result["one"]
    assert one["head"] == ["Nom", "Taille"] and one["cells"] == ["a.txt", ""] and one["aligns"] == ["left", "right"]
    assert one["empty"] is True and one["zebra"] == "1" and one["th"] == "jv-label"
    assert one["foot"] == "1 ligne · 2 colonnes"
    many = result["many"]
    assert many["rows"] == 64 and set(many["cols"]) == {8} and many["last"] == "r63c7"
    assert many["aligns"] == ["left", "right", "center"] * 2 + ["left", "right"]
    assert many["zebra"] == "0" and many["tabstops"] == 1 and many["foot"] == "64 lignes · 8 colonnes"
    assert result["errors"] == []


def test_table_notifies_row_selected_on_click_and_keyboard(tmp_path):
    result = node(tmp_path, r"""
      const f=prefab('jarvis.table');f.init('many');
      const rows=()=>f.el('tbl-body').children;
      const selected=()=>rows().map((r,i)=>r.getAttribute('aria-selected')==='true'?i:-1).filter(i=>i>=0);
      rows()[2].click();
      const afterClick={events:f.events(),selected:selected(),active:rows().indexOf(f.doc.activeElement),
        foot:f.el('tbl-foot').textContent};
      rows()[2].click();
      const repeat=f.events().length;
      const down=rows()[2].key('ArrowDown');
      const focusDown=rows().indexOf(f.doc.activeElement);
      const enter=rows()[3].key('Enter');
      rows()[3].key('End');const end=rows().indexOf(f.doc.activeElement);
      rows()[63].key(' ');
      rows()[63].key('Home');const home=rows().indexOf(f.doc.activeElement);
      rows()[0].key('ArrowUp');const top=rows().indexOf(f.doc.activeElement);
      const tabstops=rows().map((r,i)=>r.getAttribute('tabindex')==='0'?i:-1).filter(i=>i>=0);
      const ignored=rows()[0].key('x');
      f.update('fewer');
      return {afterClick,repeat,down:down.defaultPrevented,focusDown,enter:enter.defaultPrevented,end,home,top,tabstops,
        ignored:ignored.defaultPrevented,events:f.events(),selected:selected(),afterUpdate:f.el('tbl-foot').textContent,errors:f.errors()};
    """)
    assert result["afterClick"] == {"events": [["row_selected", {"index": 2}]], "selected": [2], "active": 2,
                                    "foot": "64 lignes · 8 colonnes · ligne 3 choisie"}
    assert result["repeat"] == 1  # the same row again is not a new selection
    assert result["down"] is True and result["focusDown"] == 3 and result["enter"] is True
    assert (result["end"], result["home"], result["top"], result["tabstops"]) == (63, 0, 0, [0])
    assert result["ignored"] is False
    assert result["events"] == [["row_selected", {"index": 2}], ["row_selected", {"index": 3}],
                                ["row_selected", {"index": 63}]]
    # Fewer rows than the selected index: the selection is dropped, not pointed at another row.
    assert result["selected"] == [] and result["afterUpdate"] == "2 lignes · 1 colonne"
    assert result["errors"] == []


def test_the_real_host_builds_a_frame_for_each_base_prefab_from_the_catalogue(tmp_path):
    import asyncio

    from jarvis.adapters.file_prefab_library import FilePrefabLibrary, FilePrefabRuntime
    from jarvis.core.prefab_service import PrefabService

    async def bundles():
        service = PrefabService(FilePrefabLibrary(PACKAGE, tmp_path / "data"),
                                runtime=FilePrefabRuntime(PACKAGE.parent / "runtime"))
        await service.start()
        return {f"{prefab_id}@1": await service.bundle(prefab_id, 1)
                for prefab_id in ("jarvis.window", "jarvis.document", "jarvis.table")}

    served = asyncio.run(bundles())
    result = run_node(tmp_path, r"""
      const b=bench({bundles:D});
      const out={};
      for(const key of Object.keys(D)){
        const [id]=key.split('@');const s=b.slot();
        b.host.mount(s,{object_id:id,title:id,prefab:{id,version:1},props:{},data:D[key].manifest.sample.data});
        await flush();
        const frame=b.frameOf(s);
        out[id]={state:b.host.state(id),sandbox:frame&&frame.getAttribute('sandbox'),srcdoc:!!(frame&&frame.srcdoc),
          template:frame?frame.srcdoc.includes(D[key].files.template.trim().slice(0,30)):false};
      }
      return {out,errors:b.logs.filter(l=>l.key==='scene.prefab_error')};
    """, served)
    for prefab_id in ("jarvis.window", "jarvis.document", "jarvis.table"):
        assert result["out"][prefab_id] == {"state": "loading", "sandbox": "allow-scripts", "srcdoc": True,
                                            "template": True}
    assert result["errors"] == []


def test_table_long_cells_break_between_segments_and_short_cells_stay_whole(tmp_path):
    result = node(tmp_path, r"""
      const f=prefab('jarvis.table');f.init('paths');
      const rows=f.el('tbl-body').children;
      const cell=(r,c)=>rows[r].children[c];
      const wbr=(el)=>el.descendants().filter(n=>n.tagName==='WBR').length;
      return {texts:rows.map(r=>texts(r.children)),wbr:[wbr(cell(0,0)),wbr(cell(1,0)),wbr(cell(0,1))],
        short:[cell(0,0).hasAttribute('data-short'),cell(0,1).hasAttribute('data-short')]};
    """)
    assert result["texts"] == [["jarvis/prefabs/base/module_01.py", "modifié"], ["https://example.com/a?b=c", "ok"]]
    # One break after each run of `/ : ? =` (`://` is one run); never inside `module_01.py`.
    assert result["wbr"] == [3, 4, 0] and result["short"] == [False, True]
