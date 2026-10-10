"""Le modèle pur de la comparaison et de la composition (studio de présentation, Slice 19, moitié interface) : marques, mise en page, statuts, refus, demande de composition."""

from __future__ import annotations

from tests.fakes.explorer_js import run_node

V = "const v=(n)=>'psv_'+String(n).padStart(32,'0');const view=(o)=>Object.assign({presentation_id:'pst_x',revision:3,active:true,variant_ids:[v(1),v(2)],layout:'two_up',pair:null,shown:[v(1),v(2)],mode:'sync',"
V += "variants:[{variant_id:v(1),variant_number:1,title:'A',revision:4,active:true,scenes:[{scene_id:'s1',title:'Un',mapping:'identity',equivalents:{},suggestions:[]},{scene_id:'s2',title:'Deux',mapping:'none',equivalents:{},suggestions:[]}]},"
V += "{variant_id:v(2),variant_number:2,title:'B',revision:7,active:false,scenes:[{scene_id:'s1',title:'Un',mapping:'identity',equivalents:{},suggestions:[]}]}],"
V += "structure:{relation:'divergent',pairs:[]},unmapped:{[v(1)]:['s2']},links:[],anchors:{[v(1)]:'s2',[v(2)]:'s1'},problems:[]},o||{});\n"


def test_marks_layout_and_pane_models(tmp_path):
    out = run_node(tmp_path, V + """
let m=[];const live=()=>true;
const steps=[];
for(const id of ['a','b','c','d','e']){const r=CC.toggleMark(m,id,live);m=r.marks;steps.push(r.change+':'+CC.markState(m).count+':'+CC.markState(m).ok)}
const archived=CC.toggleMark([],'z',false);
const removed=CC.toggleMark(['a','b'],'a',live);
const pruned=CC.pruneMarks(['a','b','c'],id=>id!=='b');
const lay=CC.layoutOf(view());
const focus=CC.layoutOf(view({layout:'focus',pair:[v(1),v(2)],shown:[v(1)],variant_ids:[v(1),v(2),v(3),v(4)]}));
const narrow=CC.layoutOf(view(),300);
const nav={origin:{variant_id:v(1),scene_id:'s2'},results:{[v(2)]:{scene_id:'s1',status:'unmapped'}}};
const p1=CC.paneModel(view(),v(1),nav),p2=CC.paneModel(view(),v(2),nav),gone=CC.paneModel(view(),v(9),null);
return {steps,archived:archived.change,removed:removed.marks,pruned,lay:[lay.kind,lay.columns,lay.shown.length],focus:[focus.kind,focus.shown.length,focus.hidden.length],narrow:narrow.columns,
  p1:[p1.status,p1.index,p1.count,p1.sceneId],p2:[p2.status,p2.mapping,CC.paneLine(p2)],gone:[gone.missing,CC.paneLine(gone)],none:CC.paneModel(view(),v(1),null).status,
  struct:CC.structureOf(view()),aria:CC.paneAriaLabel(p1)};
""")
    assert out["steps"] == ["added:1:false", "added:2:true", "added:3:false", "added:4:true", "refused:4:true"]
    assert out["archived"] == "refused" and out["removed"] == ["b"] and out["pruned"] == ["a", "c"]
    assert out["lay"] == ["two_up", 2, 2] and out["focus"] == ["focus", 1, 3] and out["narrow"] == 1
    assert out["p1"] == ["origin", 1, 2, "s2"] and out["p2"][:2] == ["unmapped", "identity"] and "garde sa scène" in out["p2"][2]
    assert out["gone"][0] is True and out["none"] is None
    assert out["struct"]["relation"] == "divergent" and out["struct"]["unmappedTotal"] == 1 and "1 scène sans équivalent" in out["struct"]["text"]
    assert out["aria"].startswith("Variante 1, A, active, scène 2 sur 2") and "choisie" in out["aria"]


def test_keys_refusals_and_links(tmp_path):
    out = run_node(tmp_path, V + """
const keys=Object.fromEntries(['ArrowRight','ArrowLeft','ArrowUp','ArrowDown','PageDown','PageUp','Home','End','x'].map(k=>[k,CC.keyToStep(k)]));
const withCtrl=CC.keyToStep('ArrowRight',{ctrl:true});
const d=(code,op)=>CC.describe({code},{op});
const lv=view({links:[{a:{variant_id:v(1),scene_id:'s2'},b:{variant_id:v(2),scene_id:'s1'},stale:false},{a:{variant_id:v(1),scene_id:'gone'},b:{variant_id:v(2),scene_id:'s1'},stale:true}]});
return {keys,withCtrl,stale:d('presentation_studio_stale_revision'),map:d('presentation_studio_compare_mapping_conflict'),lim:d('presentation_studio_limit_reached','link'),
  fallback:d('presentation_studio_corrupt_document'),links:CC.linkRows(lv).map(r=>[CC.describeSide(r.a),CC.describeSide(r.b),r.stale])};
""")
    assert out["keys"] == {"ArrowRight": "next", "ArrowLeft": "previous", "ArrowUp": "previous", "ArrowDown": "next", "PageDown": "next", "PageUp": "previous", "Home": "first", "End": "last", "x": None}
    assert out["withCtrl"] is None
    assert out["stale"]["kind"] == "stale" and "a changé ailleurs" in out["stale"]["text"]
    assert out["map"]["kind"] == "refused" and "même variante" in out["map"]["text"]
    assert "64" in out["lim"]["text"] and out["fallback"]["kind"] == "failed"
    assert out["links"][0] == ["#1 · scène 2 « Deux »", "#2 · scène 1 « Un »", False] and out["links"][1][0] == "#1 · scène disparue" and out["links"][1][2] is True


def test_the_composition_request_is_built_validated_and_signed(tmp_path):
    out = run_node(tmp_path, V + """
const f=CC.emptyForm(view(),v(2));
const empty=CC.buildRequest(f,view(),{});
Object.assign(f,{title:'  Mix  <b>  ',narrative:v(2),rationale:'pourquoi',on_unmapped:'keep_motion',activate:true});
const ok=CC.buildRequest(f,view(),{expectedRevision:12});
const bad=CC.buildRequest(Object.assign({},f,{base:'psv_nope',art_direction:'psv_other'}),view(),{});
const long=CC.buildRequest(Object.assign({},f,{rationale:'x'.repeat(401)}),view(),{});
const same=CC.buildRequest(f,view(),{expectedRevision:12}).signature===ok.signature;
const rows=CC.conflictRows([{code:'score_scene_missing',dimension:'motion',message:'m\\u0000x',fix:'faites ceci',details:{}},null,{code:'x',dimension:'weird',message:'a',fix:''}]);
const sum=CC.planSummary({composition:{result:{scene_count:2,item_count:5,summary:'composed on #1.'},dimensions:[{dimension:'scenes',inherited:true,sources:[{variant_number:1}]},{dimension:'narrative',inherited:false,sources:[{variant_number:2}]}],warnings:['attention']}});
return {base:f.base,empty:[empty.ok,empty.errors.map(e=>e.field)],ok:[ok.ok,ok.request],bad:bad.errors.map(e=>e.field),long:long.errors.map(e=>e.field),same,rows,sum,sug:CC.suggestTitle(view(),CC.emptyForm(view(),v(1)))};
""")
    assert out["base"].endswith("02") and out["empty"][0] is False and out["empty"][1] == ["title"]
    ok, request = out["ok"]
    assert ok is True and request["title"] == "Mix <b>" and request["base"].endswith("02") and request["narrative"].endswith("02")
    assert request["on_unmapped"] == "keep_motion" and request["activate"] is True and request["expected_revision"] == 12 and "actor" not in request
    assert list(request["source_revisions"].values()) == [7], "only the sources actually used, with the revision read in the comparison"
    assert set(out["bad"]) == {"base", "art_direction"} and out["long"] == ["rationale"] and out["same"] is True
    assert out["rows"][0] == {"code": "score_scene_missing", "dimension": "motion", "dimensionLabel": "Mouvement", "message": "m x", "fix": "faites ceci"} and len(out["rows"]) == 2
    assert out["sum"]["lines"] == ["2 scènes", "5 éléments de partition"] and out["sum"]["warnings"] == ["attention"]
    assert [p["inherited"] for p in out["sum"]["provenance"]] == [True, False] and out["sug"] == "Composition sur A"
