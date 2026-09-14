from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import ControlCenter


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_catalog.js"
HTML = ROOT / "jarvis" / "runtime" / "control_center.html"
FIXTURE = (
    ROOT
    / "tasks"
    / "jarvis-settings-model-catalog-ux"
    / "slices"
    / "04-shared-catalog-table"
    / "fixtures"
    / "catalog-states.json"
)


def node_result(tmp_path: Path, expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    runner = tmp_path / "catalog-test.js"
    runner.write_text(
        "const C=require(process.argv[2]);"
        "const fs=require('fs');"
        "const F=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));"
        f"const result=(()=>{{{expression}}})();"
        "process.stdout.write(JSON.stringify(result));",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(runner), str(MODULE), str(FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def node_async_result(tmp_path: Path, expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    runner = tmp_path / "catalog-async-test.js"
    runner.write_text(
        "const C=require(process.argv[2]);"
        "const fs=require('fs');"
        "const F=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));"
        f"(async()=>{{const result=await(async()=>{{{expression}}})();"
        "process.stdout.write(JSON.stringify(result));})()"
        ".catch(error=>{console.error(error&&error.stack||error);process.exitCode=1});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(runner), str(MODULE), str(FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


FAKE_DOM = r"""
class FakeTarget {
  constructor(kind){this.kind=kind;this.dataset={};this.value='';this.checked=false;this.selectionStart=0;this.selectionEnd=0}
  matches(selector){return ({search:'[data-catalog-search]',sort:'[data-catalog-sort]',filter:'[data-catalog-filter]',compare:'[data-catalog-compare]'})[this.kind]===selector}
  closest(selector){return this.kind==='action'&&selector==='[data-catalog-action]'?this:null}
}
class FakeRegion {constructor(){this.innerHTML='';this.textContent=''}}
class FakeContainer {
  constructor(){this.listeners=new Map();this.replacements=0;this._innerHTML='';this.search=null;this.summary=null;this.results=null;this.events=[]}
  set innerHTML(value){
    this.replacements+=1;this._innerHTML=String(value);
    if(this._innerHTML.includes('data-catalog-search')){this.search=new FakeTarget('search')}
    else this.search=null;
    this.summary=this._innerHTML.includes('data-catalog-summary')?new FakeRegion():null;
    this.results=this._innerHTML.includes('data-catalog-results')?new FakeRegion():null;
  }
  get innerHTML(){return this._innerHTML}
  addEventListener(type,handler){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(handler)}
  removeEventListener(type,handler){if(this.listeners.has(type))this.listeners.get(type).delete(handler)}
  listenerCount(type){return this.listeners.has(type)?this.listeners.get(type).size:0}
  querySelector(selector){if(selector==='[data-catalog-summary]')return this.summary;if(selector==='[data-catalog-results]')return this.results;if(selector==='[data-catalog-search]')return this.search;return null}
  emit(type,target){for(const handler of this.listeners.get(type)||[])handler({target})}
  dispatchEvent(event){this.events.push(event);return true}
}
const response=payload=>({ok:true,status:200,json:async()=>payload});
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
"""


def test_real_module_searches_and_combines_multi_filters(tmp_path: Path):
    result = node_result(
        tmp_path,
        """
        const filtered=C.filterItems(F.items,'travaux',{providers:['anthropic'],capabilities:['code','audio']});
        const alternatives=C.filterItems(F.items,'',{providers:['anthropic','openai'],tags:['fast','premium']});
        return {filtered:filtered.map(x=>x.key),alternatives:alternatives.map(x=>x.key),original:F.items.length};
        """,
    )

    assert result == {
        "filtered": ["catalog_v1_expensive"],
        "alternatives": ["catalog_v1_expensive", "catalog_v1_cheap"],
        "original": 6,
    }


def test_real_module_sorts_known_prices_and_keeps_unknown_last(tmp_path: Path):
    result = node_result(
        tmp_path,
        """
        return {
          asc:C.sortItems(F.items,'price-asc').map(x=>x.key),
          desc:C.sortItems(F.items,'price-desc').map(x=>x.key)
        };
        """,
    )

    assert result["asc"][:2] == ["catalog_v1_cheap", "catalog_v1_expensive"]
    assert result["desc"][:2] == ["catalog_v1_expensive", "catalog_v1_cheap"]
    assert set(result["asc"][2:]) == set(result["desc"][2:]) == {
        "catalog_v1_unverified",
        "catalog_v1_not_configured",
        "catalog_v1_unavailable",
        "catalog_v1_unknown",
    }


def test_real_module_trusts_backend_selectability_for_comparison(tmp_path: Path):
    result = node_result(
        tmp_path,
        """
        let selected=C.toggleComparison(F.items,new Set(),'catalog_v1_unavailable',2);
        selected=C.toggleComparison(F.items,selected,'catalog_v1_expensive',2);
        selected=C.toggleComparison(F.items,selected,'catalog_v1_cheap',2);
        selected=C.toggleComparison(F.items,selected,'catalog_v1_unknown',2);
        return {selected:[...selected],allowed:F.items.map(x=>[x.key,C.compareAllowed(x)])};
        """,
    )

    assert result["selected"] == ["catalog_v1_expensive", "catalog_v1_cheap"]
    assert dict(result["allowed"])["catalog_v1_unavailable"] is False
    assert dict(result["allowed"])["catalog_v1_unknown"] is False


def test_real_module_renders_status_provenance_backend_actions_and_escapes(tmp_path: Path):
    result = node_result(
        tmp_path,
        """
        const html=C.renderCatalog(F,{columns:['compare','model','price','availability','actions']});
        return {html,actions:C.backendActions(F.items[1]),fake:C.backendActions(F.items[0])};
        """,
    )

    html = result["html"]
    assert "Retired &lt;unsafe&gt;" in html and "Retired <unsafe>" not in html
    assert "Vérifié maintenant" in html and "provider:anthropic · live · ok" in html
    assert 'data-catalog-action="inspect"' in html
    assert result["actions"] == [{"id": "inspect", "label": "Inspecter", "enabled": True}]
    assert result["fake"] == []
    assert 'data-catalog-compare="catalog_v1_unavailable"' in html
    unavailable_checkbox = re.search(r'<input[^>]+data-catalog-compare="catalog_v1_unavailable"[^>]+>', html)
    assert unavailable_checkbox and " disabled" in unavailable_checkbox.group(0)
    assert '<th scope="row"' in html


def test_real_module_projects_loading_error_credentials_partial_and_empty_states(tmp_path: Path):
    result = node_result(
        tmp_path,
        """
        const noKey={...F,items:F.items.filter(x=>x.availability.state!=='usable'),sources:[{status_code:'catalog_no_key'}]};
        return {
          loading:C.uiState(null,{loading:true}).kind,
          error:C.uiState(null,{error:'offline'}).kind,
          noKey:C.uiState(noKey,{}).kind,
          partial:C.uiState(F,{}).kind,
          empty:C.uiState({...F,items:[]},{}).kind,
          url:C.catalogUrl('voice','realtime',true)
        };
        """,
    )

    assert result == {
        "loading": "loading",
        "error": "error",
        "noKey": "no_credentials",
        "partial": "partial",
        "empty": "empty",
        "url": "/api/catalog?surface=voice&role=realtime&refresh=true",
    }


def test_role_specific_columns_reuse_the_same_renderer(tmp_path: Path):
    result = node_result(
        tmp_path,
        """
        const html=C.renderCatalog({...F,surface:'voice',role:'realtime'},{columns:['model','roles','availability']});
        return {html,headers:(html.match(/<th scope="col">/g)||[]).length};
        """,
    )

    assert result["headers"] == 3
    assert 'data-catalog-surface="voice"' in result["html"]
    assert 'class="catalog-cell-roles"' in result["html"]
    assert 'class="catalog-cell-price"' not in result["html"]
    assert 'class="catalog-cell-actions"' not in result["html"]


def test_controller_keeps_live_search_node_focus_and_caret_while_typing(tmp_path: Path):
    result = node_async_result(
        tmp_path,
        FAKE_DOM
        + r"""
        const container=new FakeContainer();
        const controller=C.createCatalogTable(container,{surface:'subagents',fetcher:async()=>response(F)});
        await controller.load();
        const search=container.search,replacements=container.replacements;
        search.value='cheap';search.selectionStart=2;search.selectionEnd=4;
        container.emit('input',search);
        return {
          sameNode:search===container.search,replacementsBefore:replacements,replacementsAfter:container.replacements,
          start:search.selectionStart,end:search.selectionEnd,query:controller.state.query,
          results:container.results.innerHTML,summary:container.summary.textContent
        };
        """,
    )

    assert result["sameNode"] is True
    assert result["replacementsAfter"] == result["replacementsBefore"]
    assert (result["start"], result["end"], result["query"]) == (2, 4, "cheap")
    assert "Cheap" in result["results"] and "Expensive" not in result["results"]
    assert result["summary"].startswith("1 / 6")


def test_controller_is_last_request_wins_for_old_results_and_errors(tmp_path: Path):
    result = node_async_result(
        tmp_path,
        FAKE_DOM
        + r"""
        const container=new FakeContainer(),calls=[];
        const fetcher=(url,options)=>{const pending=deferred();calls.push({pending,options,url});return pending.promise};
        const controller=C.createCatalogTable(container,{surface:'subagents',fetcher});
        const oldLoad=controller.load(),newLoad=controller.refresh();
        const newest={...F,items:[{...F.items[0],label:'NEW result'}]};
        calls[1].pending.resolve(response(newest));await newLoad;
        const old={...F,items:[{...F.items[0],label:'OLD result'}]};
        calls[0].pending.resolve(response(old));await oldLoad;
        const errorLoad=controller.load(),winnerLoad=controller.refresh();
        const winner={...F,items:[{...F.items[0],label:'LATEST result'}]};
        calls[3].pending.resolve(response(winner));await winnerLoad;
        calls[2].pending.reject(new Error('OLD error'));await errorLoad;
        return {
          label:controller.state.envelope.items[0].label,error:controller.state.error,
          html:container.innerHTML,firstAborted:calls[0].options.signal.aborted,
          errorAborted:calls[2].options.signal.aborted
        };
        """,
    )

    assert result["label"] == "LATEST result"
    assert result["error"] == ""
    assert "LATEST result" in result["html"]
    assert "OLD result" not in result["html"] and "OLD error" not in result["html"]
    assert result["firstAborted"] is True and result["errorAborted"] is True


def test_destroy_aborts_pending_removes_handlers_and_prevents_resurrection(tmp_path: Path):
    result = node_async_result(
        tmp_path,
        FAKE_DOM
        + r"""
        const container=new FakeContainer(),pending=deferred();let fetches=0,signal=null;
        const controller=C.createCatalogTable(container,{surface:'voice',fetcher:(url,options)=>{fetches+=1;signal=options.signal;return pending.promise}});
        const request=controller.load();
        const before=['input','change','click'].map(type=>container.listenerCount(type));
        controller.destroy();
        const after=['input','change','click'].map(type=>container.listenerCount(type));
        pending.resolve(response(F));await request;
        const afterResolution=container.innerHTML;
        await controller.load();
        const replacement=C.createCatalogTable(container,{surface:'voice',fetcher:async()=>response(F)});
        const recreated=['input','change','click'].map(type=>container.listenerCount(type));
        replacement.destroy();
        return {before,after,recreated,aborted:signal.aborted,afterResolution,fetches,final:['input','change','click'].map(type=>container.listenerCount(type))};
        """,
    )

    assert result == {
        "before": [1, 1, 1],
        "after": [0, 0, 0],
        "recreated": [1, 1, 1],
        "aborted": True,
        "afterResolution": "",
        "fetches": 1,
        "final": [0, 0, 0],
    }


def test_controller_contains_catalog_load_failure_in_its_own_surface(tmp_path: Path):
    result = node_async_result(
        tmp_path,
        FAKE_DOM
        + r"""
        const container=new FakeContainer();
        const controller=C.createCatalogTable(container,{surface:'subagents',role:'subagent',fetcher:async()=>{throw new Error('catalog offline')}});
        const returned=await controller.load();
        return {returned,error:controller.state.error,loading:controller.state.loading,html:container.innerHTML};
        """,
    )

    assert result["returned"] is None
    assert result["error"] == "catalog offline"
    assert result["loading"] is False
    assert "catalog offline" in result["html"] and "catalog-notice error" in result["html"]


@pytest.mark.asyncio
async def test_catalog_module_is_injected_in_served_html(tmp_path: Path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    served = (await control.index(None)).text

    assert "/*__CONTROL_CENTER_CATALOG_JS__*/" not in served
    assert "root.JarvisCatalog=api" in served
    assert served.index("root.JarvisCatalog=api") < served.index("const $=s=>document.querySelector(s)")


def test_catalog_module_and_responsive_contract_are_present():
    source = MODULE.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    assert "availability(item).selectable===true" in source
    assert "item&&item.actions" in source
    assert "@media(max-width:700px)" in html
    assert ".catalog-table td::before{content:attr(data-label)" in html
    assert "outline:2px solid var(--accent)" in html


def test_catalog_module_parses_with_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    completed = subprocess.run([node, "--check", str(MODULE)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
