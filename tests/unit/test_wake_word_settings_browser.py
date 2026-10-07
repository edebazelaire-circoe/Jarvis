"""La section « Mot d'éveil » des Réglages, mesurée dans un vrai navigateur (Slice 07).

On ne lit rien : un VRAI Control Center (instance isolée : runtime temporaire,
port libre, aucun lien avec le JARVIS vivant) est servi, Chrome sans tête le
charge, et le harnais CDP clique, tape et appuie sur de vraies touches. Ce que
le fichier prouve :

- la section existe, juste après « Voix », avec ses défauts (désactivé) ;
- enregistrer écrit le fichier de réglages du runtime temporaire par la route
  et par elle seule, affiche le bandeau « Redémarrage de Voice requis », et le
  rechargement relit les valeurs ;
- une valeur refusée affiche son code traduit, ne change rien et GARDE la
  saisie ;
- un bloc d'une version étrangère désactive l'enregistrement ;
- lisible dans les deux thèmes de la page (aucun thème clair n'existe : les
  deux thèmes, « Circuit imprimé » et « Cosmos », sont sombres) ;
- tout se fait au clavier, avec des noms accessibles et un focus visible ;
- `prefers-reduced-motion` arrête vraiment l'animation du bandeau ;
- l'état du détecteur est le DERNIER événement du journal, daté, jamais une
  mesure en direct.

Aucun micro n'est ouvert. Le test se saute proprement si Chrome ou node est
absent.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

from aiohttp import web
import pytest

from jarvis.runtime import control_center as cc
from jarvis.runtime.control_center import ControlCenter

HARNESS = Path(__file__).parent / "_wake_word_settings_browser.mjs"

CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)

TAB_LABEL = "Mot d\u2019éveil"


def _chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    pytest.skip("Chrome absent")


def _shots(tmp_path: Path) -> Path:
    target = Path(os.environ.get("JARVIS_BROWSER_SHOTS") or tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    return target


class Served:
    def __init__(self, url: str, runtime: Path, control: ControlCenter) -> None:
        self.url, self.runtime, self.control = url, runtime, control

    @property
    def settings_file(self) -> Path:
        return self.control.settings_path

    def stored(self) -> dict:
        return json.loads(self.settings_file.read_text(encoding="utf-8"))


@pytest.fixture
async def served(tmp_path, monkeypatch):
    """Un Control Center isolé : runtime temporaire, bouclage, port choisi par le système."""

    for name in ("OPENAI_API_KEY", "PORCUPINE_ACCESS_KEY", "JARVIS_VOICE_ARCH"):
        monkeypatch.delenv(name, raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    control = ControlCenter(runtime_root=runtime, project_root=tmp_path)
    runner = web.AppRunner(control._app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield Served(f"http://127.0.0.1:{port}/", runtime, control)
    finally:
        await runner.cleanup()


async def drive(url: str, plan: list) -> dict:
    """Le harnais contre le vrai serveur. Asynchrone : le serveur vit dans cette boucle."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    process = await asyncio.create_subprocess_exec(
        node, str(HARNESS), url, _chrome(), json.dumps(plan),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(process.communicate(), timeout=240)
    assert process.returncode == 0, err.decode("utf-8", "replace")
    return json.loads(out.decode("utf-8"))


# ------------------------------------------------------------- les actions


def wait(expr: str, timeout_ms: int = 5000) -> dict:
    return {"a": "wait", "expr": expr, "timeoutMs": timeout_ms}


def click(selector: str) -> dict:
    return {"a": "click", "selector": selector}


def key(name: str, shift: bool = False) -> dict:
    return {"a": "key", "key": name, "shift": shift}


def type_in(selector: str, text: str) -> dict:
    return {"a": "type", "selector": selector, "text": text}


def eval_(expr: str, id: str | None = None) -> dict:
    return {"a": "eval", "expr": expr, **({"id": id} if id else {})}


def named(action: dict, id: str) -> dict:
    return {**action, "id": id}


def got(step: dict, id: str):
    """La valeur de l'action nommée `id` dans une étape."""

    found = [a for a in step["actions"] if a.get("id") == id]
    assert len(found) == 1, (id, [a.get("id") for a in step["actions"]])
    return found[0]["value"]


#: Ouvrir les Réglages, puis l'onglet du mot d'éveil, jusqu'à ce que la section soit chargée.
OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#openSettings"),
    wait("!!document.querySelector('#modalTabs [data-tab=wakeword]')"),
    click("#modalTabs [data-tab=wakeword]"),
    wait("!!document.getElementById('ww_save')"),
]

SNAP = """(()=>{
  const q=s=>document.querySelector(s), sec=q('#wakeWordSettings');
  if(!sec)return {present:false};
  const val=id=>{const e=document.getElementById(id);return e?e.value:null};
  const err=q('#wwError'), kw=q('#ww_keyword'), det=q('#wwDetector'), restart=q('#wwRestart');
  return {present:true,
    tabs:[...document.querySelectorAll('#modalTabs button')].map(b=>b.textContent),
    activeTab:(q('#modalTabs button.active')||{}).textContent,
    enabled:q('#ww_enabled').checked, provider:val('ww_provider'), keyword:val('ww_keyword'),
    keywordTag:kw.tagName, keywordOptions:[...(kw.options||[])].map(o=>o.value),
    sens:val('ww_sensitivity_value'), range:val('ww_sensitivity'), cooldown:val('ww_cooldown'),
    pill:q('#wwPill')?{kind:q('#wwPill').dataset.wwPill,text:q('#wwPill').textContent}:null,
    stateText:q('#wwState').textContent,
    saveDisabled:q('#ww_save').disabled, saveAria:q('#ww_save').getAttribute('aria-disabled'),
    inputsDisabled:[...sec.querySelectorAll('input,select')].map(e=>e.disabled),
    restart:restart?restart.textContent:null,
    error:err?{code:(err.querySelector('[data-ww-error-code]')||{}).textContent||null,role:err.getAttribute('role'),text:err.textContent}:null,
    invalid:[...sec.querySelectorAll('[aria-invalid=true]')].map(e=>e.id),
    license:(q('[data-ww-license]')||{}).textContent||null,
    text:sec.textContent,
    detector:det?{kind:det.dataset.wwDetectorKind,text:det.textContent}:null,
    dirty:q('#wwDirty').textContent,
    focus:document.activeElement&&document.activeElement.id,
    toasts:[...document.querySelectorAll('.toast')].map(t=>t.className+'|'+t.textContent),
    storage:Object.keys(localStorage).filter(k=>/wake|eveil|éveil/i.test(k)),
    sectionTop:sec.getBoundingClientRect().top,
  }})()"""

def snapshot(id: str) -> dict:
    return eval_(SNAP, id)


def posts(out: dict) -> list[dict]:
    return [r for r in out["requests"] if r["method"] != "GET"]


def assert_clean(out: dict) -> None:
    assert out["console"] == [], out["console"]


# ======================================================================
# 1. Rendu et défauts
# ======================================================================


async def test_la_section_est_rendue_avec_ses_defauts_et_n_ecrit_rien(served, tmp_path):
    shots = _shots(tmp_path)
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        snapshot("first"),
        eval_("document.getElementById('ww_provider').value='openwakeword';"
              "document.getElementById('ww_provider').dispatchEvent(new Event('change',{bubbles:true}));1"),
        wait("document.getElementById('ww_keyword').tagName==='SELECT'"),
        snapshot("second"),
        {"a": "shot", "path": str(shots / "s7-wakeword-openwakeword-1440.png")},
    ]}])
    step = out["steps"][0]
    first, second = got(step, "first"), got(step, "second")

    # L'onglet vient juste après « Voix ».
    assert first["tabs"][:2] == ["Voix", TAB_LABEL], first["tabs"]
    assert first["activeTab"] == TAB_LABEL

    # Défauts : désactivé, Porcupine, mot « jarvis » (champ de texte), 0,5, 2000.
    assert first["enabled"] is False
    assert first["provider"] == "porcupine"
    assert first["keywordTag"] == "INPUT" and first["keyword"] == "jarvis"
    assert first["sens"] == "0.5" and first["range"] == "0.5"
    assert first["cooldown"] == "2000"
    assert first["pill"] == {"kind": "disabled", "text": "Désactivé"}
    assert "ouvre un micro au repos" in first["text"]
    assert "faux positifs" in first["text"] and "faux négatifs" in first["text"]
    assert "80" in first["text"] and "30000" in first["text"]
    assert first["restart"] is None, "pas de bandeau avant le moindre enregistrement"
    assert first["saveDisabled"] is False
    assert first["license"] is None, "la licence n'est dite que pour le fournisseur qui la porte"
    assert first["detector"]["kind"] == "unread" or first["detector"]["kind"] == "none"
    assert first["storage"] == [], "la page ne stocke rien de ce réglage"

    # openWakeWord : liste fermée, exigences et licence non commerciale.
    assert second["keywordTag"] == "SELECT" and second["keywordOptions"] == ["hey_jarvis"]
    assert second["keyword"] == "hey_jarvis"
    assert "non commercial" in second["license"] and "hey_jarvis" in second["license"]
    assert "wakeword" in second["text"]
    assert "Picovoice" not in second["text"].split("Ce que ce fournisseur exige")[1][:400]

    # Lire n'écrit rien : ni fichier, ni requête autre que GET, ni exception de page.
    assert not served.settings_file.exists()
    assert posts(out) == []
    assert_clean(out)
    assert (shots / "s7-wakeword-openwakeword-1440.png").stat().st_size > 1000


# ======================================================================
# 2. Enregistrer : le fichier, le bandeau, la relecture
# ======================================================================


async def test_enregistrer_ecrit_le_fichier_affiche_le_bandeau_et_se_relit(served, tmp_path):
    shots = _shots(tmp_path)
    served.settings_file.write_text(json.dumps({"manual_wake_key": "f7"}), encoding="utf-8")
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [
            *OPEN,
            click("#ww_enabled"),
            eval_("document.getElementById('ww_provider').value='openwakeword';"
                  "document.getElementById('ww_provider').dispatchEvent(new Event('change',{bubbles:true}));1"),
            wait("document.getElementById('ww_keyword').tagName==='SELECT'"),
            type_in("#ww_sensitivity_value", "0.8"),
            type_in("#ww_cooldown", "3000"),
            eval_("document.getElementById('wwDirty').textContent", "dirty"),
            click("#ww_save"),
            wait("!!document.getElementById('wwRestart')"),
            snapshot("saved"),
            {"a": "shot", "path": str(shots / "s7-wakeword-saved-1440.png")},
        ]},
        # Le rechargement relit ce que le serveur a enregistré.
        {"width": 1440, "height": 900, "actions": [*OPEN, snapshot("reread")]},
    ])
    saved, reread = got(out["steps"][0], "saved"), got(out["steps"][1], "reread")

    assert got(out["steps"][0], "dirty") == "Modifications non enregistrées."
    # Le fichier du runtime temporaire, écrit par la route : le bloc, et le reste intact.
    stored = served.stored()
    assert stored["wake_word"] == {"schema_version": 1, "enabled": True, "provider": "openwakeword",
                                   "keyword": "hey_jarvis", "sensitivity": 0.8, "cooldown_ms": 3000}
    assert stored["manual_wake_key"] == "f7", "les autres réglages survivent"
    # Une seule écriture, par la seule route autorisée, avec la saisie telle quelle.
    written = posts(out)
    assert [(r["method"], r["path"]) for r in written] == [("POST", "/api/wake-word")], written
    assert json.loads(written[0]["body"]) == {"enabled": True, "provider": "openwakeword",
                                              "keyword": "hey_jarvis", "sensitivity": 0.8, "cooldown_ms": 3000}

    assert "Redémarrage de Voice requis" in saved["restart"]
    assert "prochain démarrage de Voice" in saved["restart"]
    assert saved["pill"]["kind"] == "enabled", "le réglage est dit activé, jamais « en écoute »"
    assert "en écoute" not in saved["text"].lower()
    assert saved["error"] is None and saved["dirty"] == ""
    assert any("ok" in t and "Mot d’éveil enregistré" in t for t in saved["toasts"]), saved["toasts"]

    assert reread["enabled"] is True and reread["provider"] == "openwakeword"
    assert reread["keyword"] == "hey_jarvis" and reread["sens"] == "0.8" and reread["cooldown"] == "3000"
    assert reread["restart"] is None, "un bandeau ne survit pas à un rechargement : la page ne le sait plus"
    assert reread["storage"] == []
    assert_clean(out)


# ======================================================================
# 3. Un refus : le code traduit, rien ne change, la saisie reste
# ======================================================================


async def test_une_valeur_refusee_affiche_son_code_traduit_et_garde_la_saisie(served, tmp_path):
    shots = _shots(tmp_path)
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        type_in("#ww_sensitivity_value", "1.5"),
        click("#ww_enabled"),
        click("#ww_save"),
        wait("!!document.getElementById('wwError')"),
        snapshot("first"),
        {"a": "shot", "path": str(shots / "s7-wakeword-refused-1440.png")},
        # Seconde faute, d'un autre champ : la première correction reste.
        type_in("#ww_sensitivity_value", "0.7"),
        type_in("#ww_cooldown", "5"),
        click("#ww_save"),
        wait("document.querySelector('[data-ww-error-code]')&&document.querySelector('[data-ww-error-code]').textContent==='wake_word_cooldown_out_of_range'"),
        snapshot("second"),
        # Un champ vide : « attend un nombre ».
        type_in("#ww_cooldown", "2000"),
        eval_("(()=>{const e=document.getElementById('ww_sensitivity_value');e.focus();e.select();return 1})()"),
        key("Delete"),
        click("#ww_save"),
        wait("document.querySelector('[data-ww-error-code]')&&document.querySelector('[data-ww-error-code]').textContent==='wake_word_sensitivity_invalid'"),
        snapshot("third"),
    ]}])
    step = out["steps"][0]
    first, second, third = got(step, "first"), got(step, "second"), got(step, "third")

    assert first["error"]["code"] == "wake_word_sensitivity_out_of_range"
    assert first["error"]["role"] == "alert"
    assert "comprise entre 0 et 1" in first["error"]["text"], "le code est dit en français"
    assert "Rien n’a été modifié" in first["error"]["text"]
    assert first["sens"] == "1.5", "la saisie est conservée, pas remplacée par la valeur du serveur"
    assert first["enabled"] is True, "l'interrupteur coché aussi"
    assert first["invalid"] == ["ww_sensitivity", "ww_sensitivity_value"]
    assert first["restart"] is None, "un refus n'annonce aucun redémarrage"
    assert first["focus"] == "ww_save", "le focus ne se perd pas"
    assert first["pill"]["kind"] == "disabled", "l'état effectif n'a pas bougé"
    assert any("bad" in t and "wake_word_sensitivity_out_of_range" in t for t in first["toasts"]), first["toasts"]

    assert second["error"]["code"] == "wake_word_cooldown_out_of_range"
    assert "80 et 30 000" in second["error"]["text"]
    assert second["sens"] == "0.7" and second["cooldown"] == "5", "les deux saisies restent"
    assert second["invalid"] == ["ww_cooldown"]

    assert third["error"]["code"] == "wake_word_sensitivity_invalid"
    assert "nombre" in third["error"]["text"] and third["sens"] == ""

    # Trois POST refusés : le fichier n'a jamais été créé.
    assert [r["path"] for r in posts(out)] == ["/api/wake-word"] * 3
    assert not served.settings_file.exists()
    assert_clean(out)


# ======================================================================
# 4. Version étrangère : message dédié, enregistrement désactivé
# ======================================================================


async def test_un_bloc_d_une_version_etrangere_desactive_l_enregistrement(served, tmp_path):
    shots = _shots(tmp_path)
    original = json.dumps({"wake_word": {"schema_version": 7, "enabled": True, "futur": 1}, "manual_wake_key": "f7"})
    served.settings_file.write_text(original, encoding="utf-8")
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        snapshot("seen"),
        eval_("document.getElementById('ww_save').click();1"),
        eval_("document.getElementById('ww_save').dispatchEvent(new MouseEvent('click',{bubbles:true}));1"),
        {"a": "shot", "path": str(shots / "s7-wakeword-foreign-1440.png")},
        snapshot("after"),
    ]}])
    seen = got(out["steps"][0], "seen")
    assert seen["pill"] == {"kind": "foreign", "text": "Version étrangère"}
    assert seen["saveDisabled"] is True
    assert all(seen["inputsDisabled"]), "les champs sont figés aussi : rien à saisir qui ne pourrait être écrit"
    assert "autre version de JARVIS" in seen["stateText"] and "Enregistrer est désactivé" in seen["stateText"]
    assert "wake_word_stored_version_unreadable" in seen["text"], "le diagnostic du fichier est montré"
    assert seen["enabled"] is False, "le bloc étranger n'est pas lu : valeurs par défaut affichées"
    # Cliquer ne fait rien : aucune requête d'écriture, fichier octet pour octet identique.
    assert posts(out) == []
    assert served.settings_file.read_text(encoding="utf-8") == original
    assert got(out["steps"][0], "after")["error"] is None
    assert_clean(out)


# ======================================================================
# 5. Les deux thèmes sont lisibles
# ======================================================================

CONTRAST = """(()=>{
  const parse=c=>{const m=c.match(/rgba?\\(([^)]+)\\)/);if(!m)return [0,0,0,0];const p=m[1].split(',').map(s=>parseFloat(s));return [p[0],p[1],p[2],p.length>3?p[3]:1]};
  const over=(top,bot)=>{const a=top[3];return [top[0]*a+bot[0]*(1-a),top[1]*a+bot[1]*(1-a),top[2]*a+bot[2]*(1-a),1]};
  const backdrop=el=>{const chain=[];for(let e=el;e;e=e.parentElement)chain.push(e);
    let bg=[7,13,19,1];for(const e of chain.reverse()){const c=parse(getComputedStyle(e).backgroundColor);if(c[3]>0)bg=over(c,bg)}return bg};
  const lum=([r,g,b])=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)};
  const ratio=el=>{const fg=over(parse(getComputedStyle(el).color),backdrop(el));const a=lum(fg),b=lum(backdrop(el));
    return Math.round(((Math.max(a,b)+0.05)/(Math.min(a,b)+0.05))*100)/100};
  const pick=sel=>[...document.querySelectorAll('#wakeWordSettings '+sel)].filter(e=>e.getBoundingClientRect().width>0);
  const out={theme:document.documentElement.dataset.jarvisTheme||null};
  for(const [name,sel] of [['label','label'],['hint','.hint'],['title','h3'],['pill','.tag'],['notice','.notice'],
      ['input','input[type=text],input[type=number]'],['button','button.action'],['state','#wwState .hint']]){
    const els=pick(sel);out[name]=els.length?Math.min(...els.map(ratio)):null;out[name+'_n']=els.length}
  return out})()"""


@pytest.mark.parametrize("theme", ["circuit-board", "cosmos"])
async def test_la_section_reste_lisible_dans_chaque_theme(served, tmp_path, theme):
    """Aucun thème clair n'existe dans cette page : les deux thèmes sont sombres.

    On mesure donc le contraste calculé (WCAG, 4,5 pour du texte) de chaque rôle
    de texte de la section, dans chaque thème, sans jamais lire une couleur dans
    la source."""

    shots = _shots(tmp_path)
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        {"a": "theme", "id": theme},
        *OPEN,
        eval_("document.getElementById('ww_provider').value='openwakeword';"
              "document.getElementById('ww_provider').dispatchEvent(new Event('change',{bubbles:true}));1"),
        type_in("#ww_sensitivity_value", "1.5"),
        click("#ww_save"),
        wait("!!document.getElementById('wwError')"),
        eval_(CONTRAST, "contrast"),
        {"a": "shot", "path": str(shots / f"s7-wakeword-theme-{theme}-1440.png")},
    ]}])
    measured = got(out["steps"][0], "contrast")
    assert measured["theme"] == theme
    for role in ("label", "hint", "title", "pill", "notice", "input", "button", "state"):
        assert measured[f"{role}_n"] > 0, f"{role} introuvable dans {theme}"
        assert measured[role] >= 4.5, f"{role} illisible dans {theme} : contraste {measured[role]}"
    assert_clean(out)


# ======================================================================
# 6. Clavier : tout s'atteint, tout s'active, tout a un nom
# ======================================================================


async def test_tout_se_fait_au_clavier_avec_des_noms_et_un_focus_visible(served):
    order = ["ww_enabled", "ww_provider", "ww_keyword", "ww_sensitivity", "ww_sensitivity_value",
             "ww_cooldown", "ww_save", "ww_detector_read"]
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        eval_("document.getElementById('ww_enabled').focus();document.activeElement.id"),
        *[named(key("Tab"), f"fwd{n}") for n in range(len(order) - 1)],
        *[named(key("Tab", shift=True), f"back{n}") for n in range(2)],
        eval_("document.getElementById('ww_enabled').focus();1"),
        key(" "),                                                       # Espace coche l'interrupteur
        eval_("document.getElementById('ww_enabled').checked", "checked"),
        eval_("document.getElementById('ww_sensitivity').focus();1"),
        key("ArrowRight"),                                              # le curseur au clavier
        eval_("document.getElementById('ww_sensitivity_value').value", "sens"),
        eval_("document.getElementById('ww_save').focus();1"),
        key("Tab"),
        key("Tab", shift=True),
        eval_("(()=>{const e=document.activeElement,c=getComputedStyle(e);"
              "return {id:e.id,style:c.outlineStyle,width:c.outlineWidth}})()", "ring"),
        key("Enter"),                                                   # enregistre au clavier
        wait("!!document.getElementById('wwRestart')"),
        snapshot("after"),
        eval_("[...document.querySelectorAll('#wakeWordSettings input,#wakeWordSettings select,#wakeWordSettings button')]"
              ".map(e=>({id:e.id,name:(e.labels&&e.labels[0]&&e.labels[0].textContent)||e.getAttribute('aria-label')||e.textContent,"
              "desc:!!e.getAttribute('aria-describedby')||e.tagName==='BUTTON'}))", "names"),
        eval_("({live:!!document.querySelector('#wakeWordLive[aria-live=polite][role=status]'),"
              "alert:document.querySelectorAll('#wakeWordSettings [role=alert]').length,"
              "labelled:document.getElementById('wakeWordSettings').getAttribute('aria-labelledby')})", "regions"),
    ]}])
    step = out["steps"][0]
    focused = {a["id"]: a["focused"] for a in step["actions"] if a.get("id", "").startswith(("fwd", "back"))}

    assert [focused[f"fwd{n}"] for n in range(len(order) - 1)] == order[1:], focused
    assert [focused["back0"], focused["back1"]] == ["ww_save", "ww_cooldown"]
    assert got(step, "checked") is True, "Espace coche l'interrupteur"
    assert float(got(step, "sens")) > 0.5, "la flèche droite fait monter le curseur et la valeur exacte suit"
    ring = got(step, "ring")
    assert ring["id"] == "ww_save" and ring["style"] == "solid" and float(ring["width"].rstrip("px")) >= 2
    # Entrée sur le bouton enregistre, et le focus y reste après le nouveau dessin.
    after = got(step, "after")
    assert after["focus"] == "ww_save" and "Redémarrage de Voice requis" in after["restart"]
    assert [r["path"] for r in posts(out)] == ["/api/wake-word"]
    for control in got(step, "names"):
        assert control["name"].strip(), f"contrôle sans nom accessible : {control}"
        assert control["desc"], control
    assert got(step, "regions") == {"live": True, "alert": 0, "labelled": "wwTitle"}
    assert_clean(out)


# ======================================================================
# 7. prefers-reduced-motion
# ======================================================================


async def test_le_mouvement_reduit_arrete_l_animation_du_bandeau(served):
    steps = []
    for reduced in (False, True):
        steps.append({"width": 1440, "height": 900, "reducedMotion": reduced, "actions": [
            *OPEN,
            click("#ww_save"),
            wait("!!document.getElementById('wwRestart')"),
            eval_("(()=>{const c=getComputedStyle(document.getElementById('wwRestart'));"
                  "return {name:c.animationName,duration:c.animationDuration,"
                  "media:matchMedia('(prefers-reduced-motion: reduce)').matches}})()", "motion"),
        ]})
    out = await drive(served.url, steps)
    normal, reduced = got(out["steps"][0], "motion"), got(out["steps"][1], "motion")
    assert normal["media"] is False and normal["name"] == "wwIn", normal
    assert reduced["media"] is True and reduced["name"] == "none", reduced
    assert_clean(out)


# ======================================================================
# 8. États de chargement et d'erreur
# ======================================================================


async def test_une_lecture_en_echec_se_dit_et_se_reessaie(served, monkeypatch):
    real = cc.wake_word_settings.describe

    def broken(_settings):
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(cc.wake_word_settings, "describe", broken)

    async def heal_later():
        await asyncio.sleep(3)
        monkeypatch.setattr(cc.wake_word_settings, "describe", real)

    healer = asyncio.create_task(heal_later())
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        wait("!!document.getElementById('openSettings')"),
        click("#openSettings"),
        wait("!!document.querySelector('#modalTabs [data-tab=wakeword]')"),
        click("#modalTabs [data-tab=wakeword]"),
        wait("!!document.querySelector('[data-ww-load-error]')"),
        eval_("({role:document.querySelector('[data-ww-load-error]').getAttribute('role'),"
              "save:!!document.getElementById('ww_save'),text:document.querySelector('[data-ww-load-error]').textContent})", "failed"),
        eval_("new Promise(r=>setTimeout(r,3200))"),
        click("[data-ww-retry]"),
        wait("!!document.getElementById('ww_save')"),
        snapshot("healed"),
    ]}])
    await healer
    failed = got(out["steps"][0], "failed")
    assert failed["role"] == "alert" and failed["save"] is False, "pas de formulaire sans réglage lu"
    assert "illisible" in failed["text"] and "Réessayer" in failed["text"]
    healed = got(out["steps"][0], "healed")
    assert healed["enabled"] is False and healed["pill"]["kind"] == "disabled"


# ======================================================================
# 9. L'état du détecteur : le dernier événement du journal, daté
# ======================================================================


async def test_l_etat_du_detecteur_est_le_dernier_evenement_du_journal(served):
    journal = served.control.journal
    journal.emit("wake.own_stream.started", "Détection démarrée", data={"keyword": "hey_jarvis", "provider": "openwakeword"})
    journal.emit("wake.own_stream.failed", "Détection hors service : OSError: C:\\Users\\Secret\\x.dll", level="error",
                 data={"code": "wake_engine_unavailable", "cause_code": "wake_package_missing", "provider": "openwakeword"})
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        wait("document.getElementById('wwDetector').dataset.wwDetectorKind==='failed'"),
        snapshot("seen"),
        eval_("document.getElementById('ww_detector_read').click();1"),
        wait("document.getElementById('wwDetector').dataset.wwDetectorKind==='failed'"),
    ]}])
    seen = got(out["steps"][0], "seen")
    detector = seen["detector"]["text"]
    assert "en panne" in detector and "wake_package_missing" in detector and "extra Python" in detector
    assert "hors ligne" in detector, "Voice n'est pas en ligne dans cette instance isolée : l'événement est du passé"
    assert "Secret" not in seen["text"] and "dll" not in seen["text"], "le texte libre du journal n'est jamais repris"
    assert "écoute" not in detector.lower().replace("l’écoute", "")
    assert posts(out) == [], "relire le journal n'écrit rien"
    assert_clean(out)
