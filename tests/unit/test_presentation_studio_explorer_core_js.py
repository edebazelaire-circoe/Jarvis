"""Fonctions pures de l'explorateur de variantes, par node (studio de présentation, Slice 18).

Le module testé est le VRAI `control_center_presentation_studio_explorer_core.js`. Épinglé : l'arbre se construit de n'importe quel graphe
(chaînes, éventails, 60 niveaux, archivées, parent absent, cycle) sans récursion ; la navigation clavier est celle de l'arbre ARIA ; le texte
d'auteur est nettoyé (NUL, marques bidirectionnelles, emoji non coupés) ; chaque refus de Core a sa phrase française ; les bornes de titre et
de raison sont celles de Core ; les préférences illisibles ne cassent rien.
"""

from __future__ import annotations

import re

from tests.fakes.explorer_js import CORE_JS, run_node

FIXTURES = r"""
const id=n=>'psv_'+String(n).padStart(32,'0');
const node=(n,parent,extra)=>Object.assign({variant_id:id(n),variant_number:n,title:'V'+n,parent_variant_id:parent?id(parent):null,
  state:'live',created_at:'2026-10-07T10:00:00.000000Z',active:false,scene_count:3,rationale:'',created_by:'user',revision:1},extra||{});
const chain=n=>Array.from({length:n},(_,i)=>node(i+1,i?i:null));
const fan=n=>[node(1,null),...Array.from({length:n-1},(_,i)=>node(i+2,1))];
"""


def test_a_chain_of_sixty_levels_flattens_without_recursion_and_keeps_every_depth(tmp_path):
    out = run_node(tmp_path, FIXTURES + """
const f=C.buildForest(chain(60),'live');
const rows=C.flatten(f,new Set());
const folded=C.flatten(f,new Set([id(10)]));
return {size:f.size,depths:rows.map(r=>r.depth).slice(0,4).concat(rows.slice(-1).map(r=>r.depth)),rows:rows.length,folded:folded.length,
  lastId:rows[rows.length-1].id===id(60),desc:rows[0].descendants,leaf:rows[59].hasChildren,
  anc:C.ancestorsOf(f,id(60)).length,sub:C.subtreeIds(f,id(55)).length};
""")
    assert out["size"] == 60 and out["rows"] == 60 and out["depths"] == [0, 1, 2, 3, 59]
    assert out["folded"] == 10 and out["lastId"] and out["desc"] == 59 and out["leaf"] is False
    assert out["anc"] == 59 and out["sub"] == 6


def test_a_wide_fan_keeps_numeric_order_and_sibling_positions(tmp_path):
    out = run_node(tmp_path, FIXTURES + """
const shuffled=fan(64).reverse();
const rows=C.flatten(C.buildForest(shuffled,'live'),new Set());
return {first:rows[0].node.variant_number,numbers:rows.map(r=>r.node.variant_number).slice(0,5),setSize:rows[1].setSize,pos:rows.slice(1,4).map(r=>r.posInSet),
  last:rows[63].node.variant_number};
""")
    assert out["numbers"] == [1, 2, 3, 4, 5] and out["setSize"] == 63 and out["pos"] == [1, 2, 3] and out["last"] == 64


def test_archived_forest_marks_roots_whose_parent_is_still_live_and_never_mixes_states(tmp_path):
    out = run_node(tmp_path, FIXTURES + """
const nodes=[node(1,null),node(2,1),node(3,2,{state:'archived'}),node(4,3,{state:'archived'}),node(5,1,{state:'archived'}),node(6,null,{state:'archived',parent_variant_id:id(99)})];
const live=C.buildForest(nodes,'live'),dead=C.buildForest(nodes,'archived');
return {live:live.size,dead:dead.size,roots:dead.roots,outside:[...dead.outside],depth4:dead.depth.get(id(4)),
  rows:C.flatten(dead,new Set()).map(r=>[r.node.variant_number,r.depth,r.outside])};
""")
    assert out["live"] == 2 and out["dead"] == 4
    assert out["rows"] == [[3, 0, True], [4, 1, False], [5, 0, True], [6, 0, True]]
    assert out["depth4"] == 1


def test_a_cycle_a_self_parent_a_duplicate_and_garbage_never_throw_or_lose_a_node(tmp_path):
    out = run_node(tmp_path, FIXTURES + """
const nodes=[node(1,2),node(2,1),node(3,3),node(4,null),null,{},{variant_id:5},node(4,null,{title:'dup'}),'x'];
const f=C.buildForest(nodes,'live');
const rows=C.flatten(f,new Set());
return {size:f.size,rows:rows.map(r=>[r.node.variant_number,r.depth,r.cyclic]),roots:f.roots.length,none:C.flatten(C.buildForest(null,'live'),null).length};
""")
    assert out["size"] == 4 and out["none"] == 0
    numbers = sorted(row[0] for row in out["rows"])
    assert numbers == [1, 2, 3, 4], "every valid node is shown exactly once"
    cyc = {row[0]: row[2] for row in out["rows"]}
    assert cyc[1] and not cyc[4]


def test_a_graph_of_sixty_four_live_and_a_hundred_and_twenty_eight_archived_builds_fast(tmp_path):
    out = run_node(tmp_path, FIXTURES + """
const nodes=[];
for(let i=1;i<=64;i++)nodes.push(node(i,i>1?Math.max(1,i-1-(i%5)):null));
for(let i=65;i<=192;i++)nodes.push(node(i,i>65?65:null,{state:'archived'}));
const t0=performance.now();
let rows=0;
for(let k=0;k<50;k++){const a=C.flatten(C.buildForest(nodes,'live'),new Set()),b=C.flatten(C.buildForest(nodes,'archived'),new Set());rows=a.length+b.length}
return {rows,ms:(performance.now()-t0)/50};
""")
    assert out["rows"] == 192
    assert out["ms"] < 20, f"one rebuild of 64 live + 128 archived took {out['ms']:.2f} ms"


def test_the_window_renders_only_the_visible_rows_plus_a_margin(tmp_path):
    out = run_node(tmp_path, """
return [C.windowOf(0,0,500),C.windowOf(64,0,480,48,0),C.windowOf(64,960,480,48,6),C.windowOf(64,99999,480,48,6),C.windowOf(5,0,9999,48,6)];
""")
    assert out[0] == {"start": 0, "end": 0} and out[1] == {"start": 0, "end": 10} and out[2] == {"start": 14, "end": 36}
    assert out[4] == {"start": 0, "end": 5}
    assert out[3]["end"] == 64, "scrolled past the end: the window still ends at the last row"


# ------------------------------------------------------------------ clavier

def test_the_tree_keys_follow_the_aria_tree_pattern(tmp_path):
    out = run_node(tmp_path, FIXTURES + """
const f=C.buildForest([node(1,null),node(2,1),node(3,2),node(4,1),node(5,null)],'live');
const folded=C.flatten(f,new Set([id(1)]));        /* 1 (collapsed), 5 */
const rows=C.flatten(f,new Set());                 /* 1,2,3,4,5 */
const k=(rowsList,i,key,m)=>C.treeKey(rowsList,i,key,m);
const num=a=>a&&a.id?Number(a.id.slice(-2)):null;
return {
 down:num(k(rows,0,'ArrowDown')),up:num(k(rows,0,'ArrowUp')),end:num(k(rows,0,'End')),home:num(k(rows,4,'Home')),pgdn:num(k(rows,0,'PageDown')),
 rightOpen:k(rows,0,'ArrowRight'),rightClosed:k(folded,0,'ArrowRight'),rightLeaf:k(rows,2,'ArrowRight'),
 leftOpen:k(rows,0,'ArrowLeft'),leftChild:k(rows,2,'ArrowLeft'),leftRoot:k(rows,4,'ArrowLeft'),
 enter:k(rows,1,'Enter'),space:k(rows,1,' '),f2:k(rows,1,'F2'),del:k(rows,1,'Delete'),n:k(rows,1,'n'),N:k(rows,1,'N'),a:k(rows,1,'a'),
 menu:k(rows,1,'ContextMenu'),shiftF10:k(rows,1,'F10',{shift:true}),f10:k(rows,1,'F10'),ctrl:k(rows,1,'ArrowDown',{ctrl:true}),alt:k(rows,1,'n',{alt:true}),
 unknown:k(rows,1,'x'),empty:C.treeKey([],0,'ArrowDown'),bad:k(rows,9,'ArrowDown')};
""")
    assert (out["down"], out["up"], out["end"], out["home"], out["pgdn"]) == (2, 1, 5, 1, 5)
    assert out["rightOpen"]["type"] == "focus" and out["rightClosed"]["type"] == "expand" and out["rightLeaf"] is None
    assert out["leftOpen"]["type"] == "collapse" and out["leftChild"]["type"] == "focus" and out["leftRoot"] is None
    assert [out[k]["type"] for k in ("enter", "space", "f2", "del", "n", "N", "a", "menu", "shiftF10")] == [
        "select", "select", "rename", "archive", "branch", "branch", "activate", "menu", "menu"]
    assert out["f10"] is None and out["ctrl"] is None and out["alt"] is None and out["unknown"] is None
    assert out["empty"] is None and out["bad"] is None


# ------------------------------------------------------------------ texte non fiable

def test_untrusted_text_loses_controls_nul_and_bidi_marks_but_keeps_emoji_and_rtl_whole(tmp_path):
    out = run_node(tmp_path, """
const hostile='a\\u0000b\\u202eevil\\u202c\\u2066x\\u2069\\n\\tline\\u2028two\\u0007';
const emoji='🎨'.repeat(100), zwj='👩‍👩‍👧‍👦'.repeat(30);
return {hostile:C.cleanLine(hostile,200),clippedEmoji:Array.from(C.cleanLine(emoji,10)),zwj:Array.from(C.cleanLine(zwj,300)).length,
  rtl:C.cleanLine('مرحبا بالعالم',200),huge:C.cleanLine('x'.repeat(5_000_000),30).length,none:[C.cleanLine(null),C.cleanLine(undefined,5),C.cleanLine(42)],
  spaces:C.cleanLine('  a \\n\\n  b   ',20),clipPoints:Array.from(C.clip('abcdef',4))};
""")
    assert "\u202e" not in out["hostile"] and "\x00" not in out["hostile"] and "\x07" not in out["hostile"]
    assert "evil" in out["hostile"] and "line two" in out["hostile"]
    assert len(out["clippedEmoji"]) == 10 and all(ch == "🎨" for ch in out["clippedEmoji"][:9]) and out["clippedEmoji"][9] == "…"
    assert out["zwj"] == len("👩‍👩‍👧‍👦" * 30), "a family emoji (ZWJ sequence) is not stripped"
    assert out["rtl"] == "مرحبا بالعالم"
    assert out["huge"] <= 30
    assert out["none"] == ["", "", "42"] and out["spaces"] == "a b"
    assert out["clipPoints"] == ["a", "b", "c", "…"]


def test_titles_and_reasons_follow_the_core_bounds(tmp_path):
    out = run_node(tmp_path, """
const r=(n)=>C.checkRationale('🎨'.repeat(n));
return {empty:C.checkTitle('   '),ok:C.checkTitle(' Cercle sombre '),long:C.checkTitle('x'.repeat(81)),edge:C.checkTitle('x'.repeat(80)).ok,
  emoji200:r(200).ok,emoji201:r(201).ok,accents400:C.checkRationale('é'.repeat(400)).ok,accents401:C.checkRationale('é'.repeat(401)).ok,
  quotes:C.checkRationale('"'.repeat(400)).ok,quotes401:C.checkRationale('"'.repeat(401)).ok,chars601:C.checkRationale('a'.repeat(601)).ok,
  chars600:C.checkRationale('a'.repeat(600)).ok,blank:C.checkRationale('').ok,bytes:C.rationaleBytes('é"')};
""")
    assert out["empty"]["ok"] is False and out["ok"] == {"ok": True, "value": "Cercle sombre"} and out["long"]["ok"] is False and out["edge"]
    assert out["emoji200"] and not out["emoji201"] and out["accents400"] and not out["accents401"]
    assert out["quotes"] and not out["quotes401"] and not out["chars601"] and out["chars600"] and out["blank"]
    assert out["bytes"] == 4, "'é' is 2 bytes and the quote counts 2 once escaped"


# ------------------------------------------------------------------ temps relatif

def test_relative_time_is_french_and_honest_about_a_diverging_clock(tmp_path):
    out = run_node(tmp_path, """
const now=new Date(2026,9,8,14,0,0).getTime();
const ago=(s)=>new Date(now-s*1000).toISOString();
const local=(y,m,d,h)=>new Date(y,m,d,h,0,0).toISOString();
return {now:C.relativeTime(ago(10),now),min:C.relativeTime(ago(300),now),hour:C.relativeTime(local(2026,9,8,11),now),yesterday:C.relativeTime(local(2026,9,7,22),now),
  days:C.relativeTime(local(2026,9,4,12),now),old:C.relativeTime(local(2026,8,12,12),now),year:C.relativeTime(local(2025,0,3,12),now),
  future:C.relativeTime(ago(-7200),now),bad:C.relativeTime('nope',now),none:C.relativeTime(undefined,now),abs:C.absoluteTime(local(2026,9,8,9))};
""")
    assert out["now"] == "à l'instant" and out["min"] == "il y a 5 min" and out["hour"] == "il y a 3 h" and out["yesterday"] == "hier"
    assert out["days"] == "il y a 4 j" and out["old"] == "12 sept." and out["year"] == "3 janv. 2025"
    assert re.fullmatch(r"\d\d/\d\d/\d{4} \d\d:\d\d", out["future"]), "a clock in the future shows the date, not an absurd relative time"
    assert out["bad"] == "" and out["none"] == "" and out["abs"].startswith("08/10/2026 09:")


# ------------------------------------------------------------------ refus de Core

def test_every_core_refusal_has_a_french_sentence_with_its_next_step(tmp_path):
    out = run_node(tmp_path, """
const codes=Object.keys(C.REFUSALS);
const text=(c,ctx)=>C.describeRefusal({code:c,status:409,message:'raw english'},ctx);
return {codes,stale:text('presentation_studio_stale_revision'),conf:text('presentation_studio_confirmation_stale'),play:text('presentation_studio_variant_in_playback'),
  limitBranch:text('presentation_studio_limit_reached',{op:'branch'}),limitRestore:text('presentation_studio_limit_reached',{op:'restore'}),
  limitPlan:text('presentation_studio_limit_reached',{op:'plan'}),protectedActive:text('presentation_studio_active_variant_protected'),
  unknown:C.describeRefusal({code:'weird_code',status:400,message:'a\\u0000b'}),timeout:C.describeRefusal({code:'timeout',after:15000}),
  net:C.describeRefusal({code:'network',message:'fetch failed'}),s503:C.describeRefusal({status:503}),origin:C.describeRefusal({status:403}),none:C.describeRefusal(null)};
""")
    assert len(out["codes"]) >= 10
    assert out["stale"]["kind"] == "stale" and "relu" in out["stale"]["text"] and "refaites" in out["stale"]["text"]
    assert out["conf"]["kind"] == "stale" and "Rien n'a été archivé" in out["conf"]["text"]
    assert "lecture" in out["play"]["text"] and "Rien n'a été déplacé" in out["play"]["text"]
    assert "64" in out["limitBranch"]["text"] and "64" in out["limitRestore"]["text"] and "128" in out["limitPlan"]["text"]
    assert "active" in out["protectedActive"]["text"]
    assert out["unknown"]["text"].startswith("Core a refusé : weird_code") and "\x00" not in out["unknown"]["text"]
    assert "15 s" in out["timeout"]["text"] and "peut-être" in out["timeout"]["text"]
    assert out["net"]["kind"] == "failed" and out["s503"]["kind"] == "failed" and "origine" in out["origin"]["text"]
    assert out["none"]["text"].startswith("Core a refusé")


def test_the_archive_plan_becomes_a_screen_model_with_the_exact_set_and_the_replacement_choices(tmp_path):
    out = run_node(tmp_path, FIXTURES + """
const f=C.buildForest([node(1,null),node(2,1),node(3,2),node(4,1),node(5,null)],'live');
const answer={plan:{affected:[{variant_id:id(2),variant_number:2,title:'Deux\\u0000'},{variant_id:id(3),variant_number:3,title:'Trois'}],count:2,
  root_variant_id:id(2),includes_active:true,requires_new_active:true,suggested_active:id(1),activate_variant_id:null,blocked:'presentation_studio_active_variant_protected',revision:7},
  confirmation:null,expires_in_s:null};
const m=C.planModel(answer,f);
const ok=C.planModel({plan:{affected:[{variant_id:id(4),variant_number:4,title:'Q'}],count:1,root_variant_id:id(4),includes_active:false,requires_new_active:false,
  suggested_active:null,activate_variant_id:null,blocked:null,revision:7},confirmation:'psc_1.abc',expires_in_s:600},f);
return {m,ok,same:C.sameSet(m.rows,m.rows),diff:C.sameSet(m.rows,ok.rows),block:C.blockedText('presentation_studio_limit_reached'),none:C.blockedText(null)};
""")
    model = out["m"]
    assert [r["number"] for r in model["rows"]] == [2, 3] and model["rows"][0]["title"] == "Deux"
    assert [c["number"] for c in model["choices"]] == [1, 4, 5], "the remaining live variants, by number, are the candidates for the new active one"
    assert model["requiresNewActive"] and model["suggestedActive"].endswith("1") and "variante active" in model["blockedReason"] and model["token"] is None
    assert out["ok"]["token"] == "psc_1.abc" and out["ok"]["expiresInS"] == 600 and out["ok"]["blocked"] is None
    assert out["same"] is True and out["diff"] is False and out["none"] == ""


def test_unreadable_or_oversized_preferences_degrade_to_defaults_and_stay_bounded(tmp_path):
    out = run_node(tmp_path, """
const store=(raw)=>({getItem:()=>raw,setItem(k,v){this.saved=v}});
const bad=['{', 'null', '[]', '"x"', undefined];
const reads=bad.map(raw=>C.readPrefs(store(raw)));
const writer=store(undefined);
const collapsed={};for(let i=0;i<40;i++)collapsed['pst_'+i]=Array.from({length:500},(_,j)=>'psv_'+j);
C.writePrefs(writer,{collapsed,last:{a:'b'},archivedOpen:true});
const saved=JSON.parse(writer.saved);
const throwing={getItem(){throw new Error('blocked')},setItem(){throw new Error('quota')}};
return {reads,keys:Object.keys(saved.collapsed).length,per:saved.collapsed[Object.keys(saved.collapsed)[0]].length,open:saved.archivedOpen,
  blocked:C.readPrefs(throwing),writeOk:(()=>{C.writePrefs(throwing,{collapsed:{},last:{},archivedOpen:false});return true})(),nothing:C.readPrefs(null)};
""")
    assert all(r == {"collapsed": {}, "last": {}, "archivedOpen": False} for r in out["reads"])
    assert out["keys"] == 16 and out["per"] == 256 and out["open"] is True and out["writeOk"] is True
    assert out["blocked"]["archivedOpen"] is False and out["nothing"]["archivedOpen"] is False


def test_the_module_is_pure_and_never_builds_markup_from_strings():
    code = re.sub(r"/\*.*?\*/", "", CORE_JS.read_text(encoding="utf-8"), flags=re.S)
    for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "outerHTML", "eval(", "new Function"):
        assert forbidden not in code, forbidden
    assert "document." not in code and "fetch(" not in code and "localStorage" not in code, "pure: no DOM, no network, no storage global"
