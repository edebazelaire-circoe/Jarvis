"""Espace de travail Architecture (refonte-ui-settings, Slice 04) dans un vrai Chrome sans tête.

Contrat : `docs/settings/architecture-tab.md` § 3–5 et `docs/settings/brain-config-panel.md` § 5–6. Un VRAI Control
Center isolé (fixture `served` : runtime temporaire, jamais le JARVIS vivant) sert la page ; le seul journal servi est
une fixture (`stub('/api/trace')`) pour que les captures soient déterministes. Ce que ce fichier prouve :

- la composition de la maquette 03 : trois cartes en tête (état, règles, actions) calculées depuis le snapshot servi,
  un canevas qui a toute la largeur, le journal et la légende en bas ; aucun défilement horizontal de la page à
  1672×941, 1254×1254, 1280×800 et 1000×800, fenêtre du cerveau ouverte, sans couvrir le nœud configuré ;
- la légende ne montre que les canaux présents dans le graphe ; le journal ne garde que `architecture.*` et
  `brain_config.*` (sans les lectures), et dit honnêtement quand il est illisible ;
- la fenêtre du cerveau marque son nœud (pointillés) et le démarque à sa fermeture ;
- une règle d'architecture sélectionne sa liaison : l'inspecteur flotte du côté opposé, Échap le ferme et rend le
  focus au libellé ; relire le journal ne remplace que sa carte (le focus reste) ;
- « Réinitialiser la disposition » (deux temps) n'écrit qu'une disposition vide : le snapshot ne change pas.

Se saute si Chrome ou node manque. `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures (JPEG).
"""

from __future__ import annotations

import json

from tests.unit.settings_visual import OVERFLOW, VIEWS, freeze, shot, shots_dir, stub
from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, wait  # noqa: F401

#: Entrées du journal du Control Center, dans le format de `/api/trace` (plus ancienne d'abord). La donnée vit ici,
#: jamais dans le composant ; la lecture `brain_config.read` et l'événement étranger doivent être écartés.
TRACE = [
    {"ts": "2026-10-24T12:31:58+00:00", "kind": "voice.turn", "level": "info", "message": "Tour vocal", "data": {}},
    {"ts": "2026-10-24T12:32:04+00:00", "kind": "brain_config.read", "level": "info", "message": "Configuration du cerveau lue.",
     "data": {"brain_id": "core"}},
    {"ts": "2026-10-24T12:32:11+00:00", "kind": "architecture.layout.saved", "level": "info",
     "message": "Disposition du graphe enregistrée", "data": {"revision": "3", "nodes": 6}},
    {"ts": "2026-10-24T12:32:15+00:00", "kind": "architecture.write.refused", "level": "warning",
     "message": "Écriture d'architecture refusée", "data": {"code": "connection_locked", "status": 423}},
    {"ts": "2026-10-24T12:32:18+00:00", "kind": "brain_config.saved", "level": "info",
     "message": "Configuration du cerveau core : delegation enregistré.", "data": {"brain_id": "core", "fields": ["delegation"]}},
]
JOURNAL = stub("/api/trace", TRACE)

OPEN_CORE = [
    click("[data-architecture-page] [data-arch-menu-btn=core]"),
    wait("!!document.querySelector('[data-arch-menu=configure]')"),
    click("[data-arch-menu=configure]"),
    wait("!!document.querySelector('.bcp-win [data-bcp-radio=delegation]')", 10000),
]
JOURNAL_READY = wait("!!document.querySelector('[data-arch-journal-entry]')", 8000)

#: Régions de la page, largeur relative du canevas, contenu des cartes et de la légende.
REGIONS = """(()=>{const q=s=>document.querySelector(s),all=s=>[...document.querySelectorAll(s)];
  const page=q('[data-architecture-page]'),canvas=q('[data-arch-canvas]');
  const snap=ARCH.view.state.snapshot,chans=new Set(snap.connections.map(c=>c.channel));
  return {cards:all('[data-arch-card]').map(e=>e.getAttribute('data-arch-card')),
    canvasShare:Math.round(canvas.getBoundingClientRect().width/page.getBoundingClientRect().width*100),
    inspector:!!q('[data-arch-inspector]'),health:q('[data-arch-health]').getAttribute('data-arch-health'),
    healthText:q('[data-arch-health]').textContent,
    rules:all('.arch-rule').map(e=>e.getAttribute('data-arch-focus-conn')),
    locked:snap.connections.filter(c=>c.mutability==='required_locked'||c.mutability==='governed').map(c=>c.id),
    legendChannels:all('.arch-legend-ch li').length,channels:chans.size,
    journal:all('[data-arch-journal-entry]').map(e=>e.getAttribute('data-arch-journal-entry')),
    voiceLink:(q('[data-arch-voice] [data-settings-open]')||{}).textContent||null,
    subagents:!!q('[data-arch-card=actions] [data-settings-open=subagents]')}})()"""

PANEL = """(()=>{const w=document.querySelector('.bcp-win').getBoundingClientRect(),
  n=document.querySelector('[data-architecture-page] [data-arch-node=core]');const r=n.getBoundingClientRect();
  const ox=Math.max(0,Math.min(w.right,r.right)-Math.max(w.left,r.left)),oy=Math.max(0,Math.min(w.bottom,r.bottom)-Math.max(w.top,r.top));
  return {overlap:ox*oy,inViewport:w.left>=0&&w.top>=0&&w.right<=innerWidth&&w.bottom<=innerHeight,
    marked:[...document.querySelectorAll('.arch-node.cfg')].map(e=>e.getAttribute('data-arch-node')),
    eyebrow:document.querySelector('.bcp-eyebrow').textContent}})()"""

#: Fait défiler le conteneur des Réglages jusqu'au journal et à la légende (capture du bas de la page).
TO_BOTTOM = """(()=>{let e=document.querySelector('[data-architecture-page]');
  while(e&&!(e.scrollHeight>e.clientHeight+1&&/auto|scroll/.test(getComputedStyle(e).overflowY)))e=e.parentElement;
  if(e)e.scrollTop=e.scrollHeight;return !!e})()"""

SIZES = [(1672, 941), (1254, 1254), (1280, 800), (1000, 800)]


async def test_workspace_composes_the_reference_without_overflow_and_the_window_marks_its_node(served, tmp_path):
    shots = shots_dir(tmp_path, "architecture-workspace")
    steps = []
    for width, height in SIZES:
        steps.append({"width": width, "height": height, "stubs": [JOURNAL], "actions": [
            *VIEWS["architecture"], JOURNAL_READY, freeze(),
            eval_(REGIONS, "regions"), eval_(OVERFLOW, "overflow"), shot(shots / f"apres-{width}x{height}.jpg"),
            eval_(TO_BOTTOM), shot(shots / f"apres-bas-{width}x{height}.jpg"),
            *OPEN_CORE, eval_("new Promise(r=>setTimeout(()=>r(1),300))"), freeze(),
            eval_(PANEL, "panel"), eval_(OVERFLOW, "overflow_panel"), shot(shots / f"apres-fenetre-{width}x{height}.jpg"),
            key("Escape"), wait("document.querySelector('.bcp-win')===null"),
            eval_("document.querySelectorAll('.arch-node.cfg').length", "unmarked"),
        ]})
    out = await drive(served.url, steps)
    assert out["console"] == [], out["console"]
    for (width, height), step in zip(SIZES, out["steps"]):
        waits = [a for a in step["actions"] if a.get("a") == "wait"]
        assert all(a["ok"] for a in waits), ((width, height), [a for a in waits if not a["ok"]])
        r = got(step, "regions")
        assert r["cards"] == ["state", "rules", "actions", "journal", "legend"], r
        assert r["canvasShare"] >= 98 and not r["inspector"], ("le canevas a toute la largeur", r)
        assert set(r["rules"]) <= set(r["locked"]) and r["rules"], r
        assert r["legendChannels"] == r["channels"], r
        # Le journal garde l'architecture et la configuration des cerveaux, plus récente d'abord, sans les lectures.
        assert r["journal"] == ["brain_config.saved", "architecture.write.refused", "architecture.layout.saved"], r
        assert r["voiceLink"] and r["subagents"], r
        assert got(step, "overflow")["page"] == 0 and got(step, "overflow_panel")["page"] == 0, (width, got(step, "overflow"))
        p = got(step, "panel")
        assert p["overlap"] == 0 and p["inViewport"], ((width, height), p)
        assert p["marked"] == ["core"] and p["eyebrow"] == "Configuration", p
        assert got(step, "unmarked") == 0


RULE_THEN_ESCAPE = [
    eval_("(()=>{const b=document.querySelector('.arch-rule');b.focus();return b.getAttribute('data-arch-focus-conn')})()", "rule"),
    # Une relecture du journal ne remplace que sa carte : le focus reste sur la règle.
    eval_("ARCH.view.loadJournal().then(()=>document.activeElement.getAttribute('data-arch-focus-conn'))", "after_journal"),
    key("Enter"),
    wait("!!document.querySelector('[data-arch-inspector]')"),
    eval_("""(()=>{const i=document.querySelector('[data-arch-inspector]'),a=document.activeElement,id=ARCH.view.state.selected.id;
      const label=document.querySelector('.arch-label[data-arch-conn="'+CSS.escape(id)+'"]').getBoundingClientRect(),box=i.getBoundingClientRect();
      const ox=Math.max(0,Math.min(box.right,label.right)-Math.max(box.left,label.left)),oy=Math.max(0,Math.min(box.bottom,label.bottom)-Math.max(box.top,label.top));
      return {selected:id,dock:i.className.match(/dock-(left|right)/)[1],covers:ox*oy,focus:a.getAttribute('data-arch-conn')}})()""", "inspect"),
    key("Escape"),
    eval_("[!!document.querySelector('[data-arch-inspector]'),document.activeElement.getAttribute('data-arch-conn'),SET.open]", "closed"),
]


async def test_a_rule_selects_its_link_and_the_floating_inspector_does_not_cover_it(served):
    out = await drive(served.url, [{"width": 1672, "height": 941, "actions": [*VIEWS["architecture"], *RULE_THEN_ESCAPE]}])
    step = out["steps"][0]
    assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait")
    rule = got(step, "rule")
    assert got(step, "after_journal") == rule, "la relecture du journal garde le focus"
    i = got(step, "inspect")
    assert i["selected"] == rule and i["focus"] == rule, i
    assert i["covers"] == 0, ("l'inspecteur flotte du côté opposé au libellé", i)
    assert got(step, "closed") == [False, rule, True], "Échap ferme l'inspecteur, rend le focus au libellé, garde les Réglages"
    assert out["console"] == [], out["console"]


LAYOUT_CALLS = "(()=>({revision:ARCH.view.state.snapshot.revision,layout:ARCH.view.state.layout.revision,positions:Object.keys(ARCH.view.state.layout.positions)}))()"


async def test_reset_layout_is_two_steps_and_only_writes_an_empty_layout(served):
    actions = [
        *VIEWS["architecture"],
        eval_("document.querySelector('[data-arch-act=layout-reset]').disabled", "disabled_before"),
        eval_("document.querySelector('[data-architecture-page] [data-arch-node=core]').focus();1"),
        key("ArrowRight", shift=True),
        wait("!!document.querySelector('[data-arch-layout-note].ok')", 8000),
        eval_(LAYOUT_CALLS, "moved"),
        click("[data-arch-act=layout-reset]"),
        eval_("document.querySelector('[data-arch-act=layout-reset]').textContent.trim()", "confirm_text"),
        click("[data-arch-act=layout-reset]"),
        wait("/réinitialisée/.test((document.querySelector('[data-arch-layout-note]')||{}).textContent||'')", 8000),
        eval_(LAYOUT_CALLS, "reset"),
        eval_("document.querySelector('[data-arch-act=layout-reset]').disabled", "disabled_after"),
    ]
    out = await drive(served.url, [{"width": 1672, "height": 941, "actions": actions}])
    step = out["steps"][0]
    assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait"), [a for a in step["actions"] if a.get("a") == "wait"]
    assert got(step, "disabled_before") is True, "sans position enregistrée, rien à réinitialiser"
    moved, reset = got(step, "moved"), got(step, "reset")
    assert moved["positions"] == ["core"]
    assert got(step, "confirm_text").startswith("Confirmer")
    assert reset["positions"] == [] and reset["revision"] == moved["revision"], ("la topologie ne change pas", moved, reset)
    assert got(step, "disabled_after") is True
    puts = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "PUT" and r["path"] == "/api/architecture/layout"]
    assert len(puts) == 2 and puts[-1]["positions"] == {}
    stored = json.loads((served.runtime / "architecture-layout.json").read_text(encoding="utf-8"))
    assert stored["positions"] == {}
    writes = [r for r in out["requests"] if r["path"].startswith("/api/architecture/connections")]
    assert writes == [], "réinitialiser la disposition n'écrit aucune liaison"
    assert out["console"] == [], out["console"]


async def test_an_unreadable_journal_says_so_with_its_code(served):
    broken = stub("/api/trace", {"ok": False, "code": "trace_unreadable", "reason": "Journal verrouillé"}, status=503)
    out = await drive(served.url, [{"width": 1280, "height": 800, "stubs": [broken], "actions": [
        *VIEWS["architecture"], wait("!!document.querySelector('[data-arch-journal-error]')", 8000),
        eval_("document.querySelector('[data-arch-journal-error]').textContent", "error"),
        eval_("!!document.querySelector('[data-arch-act=journal-reload]:not([disabled])')", "retry"),
    ]}])
    step = out["steps"][0]
    assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait")
    text = got(step, "error")
    assert "Journal verrouillé" in text and "trace_unreadable" in text, text
    assert got(step, "retry") is True
