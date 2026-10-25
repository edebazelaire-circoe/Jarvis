"""Fragments de la fondation visuelle des Réglages (`JarvisSettingsUI`, refonte-ui-settings Slice 01), sous node.

Contrat : `docs/settings/visual-foundation.md`. Ce que ce fichier prouve, sans navigateur :

- tout texte est échappé ; un SVG passé en `icon` est inséré tel quel ;
- un contrôle porte toujours un nom (bouton, interrupteur, onglets, tableau, statistique, pastille) ;
- le curseur pose son remplissage et son texte de valeur dès le premier rendu (`format`, ou `decimals` + `suffix`
  repris par `bindRange`) ; la plage vient de l'appelant ;
- les liens d'accessibilité : libellé et aide d'une ligne, compteur d'une zone de texte, onglet sélectionné seul
  focalisable, panneau flottant nommé par son titre et fermé à la création ;
- les CSS des primitives et les jetons `--set-*` sont définis dans la page, une fois.

Se saute si node manque.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "jarvis" / "runtime" / "control_center_settings_ui.js"
HTML = ROOT / "jarvis" / "runtime" / "control_center.html"


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "foundation.cjs"
    script.write_text(f"const UI=require({json.dumps(str(UI))});\nconst out=v=>process.stdout.write(JSON.stringify(v));\n"
                      "const tryIt=f=>{try{return f()}catch(e){return 'ERR:'+e.message}};\n" + body, encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_fragments_escape_text_name_every_control_and_keep_icons(tmp_path):
    out = run(tmp_path, r"""
const svg='<svg viewBox="0 0 24 24"><path d="M1 1"/></svg>';
out({
  panel:UI.panel({id:'p1',title:'A <b>',description:'« d »',icon:svg,tone:'violet',variant:'hot',aside:'<i>x</i>',body:'<p>b</p>'}),
  quiet:UI.panel({title:'Q',variant:'nope',tone:'nope'}),
  stat:UI.stat({value:'98 %',label:'Taux <',icon:svg}),
  row:UI.row({id:'r1',label:'Libellé',hint:'Aide',control:'<b>c</b>',wide:true}),
  dot:UI.dot('nope','Actif'),
  dotHook:UI.dot('ok','Actif',{className:'mem-pill bad"x'}),
  btn:UI.button({id:'b1',label:'Ok & go',variant:'primary',busy:true,data:{act:'save"x'}}),
  iconBtn:UI.button({label:'Fermer',iconOnly:true,icon:svg}),
  toggle:UI.toggle({id:'t1',labelledBy:'r1-label',describedBy:'r1-hint',checked:true,stateText:{on:'Activé',off:'Désactivé'}}),
  select:UI.select({id:'s1',label:'Modèle',value:'b',options:[{value:'a',label:'A'},{value:'b',label:'<B>'}]}),
  textarea:UI.textarea({id:'x1',value:'abc',maxLength:10,describedBy:'h1',placeholder:'Ex. <'}),
  tabs:UI.tabs({id:'tb',label:'Sections',selected:'two',items:[{id:'one',label:'Un'},{id:'two',label:'Deux',controls:'panelTwo'}]}),
  choices:UI.choices({name:'mode',legend:'Mode',value:'auto',items:[{value:'auto',title:'Auto',description:'d'},{value:'man',title:'Manuel',disabled:true}]}),
  table:UI.table({label:'Notes',columns:[{label:'Nom'},{label:'Score',num:true}],body:'<tr><td>a</td><td>1</td></tr>',foot:'f'}),
  float:UI.float({id:'f1',title:'Config',eyebrow:'Configuration',body:'<p>b</p>'}),
  errors:[tryIt(()=>UI.button({})),tryIt(()=>UI.toggle({id:'t'})),tryIt(()=>UI.tabs({items:[]})),tryIt(()=>UI.table({})),
    tryIt(()=>UI.stat({value:1})),tryIt(()=>UI.dot('ok','')),tryIt(()=>UI.row({label:'x'})),tryIt(()=>UI.choices({name:'a b'})),
    tryIt(()=>UI.button({label:'x',data:{'Bad Key':1}})),tryIt(()=>UI.float({title:'x'}))],
});""")
    panel = out["panel"]
    assert panel.startswith('<section class="set-panel set-panel-hot set-tone-violet" id="p1" aria-labelledby="p1-title">')
    assert '<h3 class="set-panel-title" id="p1-title">A &lt;b&gt;</h3>' in panel and '<path d="M1 1"/>' in panel
    assert '<div class="set-panel-aside"><i>x</i></div>' in panel and '<p class="set-panel-desc">« d »</p>' in panel
    assert out["quiet"].startswith('<section class="set-panel">')  # variante et teinte inconnues : ignorées
    assert "Taux &lt;" in out["stat"] and 'class="set-stat-value">98 %<' in out["stat"]
    assert 'id="r1-label"' in out["row"] and 'id="r1-hint"' in out["row"] and "set-row-wide" in out["row"]
    assert out["dot"] == '<span class="set-dot set-dot-info">Actif</span>'
    # Classe d'accroche optionnelle (reprise QA S07) : seuls les noms de classe sûrs passent.
    assert out["dotHook"] == '<span class="mem-pill set-dot set-dot-ok">Actif</span>'
    btn = out["btn"]
    assert 'aria-busy="true"' in btn and " disabled" in btn and 'data-act="save&quot;x"' in btn and "Ok &amp; go" in btn
    assert 'aria-label="Fermer"' in out["iconBtn"] and "set-btn-icon" in out["iconBtn"] and "<span>" not in out["iconBtn"]
    toggle = out["toggle"]
    assert 'role="switch"' in toggle and 'aria-checked="true"' in toggle and 'aria-labelledby="r1-label"' in toggle
    assert 'aria-describedby="r1-hint"' in toggle and ">Activé<" in toggle
    assert '<option value="b" selected>&lt;B&gt;</option>' in out["select"] and 'aria-label="Modèle"' in out["select"]
    textarea = out["textarea"]
    assert 'aria-describedby="h1 x1-count"' in textarea and 'maxlength="10"' in textarea and ">3/10<" in textarea
    tabs = out["tabs"]
    assert 'role="tablist" aria-label="Sections"' in tabs
    assert 'id="tb-two" data-set-tab="two" aria-selected="true" tabindex="0" aria-controls="panelTwo"' in tabs
    assert 'id="tb-one" data-set-tab="one" aria-selected="false" tabindex="-1"' in tabs
    assert 'value="auto" checked' in out["choices"] and 'value="man" disabled' in out["choices"] and "<legend" in out["choices"]
    assert 'role="region" tabindex="0" aria-label="Notes"' in out["table"] and '<th scope="col" class="set-num">Score</th>' in out["table"]
    assert 'role="dialog" aria-labelledby="f1-title" hidden' in out["float"] and "data-set-float-close" in out["float"]
    assert all(e.startswith("ERR:") for e in out["errors"]), out["errors"]


def test_range_renders_fill_and_value_text_from_the_first_paint(tmp_path):
    out = run(tmp_path, r"""
out({
  pct:UI.range({id:'v',min:0,max:100,step:5,value:80,suffix:' %',label:'Volume'}),
  rate:UI.range({id:'r',min:0.5,max:2,step:0.1,value:1,decimals:1,suffix:'x',label:'Débit',minLabel:'Lent',maxLabel:'Rapide'}),
  fn:UI.range({id:'f',min:0,max:10,value:7,format:v=>'niveau '+v,label:'Ton'}),
  inline:UI.range({id:'i',min:0,max:10,value:3,minLabel:'Min <',maxLabel:'Max',inlineEnds:true,showValue:false,labelledBy:'lab'}),
  clamp:UI.range({id:'c',min:0,max:10,value:42,label:'x'}),
  broken:UI.range({id:'b',min:5,max:5,value:5,label:'x'}),
});""")
    assert 'style="--set-range-fill:80%"' in out["pct"] and 'aria-valuetext="80 %"' in out["pct"] and ">80 %</output>" in out["pct"]
    assert 'data-set-decimals="1" data-set-suffix="x"' in out["rate"] and ">1.0x</output>" in out["rate"]
    assert 'style="--set-range-fill:33.3%"' in out["rate"] and "<span>Lent</span><span>Rapide</span>" in out["rate"]
    assert ">niveau 7</output>" in out["fn"]
    assert "set-range-inline" in out["inline"] and "<output" not in out["inline"] and "Min &lt;" in out["inline"]
    assert 'aria-labelledby="lab"' in out["inline"]
    assert "--set-range-fill:100%" in out["clamp"] and "--set-range-fill:0%" in out["broken"]


def test_foundation_tokens_and_primitive_styles_live_once_in_the_page():
    page = HTML.read_text(encoding="utf-8")
    style = page[page.index("<style>"):page.index("</style>")]
    roots = re.findall(r":root\{([^}]*)\}", style)
    defined = [name for body in roots for name in re.findall(r"(--set-[a-z0-9-]+):", body)]
    assert len(defined) == len(set(defined)), "jeton --set-* défini deux fois sur :root"
    for token in ("--set-glass", "--set-edge", "--set-accent", "--set-accent-2", "--set-r-xl", "--set-sp-4", "--set-gap",
                  "--set-fs-display", "--set-ink-3", "--set-ok", "--set-z-float", "--set-focus", "--set-disabled"):
        assert token in defined, token
    # Les jetons d'encre et de filet ne se redéfinissent plus sur le shell.
    shell = re.search(r"\.settings-shell\{([^}]*)\}", style).group(1)
    assert not re.search(r"--set-(ink|hair|font|mono|field-bg)[a-z0-9-]*:", shell), shell
    for cls in (".set-panel{", ".set-medallion{", ".set-stat{", ".set-row{", ".set-dot{", ".set-btn{", ".set-select{",
                ".set-range{", ".set-switch{", ".set-textarea{", ".set-tabs{", ".set-tab{", ".set-seg{", ".set-choice{",
                ".set-table-shell{", ".set-float{", ".set-grid{", ".set-grid-auto{", ".set-workbench{", ".set-view{"):
        assert style.count("\n" + cls) == 1, cls  # une seule règle de base, en début de ligne
