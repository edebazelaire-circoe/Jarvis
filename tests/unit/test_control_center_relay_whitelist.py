"""Garde générique : chaque route de Core qu'un relais du Control Center appelle est acceptée par `forward_json` (presentation-edition-v1 S03).

Défaut trouvé deux fois en runtime (S03 `/v1/exports`, S05 `/v1/edition/connectors`) : un relais déclaré, testé contre un faux Core, mais
dont le chemin manque dans la liste blanche du vrai client (`FORWARDABLE_PREFIXES` / `FORWARDABLE_PATHS`) : `forward_json` lève
`ValueError`, l'utilisateur lit 503 `core_unreachable`. Ici, chaque route de chaque relais à transport du vrai Control Center est appelée
devant un faux transport qui applique la MÊME liste blanche (`is_forwardable`), et chaque chemin de Core relayé doit y être.
"""

from __future__ import annotations

import re

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jarvis.protocol.client import is_forwardable
from tests.unit.test_control_center_mcp_plugins_api import _center

#: Corrigé sur une autre branche (Slice 05) : toléré absent ici, jamais ajouté par ce test.
OTHER_BRANCH = {"/v1/edition/connectors"}
_PARAM = re.compile(r"\{([A-Za-z_]+)(?::[^}]*)?\}")
_VALUES = (("job", "rj_0123456789ab"), ("artifact", "jart_" + "a" * 32), ("presentation", "pst_" + "0" * 31 + "1"),
           ("variant", "psv_" + "0" * 31 + "1"), ("scene", "pss_000000000001"), ("board", "default"), ("plugin", "demo"))


def _value(name: str) -> str:
    return next((value for key, value in _VALUES if key in name), "abc123")


class WhitelistCore:
    """`CoreSessionTransport.forward` qui refuse comme le vrai `forward_json` (et note tout)."""

    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.refused: set[str] = set()

    async def forward(self, method, path, *, params=None, body=None, timeout_s=None):  # noqa: ANN001
        bare = path.split("?", 1)[0]
        self.paths.add(bare)
        if not is_forwardable(bare):
            self.refused.add(bare)
            raise ValueError(f"forward_json would refuse {bare}")
        return 200, {}


def _relay_route_defs(center) -> list[web.RouteDef]:
    defs: list[web.RouteDef] = []
    for name, value in vars(center).items():
        if name.endswith("_routes") and hasattr(value, "_transport") and callable(getattr(value, "routes", None)):
            defs.extend(d for d in value.routes() if isinstance(d, web.RouteDef))
    return defs


async def test_every_core_path_a_relay_calls_is_in_the_forward_json_whitelist(tmp_path):
    core = WhitelistCore()
    center = _center(tmp_path, core)
    defs = _relay_route_defs(center)
    assert len(defs) > 50, "the sweep sees the relays"
    app = web.Application()
    app.add_routes(defs)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        for d in defs:
            url = _PARAM.sub(lambda m: _value(m.group(1)), d.path)
            body = b"{}" if d.method in ("POST", "PUT", "PATCH", "DELETE") else None
            await client.request(d.method, url, data=body, headers={"Content-Type": "application/json"} if body else None)
    finally:
        await client.close()
    assert "/v1/exports" in core.paths and "/v1/exports/root" in core.paths
    assert len(core.paths) > 30, sorted(core.paths)
    assert core.refused - OTHER_BRANCH == set(), f"relayed by the Control Center but refused by forward_json: {sorted(core.refused)}"
