"""Écran des réglages mémoire (Slice 11) : le module servi, exécuté par node sur la vraie section serveur."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.memory_relay import memory_settings_section

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_memory_settings.js"
HTML = ROOT / "jarvis" / "runtime" / "control_center.html"


def run_node(tmp_path: Path, settings: dict, source: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "d.json"
    data.write_text(json.dumps(memory_settings_section(settings, {})), encoding="utf-8")
    script = tmp_path / "t.cjs"
    script.write_text(
        f"const M=require({json.dumps(str(MODULE))}).JarvisMemorySettings||globalThis.JarvisMemorySettings;\n"
        f"const MEM=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));\n"
        "const host={innerHTML:'',setAttribute(){},querySelectorAll(){return[]},querySelector(){return null}};\n"
        "const calls=[];\n"
        "const fetchFn=async(p,i)=>{calls.push([p,i&&i.body]);return {memory:MEM}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout else None


def test_renders_every_server_field_and_never_a_secret(tmp_path):
    settings = {"credentials": {"openai": {"value": "sk-SECRET-123"}}, "memory": {"semantic": {"provider": "openai"}}}
    out = run_node(tmp_path, settings, """
globalThis.window=globalThis;
const v=M.create(host,{fetch:fetchFn});await v.load();
process.stdout.write(JSON.stringify({html:host.innerHTML,paths:MEM.schema.sections.flatMap(s=>s.fields.map(f=>f.path))}));""")
    for path in out["paths"]:
        assert f'data-mem="{path}"' in out["html"], path
    assert "SECRET" not in out["html"] and "sk-" not in out["html"]
    assert "Memory Center" in out["html"] and "API Keys" in out["html"]


def test_dependent_toggles_are_blocked_and_the_patch_is_minimal(tmp_path):
    out = run_node(tmp_path, {}, """
const v=M.create(host,{fetch:fetchFn});await v.load();
const blocked=/id="mem_semantic_enabled"[^>]*disabled/.test(host.innerHTML);
v.state.draft['recall.max_items']=3;v.state.draft['recall.enabled']=false;
const patch=v.patch();
await v.submit();
process.stdout.write(JSON.stringify({blocked,patch,calls,draft:v.state.draft}));""")
    assert out["blocked"] is True
    assert out["patch"] == {"recall": {"max_items": 3, "enabled": False}}
    assert out["calls"][-1][0] == "/api/settings"
    assert json.loads(out["calls"][-1][1]) == {"memory": out["patch"]}
    assert out["draft"] == {}


def test_a_refusal_is_shown_and_keeps_the_draft(tmp_path):
    out = run_node(tmp_path, {}, """
const bad=async()=>{const e=new Error('semantic.enabled invalide');e.code='memory_settings_semantic_needs_provider';throw e};
const v=M.create(host,{fetch:async(p,i)=>i?bad():{memory:MEM}});await v.load();
v.state.draft['recall.max_items']=2;await v.submit();
process.stdout.write(JSON.stringify({html:host.innerHTML,draft:v.state.draft}));""")
    assert "memory_settings_semantic_needs_provider" in out["html"] and "Rien n" in out["html"]
    assert out["draft"] == {"recall.max_items": 2}


def test_downgraded_state_is_explained(tmp_path):
    out = run_node(tmp_path, {"memory": {"tencent": {"enabled": True}}}, """
const v=M.create(host,{fetch:fetchFn});await v.load();
process.stdout.write(JSON.stringify({html:host.innerHTML}));""")
    assert "coupée" in out["html"] or "coupé" in out["html"]
    assert "memory_settings_tencent_needs_url" in out["html"] or "exige une URL" in out["html"]


def test_the_page_has_the_memory_tab_and_mount():
    html = HTML.read_text(encoding="utf-8")
    assert "id:'memory',label:'Mémoire'" in html and 'id="memorySettingsMount"' in html
