#!/usr/bin/env python3
"""Cas limite: la scene eteinte, les reglages Etoiles et orbites doivent quand
meme etre dans Reglages > Apparence (c'est un reglage d'apparence, pas un
interrupteur). Remet la scene comme elle etait."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cdp  # noqa: E402

PAGE = "http://127.0.0.1:17654/"

SCRIPT = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = {};
  for (let i = 0; i < 60 && typeof window.JarvisThemeAPI === 'undefined'; i++) await sleep(250);

  const settings = await fetch('/api/settings').then(r => r.json());
  out.scene_was = settings && settings.scene ? settings.scene.enabled : null;

  // on eteint la scene
  await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({scene:{enabled:false}})});
  for (let i = 0; i < 40 && document.getElementById('sceneLayer'); i++) await sleep(250);
  out.scene_layer_present = !!document.getElementById('sceneLayer');

  if (typeof openSettings === 'function') await openSettings();
  await sleep(300);
  if (typeof selectTab === 'function') await selectTab('appearance');
  await sleep(1200);
  const content = document.getElementById('modalContent');
  out.section_present = !!(content && content.querySelector('#sceneViewSettings'));
  out.star_controls_count = content ? content.querySelectorAll('[id^="scView_"]').length : 0;
  // le style lui est propre, il ne vient pas de la scene (retiree avec teardown)
  out.own_style = !!document.getElementById('jarvisSceneViewStyle');
  out.scene_style_gone = !document.getElementById('jarvisSceneStyle');
  // un reglage reste enregistrable sans scene
  const halo = content ? content.querySelector('#scView_halo') : null;
  if (halo) {
    halo.value = '0';
    halo.dispatchEvent(new Event('input', {bubbles:true}));
    halo.dispatchEvent(new Event('change', {bubbles:true}));
    await sleep(250);
    out.saved = localStorage.getItem('jarvis.scene.view');
    // la ligne dependante « Halo qui respire » doit etre grisee
    const breathe = content.querySelector('#scView_breathe');
    out.breathe_disabled = !!(breathe && breathe.disabled);
    out.breathe_row_greyed = !!(breathe && breathe.closest('.sc-view-row').classList.contains('sc-off'));
  }
  // remise en etat
  localStorage.removeItem('jarvis.scene.view');
  if (out.scene_was !== false) {
    await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({scene:{enabled: out.scene_was}})});
  }
  return out;
})()
"""


def main() -> int:
    proc = cdp.launch(9351, ROOT / "chrome-profile-off")
    try:
        ws = cdp.WS(cdp.page_ws(9351))
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Page.navigate", {"url": PAGE})
        time.sleep(4.0)
        result = cdp.evaluate(ws, SCRIPT, timeout=180)
        cdp.screenshot(ws, ROOT / "shots" / "scene-eteinte-apparence.png")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        ws.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
