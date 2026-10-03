"""Shim des cadres de prefab : l'API `window.jarvis` (prefab-foundation, Slice 03).

Contrat : `jarvis/prefabs/runtime/shim.js`, `docs/prefabs.md` › *Message
protocol* › *Shim API*. La fabrique `createShim(env)` est exécutée par node
avec `post` et `listen` injectés et un faux DOM minimal ; le démarrage dans
un vrai cadre est prouvé dans Chrome (preuve navigateur de la Slice).
"""

from __future__ import annotations

import re

from tests.fakes.prefab_js import SHELL_CSS, SHIM_JS, run_node

#: Un cadre factice : `body` porte le gabarit, `msgs` reçoit ce que le shim poste.
FRAME = r"""
function frame(opts){
  const o=opts||{};
  const doc=new FakeDocument();
  const msgs=[];let deliver=null;const observed=[];
  class RO{constructor(cb){this.cb=cb;observed.push(this);this.disconnected=false}observe(el){this.el=el}disconnect(){this.disconnected=true}}
  const shim=Shim.createShim({post:(m)=>msgs.push(JSON.parse(JSON.stringify(m))),listen:(fn)=>{deliver=fn},document:doc,ResizeObserver:RO});
  doc.body._height=o.height||80;
  const add=(tag,attrs)=>{const el=doc.createElement(tag);for(const [k,v] of Object.entries(attrs||{}))el.setAttribute(k,v);doc.body.appendChild(el);return el};
  return {doc,msgs,shim,api:shim.api,add,send:(m)=>deliver(m),observed,types:()=>msgs.map(m=>m.type)};
}
const INIT={jv:1,type:'init',instance:{object_id:'obj_1',prefab:{id:'test.counter',version:1},mode:'scene'},
  props:{label:'Count',accent:'#ff7a59',plain:'#nothex',big:'#123456'},data:{count:3,deep:{n:[7,8]}},
  theme:{name:'scene',accent:'#6ee7ff',text:'#dcecf4',muted:'#8aa5b3',surface:'rgba(4,10,15,.88)',scale:1.25},blocks:{}};
"""


def node(tmp_path, body, data=None):
    return run_node(tmp_path, FRAME + body, data)


def test_load_runs_the_behavior_then_announces_ready_once(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();const seen=[];
      f.shim.load(function(jarvis){seen.push(jarvis===f.api);jarvis.on('init',()=>seen.push('init'))});
      f.shim.load(function(){seen.push('second load ignored?')});
      f.send(INIT);
      return {seen,types:f.types()};
    """)
    assert result["seen"] == [True, "init"]
    assert result["types"][0] == "ready" and result["types"].count("ready") == 1


def test_init_sets_frozen_snapshots_bindings_and_css_variables(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();
      const label=f.add('h2',{'data-jv-text':'props.label'}),count=f.add('p',{'data-jv-text':'data.count'}),
            deep=f.add('p',{'data-jv-text':'data.deep.n.1'}),missing=f.add('p',{'data-jv-text':'data.nope'}),
            obj=f.add('p',{'data-jv-text':'data.deep'}),outside=f.add('p',{'data-jv-text':'window.name'});
      let got=null;
      f.shim.load((jarvis)=>jarvis.on('init',(ctx)=>{got={count:ctx.data.count,mode:ctx.instance.mode,same:ctx.props===jarvis.props}}));
      f.send(INIT);
      let mutated='no';
      try{f.api.data.count=99;mutated=f.api.data.count}catch(e){mutated='threw'}
      let replaced='no';
      try{f.api.data={};replaced=f.api.data.count}catch(e){replaced='threw'}
      return {got,texts:[label,count,deep,missing,obj,outside].map(e=>e.textContent),mutated,replaced,
              frozen:Object.isFrozen(f.api.props)&&Object.isFrozen(f.api.data.deep.n),
              vars:f.doc.documentElement.style.vars,last:f.msgs[f.msgs.length-1]};
    """)
    assert result["got"] == {"count": 3, "mode": "scene", "same": True}
    assert result["texts"] == ["Count", "3", "8", "", '{"n":[7,8]}', ""]
    assert result["mutated"] in (3, "threw") and result["replaced"] in (3, "threw") and result["frozen"] is True
    assert result["vars"] == {"--jv-accent": "#ff7a59", "--jv-text": "#dcecf4", "--jv-muted": "#8aa5b3",
                              "--jv-surface": "rgba(4,10,15,.88)", "--jv-scale": "1.25",
                              "--jv-prop-accent": "#ff7a59", "--jv-prop-big": "#123456"}
    assert result["last"] == {"jv": 1, "type": "resize", "height": 80}


def test_update_is_diffed_and_rebinds(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();const count=f.add('p',{'data-jv-text':'data.count'});const calls=[];
      f.shim.load((jarvis)=>jarvis.on('update',(ctx)=>calls.push({count:ctx.data.count,changed:ctx.changed})));
      f.send(INIT);
      f.send(Object.assign({},INIT,{type:'update'}));
      f.send(Object.assign({},INIT,{type:'update',data:{count:4,deep:{n:[7,8]}}}));
      const text=count.textContent;
      f.doc.body._height=140;
      f.send(Object.assign({},INIT,{type:'update',data:{count:4,deep:{n:[7,8]}},theme:Object.assign({},INIT.theme,{accent:'#000000'})}));
      return {calls,text,resizes:f.msgs.filter(m=>m.type==='resize').map(m=>m.height),
              accent:f.doc.documentElement.style.vars['--jv-accent']};
    """)
    assert [call["count"] for call in result["calls"]] == [4, 4]
    assert result["calls"][0]["changed"] == {"props": False, "data": True, "theme": False, "blocks": False}
    assert result["calls"][1]["changed"]["theme"] is True
    assert result["text"] == "4" and result["resizes"] == [80, 140]
    # Une prop `accent` couleur l'emporte sur le thème.
    assert result["accent"] == "#ff7a59"


def test_emit_validates_and_posts_events(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();f.shim.load(()=>{});f.send(INIT);
      const errors=[];
      for(const args of [['Bad'],['a',[]],['a','text'],['a',{big:'x'.repeat(9000)}],[42,{}]]){
        try{f.api.emit(...args);errors.push(null)}catch(e){errors.push(e.name)}
      }
      f.api.emit('item_toggled',{items:[{id:'a',done:true}]});
      f.api.emit('ping');
      return {errors,events:f.msgs.filter(m=>m.type==='event')};
    """)
    assert result["errors"] == ["TypeError", "TypeError", "TypeError", "RangeError", "TypeError"]
    assert result["events"] == [{"jv": 1, "type": "event", "name": "item_toggled", "payload": {"items": [{"id": "a", "done": True}]}},
                                {"jv": 1, "type": "event", "name": "ping", "payload": {}}]


def test_behavior_exceptions_become_bounded_error_messages(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();
      f.shim.load((jarvis)=>{
        jarvis.on('init',()=>{throw new TypeError('x'.repeat(500))});
        jarvis.on('init',()=>Promise.reject(new Error('async boom')));
        throw new Error('load boom');
      });
      f.send(INIT);
      await flush();
      for(let i=0;i<30;i++)f.shim.reportError('spam '+i);
      const errors=f.msgs.filter(m=>m.type==='error');
      return {first:f.msgs.slice(0,2).map(m=>m.type),messages:errors.slice(0,3).map(m=>m.message),count:errors.length,
              longest:Math.max(...errors.map(m=>m.message.length))};
    """)
    assert result["first"] == ["error", "ready"]
    assert result["messages"][0] == "load boom"
    assert result["messages"][1].startswith("TypeError: xxx") and len(result["messages"][1]) == 300
    assert result["messages"][2] == "async boom"
    assert result["count"] == 20 and result["longest"] == 300


def test_render_blocks_builds_text_nodes_and_links_without_href(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();f.shim.load(()=>{});f.send(INIT);
      const box=f.add('div',{});
      const md='# Title\n\nSome **bold** and `code` and [site](https://example.com/a).\n\n- one\n- two\n\n> quoted\n\n```\nraw <b>\n```\n\n---';
      f.api.renderBlocks(box,Lay.markdownBlocks(md));
      const tags=box.descendants().map(n=>n.tagName.toLowerCase());
      const link=box.find(n=>n.tagName==='A');
      const before=f.msgs.length;
      const click=link.click();link.key('Enter');
      return {tags,text:box.textContent,link:{href:link.hasAttribute('href'),role:link.getAttribute('role'),tab:link.getAttribute('tabindex'),
              title:link.getAttribute('title'),prevented:click.defaultPrevented},opened:f.msgs.slice(before),cls:box.className};
    """)
    assert result["tags"] == ["div", "p", "strong", "code", "a", "ul", "li", "p", "li", "p", "blockquote", "p", "pre",
                              "code", "hr"]
    assert "raw <b>" in result["text"] and "Title" in result["text"]
    assert result["link"] == {"href": False, "role": "link", "tab": "0", "title": "example.com", "prevented": True}
    assert result["opened"] == [{"jv": 1, "type": "open_url", "url": "https://example.com/a"}] * 2
    assert "jv-md" in result["cls"]


def test_markdown_binding_uses_the_host_blocks(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();const box=f.add('div',{'data-jv-markdown':'data.notes'});
      f.shim.load(()=>{});
      f.send(Object.assign({},INIT,{data:{notes:'**hi**'},blocks:{'data.notes':Lay.markdownBlocks('**hi**')}}));
      const first=box.descendants().map(n=>n.tagName.toLowerCase());
      f.send(Object.assign({},INIT,{type:'update',data:{notes:'plain'},blocks:{'data.notes':Lay.markdownBlocks('plain')}}));
      return {first,text:box.textContent,blocks:f.api.blocks('data.notes'),none:f.api.blocks('data.nope')};
    """)
    assert result["first"] == ["p", "strong"] and result["text"] == "plain"
    assert result["blocks"][0]["kind"] == "p" and result["none"] == []


def test_open_url_teardown_and_foreign_messages(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();const order=[];
      f.shim.load((jarvis)=>{jarvis.on('teardown',()=>order.push('teardown'));jarvis.on('update',()=>order.push('update'))});
      const refused=[];
      for(const url of ['javascript:alert(1)','/relative',42]){try{f.api.openUrl(url);refused.push(false)}catch(e){refused.push(true)}}
      const ignored=[f.shim.receive(null),f.shim.receive({jv:2,type:'init'}),f.shim.receive({jv:1,type:'event'}),f.shim.receive('init')];
      f.send(INIT);
      f.send({jv:1,type:'teardown'});
      const before=f.msgs.length;
      f.send(Object.assign({},INIT,{type:'update',data:{count:9}}));
      f.api.emit('late');
      return {refused,ignored,order,after:f.msgs.slice(before),disconnected:f.observed.every(o=>o.disconnected)};
    """)
    assert result["refused"] == [True, True, True]
    assert result["ignored"] == [False, False, False, False]
    assert result["order"] == ["teardown"] and result["after"] == [] and result["disconnected"] is True


def test_on_refuses_unknown_hooks_and_unsubscribes(tmp_path):
    result = node(tmp_path, r"""
      const f=frame();const calls=[];let off=null;const errors=[];
      f.shim.load((jarvis)=>{
        off=jarvis.on('update',()=>calls.push('u'));
        for(const args of [['ready',()=>{}],['init',null]]){try{jarvis.on(...args);errors.push(null)}catch(e){errors.push(e.name)}}
      });
      f.send(INIT);off();
      f.send(Object.assign({},INIT,{type:'update',data:{count:1}}));
      return {calls,errors,frozenApi:Object.isFrozen(f.api)};
    """)
    assert result == {"calls": [], "errors": ["TypeError", "TypeError"], "frozenApi": True}


def test_the_shim_source_is_safe_to_inline():
    text = SHIM_JS.read_text(encoding="utf-8")
    assert "</script" not in text.lower() and "<!--" not in text
    # Démarrage seulement dans un cadre, jamais sous node ; liens neutralisés ; erreurs globales captées.
    for needle in ("root.parent===root", "addEventListener('error'", "addEventListener('unhandledrejection'",
                   "closest('a[href]')", "Object.defineProperty(root,'jarvis'", "event.source===parentWindow"):
        assert needle in text, needle


def test_more_content_below_the_frame_edge_is_flagged_on_the_root(tmp_path):
    """Slice 05 : `data-jv-more` tant qu'il reste du contenu sous le bord ; la coquille y dessine un fondu."""

    result = node(tmp_path, r"""
      const f=frame();const html=f.doc.documentElement;
      html.scrollHeight=900;html.clientHeight=300;html.scrollTop=0;
      f.shim.load(()=>{});f.send(INIT);
      const atTop=html.hasAttribute('data-jv-more');
      html.scrollTop=599;f.shim.edge();const nearEnd=html.hasAttribute('data-jv-more');
      html.scrollTop=600;f.shim.edge();const atEnd=html.hasAttribute('data-jv-more');
      html.scrollTop=0;html.scrollHeight=300;f.shim.measure();const fits=html.hasAttribute('data-jv-more');
      return {atTop,nearEnd,atEnd,fits};
    """)
    assert result == {"atTop": True, "nearEnd": False, "atEnd": False, "fits": False}
    text = SHIM_JS.read_text(encoding="utf-8")
    assert "addEventListener('scroll',shim.edge" in text and "addEventListener('resize',shim.edge)" in text
    shell = SHELL_CSS.read_text(encoding="utf-8")
    assert "html[data-jv-more]::after{opacity:1}" in shell


def test_the_shell_hidden_attribute_beats_any_class_display():
    """Slice 05 (reprise QA F7) : `[hidden]` masque un élément même quand sa classe l'affiche (`.jv-list` est en flex)."""

    shell = re.sub(r"\s+", "", re.sub(r"/\*.*?\*/", "", SHELL_CSS.read_text(encoding="utf-8"), flags=re.S))
    assert "[hidden]{display:none!important}" in shell
    assert ".jv-list{" in shell and "display:flex" in shell.split(".jv-list{", 1)[1].split("}", 1)[0]
