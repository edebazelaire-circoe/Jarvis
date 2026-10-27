"""« Signaler un problème » dans un vrai Chrome sans tête (V1.2 Slice 07, `docs/support-report.md`).

La page est celle que `ControlCenter.index` sert ; seul `fetch` est un double (`_status_centre_browser.mjs` :
`/api/support/*`). L'aperçu est celui qu'écrit le service Python. Épinglé :

- ouverte depuis la vue des erreurs : aperçu (Board actif, catégories incluses et jamais incluses, destination) ;
- consentement obligatoire : sans la case, « Envoyer » ne crée rien et le dit ;
- création (compteur de secondes) puis envoi réussi ;
- envoi échoué : la cause (rôle `alert`, code), le paquet gardé, « Enregistrer dans Documents\\Jarvis »,
  « Télécharger… » et « Réessayer l'envoi » ; l'enregistrement aboutit ;
- « Enregistrer… » : le paquet créé, les deux façons de l'enregistrer ;
- le pied de la fenêtre de préparation ouvre aussi le rapport.

Captures : `JARVIS_V12S07_SHOTS=<dossier>`. Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from jarvis.domain.product_edition import PRESENTATION_EDITION
from tests.unit.test_presentation_edition_ui_browser import _boards, _drive, _no_errors
from tests.unit.test_product_readiness_browser import report as readiness_report
from tests.unit.test_support_report import seeded, service

SHOTS = os.environ.get("JARVIS_V12S07_SHOTS")
PRESENTATION = PRESENTATION_EDITION.to_payload()
NAME = "jarvis-support-20261027T101500Z.zip"
DIALOG = ("(h=>h?{shown:!h.hidden,title:h.querySelector('h2').textContent,meta:(h.querySelector('.sp-meta')||{}).textContent||null,"
          "included:[...h.querySelectorAll('ul.sp-in li')].map(li=>li.dataset.category),"
          "excluded:[...h.querySelectorAll('ul.sp-out li')].map(li=>li.dataset.category),"
          "dest:(h.querySelector('.sp-dest b')||{}).textContent||null,status:h.querySelector('.sp-status').textContent,"
          "statusKind:h.querySelector('.sp-status').dataset.kind||'',send:h.querySelector('.sp-send').textContent,"
          "sendDisabled:h.querySelector('.sp-send').getAttribute('aria-disabled'),"
          "result:h.querySelector('.sp-result').hidden?null:h.querySelector('.sp-result').textContent,"
          "said:(h.querySelector('.sp-said')||{}).textContent||null,role:(h.querySelector('.sp-result .sp-said')||{getAttribute:()=>null}).getAttribute('role'),"
          "roles:[...h.querySelectorAll('.sp-result [data-role]')].map(n=>n.dataset.role),"
          "download:(h.querySelector('[data-role=download]')||{}).getAttribute?h.querySelector('[data-role=download]').getAttribute('href'):null}:null)"
          "(document.getElementById('jvSupport'))")


def _shot(name: str, wait: int = 250) -> list:
    if not SHOTS:
        return []
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot_" + name, str(Path(SHOTS) / f"{name}.png"), wait]]


def _preview(tmp_path: Path) -> dict:
    return asyncio.run(service(tmp_path, seeded(tmp_path)).preview())


def _created(**overrides) -> dict:
    bundle = {"name": NAME, "bytes": 1_234_567, "report_kind": "ai", "ai_status": "done", "ai_detail": None,
              "unknown_mentions": [], "omitted": [{"path": "board/memory/x.png"}], "sendable": True, **overrides}
    return {"answer": {"bundle": bundle, "destination": "e.debazelaire@circoe.com"}, "delayMs": 1600}


def _support_calls(step: dict) -> list:
    return [call for call in step["calls"] if "/api/support/" in call]


def test_report_from_the_errors_view_requires_consent_then_creates_and_sends(tmp_path):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Budget 2027", "presentation")),
            "errors": [{"ts": "2026-10-27T10:05:00Z", "kind": "presentation.render.failed", "level": "error", "message": "ffmpeg"}],
            "support": {"preview": _preview(tmp_path), "create": _created(),
                        "send": {"answer": {"status": "draft_opened", "bundle": NAME,
                                            "message": "Brouillon ouvert dans Outlook avec le paquet en pièce jointe : relisez-le puis envoyez-le depuis votre messagerie."}}}}
    actions = [
        ["eval", "settle", "1", 1500],
        ["click", "errors", '.dock button[data-panel="errors"]', 700],
        ["click", "report", "#reportProblem", 900],
        ["eval", "opened", DIALOG, 50],
        *_shot("support-preview-1440x900"),
        ["click", "send_no_consent", "#jvSupport .sp-send", 300],
        ["eval", "refused", DIALOG, 50],
        ["eval", "describe", "(e=>{e.value='La vidéo ne s’exporte plus';e.dispatchEvent(new Event('input',{bubbles:true}));return e.value})(document.getElementById('jvSupportDescription'))", 50],
        ["click", "consent", "#jvSupportConsent", 200],
        ["click", "send", "#jvSupport .sp-send", 1200],
        ["eval", "creating", DIALOG, 50],
        *_shot("support-creating-1440x900", 50),
        ["eval", "wait", "1", 1400],
        ["eval", "sent", DIALOG, 50],
        *_shot("support-sent-1440x900"),
        ["key", "esc", "Escape", 300],
        ["eval", "closed", "document.getElementById('jvSupport').hidden", 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    opened = r["opened"]
    assert opened["shown"] and opened["title"] == "Signaler un problème"
    assert opened["meta"].startswith("Board actif : Budget 2027") and opened["dest"] == "e.debazelaire@circoe.com"
    assert opened["included"] == ["report", "logs", "state_databases", "board_memory", "settings", "health"]
    assert "credential_vault" in opened["excluded"] and opened["sendDisabled"] == "true"
    assert r["refused"]["status"] == "Cochez d’abord la case de consentement." and r["refused"]["statusKind"] == "failed"
    creating = r["creating"]
    assert "Préparation du paquet et du rapport…" in creating["status"] and "(au plus 3 min 30 s)" in creating["status"]
    assert r["sent"]["said"].startswith("Brouillon ouvert dans Outlook") and NAME in r["sent"]["result"]
    assert "rapport IA écrit" in r["sent"]["result"] and "1 élément(s) omis" in r["sent"]["result"]
    assert r["closed"] is True
    calls = _support_calls(step)
    assert calls[0] == "GET /api/support/preview" and calls[1:] == ["POST /api/support/reports", f"POST /api/support/reports/{NAME}/send"]
    body = next(b["body"] for b in step["bodies"] if b["path"] == "/api/support/reports")
    assert body == {"consent": True, "description": "La vidéo ne s’exporte plus"}


def test_a_failed_send_keeps_the_bundle_offers_save_and_retry(tmp_path):
    failure = {"status": 502, "answer": {"code": "support_mapi_failed", "detail": "MAPISendMail = 2 (MAPI_E_FAILURE)",
                                         "message": "La messagerie Outlook a refusé le brouillon. Le paquet est conservé : enregistrez-le pour le transmettre."}}
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Budget 2027", "presentation")),
            "support": {"preview": _preview(tmp_path), "create": _created(report_kind="factual", ai_status="failed"),
                        "sendQueue": [failure, {"answer": {"status": "draft_opened", "message": "Brouillon ouvert."}}],
                        "save": {"answer": {"status": "saved", "file_name": NAME,
                                            "message": f"Paquet enregistré dans Documents\\Jarvis sous le nom {NAME}."}}}}
    actions = [
        ["eval", "settle", "1", 1500],
        ["eval", "open", "window.JarvisSupportReport.open({reason:'test'}).then(()=>true)", 700],
        ["click", "consent", "#jvSupportConsent", 200],
        ["click", "send", "#jvSupport .sp-send", 2600],
        ["eval", "failed", DIALOG, 50],
        *_shot("support-send-failed-1440x900"),
        ["click", "save", "#jvSupport [data-role=save-documents]", 700],
        ["eval", "saved", DIALOG, 50],
        ["click", "retry", "#jvSupport .sp-send", 900],
        ["eval", "retried", DIALOG, 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors_but_logged(step)
    r = step["results"]
    failed = r["failed"]
    assert failed["said"].startswith("Envoi impossible : La messagerie Outlook a refusé") and failed["role"] == "alert"
    assert "support_mapi_failed" in failed["result"] and "rapport factuel (IA : échec du modèle)" in failed["result"]
    assert failed["roles"] == ["save-documents", "download", "retry-send"] and failed["send"] == "Réessayer l’envoi"
    assert failed["download"] == f"/api/support/reports/{NAME}/download"
    assert r["saved"]["said"] == f"Paquet enregistré dans Documents\\Jarvis sous le nom {NAME}."
    assert r["retried"]["said"] == "Brouillon ouvert."
    calls = _support_calls(step)
    assert calls.count("POST /api/support/reports") == 1, "the kept bundle is reused, never rebuilt"
    assert calls.count(f"POST /api/support/reports/{NAME}/send") == 2 and f"POST /api/support/reports/{NAME}/save" in calls


def _no_errors_but_logged(step: dict) -> None:
    """Un échec d'envoi est dit au journal de la console (`console.error`) : c'est voulu, rien d'autre ne l'est."""

    bad = [line for line in step["console"] if line["type"] in ("exception", "error") and "[support] support.send_failed" not in line["text"]]
    assert bad == [], bad


def test_save_creates_then_offers_both_ways_and_the_readiness_footer_opens_the_report(tmp_path):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Budget 2027", "presentation")),
            "readiness": readiness_report(),
            "support": {"preview": _preview(tmp_path), "create": {**_created(), "delayMs": 200}}}
    actions = [
        ["eval", "settle", "1", 1800],
        ["click", "from_readiness", "#jvReadiness [data-role=report-problem]", 800],
        ["eval", "opened", DIALOG + "&&{readiness:document.getElementById('jvReadiness').hidden}", 50],
        ["eval", "opened_dialog", DIALOG, 50],
        ["click", "consent", "#jvSupportConsent", 200],
        ["click", "save", "#jvSupport .sp-save", 900],
        ["eval", "offered", DIALOG, 50],
        *_shot("support-save-offered-600x800", 50),
    ]
    step = _drive(tmp_path, [{"width": 600, "height": 800, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["opened"]["readiness"] is True and r["opened_dialog"]["shown"] is True
    offered = r["offered"]
    assert offered["said"] == "Paquet prêt. Choisissez où l’enregistrer." and offered["roles"] == ["save-documents", "download"]
    assert _support_calls(step)[-1] == "POST /api/support/reports"
