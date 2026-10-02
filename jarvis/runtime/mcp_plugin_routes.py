"""Routes de gestion des plugins MCP du Control Center : relais de Core (generic-mcp-plugin-runtime, Slice 06).

Core possède le registre des plugins, le coffre des identifiants, les
connexions et le flux OAuth (`docs/mcp/plugins.md` §1, ARCH §14 C1). Le Control
Center n'en garde rien : ces routes relaient telles quelles vers Core, sur le
modèle de `board_routes.py`, et c'est `control_center_mcp_plugins.js` qui les
appelle — le seul module de la page qui écrit sous `/api/mcp`.

| Control Center | Core | Délai |
| --- | --- | --- |
| `GET/POST /api/mcp/plugins` | `GET/POST /v1/mcp/plugins` | 10 s |
| `GET/PATCH/DELETE /api/mcp/plugins/{id}` | `…/v1/mcp/plugins/{id}` | 10 s (DELETE 35 s) |
| `POST /api/mcp/plugins/{id}/connect\\|disconnect\\|refresh` | même chemin sous `/v1` | 35 s |
| `PUT /api/mcp/plugins/{id}/credential` | même chemin sous `/v1` | 10 s |
| `GET /api/mcp/oauth/callback?code&state&iss&error` | `POST /v1/mcp/oauth/callback` | 25 s |

**Relais transparent.** Statut et corps JSON de Core rendus tels quels, erreurs
comprises (`{"error": {"code", "message"}}`, codes de `plugins.md` §8.2). Core
injoignable ou non configuré : 503 `core_unreachable` / `core_unconfigured` ;
délai dépassé : 504 `core_timeout` (l'issue d'une écriture est alors inconnue,
l'écran relit la liste). Les délais longs couvrent ce que Core attend lui-même :
une connexion jusqu'à 20 s (§3.3), une déconnexion jusqu'à 5 s d'arrêt plus 10 s
de révocation (§2.2), un retour OAuth jusqu'à 15 s.

**Chemins inconnus** (ARCH §16 E8) : un identifiant qui ne peut pas être celui
d'un plugin (hors du motif `plugin_id`) répond `404 mcp_plugin_unknown` sans
déranger Core ; un sous-chemin inconnu `404 not_found` ; une méthode absente
`405 method_not_allowed` avec le vrai `Allow` (`refusal`, appelée par le
middleware `_mcp_json_errors`). `mcp_tool_unknown` reste à `/api/mcp/tools*`.

**Garde.** `/api/mcp/plugins` est dans `READ_GUARDED_ROUTES` (les adresses des
plugins sont privées, et ces routes écrivent). Le retour OAuth n'y est pas : la
redirection du serveur d'autorisation est une navigation inter-sites de premier
niveau (ARCH §14 C6). Il est protégé par l'`state` à usage unique de Core, son
délai de 300 s, le contrôle `iss`, et ici par un `Host` de bouclage. Il répond
une page HTML statique en français, `Cache-Control: no-store`,
`Referrer-Policy: no-referrer`, qui ne recopie jamais `code` ni `state`.

**Journal.** Chaque écriture relayée : `mcp.plugin.relayed` (action,
`plugin_id`, statut, code) ; jamais un corps — celui de `…/credential` porte un
secret. Les lectures ne sont pas journalisées une à une (l'écran les répète
toutes les 2 s pendant une autorisation) ; une panne de Core l'est une fois
(`mcp.plugin.core_unreachable`), son retour aussi (`mcp.plugin.core_restored`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import html
import json
import re
from typing import Any

from aiohttp import web

from jarvis.runtime.journal import RuntimeJournal

PLUGINS_ROUTE = "/api/mcp/plugins"
OAUTH_CALLBACK_ROUTE = "/api/mcp/oauth/callback"
#: Préfixes dont `refusal` rend les 404/405 (le reste de `/api/mcp` garde les siens).
OWNED_PREFIXES = (PLUGINS_ROUTE, "/api/mcp/oauth")
#: Motif d'un identifiant de plugin (`docs/mcp/plugins.md` §2.1).
PLUGIN_ID = re.compile(r"\A[a-z0-9][a-z0-9-]{0,31}\Z")
#: Corps relayés : même borne que Core pour `/v1/mcp/*` (256 Kio).
MAX_PROXY_BODY_BYTES = 256 * 1024
#: Délai d'une opération qui attend le serveur distant (connexion ≤ 20 s côté
#: Core, déconnexion ≤ 5 s + 10 s de révocation), plus une marge.
LONG_TIMEOUT_S = 35.0
#: Délai du retour OAuth : Core attend la connexion jusqu'à 15 s.
CALLBACK_TIMEOUT_S = 25.0
#: Borne de chaque paramètre du retour OAuth (un `code` d'AS tient largement dedans).
MAX_CALLBACK_PARAM_CHARS = 4096

#: Phrases de la page de retour, par code stable. Un code absent de la table
#: garde une phrase générique et s'affiche tel quel : jamais maquillé. Les
#: boutons cités sont ceux que la carte du plugin montre alors
#: (`control_center_mcp_plugins.js`, `primaryAction`) ; espaces insécables dans
#: les guillemets.
_NBSP = "\u00a0"


def _button(label: str) -> str:
    return f"«{_NBSP}{label}{_NBSP}»"


_CALLBACK_SENTENCES = {
    "mcp_oauth_state_invalid": "Ce retour d’autorisation est inconnu, expiré ou déjà utilisé. "
                               f"Dans le Control Center, cliquez {_button('Relancer l’autorisation')} "
                               "sur la carte du plugin.",
    "mcp_oauth_denied": "L’autorisation a été refusée sur la page du service. "
                        f"Si c’était une erreur, cliquez {_button('Relancer l’autorisation')} dans le Control Center.",
    "mcp_oauth_issuer_mismatch": "Le serveur d’autorisation qui a répondu n’est pas celui attendu : "
                                 "le code n’a pas été utilisé.",
    "mcp_plugin_reauthorization_required": "Le service demande une nouvelle autorisation. "
                                           f"Cliquez {_button('Reconnecter')} dans le Control Center.",
    "mcp_vault_unavailable": "Aucun coffre de secrets local : le jeton ne peut pas être conservé sur ce poste.",
    "core_unreachable": "Le cœur de JARVIS ne répond pas : l’autorisation n’a pas pu être enregistrée.",
    "core_unconfigured": "Le Control Center ne connaît pas le cœur de JARVIS.",
    "core_timeout": "Le cœur de JARVIS n’a pas répondu à temps : relisez l’état du plugin dans le Control Center.",
    "forbidden_host": "Ce retour n’est accepté que sur l’adresse locale du Control Center.",
    "mcp_plugin_invalid": "Le retour d’autorisation est mal formé.",
}


def _envelope(status: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status, headers=headers)


def _code_of(payload: Any) -> str | None:
    error = payload.get("error") if isinstance(payload, dict) else None
    return error.get("code") if isinstance(error, dict) and isinstance(error.get("code"), str) else None


class McpPluginRoutes:
    """Relais `/api/mcp/plugins*` et `/api/mcp/oauth/callback` -> Core. Voir l'en-tête du module."""

    def __init__(self, *, transport: Callable[[], Any], journal: RuntimeJournal,
                 loopback_host: Callable[[str | None], bool]) -> None:
        # `transport` est lu à chaque requête : le Control Center peut le
        # recevoir (ou le perdre) après la construction des routes.
        self._transport = transport
        self._journal = journal
        self._loopback_host = loopback_host
        self._core_down = False

    def routes(self) -> list[web.RouteDef]:
        item = PLUGINS_ROUTE + "/{plugin_id}"
        return [
            web.get(PLUGINS_ROUTE, self._relay("list", "/v1/mcp/plugins")),
            web.post(PLUGINS_ROUTE, self._relay("create", "/v1/mcp/plugins")),
            web.get(item, self._relay("get", "/v1/mcp/plugins/{plugin_id}")),
            web.patch(item, self._relay("update", "/v1/mcp/plugins/{plugin_id}")),
            web.delete(item, self._relay("remove", "/v1/mcp/plugins/{plugin_id}", LONG_TIMEOUT_S)),
            web.post(item + "/connect", self._relay("connect", "/v1/mcp/plugins/{plugin_id}/connect", LONG_TIMEOUT_S)),
            web.post(item + "/disconnect",
                     self._relay("disconnect", "/v1/mcp/plugins/{plugin_id}/disconnect", LONG_TIMEOUT_S)),
            web.post(item + "/refresh", self._relay("refresh", "/v1/mcp/plugins/{plugin_id}/refresh", LONG_TIMEOUT_S)),
            web.put(item + "/credential", self._relay("credential", "/v1/mcp/plugins/{plugin_id}/credential")),
            # Pas de HEAD : une requête sans corps ne doit jamais consommer un `state`.
            web.get(OAUTH_CALLBACK_ROUTE, self.oauth_callback, allow_head=False),
        ]

    # ------------------------------------------------------------ refus (middleware)

    @staticmethod
    def owns(path: str) -> bool:
        return any(path == prefix or path.startswith(prefix + "/") for prefix in OWNED_PREFIXES)

    @staticmethod
    def refusal(exc: web.HTTPException) -> web.Response | None:
        """404/405 codés sous les préfixes de ce module (ARCH §16 E8) ; `None` pour toute autre exception."""

        if isinstance(exc, web.HTTPMethodNotAllowed):
            return _envelope(405, "method_not_allowed", "this method is not allowed on this MCP plugin route",
                             headers={"Allow": ", ".join(sorted(exc.allowed_methods))})
        if isinstance(exc, web.HTTPNotFound):
            return _envelope(404, "not_found", "unknown MCP plugin route")
        return None

    # ------------------------------------------------------------ relais

    def _relay(self, action: str, core_path: str,
               timeout_s: float | None = None) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            plugin_id = request.match_info.get("plugin_id")
            if plugin_id is not None and not PLUGIN_ID.match(plugin_id):
                # Rien qui puisse être un plugin : répondu ici, jamais recopié.
                return _envelope(404, "mcp_plugin_unknown", "unknown MCP plugin")
            try:
                body = await self._read_body(request)
            except ValueError as exc:
                return _envelope(400, "mcp_plugin_invalid", str(exc))
            path = core_path.format(plugin_id=plugin_id) if plugin_id is not None else core_path
            status, payload = await self._forward(request.method, path, action=action,
                                                  params=dict(request.query) or None, body=body,
                                                  timeout_s=timeout_s)
            if request.method != "GET":
                self._journal.emit(
                    "mcp.plugin.relayed", f"Plugin MCP : {action} relayé à Core (HTTP {status})",
                    level="info" if status < 400 else "warning",
                    data={"action": action, "plugin_id": plugin_id, "status": status, "code": _code_of(payload)})
            if payload is None:
                return _envelope(status if status >= 400 else 502, "http_error",
                                 f"Core answered HTTP {status} without JSON")
            return web.json_response(payload, status=status)

        return handler

    async def _forward(self, method: str, core_path: str, *, action: str, params: dict[str, str] | None = None,
                       body: bytes | None = None, timeout_s: float | None = None) -> tuple[int, Any]:
        """(statut, JSON) de Core, ou l'enveloppe d'une panne de transport. Ne lève jamais sauf annulation."""

        transport = self._transport()
        if transport is None:
            return 503, {"error": {"code": "core_unconfigured", "message": "the control center does not know Core"}}
        try:
            status, payload = await transport.forward(method, core_path, params=params, body=body,
                                                      timeout_s=timeout_s)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            self._journal.emit("mcp.plugin.core_timeout",
                               f"Core n'a pas répondu à temps pour {action} : issue inconnue", level="warning",
                               data={"code": "core_timeout", "action": action, "exception_type": type(exc).__name__})
            unknown = "" if method == "GET" else "; the outcome of this write is unknown, read the list again"
            return 504, {"error": {"code": "core_timeout", "message": f"Core did not answer in time{unknown}"}}
        except Exception as exc:  # noqa: BLE001 - surfaced: 503 with the real cause, journaled once per outage
            if not self._core_down:
                self._core_down = True
                self._journal.emit("mcp.plugin.core_unreachable",
                                   f"Plugins MCP : Core injoignable ({type(exc).__name__})", level="warning",
                                   data={"code": "core_unreachable", "action": action,
                                         "exception_type": type(exc).__name__})
            return 503, {"error": {"code": "core_unreachable",
                                   "message": f"Core is unreachable: {type(exc).__name__}: {str(exc)[:200]}"}}
        if self._core_down:
            self._core_down = False
            self._journal.emit("mcp.plugin.core_restored", "Plugins MCP : Core répond de nouveau",
                               data={"action": action})
        return status, payload

    @staticmethod
    async def _read_body(request: web.Request) -> bytes | None:
        if not request.can_read_body:
            return None
        # `content.read(n)` rend ce qui est arrivé, pas forcément n octets : on lit
        # jusqu'à la fin ou jusqu'à dépasser la borne, jamais au-delà.
        if request.content_length is not None and request.content_length > MAX_PROXY_BODY_BYTES:
            raise ValueError(f"request body exceeds {MAX_PROXY_BODY_BYTES} bytes")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = await request.content.read(MAX_PROXY_BODY_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_PROXY_BODY_BYTES:
                raise ValueError(f"request body exceeds {MAX_PROXY_BODY_BYTES} bytes")
        return b"".join(chunks) or None

    # ------------------------------------------------------------ retour OAuth

    async def oauth_callback(self, request: web.Request) -> web.Response:
        """`GET /api/mcp/oauth/callback` : relaie à Core et répond une page statique, jamais `code` ni `state`."""

        if not self._loopback_host(request.headers.get("Host")):
            return self._callback_page(403, "forbidden_host")
        query = request.query
        params = {key: query.get(key) for key in ("state", "code", "iss", "error")}
        if any(value is not None and len(value) > MAX_CALLBACK_PARAM_CHARS for value in params.values()):
            return self._callback_page(400, "mcp_plugin_invalid")
        if not params["state"]:
            # Sans `state`, aucune autorisation en attente ne peut être retrouvée.
            self._journal.emit("mcp.oauth.callback", "Retour OAuth sans state : refusé", level="warning",
                               data={"status": 400, "code": "mcp_oauth_state_invalid"})
            return self._callback_page(400, "mcp_oauth_state_invalid")
        body = json.dumps({key: value for key, value in params.items() if value is not None}).encode("utf-8")
        status, payload = await self._forward("POST", "/v1/mcp/oauth/callback", action="oauth_callback",
                                              body=body, timeout_s=CALLBACK_TIMEOUT_S)
        plugin = payload.get("plugin") if isinstance(payload, dict) else None
        code = _code_of(payload) or (None if status < 400 else "http_error")
        plugin_id = plugin.get("plugin_id") if isinstance(plugin, dict) else None
        self._journal.emit("mcp.oauth.callback",
                           "Retour OAuth relayé à Core" if status < 400 else f"Retour OAuth refusé (HTTP {status})",
                           level="info" if status < 400 else "warning",
                           data={"status": status, "code": code, "plugin_id": plugin_id})
        if status < 400 and isinstance(plugin, dict):
            return self._callback_page(200, None)
        return self._callback_page(status if status >= 400 else 502, code or "http_error")

    @staticmethod
    def _callback_page(status: int, code: str | None) -> web.Response:
        if code is None:
            title, lead = "Autorisation reçue", "Autorisation reçue, vous pouvez fermer cet onglet."
            detail, tone = "Le Control Center termine la connexion du plugin et l’affiche dès qu’elle aboutit.", "ok"
        else:
            title, lead, tone = "Autorisation non aboutie", "L’autorisation n’a pas abouti.", "bad"
            detail = _CALLBACK_SENTENCES.get(code, "Le retour d’autorisation a été refusé.")
        code_line = f'<p class="code">Code : <code>{html.escape(code)}</code></p>' if code else ""
        close_line = "" if code is None else '<p class="muted">Vous pouvez fermer cet onglet et revenir au Control Center.</p>'
        page = (
            '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>JARVIS · {html.escape(title)}</title><style>"
            ":root{color-scheme:dark;--bg:#05080b;--line:#183343;--text:#d8edf7;--muted:#7190a0;"
            "--ok:#68e0a0;--danger:#ff6577}"
            "body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;box-sizing:border-box;"
            "background:var(--bg);color:var(--text);font:15px ui-monospace,SFMono-Regular,Consolas,monospace}"
            "main{max-width:520px;padding:22px 22px 18px;border:1px solid var(--line);border-radius:10px;"
            "background:#070d13}"
            "h1{margin:0 0 10px;font-size:15px;letter-spacing:.02em}"
            "main.ok h1{color:var(--ok)}main.bad h1{color:var(--danger)}"
            "p{margin:0 0 8px;font-size:13px;line-height:1.55}"
            ".muted,.code{color:var(--muted)}code{color:var(--text)}"
            f'</style></head><body><main class="{tone}" role="main"><h1>{html.escape(lead)}</h1>'
            f"<p>{html.escape(detail)}</p>{code_line}{close_line}"
            "</main></body></html>"
        )
        return web.Response(text=page, status=status, content_type="text/html", headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                                       "form-action 'none'; frame-ancestors 'none'",
        })
