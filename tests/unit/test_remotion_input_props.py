"""Les `inputProps` d'une scène Remotion : construites et validées AVANT de traverser vers le bac à sable (Slice 13).

Le même tableau de cas (`tests/fixtures/remotion_input_props_cases.json`) est joué par Python (`build_input_props`, côté Core) et par
JavaScript (`control_center_remotion_props.js`, la page de scène) : mêmes décisions, mêmes `inputProps`. Les valeurs que seul JavaScript
peut porter (fonction, accesseur, prototype, symbole) ont leurs propres épreuves. Contrat : `docs/remotion-isolation.md` § 12.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.remotion_controls import build_input_props

FIXTURE = Path(__file__).parents[1] / "fixtures" / "remotion_input_props_cases.json"
MODULE = Path(__file__).parents[2] / "jarvis" / "runtime" / "control_center_remotion_props.js"
TABLE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CONTRACTS, CASES = TABLE["contracts"], TABLE["cases"]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def inputs_of(case: dict) -> tuple[object, object]:
    props = json.loads(case["props_json"]) if "props_json" in case else case.get("props", {})
    data = json.loads(case["data_json"]) if "data_json" in case else case.get("data", {})
    return props, data


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_python_builds_or_refuses_each_case(case):
    props, data = inputs_of(case)
    result = build_input_props(CONTRACTS[case["contract"]], props, data)
    assert result.ok is case["ok"], result.problems
    if case["ok"]:
        assert result.input_props == case["inputProps"]
        assert list(result.dropped) == case.get("dropped", [])
    else:
        assert result.input_props == {} and result.problems, "a refusal names what is wrong and sends nothing"


def run_node(script: str) -> object:
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_javascript_takes_the_same_decisions_on_the_same_table():
    script = f"""
      const B=require({json.dumps(str(MODULE))});const T=JSON.parse(require('fs').readFileSync({json.dumps(str(FIXTURE))},'utf8'));
      const out=T.cases.map(c=>{{
        const props=c.props_json!==undefined?JSON.parse(c.props_json):(c.props!==undefined?c.props:{{}});
        const data=c.data_json!==undefined?JSON.parse(c.data_json):(c.data!==undefined?c.data:{{}});
        const r=B.buildInputProps(T.contracts[c.contract],props,data);
        return {{name:c.name,ok:r.ok,inputProps:r.inputProps,dropped:r.dropped,problems:r.problems.length}};
      }});
      process.stdout.write(JSON.stringify(out));
    """
    for case, got in zip(CASES, run_node(script), strict=True):
        assert got["ok"] is case["ok"], (case["name"], got)
        if case["ok"]:
            assert got["inputProps"] == case["inputProps"], case["name"]
            assert got["dropped"] == case.get("dropped", []), case["name"]
        else:
            assert got["inputProps"] == {} and got["problems"] >= 1, case["name"]


@needs_node
def test_javascript_refuses_what_only_javascript_can_carry():
    script = f"""
      const B=require({json.dumps(str(MODULE))});
      const contract=JSON.parse(require('fs').readFileSync({json.dumps(str(FIXTURE))},'utf8')).contracts.main;
      const getter={{}};Object.defineProperty(getter,'title',{{get(){{return 'x'}},enumerable:true}});
      const inherited=Object.create({{accent:'#ff0000'}});
      class Klass{{constructor(){{this.title='x'}}}}
      const polluted=JSON.parse('{{"__proto__":{{"polluted":true}}}}');
      const sparse=[];sparse[2]={{label:'a'}};
      const cases={{
        fn:{{title:()=>1}}, symbol:{{title:Symbol('x')}}, undef:{{title:undefined}}, big:{{gap:10n}}, nan:{{stagger:NaN}},
        inf:{{stagger:Infinity}}, getter, inherited, klass:new Klass(), date:{{title:new Date()}}, sparse:{{items:sparse}},
        polluted, map:{{title:new Map()}}, arrayAsProps:[],
      }};
      const out={{}};
      for(const [name,value] of Object.entries(cases)){{const r=B.buildInputProps(contract,value,{{}});out[name]={{ok:r.ok,sent:Object.keys(r.inputProps).length}}}}
      out.polluted_global={{}}.polluted===undefined;
      process.stdout.write(JSON.stringify(out));
    """
    got = run_node(script)
    assert got.pop("polluted_global") is True, "the builder never touches Object.prototype"
    assert all(value == {"ok": False, "sent": 0} for value in got.values()), got  # incl. an object with a borrowed prototype


@needs_node
def test_a_contract_that_is_missing_sends_nothing():
    script = f"""const B=require({json.dumps(str(MODULE))});
      process.stdout.write(JSON.stringify([B.buildInputProps(undefined,{{}},{{}}),B.buildInputProps({{props:{{}},data:{{}}}},{{}},{{}})]))"""
    for result in run_node(script):
        assert result["ok"] is False and result["inputProps"] == {} and result["problems"], "fail closed: no contract, no inputProps"


# ------------------------------------------------------------------ the page's budget IS the sandbox's budget

def _nest(depth: int):
    value: object = 1
    for _ in range(depth):
        value = {"a": value}
    return value


BUDGET_VALUES = [
    {}, _nest(7), _nest(8), _nest(9), {"data": _nest(7)}, {"data": _nest(8)}, [0] * 1999, [0] * 2000, {"a": [0] * 1998}, {"a": [0] * 1999},
    {"s": "x" * 65000}, {"s": "x" * 65600}, {"s": "\U0001F600" * 32000}, {"s": "\U0001F600" * 33000}, {"k" * 200: 1}, {"k" * 201: 1},
    {"a": [1.5] * 1000, "b": [True] * 500, "c": [None] * 400}, {"__proto__": 1}, {"n": 10**400}, {"s": "\ud800"},
]


def test_python_budget_matches_the_sandbox_jsonbudget_on_boundary_values(tmp_path):
    from jarvis.domain.remotion_controls import sandbox_budget
    script = f"""const S=require({json.dumps(str(MODULE.parent / "remotion_sandbox_protocol.js"))});
      const values=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));
      process.stdout.write(JSON.stringify(values.map(v=>S.jsonBudget(v,S.LIMITS.maxPropsBytes))))"""
    shippable = [v for v in BUDGET_VALUES if not (isinstance(v, dict) and v.get("n") == 10**400)]   # not representable in JSON for node
    (tmp_path / "values.json").write_text(json.dumps(shippable), encoding="utf-8")
    done = subprocess.run(["node", "-e", script, str(tmp_path / "values.json")], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    expected = json.loads(done.stdout)
    got = [sandbox_budget(v) for v in shippable]
    assert got == expected, [(i, g, e) for i, (g, e) in enumerate(zip(got, expected, strict=True)) if g != e]
    assert True in got and False in got, "the values straddle the limits"
