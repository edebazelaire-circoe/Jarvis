"""Dossier plein écran, logique pure exécutée par node (wheel-dossier-refactor, Slice 07).

Contrat : `docs/dossier.md` › *Full-screen Dossier (UI)*. Ce que ce fichier épingle :

- le client n'atteint que les routes du Dossier et des propriétaires (liste, entrée, Afficher sur le Board,
  lecture / recherche / écriture / déplacement / suppression de la mémoire, un Artifact) ; tout le reste est
  refusé avant le réseau ;
- l'organisation (collections, arbre des dossiers) vient des seules entrées ; le filtre ignore les accents ;
- le Markdown devient des **données** (jamais du HTML) ; le commentaire machine de Ranger quitte la lecture ;
- onglets : un document n'est ouvert qu'une fois, le plus ancien non modifié part au-delà de la borne ;
  deux ouvertures de Jarvis rapprochées se posent côte à côte ; le côte à côte retombe en onglets en format étroit ;
- issues d'écriture : enregistré, conflit, inconnu, refusé — jamais un succès supposé ;
- capacités : Board archivé, Board non affiché, Core perdu, lecture dans Variantes disent pourquoi ;
- l'ordre de Jarvis est refusé avec un code stable (`board_not_displayed`, `dossier_unavailable`) ;
- une bascule de Board relie un Dossier qui suit le Board affiché, jamais un Dossier ouvert sur un Board précis ;
- le module est inséré dans la page servie après la roue, et `refreshStatus` le nourrit.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    DOSSIER_CORE_SCRIPT_FILE,
    DOSSIER_CORE_SCRIPT_MARKER,
    DOSSIER_SCRIPT_MARKER,
    TOOL_WHEEL_SCRIPT_MARKER,
)

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
MODULE = RUNTIME / DOSSIER_CORE_SCRIPT_FILE


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "probe.js"
    script.write_text(f"const C=require({json.dumps(str(MODULE))});\nconst out=(()=>{{{body}}})();\n"
                      "Promise.resolve(out).then(v=>process.stdout.write(JSON.stringify(v)));", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_client_reaches_only_the_dossier_and_its_owners(tmp_path):
    r = run(tmp_path, r"""
      const ok=[['GET','/api/workspace/boards/b1/dossier?limit=100'],['GET','/api/workspace/boards/b1/dossier/entry?id=memory%3Aa.md'],
        ['POST','/api/workspace/boards/b1/dossier/present'],['GET','/api/workspace/boards/b1/memory/read?path=a.md'],
        ['GET','/api/workspace/boards/b1/memory/search?q=x'],['POST','/api/workspace/boards/b1/memory/write'],
        ['POST','/api/workspace/boards/b1/memory/move'],['POST','/api/workspace/boards/b1/memory/delete'],
        ['GET','/api/artifacts/jart_x?text_chars=20000']];
      const no=[['POST','/api/workspace/boards/b1/dossier/ranger'],['POST','/api/workspace/boards/b1/memory/mkdir'],
        ['DELETE','/api/artifacts/jart_x'],['GET','/api/boards'],['GET','//evil/api/artifacts/x'],
        ['GET','/api/workspace/boards/%2e%2e/dossier'],['POST','/api/workspace/boards/b1/memory/write?x=1'],
        ['GET','/api/artifacts/jart_x/payload'],['POST','/api/scene/commands']];
      return {ok:ok.map(([m,p])=>C.allowed(m,p)),no:no.map(([m,p])=>C.allowed(m,p))};
    """)
    assert all(r["ok"]) and not any(r["no"]), r


def test_the_client_names_refusals_timeouts_and_network_failures(tmp_path):
    r = run(tmp_path, r"""
      const reply=(status,body)=>async()=>({status,json:async()=>body});
      const mk=f=>C.createClient({fetchImpl:f});
      return Promise.all([
        mk(reply(409,{error:{code:'memory_conflict',message:'sha'}})).post('/api/workspace/boards/b/memory/write',{}),
        mk(async()=>{throw new TypeError('Failed to fetch')}).get('/api/workspace/boards/b/dossier'),
        mk((p,init)=>new Promise((_,ko)=>init.signal.addEventListener('abort',()=>ko(new Error('aborted'))))).get('/api/workspace/boards/b/dossier',30),
        mk(reply(200,{entries:[]})).get('/api/workspace/boards/b/dossier'),
        mk(reply(200,{})).get('/api/boards'),
      ]).then(([conflict,net,slow,good,forbidden])=>({conflict:C.writeOutcome(conflict).kind,net:net.error.code,
        slow:slow.error.code,slowOutcome:C.writeOutcome(slow).kind,good:good.ok,forbidden:forbidden.error.code,
        unknown:C.errorOf('weird_code',418,'détail').title}));
    """)
    assert r == {"conflict": "conflict", "net": "network", "slow": "timeout", "slowOutcome": "unknown", "good": True,
                 "forbidden": "forbidden_route", "unknown": "Refus du serveur (weird_code, HTTP 418)"}


def test_organization_comes_from_the_entries_and_the_filter_ignores_accents(tmp_path):
    r = run(tmp_path, r"""
      const e=[{entry_id:'memory:summary.md',source:'memory',kind:'memory_summary',title:'Résumé du Board',folder:''},
        {entry_id:'memory:notes/a.md',source:'memory',kind:'note',title:'Décision budget',folder:'notes'},
        {entry_id:'memory:notes/2026/b.md',source:'memory',kind:'note',title:'Bilan',folder:'notes/2026'},
        {entry_id:'artifact:jart_1',source:'artifact',kind:'image',title:'Schéma',preview:'schema.png'}];
      const o=C.organize(e);
      return {collections:o.collections.map(c=>[c.id,c.ids.length]),folders:o.folders.map(f=>[f.path,f.count,f.folders.map(x=>x.path)]),
        filtered:C.filterEntries(e,'decision').map(x=>x.title),both:C.filterEntries(e,'bilan 2026').map(x=>x.title),
        folder:C.entriesOfSection(e,'f:notes').length,media:C.entriesOfSection(e,'c:media').length};
    """)
    assert r["collections"] == [["syntheses", 1], ["notes", 2], ["media", 1]]
    assert r["folders"] == [["notes", 2, ["notes/2026"]]]
    assert r["filtered"] == ["Décision budget"] and r["both"] == ["Bilan"]
    assert r["folder"] == 2 and r["media"] == 1


def test_markdown_is_data_and_the_ranger_comment_leaves_the_reading(tmp_path):
    r = run(tmp_path, r"""
      const md='# Titre\n\nUn **gras** et `code` <script>x</script>\n\n- un\n- deux\n\n1. a\n\n> cité\n\n```\nbrut <b>\n```\n---\nRangé.\n<!-- jarvis:dossier object_id=o1 kind=artifact -->\n';
      const {blocks,meta}=C.markdownBlocks(md);
      const lead=C.leadHeading(blocks);
      return {kinds:blocks.map(b=>b.t),meta,para:blocks[1].inline,link:C.inline('voir [ici](https://x.fr/a) et https://y.fr'),
        heading:lead.heading,rest:lead.blocks.length,none:C.leadHeading(C.markdownBlocks('texte').blocks).heading};
    """)
    assert r["kinds"] == ["h", "p", "ul", "ol", "quote", "code", "hr", "p"]
    assert r["meta"] == ["object_id=o1 kind=artifact"]
    assert {"t": "text", "v": " <script>x</script>"} in r["para"], "author HTML stays text, never markup"
    assert r["link"][1] == {"t": "link", "v": "ici", "href": "https://x.fr/a"} and r["link"][3]["href"] == "https://y.fr"
    assert r["heading"] == "Titre" and r["rest"] == len(r["kinds"]) - 1 and r["none"] is None, "the # heading becomes the title"


def test_tabs_open_once_drop_the_oldest_and_pair_jarvis_openings(tmp_path):
    r = run(tmp_path, r"""
      let s={tabs:[],active:null};
      for(let i=0;i<C.MAX_TABS;i+=1){s=C.openTab(s.tabs,'memory:'+i+'.md',{at:i,active:s.active})}
      const again=C.openTab(s.tabs,'memory:3.md',{at:50,active:s.active});
      const over=C.openTab(again.tabs,'memory:new.md',{at:60,active:again.active});
      const closed=C.closeTab(over.tabs,'memory:new.md','memory:new.md');
      const j=C.openTab([],'memory:a.md',{opener:'jarvis',at:1000});
      const j2=C.openTab(j.tabs,'memory:b.md',{opener:'jarvis',at:5000});
      return {count:again.tabs.length,dropped:over.dropped,len:over.tabs.length,next:closed.active,
        pair:C.pairFor(j2.tabs,'memory:b.md',5000),late:C.pairFor(j2.tabs,'memory:b.md',1000+C.PAIR_WINDOW_MS+10),
        wide:C.layoutFor(1440,{ctxOpen:false}).split,wideCtx:C.layoutFor(1440,{ctxOpen:true}).split,
        narrow:C.layoutFor(600,{}),big:C.layoutFor(1920,{ctxOpen:true}).split};
    """)
    assert r["count"] == 8 and r["dropped"] == "memory:0.md" and r["len"] == 8
    assert r["next"] is not None
    assert r["pair"] == ["memory:a.md", "memory:b.md"] and r["late"] is None
    assert r["wide"] is True and r["wideCtx"] is False and r["big"] is True, "an open context pane at 1440 leaves too little for two"
    assert r["narrow"]["narrow"] is True and r["narrow"]["split"] is False and r["narrow"]["orgDrawer"] is True


def test_capabilities_say_why_an_action_is_off(tmp_path):
    r = run(tmp_path, r"""
      const note={entry_id:'memory:a.md',source:'memory',open:'text',size:10};
      const art={entry_id:'artifact:jart_1',source:'artifact',open:'text'};
      const active={board_id:'b1',status:'active',writable:true};
      const arch={board_id:'b0',status:'archived',writable:false};
      const c=(e,o)=>C.capabilities(e,Object.assign({board:active,displayedBoardId:'b1',running:false,coreLost:false},o));
      return {ok:c(note,{}),art:c(art,{}).edit,arch:c(note,{board:arch,displayedBoardId:'b1'}),other:c(note,{displayedBoardId:'b2'}).present,
        lost:c(note,{coreLost:true}).edit,run:c(note,{running:true}).delete,big:c(Object.assign({},note,{size:300000}),{}).edit};
    """)
    assert all(v["ok"] for v in r["ok"].values())
    assert not r["art"]["ok"] and "registre" in r["art"]["reason"]
    assert not r["arch"]["present"]["ok"] and "archivé" in r["arch"]["edit"]["reason"]
    assert not r["other"]["ok"] and "Board affiché" in r["other"]["reason"]
    assert "Core ne répond pas" in r["lost"]["reason"] and "Variantes" in r["run"]["reason"]
    assert "256 Kio" in r["big"]["reason"]


def test_jarvis_orders_are_refused_with_stable_codes_and_switches_rebind_only_a_following_dossier(tmp_path):
    r = run(tmp_path, r"""
      const cmd={action:'open_entry',board_id:'b1',entry_id:'memory:a.md'};
      return {ok:C.openDecision(cmd,{displayedBoardId:'b1',covered:null}),other:C.openDecision(cmd,{displayedBoardId:'b2'}).code,
        lost:C.openDecision(cmd,{displayedBoardId:null}).code,covered:C.openDecision(cmd,{displayedBoardId:'b1',covered:'Variantes'}).code,
        bad:C.openDecision({action:'nope'},{displayedBoardId:'b1'}).code,
        follow:C.rebindOnSwitch({follow:true,boardId:'b1',displayedBoardId:'b2'}),
        pinned:C.rebindOnSwitch({follow:false,boardId:'b0',displayedBoardId:'b2'}),
        same:C.rebindOnSwitch({follow:true,boardId:'b1',displayedBoardId:'b1'}),
        wheel:C.wheelItems({board:{title:'Atlas'},recent:[{entry_id:'memory:a.md',title:'A',kind:'note'}]}).map(i=>i.id),
        wheelLost:C.wheelItems({board:null,coreLost:true})[0].disabled};
    """)
    assert r["ok"] == {"ok": True} and r["other"] == "board_not_displayed"
    assert r["lost"] == r["covered"] == r["bad"] == "dossier_unavailable"
    assert (r["follow"], r["pinned"], r["same"]) == ("rebind", "keep", "keep")
    assert r["wheel"] == ["open", "entry:memory:a.md"] and r["wheelLost"] is True


def test_the_served_page_inserts_the_dossier_after_the_wheel_and_feeds_it_from_the_status():
    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    assert html.index(TOOL_WHEEL_SCRIPT_MARKER) < html.index(DOSSIER_CORE_SCRIPT_MARKER) < html.index(DOSSIER_SCRIPT_MARKER)
    assert "JarvisDossier.gate(s.boards,s.dossier_navigation)" in html and "JarvisDossier.statusLost()" in html
    assert 'id="dossierView"' in html
    view = (RUNTIME / "control_center_dossier.js").read_text(encoding="utf-8")
    assert "'__JARVIS_DOSSIER_PAGE_TOKEN__'" in view, "the page token marker lives in the view the broker serves"
    assert "register({id:'dossier'" in view, "the wheel's Dossier category is wired here, not a placeholder"


def test_a_dirty_tab_is_never_evicted_and_a_full_dirty_set_refuses(tmp_path):
    """QA S07, B2 : l'éviction saute les onglets modifiés ; tous modifiés = refus `full`, onglets inchangés."""

    r = run(tmp_path, r"""
      const tabs=[];for(let i=0;i<C.MAX_TABS;i+=1)tabs.push({entryId:'memory:'+i+'.md',opener:'user',openedAt:i,dirty:i===0});
      const one=C.openTab(tabs,'memory:new.md',{at:99});
      const all=tabs.map(t=>Object.assign({},t,{dirty:true}));
      const full=C.openTab(all,'memory:new.md',{at:99,active:'memory:3.md'});
      return {dropped:one.dropped,full:full.full,len:full.tabs.length,active:full.active,
        guardBoard:C.editGuard({dirtyCount:1,boardId:'a',targetBoardId:'b'}),guardSame:C.editGuard({dirtyCount:1,boardId:'a',targetBoardId:'a'}),
        guardFull:C.editGuard({dirtyCount:8,tabsFull:true}).code,clean:C.editGuard({dirtyCount:0,boardId:'a',targetBoardId:'b'}).ok};
    """)
    assert r["dropped"] == "memory:1.md", "the oldest *unmodified* tab leaves"
    assert r["full"] is True and r["len"] == 8 and r["active"] == "memory:3.md"
    assert r["guardBoard"]["code"] == "edit_in_progress" and r["guardSame"]["ok"] is True
    assert r["guardFull"] == "edit_in_progress" and r["clean"] is True


def test_only_an_absolute_http_link_becomes_a_href(tmp_path):
    """QA S07 3 (Slice 08) : défense en profondeur ; `check_link_url` vérifie déjà en amont."""
    r = run(tmp_path, r"""
      const u=['https://intranet.exemple/budget','http://exemple.fr/a?b=1','javascript:alert(1)','JAVASCRIPT:alert(1)',
        'data:text/html,<b>x</b>','file:///C:/x','/relatif','  https://exemple.fr  ','https://a b','', null,'x'.repeat(3000)];
      return u.map(v=>C.safeLinkUrl(v));
    """)
    assert r[:2] == ["https://intranet.exemple/budget", "http://exemple.fr/a?b=1"]
    assert r[2:7] == [None] * 5
    assert r[7] == "https://exemple.fr/" and r[8:] == [None] * 4
