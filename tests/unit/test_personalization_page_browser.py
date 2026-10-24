"""Page Personnalisation des Réglages, dans un vrai Chrome sans tête (refonte page par page, 2026-10-23 ; composition
de la maquette 01 sur les primitives partagées, Slice 02 de refonte-ui-settings, 2026-10-24).

Un VRAI Control Center isolé (fixture `served` de `test_wake_word_settings_browser.py`) sert la page. Ce que ce
fichier prouve :

- la carte Personnalisation du hub ouvre la page (pas le shell) ; aucune citation ; le profil actif est en haut à
  droite ; trois colonnes de panneaux `.set-panel` (deux sous 1240 px de page, une sous 640 px) dont l'enveloppe est
  un rectangle, sans débordement, à plusieurs largeurs ; à 1672×941 (maquette) tout tient dans la fenêtre ;
- la page n'a plus de doublon des primitives (`.perso-card`, `.perso-switch`, `.perso-seg`…) ;
- chaque contrôle écrit le vrai réglage (`agent_behavior`, `voice_stack_settings`, `agenda_reminders`) ; les curseurs à
  crans écrivent les choix fermés du serveur, au clavier aussi, et « Hériter » se rétablit ;
- un profil se crée, se choisit (ses préférences et sa voix reviennent) et se supprime ;
- clavier : le panneau des profils (`.set-float`) prend le focus, Échap le replie puis ferme ; clic extérieur ; le fil
  d'Ariane ramène au hub ; une ligne des réglages détaillés ouvre sa section dans le shell ;
- états : lecture refusée (message du serveur + Réessayer), chargement (avec échéance), champs désactivés ; captures
  gardées dans `JARVIS_BROWSER_SHOTS` quand la variable est posée.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

from tests.unit.settings_visual import OVERFLOW, freeze, shot, shots_dir, stub
from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, type_in, wait  # noqa: F401

OPEN_PAGE = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), click("#openSettings"),
    wait("!!document.querySelector('#settingsHubGrid [data-hub-category=voice_audio]')"),
    click("#settingsHubGrid [data-hub-category=voice_audio]"),
    wait("!!document.querySelector('#persoGrid .perso-persona')", 10000),
]

#: Géométrie : chaque panneau dans l'enveloppe de la grille, bords extérieurs alignés sur elle, pas de défilement horizontal.
GEOMETRY = """(()=>{const g=document.getElementById('persoGrid').getBoundingClientRect(),page=document.getElementById('settingsPerso');
  const cards=[...document.querySelectorAll('#persoGrid .set-panel')].map(c=>{const r=c.getBoundingClientRect();
    return {id:c.id,l:Math.round(r.left),r:Math.round(r.right),t:Math.round(r.top),b:Math.round(r.bottom),w:Math.round(r.width),h:Math.round(r.height)}});
  const near=(a,b)=>Math.abs(a-b)<=1;
  return {cards,inside:cards.every(c=>c.l>=g.left-1&&c.r<=g.right+1&&c.t>=g.top-1&&c.b<=g.bottom+1),
    leftEdge:cards.some(c=>near(c.l,g.left)),rightEdge:cards.some(c=>near(c.r,g.right)),bottomEdge:cards.filter(c=>near(c.b,g.bottom)).length,
    columns:[...new Set(cards.map(c=>c.l))].length,
    colBottoms:[...document.querySelectorAll('#persoGrid>.perso-col')].map(c=>Math.round(c.lastElementChild.getBoundingClientRect().bottom)),
    hscroll:page.scrollWidth>page.clientWidth+1||document.documentElement.scrollWidth>innerWidth+1,
    fits:g.bottom<=innerHeight,bottom:Math.round(g.bottom),
    quote:/Chaque intelligence artificielle|refl[eé]ter la personne/i.test(page.textContent),
    view:overlay.dataset.view,shell:getComputedStyle(document.getElementById('settingsShell')).display,
    profile:(()=>{const b=document.getElementById('persoProfileBtn');if(!b)return null;const r=b.getBoundingClientRect();
      return {name:b.textContent.trim(),gridRight:Math.round(g.right-r.right),below:Math.round(g.top-r.bottom),avatar:!!b.querySelector('.set-medallion')}})()}})()"""

#: Doublons des primitives que la Slice 02 a supprimés : ni dans la feuille, ni dans le DOM de la page.
LEGACY = """(()=>{const css=[...document.styleSheets].flatMap(s=>{try{return [...s.cssRules].map(r=>r.cssText)}catch{return []}}).join('\\n');
  const gone=['perso-card','perso-switch','perso-seg','perso-preset','perso-frame','perso-avatar','perso-mini','perso-select','perso-load-error','perso-title','perso-lead','perso-badge'];
  return {css:gone.filter(c=>new RegExp('\\\\.'+c+'(?![-\\\\w])').test(css)),dom:gone.filter(c=>document.querySelector('#settingsPerso .'+c))}})()"""


async def test_la_carte_ouvre_une_page_rectangulaire_sans_citation(served):
    sizes = [(1920, 1080), (1672, 941), (1440, 900), (1280, 800), (1000, 800), (420, 860)]
    out = await drive(served.url, [{"width": w, "height": h, "actions": [
        *OPEN_PAGE, eval_(GEOMETRY, "geo"), eval_(LEGACY, "legacy")]}
        for w, h in sizes])
    assert out["console"] == [], out["console"]
    for (w, h), step in zip(sizes, out["steps"]):
        geo = got(step, "geo")
        assert geo["view"] == "perso" and geo["shell"] == "none", (w, geo)
        assert len(geo["cards"]) == 5 and geo["inside"] and not geo["hscroll"], (w, geo)
        assert not geo["quote"], w
        assert geo["profile"] and geo["profile"]["avatar"] and "Jarvis Classique" in geo["profile"]["name"], (w, geo)
        assert got(step, "legacy") == {"css": [], "dom": []}, w
        if w >= 1000:
            assert geo["leftEdge"] and geo["rightEdge"] and geo["bottomEdge"] >= 1, (w, geo)
            # les colonnes côte à côte finissent à la même hauteur (Voix | Personnalité [| Proactivité])
            side = geo["colBottoms"] if geo["columns"] == 3 else geo["colBottoms"][:2]
            assert max(side) - min(side) <= 1, (w, geo["colBottoms"])
            # en haut à droite : son bord droit est celui de la grille, au-dessus d'elle
            assert abs(geo["profile"]["gridRight"]) <= 1 and geo["profile"]["below"] > 0, (w, geo)
        expected = 3 if w >= 1366 else 2 if w >= 1000 else 1
        assert geo["columns"] == expected, (w, geo["columns"])
        if (w, h) == (1672, 941):  # la fenêtre de la maquette : toute la grille est visible sans défiler
            assert geo["fits"], geo


def _set(selector: str, value: str) -> dict:
    return eval_(f"""(()=>{{const el=document.querySelector({json.dumps(selector)});el.value={json.dumps(value)};
      el.dispatchEvent(new Event('input',{{bubbles:true}}));el.dispatchEvent(new Event('change',{{bubbles:true}}));return true}})()""")


async def test_chaque_controle_ecrit_le_vrai_reglage(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN_PAGE,
        _set("#persoTrait_response_verbosity", "2"),
        wait("document.querySelector('[data-card-status=persona]').dataset.kind==='ok'"),
        click("[data-perso-preset=concise]"),
        wait("document.querySelector('[data-perso-preset=concise]').checked"),
        wait("document.querySelector('[data-card-status=presets]').dataset.kind==='ok'"),
        type_in("#persoInstructions", "Donnez des exemples concrets."),
        eval_("document.getElementById('persoInstructions-count').textContent", "count"),
        eval_("(document.getElementById('persoInstructions').blur(),1)"),
        wait("document.querySelector('[data-card-status=persona]').dataset.kind==='ok'"),
        _set("#persoVoice", "alloy"),
        wait("document.querySelector('[data-card-status=voice]').dataset.kind==='ok'"),
        click("[data-perso-agenda-switch]"),
        wait("document.querySelector('[data-perso-agenda-switch]').getAttribute('aria-checked')==='false'"),
        wait("document.querySelector('[data-card-status=proactive]').dataset.kind==='ok'"),
        eval_("[...document.querySelectorAll('[data-perso-agenda]')].every(i=>i.disabled)", "disabled"),
    ]}])
    assert out["console"] == [], out["console"]
    assert got(out["steps"][0], "disabled") is True
    assert got(out["steps"][0], "count") == "29/1000"
    final = served.stored()
    assert final["agent_behavior"] == {"response_verbosity": "concise", "politeness_formality": "direct",
                                       "custom_instructions": "Donnez des exemples concrets."}
    assert final["voice_stack_settings"]["openai_realtime"]["voice"] == "alloy"
    assert final["agenda_reminders"]["enabled"] is False
    bodies = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/settings"]
    # Des charges partielles : la page n'envoie que ce qu'elle a changé, jamais le brouillon complet du shell.
    assert {"cli": {"behavior": {"response_verbosity": "detailed"}}} in bodies
    assert all(set(b) <= {"cli", "voice", "agenda_reminders"} for b in bodies), bodies


#: État d'un curseur à crans : valeur, texte affiché et accessible, « Hériter », focus, bornes.
TRAIT = """(id=>{const r=document.getElementById('persoTrait_'+id),row=r.closest('.perso-trait'),b=row.querySelector('[data-perso-inherit]');
  return {value:r.value,text:document.getElementById(r.id+'-hint').textContent,valuetext:r.getAttribute('aria-valuetext'),
    inherit:row.hasAttribute('data-inherit'),reset:!b.disabled,focus:document.activeElement===r,ends:[...row.querySelectorAll('.set-range-end')].map(e=>e.textContent)}})"""


async def test_les_curseurs_a_crans_ecrivent_les_choix_du_serveur(served):
    out = await drive(served.url, [{"width": 1672, "height": 941, "actions": [
        *OPEN_PAGE,
        eval_(f"{TRAIT}('politeness_formality')", "before"),
        _set("#persoTrait_politeness_formality", "2"),
        wait("!document.querySelector('#persoTrait_politeness_formality').closest('.perso-trait').hasAttribute('data-inherit')"),
        eval_(f"{TRAIT}('politeness_formality')", "formal"),
        click("[data-perso-inherit=politeness_formality]"),
        wait("document.querySelector('#persoTrait_politeness_formality').closest('.perso-trait').hasAttribute('data-inherit')"),
        eval_(f"{TRAIT}('politeness_formality')", "inherit"),
        # Clavier : une flèche choisit le cran voisin et l'écrit.
        eval_("(document.getElementById('persoTrait_response_verbosity').focus(),1)"),
        key("ArrowRight"),
        wait("!document.querySelector('#persoTrait_response_verbosity').closest('.perso-trait').hasAttribute('data-inherit')"),
        wait("document.querySelector('[data-card-status=persona]').dataset.kind==='ok'"),
        eval_(f"{TRAIT}('response_verbosity')", "keyboard"),
    ]}])
    assert out["console"] == [], out["console"]
    step = out["steps"][0]
    before = got(step, "before")
    assert before["inherit"] and before["text"] == "Hériter" and not before["reset"], before
    assert before["ends"] == ["Direct", "Formel"], before
    formal = got(step, "formal")
    assert formal["value"] == "2" and formal["text"] == formal["valuetext"] == "Formel" and formal["reset"], formal
    assert got(step, "inherit")["inherit"] and got(step, "inherit")["focus"], got(step, "inherit")
    keyboard = got(step, "keyboard")
    assert keyboard["valuetext"] == "Détaillée" and keyboard["focus"], keyboard
    assert served.stored()["agent_behavior"] == {"response_verbosity": "detailed", "politeness_formality": "inherit"}


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
        wait("document.querySelector('[data-perso-preset=formal]').checked"),
        _set("#persoVoice", "sage"),
        wait("document.querySelector('[data-card-status=voice]').dataset.kind==='ok'"),
        click("#persoProfileBtn"),
        click("[data-perso-profile=classic]"),
        wait("document.getElementById('persoProfileBtn').textContent.includes('Jarvis Classique')"),
        eval_("({inherit:document.getElementById('persoTrait_response_verbosity').closest('.perso-trait').hasAttribute('data-inherit'),"
              "voice:document.getElementById('persoVoice').value,menu:!document.getElementById('persoProfileMenu').hidden})", "classic"),
        click("#persoProfileBtn"),
        click("[data-perso-delete=decontracte]"),
        wait("!document.querySelector('[data-perso-profile=decontracte]')"),
    ]}])
    assert out["console"] == [], out["console"]
    assert got(out["steps"][0], "classic") == {"inherit": True, "voice": "cedar", "menu": False}
    block = served.stored()["personalization_profiles"]
    assert block["active"] == "classic" and [p["id"] for p in block["profiles"]] == ["classic"]
    assert served.stored()["voice_stack_settings"]["openai_realtime"]["voice"] == "cedar"


async def test_clavier_echap_fil_d_ariane_et_reglages_detailles(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE,
            click("#persoProfileBtn"), wait("!document.getElementById('persoProfileMenu').hidden"),
            eval_("({role:document.getElementById('persoProfileMenu').getAttribute('role'),expanded:document.getElementById('persoProfileBtn').getAttribute('aria-expanded'),"
                  "focus:document.activeElement.dataset.persoProfile||null})", "opened"),
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
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE,
            click("#persoProfileBtn"), wait("!document.getElementById('persoProfileMenu').hidden"),
            click("#persoCard_voice-title"),
            eval_("({menu:!document.getElementById('persoProfileMenu').hidden,expanded:document.getElementById('persoProfileBtn').getAttribute('aria-expanded'),view:overlay.dataset.view})", "outside"),
        ]},
    ])
    assert out["console"] == [], out["console"]
    assert got(out["steps"][0], "opened") == {"role": "dialog", "expanded": "true", "focus": "classic"}
    assert got(out["steps"][0], "esc1") == {"menu": False, "focus": "persoProfileBtn", "view": "perso"}
    assert got(out["steps"][0], "esc2") == {"open": False, "view": None}
    assert got(out["steps"][1], "hub")["view"] == "hub"
    rows = got(out["steps"][2], "rows")
    assert "agent_behavior" not in rows and {"conversation", "microphone_sound", "wake_word", "theme_scene"} <= set(rows)
    assert got(out["steps"][2], "shell") == {"view": "shell", "section": "microphone_sound"}
    assert got(out["steps"][3], "outside") == {"menu": False, "expanded": "false", "view": "perso"}


#: Ce que dit la grille : état (`data-perso-state`), message, bouton Réessayer.
STATE = """(()=>{const s=document.querySelector('#persoGrid [data-perso-state]');
  return s?{state:s.dataset.persoState,text:s.textContent.trim(),retry:!!s.querySelector('[data-perso-retry]'),busy:document.getElementById('persoGrid').getAttribute('aria-busy')}:null})()"""


async def test_etats_erreur_chargement_et_desactive(served, tmp_path):
    shots = shots_dir(tmp_path)
    refused = stub("/api/personalization/profiles", {"error": "Profils illisibles : fichier de réglages abîmé (test)."}, status=500)
    out = await drive(served.url, [
        # Lecture refusée : le message du serveur et Réessayer.
        {"width": 1280, "height": 800, "stubs": [refused], "actions": [
            *OPEN_PAGE[:-1], wait("!!document.querySelector('#persoGrid [data-perso-state=error]')", 10000),
            eval_(STATE, "error"), freeze(), eval_(OVERFLOW, "overflow"), shot(shots / "state-error-1280x800.jpg"),
        ]},
        # Chargement : une lecture qui ne répond pas encore (l'échéance la clôt au bout de DEADLINE_MS).
        {"width": 1280, "height": 800, "actions": [
            *OPEN_PAGE[:-2], eval_("(window.api=()=>new Promise(()=>{}),1)"),
            click("#settingsHubGrid [data-hub-category=voice_audio]"),
            wait("!!document.querySelector('#persoGrid [data-perso-state=loading]')"),
            eval_(STATE, "loading"), eval_("JarvisPersonalization.DEADLINE_MS", "deadline"), freeze(), shot(shots / "state-loading-1280x800.jpg"),
        ]},
        # Désactivé : rappels coupés, champs inertes ; panneau des profils ouvert (comme la maquette).
        {"width": 1672, "height": 941, "actions": [
            *OPEN_PAGE,
            click("[data-perso-agenda-switch]"),
            wait("[...document.querySelectorAll('[data-perso-agenda]')].every(i=>i.disabled)"),
            click("#persoProfileBtn"), wait("!document.getElementById('persoProfileMenu').hidden"),
            eval_("getComputedStyle(document.getElementById('persoAgenda_morning_time')).cursor", "cursor"),
            freeze(), eval_(OVERFLOW, "overflow"), shot(shots / "after-profiles-disabled-1672x941.jpg"),
        ]},
    ])
    error = got(out["steps"][0], "error")
    assert error["state"] == "error" and "fichier de réglages abîmé (test)" in error["text"] and error["retry"], error
    assert got(out["steps"][0], "overflow")["page"] == 0
    loading = got(out["steps"][1], "loading")
    assert loading["state"] == "loading" and loading["busy"] == "true" and "15 s" in loading["text"], loading
    assert got(out["steps"][1], "deadline") == 15000
    assert got(out["steps"][2], "cursor") == "not-allowed"
    assert got(out["steps"][2], "overflow")["page"] == 0


async def test_captures_de_la_maquette(served, tmp_path):
    """Captures « après » à la fenêtre de la maquette, plus étroite et étroite : sans débordement horizontal."""

    shots = shots_dir(tmp_path)
    sizes = [(1672, 941), (1280, 800), (600, 900)]
    out = await drive(served.url, [{"width": w, "height": h, "actions": [
        *OPEN_PAGE, eval_("new Promise(r=>setTimeout(()=>r(1),400))"), freeze(), eval_(OVERFLOW, "overflow"),
        shot(shots / f"after-perso-{w}x{h}.jpg")]} for w, h in sizes])
    assert out["console"] == [], out["console"]
    for (w, _h), step in zip(sizes, out["steps"]):
        overflow = got(step, "overflow")
        assert overflow["page"] == 0 and not any(overflow["containers"].values()), (w, overflow)


#: `api` de la page remplacé en place (déclaration de fonction du `<script>`, lue par le module à chaque appel) :
#: un envoi qui ne répond jamais, ou seulement l'envoi des instructions retardé de 2,5 s.
SILENT_POST = "(()=>{const real=window.api;window.api=(p,o)=>o&&o.method==='POST'?new Promise(()=>{}):real(p,o);return 1})()"
SLOW_TEXT = """(()=>{const real=window.api;window.api=(p,o)=>o&&o.method==='POST'&&String(o.body).includes('custom_instructions')
  ?new Promise(r=>setTimeout(r,2500)).then(()=>real(p,o)):real(p,o);return 1})()"""
#: Les contrôles que le piège de Tab de la page parcourt (même filtre que `control_center_personalization.js`).
TAB_ENDS = """(()=>{const page=document.getElementById('settingsPerso');
  const items=[...page.querySelectorAll('button,select,textarea,input,[tabindex]:not([tabindex="-1"])')]
    .filter(el=>!el.disabled&&el.offsetParent!==null&&!(el.type==='radio'&&!el.checked&&page.querySelector(`input[name="${el.name}"]:checked`)));
  window.__ends=[items[0],items[items.length-1]];return items.length})()"""


async def test_refus_echeance_brouillon_en_vol_et_piege_tab(served):
    """Lot de finitions S02 repris en Slice 07 : un refus remet la valeur enregistrée ; un envoi sans réponse se clôt à
    l'échéance et la page relit les réglages ; un texte d'instructions en cours d'envoi survit au rendu d'une autre
    carte (course corrigée) ; Tab et Maj+Tab bouclent dans la page."""
    refused = stub("/api/settings", {"error": "Refusé par le serveur (test)."}, method="POST", status=400)
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "stubs": [refused], "actions": [
            *OPEN_PAGE,
            eval_("document.getElementById('persoTrait_response_verbosity').value", "before"),
            _set("#persoTrait_response_verbosity", "0"),
            wait("document.querySelector('[data-card-status=persona]').dataset.kind==='error'"),
            eval_("[document.getElementById('persoTrait_response_verbosity').value,document.querySelector('[data-card-status=persona]').textContent]", "refused"),
        ]},
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE, eval_(SILENT_POST),
            _set("#persoVoice", "alloy"),
            wait("document.querySelector('[data-card-status=voice]').dataset.kind==='busy'"),
            wait("/Valeurs relues/.test(document.querySelector('[data-card-status=voice]').textContent)", 20000),
            eval_("[document.querySelector('[data-card-status=voice]').textContent,document.getElementById('persoVoice').value]", "late"),
        ]},
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE, eval_(SLOW_TEXT),
            type_in("#persoInstructions", "Texte en cours d'envoi."),
            eval_("(document.getElementById('persoInstructions').blur(),1)"),
            click("[data-perso-preset=concise]"),
            wait("document.querySelector('[data-card-status=presets]').dataset.kind==='ok'"),
            eval_("document.getElementById('persoInstructions').value", "during"),
            wait("document.querySelector('[data-card-status=persona]').dataset.kind==='ok'", 8000),
            eval_("document.getElementById('persoInstructions').value", "after"),
        ]},
        {"width": 1440, "height": 900, "actions": [
            *OPEN_PAGE, eval_(TAB_ENDS, "count"),
            eval_("(window.__ends[1].focus(),1)"), key("Tab"),
            eval_("document.activeElement===window.__ends[0]", "wrap_forward"),
            key("Tab", shift=True),
            eval_("document.activeElement===window.__ends[1]", "wrap_back"),
        ]},
    ])
    steps = out["steps"]
    for step in steps:
        assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait"), [a for a in step["actions"] if a.get("a") == "wait" and not a["ok"]]
    value, text = got(steps[0], "refused")
    assert value == got(steps[0], "before") and "Refusé par le serveur (test)." in text, (value, text)
    late, voice = got(steps[1], "late")
    assert "pas de réponse du Control Center après 15 s" in late and voice != "alloy", (late, voice)
    assert got(steps[2], "during") == "Texte en cours d'envoi.", "le texte en vol survit au rendu des préférences rapides"
    assert got(steps[2], "after") == "Texte en cours d'envoi."
    assert served.stored()["agent_behavior"]["custom_instructions"] == "Texte en cours d'envoi."
    assert got(steps[3], "count") > 10 and got(steps[3], "wrap_forward") is True and got(steps[3], "wrap_back") is True
    # Seuls les refus voulus du test parlent en console (avertissements journalisés de la page).
    assert all("personalization" in m.get("text", str(m)) for m in out["console"]), out["console"]
