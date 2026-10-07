"""Contrat du monteur de présentation avec l'outil de scène réel (Slice 01).

`DisplaySceneStager.reveal` appelait `set_visibility`, une méthode que
`SceneDisplayTools` n'a plus depuis le retrait de `scene_set_visibility` (sans
alias). Les doubles des tests de présentation portaient encore cette méthode :
ils ont caché la dérive, et la révélation était cassée en production. Ce
fichier ferme les trois portes par lesquelles elle est passée :

- l'appel lui-même, lu dans la source et confronté à la vraie classe ;
- un aller-retour sur une scène réelle (Core en processus, même montage que
  `tests/unit/test_display_mcp.py`) ;
- les doubles, désormais spécifiés sur `SceneDisplayTools`.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from jarvis.runtime import presentation_staging
from jarvis.runtime.display_mcp import SceneDisplayTools
from jarvis.runtime.presentation_staging import DisplaySceneStager
from tests.unit.test_display_mcp import core, scene_object, tools  # noqa: F401 - fixtures réutilisées
from tests.unit.test_presentation_integration import FakeSceneTools
from tests.unit.test_presentation_speculative import FakeDisplayTools

_REPO = Path(__file__).resolve().parents[2]
_STAGING_SOURCE = Path(presentation_staging.__file__)


def _scene_tool_calls(source: str) -> list[tuple[str, tuple[str, ...]]]:
    """Chaque `self._tools.<méthode>(...)` de la source, avec ses mots-clés."""

    calls = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (isinstance(owner, ast.Attribute) and owner.attr == "_tools"
                and isinstance(owner.value, ast.Name) and owner.value.id == "self"):
            calls.append((node.func.attr, tuple(kw.arg for kw in node.keywords if kw.arg is not None)))
    return calls


def test_every_scene_tool_the_stager_calls_exists_on_scene_display_tools():
    """Lecture de source assumée : c'est la dérive d'un nom qu'on garde ici."""

    calls = _scene_tool_calls(_STAGING_SOURCE.read_text(encoding="utf-8"))
    for name, keywords in calls:
        assert hasattr(SceneDisplayTools, name), f"SceneDisplayTools.{name} n'existe pas"
        method = getattr(SceneDisplayTools, name)
        assert inspect.iscoroutinefunction(method), f"SceneDisplayTools.{name} n'est pas une coroutine"
        accepted = inspect.signature(method).parameters
        for keyword in keywords:
            assert keyword in accepted, f"SceneDisplayTools.{name} n'accepte pas {keyword}="
    # Montage, révélation, reprise : sans eux, l'absence d'échec ne prouverait rien.
    assert {"create_object", "update_object", "archive"} <= {name for name, _ in calls}, calls


async def test_reveal_makes_the_hidden_object_visible_through_real_scene_tools(core, tools):  # noqa: F811
    stager = DisplaySceneStager(tools)
    object_id = await stager.stage_hidden(category="preparation", title="Marges", summary="chart:marges")
    assert (await scene_object(core, object_id))["visibility"] == "hidden"

    await stager.reveal(object_id)
    assert (await scene_object(core, object_id))["visibility"] == "visible"

    await stager.discard([object_id])
    assert await scene_object(core, object_id) is None, "archivé : absent de l'instantané"


@pytest.mark.parametrize("fake_class", [FakeDisplayTools, FakeSceneTools])
async def test_stager_fakes_are_specced(fake_class, monkeypatch):
    """Un double qui survit au retrait d'une méthode réelle est celui qui a caché la panne."""

    fake = fake_class()
    assert getattr(fake.spec, "_spec_class", None) is SceneDisplayTools
    for name, member in vars(fake_class).items():
        if inspect.iscoroutinefunction(member) and not name.startswith("_"):
            assert inspect.iscoroutinefunction(getattr(SceneDisplayTools, name, None)), name

    object_id = await DisplaySceneStager(fake).stage_hidden(category="c", title="t", summary="s")
    monkeypatch.delattr(SceneDisplayTools, "update_object")
    with pytest.raises(AttributeError):
        await DisplaySceneStager(fake_class()).reveal(object_id)


def test_presentation_modules_do_not_name_removed_visibility_tool():
    offenders = []
    for layer in ("domain", "core", "runtime"):
        for path in sorted((_REPO / "jarvis" / layer).glob("presentation_*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "scene_set_visibility" in line or ".set_visibility(" in line:
                    offenders.append(f"{path.relative_to(_REPO)}:{number}")
    assert offenders == []
