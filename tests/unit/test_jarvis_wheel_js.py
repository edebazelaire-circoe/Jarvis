"""Catégories JARVIS et Paramètres de la roue, modèle pur exécuté par node.

Handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 04 (`docs/06-ui-visual-spec.md`
› C et F ; contrat `docs/control-center-shell.md` › *Tool wheel*). Ce que ce fichier
épingle :

- le sous-menu JARVIS ne montre que des faits du battement `/api/status` et deux
  portes vers des surfaces existantes ; aucune commande Veille / Réveil, Pause ou
  mode de réflexion (aucune route ne les porte) ;
- inconnu n'est jamais un état deviné : avant le premier battement et après un
  battement perdu, chaque fait dit « état inconnu » et pourquoi ; rien n'est gardé
  d'un battement réussi précédent ;
- la touche d'éveil dit ce qu'elle fait maintenant (l'ancien `#wakeHint`, mêmes
  phrases) ;
- Paramètres : une ligne par onglet réel des réglages, aucune inventée ;
- le module est inséré dans la page servie, après la roue, et `refreshStatus` le
  nourrit (`gate` / `statusLost`) sans second sondage.

Le DOM et les routes sont prouvés dans Chrome par `test_jarvis_wheel_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    CAPTURE_WHEEL_SCRIPT_MARKER,
    JARVIS_WHEEL_SCRIPT_FILE,
    JARVIS_WHEEL_SCRIPT_MARKER,
    TOOL_WHEEL_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / JARVIS_WHEEL_SCRIPT_FILE
PAGE_HTML = RUNTIME / "control_center.html"

STATUS = {"voice_state": "idle", "voice_online": True, "manual_wake_key": "f9", "voice_turn_mode": "auto",
          "voice_stack_label": "Cerveau continu", "agent_cli": "claude",
          "agent": {"name": "Claude", "state": "running", "model": "opus"}, "subagents": {"active": 2, "running_shell": 0}}


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "jarvis.js"
    script.write_text(
        f"const J=require({json.dumps(str(MODULE))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        f"const S={json.dumps(STATUS)};\n" + body,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_online_rows_are_facts_with_their_source_and_two_existing_routes(tmp_path):
    rows = run(tmp_path, "out(J.jarvisItemsOf(J.factsOf(S,'ok')))")
    assert [r["id"] for r in rows] == ["voice", "wake", "agent", "subagents", "voice_settings"]
    by = {r["id"]: r for r in rows}
    assert by["voice"]["status"] is True and by["voice"]["note"] == "Veille · SLEEP"
    assert by["voice"]["detail"] == "Voice en ligne, veille, pile Cerveau continu"
    assert by["wake"]["status"] is True and by["wake"]["label"] == "F9 · DÉMARRER"
    assert by["wake"]["note"] == "tour automatique" and by["wake"]["detail"] == "touche F9, raccourci global de Voice, tour automatique"
    assert by["agent"]["label"] == "Agent : Claude" and by["agent"]["note"] == "actif"
    assert by["agent"]["detail"] == "état du brain : actif, modèle opus"
    assert by["subagents"]["note"] == "2 en cours" and "status" not in by["subagents"]
    assert by["voice_settings"]["kind"] == "action" and "status" not in by["voice_settings"]
    # Les lignes d'état n'agissent pas ; le module pur ne branche aucune action.
    assert all("onActivate" not in r for r in rows)


def test_no_fake_control_is_ever_offered(tmp_path):
    texts = run(tmp_path, """
      const all=[];for(const state of ['idle','waiting','listening','speaking','thinking','weird'])
        for(const online of [true,false])all.push(...J.jarvisItemsOf(J.factsOf({...S,voice_state:state,voice_online:online},'ok')));
      all.push(...J.jarvisItemsOf(J.factsOf(null,'lost')),...J.jarvisItemsOf(J.factsOf(null,'pending')));
      out(all.map(r=>[r.id,r.label,r.note||'',r.detail||''].join(' | ')))""")
    joined = "\n".join(texts).lower()
    for word in ("pause", "réveiller", "endormir", "mettre en veille", "autonomie", "focus", "réflexion profonde"):
        assert word not in joined, word
    assert {t.split(" | ")[0] for t in texts} == {"voice", "wake", "agent", "subagents", "voice_settings"}


def test_each_voice_state_reads_with_the_orb_vocabulary_and_the_wake_key_sentence(tmp_path):
    got = run(tmp_path, """
      const o={};for(const [state,turn] of [['idle','auto'],['waiting','manual'],['waiting','auto'],['listening','manual'],
        ['speaking','auto'],['thinking','auto'],['weird','auto']]){
        const f=J.factsOf({...S,voice_state:state,voice_turn_mode:turn},'ok');
        o[state+':'+turn]={note:J.jarvisItemsOf(f)[0].note,hint:J.wakeHintOf(f)};}
      const off=J.factsOf({...S,voice_online:false,voice_state:'listening'},'ok');
      o.offline={rows:J.jarvisItemsOf(off).slice(0,2),hint:J.wakeHintOf(off),cat:J.categoryStatusOf(off)};
      out(o)""")
    assert got["idle:auto"] == {"note": "Veille · SLEEP", "hint": "F9 · DÉMARRER"}
    assert got["waiting:manual"] == {"note": "Attente · WAIT", "hint": "F9 · ENVOYER"}
    assert got["waiting:auto"]["hint"] == "F9 · ANNULER"
    assert got["listening:manual"] == {"note": "Écoute · LISTEN", "hint": "F9 · ENVOYER"}
    assert got["speaking:auto"] == {"note": "Parole · TALK", "hint": "F9 · INTERROMPRE"}
    assert got["thinking:auto"] == {"note": "Réflexion · THINKING", "hint": "F9 · ANNULER"}
    assert got["weird:auto"] == {"note": "WEIRD", "hint": "F9 · CONTRÔLER"}, "un état inconnu n'est pas traduit au hasard"
    off = got["offline"]
    assert off["rows"][0]["note"] == "hors ligne" and off["rows"][0]["tone"] == "off"
    assert off["hint"] == "F9 · VOICE HORS LIGNE" and off["rows"][1]["label"] == "F9 · VOICE HORS LIGNE"
    assert off["rows"][1]["note"] == "Voice hors ligne : sans effet"
    assert off["cat"] == {"tone": None, "text": "voix hors ligne · 2 sous-agents"}


def test_unknown_before_the_first_beat_and_after_a_lost_beat_never_a_stale_fact(tmp_path):
    got = run(tmp_path, """
      const pending=J.factsOf(null,'pending'),lost=J.factsOf(S,'lost');
      out({pending:J.jarvisItemsOf(pending),lost:J.jarvisItemsOf(lost),hint:J.wakeHintOf(lost),
        catPending:J.categoryStatusOf(pending),catLost:J.categoryStatusOf(lost),
        none:J.jarvisItemsOf(J.factsOf(undefined))})""")
    for key in ("pending", "lost"):
        rows = got[key]
        assert [r["tone"] for r in rows[:4]] == ["unknown"] * 4, rows
        assert rows[0]["note"] == rows[1]["note"] == rows[2]["note"] == "état inconnu"
        assert rows[3]["note"] == "nombre inconnu"
        # Même avec un statut passé en argument, un battement perdu ne garde rien.
        assert "Claude" not in json.dumps(rows) and "SLEEP" not in json.dumps(rows)
    assert got["lost"][0]["detail"] == "statut du Control Center illisible : rien n’est confirmé"
    assert got["pending"][0]["detail"].startswith("pas encore lu")
    assert got["hint"] == "VOICE HORS LIGNE"
    assert got["catPending"] is None
    assert got["catLost"] == {"tone": "unknown", "text": "état inconnu, statut illisible"}
    assert got["none"] == got["pending"]


def test_agent_and_subagent_edges(tmp_path):
    got = run(tmp_path, """
      const rows=s=>J.jarvisItemsOf(J.factsOf(s,'ok'));
      out({stopped:rows({...S,agent:{name:'Claude',state:'stopped'}})[2],
        error:rows({...S,agent:{state:'error'},agent_cli:'codex'})[2],
        silent:rows({...S,agent:null,agent_cli:''})[2],
        zero:rows({...S,subagents:{active:0}})[3],one:rows({...S,subagents:{active:1}})[3],
        missing:rows({...S,subagents:null})[3],
        cat:J.categoryStatusOf(J.factsOf({...S,voice_state:'listening',subagents:{active:1}},'ok'))})""")
    assert got["stopped"]["note"] == "arrêté" and got["stopped"]["detail"] == "état du brain : arrêté"
    assert got["error"]["label"] == "Agent : codex" and got["error"]["tone"] == "error"
    assert got["silent"]["label"] == "Agent : inconnu" and got["silent"]["note"] == "état non dit"
    assert got["silent"]["tone"] == "unknown"
    assert got["zero"]["note"] == "aucun en cours" and got["one"]["note"] == "1 en cours"
    assert got["missing"]["note"] == "nombre non dit" and got["missing"]["tone"] == "unknown"
    assert got["cat"] == {"tone": None, "text": "voix : écoute · 1 sous-agent"}


def test_settings_rows_follow_the_six_categories(tmp_path):
    """Une ligne par catégorie des réglages (`settingsTabs()`, Slice 02 de jarvis-settings-ui-reorganization)."""
    got = run(tmp_path, """
      out({tabs:J.settingsItemsOf([{id:'voice_audio',label:'Voix & audio',description:'Conversation, voix.'},
          {id:'connections',label:'Connexions'},{id:'future_cat',label:'Plus tard',description:'Une description.'},{id:'bare',label:'Nue'}]),
        none:J.settingsItemsOf(null),bad:J.settingsItemsOf([{label:'sans id'},null])})""")
    assert [(r["id"], r["tab"], r["label"], r["note"]) for r in got["tabs"]] == [
        ("tab:voice_audio", "voice_audio", "Voix & audio", "micro, voix, mot d’éveil"),
        ("tab:connections", "connections", "Connexions", "fournisseurs et clés"),
        ("tab:future_cat", "future_cat", "Plus tard", "Une description."),
        ("tab:bare", "bare", "Nue", "catégorie des réglages")]
    assert got["tabs"][0]["detail"] == "ouvre les réglages, catégorie Voix & audio"
    assert got["none"] == got["bad"] == [{"id": "settings", "tab": None, "icon": "settings",
                                          "label": "Réglages de Jarvis", "note": "ouvrir"}]


def test_inserted_after_the_wheel_and_fed_by_the_one_status_beat():
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert html.index(TOOL_WHEEL_SCRIPT_MARKER) < html.index(CAPTURE_WHEEL_SCRIPT_MARKER) < html.index(JARVIS_WHEEL_SCRIPT_MARKER)
    status = html[html.index("async function refreshStatus(){"):]
    status = status[:status.index("\n")]
    assert "JarvisRuntimeWheel.gate(s)" in status and "JarvisRuntimeWheel.statusLost()" in status
    # Le rappel de la touche d'éveil vit dans le sous-menu : plus de `#wakeHint` caché.
    assert 'id="wakeHint"' not in html and "setWakeHint" not in html
    source = MODULE.read_text(encoding="utf-8")
    assert "fetch(" not in source and "setInterval" not in source and "setTimeout" not in source, "aucun second sondage"
    # Les deux portes sont les routes existantes : le bouton Agents et le modal des réglages.
    assert "getElementById('agentsButton')" in source and "root.openSettingsTab(" in source
    assert re.search(r"function openSettingsTab\(tab,options\)\{", html) and re.search(r"function settingsTabs\(\)\{", html)
