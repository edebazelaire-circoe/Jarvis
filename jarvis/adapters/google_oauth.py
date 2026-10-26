"""Identifiants Google OAuth « installed app » (Agenda, Drive).

Deux stockages du jeton (`docs/product-connectors.md` › *Secrets*, Slice 05 presentation-edition) :

- **en clair** (développement, `sealer=None`) : le fichier JSON nommé par `.env`, comme avant ;
- **scellé** (édition produit, `sealer` fourni) : `<jeton>.dpapi`, blob DPAPI CurrentUser, jamais de
  clair sur disque. Un ancien jeton en clair est **d'abord copié** dans le blob, relu et comparé, et
  seulement alors supprimé (`migrate_plain_token`) ; un échec laisse le clair intact.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, Sequence

SEALED_SUFFIX = ".dpapi"


class TokenSealer(Protocol):
    available: bool

    def seal(self, plaintext: bytes) -> bytes: ...

    def unseal(self, blob: bytes) -> bytes: ...


def sealed_token_path(token_file: Path) -> Path:
    return token_file.with_name(token_file.name + SEALED_SUFFIX)


def token_present(token_file: Path) -> bool:
    """Un jeton existe-t-il, en clair ou scellé ?"""

    return token_file.is_file() or sealed_token_path(token_file).is_file()


def migrate_plain_token(token_file: Path, sealer: TokenSealer) -> bool:
    """Copie d'abord le jeton en clair dans son blob scellé, vérifie la relecture, puis supprime le clair.

    Rend `True` si une migration a eu lieu. Coffre indisponible : `RuntimeError`, clair intact.
    """

    if not token_file.is_file():
        return False
    if not sealer.available:
        raise RuntimeError("coffre DPAPI indisponible : le jeton Google ne peut pas être scellé")
    plain = token_file.read_bytes()
    sealed = sealed_token_path(token_file)
    _write_bytes(sealed, sealer.seal(plain))
    if sealer.unseal(sealed.read_bytes()) != plain:
        sealed.unlink(missing_ok=True)
        raise RuntimeError("jeton Google scellé illisible après écriture : le jeton en clair est conservé")
    token_file.unlink()
    return True


def _read_token_info(token_file: Path, sealer: TokenSealer | None) -> dict[str, Any] | None:
    import json

    if sealer is None:
        return json.loads(token_file.read_text(encoding="utf-8")) if token_file.exists() else None
    migrate_plain_token(token_file, sealer)
    sealed = sealed_token_path(token_file)
    if not sealed.is_file():
        return None
    return json.loads(sealer.unseal(sealed.read_bytes()).decode("utf-8"))


def _store_token(token_file: Path, payload: str, sealer: TokenSealer | None) -> None:
    if sealer is None:
        _write_token(token_file, payload)
        return
    _write_bytes(sealed_token_path(token_file), sealer.seal(payload.encode("utf-8")))


def load_credentials(client_secret_file: Path, token_file: Path, scopes: Sequence[str],
                     sealer: TokenSealer | None = None) -> Any:
    """Charger (et rafraîchir) des identifiants OAuth « installed app ».

    Le jeton est lié aux portées demandées : Agenda et Drive partagent le même
    client Google mais gardent chacun leur fichier de jeton, sinon un accès
    élargi d'un côté invaliderait silencieusement l'autre. Des portées
    différentes de celles accordées (passage aux portées minimales du produit)
    redemandent un consentement. `sealer` : stockage scellé (voir l'en-tête).
    """
    try:
        from google.auth.exceptions import TransportError  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Google support requires the google optional dependencies") from exc

    wanted = tuple(scopes)
    info = _read_token_info(token_file, sealer)
    creds = Credentials.from_authorized_user_info(info, wanted) if info is not None else None
    if creds and creds.valid and _covers(creds, wanted):
        return creds
    if creds and creds.expired and creds.refresh_token and _covers(creds, wanted):
        try:
            creds.refresh(Request())
        except TransportError:
            # Réseau coupé au démarrage : Core doit démarrer quand même. Le jeton
            # expiré n'est pas réécrit ; le client Google le rafraîchira à la
            # première requête réelle, quand le réseau sera revenu.
            return creds
    else:
        if not client_secret_file.is_file():
            raise RuntimeError(f"Google client secret file not found: {client_secret_file}")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), list(wanted))
        creds = flow.run_local_server(port=0)
    _store_token(token_file, creds.to_json(), sealer)
    return creds


def _covers(creds: Any, scopes: Sequence[str]) -> bool:
    """Un jeton conserve les portées accordées : les élargir exige un nouveau
    consentement, que `refresh` ne demande jamais."""
    granted = set(getattr(creds, "scopes", None) or ())
    return not granted or set(scopes).issubset(granted)


def _write_token(token_file: Path, payload: str) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = token_file.with_suffix(token_file.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, token_file)


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def build_service(api: str, version: str, credentials: Any) -> Any:
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Google support requires the google optional dependencies") from exc
    return build(api, version, credentials=credentials, cache_discovery=False)
