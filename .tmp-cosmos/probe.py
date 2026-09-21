#!/usr/bin/env python3
"""Sonde: ce que l'utilisateur voit vraiment dans le Control Center servi.

Mesure, sur la page reelle (port 17654), les trois choses demandees:
  1. bouton flottant de reglage en bas a droite de la scene  -> doit disparaitre
  2. reglages etoiles/orbites dans Reglages > Apparence       -> doivent y etre
  3. le mot "Omega" dans le texte affiche                     -> doit devenir "Cosmos"

Sort un JSON sur stdout + deux captures PNG.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cdp  # noqa: E402

PAGE = "http://127.0.0.1:17654/"

# --- script de mesure execute DANS la page ---------------------------------
MEASURE = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = {steps: []};

  // 0. la page est-elle montee ?
  for (let i = 0; i < 60 && typeof window.JarvisThemeAPI === 'undefined'; i++) await sleep(250);
  out.theme_api = typeof window.JarvisThemeAPI !== 'undefined';
  if (!out.theme_api) return out;

  // 1. la scene doit etre allumee pour que le bouton flottant puisse exister
  const settings = await fetch('/api/settings').then(r => r.json());
  out.scene_was = settings && settings.scene ? settings.scene.enabled : null;
  out.scene_source = settings && settings.scene ? settings.scene.source : null;
  if (out.scene_was !== true && out.scene_source !== 'env') {
    await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({scene:{enabled:true}})});
    out.steps.push('scene allumee par la sonde');
  }
  // la scene se monte au battement suivant de /api/status
  for (let i = 0; i < 40 && !document.getElementById('sceneLayer'); i++) await sleep(250);
  out.scene_layer = !!document.getElementById('sceneLayer');

  // 2. thème: on active la version demandee (cosmos si present, sinon omega)
  const ids = window.JarvisThemeAPI.list().map(t => t.id);
  out.theme_ids = ids;
  out.theme_names = window.JarvisThemeAPI.list().map(t => t.name);
  const target = ids.includes('cosmos') ? 'cosmos' : (ids.includes('omega') ? 'omega' : ids[0]);
  window.JarvisThemeAPI.activate(target, {persist:false});
  out.theme_active = window.JarvisThemeAPI.current();
  await sleep(400);

  // 3. bouton flottant en bas a droite de la scene
  const btn = document.querySelector('.sc-view-btn');
  out.floating_button = !!btn;
  if (btn) {
    const r = btn.getBoundingClientRect();
    out.floating_button_rect = {right: Math.round(innerWidth - r.right), bottom: Math.round(innerHeight - r.bottom),
                                w: Math.round(r.width), h: Math.round(r.height)};
  }
  out.floating_panel = !!document.getElementById('sceneViewPanel');

  // 4. texte affiche de la page, hors reglages
  out.page_text_has_omega = /omega/i.test(document.body.innerText || '');
  out.page_text_has_cosmos = /cosmos/i.test(document.body.innerText || '');

  // 5. Reglages > Apparence
  if (typeof openSettings === 'function') { await openSettings(); }
  await sleep(300);
  const tabIds = (typeof TABS !== 'undefined' ? TABS : []).map(t => t.id);
  out.tabs = tabIds;
  if (typeof selectTab === 'function' && tabIds.includes('appearance')) {
    await selectTab('appearance');
  }
  for (let i = 0; i < 40; i++) {
    if (document.querySelector('#modalContent input[name=jarvisTheme]')) break;
    await sleep(150);
  }
  await sleep(600);
  const content = document.getElementById('modalContent');
  out.appearance_text = content ? (content.innerText || '').replace(/\s+/g, ' ').trim() : '';
  out.appearance_has_omega = /omega/i.test(out.appearance_text);
  out.appearance_has_cosmos = /cosmos/i.test(out.appearance_text);

  // les controles etoiles/orbites, dans les reglages
  const controls = content ? [...content.querySelectorAll('[id^="scView_"]')] : [];
  out.star_controls = controls.map(el => ({id: el.id, type: el.type,
    min: el.min || null, max: el.max || null, step: el.step || null}));
  out.star_controls_count = controls.length;
  out.reset_button = content ? !!content.querySelector('[data-scene-view-reset],.sc-view-reset') : false;

  // le radio du theme
  const radios = content ? [...content.querySelectorAll('input[name=jarvisTheme]')] : [];
  out.theme_radio_values = radios.map(r => r.value);
  out.theme_radio_labels = radios.map(r => {
    const card = r.closest('label');
    return card ? (card.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60) : '';
  });

  // 6. un reglage change-t-il vraiment la scene ?
  const size = content ? content.querySelector('#scView_size') : null;
  if (size) {
    const before = getComputedStyle(document.getElementById('sceneLayer') || document.body)
      .getPropertyValue('--sc-star-scale').trim();
    size.value = '2';
    size.dispatchEvent(new Event('input', {bubbles:true}));
    size.dispatchEvent(new Event('change', {bubbles:true}));
    await sleep(300);
    const after = getComputedStyle(document.getElementById('sceneLayer') || document.body)
      .getPropertyValue('--sc-star-scale').trim();
    out.star_scale_before = before;
    out.star_scale_after = after;
    out.star_scale_applied = before !== after && after === '2';
    out.localstorage_view = localStorage.getItem('jarvis.scene.view');
  }
  return out;
})()
"""

RESTORE = r"""
(async () => {
  // remet la scene comme on l'a trouvee et efface les prefs posees par la sonde
  localStorage.removeItem('jarvis.scene.view');
  const was = %s;
  if (was !== null && was !== true) {
    await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({scene:{enabled: was}})});
  }
  return true;
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--no-restore", action="store_true")
    args = ap.parse_args()

    shots = ROOT / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    proc = cdp.launch(args.port, ROOT / "chrome-profile")
    try:
        ws = cdp.WS(cdp.page_ws(args.port))
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Page.navigate", {"url": PAGE})
        time.sleep(4.0)

        # capture de la page seule, avant d'ouvrir les reglages
        cdp.evaluate(ws, "typeof openSettings==='function'")
        result = cdp.evaluate(ws, MEASURE, timeout=180)
        cdp.screenshot(ws, shots / f"{args.label}-apparence.png")

        # la scene seule, reglages fermes
        cdp.evaluate(ws, "typeof closeSettings==='function'&&closeSettings(),true")
        time.sleep(1.0)
        cdp.screenshot(ws, shots / f"{args.label}-scene.png")

        if not args.no_restore:
            was = json.dumps(result.get("scene_was") if isinstance(result, dict) else None)
            cdp.evaluate(ws, RESTORE % was, timeout=30)

        print(json.dumps(result, ensure_ascii=False, indent=2))
        ws.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
