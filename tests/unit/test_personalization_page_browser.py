"""Page Personnalisation des Réglages, dans un vrai Chrome sans tête (refonte page par page, 2026-10-23).

Un VRAI Control Center isolé (fixture `served` de `test_wake_word_settings_browser.py`) sert la page. Ce que ce
fichier prouve :

- la carte Personnalisation du hub ouvre la page (pas le shell) ; aucune citation ; le profil actif est en haut à
  droite ; cinq cartes de spans différents dont l'enveloppe est un rectangle, sans débordement, à plusieurs largeurs ;
- chaque contrôle écrit le vrai réglage (`agent_behavior`, `voice_stack_settings`, `agenda_reminders`) ;
- un profil se crée, se choisit (ses préférences et sa voix reviennent) et se supprime ;
- clavier : Échap replie le panneau des profils puis ferme ; le fil d'Ariane ramène au hub ; une ligne des
  réglages détaillés ouvre sa section dans le shell.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

from tests.unit.test_wake_word_settings_browser import _shots, click, drive, eval_, got, served, type_in, wait, key  # noqa: F401

OPEN_PAGE = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), click("#openSettings"),
    wait("!!document.querySelector('#settingsHubGrid [data-hub-category=voice_audio]')"),
    click("#settingsHubGrid [data-hub-category=voice_audio]"),
    wait("!!document.querySelector('#persoGrid .perso-persona')", 10000),
]

#: Géométrie : chaque carte dans l'enveloppe de la grille, bords extérieurs alignés sur elle, pas de défilement horizontal.
GEOMETRY = """(()=>{const g=document.getElementById('persoGrid').getBoundingClientRect(),page=document.getElementById('settingsPerso');
  const cards=[...document.querySelectorAll('#persoGrid>.perso-card')].map(c=>{const r=c.getBoundingClientRect();
    return {id:c.id,l:Math.round(r.left),r:Math.round(r.right),t:Math.round(r.top),b:Math.round(r.bottom),w:Math.round(r.width),h:Math.round(r.height)}});
  const near=(a,b)=>Math.abs(a-b)<=1;
  return {cards,inside:cards.every(c=>c.l>=g.left-1&&c.r<=g.right+1&&c.t>=g.top-1&&c.b<=g.bottom+1),
    leftEdge:cards.some(c=>near(c.l,g.left)),rightEdge:cards.some(c=>near(c.r,g.right)),bottomEdge:cards.filter(c=>near(c.b,g.bottom)).length,
    widths:[...new Set(cards.map(c=>c.w))].length,
    hscroll:page.scrollWidth>page.clientWidth+1||document.documentElement.scrollWidth>innerWidth+1,
    quote:/Chaque intelligence artificielle|refl[eé]ter la personne/i.test(page.textContent),
    view:overlay.dataset.view,shell:getComputedStyle(document.getElementById('settingsShell')).display,
    profile:(()=>{const b=document.getElementById('persoProfileBtn');if(!b)return null;const r=b.getBoundingClientRect();
      return {name:b.textContent.trim(),gridRight:Math.round(g.right-r.right),below:Math.round(g.top-r.bottom),avatar:!!b.querySelector('.perso-avatar')}})()}})()"""


async def test_la_carte_ouvre_une_page_rectangulaire_sans_citation(served, tmp_path):
    shots = _shots(tmp_path)
    sizes = [(1920, 1080), (1440, 900), (1366, 768), (1000, 800), (420, 860)]
    out = await drive(served.url, [{"width": w, "height": h, "actions": [
        *OPEN_PAGE, eval_(GEOMETRY, "geo"), {"a": "shot", "path": str(shots / f"perso-{w}x{h}.png")}]} for w, h in sizes])
    assert out["console"] == [], out["console"]
    for (w, _h), step in zip(sizes, out["steps"]):
        geo = got(step, "geo")
        assert geo["view"] == "perso" and geo["shell"] == "none", (w, geo)
        assert len(geo["cards"]) == 5 and geo["inside"] and not geo["hscroll"], (w, geo)
        assert not geo["quote"], w
        assert geo["profile"] and geo["profile"]["avatar"] and "Jarvis Classique" in geo["profile"]["name"], (w, geo)
        if w >= 1000:
            assert geo["leftEdge"] and geo["rightEdge"] and geo["bottomEdge"] >= 2, (w, geo)
            assert geo["widths"] >= 2, (w, geo)  # des cartes de tailles différentes
        if w >= 1000:  # en haut à droite : son bord droit est celui de la grille, au-dessus d'elle
            assert abs(geo["profile"]["gridRight"]) <= 1 and geo["profile"]["below"] > 0, (w, geo)


def _set(selector: str, value: str) -> dict:
    return eval_(f"""(()=>{{const el=document.querySelector({json.dumps(selector)});el.value={json.dumps(value)};
      el.dispatchEvent(new Event('change',{{bubbles:true}}));return true}})()""")


async def test_chaque_controle_ecrit_le_vrai_reglage(served):
    stored = lambda: served.stored()  # noqa: E731
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN_PAGE,
        click("#persoCard_persona input[name=perso_response_verbosity][value=detailed]"),
        wait("document.querySelector('[data-card-status=persona]').dataset.kind==='ok'"),
        click("[data-perso-preset=concise]"),
        wait("document.querySelector('[data-perso-preset=concise]').getAttribute('aria-pressed')==='true'"),
        type_in("#persoInstructions", "Donnez des exemples concrets."),
        eval_("(document.getElementById('persoInstructions').blur(),1)"),
        wait("document.querySelector('[data-card-status=persona]').dataset.kind==='ok'"),
        _set("#persoVoice", "alloy"),
        wait("document.querySelector('[data-card-status=voice]').dataset.kind==='ok'"),
        click("[data-perso-agenda-switch]"),
        wait("document.querySelector('[data-perso-agenda-switch]').getAttribute('aria-checked')==='false'"),
        eval_("[...document.querySelectorAll('[data-perso-agenda]')].every(i=>i.disabled)", "disabled"),
    ]}])
    assert out["console"] == [], out["console"]
    assert got(out["steps"][0], "disabled") is True
    final = stored()
    assert final["agent_behavior"] == {"response_verbosity": "concise", "politeness_formality": "direct",
                                       "custom_instructions": "Donnez des exemples concrets."}
    assert final["voice_stack_settings"]["openai_realtime"]["voice"] == "alloy"
    assert final["agenda_reminders"]["enabled"] is False
    bodies = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/settings"]
    # Des charges partielles : la page n'envoie que ce qu'elle a changé, jamais le brouillon complet du shell.
    assert {"cli": {"behavior": {"response_verbosity": "detailed"}}} in bodies
    assert all(set(b) <= {"cli", "voice", "agenda_reminders"} for b in bodies), bodies


async def test_un_profil_se_cree_se_choisit_et_se_supprime(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN_PAGE,
        click("#persoProfileBtn"),
        wait("!document.getElementById('persoProfileMenu').hidden"),
        click("[data-perso-create]"),
        type_in("#persoProfileName", "Décontracté"),
        key("Enter"),
        wait("document.getElementById('persoProfileBtn').textContent.includes('Décontracté')"),
        click("[data-perso-preset=formal]"),
        wait("document.querySelector('[data-perso-preset=formal]').getAttribute('aria-pressed')==='true'"),
        _set("#persoVoice", "sage"),
        wait("document.querySelector('[data-card-status=voice]').dataset.kind==='ok'"),
        click("#persoProfileBtn"),
        click("[data-perso-profile=classic]"),
        wait("document.getElementById('persoProfileBtn').textContent.includes('Jarvis Classique')"),
        eval_("({verbosity:document.querySelector('input[name=perso_response_verbosity]:checked').value,voice:document.getElementById('persoVoice').value})", "classic"),
        click("#persoProfileBtn"),
        click("[data-perso-delete=decontracte]"),
        wait("!document.querySelector('[data-perso-profile=decontracte]')"),
    ]}])
    assert out["console"] == [], out["console"]
    assert got(out["steps"][0], "classic") == {"verbosity": "inherit", "voice": "cedar"}
    block = served.stored()["personalization_profiles"]
    assert block["active"] == "classic" and [p["id"] for p in block["profiles"]] == ["classic"]
    assert served.stored()["voice_stack_settings"]["openai_realtime"]["voice"] == "cedar"


async def test_clavier_echap_fil_d_ariane_et_reglages_detailles(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE,
            click("#persoProfileBtn"), wait("!document.getElementById('persoProfileMenu').hidden"),
            key("Escape"),
            eval_("({menu:!document.getElementById('persoProfileMenu').hidden,focus:document.activeElement.id,view:overlay.dataset.view})", "esc1"),
            key("Escape"),
            eval_("({open:overlay.classList.contains('open'),view:overlay.dataset.view||null})", "esc2"),
        ]},
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE, click("#persoCrumbHub"),
            eval_("({view:overlay.dataset.view,focus:document.activeElement.dataset.hubCategory||null})", "hub"),
        ]},
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE,
            eval_("[...document.querySelectorAll('[data-perso-open]')].map(b=>b.dataset.persoOpen)", "rows"),
            click("[data-perso-open=microphone_sound]"),
            wait("!!document.getElementById('voiceSection_microphone_sound')", 10000),
            eval_("({view:overlay.dataset.view,section:SET.section})", "shell"),
        ]},
    ])
    assert out["console"] == [], out["console"]
    assert got(out["steps"][0], "esc1") == {"menu": False, "focus": "persoProfileBtn", "view": "perso"}
    assert got(out["steps"][0], "esc2") == {"open": False, "view": None}
    assert got(out["steps"][1], "hub")["view"] == "hub"
    rows = got(out["steps"][2], "rows")
    assert "agent_behavior" not in rows and {"conversation", "microphone_sound", "wake_word", "theme_scene"} <= set(rows)
    assert got(out["steps"][2], "shell") == {"view": "shell", "section": "microphone_sound"}
