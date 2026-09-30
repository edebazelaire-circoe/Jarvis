"""Validation réelle du plugin Circuit Toolbox (Slice 07 ; `docs/mcp/plugins.md` « Conformance: Circuit Toolbox »).

**Marqué `live`, ignoré par défaut.** Il ne tourne que si :

- `JARVIS_LIVE_CIRCOE=1` ;
- une racine de données est donnée — `JARVIS_LIVE_CIRCOE_DATA_ROOT`, sinon
  `JARVIS_DATA_ROOT` **lu à l'import** (le `conftest` remplace ensuite
  `JARVIS_DATA_ROOT` par une racine temporaire pour chaque test) ;
- cette racine contient un plugin **déjà autorisé** (`auth_strategy=oauth`,
  `auth_status=authorized`) dont l'adresse est `JARVIS_LIVE_CIRCOE_ENDPOINT`
  (défaut : l'URL de production de Circuit Toolbox). Le consentement se fait
  dans le Control Center (HV-07-01), jamais ici.

Le test travaille sur une **copie** de la base (API `backup` de sqlite3) : un
Core isolé peut rester démarré sur la racine. Le blob scellé est lié au
plugin et à l'origine, pas au fichier : la copie se descelle sous la même
session Windows (DPAPI CurrentUser). `JARVIS_UI_PORT` doit valoir celui du
consentement (l'URI de retour enregistrée), sinon le client OAuth serait
oublié.

Étapes : connexion non interactive (jeton stocké), liste des outils, **un**
appel d'un outil en lecture seule (`readOnlyHint`, `side_effect == "read"`).
Outil choisi : `JARVIS_LIVE_CIRCOE_TOOL` (+ `JARVIS_LIVE_CIRCOE_ARGS`, JSON),
sinon le premier outil en lecture seule sans argument requis. Aucun secret
(jeton d'accès, de rafraîchissement, identifiant client) dans les vues
publiques, la liste, le résultat ni `trace.jsonl`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import pytest

pytest.importorskip("mcp")

from jarvis.adapters.dpapi_sealer import default_sealer  # noqa: E402
from jarvis.adapters.remote_mcp import SdkRemoteMcpConnector  # noqa: E402
from jarvis.adapters.sqlite_mcp_plugins import SQLiteMcpPluginRepository  # noqa: E402
from jarvis.adapters.sqlite_state import SQLiteStateRepository  # noqa: E402
from jarvis.app import _mcp_allow_loopback_http, _mcp_oauth_redirect_uri  # noqa: E402
from jarvis.core.credential_vault import CredentialVault  # noqa: E402
from jarvis.core.mcp_plugin_service import McpPluginService  # noqa: E402
from jarvis.domain.mcp_plugins import AuthStatus, AuthStrategy  # noqa: E402
from jarvis.runtime.journal import RuntimeJournal  # noqa: E402

pytestmark = pytest.mark.live

DEFAULT_ENDPOINT = "https://circoetoolbox-server-production.up.railway.app/mcp"
LIVE = os.environ.get("JARVIS_LIVE_CIRCOE") == "1"
# Lu à l'import : l'autouse `data_root_is_never_the_real_one` remplace JARVIS_DATA_ROOT pendant le test.
DATA_ROOT = os.environ.get("JARVIS_LIVE_CIRCOE_DATA_ROOT") or os.environ.get("JARVIS_DATA_ROOT")
STATE_DB = Path("state") / "jarvis.sqlite3"


@pytest.fixture
def endpoint() -> str:
    return os.environ.get("JARVIS_LIVE_CIRCOE_ENDPOINT", DEFAULT_ENDPOINT).strip()


@pytest.fixture
def state_copy(tmp_path) -> Path:
    if not LIVE:
        pytest.skip("live test: set JARVIS_LIVE_CIRCOE=1")
    if not DATA_ROOT or not (Path(DATA_ROOT) / STATE_DB).is_file():
        pytest.skip("live test: JARVIS_LIVE_CIRCOE_DATA_ROOT / JARVIS_DATA_ROOT has no state/jarvis.sqlite3")
    source = sqlite3.connect(f"{(Path(DATA_ROOT) / STATE_DB).resolve().as_uri()}?mode=ro", uri=True)
    target = sqlite3.connect(tmp_path / "jarvis.sqlite3")
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return tmp_path / "jarvis.sqlite3"


def _secrets_of(oauth: dict | None) -> list[str]:
    """Valeurs qui ne doivent sortir nulle part (jetons, identifiant client) ; ≥ 8 caractères seulement."""

    if not isinstance(oauth, dict):
        return []
    tokens = oauth.get("tokens") or {}
    client = oauth.get("client_info") or {}
    values = [tokens.get("access_token"), tokens.get("refresh_token"), client.get("client_id"),
              client.get("client_secret")]
    return [value for value in values if isinstance(value, str) and len(value) >= 8]


def _pick_tool(tools: list[dict]) -> tuple[dict, dict]:
    wanted = os.environ.get("JARVIS_LIVE_CIRCOE_TOOL")
    if wanted:
        tool = next((item for item in tools if item["name"] == wanted), None)
        assert tool is not None, f"JARVIS_LIVE_CIRCOE_TOOL={wanted!r} is not listed by the plugin"
        return tool, json.loads(os.environ.get("JARVIS_LIVE_CIRCOE_ARGS") or "{}")
    for tool in tools:
        if tool["side_effect"] == "read" and not (tool["input_schema"].get("required") or []):
            return tool, {}
    pytest.fail("no read-only tool without required argument: set JARVIS_LIVE_CIRCOE_TOOL and JARVIS_LIVE_CIRCOE_ARGS")


async def test_an_authorized_plugin_connects_lists_and_answers_one_read_only_call(state_copy, endpoint, tmp_path):
    state = SQLiteStateRepository(state_copy)
    await state.initialize()
    repo = SQLiteMcpPluginRepository(state)
    journal = RuntimeJournal(tmp_path / "runtime")
    vault = CredentialVault(repo, default_sealer(), diagnostics=journal)
    # Même source que Core : le drapeau de bouclage ne sert qu'à valider ce test sur le faux serveur.
    loopback = _mcp_allow_loopback_http()
    connector = SdkRemoteMcpConnector(redirect_uri=_mcp_oauth_redirect_uri(), allow_loopback_http=loopback)
    service = McpPluginService(repo, vault, connector=connector, diagnostics=journal, allow_loopback_http=loopback)
    try:
        plugin = next((item for item in await service.list_plugins() if item.endpoint == endpoint), None)
        if plugin is None or plugin.auth_strategy is not AuthStrategy.OAUTH \
                or plugin.auth_status is not AuthStatus.AUTHORIZED:
            pytest.skip(f"live test: no authorized OAuth plugin for {endpoint} in the data root")
        sealed = await vault.get_secret(plugin)
        secrets = _secrets_of((sealed or {}).get("oauth"))
        assert secrets, "the authorized plugin has no sealed token readable by this Windows session"

        # 1. connexion : le jeton stocké suffit, aucune URL d'autorisation.
        outcome = await service.connect(plugin.plugin_id)
        assert outcome.status == "connected", (
            f"connect answered {outcome.status!r}: the stored authorization expired — Reconnect in the Control Center")
        assert outcome.authorization_url is None

        # 2. liste : descripteurs normalisés, schémas d'entrée complets.
        listed = await service.external_tools()
        tools = [tool for tool in listed["tools"] if tool["plugin_id"] == plugin.plugin_id]
        assert tools, "the plugin exposes no tool"
        assert all(isinstance(tool["input_schema"], dict) and tool["input_schema"].get("type") == "object"
                   for tool in tools)

        # 3. un appel en lecture seule.
        tool, arguments = _pick_tool(tools)
        assert tool["side_effect"] == "read", f"{tool['name']} is not read-only: V1 validation calls read tools only"
        result = await service.call(tool["tool_id"], arguments, caller={"agent": "live-test"}, timeout_s=60)
        assert result["ok"] is True, result.get("code")

        # 4. aucun secret dans ce qui sort.
        public = json.dumps([item.public_view() for item in await service.list_plugins()], ensure_ascii=False)
        exposed = public + json.dumps(listed, ensure_ascii=False) + json.dumps(result, ensure_ascii=False)
        await service.stop()
        trace = tmp_path / "runtime" / "trace.jsonl"
        exposed += trace.read_text(encoding="utf-8") if trace.exists() else ""
        leaked = [f"secret #{index}" for index, value in enumerate(secrets) if value in exposed]
        assert leaked == [], f"secret material found in outputs: {leaked}"
    finally:
        await service.stop()
        await state.close()
