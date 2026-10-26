"""Secrets locaux de l'édition produit (jarvis-presentation-edition-v1, Slice 05, amendement E3).

Contrat : `jarvis/runtime/local_secrets.py`, `docs/product-connectors.md` › *Secrets*,
`docs/SECURITY.md` § 15b. Faux sceau (`FakeSealer`) et répertoires temporaires ; DPAPI réel
seulement pour l'aller-retour Windows de `secret_for`. Une valeur sentinelle prouve la non-fuite :
absente du fichier, des sauvegardes, des vues publiques et du journal.
"""

from __future__ import annotations

import json
import sys

import pytest

from jarvis.adapters.google_oauth import (
    _read_token_info, _store_token, migrate_plain_token, sealed_token_path, token_present,
)
from jarvis.installation import PRODUCT_MARKER, marker_payload
from jarvis.runtime import credentials as creds
from jarvis.runtime import local_secrets
from jarvis.runtime.control_center import ControlCenter
from tests.fakes.fake_sealer import FakeSealer

SENTINEL = "sk-SENTINEL-4291-abcd"
OTHER = "pk-OTHER-SENTINEL-9z"


class Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, message, dict(data or {})))


def _plain_settings() -> dict:
    settings: dict = {"porcupine_access_key": OTHER, "voice_stack": "openai"}
    creds.upsert_credential(settings, provider="openai", name="Perso", value=SENTINEL)
    return settings


# ------------------------------------------------------------------ quand sceller


def test_sealing_applies_to_presentation_and_to_any_installed_product(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    assert local_secrets.local_secrets_sealed({}, code_root=checkout) is False
    assert local_secrets.local_secrets_sealed({"JARVIS_PRODUCT_EDITION": "presentation"}, code_root=checkout)
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / PRODUCT_MARKER).write_text(json.dumps(marker_payload()), encoding="utf-8")
    env = {"JARVIS_PRODUCT_EDITION": "full", "LOCALAPPDATA": str(tmp_path / "appdata")}
    assert local_secrets.local_secrets_sealed(env, code_root=installed) is True


def test_google_token_options_follow_the_edition():
    full = local_secrets.google_token_options({"JARVIS_PRODUCT_EDITION": "full"})
    assert full == {"minimal_scopes": False, "sealer": None, "interactive": True}
    product = local_secrets.google_token_options({"JARVIS_PRODUCT_EDITION": "presentation"})
    assert product["minimal_scopes"] is True and product["sealer"] is not None


# ------------------------------------------------------------------ magasin de clés


def test_seal_settings_removes_every_plaintext_and_keeps_the_hint():
    sealer = FakeSealer()
    settings = _plain_settings()
    assert local_secrets.seal_settings(settings, sealer) == 2
    text = json.dumps(settings)
    assert SENTINEL not in text and OTHER not in text and "porcupine_access_key" not in settings
    by_provider = {item["provider"]: item for item in settings["credentials"]}
    assert "value" not in by_provider["openai"] and by_provider["openai"]["hint"] == "…abcd"
    assert creds.entry_value(by_provider["openai"], sealer) == SENTINEL
    assert creds.entry_value(by_provider["porcupine"], sealer) == OTHER
    assert local_secrets.seal_settings(settings, sealer) == 0  # idempotent


def test_seal_settings_without_a_vault_refuses_and_changes_nothing():
    settings = _plain_settings()
    before = json.dumps(settings, sort_keys=True)
    with pytest.raises(local_secrets.LocalSecretsError) as refused:
        local_secrets.seal_settings(settings, FakeSealer(available=False))
    assert refused.value.code == "credential_vault_unavailable"
    assert json.dumps(settings, sort_keys=True) == before


def test_public_views_of_a_sealed_store_carry_no_secret():
    sealer = FakeSealer()
    settings = _plain_settings()
    local_secrets.seal_settings(settings, sealer)
    views = creds.list_credentials(settings)
    assert all(view["sealed"] is True for view in views)
    state = json.dumps(creds.credentials_state(settings))
    assert SENTINEL not in state and OTHER not in state and "blob" not in state


def test_an_unreadable_sealed_key_reads_as_absent_and_is_flagged():
    settings = _plain_settings()
    local_secrets.seal_settings(settings, FakeSealer())
    settings["credentials"][0]["sealed"]["blob"] = "AAAA"  # copié d'un autre poste / altéré
    assert creds.entry_value(settings["credentials"][0], FakeSealer()) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI réel")
def test_secret_for_reads_a_dpapi_sealed_key_in_any_process(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = _plain_settings()
    local_secrets.seal_settings(settings, local_secrets.credential_sealer())
    assert SENTINEL not in json.dumps(settings)
    assert creds.secret_for(settings, "openai") == SENTINEL
    # Un blob du coffre MCP (autre entropie) ne se descelle pas comme clé API.
    from jarvis.adapters.dpapi_sealer import default_sealer

    other = local_secrets.seal_value(SENTINEL, default_sealer())
    assert creds.entry_value({"sealed": other}) == ""


def test_updating_a_sealed_key_replaces_its_blob():
    sealer = FakeSealer()
    settings = _plain_settings()
    local_secrets.seal_settings(settings, sealer)
    key_id = next(item["id"] for item in settings["credentials"] if item["provider"] == "openai")
    creds.upsert_credential(settings, credential_id=key_id, provider="openai", name="Perso", value="sk-new-0001")
    local_secrets.seal_settings(settings, sealer)
    item = next(item for item in settings["credentials"] if item["id"] == key_id)
    assert creds.entry_value(item, sealer) == "sk-new-0001" and "sk-new-0001" not in json.dumps(settings)


# ------------------------------------------------------------------ migration copie d'abord


def test_settings_file_migration_backs_up_sealed_then_seals(tmp_path):
    sealer, journal = FakeSealer(), Journal()
    path = tmp_path / "control-center-settings.json"
    original = (json.dumps(_plain_settings(), indent=2) + "\n").encode("utf-8")
    path.write_bytes(original)
    assert local_secrets.migrate_settings_file(path, sealer, journal.emit) == 2
    backup = path.with_name(path.name + local_secrets.BACKUP_SUFFIX)
    assert SENTINEL.encode() not in path.read_bytes() and SENTINEL.encode() not in backup.read_bytes()
    assert local_secrets.unseal_backup(backup, sealer) == original  # retour arrière possible
    assert json.loads(path.read_text(encoding="utf-8"))["voice_stack"] == "openai"
    assert [event[0] for event in journal.events] == ["secrets.migrated"]
    assert SENTINEL not in json.dumps(journal.events) and "…abcd" not in json.dumps(journal.events)
    assert local_secrets.migrate_settings_file(path, sealer, journal.emit) == 0


def test_settings_file_migration_without_a_vault_touches_nothing(tmp_path):
    journal = Journal()
    path = tmp_path / "control-center-settings.json"
    path.write_text(json.dumps(_plain_settings()), encoding="utf-8")
    before = path.read_bytes()
    assert local_secrets.migrate_settings_file(path, FakeSealer(available=False), journal.emit) == 0
    assert path.read_bytes() == before and journal.events[0][0] == "secrets.migration_skipped"
    assert not path.with_name(path.name + local_secrets.BACKUP_SUFFIX).exists()


def test_env_file_migration_moves_only_provider_keys(tmp_path):
    sealer, journal = FakeSealer(), Journal()
    env = tmp_path / ".env"
    env.write_text(f"# produit\nOPENAI_API_KEY={SENTINEL}\nJARVIS_VOICE_STACK=openai\n"
                   f"export PORCUPINE_ACCESS_KEY='{OTHER}'\n", encoding="utf-8")
    settings_path = tmp_path / "runtime" / "control-center-settings.json"
    assert local_secrets.migrate_env_file(env, settings_path, sealer, journal.emit) == 2
    assert env.read_text(encoding="utf-8") == "# produit\nJARVIS_VOICE_STACK=openai\n"
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert SENTINEL not in json.dumps(stored) and OTHER not in json.dumps(stored)
    assert {creds.entry_value(item, sealer) for item in stored["credentials"]} == {SENTINEL, OTHER}
    assert local_secrets.unseal_backup(env.with_name(".env" + local_secrets.BACKUP_SUFFIX), sealer).startswith(
        b"# produit")
    assert SENTINEL not in json.dumps(journal.events)


# ------------------------------------------------------------------ Control Center


def _center(tmp_path, *, seal, sealer=None) -> ControlCenter:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return ControlCenter(runtime_root=runtime, project_root=tmp_path, seal_local_secrets=seal,
                         secret_sealer=sealer)


def test_control_center_in_product_mode_never_writes_a_plaintext_key(tmp_path):
    center = _center(tmp_path, seal=True, sealer=FakeSealer())
    settings = center._settings()
    creds.upsert_credential(settings, provider="openai", name="Perso", value=SENTINEL)
    center._write_settings(settings)
    assert SENTINEL not in center.settings_path.read_text(encoding="utf-8")
    trace = (tmp_path / "runtime" / "trace.jsonl").read_text(encoding="utf-8")
    assert "secrets.sealed" in trace and SENTINEL not in trace


def test_control_center_in_product_mode_without_vault_refuses_the_write(tmp_path):
    from aiohttp import web

    center = _center(tmp_path, seal=True, sealer=FakeSealer(available=False))
    settings = center._settings()
    creds.upsert_credential(settings, provider="openai", name="Perso", value=SENTINEL)
    with pytest.raises(web.HTTPServiceUnavailable):
        center._write_settings(settings)
    assert not center.settings_path.exists()


def test_control_center_in_development_keeps_the_plaintext_store(tmp_path):
    center = _center(tmp_path, seal=False)
    settings = center._settings()
    creds.upsert_credential(settings, provider="openai", name="Perso", value=SENTINEL)
    center._write_settings(settings)
    assert SENTINEL in center.settings_path.read_text(encoding="utf-8")


def test_control_center_start_migration_seals_a_previous_plaintext_file(tmp_path):
    sealer = FakeSealer()
    center = _center(tmp_path, seal=True, sealer=sealer)
    center.settings_path.write_text(json.dumps(_plain_settings()), encoding="utf-8")
    center._migrate_local_secrets()
    assert SENTINEL not in center.settings_path.read_text(encoding="utf-8")
    assert creds.secret_for(json.loads(center.settings_path.read_text(encoding="utf-8")), "custom") == ""


# ------------------------------------------------------------------ jetons Google


def test_a_plaintext_google_token_is_copied_sealed_then_removed(tmp_path):
    sealer = FakeSealer()
    token = tmp_path / "drive-token.json"
    token.write_text(json.dumps({"refresh_token": SENTINEL, "client_id": "c"}), encoding="utf-8")
    assert migrate_plain_token(token, sealer) is True
    assert not token.exists() and token_present(token)
    assert SENTINEL.encode() not in sealed_token_path(token).read_bytes()
    assert _read_token_info(token, sealer)["refresh_token"] == SENTINEL


def test_a_token_that_does_not_reread_stays_in_plaintext(tmp_path):
    class Broken(FakeSealer):
        def unseal(self, blob):
            return b"something else"

    token = tmp_path / "drive-token.json"
    token.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError):
        migrate_plain_token(token, Broken())
    assert token.exists() and not sealed_token_path(token).exists()


def test_sealed_token_storage_never_writes_plaintext(tmp_path):
    sealer = FakeSealer()
    token = tmp_path / "calendar-token.json"
    _store_token(token, json.dumps({"refresh_token": SENTINEL}), sealer)
    assert not token.exists() and SENTINEL.encode() not in sealed_token_path(token).read_bytes()
    _store_token(token, json.dumps({"refresh_token": "dev"}), None)
    assert json.loads(token.read_text(encoding="utf-8")) == {"refresh_token": "dev"}  # développement : inchangé


def test_two_keys_of_one_provider_in_env_and_backups_never_overwrite(tmp_path):
    sealer = FakeSealer()
    env = tmp_path / ".env"
    env.write_text("GOOGLE_API_KEY=AIza-one-1111\nGEMINI_API_KEY=AIza-two-2222\n", encoding="utf-8")
    settings_path = tmp_path / "control-center-settings.json"
    settings_path.write_text(json.dumps(_plain_settings()), encoding="utf-8")
    assert local_secrets.migrate_settings_file(settings_path, sealer) == 2
    assert local_secrets.migrate_env_file(env, settings_path, sealer) == 2
    backups = sorted(path.name for path in tmp_path.iterdir() if "plain-backup" in path.name)
    assert backups == [".env.plain-backup.dpapi", "control-center-settings.json.plain-backup.2.dpapi",
                       "control-center-settings.json.plain-backup.dpapi"]
    first = json.loads(local_secrets.unseal_backup(tmp_path / "control-center-settings.json.plain-backup.dpapi",
                                                   sealer))
    assert creds.entry_value(first["credentials"][0]) == SENTINEL  # la sauvegarde d'origine est intacte
    stored = json.loads(settings_path.read_text(encoding="utf-8"))["credentials"]
    assert {creds.entry_value(item, sealer) for item in stored if item["provider"] == "google"} == {
        "AIza-one-1111", "AIza-two-2222"}


# ------------------------------------------------------------------ reprise QA : parseur .env canonique (B1)


def test_env_migration_uses_the_canonical_parser_for_comments_quotes_export_and_spaces(tmp_path):
    sealer = FakeSealer()
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-abc  # ma cle perso\n"
                   'DEEPGRAM_API_KEY="dg-1" # c\n'
                   "export ANTHROPIC_API_KEY='sk-ant-#1'\n"
                   "  ELEVENLABS_API_KEY =  el-2  \n"
                   "PORCUPINE_ACCESS_KEY=#vide\n"
                   "JARVIS_VOICE_STACK=openai # garde\n", encoding="utf-8")
    settings_path = tmp_path / "control-center-settings.json"
    assert local_secrets.migrate_env_file(env, settings_path, sealer) == 4
    stored = json.loads(settings_path.read_text(encoding="utf-8"))["credentials"]
    assert {item["provider"]: creds.entry_value(item, sealer) for item in stored} == {
        "openai": "sk-abc", "deepgram": "dg-1", "anthropic": "sk-ant-#1", "elevenlabs": "el-2"}
    # Les lignes reprises disparaissent ; la clé vide et les réglages restent tels quels.
    assert env.read_text(encoding="utf-8") == "PORCUPINE_ACCESS_KEY=#vide\nJARVIS_VOICE_STACK=openai # garde\n"


def test_env_migration_refuses_an_unreadable_env_and_touches_nothing(tmp_path):
    from jarvis.domain.errors import ConfigurationError

    env = tmp_path / ".env"
    env.write_text('OPENAI_API_KEY="sk-open\n', encoding="utf-8")
    before = env.read_bytes()
    with pytest.raises(ConfigurationError):
        local_secrets.migrate_env_file(env, tmp_path / "settings.json", FakeSealer())
    assert env.read_bytes() == before and not (tmp_path / "settings.json").exists()


def test_the_startup_loader_and_the_migration_share_one_parser(monkeypatch, tmp_path):
    from jarvis import environment

    env = tmp_path / ".env"
    env.write_text('DEEPGRAM_API_KEY="dg-1" # c\n', encoding="utf-8")
    monkeypatch.setattr(environment, "project_environment_file", lambda: env)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    environment.load_project_environment()
    import os

    assert os.environ["DEEPGRAM_API_KEY"] == "dg-1"
    monkeypatch.delenv("DEEPGRAM_API_KEY")


def test_an_identical_backup_is_never_duplicated(tmp_path):
    sealer = FakeSealer()
    path = tmp_path / "f.json"
    path.write_text("{}", encoding="utf-8")
    first = local_secrets.backup_sealed(path, sealer)
    assert local_secrets.backup_sealed(path, sealer) == first
    path.write_text('{"a": 1}', encoding="utf-8")
    assert local_secrets.backup_sealed(path, sealer).name == "f.json.plain-backup.2.dpapi"
    assert len(list(tmp_path.glob("*.dpapi"))) == 2


def test_support_restore_writes_the_original_and_never_overwrites(tmp_path):
    sealer = FakeSealer()
    path = tmp_path / "control-center-settings.json"
    original = json.dumps(_plain_settings()).encode("utf-8")
    path.write_bytes(original)
    local_secrets.migrate_settings_file(path, sealer)
    backup = path.with_name(path.name + local_secrets.BACKUP_SUFFIX)
    out = local_secrets.restore_backup(backup, tmp_path / "restored.json", sealer)
    assert out.read_bytes() == original
    with pytest.raises(FileExistsError):
        local_secrets.restore_backup(backup, out, sealer)


def test_the_cli_exposes_the_support_restore():
    from jarvis.app import _parser

    args = _parser().parse_args(["secrets-restore", "a.plain-backup.dpapi", "out.json"])
    assert (args.command, args.backup, args.out) == ("secrets-restore", "a.plain-backup.dpapi", "out.json")


# ------------------------------------------------------------------ reprise QA : portées du jeton (B3)


FULL_DRIVE = {"token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s",
              "token_uri": "https://oauth2.googleapis.com/token", "scopes": ["https://www.googleapis.com/auth/drive"],
              "expiry": "2999-01-01T00:00:00Z"}
MINIMAL_DRIVE = ("https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file")


def test_token_covers_reads_the_scopes_recorded_in_the_token():
    from jarvis.adapters.google_oauth import granted_scopes, token_covers

    assert token_covers(FULL_DRIVE, ("https://www.googleapis.com/auth/drive",))
    assert not token_covers(FULL_DRIVE, MINIMAL_DRIVE)  # `drive` ne vaut pas `drive.readonly` + `drive.file`
    assert granted_scopes({"scopes": "a b"}) == ("a", "b") and not token_covers(None, MINIMAL_DRIVE)


def test_a_full_scope_token_requires_a_new_consent_for_minimal_scopes(tmp_path):
    from jarvis.adapters.google_oauth import GoogleAuthorizationRequired, load_credentials

    token = tmp_path / "drive-token.json"
    token.write_text(json.dumps(FULL_DRIVE), encoding="utf-8")
    secret = tmp_path / "client.json"
    # Avant la reprise, `from_authorized_user_info(info, wanted)` écrasait les portées : ce jeton passait.
    with pytest.raises(GoogleAuthorizationRequired):
        load_credentials(secret, token, MINIMAL_DRIVE, interactive=False)
    creds = load_credentials(secret, token, ("https://www.googleapis.com/auth/drive",), interactive=False)
    assert list(creds.scopes) == ["https://www.googleapis.com/auth/drive"]  # portées du jeton, pas demandées


def test_no_token_in_product_mode_is_an_authorization_requirement(tmp_path):
    from jarvis.adapters.google_oauth import GoogleAuthorizationRequired, load_credentials

    with pytest.raises(GoogleAuthorizationRequired):
        load_credentials(tmp_path / "c.json", tmp_path / "t.json", MINIMAL_DRIVE, sealer=FakeSealer(),
                         interactive=False)


def test_core_records_a_missing_google_consent_instead_of_failing(monkeypatch):
    from jarvis import app
    from jarvis.adapters.google_oauth import GoogleAuthorizationRequired

    def build():
        raise GoogleAuthorizationRequired("consent")

    monkeypatch.setattr(app, "_GOOGLE_AUTHORIZATION_REQUIRED", set())
    assert app._google_backend("google_drive", build) is None
    assert app._GOOGLE_AUTHORIZATION_REQUIRED == {"google_drive"}


def test_product_token_options_never_open_a_browser():
    assert local_secrets.google_token_options({"JARVIS_PRODUCT_EDITION": "presentation"})["interactive"] is False
    assert local_secrets.google_token_options({"JARVIS_PRODUCT_EDITION": "full"})["interactive"] is True
