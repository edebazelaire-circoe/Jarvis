"""Connexions › Fournisseurs : le rendu pur du module servi, exécuté par node sur le vrai état du magasin de clés.

Slice 07 de jarvis-settings-ui-reorganization (`docs/settings/connections.md`). L'état vient de
`credentials.credentials_state` (le même que la route), jamais d'une liste écrite ici : une carte par fournisseur servi,
dans l'ordre du serveur, la note d'usage = le `hint` du serveur, l'état (clé enregistrée, environnement, rien), la clé
active, les variables d'environnement par leur NOM seulement. Aucun secret ne peut atteindre le HTML : le magasin n'en
renvoie qu'un indice. Le comportement (requêtes, focus, réponses tardives, minuteur) est prouvé dans un vrai Chrome :
`test_connections_settings_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime import credentials as creds

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_connections_settings.js"
SECRET_A = "sk-test-FAKE-perso-0001"
SECRET_B = "sk-test-FAKE-travail-0002"


def render(tmp_path: Path, state: dict, view: dict | None = None) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "render.cjs"
    script.write_text(
        f"const M=require({json.dumps(str(MODULE))});"
        f"process.stdout.write(M.html({json.dumps(state)},{json.dumps(view or {})}));",
        encoding="utf-8",
    )
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return run.stdout


def cards(html: str) -> dict[str, str]:
    """`fournisseur → HTML de sa carte`, dans l'ordre du rendu."""
    parts = re.split(r'(?=<article class="conn-card")', html)
    return {re.search(r'data-conn-provider="([^"]+)"', p).group(1): p for p in parts if p.startswith("<article")}


@pytest.fixture
def state(monkeypatch) -> dict:
    """Deux clés OpenAI (la seconde active), Anthropic par l'environnement seul, le reste vide."""
    for spec in creds.PROVIDERS:
        for name in spec.env:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FAKE-env-9999")
    settings: dict = {}
    creds.upsert_credential(settings, provider="openai", name="Perso", value=SECRET_A)
    second = creds.upsert_credential(settings, provider="openai", name="Travail <b>", value=SECRET_B)
    creds.bind_credential(settings, "openai", second["id"])
    return creds.credentials_state(settings)


def test_one_card_per_served_provider_in_server_order_with_the_server_note(tmp_path, state):
    html = render(tmp_path, state)
    found = cards(html)
    assert list(found) == [p["id"] for p in state["providers"]]
    for provider in state["providers"]:
        card = found[provider["id"]]
        assert f'id="connection_{provider["id"]}"' in card
        assert f">{provider['label']}</h4>" in card.replace("&#39;", "'")
        assert f'<p class="conn-use">{provider["hint"]}</p>'.replace("'", "&#39;") in card
    # Pas de note quand le serveur n'en donne pas : rien n'est inventé.
    bare = {**state, "providers": [{**state["providers"][0], "hint": ""}]}
    assert "conn-use" not in render(tmp_path, bare)


def test_status_active_key_and_environment_fallback(tmp_path, state):
    found = cards(render(tmp_path, state))
    openai, anthropic, google = found["openai"], found["anthropic"], found["google"]
    assert 'set-badge-ok">Clé enregistrée<' in openai
    active = [c for c in state["credentials"] if c["bound"]][0]
    assert re.search(rf'data-bind-id="{active["id"]}" checked', openai)
    assert openai.count(" checked") == 1 and openai.count('set-badge-ok">Active<') == 1
    assert "Travail &lt;b&gt;" in openai and "<b>" not in openai  # le nom est échappé
    assert "Clé utilisée par JARVIS" in openai  # deux clés : un choix
    assert 'set-badge-warn">Variable d’environnement<' in anthropic
    assert "<code>ANTHROPIC_API_KEY</code>" in anthropic and "tant qu’aucune clé n’est enregistrée" in anthropic
    assert "data-bind-id" not in anthropic
    assert 'set-badge-info">Non configuré<' in google and "Aucune clé enregistrée ni variable" in google
    assert "<details class=\"conn-add\"><summary>Ajouter une clé</summary>" in google
    assert "<summary>Ajouter une autre clé</summary>" in openai


def test_no_secret_reaches_the_html_and_value_fields_are_password_and_empty(tmp_path, state):
    html = render(tmp_path, state)
    for secret in (SECRET_A, SECRET_B, "sk-ant-FAKE-env-9999"):
        assert secret not in html
        assert secret[-4:] in html or secret.startswith("sk-ant")  # l'indice seul, pour les clés enregistrées
    values = re.findall(r'<input [^>]*name="value"[^>]*>', html)
    assert values and all('type="password"' in v and "value=" not in v.replace('name="value"', "") for v in values)
    assert all('autocomplete="off"' in v for v in values)


def test_view_state_live_regions_busy_and_delete_confirmation(tmp_path, state):
    key = state["credentials"][0]
    html = render(tmp_path, state, {"busy": True, "confirm": key["id"], "status": "Enregistrement…", "error": "Refusé <x>"})
    assert '<div class="conn-live" id="connectionsStatus" role="status" aria-live="polite">Enregistrement…</div>' in html
    assert 'id="connectionsError" role="alert">Refusé &lt;x&gt;</div>' in html
    assert f'data-conn-delete-confirm="{key["id"]}" disabled' in html and "data-conn-delete-cancel disabled" in html
    assert f'data-conn-delete="{key["id"]}"' not in html  # le bouton laisse la place à la confirmation
    assert all(" disabled" in tag for tag in re.findall(r"<(?:input|button)[^>]*>", html))
    calm = render(tmp_path, state)
    assert 'id="connectionsStatus" role="status" aria-live="polite"></div>' in calm and " disabled" not in calm


def test_the_module_copies_no_provider_list_and_cites_no_secret_sink():
    source = MODULE.read_text(encoding="utf-8")
    for spec in creds.PROVIDERS:
        assert f"'{spec.id}'" not in source and f'"{spec.id}"' not in source, spec.id
        for name in spec.env:
            assert name not in source, name
        assert spec.label not in source and spec.hint not in source
    # La valeur saisie est effacée avant l'envoi et ne part dans aucun journal.
    assert "input.value='';return value" in source
    for call in re.findall(r"log\.(?:info|warn|error)\([^;]*\);", source):
        assert "value" not in call.replace("waited_ms", ""), call
