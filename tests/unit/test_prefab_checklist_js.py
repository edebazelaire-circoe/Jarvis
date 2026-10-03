"""`jarvis.checklist` dans le shim et dans l'hôte réel (prefab-foundation, Slice 06).

Le prefab livré (`jarvis/prefabs/base/jarvis.checklist/1/`) est exécuté tel
quel : gabarit dans le faux DOM, `behavior.js` chargé par le vrai shim, messages
de l'hôte construits par `JarvisPrefabProtocol.hostMessage`, minuteries
manuelles. Les données envoyées sont celles que Core stocke (validées,
complétées de leurs défauts). Les charges émises sont vérifiées par le domaine
(`check_state_event`, `validate_value`) : ce que le cadre envoie, Core
l'accepte.

Contrat : `docs/prefabs.md` › *Base catalogue* (`jarvis.checklist`) et
*Structured inputs and events* ; règles de coche en tête de `behavior.js`.
"""

from __future__ import annotations

from pathlib import Path

import jarvis
from jarvis.domain.prefab import (
    MAX_MANIFEST_BYTES, StateEventOutcome, check_state_event, decode_json_text, parse_bundle, validate_value,
)
from tests.fakes.prefab_js import run_node

FOLDER = Path(jarvis.__file__).resolve().parent / "prefabs" / "base" / "jarvis.checklist" / "1"
TEXT = {name: (FOLDER / name).read_text(encoding="utf-8")
        for name in ("manifest.json", "template.html", "style.css", "behavior.js")}
MANIFEST = parse_bundle(decode_json_text(TEXT["manifest.json"], MAX_MANIFEST_BYTES, "manifest"),
                        TEXT["template.html"], TEXT["style.css"], TEXT["behavior.js"]).manifest

BENCH = r"""
/* Événement qui remonte du nœud visé jusqu'à la racine, comme dans un vrai document. */
function fire(target,type,fields){
  const ev=Object.assign({type,target,defaultPrevented:false,preventDefault(){this.defaultPrevented=true},stopPropagation(){}},fields||{});
  for(let node=target;node;node=node.parentNode)(node.listeners&&node.listeners[type]||[]).slice().forEach(fn=>fn(ev));
  return ev;
}
function listenerCount(doc){
  const nodes=[doc.documentElement,doc.body,...doc.body.descendants()];
  return nodes.reduce((n,el)=>n+Object.values(el.listeners).reduce((m,l)=>m+l.length,0),0)
    +Object.values(doc.listeners).reduce((m,l)=>m+l.length,0);
}
/* Un cadre : gabarit et comportement livrés, vrai shim, horloge manuelle. */
function checklist(){
  const doc=new FakeDocument();
  parseTemplate(doc.body,D.template);
  const c=clock();
  const msgs=[];let deliver=null;
  const shim=Shim.createShim({post:(m)=>msgs.push(JSON.parse(JSON.stringify(m))),listen:(fn)=>{deliver=fn},document:doc});
  const behavior=new Function('jarvis','document','window','setTimeout','clearTimeout',D.behavior);
  shim.load((api)=>behavior(api,doc,new FakeWindow(),c.setTimeout,c.clearTimeout));
  const fields=(v)=>({props:v.props,data:v.data,theme:H.DEFAULT_THEME,blocks:{}});
  const f={
    doc,clock:c,msgs,
    init(v){deliver(P.hostMessage('init',Object.assign({instance:{object_id:'ck-1',prefab:{id:'jarvis.checklist',version:1},mode:'scene'}},fields(v))))},
    update(v,force){deliver(P.hostMessage('update',Object.assign(fields(v),force?{force:true}:{})))},
    /* L'issue d'une écriture, telle que l'hôte la dit au cadre (`event_result`, A4). */
    result(outcome,reason,name){deliver(P.hostMessage('event_result',{name:name||'item_toggled',outcome,reason}))},
    /* Core écrit la dernière liste envoyée et la scène la rapporte (clés dans un autre ordre). */
    sent:()=>f.events().filter(e=>e[0]==='item_toggled').map(e=>e[1].items),
    rows:()=>doc.getElementById('ck-list').children,
    checked:()=>f.rows().map(r=>r.getAttribute('aria-checked')==='true'),
    events:()=>msgs.filter(m=>m.type==='event').map(m=>[m.name,m.payload]),
    errors:()=>msgs.filter(m=>m.type==='error'),
    notice:()=>doc.getElementById('ck-notice').textContent,
    hidden:(id)=>doc.getElementById(id).hasAttribute('hidden'),
    click:(i)=>fire(f.rows()[i].byClass('ck-label')[0],'click'),
    key:(k)=>fire(doc.activeElement||f.rows()[0],'keydown',{key:k}),
    /* Core confirme : la liste envoyée revient par la scène, clés dans un autre ordre. */
    confirm(props){const last=f.events().filter(e=>e[0]==='item_toggled').pop()[1].items;
      const items=last.map(it=>Object.fromEntries(Object.entries(it).reverse()));
      f.update({props:props||D.props,data:{items}})},
  };
  return f;
}
"""


def _stored(props: dict, data: dict) -> dict:
    props, problems = validate_value(MANIFEST.props, props, "props")
    data, more = validate_value(MANIFEST.data, data, "data")
    assert problems + more == (), problems + more
    return {"props": props, "data": data}


def node(tmp_path, body: str, **extra):
    items = [{"id": f"i{n}", "label": f"Élément {n}", **({"note": f"Note {n}\nseconde ligne"} if n % 5 == 0 else {})}
             for n in range(64)]
    data = {
        "template": TEXT["template.html"], "behavior": TEXT["behavior.js"],
        "props": _stored({}, {"items": []})["props"],
        "empty": _stored({}, {"items": []}),
        "one": _stored({"show_progress": False}, {"items": [{"id": "a", "label": "Seul"}]}),
        "three": _stored({}, {"items": [{"id": "a", "label": "Un", "done": True}, {"id": "b", "label": "Deux"},
                                        {"id": "c", "label": "Trois", "note": "Détail"}]}),
        "many": _stored({"accent": "#ff7a59"}, {"items": items}),
        "brain": _stored({}, {"items": [{"id": "x", "label": "Remplacé par Jarvis"}, {"id": "y", "label": "Autre"}]}),
        "all_done": _stored({}, {"items": [{"id": "a", "label": "Un", "done": True}]}),
        # Telles que la scène les garde quand Jarvis les écrit : sans les défauts du schéma.
        "raw": {"props": {}, "data": {"items": [{"id": "a", "label": "Un"}, {"id": "b", "label": "Deux", "note": "n"}]}},
        **extra,
    }
    return run_node(tmp_path, BENCH + body, data)


def test_renders_empty_one_and_sixty_four_items_with_progress_notes_and_empty_state(tmp_path):
    result = node(tmp_path, r"""
      const out={};
      for(const name of ['empty','one','three','many']){
        const f=checklist();f.init(D[name]);
        const rows=f.rows();
        out[name]={rows:rows.length,checked:f.checked().filter(Boolean).length,empty:!f.hidden('ck-empty'),
          progress:!f.hidden('ck-progress'),count:f.doc.getElementById('ck-count').textContent,
          roles:[...new Set(rows.map(r=>r.getAttribute('role')))],tabStops:rows.filter(r=>r.getAttribute('tabindex')==='0').length,
          notes:rows.filter(r=>r.hasAttribute('aria-describedby')).length,
          noteText:rows.map(r=>r.byClass('ck-note')[0]).filter(n=>!n.hasAttribute('hidden')).map(n=>n.textContent)[0]||null,
          labelled:rows.every(r=>f.doc.getElementById(r.getAttribute('aria-labelledby'))!==null),
          ratio:f.doc.getElementById('ck-fill').style.vars['--ck-ratio'],
          track:['aria-valuenow','aria-valuemax','aria-valuetext'].map(a=>f.doc.getElementById('ck-track').getAttribute(a)),
          accent:f.doc.documentElement.style.vars['--jv-accent'],events:f.events().length,errors:f.errors().length};
      }
      return out;""")
    assert result["empty"] | {"track": None} == {
        "rows": 0, "checked": 0, "empty": True, "progress": False, "count": "0/0", "roles": [], "tabStops": 0,
        "notes": 0, "noteText": None, "labelled": True, "ratio": "0", "track": None, "accent": "#6ee7ff",
        "events": 0, "errors": 0}
    one = result["one"]
    assert (one["rows"], one["progress"], one["empty"], one["tabStops"]) == (1, False, False, 1)  # show_progress: false
    three = result["three"]
    assert (three["rows"], three["checked"], three["count"], three["notes"], three["noteText"]) == (3, 1, "1/3", 1, "Détail")
    assert three["roles"] == ["checkbox"] and three["labelled"] and three["track"] == ["1", "3", "1 sur 3 cochés"]
    many = result["many"]
    assert (many["rows"], many["checked"], many["notes"], many["tabStops"], many["accent"]) == (64, 0, 13, 1, "#ff7a59")
    assert many["noteText"] == "Note 0\nseconde ligne" and many["events"] == many["errors"] == 0


def test_a_click_ticks_at_once_and_emits_exactly_one_state_event_that_core_accepts(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      f.click(1);
      const afterClick={checked:f.checked(),events:f.events()};
      f.confirm();
      const afterConfirm={checked:f.checked(),events:f.events().length};
      f.click(1);
      return {afterClick,afterConfirm,second:f.events().slice(1),checked:f.checked(),errors:f.errors().length};""")
    assert result["afterClick"]["checked"] == [True, True, False]  # optimiste : avant toute réponse
    [(name, payload)] = result["afterClick"]["events"]
    assert name == "item_toggled" and [i["done"] for i in payload["items"]] == [True, True, False]
    assert payload["items"][2]["note"] == "Détail"  # le reste de l'élément part intact
    stored = _stored({}, {"items": [{"id": "a", "label": "Un", "done": True}, {"id": "b", "label": "Deux"},
                                    {"id": "c", "label": "Trois", "note": "Détail"}]})["data"]
    check = check_state_event(MANIFEST, name, payload, {"items": stored["items"]}, stored)
    assert check.outcome is StateEventOutcome.OK, check.detail
    assert result["afterConfirm"] == {"checked": [True, True, False], "events": 1}  # confirmation : rien de plus
    [(name, payload)] = result["second"]
    assert name == "item_toggled" and [i["done"] for i in payload["items"]] == [True, False, False]
    assert result["checked"] == [True, False, False] and result["errors"] == 0


def test_fast_ticks_coalesce_behind_the_write_in_flight(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      f.click(1);f.click(2);
      const before=f.events().length;
      f.confirm();
      return {before,events:f.events().map(e=>[e[0],e[1].items.map(i=>i.done)]),checked:f.checked()};""")
    # Deux actions avant la confirmation : la seconde attend (sa base serait dépassée), puis part seule.
    assert result["before"] == 1
    assert result["events"] == [["item_toggled", [True, True, False]], ["item_toggled", [True, True, True]]]
    assert result["checked"] == [True, True, True]


def test_completion_is_notified_once_per_user_completion_confirmed_by_core(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      const names=()=>f.events().map(e=>e[0]);
      f.click(1);f.confirm();f.click(2);
      const beforeConfirm=names();
      f.confirm();
      const done=f.events().slice(-1)[0];
      const marked=f.doc.getElementById('ck').hasAttribute('data-complete');
      const countText=f.doc.getElementById('ck-count').textContent;
      f.update({props:{accent:'#c6a0ff',show_progress:true},data:f.events().filter(e=>e[0]==='item_toggled').pop()[1]});
      const afterAccent=names().length;
      f.click(0);f.confirm();f.click(0);f.confirm();
      const again=names();
      const g=checklist();g.init(D.all_done);g.update({props:{accent:'#ff7a59',show_progress:true},data:D.all_done.data});
      return {beforeConfirm,done,marked,countText,afterAccent,again,brainComplete:g.events().length};""")
    assert result["beforeConfirm"] == ["item_toggled"] * 2  # pas de complétion avant que Core ait écrit
    assert result["done"] == ["checklist_completed", {"count": 3}]
    assert result["marked"] and result["countText"] == "Terminé · 3/3"
    assert result["afterAccent"] == 3  # mise à jour pendant que la liste est complète : rien
    assert result["again"] == ["item_toggled", "item_toggled", "checklist_completed", "item_toggled", "item_toggled",
                               "checklist_completed"]  # décocher puis recocher : nouvelle complétion
    assert result["brainComplete"] == 0  # une liste complète venue de Jarvis n'est pas une action de l'utilisateur
    _, problems = validate_value(MANIFEST.events["checklist_completed"].payload, {"count": 3}, "payload")
    assert problems == ()


def test_brain_replacement_during_a_write_wins_and_says_the_tick_was_lost(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      const first=f.rows()[0];
      f.click(1);
      f.update(D.three);  // `stale` : l'hôte renvoie l'état connu (le shim n'y voit aucun changement)
      const afterResync=f.checked();
      f.update(D.brain);  // puis la scène apporte la liste de Jarvis
      const out={afterResync,labels:f.rows().map(r=>r.byClass('ck-label')[0].textContent),checked:f.checked(),
        notice:f.notice(),sameNode:f.rows()[0]===first,events:f.events().length};
      f.clock.advance(6000);
      out.noticeLater=f.notice();out.eventsLater=f.events().length;
      return out;""")
    assert result["afterResync"] == [True, True, False]
    assert result["labels"] == ["Remplacé par Jarvis", "Autre"] and result["checked"] == [False, False]
    assert "pas été enregistrée" in result["notice"] and result["sameNode"]  # ligne réutilisée, pas recréée
    assert result["events"] == 1 and result["eventsLater"] == 1  # rien ne repart, aucun délai ne réécrit
    assert result["noticeLater"] == ""


def test_an_unconfirmed_tick_rolls_back_and_an_oversized_list_is_refused_visibly(tmp_path):
    big = _stored({}, {"items": [{"id": f"i{n}", "label": "L" * 200, "note": "N" * 500} for n in range(24)]})
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      f.click(2);
      f.clock.advance(4999);const pending=f.checked();
      f.clock.advance(1);
      const rolled={checked:f.checked(),notice:f.notice()};
      const g=checklist();g.init(D.big);g.click(0);
      return {pending,rolled,big:{checked:g.checked()[0],notice:g.notice(),events:g.events().length,errors:g.errors().length}};""",
                  big=big)
    assert result["pending"] == [True, False, True]
    assert result["rolled"]["checked"] == [True, False, False] and "pas encore confirmée" in result["rolled"]["notice"]
    # Plus de 16 Kio : le shim refuse l'émission, la coche est défaite et dite en français (jamais une bande d'erreur).
    assert result["big"]["checked"] is False and "trop longue" in result["big"]["notice"]
    assert result["big"]["events"] == 0 and result["big"]["errors"] == 0


def test_fifty_updates_reuse_rows_and_never_add_a_listener_and_accent_needs_no_source_change(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.many);
      const listeners=listenerCount(f.doc);
      const row0=f.rows()[0];
      const counts=[];
      for(let n=0;n<50;n++){
        const items=D.many.data.items.slice(0,40+(n%25)).map((it,i)=>Object.assign({},it,{label:it.label+' v'+n,done:(i+n)%3===0}));
        f.update({props:{accent:n%2?'#ff7a59':'#6fe3a4',show_progress:n%7!==0},data:{items}});
        counts.push(listenerCount(f.doc));
      }
      const rowListeners=f.doc.created.filter(e=>e.className==='ck-item').reduce((n,e)=>n+Object.values(e.listeners).reduce((m,l)=>m+l.length,0),0);
      return {listeners,counts:[...new Set(counts)],sameRow:f.rows()[0]===row0,rowListeners,rows:f.rows().length,
        label:f.rows()[3].byClass('ck-label')[0].textContent,accent:f.doc.documentElement.style.vars['--jv-accent'],
        prop:f.doc.documentElement.style.vars['--jv-prop-accent'],events:f.events().length};""")
    assert result["counts"] == [result["listeners"]]  # aucune croissance sur 50 mises à jour
    assert result["sameRow"] and result["rowListeners"] == 0  # lignes réutilisées par position, écoute déléguée à la liste
    assert result["rows"] == 40 + 49 % 25 and result["label"] == "Élément 3 v49"
    assert result["accent"] == result["prop"] == "#ff7a59" and result["events"] == 0
    assert "#ff7a59" not in TEXT["behavior.js"] + TEXT["style.css"]  # la couleur vient des props, pas du source


def test_keyboard_one_tab_stop_arrows_home_end_and_space_toggles(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      const stops=()=>f.rows().map(r=>r.getAttribute('tabindex'));
      const focusIndex=()=>f.rows().indexOf(f.doc.activeElement);
      const out={initial:stops()};
      f.rows()[0].focus();
      const steps=[];
      for(const k of ['ArrowDown','ArrowDown','ArrowDown','ArrowUp','Home','End']){const ev=f.key(k);steps.push([k,focusIndex(),ev.defaultPrevented])}
      out.steps=steps;out.stopsAfter=stops();
      const space=f.key(' ');
      out.space={prevented:space.defaultPrevented,checked:f.checked(),events:f.events().map(e=>e[0])};
      const enter=f.key('Enter');const ctrl=f.key('a');
      out.ignored={enter:enter.defaultPrevented,other:ctrl.defaultPrevented,events:f.events().length};
      f.update(D.brain);  // la liste rétrécit sous le focus : le focus reste dans la liste
      out.afterShrink={focus:focusIndex(),stops:stops()};
      return out;""")
    assert result["initial"] == ["0", "-1", "-1"]
    assert result["steps"] == [["ArrowDown", 1, True], ["ArrowDown", 2, True], ["ArrowDown", 2, True],
                               ["ArrowUp", 1, True], ["Home", 0, True], ["End", 2, True]]
    assert result["stopsAfter"] == ["-1", "-1", "0"]
    assert result["space"] == {"prevented": True, "checked": [True, False, True], "events": ["item_toggled"]}
    assert result["ignored"] == {"enter": False, "other": False, "events": 1}
    assert result["afterShrink"] == {"focus": 1, "stops": ["-1", "0"]}


def test_the_real_host_resends_on_stale_and_the_frame_reconciles_from_the_scene(tmp_path):
    """Hôte réel ↔ vrai shim ↔ comportement livré : un clic, Core répond `stale`, la scène apporte la liste de Jarvis.

    Le paquet est servi par le vrai catalogue (`PrefabService.bundle`) depuis le paquet livré.
    """

    import asyncio

    from jarvis.adapters.file_prefab_library import FilePrefabLibrary, FilePrefabRuntime
    from jarvis.core.prefab_service import PrefabService

    async def served():
        service = PrefabService(FilePrefabLibrary(FOLDER.parents[1], tmp_path / "data"),
                                runtime=FilePrefabRuntime(FOLDER.parents[2] / "runtime"))
        await service.start()
        return await service.bundle("jarvis.checklist", 1)

    result = node(tmp_path, r"""
      const answers=[];
      const b=bench({bundles:{'jarvis.checklist@1':D.bundle},postEvent:(e)=>Promise.resolve(answers.shift()||{outcome:'applied'})});
      const s=b.slot();
      b.host.mount(s,{object_id:'ck-1',title:'Liste',prefab:{id:'jarvis.checklist',version:1},props:D.three.props,data:D.three.data});
      await flush();
      const frame=b.frameOf(s);
      const fdoc=new FakeDocument();parseTemplate(fdoc.body,D.template);
      const c=clock();let deliver=null;
      const shim=Shim.createShim({post:(m)=>b.win.dispatch({source:frame.contentWindow,origin:'null',data:JSON.parse(JSON.stringify(m))}),
        listen:(fn)=>{deliver=fn},document:fdoc});
      frame.contentWindow.postMessage=(m)=>deliver(JSON.parse(JSON.stringify(m)));
      frame.load();
      shim.load((api)=>new Function('jarvis','document','window','setTimeout','clearTimeout',D.behavior)(api,fdoc,new FakeWindow(),c.setTimeout,c.clearTimeout));
      await flush();
      const rows=()=>fdoc.getElementById('ck-list').children;
      answers.push({outcome:'stale',reason:'stale',revision:7});
      fire(rows()[1],'click');
      const optimistic=rows()[1].getAttribute('aria-checked');
      await flush();
      const posted=b.posted.map(e=>({event:e.event,basis:e.basis.items.map(i=>i.done),payload:e.payload.items.map(i=>i.done)}));
      b.host.update('ck-1',D.three.props,D.brain.data);  // le flux de scène
      await flush();
      return {optimistic,posted,iframes:s.children.filter(n=>n.tagName==='IFRAME').length,sameFrame:b.frameOf(s)===frame,
        labels:rows().map(r=>r.textContent),notice:fdoc.getElementById('ck-notice').textContent,
        failed:b.logs.filter(l=>l.key==='scene.prefab_event_failed').map(l=>l.data.outcome),
        winListeners:b.win.count('message')};""",
                  bundle=asyncio.run(served()))
    assert result["optimistic"] == "true"
    assert result["posted"] == [{"event": "item_toggled", "basis": [True, False, False], "payload": [True, True, False]}]
    assert result["iframes"] == 1 and result["sameFrame"] and result["winListeners"] == 1
    assert result["labels"] == ["Remplacé par Jarvis", "Autre"] and "pas été enregistrée" in result["notice"]
    assert result["failed"] == ["stale"]


def test_raw_brain_data_without_defaults_is_confirmed_by_cores_defaulted_write(tmp_path):
    """La scène garde `{id, label}` sans `done` ; Core écrit la coche complétée de ses défauts."""

    raw = [{"id": "a", "label": "Un"}, {"id": "b", "label": "Deux", "note": "n"}]
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.raw);
      f.click(0);
      const sent=f.events()[0][1];
      return {sent,checked:f.checked()};""")
    sent = result["sent"]
    assert [item["done"] for item in sent["items"]] == [True, False]
    stored = {"items": raw}
    check = check_state_event(MANIFEST, "item_toggled", sent, {"items": raw}, stored)
    assert check.outcome is StateEventOutcome.OK, check.detail
    written = check.merged["items"]
    assert written == sent["items"]  # ce que Core écrit = ce que le cadre a envoyé : la coche se confirme
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.raw);
      f.click(0);f.click(1);
      f.update({props:{},data:{items:D.written}});
      return {checked:f.checked(),notice:f.notice(),events:f.events().map(e=>e[0])};""", written=written)
    assert result == {"checked": [True, True], "notice": "", "events": ["item_toggled", "item_toggled"]}


# ------------------------------------------------------------ reprise QA S06 (B1-B6)


def test_a_refused_or_stale_write_is_undone_at_once_from_its_event_result_b1(tmp_path):
    result = node(tmp_path, r"""
      const out={};
      for(const [outcome,reason] of [['stale','stale'],['refused','invalid_event'],['failed','unreachable'],['refused','rate_limited']]){
        const f=checklist();f.init(D.three);
        f.click(1);
        const optimistic=f.checked();
        f.result(outcome,reason);                           // aucune attente de 5 s
        const now={checked:f.checked(),notice:f.notice()};
        f.clock.advance(5000);                              // le délai de dernier recours ne repasse pas
        out[outcome+'/'+reason]={optimistic,now,later:f.checked(),events:f.events().length};
      }
      return out;""")
    notices = {key: value["now"]["notice"] for key, value in result.items()}
    assert notices == {
        "stale/stale": "La liste a changé entre-temps : votre coche n’a pas été enregistrée.",
        "refused/invalid_event": "Jarvis a refusé la coche : elle n’a pas été enregistrée.",
        "failed/unreachable": "Jarvis est injoignable : votre coche n’a pas été enregistrée.",
        "refused/rate_limited": "Trop de coches à la fois : la dernière n’a pas été enregistrée.",
    }
    for value in result.values():
        assert value["optimistic"] == [True, True, False]
        assert value["now"]["checked"] == value["later"] == [True, False, False] and value["events"] == 1


def test_a_stale_note_survives_the_forced_resync_and_the_newer_list_b1(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      f.click(1);
      f.result('stale','stale');
      f.update(D.three,true);                               // l'hôte renvoie aussitôt l'état connu, forcé
      const afterForced={checked:f.checked(),notice:f.notice()};
      f.update(D.brain);                                    // puis la liste plus récente de Core
      return {afterForced,labels:f.rows().map(r=>r.byClass('ck-label')[0].textContent),notice:f.notice()};""")
    assert result["afterForced"]["checked"] == [True, False, False]
    assert "pas été enregistrée" in result["afterForced"]["notice"]
    assert result["labels"] == ["Remplacé par Jarvis", "Autre"] and "pas été enregistrée" in result["notice"]


def test_a_late_confirmation_after_the_timeout_confirms_and_still_announces_completion_b2(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      f.click(1);f.confirm();
      f.click(2);                                           // la coche qui complète la liste
      f.clock.advance(5000);                                // dernier recours : aucune issue
      const timedOut={checked:f.checked(),notice:f.notice()};
      const items=f.sent().pop();
      f.update({props:D.props,data:{items}});               // Core avait bien écrit : la scène l'apporte en retard
      return {timedOut,checked:f.checked(),notice:f.notice(),events:f.events().map(e=>e[0]),
        last:f.events().slice(-1)[0],complete:f.doc.getElementById('ck').hasAttribute('data-complete')};""")
    assert result["timedOut"]["checked"] == [True, True, False]
    assert result["timedOut"]["notice"] == "Coche pas encore confirmée : la liste affichée est la dernière enregistrée."
    assert "Réessayez" not in result["timedOut"]["notice"]  # rien n'invite à décocher ce que Core va peut-être écrire
    assert result["checked"] == [True, True, True] and result["notice"] == "" and result["complete"]
    assert result["events"] == ["item_toggled", "item_toggled", "checklist_completed"]
    assert result["last"] == ["checklist_completed", {"count": 3}]


def test_a_late_verdict_of_a_timed_out_write_changes_nothing_b2(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      f.click(1);f.clock.advance(5000);
      f.click(2);                                           // nouvelle écriture après le délai
      f.result('stale','stale');                            // l'issue tardive de la première
      const afterOld={checked:f.checked(),events:f.events().length,notice:f.notice()};
      f.confirm();                                          // la seconde est confirmée
      return {afterOld,checked:f.checked()};""")
    # L'écran ne bouge pas ; la note « pas encore confirmée » devient définitive.
    assert result["afterOld"] == {"checked": [True, False, True], "events": 2,
                                  "notice": "La liste a changé entre-temps : votre coche n’a pas été enregistrée."}
    assert result["checked"] == [True, False, True]


def test_the_notice_lives_in_the_sticky_head_as_a_status_b3(tmp_path):
    import re

    template, style = TEXT["template.html"], re.sub(r"/\*.*?\*/", "", TEXT["style.css"], flags=re.S)
    head = re.search(r'<div class="ck-head"[^>]*>(.*?)</div>\s*<div class="ck-list"', template, re.S).group(1)
    assert 'id="ck-notice" role="status" aria-live="polite"' in head and 'id="ck-progress"' in head
    rule = re.search(r"\.ck-head\{([^}]*)\}", style).group(1)
    assert "position:sticky" in rule and "top:0" in rule and "background:var(--jv-ground)" in rule
    assert re.search(r":root:has\(\.ck-notice:not\(:empty\)\)\{scroll-padding-top:\d+px\}", style)


def test_lows_replacement_clears_space_repeat_french_only_and_an_untick_cancels_completion_b4(tmp_path):
    big = _stored({}, {"items": [{"id": f"i{n}", "label": "L" * 200, "note": "N" * 500} for n in range(24)]})
    result = node(tmp_path, r"""
      const out={};
      let f=checklist();f.init(D.three);f.click(1);f.clock.advance(5000);
      const before=f.notice();f.update(D.brain);
      out.replaced={before,after:f.notice()};
      f=checklist();f.init(D.three);f.rows()[1].focus();
      f.key(' ');fire(f.rows()[1],'keydown',{key:' ',repeat:true});fire(f.rows()[1],'keydown',{key:' ',repeat:true});
      out.repeat={checked:f.checked(),events:f.events().length};
      f=checklist();f.init(D.big);f.click(0);
      out.big={notice:f.notice(),checked:f.checked()[0],events:f.events().length,errors:f.errors().length};
      f=checklist();f.init(D.three);
      f.click(1);f.confirm();
      f.click(2);                                           // complète la liste (en vol)
      f.click(2);                                           // défaite avant la confirmation
      f.confirm();                                          // Core confirme la liste complète
      const afterFirst=f.events().map(e=>e[0]);
      f.confirm();                                          // puis la décoche partie ensuite
      out.untick={afterFirst,events:f.events().map(e=>e[0]),checked:f.checked()};
      return out;""", big=big)
    assert result["replaced"]["before"] and result["replaced"]["after"] == ""
    assert result["repeat"] == {"checked": [True, True, False], "events": 1}
    big = result["big"]
    assert big["notice"] == "Liste trop longue pour être envoyée : la coche n’a pas été enregistrée."
    assert big["checked"] is False and big["events"] == 0 and big["errors"] == 0
    # Défaite avant que Core n'écrive la complétion : la liste n'est plus complète, rien n'est annoncé.
    assert result["untick"]["afterFirst"] == ["item_toggled"] * 3
    assert result["untick"]["events"] == ["item_toggled"] * 3 and result["untick"]["checked"] == [True, True, False]


def test_same_ids_with_another_done_during_a_write_is_not_a_confirmation_b5(tmp_path):
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.three);
      f.click(1);                                           // envoie [T,T,F]
      const items=f.sent()[0].map(it=>Object.assign({},it,{done:it.id==='c'}));  // mêmes ids, autre `done`
      f.update({props:D.props,data:{items}});
      return {checked:f.checked(),notice:f.notice(),events:f.events().map(e=>e[0])};""")
    assert result["checked"] == [False, False, True]  # la liste de Core, pas la coche
    assert "pas été enregistrée" in result["notice"] and result["events"] == ["item_toggled"]


def test_sixty_four_long_labels_stay_tickable_above_8_kib_b6(tmp_path):
    long_items = [{"id": f"item-{n:02d}", "label": (f"Élément {n:02d} " + "à vérifier avant la livraison " * 4)[:95]}
                  for n in range(64)]
    stored = _stored({}, {"items": long_items})
    result = node(tmp_path, r"""
      const f=checklist();f.init(D.long);
      f.click(63);
      const sent=f.events()[0];
      f.confirm();
      return {rows:f.rows().length,sent,checked:f.checked().filter(Boolean).length,notice:f.notice()};""", long=stored)
    assert result["rows"] == 64 and result["notice"] == "" and result["checked"] == 1
    name, payload = result["sent"]
    size = len(__import__("json").dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert 8 * 1024 < size <= 16 * 1024  # au-delà de l'ancienne borne de 8 Kio
    check = check_state_event(MANIFEST, name, payload, {"items": stored["data"]["items"]}, stored["data"])
    assert check.outcome is StateEventOutcome.OK, check.detail
