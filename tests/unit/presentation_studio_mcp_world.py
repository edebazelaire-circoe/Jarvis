"""Monde de test du serveur MCP `jarvis-presentation` : un vrai Core (`JarvisCoreApplication`) derrière le vrai protocole, les vrais outils.

`world(tmp_path)` rend `World` : `tools` (les outils sous test, journal réel), `core` (le harnais `Core` du Studio), `pid` / `vid` / scènes
`S1..S3` / items `I1..I3`, une présentation jouable (partition, direction artistique de repli). `spy.calls` liste chaque appel du client typé
(nom, arguments) : c'est ce qui prouve ce que le serveur a envoyé à Core (acteur, `expected_entry_id`, absence d'`origin`).
`FakeCC` est le Control Center : requêtes enregistrées, réponses scriptées.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.presentation_studio_mcp_tools import PresentationTools
from tests.unit.test_presentation_studio_playback_routes import I1, I2, I3, S1, S2, S3, presentation_with_score
from tests.unit.test_presentation_studio_routes import Core


class SpyClient:
    """Le client typé de Core, appels enregistrés ; tout le reste est transmis tel quel."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        async def run(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return await attr(*args, **kwargs)

        return run

    def named(self, name: str) -> list[tuple[tuple, dict]]:
        return [(a, k) for n, a, k in self.calls if n == name]


class DirectCore:
    def __init__(self, client: Any) -> None:
        self.spy = SpyClient(client)

    async def call(self, fn: Any) -> Any:
        return await fn(self.spy)


@dataclass
class FakeCC:
    """Le Control Center : `answers[(method, route)]` est `(status, body)` ou une fonction du corps."""

    answers: dict[tuple[str, str], Any] = field(default_factory=dict)
    requests: list[tuple[str, str, Any]] = field(default_factory=list)

    async def request(self, method: str, route: str, payload: Any = None, *, timeout_s: float = 0) -> tuple[int, Any]:
        self.requests.append((method, route, payload))
        answer = self.answers.get((method, route), (200, {}))
        return answer(payload) if callable(answer) else answer


@dataclass
class World:
    core: Core
    tools: PresentationTools
    spy: SpyClient
    cc: FakeCC
    journal_root: Path
    pid: str
    vid: str

    @property
    def client(self) -> Any:
        return self.core.client

    def journal_rows(self) -> list[dict[str, Any]]:
        path = self.journal_root / "trace.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


async def open_world(tmp_path: Path) -> tuple[Core, World]:
    core = Core(tmp_path)
    await core.__aenter__()
    pid, vid = await presentation_with_score(core)
    direct = DirectCore(core.client)
    cc = FakeCC()
    root = tmp_path / "journal"
    root.mkdir()
    tools = PresentationTools(direct, cc, journal=RuntimeJournal(root))
    return core, World(core, tools, direct.spy, cc, root, pid, vid)


async def bare_presentation(core: Core) -> tuple[str, str]:
    """Une présentation avec scènes et partition mais SANS direction artistique : une lecture sérieuse y est refusée."""

    from tests.unit.test_presentation_studio_playback_routes import scene, score
    from tests.unit.test_presentation_studio_routes import variant_body

    _, created = await core.call("POST", "", json={"title": "Sans DA"})
    pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
    vid = variant["variant_id"]
    status, saved = await core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(
        variant, scenes=[scene(S1, "Un"), scene(S2, "Deux"), scene(S3, "Trois")]))
    assert status == 200, saved
    status, made = await core.call("POST", f"/{pid}/variants/{vid}/score", json=score(saved["revision"]))
    assert status == 201, made
    return pid, vid


__all__ = ["DirectCore", "FakeCC", "I1", "I2", "I3", "S1", "S2", "S3", "SpyClient", "World", "bare_presentation", "open_world"]
