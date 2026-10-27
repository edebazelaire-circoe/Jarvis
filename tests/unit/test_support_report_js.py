"""Logique pure de « Signaler un problème » (node, sans navigateur ; V1.2 Slice 07).

L'aperçu lu est celui que le service Python écrit (`SupportReportService.preview`) : le contrat entre le serveur et la
page est épinglé des deux côtés. Le comportement dans une vraie page : `test_support_report_browser.py`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_support_report import seeded, service

MODULE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_support_report.js"


def node(script: str):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    code = (f"const J=require({json.dumps(str(MODULE))});"
            f"Promise.resolve((async()=>{{{script}}})()).then(v=>process.stdout.write(JSON.stringify(v)))"
            ".catch(e=>{console.error(e&&e.stack||e);process.exit(1)})")
    done = subprocess.run([exe, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_python_preview_is_read_strictly(tmp_path):
    preview = asyncio.run(service(tmp_path, seeded(tmp_path)).preview())
    out = node(f"const p=J.parsePreview({json.dumps(preview)}).preview;"
               "return {dest:p.destination,board:p.board,ids:p.included.map(i=>i.id),out:p.excluded.map(i=>i.id),"
               "transport:p.transport,approx:p.approxBytes,"
               "bad:[J.parsePreview(null).ok,J.parsePreview({destination:1,included:[],excluded:[]}).ok,J.parsePreview({destination:'x'}).ok]}")
    assert out["dest"] == "e.debazelaire@circoe.com"
    assert out["board"] == {"id": "board_0123abcd", "title": "Budget 2027", "kind": "presentation"}
    assert out["ids"] == ["report", "logs", "state_databases", "board_memory", "settings", "health"]
    assert "credential_vault" in out["out"] and out["transport"]["available"] is True and out["approx"] > 0
    assert out["bad"] == [False, False, False]


def test_sizes_elapsed_and_refusals_in_words():
    out = node("return {b:[J.formatBytes(0),J.formatBytes(900),J.formatBytes(5000),J.formatBytes(3.5*1048576),J.formatBytes(-1)],"
               "e:[J.elapsed(5),J.elapsed(75)],"
               "r:[J.blockedReason({consent:false},'send'),J.blockedReason({consent:true,busy:{}},'send'),"
               "J.blockedReason({consent:true,preview:{transport:{available:false,label:'aucun moyen d’envoi configuré'}}},'send'),"
               "J.blockedReason({consent:true,preview:{transport:{available:false}}},'save'),J.blockedReason({consent:true},'send')]}")
    assert out["b"] == ["0 o", "900 o", "5 Ko", "3,5 Mo", "—"]
    assert out["e"] == ["5 s", "1 min 15 s"]
    assert out["r"][0].startswith("Cochez") and out["r"][1].startswith("Une action")
    assert "aucun moyen" in out["r"][2] and out["r"][3] is None and out["r"][4] is None


def test_the_module_parses_with_node():
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    done = subprocess.run([exe, "--check", str(MODULE)], capture_output=True, text=True, timeout=30, check=False)
    assert done.returncode == 0, done.stderr
