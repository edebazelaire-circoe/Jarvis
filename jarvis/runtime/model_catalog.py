"""Liste des modèles réellement disponibles, demandée au fournisseur.

Aucun CLI d'agent n'expose « donne-moi tes modèles » : ni `claude`, ni `codex`.
La seule source qui ne périme pas est l'API du fournisseur. Ce module l'appelle,
classe chaque modèle par usage à partir de ce que l'API déclare, et met le
résultat en cache.

Règle de conduite : en cas d'échec, on dit pourquoi. Jamais de liste écrite en
dur servie à la place — un modèle retiré du service qui reste proposé dans un
menu est un piège, pas un secours.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time
from typing import Any

import aiohttp

from jarvis.runtime.credentials import provider_spec, redact

# Un catalogue bouge à l'échelle de la semaine ; dix minutes suffisent à éviter
# un aller-retour réseau à chaque ouverture des réglages.
CACHE_TTL_S = 600.0
REQUEST_TIMEOUT_S = 15.0

ANTHROPIC_VERSION = "2023-06-01"

# Usages proposés dans l'interface. Un modèle peut en cumuler plusieurs.
ROLES = ("text", "realtime", "transcription", "speech")


class CatalogError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _openai_roles(model_id: str) -> tuple[str, ...]:
    name = model_id.lower()
    if "realtime" in name:
        return ("realtime",)
    if "transcribe" in name or name.startswith("whisper"):
        return ("transcription",)
    if "-tts" in name or name.startswith("tts-"):
        return ("speech",)
    excluded = ("embedding", "moderation", "dall-e", "gpt-image", "sora", "omni-moderation", "davinci", "babbage")
    if any(token in name for token in excluded):
        return ()
    if name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt", "codex")):
        return ("text",)
    return ()


def _google_roles(methods: list[str], model_id: str) -> tuple[str, ...]:
    roles: list[str] = []
    # Google déclare lui-même la capacité Live : `bidiGenerateContent` est le
    # protocole bidirectionnel audio. C'est un fait de l'API, pas une déduction.
    if "bidiGenerateContent" in methods:
        roles.append("realtime")
    if "generateContent" in methods:
        roles.append("text")
        # Les modèles Gemini acceptent l'audio en entrée de generateContent ;
        # c'est ce qui sert de transcription hors session Live.
        if "gemini" in model_id.lower():
            roles.append("transcription")
    return tuple(roles)


async def _fetch_anthropic(session: aiohttp.ClientSession, api_key: str) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    params: dict[str, str] = {"limit": "100"}
    for _ in range(10):  # borne dure : une pagination qui ne finit pas est un bug amont
        async with session.get(
            "https://api.anthropic.com/v1/models",
            params=params,
            headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
        ) as response:
            payload = await _payload(response, "anthropic")
        for item in payload.get("data") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            models.append(
                {
                    "id": str(item["id"]),
                    "label": str(item.get("display_name") or item["id"]),
                    "created": str(item.get("created_at") or ""),
                    "roles": ("text",),
                }
            )
        if not payload.get("has_more") or not payload.get("last_id"):
            break
        params = {"limit": "100", "after_id": str(payload["last_id"])}
    return models


async def _fetch_openai(session: aiohttp.ClientSession, api_key: str) -> list[dict[str, Any]]:
    async with session.get(
        "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"}
    ) as response:
        payload = await _payload(response, "openai")
    models: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        model_id = str(item["id"])
        roles = _openai_roles(model_id)
        if not roles:
            continue
        models.append({"id": model_id, "label": model_id, "created": item.get("created"), "roles": roles})
    return models


async def _fetch_google(session: aiohttp.ClientSession, api_key: str) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    params: dict[str, str] = {"key": api_key, "pageSize": "200"}
    for _ in range(10):
        async with session.get(
            "https://generativelanguage.googleapis.com/v1beta/models", params=params
        ) as response:
            payload = await _payload(response, "google")
        for item in payload.get("models") or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            model_id = str(item["name"]).removeprefix("models/")
            methods = [str(x) for x in (item.get("supportedGenerationMethods") or [])]
            roles = _google_roles(methods, model_id)
            if not roles:
                continue
            models.append(
                {
                    "id": model_id,
                    "label": str(item.get("displayName") or model_id),
                    "methods": methods,
                    "roles": roles,
                }
            )
        token = payload.get("nextPageToken")
        if not token:
            break
        params = {"key": api_key, "pageSize": "200", "pageToken": str(token)}
    return models


async def _payload(response: aiohttp.ClientResponse, provider: str) -> dict[str, Any]:
    # Le fournisseur est nommé comme l'utilisateur le voit dans l'onglet API
    # Keys : « OpenAI », pas « openai ».
    label = provider_spec(provider).label
    text = await response.text()
    if response.status in {401, 403}:
        raise CatalogError(
            "catalog_unauthorized",
            f"La clé {label} a été refusée par le fournisseur (HTTP {response.status}).",
        )
    if response.status == 429:
        raise CatalogError("catalog_rate_limited", f"{label} limite les appels (HTTP 429).")
    if response.status >= 400:
        raise CatalogError(
            "catalog_provider_error",
            f"{label} a répondu HTTP {response.status}.",
        )
    try:
        value = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise CatalogError("catalog_bad_payload", f"Réponse illisible de {label}.") from exc
    return value if isinstance(value, dict) else {}


_FETCHERS = {"anthropic": _fetch_anthropic, "openai": _fetch_openai, "google": _fetch_google}
SUPPORTED_PROVIDERS: tuple[str, ...] = tuple(_FETCHERS)


class ModelCatalog:
    """Cache mémoire + disque des catalogues, avec l'origine de chaque réponse."""

    def __init__(self, cache_path: Path, *, ttl_s: float = CACHE_TTL_S) -> None:
        self.cache_path = cache_path
        self.ttl_s = ttl_s
        self._cache: dict[str, dict[str, Any]] = self._load()
        self._locks: dict[str, asyncio.Lock] = {}

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        except OSError:
            # Le cache est un confort : ne jamais faire échouer une lecture de
            # catalogue parce que le disque refuse de l'écrire.
            pass

    def invalidate(self, provider: str | None = None) -> None:
        if provider is None:
            self._cache.clear()
        else:
            self._cache.pop(provider, None)
        self._save()

    async def models(
        self,
        provider: str,
        api_key: str,
        *,
        refresh: bool = False,
        session: aiohttp.ClientSession | None = None,
    ) -> dict[str, Any]:
        name = str(provider or "").strip().lower()
        if name not in _FETCHERS:
            raise CatalogError("catalog_unsupported_provider", f"Aucun catalogue pour {provider}.")
        key = str(api_key or "").strip()
        if not key:
            raise CatalogError(
                "catalog_no_key",
                f"Ajoutez une clé {provider_spec(name).label} dans l'onglet API Keys "
                "pour lister les modèles réels.",
            )
        hint = redact(key)
        cached = self._cache.get(name)
        fresh = (
            cached is not None
            and cached.get("key_hint") == hint
            and (time.time() - float(cached.get("fetched_at") or 0)) < self.ttl_s
        )
        if fresh and not refresh:
            return {**cached, "source": "cache"}

        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            cached = self._cache.get(name)
            if not refresh and cached is not None and cached.get("key_hint") == hint:
                if (time.time() - float(cached.get("fetched_at") or 0)) < self.ttl_s:
                    return {**cached, "source": "cache"}
            owns = session is None
            http = session or aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
            )
            try:
                models = await _FETCHERS[name](http, key)
            except CatalogError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise CatalogError(
                    "catalog_unreachable",
                    f"{provider_spec(name).label} injoignable : {type(exc).__name__}.",
                ) from exc
            finally:
                if owns:
                    await http.close()
            entry = {
                "provider": name,
                "models": models,
                "fetched_at": time.time(),
                "key_hint": hint,
            }
            self._cache[name] = entry
            self._save()
            return {**entry, "source": "live"}

    def cached(self, provider: str) -> dict[str, Any] | None:
        """Dernier catalogue connu, même périmé : mieux qu'un menu vide."""
        entry = self._cache.get(str(provider or "").strip().lower())
        return {**entry, "source": "stale"} if entry else None


def filter_by_role(models: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    if role not in ROLES:
        return list(models)
    return [item for item in models if role in tuple(item.get("roles") or ())]
