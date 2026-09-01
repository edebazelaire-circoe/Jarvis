from __future__ import annotations

import json

import httpx
import pytest

from jarvis.adapters.barehands_board import BarehandsBoardClient
from jarvis.domain.errors import ConfigurationError


@pytest.mark.asyncio
async def test_board_client_sends_ephemeral_session_token_not_query_secret():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["token"] = request.headers.get("x-jarvis-token")
        seen["payload"] = json.loads(request.read())
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    board = BarehandsBoardClient("http://127.0.0.1:8794", "opaque-session-secret", client=client)
    result = await board.present("Résumé", "Contenu", x=0.4, y=0.5)
    await client.aclose()
    assert result["presented"] is True
    assert seen["token"] == "opaque-session-secret"
    assert "opaque-session-secret" not in seen["url"]
    assert seen["payload"]["a"] == "present"


def test_board_client_defense_in_depth_rejects_remote_or_tokenless_configuration():
    with pytest.raises(ConfigurationError, match="loopback"):
        BarehandsBoardClient("http://192.0.2.10:8794", "token")
    with pytest.raises(ConfigurationError, match="token"):
        BarehandsBoardClient("http://127.0.0.1:8794", "")
