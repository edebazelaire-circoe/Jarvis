"""Protocole `jv: 1` des cadres de prefab, logique pure (prefab-foundation, Slice 03).

Contrat : `jarvis/runtime/control_center_prefab_protocol.js`, `docs/prefabs.md` ›
*Runtime*, *Message protocol*. Exécuté par node (motif `run_node`), plus les
gardes statiques du runtime : `srcdoc` posé par un seul fichier, aucun
balisage en chaîne, module de protocole sans DOM ni réseau, modules insérés
dans la page sans balise de script ni commentaire HTML en clair.
"""

from __future__ import annotations

import asyncio
import re

from jarvis.runtime.control_center import ControlCenter
from tests.fakes.prefab_js import HOST_JS, PROTOCOL_JS, RUNTIME, SHIM_JS, catalogue_bundles, run_node

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
       "base-uri 'none'; form-action 'none'")


def test_sandbox_and_csp_are_the_contract_values(tmp_path):
    result = run_node(tmp_path, "return {sandbox:P.SANDBOX,csp:P.CSP,jv:P.JV,host:P.HOST_TYPES,frame:P.FRAME_TYPES};")
    assert result == {"sandbox": "allow-scripts", "csp": CSP, "jv": 1, "host": ["init", "update", "teardown"],
                      "frame": ["ready", "event", "resize", "open_url", "error"]}


async def test_build_srcdoc_puts_the_csp_before_anything_that_can_load(tmp_path):
    bundles = await catalogue_bundles(tmp_path, "test.counter")
    result = run_node(tmp_path, "return P.buildSrcdoc(D['test.counter@1']);", bundles)
    bundle = bundles["test.counter@1"]
    head = result[: result.index("</head>")]
    # Seul `<meta charset>` précède le CSP : rien avant lui ne peut charger quoi que ce soit.
    assert head.startswith('<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy"')
    assert f'content="{CSP}"' in head
    marks = [result.index(mark) for mark in (
        '<meta charset="utf-8">', 'http-equiv="Content-Security-Policy"', '<style data-jv="shell">',
        '<style data-jv="prefab">', '<body class="jv-body">' + bundle["files"]["template"],
        '<script data-jv="shim">', '<script data-jv="behavior">__jvLoad(function(jarvis){')]
    assert marks == sorted(marks)
    assert bundle["runtime"]["shell_css"] in result and bundle["files"]["style"] in result
    assert bundle["files"]["behavior"] in result
    assert result.count("<script") == 2 and result.count("</script>") == 2
    assert result.endswith("</script></body></html>")


def test_build_srcdoc_neutralizes_block_breakouts_and_refuses_incomplete_bundles(tmp_path):
    result = run_node(tmp_path, r"""
      const base={files:{template:'<p>t</p>',style:'a{}</style><b>',behavior:'var s="</script><i>";<!-- x'},
                  runtime:{version:'v',shim:'/* </SCRIPT> */',shell_css:'</Style>'}};
      const doc=P.buildSrcdoc(base);
      const errors=[];
      for(const bad of [{},{files:base.files},{files:{template:'',style:'',behavior:1},runtime:base.runtime},
                        {files:base.files,runtime:{shim:'x'}}]){
        try{P.buildSrcdoc(bad);errors.push(null)}catch(e){errors.push(e.message)}
      }
      return {doc,errors};
    """)
    doc = result["doc"]
    assert doc.count("</style>") == 2 and doc.count("</script>") == 2
    assert "<\\/style><b>" in doc and "<\\/Style>" in doc and "<\\/script><i>" in doc and "<\\/SCRIPT>" in doc
    assert "<!--" not in doc and "<\\!-- x" in doc
    assert all(error for error in result["errors"])


def test_parse_frame_message_accepts_the_contract_and_nothing_else(tmp_path):
    result = run_node(tmp_path, r"""
      const ok=(m)=>{const r=P.parseFrameMessage(m);return r.ok?r.message:'refused: '+r.reason};
      const big={blob:'x'.repeat(8*1024)};
      return {
        ready:ok({jv:1,type:'ready'}),
        event:ok({jv:1,type:'event',name:'item_toggled',payload:{items:[1]}}),
        resizeLow:ok({jv:1,type:'resize',height:3}),resizeHigh:ok({jv:1,type:'resize',height:1e9}),resize:ok({jv:1,type:'resize',height:120.4}),
        url:ok({jv:1,type:'open_url',url:'https://example.com/a?b=1'}),
        error:ok({jv:1,type:'error',message:'boom\nline\u0007'+'y'.repeat(400)}),
        emptyError:ok({jv:1,type:'error'}),
        refused:[
          ok(null),ok('{"jv":1}'),ok([]),ok({type:'ready'}),ok({jv:2,type:'ready'}),ok({jv:1,type:'init'}),
          ok({jv:1,type:'ready',extra:1}),ok({jv:1,type:'event',name:'Bad-Name',payload:{}}),
          ok({jv:1,type:'event',name:'a',payload:[]}),ok({jv:1,type:'event',name:'a'}),ok({jv:1,type:'event',name:'a',payload:big}),
          ok({jv:1,type:'resize',height:NaN}),ok({jv:1,type:'resize',height:'12'}),
          ok({jv:1,type:'open_url',url:'javascript:alert(1)'}),ok({jv:1,type:'open_url',url:'https://user:pw@example.com/'}),
          ok({jv:1,type:'open_url',url:'ftp://example.com/'}),ok({jv:1,type:'open_url',url:'https://e.com/'+'a'.repeat(2100)}),
        ],
      };
    """)
    assert result["ready"] == {"type": "ready"}
    assert result["event"] == {"type": "event", "name": "item_toggled", "payload": {"items": [1]}}
    assert (result["resizeLow"]["height"], result["resizeHigh"]["height"], result["resize"]["height"]) == (24, 4000, 120)
    assert result["url"] == {"type": "open_url", "url": "https://example.com/a?b=1"}
    assert len(result["error"]["message"]) == 300 and "\n" not in result["error"]["message"]
    assert result["error"]["message"].startswith("boom line") and result["emptyError"]["message"] == "unknown error"
    assert all(isinstance(item, str) and item.startswith("refused: ") for item in result["refused"])


def test_host_messages_carry_only_the_instance_values(tmp_path):
    result = run_node(tmp_path, r"""
      const props={accent:'#ff7a59'},data={items:[{id:'a'}]};
      const init=P.hostMessage('init',{instance:{object_id:'obj_1',prefab:{id:'jarvis.checklist',version:2},mode:'preview',secret:'x'},
        props,data,theme:{accent:'#6ee7ff'},blocks:{'data.n':[]},token:'never'});
      props.accent='#000000';data.items.push({id:'b'});
      const errors=[];
      for(const call of [()=>P.hostMessage('ready',{}),()=>P.hostMessage('init',{instance:{mode:'other'}})]){
        try{call();errors.push(null)}catch(e){errors.push(e.message)}
      }
      return {init,update:P.hostMessage('update',{props:{},data:{x:1}}),teardown:P.hostMessage('teardown',{props:{a:1}}),errors};
    """)
    assert result["init"] == {"jv": 1, "type": "init", "props": {"accent": "#ff7a59"}, "data": {"items": [{"id": "a"}]},
                              "theme": {"accent": "#6ee7ff"}, "blocks": {"data.n": []},
                              "instance": {"object_id": "obj_1", "prefab": {"id": "jarvis.checklist", "version": 2},
                                           "mode": "preview"}}
    assert result["update"] == {"jv": 1, "type": "update", "props": {}, "data": {"x": 1}, "theme": {}, "blocks": {}}
    assert result["teardown"] == {"jv": 1, "type": "teardown"}
    assert all(result["errors"])


def test_the_url_rule_is_the_scene_link_rule_minus_local_hosts(tmp_path):
    urls = ["https://example.com/", "http://127.0.0.1:8080/x", "javascript:alert(1)", "data:text/html,x",
            "https://a:b@example.com/", "//example.com", "https://exa mple.com/", "", None, 42]
    result = run_node(tmp_path, "return D.map(u=>[P.isAllowedUrl(u),u!==null&&typeof u==='string'&&Lay.linkOf(u)!==null]);", urls)
    assert [allowed for allowed, _ in result] == [True, False, False, False, False, False, False, False, False, False]
    # Même règle que la scène, sauf les hôtes locaux et privés que la scène, elle, garde.
    assert [scene for _, scene in result] == [True, True, False, False, False, False, False, False, False, False]


def test_markdown_inputs_become_blocks_by_path_and_values_stay_text(tmp_path):
    manifest = {"inputs": {
        "props": {"type": "object", "properties": {"body": {"type": "text", "format": "markdown"},
                                                    "plain": {"type": "text"}}},
        "data": {"type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": {"note": {"type": "text", "format": "markdown"}}}}}}}}
    result = run_node(tmp_path, r"""
      const props={body:'# Title\n\n- **a**',plain:'**no**'},data={items:[{note:'*x*'},{},{note:'y'}]};
      const out=P.markdownBlocksOf(D,props,data);
      return {paths:P.markdownPaths(D.inputs.data,'data',[]),out,same:JSON.stringify(out['props.body'])===JSON.stringify(Lay.markdownBlocks(props.body)),
              props};
    """, manifest)
    assert result["paths"] == ["data.items.*.note"]
    assert sorted(result["out"]) == ["data.items.0.note", "data.items.2.note", "props.body"]
    assert result["same"] is True and result["props"]["body"].startswith("# Title")


def test_declared_events_come_from_the_manifest(tmp_path):
    manifest = {"events": {"item_toggled": {"class": "state", "writes": ["items"]},
                           "done": {"class": "notify", "summary": "x"}}}
    result = run_node(tmp_path, "return [...P.declaredEvents(D).entries()];", manifest)
    assert result == [["item_toggled", {"class": "state", "writes": ["items"]}], ["done", {"class": "notify", "writes": []}]]


# ---------------------------------------------------------------- gardes statiques


def _code(path) -> str:
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)


def test_srcdoc_is_set_by_one_runtime_file_only():
    owners = []
    for path in sorted(RUNTIME.rglob("*")):
        if path.suffix in {".js", ".html", ".mjs"} and re.search(r"\bsrcdoc\b", path.read_text(encoding="utf-8")):
            owners.append(path.name)
    assert owners == ["control_center_prefab_host.js"]
    host = HOST_JS.read_text(encoding="utf-8")
    assert len(re.findall(r"\.srcdoc\s*=", host)) == 1
    # L'attribut sandbox vient de la constante du protocole, posée avant le document.
    assert "iframe.setAttribute('sandbox',P.SANDBOX);" in host
    assert host.index("setAttribute('sandbox'") < host.index(".srcdoc=")
    assert "const SANDBOX='allow-scripts';" in PROTOCOL_JS.read_text(encoding="utf-8")
    for path in (PROTOCOL_JS, HOST_JS, SHIM_JS):
        assert not re.search(r"allow-(same-origin|popups|forms|top-navigation|modals)", _code(path)), path.name


def test_no_markup_strings_in_the_prefab_runtime():
    for path in (PROTOCOL_JS, HOST_JS, SHIM_JS):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert forbidden not in text, (path.name, forbidden)


def test_the_protocol_module_is_pure():
    code = _code(PROTOCOL_JS)
    for forbidden in ("document.", "window.", "fetch(", "setTimeout", "setInterval", "addEventListener",
                      "localStorage", "XMLHttpRequest", "postMessage("):
        assert forbidden not in code, forbidden


def test_page_modules_never_spell_a_script_tag_or_an_html_comment():
    """Insérés dans le bloc de script de la page : une balise de script ou `<!--` en clair le casserait."""

    for path in (PROTOCOL_JS, HOST_JS):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?i)</?script|<!--", text), path.name


def test_the_page_splices_both_modules_before_the_scene_page(tmp_path):
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = asyncio.run(center.index(None)).text
    assert "__CONTROL_CENTER_PREFAB_" not in html
    order = [html.index(token) for token in ("root.JarvisSceneLayout=api", "root.JarvisPrefabProtocol=api",
                                             "root.JarvisPrefabHost=api", "window.JarvisScene=Object.freeze(")]
    assert order == sorted(order)
