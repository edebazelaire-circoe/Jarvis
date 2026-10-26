"""Secrets locaux de l'édition produit : clés API et jetons Google scellés par DPAPI (amendement E3, Slice 05).

Contrat : `docs/product-connectors.md` › *Secrets* et `docs/SECURITY.md` § 15b.

**Quand.** `local_secrets_sealed()` : la politique de connecteurs de l'édition le demande
(`presentation`) **ou** le code tourne comme produit installé (`jarvis/installation.py`), quelle que
soit l'édition. Un checkout de développement en `full` garde le stockage en clair d'avant.

**Quoi.**

- Clés API du Control Center (`control-center-settings.json`, `credentials`) : une entrée scellée
  porte `sealed: {scheme, purpose, blob}` et son indice `hint`, jamais `value`. Les anciens champs
  plats (`openai_api_key`…) sont repris dans le magasin puis retirés. Lecture : `credentials.entry_value`
  descelle à la demande, dans tout processus JARVIS du même utilisateur Windows.
- Jetons Google OAuth : `<jeton>.dpapi` (`jarvis/adapters/google_oauth.py`).
- `.env` du produit installé (`<maison>\\config\\.env`) : les variables de clé des fournisseurs connus
  sont reprises dans le magasin scellé puis retirées du fichier.

**Copie d'abord.** Aucune valeur en clair n'est retirée avant que sa copie scellée soit écrite, relue
et comparée. Le fichier d'origine est d'abord sauvegardé **scellé en entier**
(`<fichier>.plain-backup.dpapi`) : la sauvegarde ne laisse aucun clair sur disque, et un retour
arrière reste possible sur ce poste (`unseal_backup`). Coffre indisponible : rien n'est touché, et
une écriture qui produirait un clair est refusée (`credential_vault_unavailable`) — jamais de repli
en clair.

**Journal.** Compteurs, fournisseurs, chemins relatifs à la racine d'exécution : jamais une valeur,
un indice, ni un blob.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
from typing import Any, Protocol

from jarvis.adapters.dpapi_sealer import DPAPI_SCHEME, default_sealer
from jarvis.domain.product_connectors import GoogleScopeProfile, connector_policy

#: Entropies DPAPI par usage : un blob d'un usage ne se descelle pas dans un autre (ni dans le coffre MCP).
CREDENTIALS_ENTROPY = b"jarvis-credentials-v1"
GOOGLE_TOKEN_ENTROPY = b"jarvis-google-oauth-v1"
CREDENTIALS_PURPOSE = "credentials-v1"
BACKUP_SUFFIX = ".plain-backup.dpapi"
VAULT_UNAVAILABLE = "credential_vault_unavailable"


class Sealer(Protocol):
    available: bool

    def seal(self, plaintext: bytes) -> bytes: ...

    def unseal(self, blob: bytes) -> bytes: ...


class LocalSecretsError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def local_secrets_sealed(environ: Mapping[str, str] | None = None, *, code_root=None) -> bool:
    """Vrai pour l'édition `presentation` et pour tout produit installé (voir l'en-tête)."""

    from jarvis.installation import detect_installation
    from jarvis.runtime.product_edition_env import process_edition

    env = os.environ if environ is None else environ
    if connector_policy(process_edition(env, code_root=code_root)).seal_local_secrets:
        return True
    return detect_installation(env, code_root=code_root).installed


def credential_sealer() -> Sealer:
    return default_sealer(CREDENTIALS_ENTROPY)


def google_token_options(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Arguments de `Google*Backend.from_oauth_files` pour ce processus : portées et stockage du jeton."""

    from jarvis.runtime.product_edition_env import process_edition

    env = os.environ if environ is None else environ
    minimal = connector_policy(process_edition(env)).google_scopes is GoogleScopeProfile.MINIMAL
    sealed = local_secrets_sealed(env)
    return {"minimal_scopes": minimal or sealed, "sealer": default_sealer(GOOGLE_TOKEN_ENTROPY) if sealed else None}


# ------------------------------------------------------------------ entrées du magasin de clés


def seal_value(value: str, sealer: Sealer) -> dict[str, str]:
    blob = sealer.seal(value.encode("utf-8"))
    return {"scheme": DPAPI_SCHEME, "purpose": CREDENTIALS_PURPOSE, "blob": base64.b64encode(blob).decode("ascii")}


def unseal_value(sealed: object, sealer: Sealer) -> str:
    """Valeur d'une entrée scellée ; `ValueError` si le blob est d'un autre schéma, altéré ou d'un autre poste."""

    if not isinstance(sealed, Mapping) or sealed.get("scheme") != DPAPI_SCHEME or not isinstance(
            sealed.get("blob"), str):
        raise ValueError("sealed credential has an unknown shape")
    try:
        return sealer.unseal(base64.b64decode(sealed["blob"], validate=True)).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - SealerError, binascii.Error, UnicodeError : même verdict, illisible
        raise ValueError(f"sealed credential unreadable ({type(exc).__name__})") from None


def plaintext_secret_count(settings: Mapping[str, Any]) -> int:
    """Combien de valeurs en clair le document porte (entrées `value`, anciens champs plats)."""

    from jarvis.runtime.credentials import LEGACY_KEYS

    entries = settings.get("credentials") if isinstance(settings.get("credentials"), list) else []
    plain = sum(1 for item in entries if isinstance(item, dict) and str(item.get("value") or "").strip())
    return plain + sum(1 for key in LEGACY_KEYS if str(settings.get(key) or "").strip())


def seal_settings(settings: dict[str, Any], sealer: Sealer) -> int:
    """Scelle en place chaque valeur en clair du document de réglages ; rend le nombre de valeurs scellées.

    Anciens champs plats : repris d'abord dans le magasin (`migrate_legacy`), puis retirés. Chaque
    valeur scellée est relue avant que le clair disparaisse. Coffre indisponible avec du clair :
    `LocalSecretsError(credential_vault_unavailable)`, document inchangé.
    """

    from jarvis.runtime.credentials import LEGACY_KEYS, migrate_legacy, redact

    if not plaintext_secret_count(settings):
        return 0
    if not sealer.available:
        raise LocalSecretsError(VAULT_UNAVAILABLE, "Coffre de secrets indisponible : clé non enregistrée en clair.")
    migrate_legacy(settings, sealer)
    sealed_count = 0
    sealed_entries: list[tuple[dict[str, Any], dict[str, str], str]] = []
    for item in settings.get("credentials", []):
        value = str(item.get("value") or "").strip() if isinstance(item, dict) else ""
        if not value:
            continue
        sealed = seal_value(value, sealer)
        if unseal_value(sealed, sealer) != value:
            raise LocalSecretsError(VAULT_UNAVAILABLE, "Relecture de la clé scellée différente : rien n'est changé.")
        sealed_entries.append((item, sealed, redact(value)))
    for item, sealed, hint in sealed_entries:
        item.pop("value", None)
        item["sealed"] = sealed
        item["hint"] = hint
        sealed_count += 1
    for key in LEGACY_KEYS:
        if str(settings.get(key) or "").strip():
            settings.pop(key, None)
    return sealed_count


# ------------------------------------------------------------------ fichiers


def _atomic_write(path: Path, payload: bytes) -> None:
    from jarvis.adapters.file_replace import replace_with_retry

    tmp = path.with_name(path.name + ".seal.tmp")
    tmp.write_bytes(payload)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    try:
        replace_with_retry(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def backup_sealed(path: Path, sealer: Sealer) -> Path:
    """Copie scellée du fichier entier (`<fichier>.plain-backup.dpapi`), relue avant d'être rendue.

    N'écrase jamais une sauvegarde existante : la suivante prend `<fichier>.plain-backup.<n>.dpapi`.
    """

    raw = path.read_bytes()
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    index = 2
    while backup.exists():
        backup = path.with_name(f"{path.name}.plain-backup.{index}.dpapi")
        index += 1
    _atomic_write(backup, sealer.seal(raw))
    if sealer.unseal(backup.read_bytes()) != raw:
        raise LocalSecretsError(VAULT_UNAVAILABLE, "Sauvegarde scellée illisible : rien n'est changé.")
    return backup


def unseal_backup(backup: Path, sealer: Sealer) -> bytes:
    """Retour arrière manuel : le contenu d'origine d'une sauvegarde scellée (même poste, même utilisateur)."""

    return sealer.unseal(Path(backup).read_bytes())


Emit = Callable[..., None]


def migrate_settings_file(path: Path, sealer: Sealer, emit: Emit | None = None) -> int:
    """Scelle les clés en clair de `control-center-settings.json` (copie d'abord). Rend le nombre scellé."""

    path = Path(path)
    if not path.is_file():
        return 0
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if emit:
            emit("secrets.migration_skipped", "Réglages illisibles : clés non scellées", level="warning",
                 data={"file": path.name, "error": type(exc).__name__})
        return 0
    if not isinstance(settings, dict) or not plaintext_secret_count(settings):
        return 0
    if not sealer.available:
        if emit:
            emit("secrets.migration_skipped", "Coffre de secrets indisponible : clés laissées en clair",
                 level="error", data={"file": path.name, "code": VAULT_UNAVAILABLE})
        return 0
    backup = backup_sealed(path, sealer)
    count = seal_settings(settings, sealer)
    _atomic_write(path, (json.dumps(settings, indent=2) + "\n").encode("utf-8"))
    if emit:
        emit("secrets.migrated", "Clés API scellées dans le coffre local", data={
            "file": path.name, "sealed": count, "backup": backup.name})
    return count


def migrate_env_file(env_path: Path, settings_path: Path, sealer: Sealer, emit: Emit | None = None) -> int:
    """`.env` du produit installé : reprend les clés des fournisseurs dans le magasin scellé, puis les retire.

    Seules les lignes `NOM=valeur` dont `NOM` est une variable de clé d'un fournisseur
    (`credentials.PROVIDERS[*].env`) sont concernées ; les autres lignes restent telles quelles.
    Rend le nombre de clés reprises.
    """

    from jarvis.runtime.credentials import PROVIDERS, entry_value, upsert_credential

    env_path, settings_path = Path(env_path), Path(settings_path)
    if not env_path.is_file():
        return 0
    names = {name: spec.id for spec in PROVIDERS for name in spec.env}
    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    found: list[tuple[int, str, str, str]] = []
    for index, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        value = value.strip().strip("'\"")
        if separator and name.strip() in names and value:
            found.append((index, names[name.strip()], value, name.strip()))
    if not found:
        return 0
    if not sealer.available:
        if emit:
            emit("secrets.migration_skipped", "Coffre de secrets indisponible : .env laissé en clair",
                 level="error", data={"file": env_path.name, "code": VAULT_UNAVAILABLE})
        return 0
    settings: dict[str, Any] = {}
    if settings_path.is_file():
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        settings = loaded if isinstance(loaded, dict) else {}
        backup_sealed(settings_path, sealer)
    backup = backup_sealed(env_path, sealer)
    entries = settings.get("credentials") if isinstance(settings.get("credentials"), list) else []
    for _, provider, value, variable in found:
        known = [entry_value(item, sealer) for item in entries
                 if isinstance(item, dict) and item.get("provider") == provider]
        if value not in known:
            # Le nom de la variable distingue deux clés d'un même fournisseur (GOOGLE_API_KEY, GEMINI_API_KEY).
            upsert_credential(settings, provider=provider, name=f"Reprise du .env ({variable})"[:60], value=value)
            entries = settings["credentials"]
    seal_settings(settings, sealer)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(settings_path, (json.dumps(settings, indent=2) + "\n").encode("utf-8"))
    # Les clés sont relues scellées avant que le .env les perde.
    reread = json.loads(settings_path.read_text(encoding="utf-8"))
    stored = {entry_value(item, sealer) for item in reread.get("credentials", []) if isinstance(item, dict)}
    if any(value not in stored for _, _, value, _ in found):
        raise LocalSecretsError(VAULT_UNAVAILABLE, "Clés du .env absentes du coffre après écriture : .env conservé.")
    dropped = {index for index, _, _, _ in found}
    kept = [line for index, line in enumerate(lines) if index not in dropped]
    _atomic_write(env_path, ("\n".join(kept) + ("\n" if kept else "")).encode("utf-8"))
    if emit:
        emit("secrets.env_migrated", "Clés du .env reprises dans le coffre local", data={
            "file": env_path.name, "moved": len(found), "providers": sorted({p for _, p, _, _ in found}),
            "backup": backup.name})
    return len(found)
