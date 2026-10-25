"""Essai réel S07 (refonte-ui-settings) en bac à sable : Core + Control Center lancés depuis le worktree `rui`, ports
27653/27654, racines (données, runtime) dans ce dossier `s07`, visualiseur coupé, CLI cerveau neutralisé (commande
absente : aucun Claude lancé). Candidats de consolidation semés dans la vraie file de Core (FileCandidateStore). Le
navigateur (harnais CDP des tests) parcourt les cinq vues. N'arrête QUE les PID lancés ici (TerminateProcess, sans /T).
Les bases et fichiers du bac à sable restent en place.

Usage : python sandbox_s07.py
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = Path("C:/Projects/jarvis/rui")
PY = Path("C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe")
DATA = HERE / "data"
RUNTIME = HERE / "runtime"
UI = "http://127.0.0.1:27654"
LOG = HERE / "sandbox-log.txt"
sys.path.insert(0, str(WORKTREE))


def say(text: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as out:
        out.write(line + "\n")


def free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _free_on(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def env() -> dict:
    out = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    out.update(JARVIS_DATA_ROOT=str(DATA), JARVIS_RUNTIME_DIR=str(RUNTIME), JARVIS_CORE_PORT="27653",
               JARVIS_UI_PORT="27654", JARVIS_VISUALIZER_ENABLED="0", PYTHONIOENCODING="utf-8")
    return out


def seed() -> None:
    """Réglages du bac à sable (CLI cerveau absent) et candidats réels dans `<data>/memory/_candidates/`."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    settings = RUNTIME / "control-center-settings.json"
    if not settings.exists():
        settings.write_text(json.dumps({"agent_cli_settings": {"claude": {"command": str(HERE / "no-claude-in-sandbox.exe")}}}),
                            encoding="utf-8")
    from jarvis.adapters.memory_candidates import FileCandidateStore
    from jarvis.domain.memory import Candidate, MemoryKind, MemoryLevel, RetentionClass
    store = FileCandidateStore(DATA / "memory")
    now = datetime.now(timezone.utc)
    texts = [("Vous préférez des réponses concises avec des exemples", MemoryKind.PREFERENCE),
             ("Vous travaillez sur la refonte des Réglages de JARVIS", MemoryKind.FACT),
             ("Vous testez le rappel avant chaque démonstration", MemoryKind.SCENARIO)]
    for i, (title, kind) in enumerate(texts):
        cid = f"s07cand{i + 1}"
        try:
            store.get(cid)
            continue
        except Exception:  # noqa: BLE001 - absent : on le crée
            pass
        store.save(Candidate(id=cid, title=title, body=title + ".", level=MemoryLevel.L1, kind=kind,
                             retention=RetentionClass.LONG_TERM, scope="private", confidence=0.8 - i * 0.05,
                             evidence_hash=f"s07evidence{i + 1:04d}", created_at=now))
    say(f"candidats semés : {[c.id for c in store.list()]}")


def launch(kind: str) -> subprocess.Popen:
    out = open(HERE / f"{kind}.log", "a", encoding="utf-8")
    proc = subprocess.Popen([str(PY), "-m", "jarvis", kind], cwd=WORKTREE, env=env(), stdout=out, stderr=subprocess.STDOUT)
    say(f"{kind} lancé : PID {proc.pid}")
    return proc


def wait_url(url: str, proc: subprocess.Popen, seconds: int = 90) -> None:
    for _ in range(seconds * 2):
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except (urllib.error.URLError, OSError):
            if proc.poll() is not None:
                raise SystemExit(f"processus arrêté au démarrage ({url})")
            time.sleep(0.5)
    raise SystemExit(f"injoignable : {url}")


def stop(proc: subprocess.Popen, kind: str) -> None:
    proc.terminate()  # TerminateProcess sur CE PID seulement
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    say(f"{kind} arrêté : PID {proc.pid}, code {proc.returncode}")


async def tour() -> dict:
    from tests.unit.test_wake_word_settings_browser import drive, click, eval_, key, wait
    shots = HERE / "shots"
    shots.mkdir(exist_ok=True)

    def shot(name: str) -> dict:
        return {"a": "shot", "path": str(shots / name)}

    hub = [wait("!!document.getElementById('openSettings')", 15000), click("#dockMore"), click("#openSettings"),
           wait("!!document.querySelector('#settingsHubGrid [data-hub-category]')")]
    pause = lambda ms: eval_(f"new Promise(r=>setTimeout(()=>r(1),{ms}))")  # noqa: E731
    plans = {
        "perso": [{"width": 1672, "height": 941, "actions": [
            *hub, click("#settingsHubGrid [data-hub-category=voice_audio]"),
            wait("!!document.querySelector('#persoGrid .perso-persona')", 15000),
            click("#persoProfileBtn"), wait("!document.getElementById('persoProfileMenu').hidden"),
            eval_("document.activeElement.className", "profile_focus"), shot("perso-profils.jpg"),
            key("Escape"), eval_("[document.getElementById('persoProfileMenu').hidden,document.activeElement.id]", "profile_closed"),
            click("[data-perso-preset=concise]"), wait("document.querySelector('[data-card-status=presets]').dataset.kind==='ok'", 15000),
            click("#persoCrumbHub"), wait("document.getElementById('overlay').dataset.view==='hub'"),
            key("Escape"), wait("!document.getElementById('overlay').classList.contains('open')"),
        ]}],
        "architecture": [{"width": 1254, "height": 1254, "actions": [
            *hub, click("#settingsHubGrid [data-hub-category=agents_models]"),
            wait("!!document.querySelector('[data-architecture-page] [data-arch-node=core]')", 20000), pause(800),
            eval_("({layout:document.getElementById('settingsShell').dataset.layout,rail:!!document.getElementById('settingsCategories').getClientRects().length,"
                  "health:(document.querySelector('[data-arch-health]')||{}).textContent})", "arch"),
            eval_("(document.querySelector('[data-architecture-page] [data-arch-menu-btn=core]').click(),1)"),
            wait("!!document.querySelector('[data-arch-menu=configure]')"),
            eval_("(document.querySelector('[data-arch-menu=configure]').click(),1)"),
            wait("!!document.querySelector('.bcp-win')", 15000), pause(800), shot("architecture-fenetre-1254.jpg"),
            key("Escape"), wait("!document.querySelector('.bcp-win')", 8000),
            eval_("[document.getElementById('overlay').classList.contains('open'),SET.section]", "after_panel_escape"),
            click("#modalTabs [data-section=subagents]"),
            wait("!!document.querySelector('[data-subagent-settings-host]')&&!/Lecture de la politique/.test(document.querySelector('[data-subagent-settings-host]').textContent)", 20000),
            pause(600), shot("sous-agents-1254.jpg"),
            key("Escape"), wait("!document.getElementById('overlay').classList.contains('open')"),
        ]}],
        "memory": [{"width": 1254, "height": 1254, "actions": [
            *hub, click("#settingsHubGrid [data-hub-category=memory_knowledge]"),
            wait("!!document.querySelector('#memSection_recall [data-mem]')&&!/Lecture…/.test(document.getElementById('memSection_recall').textContent)", 20000),
            pause(600), shot("memoire-1254.jpg"),
            eval_("[...document.querySelectorAll('#memSection_recall .mem-tile small')].map(e=>e.textContent)", "tiles"),
            click("#modalTabs [data-section=knowledge_sources]"),
            wait("!!document.querySelector('.mem-source')&&!/Lecture…/.test(document.getElementById('modalContent').textContent)", 15000),
            eval_("Object.fromEntries([...document.querySelectorAll('.mem-source')].map(c=>[c.querySelector('h3').textContent,c.querySelector('.mem-pill').textContent.trim()]))", "sources"),
            click("#modalTabs [data-section=memory_center]"),
            wait("!!document.querySelector('#modalContent .mcw .mc-stats')&&!/Chargement/.test(document.querySelector('#modalContent .mcw').textContent)", 20000),
            pause(800), shot("memory-center-1254.jpg"),
            eval_("[...document.querySelectorAll('.mc-stat strong')].map(e=>e.textContent)", "stats"),
            # Décision réelle d'un candidat : Accepter, confirmer, la note canonique apparaît.
            wait("!!document.querySelector('[data-act=cand-accept]')", 15000),
            eval_("(document.querySelector('[data-act=cand-accept]').click(),1)"),
            wait("!!document.querySelector('[data-act=decide]')"),
            eval_("(document.querySelector('[data-act=decide]').click(),1)"),
            pause(2500),
            eval_("[...document.querySelectorAll('.mc-stat strong')].map(e=>e.textContent)", "stats_after"),
            # Test de rappel réel (Core).
            click("[data-act=tab][data-tab=recall]"), wait("!!document.getElementById('mcRecallQ')", 8000),
            eval_("(()=>{const i=document.getElementById('mcRecallQ');i.value='réponses concises';i.dispatchEvent(new Event('input',{bubbles:true}));i.focus();return 1})()"),
            key("Enter"), pause(4000),
            eval_("(document.getElementById('modalContent').querySelector('.mc-results,.mc-empty,.mc-error')||{}).textContent", "recall"),
            shot("memory-center-rappel-1254.jpg"),
            key("Escape"), wait("!document.getElementById('overlay').classList.contains('open')"),
        ]}],
    }
    results = {}
    for name, plan in plans.items():
        results[name] = await drive(UI + "/", plan)
        step = results[name]["steps"][0]
        failed = [a for a in step["actions"] if a.get("a") == "wait" and not a.get("ok")]
        named = {a["id"]: a.get("value") for a in step["actions"] if a.get("id")}
        say(f"{name} : attentes échouées {failed} ; mesures {json.dumps(named, ensure_ascii=False)[:1500]}")
        say(f"{name} : console {json.dumps(results[name].get('console'), ensure_ascii=False)[:1500]}")
    return results


def main() -> None:
    if not (free(27653) and free(27654) and _free_on("127.77.0.1", 27653)):
        raise SystemExit("ports 27653/27654 occupés : rien n'est lancé")
    seed()
    core = launch("core")
    try:
        for _ in range(180):  # Core écoute (port ouvert) ; son hôte vient de la configuration
            if not free(27653) or any(not _free_on(h, 27653) for h in ("127.77.0.1",)):
                break
            if core.poll() is not None:
                raise SystemExit("Core arrêté au démarrage, voir core.log")
            time.sleep(0.5)
        say("Core à l'écoute sur 27653")
        cc = launch("control-center")
        try:
            wait_url(UI + "/api/status", cc, 90)
            say("Control Center prêt")
            asyncio.run(tour())
        finally:
            stop(cc, "control-center")
    finally:
        stop(core, "core")


if __name__ == "__main__":
    main()
