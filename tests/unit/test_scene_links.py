"""Règle unique d'un lien d'artefact, partagée par la page et le cerveau (Slice 09, reprise QA M3).

Le même corpus (`tests/fixtures/scene_link_corpus.json` : les 52 URL de la QA et des ajouts) fixe, pour
chaque URL, `link` et `host`. `jarvis.domain.scene_links.link_host` (hôte de `scene_get`) et `linkOf` de
`control_center_scene_layout.js` (lien de la page, avec l'analyseur d'URL de node) doivent le suivre tous
les deux, sans écart.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.scene_links import link_host

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "fixtures" / "scene_link_corpus.json"
LAYOUT_JS = ROOT / "jarvis" / "runtime" / "control_center_scene_layout.js"


def corpus() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_the_corpus_covers_the_qa_attacks_and_both_outcomes():
    rows = corpus()
    names = {row["name"] for row in rows}
    assert len(rows) >= 90 and len(names) == len(rows)
    for attack in ("backslash trick", "backslash2", "IDN cyrillic a", "fullwidth dot", "ideographic dot host", "IPv4 decimal",
                   "IPv4 hex", "percent host", "userinfo", "IDN ru"):
        assert attack in names and next(r for r in rows if r["name"] == attack)["link"] is False, attack
    assert sum(row["link"] for row in rows) >= 25 and all((row["host"] is None) is (not row["link"]) for row in rows)


def test_python_follows_the_corpus():
    mismatches = [(row["name"], row["host"], link_host(row["url"])) for row in corpus() if link_host(row["url"]) != row["host"]]
    assert mismatches == []


def test_the_page_follows_the_same_corpus():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = r"""
      const L=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{
        const rows=JSON.parse(s);
        process.stdout.write(JSON.stringify(rows.map(r=>{const l=L.linkOf(r.url);
          return {name:r.name,link:!!l,host:l?l.host:null,rule:L.linkHost(r.url),href:l?l.href:null}})));});
    """
    result = subprocess.run([node, "-e", script, str(LAYOUT_JS)], input=json.dumps(corpus()), capture_output=True, text=True,
                            encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    page = json.loads(result.stdout)
    mismatches = [(row["name"], (row["link"], row["host"]), (js["link"], js["host"], js["rule"]))
                  for row, js in zip(corpus(), page) if (row["link"], row["host"]) != (js["link"], js["host"]) or js["rule"] != row["host"]]
    assert mismatches == []
    for row, js in zip(corpus(), page):
        if js["link"]:
            assert js["href"].startswith(("http://", "https://")) and "@" not in js["href"].split("/")[2]
