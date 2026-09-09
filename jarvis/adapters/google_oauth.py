from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence


def load_credentials(client_secret_file: Path, token_file: Path, scopes: Sequence[str]) -> Any:
    """Charger (et rafraîchir) des identifiants OAuth « installed app ».

    Le jeton est lié aux portées demandées : Agenda et Drive partagent le même
    client Google mais gardent chacun leur fichier de jeton, sinon un accès
    élargi d'un côté invaliderait silencieusement l'autre.
    """
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Google support requires the google optional dependencies") from exc

    wanted = tuple(scopes)
    creds = Credentials.from_authorized_user_file(str(token_file), wanted) if token_file.exists() else None
    if creds and creds.valid and _covers(creds, wanted):
        return creds
    if creds and creds.expired and creds.refresh_token and _covers(creds, wanted):
        creds.refresh(Request())
    else:
        if not client_secret_file.is_file():
            raise RuntimeError(f"Google client secret file not found: {client_secret_file}")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), list(wanted))
        creds = flow.run_local_server(port=0)
    _write_token(token_file, creds.to_json())
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


def build_service(api: str, version: str, credentials: Any) -> Any:
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Google support requires the google optional dependencies") from exc
    return build(api, version, credentials=credentials, cache_discovery=False)
