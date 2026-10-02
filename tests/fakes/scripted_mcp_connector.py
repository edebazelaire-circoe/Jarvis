"""`RemoteMcpConnector` scripté pour les tests unitaires du service et des routes (Slice 03).

Aucun réseau : chaque ouverture suit un pas du plan (`ok`, `authorize`,
`hang` ou un `McpErrorCode` levé en `RemoteMcpError`). `authorize` joue le
rôle du SDK : URL d'autorisation vers l'invite, attente du retour, jetons
enregistrés par `auth.oauth.save`. Jamais importé hors des tests.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from jarvis.domain.mcp_plugins import McpErrorCode
from jarvis.ports.mcp_plugins import RemoteMcpError

SENTINEL = "SENTINEL-SECRET-7f3a"
AUTH_URL = "https://auth.example.com/authorize?response_type=code&state={state}&code_challenge=c"
ISSUER = "https://auth.example.com"
TOOLS = [{"name": "search", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]


class ScriptedSession:
    def __init__(self, connector) -> None:
        self.connector = connector
        self.broken = asyncio.Event()
        self.code = None
        self.changed = None

    async def initialize(self):
        return {"name": "Scripted", "version": "1", "protocol_version": "2025-11-25", "icon_url": None}

    async def list_tools_all(self):
        return list(self.connector.tools)

    async def call_tool(self, name, arguments, timeout_s):
        self.connector.calls.append(name)
        self.connector.call_log.append((name, dict(arguments), timeout_s))
        if self.connector.call_error is not None:
            raise RemoteMcpError(self.connector.call_error, "scripted call failure")
        result = self.connector.call_result
        return result(name, arguments) if callable(result) else result

    def on_tools_changed(self, callback):
        self.changed = callback

    async def wait_failure(self):
        await self.broken.wait()
        return self.code


class ScriptedConnector:
    """`RemoteMcpConnector` scripté : un comportement par ouverture (`ok`, `authorize`, `hang`, ou un code)."""

    def __init__(self, *plan) -> None:
        self.plan = list(plan)
        self.opens: list[tuple[str, bool | None]] = []
        self.tools = list(TOOLS)
        self.calls: list[str] = []
        # Slice 04 : résultat (dict, ou fonction de (nom, arguments)) et panne des appels d'outil.
        self.call_log: list[tuple[str, dict, float]] = []
        self.call_result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        self.call_error = None
        self.sessions: list[ScriptedSession] = []
        self.revoked: list[dict] = []
        self.revoke_error = None
        self.state = 0

    @asynccontextmanager
    async def open(self, plugin, auth, prompt):
        step = self.plan.pop(0) if self.plan else "ok"
        self.opens.append((auth.strategy, None if prompt is None else prompt.interactive))
        if isinstance(step, McpErrorCode):
            raise RemoteMcpError(step, "scripted failure")
        if step == "hang":
            await asyncio.sleep(3600)
        if step == "authorize":
            if prompt is None or not prompt.interactive:
                raise RemoteMcpError(McpErrorCode.REAUTHORIZATION_REQUIRED, "non-interactive")
            self.state += 1
            await prompt.authorization_url(AUTH_URL.format(state=f"st{self.state}"), issuer=ISSUER,
                                           iss_supported=True)
            code, _ = await prompt.wait_callback()
            await auth.oauth.save({"tokens": {"access_token": SENTINEL, "token_type": "Bearer"}, "expires_at": None,
                                   "client_info": {"client_id": "c"}, "issuer": ISSUER, "iss_supported": True,
                                   "revocation_endpoint": ISSUER + "/revoke", "redirect_uri": "http://127.0.0.1/cb",
                                   "code_seen": code})
        session = ScriptedSession(self)
        self.sessions.append(session)
        yield session

    async def revoke(self, plugin, oauth):
        if self.revoke_error is not None:
            raise RemoteMcpError(self.revoke_error, "scripted")
        self.revoked.append(dict(oauth))
