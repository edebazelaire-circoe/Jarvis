"""Produit installé : maison `%LOCALAPPDATA%\\CIRCOE\\Jarvis`, CONTEXT_GLOBAL permanent, reprise de profil.

Contrat : `docs/local-data.md` › *Produit installé*, `docs/context-global.md` › *Permanence*,
`jarvis/installation.py`, `jarvis/data_root.py`. Environnement simulé : aucun vrai
`%LOCALAPPDATA%`, aucune racine du JARVIS vivant n'est lue ni écrite.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from jarvis import data_root, installation
from jarvis.adapters import global_context
from jarvis.adapters.global_context import GLOBAL_CONTEXT_DIR, GlobalContextProtected, ensure_not_global_context
from jarvis.adapters.node_capability_runner import _remove_tree
from jarvis.adapters.safe_tree import UnsafeTree, remove_tree
from jarvis.data_root import (ProfileAdoptionError, adopt_data_root, adopt_legacy_data, installation_diagnostics,
                              resolve_data_root, resolve_runtime_root)
from jarvis.domain.errors import ConfigurationError
from jarvis.domain.product_edition import ProductEdition
from jarvis.installation import PRODUCT_MARKER, InstallMode, detect_installation, marker_payload
from jarvis.runtime.product_edition_env import process_edition


def installed_code(root: Path) -> Path:
    """Un dossier de programme tel que le paquet le pose : le marqueur à côté du code."""

    root.mkdir(parents=True, exist_ok=True)
    (root / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    return root


def local_appdata(tmp_path: Path) -> dict[str, str]:
    return {"LOCALAPPDATA": str(tmp_path / "Users" / "someone" / "AppData" / "Local")}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- identité d'installation ---------------------------------------------------------------------------------------

def test_a_checkout_without_marker_keeps_the_development_roots_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(data_root.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    checkout = tmp_path / "Jarvis"
    checkout.mkdir()
    env = local_appdata(tmp_path)  # un LOCALAPPDATA présent ne change rien sans marqueur
    assert detect_installation(env, code_root=checkout).mode is InstallMode.DEVELOPMENT
    root = resolve_data_root(env, project_root=checkout)
    assert root == data_root.default_data_root(checkout).resolve()
    assert root.parent.parent == (tmp_path / "home" / ".jarvis" / "instances").resolve()
    assert resolve_runtime_root(env, project_root=checkout) == (tmp_path / "runtime").resolve()
    assert process_edition({}, code_root=checkout).edition is ProductEdition.FULL


def test_the_installed_product_lives_under_localappdata_whatever_the_cwd(tmp_path, monkeypatch):
    code = installed_code(tmp_path / "Program Files" / "CIRCOE" / "Jarvis")
    env = local_appdata(tmp_path)
    home = Path(env["LOCALAPPDATA"]) / "CIRCOE" / "Jarvis"
    for cwd in (tmp_path, code):
        monkeypatch.chdir(cwd)
        assert resolve_data_root(env, project_root=code) == (home / "data").resolve()
        assert resolve_runtime_root(env, project_root=code) == (home / "runtime").resolve()
    found = detect_installation(env, code_root=code)
    assert found.installed and found.home.config == home / "config"
    # Rien de canonique sous le programme ni sous le dossier courant.
    assert code not in resolve_data_root(env, project_root=code).parents


def test_moving_or_updating_the_program_does_not_create_a_second_profile(tmp_path):
    env = local_appdata(tmp_path)
    before = installed_code(tmp_path / "Program Files" / "CIRCOE" / "Jarvis")
    after = installed_code(tmp_path / "D" / "Apps" / "Jarvis 1.1")
    assert resolve_data_root(env, project_root=before) == resolve_data_root(env, project_root=after)
    assert resolve_runtime_root(env, project_root=before) == resolve_runtime_root(env, project_root=after)


def test_overrides_keep_priority_in_both_modes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    code = installed_code(tmp_path / "program")
    env = local_appdata(tmp_path) | {"JARVIS_DATA_ROOT": str(tmp_path / "admin-data"),
                                     "JARVIS_RUNTIME_DIR": str(tmp_path / "admin-runtime")}
    for root in (checkout, code):
        assert resolve_data_root(env, project_root=root) == (tmp_path / "admin-data").resolve()
        assert resolve_runtime_root(env, project_root=root) == (tmp_path / "admin-runtime").resolve()
    # Relatif : au dossier courant, comme avant ; vide : absent.
    assert resolve_runtime_root({"JARVIS_RUNTIME_DIR": "rt"}, project_root=checkout) == (tmp_path / "rt").resolve()
    assert resolve_runtime_root(local_appdata(tmp_path) | {"JARVIS_RUNTIME_DIR": "  "}, project_root=code) == \
        (Path(local_appdata(tmp_path)["LOCALAPPDATA"]) / "CIRCOE" / "Jarvis" / "runtime").resolve()


@pytest.mark.parametrize("content", ["{not json", json.dumps({"schema": "other", "schema_version": 1}),
                                     json.dumps({"schema": "jarvis.product-install", "schema_version": 2}), "[]"])
def test_an_unreadable_marker_refuses_to_start_instead_of_falling_back_to_development(tmp_path, content):
    code = tmp_path / "program"
    code.mkdir()
    (code / PRODUCT_MARKER).write_text(content, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        detect_installation(local_appdata(tmp_path), code_root=code)
    with pytest.raises(ConfigurationError):
        resolve_data_root(local_appdata(tmp_path), project_root=code)


@pytest.mark.parametrize("env", [{}, {"LOCALAPPDATA": "  "}, {"LOCALAPPDATA": "relative\\Local"}])
def test_installed_without_a_usable_localappdata_refuses_to_start(tmp_path, env):
    code = installed_code(tmp_path / "program")
    with pytest.raises(ConfigurationError, match="LOCALAPPDATA"):
        resolve_data_root(env, project_root=code)


def test_the_installed_product_defaults_to_presentation_and_the_variable_still_wins(tmp_path):
    code = installed_code(tmp_path / "program")
    env = local_appdata(tmp_path)
    assert process_edition(env, code_root=code).edition is ProductEdition.PRESENTATION
    assert process_edition(env | {"JARVIS_PRODUCT_EDITION": "full"}, code_root=code).edition is ProductEdition.FULL
    with pytest.raises(ConfigurationError):
        process_edition(env | {"JARVIS_PRODUCT_EDITION": "bogus"}, code_root=code)


def test_diagnostics_name_the_product_home_without_any_user_path(tmp_path):
    code = installed_code(tmp_path / "program")
    env = local_appdata(tmp_path)
    payload = installation_diagnostics(resolve_data_root(env, project_root=code),
                                       resolve_runtime_root(env, project_root=code), env, project_root=code)
    assert payload == {"mode": "installed", "product_home": r"%LOCALAPPDATA%\CIRCOE\Jarvis",
                       "data_root": {"source": "product_home", "label": r"%LOCALAPPDATA%\CIRCOE\Jarvis\data"},
                       "runtime_root": {"source": "product_home", "label": r"%LOCALAPPDATA%\CIRCOE\Jarvis\runtime"}}
    override = env | {"JARVIS_DATA_ROOT": str(tmp_path / "x")}
    text = json.dumps(installation_diagnostics(tmp_path / "x", resolve_runtime_root(env, project_root=code),
                                               override, project_root=code))
    assert "someone" not in text and str(tmp_path) not in text and '"override"' in text


# -- consommateurs : une seule racine partagée ---------------------------------------------------------------------

def test_every_consumer_resolves_under_the_shared_product_home(tmp_path, monkeypatch):
    """Core et Control Center (`V2Settings`), Test Lab, MCP Écran, hook de routage, modèles, retours, `.env`.

    Le chemin V1 (`AppConfig`) est exercé par `test_app_config_in_installed_mode_…`.
    """

    code = installed_code(tmp_path / "program")
    env = local_appdata(tmp_path)
    home = (Path(env["LOCALAPPDATA"]) / "CIRCOE" / "Jarvis").resolve()
    monkeypatch.setattr(installation, "CODE_ROOT", code)
    for name in ("JARVIS_DATA_ROOT", "JARVIS_RUNTIME_DIR", "JARVIS_CORE_TOKEN_FILE", "JARVIS_PRODUCT_EDITION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", env["LOCALAPPDATA"])
    monkeypatch.chdir(tmp_path)

    from jarvis.adapters.wakeword_model_catalog import default_model_dir
    from jarvis.environment import project_environment_file
    from jarvis.runtime.display_mcp import DisplayMcpTarget
    from jarvis.runtime.feedback_sessions import feedback_base
    from jarvis.runtime.routing_hook import default_runtime_root as routing_runtime
    from jarvis.runtime.speaker_benchmark import default_runtime_root as benchmark_runtime
    from jarvis.testlab.composition import _roots
    from jarvis.v2_config import V2Settings

    settings = V2Settings.load()
    assert settings.data_root == home / "data"
    assert settings.runtime_root == home / "runtime"
    assert settings.token_file == home / "runtime" / "core.token"
    assert global_context.global_context_root(settings.data_root) == home / "data" / GLOBAL_CONTEXT_DIR
    assert _roots(os.environ, None, None) == (home / "runtime", home / "data")
    assert DisplayMcpTarget.from_env(env).token_file == home / "runtime" / "core.token"
    assert routing_runtime() == home / "runtime"
    assert benchmark_runtime() == home / "runtime"
    assert default_model_dir() == home / "runtime" / "wake-word" / "models"
    assert feedback_base(code) == home / "data"
    assert project_environment_file() == home / "config" / ".env"
    assert process_edition().edition is ProductEdition.PRESENTATION


def test_core_never_adopts_the_program_folder_data_when_installed(tmp_path, monkeypatch):
    from jarvis import app
    from jarvis.v2_config import V2Settings

    code = installed_code(tmp_path / "program")
    (code / "data" / "state").mkdir(parents=True)
    sqlite3.connect(code / "data" / "state" / "jarvis.sqlite3").close()
    monkeypatch.setattr(installation, "CODE_ROOT", code)
    monkeypatch.setattr(data_root, "LEGACY_DATA_ROOT", code / "data")
    monkeypatch.delenv("JARVIS_DATA_ROOT", raising=False)
    monkeypatch.delenv("JARVIS_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", local_appdata(tmp_path)["LOCALAPPDATA"])
    settings = V2Settings.load()
    assert app._adopt_legacy_data_root(settings) == settings
    assert not (code / "data" / data_root.LEGACY_MARKER).exists()
    assert not settings.data_root.exists()


# -- CONTEXT_GLOBAL : permanent ------------------------------------------------------------------------------------

def seeded_global_context(root: Path) -> Path:
    context = root / GLOBAL_CONTEXT_DIR
    assert global_context.seed_global_context(context)
    (context / "user_habits.md").write_text("tutoie jamais\n", encoding="utf-8")
    return context


def test_global_context_is_loaded_from_the_product_root_and_survives_restart(tmp_path):
    code = installed_code(tmp_path / "program")
    env = local_appdata(tmp_path)
    root = global_context.global_context_root(resolve_data_root(env, project_root=code))
    first = global_context.load_global_context(root)
    assert first.seeded and first.text
    (root / "mission.md").write_text("mission propre à l'utilisateur\n", encoding="utf-8")
    (root / "personnality.md").unlink()
    # Redémarrage, puis mise à jour du programme ailleurs : même dossier, jamais ré-ensemencé.
    moved = installed_code(tmp_path / "program-v2")
    again = global_context.load_global_context(
        global_context.global_context_root(resolve_data_root(env, project_root=moved)))
    assert again.root == first.root and not again.seeded
    assert "mission propre" in again.text and not (root / "personnality.md").exists()


def test_the_global_context_guard_refuses_the_folder_its_content_and_an_ancestor(tmp_path):
    context = seeded_global_context(tmp_path / "data")
    for path in (context, context / "user_habits.md", context / "current_task"):
        with pytest.raises(GlobalContextProtected):
            ensure_not_global_context(path)
    ensure_not_global_context(tmp_path / "data" / "prefabs")  # le reste n'est pas concerné
    # Effaceur qui inventorie d'abord : refus avant le premier octet.
    with pytest.raises(UnsafeTree, match=GLOBAL_CONTEXT_DIR):
        remove_tree(tmp_path / "data", within=tmp_path)
    with pytest.raises(UnsafeTree):
        remove_tree(context, within=tmp_path / "data")
    # Effaceur récursif des capacités locales (nettoyage, réparation) : refus en descendant.
    with pytest.raises(GlobalContextProtected):
        _remove_tree(context)
    with pytest.raises(GlobalContextProtected):
        _remove_tree(tmp_path / "data")
    assert (context / "user_habits.md").read_text(encoding="utf-8") == "tutoie jamais\n"
    assert (context / global_context.MANIFEST_NAME).is_file()


def test_the_remotion_cache_purge_never_removes_global_context(tmp_path):
    from jarvis.adapters.remotion_compiler import RemotionCompiler

    context = seeded_global_context(tmp_path / "data")
    assert RemotionCompiler._remove_tree(context) is False
    assert (context / "user_habits.md").is_file()


def test_legacy_adoption_copies_global_context_whole_and_never_merges_it(tmp_path):
    legacy, target = tmp_path / "repo" / "data", tmp_path / "home" / "data"
    seeded_global_context(legacy)
    report = adopt_legacy_data(target, legacy)
    assert report.adopted
    assert (target / GLOBAL_CONTEXT_DIR / "user_habits.md").read_text(encoding="utf-8") == "tutoie jamais\n"
    assert (legacy / GLOBAL_CONTEXT_DIR / "user_habits.md").is_file()  # source intacte
    # Une cible qui a déjà le sien n'est jamais complétée fichier par fichier.
    other_legacy, other_target = tmp_path / "repo2" / "data", tmp_path / "home2" / "data"
    seeded_global_context(other_legacy)
    (other_target / GLOBAL_CONTEXT_DIR).mkdir(parents=True)
    report = adopt_legacy_data(other_target, other_legacy)
    assert list((other_target / GLOBAL_CONTEXT_DIR).iterdir()) == []
    assert any(GLOBAL_CONTEXT_DIR in item for item in report.skipped)


# -- reprise explicite d'un profil ---------------------------------------------------------------------------------

def profile(root: Path) -> sqlite3.Connection:
    """Un profil réaliste : base WAL dont des lignes ne sont que dans le -wal, fichiers, CONTEXT_GLOBAL, restes."""

    (root / "state").mkdir(parents=True)
    conn = sqlite3.connect(root / "state" / "jarvis.sqlite3", isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
    for index in range(40):
        conn.execute("INSERT INTO items(label) VALUES (?)", (f"row-{index}",))
    seeded_global_context(root)
    (root / "boards" / "b1" / "memory").mkdir(parents=True)
    (root / "boards" / "b1" / "memory" / "summary.md").write_text("résumé\n", encoding="utf-8")
    (root / "presentations" / "p1").mkdir(parents=True)
    (root / "presentations" / "p1" / "presentation.json").write_text("{}", encoding="utf-8")
    (root / "presentations" / ".staging-0123456789abcdef").mkdir()
    (root / "artifacts" / "a1").mkdir(parents=True)
    (root / "artifacts" / "a1" / "upload.png.partial").write_bytes(b"half")
    (root / "local_capabilities" / "remotion" / "runtime" / "node_modules").mkdir(parents=True)
    (root / "local_capabilities" / "remotion" / "state.json").write_text("{}", encoding="utf-8")
    (root / "state" / "orphan.sqlite3-wal").write_bytes(b"wal without its base")
    return conn


def test_profile_adoption_copies_first_verifies_and_leaves_the_source_untouched(tmp_path):
    source, target = tmp_path / "dev" / "data", tmp_path / "Local" / "CIRCOE" / "Jarvis" / "data"
    conn = profile(source)
    before = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob("*")
              if p.is_file() and not p.name.endswith("-shm")}
    try:
        report = adopt_data_root(source, target)
    finally:
        conn.close()
    assert report.databases["state/jarvis.sqlite3"]["rows"] == {"items": 40}
    copy = sqlite3.connect(target / "state" / "jarvis.sqlite3")
    assert copy.execute("SELECT count(*) FROM items").fetchone()[0] == 40
    copy.close()
    assert report.global_context_files >= 2
    assert (target / GLOBAL_CONTEXT_DIR / "user_habits.md").read_text(encoding="utf-8") == "tutoie jamais\n"
    assert (target / "boards" / "b1" / "memory" / "summary.md").is_file()
    assert (target / "local_capabilities" / "remotion" / "state.json").is_file()
    for absent in ("presentations/.staging-0123456789abcdef", "artifacts/a1/upload.png.partial",
                   "local_capabilities/remotion/runtime", "state/orphan.sqlite3-wal", "state/jarvis.sqlite3-wal"):
        assert not (target / absent).exists(), absent
    assert any("orphan.sqlite3-wal" in item for item in report.skipped)
    assert (target / data_root.PROFILE_ADOPTION_RECORD).is_file()
    after = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob("*")
             if p.is_file() and not p.name.endswith("-shm")}
    # Source intacte : seul le -wal a pu être rejoué dans sa propre base par la fermeture de la connexion.
    assert {k: v for k, v in after.items() if not k.endswith("-wal") and k != "state/jarvis.sqlite3"} == \
        {k: v for k, v in before.items() if not k.endswith("-wal") and k != "state/jarvis.sqlite3"}
    assert not list(target.parent.glob(".data.adopting-*"))


def test_profile_adoption_never_merges_into_a_root_that_has_content(tmp_path):
    source, target = tmp_path / "dev" / "data", tmp_path / "product" / "data"
    profile(source).close()
    (target / GLOBAL_CONTEXT_DIR).mkdir(parents=True)
    (target / GLOBAL_CONTEXT_DIR / "mission.md").write_text("déjà là\n", encoding="utf-8")
    with pytest.raises(ProfileAdoptionError) as caught:
        adopt_data_root(source, target)
    assert caught.value.code == "target_not_empty"
    assert (target / GLOBAL_CONTEXT_DIR / "mission.md").read_text(encoding="utf-8") == "déjà là\n"
    assert sorted(p.name for p in target.iterdir()) == [GLOBAL_CONTEXT_DIR]
    with pytest.raises(ProfileAdoptionError) as caught:
        adopt_data_root(source, source / "nested")
    assert caught.value.code == "roots_overlap"


def test_a_failed_database_copy_leaves_nothing_in_place(tmp_path):
    source, target = tmp_path / "dev" / "data", tmp_path / "product" / "data"
    (source / "state").mkdir(parents=True)
    (source / "state" / "scene.sqlite3").write_bytes(b"this is not a database at all" * 40)
    with pytest.raises(ProfileAdoptionError, match="database_copy_failed"):
        adopt_data_root(source, target)
    assert not target.exists()
    assert not list(target.parent.glob(".data.adopting-*")) if target.parent.exists() else True
    assert (source / "state" / "scene.sqlite3").read_bytes().startswith(b"this is not")


def test_health_carries_the_installation_block_only_when_given(tmp_path):
    import asyncio
    from dataclasses import dataclass
    from enum import Enum
    from types import SimpleNamespace

    from jarvis.protocol.server import LocalProtocolServer

    class State(Enum):
        READY = "ready"

    @dataclass
    class Counters:
        emitted: int = 0

    core = SimpleNamespace(
        health=SimpleNamespace(ready=True, status="ready", detail=None),
        scene=SimpleNamespace(availability=SimpleNamespace(state=State.READY, code=None), capacity=None),
        conversation_events=SimpleNamespace(unreadable_rows=0, diagnostic_failures=0),
        conversation_event_emitter=SimpleNamespace(counters=Counters()),
        conversation_event_queries=SimpleNamespace(failures=0))
    code = installed_code(tmp_path / "program")
    env = local_appdata(tmp_path)
    block = installation_diagnostics(resolve_data_root(env, project_root=code),
                                     resolve_runtime_root(env, project_root=code), env, project_root=code)
    token = "t" * 40
    with_block = LocalProtocolServer(core, host="127.0.0.1", port=1, token=token, installation=block)
    body = json.loads(asyncio.run(with_block.health(None)).body)
    assert body["installation"]["mode"] == "installed" and str(tmp_path) not in json.dumps(body)
    without = LocalProtocolServer(core, host="127.0.0.1", port=1, token=token)
    assert "installation" not in json.loads(asyncio.run(without.health(None)).body)


# -- reprise QA S2 -------------------------------------------------------------------------------------------------

EXAMPLE_TOML = Path(__file__).resolve().parents[2] / "config" / "jarvis.example.toml"


def app_config_env(monkeypatch, tmp_path, *, installed_at: Path | None):
    for name in ("JARVIS_DATA_ROOT", "JARVIS_RUNTIME_DIR", "JARVIS_MEMORY_DIR", "JARVIS_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", local_appdata(tmp_path)["LOCALAPPDATA"])
    if installed_at is not None:
        monkeypatch.setattr(installation, "CODE_ROOT", installed_at)
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "jarvis.toml").write_text(EXAMPLE_TOML.read_text(encoding="utf-8"), encoding="utf-8")
    return config / "jarvis.toml"


def test_app_config_in_installed_mode_uses_the_product_home_and_ignores_a_relative_toml_runtime(tmp_path, monkeypatch):
    from jarvis import config as v1_config
    from jarvis.config import AppConfig

    code = installed_code(tmp_path / "program")
    (code / "data" / "memory" / "long_term_memory").mkdir(parents=True)
    (code / "data" / "memory" / "long_term_memory" / "note.md").write_text("ancienne\n", encoding="utf-8")
    monkeypatch.setattr(v1_config, "LEGACY_DATA_ROOT", code / "data")
    toml = app_config_env(monkeypatch, tmp_path, installed_at=code)
    assert 'runtime_dir = "./runtime"' in toml.read_text(encoding="utf-8")
    home = (Path(local_appdata(tmp_path)["LOCALAPPDATA"]) / "CIRCOE" / "Jarvis").resolve()
    loaded = AppConfig.load(toml)
    assert loaded.runtime.runtime_dir == home / "runtime"  # pas `<cwd>/runtime`
    assert loaded.runtime.memory_dir == home / "data" / "memory"
    assert not (home / "data" / "memory" / "long_term_memory" / "note.md").exists()  # dossier du programme jamais repris
    # Une valeur TOML absolue est un choix d'administration, respecté ; la variable passe toujours devant.
    toml.write_text(toml.read_text(encoding="utf-8").replace('runtime_dir = "./runtime"',
                    f"runtime_dir = '{tmp_path / 'admin-rt'}'"), encoding="utf-8")
    assert AppConfig.load(toml).runtime.runtime_dir == (tmp_path / "admin-rt").resolve()
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path / "env-rt"))
    assert AppConfig.load(toml).runtime.runtime_dir == (tmp_path / "env-rt").resolve()


def test_app_config_in_development_keeps_the_toml_runtime_under_the_cwd(tmp_path, monkeypatch):
    from jarvis.config import AppConfig

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    toml = app_config_env(monkeypatch, tmp_path, installed_at=checkout)
    assert AppConfig.load(toml).runtime.runtime_dir == (tmp_path / "runtime").resolve()


def test_a_global_context_copy_failure_is_reported_and_the_rest_of_the_adoption_stands(tmp_path, monkeypatch):
    legacy, target = tmp_path / "repo" / "data", tmp_path / "home" / "data"
    (legacy / "state").mkdir(parents=True)
    conn = sqlite3.connect(legacy / "state" / "jarvis.sqlite3")
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    seeded_global_context(legacy)

    def refuse(source, staging):
        raise UnsafeTree("current_task", "symbolic link, junction or reparse point refused")

    monkeypatch.setattr(data_root, "copy_tree", refuse)
    report = adopt_legacy_data(target, legacy)
    assert "state/jarvis.sqlite3" in report.databases
    assert any(item.startswith(f"{GLOBAL_CONTEXT_DIR}: non repris") and "junction" in item for item in report.skipped)
    assert not (target / GLOBAL_CONTEXT_DIR).exists()
    assert (legacy / GLOBAL_CONTEXT_DIR / "user_habits.md").is_file()
    assert not list(target.glob(f".{GLOBAL_CONTEXT_DIR}.adopting-*"))


def test_the_guard_resolves_dotdot_and_case_and_ignores_an_ancestor_of_the_allowed_root(tmp_path):
    from jarvis.adapters.global_context import is_global_context_path

    data = tmp_path / "data"
    context = seeded_global_context(data)
    sneaky = data / "prefabs" / ".." / "context_global" / "user_habits.md"
    assert is_global_context_path(sneaky) and is_global_context_path(sneaky, within=data)
    with pytest.raises(GlobalContextProtected):
        _remove_tree(data / "prefabs" / ".." / "Context_Global")
    with pytest.raises(UnsafeTree):
        remove_tree(data / "prefabs" / ".." / GLOBAL_CONTEXT_DIR, within=data)
    # Un ANCÊTRE de la racine nommé CONTEXT_GLOBAL ne bloque pas une purge légitime sous cette racine.
    odd_root = tmp_path / GLOBAL_CONTEXT_DIR / "jarvis-data"
    (odd_root / "prefabs" / ".archive" / "p" / "1").mkdir(parents=True)
    (odd_root / "prefabs" / ".archive" / "p" / "1" / "manifest.json").write_text("{}", encoding="utf-8")
    assert not is_global_context_path(odd_root / "prefabs" / ".archive" / "p", within=odd_root)
    remove_tree(odd_root / "prefabs" / ".archive" / "p", within=odd_root)
    assert not (odd_root / "prefabs" / ".archive" / "p").exists()
    assert (context / "user_habits.md").is_file()


def test_the_guard_sees_through_windows_short_names(tmp_path):
    if os.name != "nt":
        pytest.skip("noms courts 8.3 : Windows seulement")
    import ctypes

    context = seeded_global_context(tmp_path / "data")
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(context), buffer, 1024):
        pytest.skip("GetShortPathNameW indisponible")
    short = Path(buffer.value)
    if short.name.casefold() == GLOBAL_CONTEXT_DIR.casefold():
        pytest.skip("noms courts 8.3 désactivés sur ce volume")
    with pytest.raises(GlobalContextProtected):
        ensure_not_global_context(short / "user_habits.md")
    with pytest.raises(GlobalContextProtected):
        _remove_tree(short)
    assert (context / "user_habits.md").is_file()


def test_the_remotion_cache_purge_refuses_a_folder_that_contains_global_context(tmp_path):
    from jarvis.adapters.remotion_compiler import RemotionCompiler

    data = tmp_path / "data"
    context = seeded_global_context(data)
    assert RemotionCompiler._remove_tree(data) is False
    assert RemotionCompiler._remove_tree(context / "user_habits.md") is False
    assert (context / "user_habits.md").is_file()
    cache = data / "local_capabilities" / "remotion" / "compiled" / "k1"
    cache.mkdir(parents=True)
    (cache / "bundle.js").write_text("x", encoding="utf-8")
    assert RemotionCompiler._remove_tree(cache) is True and not cache.exists()


def test_the_feedback_log_label_names_no_user_path(tmp_path):
    from jarvis.runtime.feedback_sessions import feedback_dir_label

    code = installed_code(tmp_path / "program")
    env = local_appdata(tmp_path)
    directory = Path(env["LOCALAPPDATA"]) / "CIRCOE" / "Jarvis" / "data" / "retours-utilisateur" / "1789654261"
    assert feedback_dir_label(directory, env) == "<dépôt>/retours-utilisateur/1789654261"  # CODE_ROOT réel : checkout
    assert feedback_dir_label(directory, env | {"JARVIS_DATA_ROOT": str(tmp_path)}) == \
        "<JARVIS_DATA_ROOT>/retours-utilisateur/1789654261"
    import jarvis.installation as inst
    original = inst.CODE_ROOT
    try:
        inst.CODE_ROOT = code
        label = feedback_dir_label(directory, env)
    finally:
        inst.CODE_ROOT = original
    assert label == r"%LOCALAPPDATA%\CIRCOE\Jarvis\data/retours-utilisateur/1789654261"
    assert "someone" not in label
