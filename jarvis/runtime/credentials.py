"""Magasin de clés API du Control Center.

Une clé n'est plus un champ de formulaire par service : c'est une entrée
nommée (`fournisseur`, `nom libre`, `valeur`) que l'on range une fois et que
l'on sélectionne ensuite dans chaque configuration qui en a besoin. Deux clés
OpenAI — une perso, une du travail — peuvent donc coexister, et changer celle
qu'utilise la voix ne demande pas de recoller la valeur.

La valeur en clair ne sort jamais d'ici : `list_credentials` ne rend qu'un
indice de fin de chaîne, et seuls les processus JARVIS appellent `secret_for`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import secrets
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: str
    label: str
    env: tuple[str, ...]
    placeholder: str
    hint: str


# Fournisseurs proposés dans l'onglet API Keys. `env` est la retombée lorsque
# aucune clé n'est enregistrée : le .env du projet reste une source valide.
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="openai",
        label="OpenAI",
        env=("OPENAI_API_KEY",),
        placeholder="sk-…",
        hint="Voix Realtime (ChatGPT Live), transcription, TTS, modèles Codex.",
    ),
    ProviderSpec(
        id="anthropic",
        label="Anthropic",
        env=("ANTHROPIC_API_KEY",),
        placeholder="sk-ant-…",
        hint="Sert à lister les modèles Claude réels. Le CLI Claude peut par ailleurs "
        "fonctionner sur abonnement, sans clé.",
    ),
    ProviderSpec(
        id="google",
        label="Google (Gemini)",
        env=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        placeholder="AIza…",
        hint="Voix Gemini Live et transcription Gemini.",
    ),
    ProviderSpec(
        id="porcupine",
        label="Porcupine",
        env=("PORCUPINE_ACCESS_KEY",),
        placeholder="Access key Picovoice",
        hint="Mot de réveil « Jarvis » toujours à l'écoute.",
    ),
    ProviderSpec(
        id="elevenlabs",
        label="ElevenLabs",
        env=("ELEVENLABS_API_KEY", "ELEVEN_API_KEY"),
        placeholder="Clé ElevenLabs",
        hint="Non branché sur la boucle vocale pour l'instant.",
    ),
    ProviderSpec(
        id="deepgram",
        label="Deepgram",
        env=("DEEPGRAM_API_KEY",),
        placeholder="Clé Deepgram",
        hint="Non branché sur la boucle vocale pour l'instant.",
    ),
    ProviderSpec(
        id="custom",
        label="Autre",
        env=(),
        placeholder="Valeur libre",
        hint="Rangée ici pour mémoire ; aucun service JARVIS ne la lit.",
    ),
)

PROVIDER_IDS: tuple[str, ...] = tuple(spec.id for spec in PROVIDERS)
_BY_ID: dict[str, ProviderSpec] = {spec.id: spec for spec in PROVIDERS}

# Anciens champs plats du Control Center, avant le magasin de clés.
LEGACY_KEYS: dict[str, str] = {
    "openai_api_key": "openai",
    "porcupine_access_key": "porcupine",
    "anthropic_api_key": "anthropic",
    "google_api_key": "google",
}

MAX_NAME_LENGTH = 60


class CredentialError(ValueError):
    """Refus explicite : le code accompagne le message pour l'interface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def provider_spec(provider: str) -> ProviderSpec:
    spec = _BY_ID.get(str(provider or "").strip().lower())
    if spec is None:
        raise CredentialError("credential_unknown_provider", f"Fournisseur inconnu : {provider}")
    return spec


def describe_providers() -> list[dict[str, Any]]:
    return [
        {"id": spec.id, "label": spec.label, "placeholder": spec.placeholder, "hint": spec.hint}
        for spec in PROVIDERS
    ]


def redact(value: str) -> str:
    """Indice suffisant pour reconnaître une clé, insuffisant pour la rejouer."""
    text = str(value or "")
    if len(text) <= 4:
        return "•" * len(text)
    return "…" + text[-4:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entries(settings: dict[str, Any]) -> list[dict[str, Any]]:
    raw = settings.get("credentials")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("id")]


def _bindings(settings: dict[str, Any]) -> dict[str, str]:
    raw = settings.get("credential_bindings")
    return dict(raw) if isinstance(raw, dict) else {}


def _new_id(existing: Iterable[str]) -> str:
    taken = set(existing)
    while True:
        candidate = "cred_" + secrets.token_hex(4)
        if candidate not in taken:
            return candidate


def migrate_legacy(settings: dict[str, Any]) -> bool:
    """Reprendre les clés du format plat sans jamais en perdre une.

    Les anciens champs sont conservés en place : `app.py` et les tests plus
    anciens les lisent encore, et une clé effacée d'un côté serait perdue des
    deux. Le magasin devient la source affichée, pas un remplacement destructif.
    """
    entries = _entries(settings)
    bindings = _bindings(settings)
    changed = False
    for legacy_key, provider in LEGACY_KEYS.items():
        value = str(settings.get(legacy_key) or "").strip()
        if not value:
            continue
        if any(item.get("value") == value for item in entries):
            continue
        record = {
            "id": _new_id(item["id"] for item in entries),
            "provider": provider,
            "name": "Reprise de l'ancienne configuration",
            "value": value,
            "created_at": _now(),
        }
        entries.append(record)
        bindings.setdefault(provider, record["id"])
        changed = True
    if changed:
        settings["credentials"] = entries
        settings["credential_bindings"] = bindings
    return changed


def list_credentials(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Vue publique : jamais la valeur, seulement de quoi la reconnaître."""
    bindings = _bindings(settings)
    out: list[dict[str, Any]] = []
    for item in _entries(settings):
        provider = str(item.get("provider") or "custom")
        out.append(
            {
                "id": str(item["id"]),
                "provider": provider,
                "name": str(item.get("name") or ""),
                "hint": redact(str(item.get("value") or "")),
                "created_at": str(item.get("created_at") or ""),
                "bound": bindings.get(provider) == str(item["id"]),
            }
        )
    out.sort(key=lambda x: (x["provider"], x["name"].lower()))
    return out


def credentials_state(settings: dict[str, Any]) -> dict[str, Any]:
    """Ce que l'interface doit savoir pour peupler ses menus déroulants."""
    items = list_credentials(settings)
    return {
        "providers": describe_providers(),
        "credentials": items,
        "bindings": _bindings(settings),
        "environment": {
            spec.id: sorted({name for name in spec.env if os.getenv(name, "").strip()})
            for spec in PROVIDERS
        },
    }


def upsert_credential(
    settings: dict[str, Any],
    *,
    credential_id: str | None = None,
    provider: str,
    name: str,
    value: str | None,
) -> dict[str, Any]:
    spec = provider_spec(provider)
    label = str(name or "").strip()
    if not label:
        raise CredentialError("credential_name_required", "Donnez un nom à la clé.")
    if len(label) > MAX_NAME_LENGTH:
        raise CredentialError(
            "credential_name_too_long", f"Le nom ne peut pas dépasser {MAX_NAME_LENGTH} caractères."
        )
    entries = _entries(settings)
    secret = None if value is None else str(value).strip()

    if credential_id:
        target = next((item for item in entries if str(item.get("id")) == str(credential_id)), None)
        if target is None:
            raise CredentialError("credential_not_found", "Cette clé n'existe plus.")
        # Champ laissé vide = « garde la valeur actuelle ». Sans cette règle,
        # renommer une clé l'effacerait, puisque l'interface ne la relit jamais.
        if secret:
            target["value"] = secret
        target["provider"] = spec.id
        target["name"] = label
        record = target
    else:
        if not secret:
            raise CredentialError("credential_value_required", "La valeur de la clé est obligatoire.")
        if any(
            str(item.get("provider")) == spec.id and str(item.get("name", "")).strip().lower() == label.lower()
            for item in entries
        ):
            raise CredentialError(
                "credential_duplicate_name", f"Une clé {spec.label} porte déjà le nom « {label} »."
            )
        record = {
            "id": _new_id(str(item.get("id")) for item in entries),
            "provider": spec.id,
            "name": label,
            "value": secret,
            "created_at": _now(),
        }
        entries.append(record)

    settings["credentials"] = entries
    bindings = _bindings(settings)
    # Première clé d'un fournisseur : la lier évite un menu déroulant vide et
    # une configuration qui « ne marche pas » alors que la clé est là.
    bindings.setdefault(spec.id, str(record["id"]))
    settings["credential_bindings"] = bindings
    return {
        "id": str(record["id"]),
        "provider": spec.id,
        "name": label,
        "hint": redact(str(record.get("value") or "")),
        "created_at": str(record.get("created_at") or ""),
    }


def delete_credential(settings: dict[str, Any], credential_id: str) -> bool:
    entries = _entries(settings)
    remaining = [item for item in entries if str(item.get("id")) != str(credential_id)]
    if len(remaining) == len(entries):
        return False
    settings["credentials"] = remaining
    bindings = {
        provider: bound
        for provider, bound in _bindings(settings).items()
        if str(bound) != str(credential_id)
    }
    # La liaison disparaît avec la clé, mais un autre exemplaire du même
    # fournisseur doit reprendre le relais plutôt que laisser le service muet.
    for item in remaining:
        bindings.setdefault(str(item.get("provider") or "custom"), str(item.get("id")))
    settings["credential_bindings"] = bindings
    return True


def bind_credential(settings: dict[str, Any], provider: str, credential_id: str | None) -> None:
    spec = provider_spec(provider)
    bindings = _bindings(settings)
    if not credential_id:
        bindings.pop(spec.id, None)
    else:
        match = next(
            (item for item in _entries(settings) if str(item.get("id")) == str(credential_id)), None
        )
        if match is None:
            raise CredentialError("credential_not_found", "Cette clé n'existe plus.")
        if str(match.get("provider")) != spec.id:
            raise CredentialError(
                "credential_provider_mismatch",
                f"Cette clé est enregistrée pour {provider_spec(str(match.get('provider'))).label}, pas {spec.label}.",
            )
        bindings[spec.id] = str(credential_id)
    settings["credential_bindings"] = bindings


def secret_for(settings: dict[str, Any], provider: str) -> str:
    """Valeur en clair à donner à un service, ou chaîne vide.

    Ordre : la clé explicitement liée, puis l'unique clé du fournisseur, puis
    l'ancien champ plat, puis l'environnement. La retombée sur l'environnement
    garantit qu'un .env qui marchait avant ce magasin marche encore.
    """
    spec = _BY_ID.get(str(provider or "").strip().lower())
    if spec is None:
        return ""
    entries = _entries(settings)
    bound_id = _bindings(settings).get(spec.id)
    if bound_id:
        match = next((item for item in entries if str(item.get("id")) == str(bound_id)), None)
        if match and str(match.get("value") or "").strip():
            return str(match["value"]).strip()
    owned = [item for item in entries if str(item.get("provider")) == spec.id and str(item.get("value") or "").strip()]
    if len(owned) == 1:
        return str(owned[0]["value"]).strip()
    for legacy_key, legacy_provider in LEGACY_KEYS.items():
        if legacy_provider == spec.id:
            value = str(settings.get(legacy_key) or "").strip()
            if value:
                return value
    for name in spec.env:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""
