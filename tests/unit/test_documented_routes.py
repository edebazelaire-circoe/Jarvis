"""Les gabarits de routes cités par la documentation existent vraiment.

NB11 : `docs/ARCHITECTURE.md` et `docs/OPERATIONS.md` ont longtemps écrit
`/api/agent/tasks/{external_id}/trace` alors que la route enregistrée s'appelle
`{task_id}`. Une adresse fausse dans le mode d'emploi coûte une session de
debug ; ce fichier compare les deux listes au lieu de s'en remettre à la
relecture.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from jarvis.runtime.control_center import ControlCenter

ROOT = Path(__file__).resolve().parents[2]
PAGES = (ROOT / "docs" / "ARCHITECTURE.md", ROOT / "docs" / "OPERATIONS.md")

#: Une adresse `/api/...` citée dans la doc, avec ses éventuels segments `{...}`.
QUOTED = re.compile(r"/api/[A-Za-z0-9_{}/.-]*")


@pytest.fixture(scope="module")
def registered(tmp_path_factory) -> set[str]:
    """Les gabarits que le serveur enregistre réellement, `{segment}` compris."""

    root = tmp_path_factory.mktemp("control-center")
    center = ControlCenter(runtime_root=root, project_root=root)
    paths = set()
    for resource in center._app.router.resources():
        info = resource.get_info()
        path = info.get("path") or info.get("formatter")
        if path:
            paths.add(path)
    assert paths, "aucune route enregistrée : le test ne prouverait rien"
    return paths


def quoted_paths() -> dict[str, list[str]]:
    """Chaque `/api/...` cité dans les pages, avec l'endroit où il est écrit."""

    found: dict[str, list[str]] = {}
    for page in PAGES:
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            for match in QUOTED.finditer(line):
                path = match.group(0).rstrip("`.,;:)")
                found.setdefault(path, []).append(f"{page.name}:{number}")
    return found


def test_every_api_route_the_docs_quote_is_registered(registered):
    """Chaque `/api/...` cité dans les deux pages doit exister côté serveur."""

    quoted = quoted_paths()
    assert quoted, "aucune route citée : la documentation aurait changé de forme"
    unknown = {
        path: where
        for path, where in quoted.items()
        if path not in registered
        # Un préfixe cité sans sa suite (« les routes sous /api/agent ») n'est pas
        # un gabarit : on ne retient que ce qu'aucune route ne prolonge.
        and not any(route.startswith(path + "/") for route in registered)
    }
    assert not unknown, f"routes citées mais non enregistrées : {unknown}"


def test_the_trace_route_template_names_the_segment_the_server_declares(registered):
    """Le cas exact de NB11 : le gabarit de la trace, épinglé des deux côtés."""

    assert "/api/agent/tasks/{task_id}/trace" in registered
    for page in PAGES:
        assert "/api/agent/tasks/{external_id}/trace" not in page.read_text(encoding="utf-8"), page.name


def test_every_conversation_history_route_is_documented(registered):
    """Slice 04/06: each `/api/conversations...` route the server registers is described in the pages."""

    quoted = quoted_paths()
    undocumented = sorted(route for route in registered
                          if route.startswith("/api/conversations") and route not in quoted)
    assert not undocumented, f"routes de conversation non documentées : {undocumented}"
