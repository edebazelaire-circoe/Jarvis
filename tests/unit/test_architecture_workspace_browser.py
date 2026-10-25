"""Espace de travail Architecture dans un vrai Chrome sans tête (refonte-ui-settings, Slice 04 ; graphe plein espace
depuis les retours Human du 25/10).

Contrat : `docs/settings/architecture-tab.md` § 3–5 et `docs/settings/brain-config-panel.md` § 5–6. Un VRAI Control
Center isolé (fixture `served` : runtime temporaire, jamais le JARVIS vivant) sert la page. Ce que ce fichier prouve :

- le graphe occupe toute la place sous l'en-tête de la page (largeur et hauteur restantes), sans rien à faire défiler
  et sans débordement horizontal à 1672×941, 1254×1254, 1280×800 et 1000×800 ; plus aucune carte autour (ni état,
  ni règles, ni actions rapides, ni journal) ;
- par-dessus le graphe, en haut à droite, Relire · Gestion · État · Légende ; chaque panneau s'ouvre ancré sous la
  barre, se ferme au clic dehors et par Échap ; la pastille d'État dit la santé ; la légende ne montre que les canaux
  présents ; le zoom est en bas à droite sans chevaucher la barre ;
- « Relire » dit son résultat dans un message court ; « Réinitialiser la disposition » (deux temps, dans Gestion)
  n'écrit qu'une disposition vide ;
- la fenêtre du cerveau marque son nœud, ne le couvre pas, et laisse le chrome de la page (×, ←, titre, onglet)
  atteignable.

Se saute si Chrome ou node manque. `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures (JPEG).
"""

from __future__ import annotations

import json

from tests.unit.settings_visual import OVERFLOW, VIEWS, freeze, shot, shots_dir
from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, wait  # noqa: F401

OPEN_CORE = [
    click("[data-architecture-page] [data-arch-menu-btn=core]"),
    wait("!!document.querySelector('[data-arch-menu=configure]')"),
    click("[data-arch-menu=configure]"),
    wait("!!document.querySelector('.bcp-win [data-bcp-radio=delegation]')", 10000),
]
#: La barre d'outils et le zoom sont dessinés (première lecture faite, vue ajustée au canevas).
READY = wait("!!document.querySelector('[data-arch-tools]')&&!!document.querySelector('[data-arch-zoom-level]')", 8000)

#: Régions : le canevas dans la page, la barre d'outils et le zoom dans le canevas, ce qui reste autour.
REGIONS = """(()=>{const q=s=>document.querySelector(s),all=s=>[...document.querySelectorAll(s)],box=e=>{const r=e.getBoundingClientRect();
    return {l:Math.round(r.left),t:Math.round(r.top),r:Math.round(r.right),b:Math.round(r.bottom),w:Math.round(r.width),h:Math.round(r.height)}};
  const page=q('[data-architecture-page]'),canvas=q('[data-arch-canvas]'),main=q('#settingsMain'),tabs=q('#modalTabs');
  return {canvas:box(canvas),page:box(page),tabs:box(tabs),vh:innerHeight,vw:innerWidth,
    scrollable:main.scrollHeight-main.clientHeight,fill:document.getElementById('settingsShell').hasAttribute('data-fill'),
    tools:all('[data-arch-tools] .arch-tool').map(b=>b.getAttribute('data-arch-act')||b.getAttribute('data-arch-pop')),
    toolsBox:box(q('[data-arch-tools]')),zoomBox:box(q('.arch-zoombar')),
    dot:(q('[data-arch-tool-dot]')||{getAttribute:()=>null}).getAttribute('data-arch-tool-dot'),
    gone:['[data-arch-card]','.arch-rule','.arch-quick','[data-arch-journal-entry]','.arch-top','.arch-bottom'].filter(s=>q(s)),
    inspector:!!q('[data-arch-inspector]')}})()"""

#: Panneau ouvert, ancré sous la barre et dans le canevas ; sa légende ou son état.
POP = """(()=>{const q=s=>document.querySelector(s),p=q('[data-arch-pop-panel]');if(!p)return null;
  const r=p.getBoundingClientRect(),t=q('[data-arch-tools]').getBoundingClientRect(),c=q('[data-arch-canvas]').getBoundingClientRect();
  const snap=ARCH.view.state.snapshot;
  return {id:p.getAttribute('data-arch-pop-panel'),below:r.top>=t.bottom-1,inside:r.left>=c.left-1&&r.right<=c.right+1&&r.bottom<=c.bottom+1,
    expanded:q('[data-arch-pop="'+p.getAttribute('data-arch-pop-panel')+'"]').getAttribute('aria-expanded'),
    legendChannels:document.querySelectorAll('.arch-legend-ch li').length,channels:new Set(snap.connections.map(c=>c.channel)).size,
    health:(q('[data-arch-health]')||{getAttribute:()=>null}).getAttribute('data-arch-health'),voice:!!q('[data-arch-voice]')}})()"""

PANEL = """(()=>{const w=document.querySelector('.bcp-win').getBoundingClientRect(),
  n=document.querySelector('[data-architecture-page] [data-arch-node=core]');const r=n.getBoundingClientRect();
  const ox=Math.max(0,Math.min(w.right,r.right)-Math.max(w.left,r.left)),oy=Math.max(0,Math.min(w.bottom,r.bottom)-Math.max(w.top,r.top));
  return {overlap:ox*oy,inViewport:w.left>=0&&w.top>=0&&w.right<=innerWidth&&w.bottom<=innerHeight,
    marked:[...document.querySelectorAll('.arch-node.cfg')].map(e=>e.getAttribute('data-arch-node')),
    eyebrow:document.querySelector('.bcp-eyebrow').textContent}})()"""

SIZES = [(1672, 941), (1254, 1254), (1280, 800), (1000, 800)]


async def test_the_graph_fills_the_page_with_a_floating_toolbar_and_the_window_marks_its_node(served, tmp_path):
    shots = shots_dir(tmp_path, "architecture-workspace")
    # Une session de navigateur par taille : le plan passe en argument au harnais, de longueur bornée sous Windows.
    for width, height in SIZES:
        out = await drive(served.url, [{"width": width, "height": height, "actions": [
            *VIEWS["architecture"], READY, eval_("new Promise(r=>setTimeout(()=>r(1),400))"), freeze(),
            eval_(REGIONS, "regions"), eval_(OVERFLOW, "overflow"), shot(shots / f"apres-{width}x{height}.jpg"),
            click("[data-arch-pop=state]"), eval_(POP, "state"),
            click("[data-arch-pop=legend]"), eval_(POP, "legend"), shot(shots / f"apres-legende-{width}x{height}.jpg"),
            # Clic dehors (le titre de la page) : le panneau se ferme.
            click("#settingsCategoryTitle"), eval_("ARCH.view.state.pop", "outside"),
            click("[data-arch-pop=manage]"), eval_(POP, "manage"), key("Escape"),
            eval_("[ARCH.view.state.pop,document.activeElement.getAttribute('data-arch-pop'),SET.open]", "escape"),
            *OPEN_CORE, eval_("new Promise(r=>setTimeout(()=>r(1),300))"), freeze(),
            eval_(PANEL, "panel"), eval_(OVERFLOW, "overflow_panel"), shot(shots / f"apres-fenetre-{width}x{height}.jpg"),
            key("Escape"), wait("document.querySelector('.bcp-win')===null"),
            eval_("document.querySelectorAll('.arch-node.cfg').length", "unmarked"),
        ]}])
        assert out["console"] == [], out["console"]
        step = out["steps"][0]
        waits = [a for a in step["actions"] if a.get("a") == "wait"]
        assert all(a["ok"] for a in waits), ((width, height), [a for a in waits if not a["ok"]])
        r = got(step, "regions")
        assert r["fill"] and r["gone"] == [] and not r["inspector"], r
        # Toute la largeur de la page et toute la hauteur restante sous les onglets, rien à faire défiler.
        assert r["canvas"]["w"] >= r["page"]["w"] - 2 and r["canvas"]["t"] > r["tabs"]["b"], r
        assert r["vh"] - 40 <= r["canvas"]["b"] <= r["vh"], ("le graphe descend jusqu'au bas de la fenêtre", (width, height), r)
        assert r["scrollable"] <= 1, ("contenu à la taille de l'écran : rien à faire défiler", (width, height), r)
        assert r["tools"] == ["reload", "manage", "state", "legend"], r
        tb, zb, cv = r["toolsBox"], r["zoomBox"], r["canvas"]
        assert tb["r"] <= cv["r"] and tb["t"] >= cv["t"] and tb["r"] >= cv["r"] - 20, ("barre en haut à droite du graphe", r)
        assert zb["b"] <= cv["b"] and zb["r"] >= cv["r"] - 20 and zb["t"] >= tb["b"], ("zoom en bas à droite, sous la barre", r)
        assert r["dot"] in ("ok", "off", "bad"), r
        assert got(step, "overflow")["page"] == 0 and got(step, "overflow_panel")["page"] == 0, (width, got(step, "overflow"))
        state, legend, manage = got(step, "state"), got(step, "legend"), got(step, "manage")
        assert state["id"] == "state" and state["expanded"] == "true" and state["health"] == r["dot"] and state["voice"], state
        assert legend["id"] == "legend" and legend["legendChannels"] == legend["channels"], legend
        for pop in (state, legend, manage):
            assert pop["below"] and pop["inside"], ((width, height), pop)
        assert got(step, "outside") is None, "un clic dehors ferme le panneau"
        assert got(step, "escape") == [None, "manage", True], "Échap ferme le panneau, rend le focus à son bouton, garde les Réglages"
        p = got(step, "panel")
        assert p["overlap"] == 0 and p["inViewport"], ((width, height), p)
        assert p["marked"] == ["core"] and p["eyebrow"] == "Configuration", p
        assert got(step, "unmarked") == 0


LAYOUT_CALLS = "(()=>({revision:ARCH.view.state.snapshot.revision,layout:ARCH.view.state.layout.revision,positions:Object.keys(ARCH.view.state.layout.positions)}))()"


async def test_reset_layout_is_two_steps_in_the_manage_panel_and_only_writes_an_empty_layout(served):
    actions = [
        *VIEWS["architecture"], READY, click("[data-arch-pop=manage]"),
        eval_("document.querySelector('[data-arch-act=layout-reset]').disabled", "disabled_before"),
        eval_("document.querySelector('[data-architecture-page] [data-arch-node=core]').focus();1"),
        key("ArrowRight", shift=True),
        wait("!!document.querySelector('[data-arch-layout-note].ok')", 8000),
        eval_(LAYOUT_CALLS, "moved"),
        # Le panneau Gestion est resté ouvert pendant le déplacement au clavier.
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


async def test_reload_rereads_the_architecture_and_says_so_in_a_short_message(served):
    out = await drive(served.url, [{"width": 1280, "height": 800, "actions": [
        *VIEWS["architecture"], READY, click("[data-arch-act=reload]"),
        wait("!!document.querySelector('[data-arch-toast]')", 8000),
        eval_("({tone:document.querySelector('[data-arch-toast]').getAttribute('data-arch-toast'),text:document.querySelector('[data-arch-toast]').textContent})", "toast"),
        click("[data-arch-act=toast-close]"), eval_("!!document.querySelector('[data-arch-toast]')", "closed"),
    ]}])
    step = out["steps"][0]
    assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait")
    toast = got(step, "toast")
    assert toast["tone"] == "ok" and "Architecture relue" in toast["text"], toast
    assert got(step, "closed") is False
    reads = [r for r in out["requests"] if r["method"] == "GET" and r["path"] == "/api/architecture"]
    assert len(reads) >= 2, "« Relire » relit vraiment le snapshot"
    assert out["console"] == [], out["console"]


#: Points d'entrée de la page encore atteignables (centre de l'élément) et recouvrement du nœud configuré.
REACHABLE = """(()=>{const hit=sel=>{const e=document.querySelector(sel);if(!e)return 'absent';const r=e.getBoundingClientRect();
    const top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!top&&e.contains(top)};
  const w=document.querySelector('.bcp-win').getBoundingClientRect(),
    n=document.querySelector('[data-architecture-page] [data-arch-node=core]').getBoundingClientRect();
  const ox=Math.max(0,Math.min(w.right,n.right)-Math.max(w.left,n.left)),oy=Math.max(0,Math.min(w.bottom,n.bottom)-Math.max(w.top,n.top));
  return {back:hit('#settingsBack'),close:hit('#closeModal'),tab:hit('#modalTabs [aria-selected=true]'),
    title:hit('#settingsCategoryTitle'),rail:!!document.getElementById('settingsCategories').getClientRects().length,
    overlap:ox*oy,width:Math.round(w.width),height:Math.round(w.height),inViewport:w.left>=0&&w.top>=0&&w.right<=innerWidth&&w.bottom<=innerHeight,
    gap:Math.round(Math.min(Math.abs(w.left-n.right),Math.abs(n.left-w.right),Math.abs(w.top-n.bottom),Math.abs(n.top-w.bottom)))}})()"""


async def test_the_brain_window_opens_beside_its_node_and_leaves_the_page_chrome_reachable(served):
    sizes = [(1672, 941), (1254, 1254), (1280, 800)]
    out = await drive(served.url, [{"width": w, "height": h, "actions": [
        *VIEWS["architecture"], READY, *OPEN_CORE, eval_("new Promise(r=>setTimeout(()=>r(1),300))"), eval_(REACHABLE, "reach")]}
        for w, h in sizes])
    assert out["console"] == [], out["console"]
    for size, step in zip(sizes, out["steps"]):
        assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait"), size
        r = got(step, "reach")
        # × et ← (fixes), le titre et l'onglet actif restent atteignables ; pas de rail.
        assert r["back"] is True and r["close"] is True and r["tab"] is True and r["title"] is True, (size, r)
        assert r["rail"] is False, (size, r)
        assert r["overlap"] == 0 and r["inViewport"], (size, r)
        assert r["gap"] <= 40, ("la fenêtre s'ouvre près du nœud", size, r)
        assert r["width"] >= 340 and r["height"] >= 300, ("assez grande pour être utile", size, r)
