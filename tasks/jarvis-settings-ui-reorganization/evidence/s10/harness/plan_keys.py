"""Plan 2 : clavier seul — roue Jarvis, raccourci `s`, traversée du shell, Échap sous une confirmation."""
import json, pathlib

S = pathlib.Path(__file__).resolve().parent.parent
SHOTS = S / "shots"
READY = {"a": "wait", "expr": "!!document.getElementById('openSettings')&&!!window.JarvisSettingsRegistry&&!!window.JarvisToolWheel", "timeoutMs": 15000}
FOCUS = r"""(()=>{const e=document.activeElement,sh=document.getElementById('settingsShell'),cs=e&&getComputedStyle(e);
  return {id:e&&e.id||null,tag:e&&e.tagName,text:e&&(e.textContent||'').trim().slice(0,40),slot:e&&e.dataset&&e.dataset.twSlot||null,
    item:e&&e.dataset&&e.dataset.twItem||null,anchor:!!(e&&e.classList&&e.classList.contains('tw-anchor')),
    inShell:!!(e&&sh&&sh.contains(e)),outline:!!cs&&cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>=1,
    open:SET.open,category:SET.category,section:SET.section,confirm:!document.getElementById('confirmBack').hidden}})()"""
IS = lambda cond: {"a": "wait", "expr": cond, "timeoutMs": 6000}

wheel = [
    READY, {"a": "sleep", "ms": 600},
    {"a": "eval", "expr": "document.activeElement&&document.activeElement.blur&&document.activeElement.blur();document.body.focus();true"},
    # Tab depuis le début de la page jusqu'à l'ancre de la roue.
    {"a": "keyUntil", "id": "toAnchor", "key": "Tab", "max": 80,
     "expr": "!!(document.activeElement&&document.activeElement.closest&&document.activeElement.closest('.tw-anchor'))"},
    {"a": "eval", "id": "anchor", "expr": FOCUS},
    {"a": "key", "key": "ArrowRight"},
    {"a": "keyUntil", "id": "toSettingsWedge", "key": "ArrowDown", "max": 12,
     "expr": "(document.activeElement&&document.activeElement.closest('[data-tw-slot]')||{dataset:{}}).dataset.twSlot==='settings'"},
    {"a": "key", "key": "ArrowRight", "after": 400},
    {"a": "eval", "id": "submenu", "expr": "[...document.querySelectorAll('#toolWheel .tw-sub:not([hidden]) .tw-item')].map(b=>b.dataset.twItem)"},
    {"a": "keyUntil", "id": "toConnections", "key": "ArrowDown", "max": 10,
     "expr": "(document.activeElement&&document.activeElement.dataset||{}).twItem==='tab:connections'"},
    {"a": "key", "key": "Enter", "after": 300},
    IS("SET.open&&SET.category==='connections'"),
    {"a": "eval", "id": "afterWheel", "expr": FOCUS},
    {"a": "sleep", "ms": 900},
    {"a": "eval", "id": "afterWheel900", "expr": FOCUS},
    {"a": "shot", "path": str(SHOTS / "k01-roue-clavier-connexions.png")},
    # Traversée au clavier : 45 Tab dans le shell, chaque focus relevé (dans le shell ? contour ?).
    {"a": "keyUntil", "id": "tabTrail", "key": "Tab", "max": 45, "expr": "false"},
    {"a": "keyUntil", "id": "shiftTabTrail", "key": "Tab", "shift": True, "max": 8, "expr": "false"},
    {"a": "key", "key": "Escape", "after": 400},
    {"a": "eval", "id": "afterEscape", "expr": FOCUS},
    # Route JARVIS › Réglages de la voix, au clavier.
    {"a": "key", "key": "ArrowRight", "after": 300},
    {"a": "keyUntil", "id": "toJarvisWedge", "key": "ArrowDown", "max": 12,
     "expr": "(document.activeElement&&document.activeElement.closest('[data-tw-slot]')||{dataset:{}}).dataset.twSlot==='jarvis'"},
    {"a": "key", "key": "ArrowRight", "after": 400},
    {"a": "keyUntil", "id": "toVoiceRow", "key": "ArrowDown", "max": 12,
     "expr": "(document.activeElement&&document.activeElement.dataset||{}).twItem==='voice_settings'"},
    {"a": "key", "key": "Enter", "after": 300},
    IS("SET.open"),
    {"a": "sleep", "ms": 900},
    {"a": "eval", "id": "voiceRow", "expr": FOCUS},
    {"a": "key", "key": "Escape", "after": 400},
    {"a": "eval", "id": "afterEscape2", "expr": FOCUS},
]

shortcut = [
    READY, {"a": "sleep", "ms": 600},
    {"a": "eval", "expr": "document.activeElement&&document.activeElement.blur&&document.activeElement.blur();true"},
    {"a": "eval", "id": "before", "expr": FOCUS},
    {"a": "key", "key": "s", "after": 400},
    IS("SET.open"),
    {"a": "sleep", "ms": 800},
    {"a": "eval", "id": "afterS", "expr": FOCUS},
    # Rail : Début, 3 x flèche bas, Entrée -> Interface & interactions.
    {"a": "key", "key": "Home"}, {"a": "key", "key": "ArrowDown"}, {"a": "key", "key": "ArrowDown"}, {"a": "key", "key": "ArrowDown"},
    {"a": "eval", "id": "railBrowse", "expr": FOCUS},
    {"a": "key", "key": "Enter", "after": 600},
    {"a": "eval", "id": "railEnter", "expr": FOCUS},
    # Vers la liste des entrées, puis Bare Hands.
    {"a": "keyUntil", "id": "toList", "key": "Tab", "max": 6,
     "expr": "!!(document.activeElement&&document.activeElement.closest('#modalTabs'))"},
    {"a": "key", "key": "End"}, {"a": "key", "key": "Enter", "after": 900},
    IS("SET.section==='bare_hands'&&!!document.getElementById('barehandsReset')"),
    {"a": "keyUntil", "id": "toReset", "key": "Tab", "max": 40,
     "expr": "document.activeElement&&document.activeElement.id==='barehandsReset'"},
    {"a": "eval", "id": "onReset", "expr": FOCUS},
    {"a": "key", "key": "Enter", "after": 500},
    IS("!document.getElementById('confirmBack').hidden"),
    {"a": "eval", "id": "confirmOpen", "expr": FOCUS},
    {"a": "shot", "path": str(SHOTS / "k02-confirmation-sur-reglages.png")},
    {"a": "key", "key": "Escape", "after": 500},
    {"a": "eval", "id": "afterConfirmEscape", "expr": FOCUS},
    # Seconde fois : Tab dans la confirmation reste dedans, puis Échap.
    {"a": "key", "key": "Enter", "after": 500},
    IS("!document.getElementById('confirmBack').hidden"),
    {"a": "keyUntil", "id": "confirmTabTrail", "key": "Tab", "max": 4, "expr": "false"},
    {"a": "key", "key": "Escape", "after": 500},
    {"a": "eval", "id": "afterConfirmEscape2", "expr": FOCUS},
    # Pied et fermeture : Voix & audio (pied Enregistrer), Tab jusqu'à Enregistrer puis Fermer.
    {"a": "eval", "expr": "selectTab('conversation');document.querySelector('#modalTabs [aria-selected=true]').focus();true"},
    {"a": "sleep", "ms": 800},
    {"a": "keyUntil", "id": "toSave", "key": "Tab", "max": 80,
     "expr": "!!(document.activeElement&&document.activeElement.closest&&document.activeElement.closest('.set-foot,#modalFoot,footer'))"},
    {"a": "eval", "id": "onSave", "expr": FOCUS},
    {"a": "key", "key": "Tab"},
    {"a": "eval", "id": "afterSave", "expr": FOCUS},
    {"a": "keyUntil", "id": "toClose", "key": "Tab", "max": 20,
     "expr": "!!(document.activeElement&&document.activeElement.closest&&document.activeElement.closest('.set-close'))"},
    {"a": "key", "key": "Enter", "after": 500},
    {"a": "eval", "id": "afterClose", "expr": FOCUS},
]

plan = {"steps": [
    {"name": "wheel", "width": 1440, "height": 900, "settleMs": 2500, "actions": wheel},
    {"name": "shortcut", "width": 1440, "height": 900, "settleMs": 2500, "actions": shortcut},
]}
(S / "plan_keys.json").write_text(json.dumps(plan), encoding="utf-8")
print("ok")
