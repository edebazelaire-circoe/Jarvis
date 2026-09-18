from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Transports, fournisseurs et bases de données concrets : aucune couche neutre
# (`jarvis/domain`, `jarvis/ports`) ni le coeur (`jarvis/core`) ne doit en
# dépendre directement. Tout doit passer par un port.
FORBIDDEN_ROOTS = frozenset(
    {
        "aiohttp",
        "httpx",
        "msal",
        "openai",
        "requests",
        "sounddevice",
        "sqlite3",
        "websockets",
    }
)

# Préfixes : couvrent les familles de paquets (`google`, `google.auth`,
# `googleapiclient`, `google_auth_oauthlib`, `winrt.windows.*`, `winsdk`...).
FORBIDDEN_ROOT_PREFIXES = ("google", "winrt", "winsdk")

# Exception nommée et exhaustive : `jarvis/core/v2_app.py` est le composition
# root historique de la v0.2, il assemble les adaptateurs concrets avant de les
# injecter dans les services. L'exception est limitée aux modules réellement
# importés aujourd'hui : tout nouvel adaptateur câblé dans le coeur fera échouer
# ce test tant qu'il n'aura pas été discuté. Elle ne couvre jamais
# `jarvis.runtime.*` ni un transport/fournisseur concret.
CORE_ADAPTER_IMPORT_EXCEPTIONS: dict[str, frozenset[str]] = {
    "jarvis/core/v2_app.py": frozenset(
        {
            "jarvis.adapters.fake_calendar",
            "jarvis.adapters.jsonl_history",
            # Slice 02 de la scène constellation : même rôle que
            # `sqlite_state`, fichier distinct `data/state/scene.sqlite3`.
            "jarvis.adapters.sqlite_scene",
            # Conversation Event store (Slice 02 of conversation-observability):
            # shares the `sqlite_state` connection, constructed only.
            "jarvis.adapters.sqlite_conversation_events",
            "jarvis.adapters.sqlite_state",
            "jarvis.adapters.windows_notifications",
        }
    ),
}


def imports(path: Path, *, root: Path = ROOT) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                package = ".".join(path.relative_to(root).parent.parts)
                name = resolve_name("." * node.level + name, package)
            if name:
                found.add(name)
                # `from jarvis import adapters` and its relative spelling must
                # not evade the layer checks by reporting only `jarvis`.
                if name == "jarvis":
                    found.update(f"jarvis.{alias.name}" for alias in node.names)
    return found


def is_forbidden_dependency(name: str) -> bool:
    """Vrai si l'import cible un transport, un fournisseur ou une base concrète."""
    root = name.split(".")[0]
    return root in FORBIDDEN_ROOTS or root.startswith(FORBIDDEN_ROOT_PREFIXES)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_domain_and_ports_remain_provider_transport_and_database_neutral():
    for folder in (ROOT / "jarvis/domain", ROOT / "jarvis/ports"):
        for path in folder.rglob("*.py"):
            leaked = {name for name in imports(path) if is_forbidden_dependency(name)}
            assert not leaked, f"{path} leaks concrete provider/runtime dependencies: {sorted(leaked)}"


def test_domain_and_ports_do_not_depend_on_adapters_core_or_runtime():
    """Les couches neutres ne connaissent ni implémentation ni orchestration."""
    forbidden_packages = ("jarvis.adapters", "jarvis.core", "jarvis.runtime")
    for folder in (ROOT / "jarvis/domain", ROOT / "jarvis/ports"):
        for path in folder.rglob("*.py"):
            leaked = {name for name in imports(path) if name.startswith(forbidden_packages)}
            assert not leaked, f"{path} inverts the dependency direction: {sorted(leaked)}"


def test_core_does_not_import_concrete_transports_or_providers():
    for path in (ROOT / "jarvis/core").rglob("*.py"):
        leaked = {name for name in imports(path) if is_forbidden_dependency(name)}
        assert not leaked, f"{path} bypasses a v0.2 port: {sorted(leaked)}"


def test_core_does_not_import_concrete_adapters():
    for path in (ROOT / "jarvis/core").rglob("*.py"):
        allowed = CORE_ADAPTER_IMPORT_EXCEPTIONS.get(relative(path), frozenset())
        leaked = {
            name
            for name in imports(path)
            if name.startswith("jarvis.adapters") and name not in allowed
        }
        assert not leaked, f"{path} bypasses a v0.2 port: {sorted(leaked)}"


def test_core_does_not_import_runtime_modules():
    """Le coeur ne remonte jamais vers la couche runtime (journal, serveurs, audio)."""
    for path in (ROOT / "jarvis/core").rglob("*.py"):
        leaked = {name for name in imports(path) if name.startswith("jarvis.runtime")}
        assert not leaked, f"{path} depends on the runtime layer: {sorted(leaked)}"


def test_core_adapter_exceptions_stay_minimal():
    """Chaque exception nommée doit rester réelle et exhaustive.

    Si un import listé disparaît, l'exception doit rétrécir : sinon le gate se
    relâche en silence au fil des refactorings.
    """
    for relative_path, allowed in CORE_ADAPTER_IMPORT_EXCEPTIONS.items():
        path = ROOT / relative_path
        assert path.is_file(), f"exception declared for a missing file: {relative_path}"
        actual = {name for name in imports(path) if name.startswith("jarvis.adapters")}
        stale = allowed - actual
        assert not stale, f"{relative_path} no longer imports {sorted(stale)}: shrink the exception"


def test_nested_relative_and_package_imports_cannot_hide_provider_boundaries(tmp_path):
    path = tmp_path / "jarvis" / "core" / "nested" / "events.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "from openai.types.realtime import RealtimeServerEvent\n"
        "from google.genai import types\n"
        "from ...adapters import openai_realtime\n"
        "from ... import runtime\n"
        "from jarvis import adapters\n",
        encoding="utf-8",
    )
    found = imports(path, root=tmp_path)
    assert {"openai.types.realtime", "google.genai", "jarvis.adapters", "jarvis.runtime"} <= found
    assert {name for name in found if is_forbidden_dependency(name)} == {"openai.types.realtime", "google.genai"}


def test_production_never_imports_test_frontends():
    for path in (ROOT / "jarvis").rglob("*.py"):
        assert not any(name == "tests" or name.startswith("tests.") for name in imports(path)), path
