"""Contrôles de validation partagés par les contrats du domaine.

Module privé du paquet `jarvis.domain` : `work_state`, `scene`,
`workspace_board` et `session_context` y prennent les mêmes règles de texte,
de jeton, d'identifiant, de date et de champs, avec les mêmes messages.
Pur : aucune E/S, aucune dépendance hors bibliothèque standard.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
import math
import re
from types import MappingProxyType
from typing import Any

#: Identifiants publics (`external_id`, `object_id`...) : bornés, sans espace
#: autour.
MAX_ID_CHARS = 128
#: Longueur maximale d'une valeur brute recopiée dans un message d'erreur : un
#: fil hostile ne fait pas grossir les journaux.
MAX_PREVIEW_CHARS = 80

# Jeton court et stable : source, nature, catégorie, classe d'erreur. Pas de
# `:` ni d'espace, pour qu'un couple `(source, external_id)` reste lisible
# sans ambiguïté dans un journal.
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_ELLIPSIS = "…"


def check_text(name: str, value: object, limit: int, *, single_line: bool = True) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    if single_line and value and not value.isprintable():
        raise ValueError(f"{name} must be a single printable line")


def check_token(name: str, value: object, limit: int, *, required: bool) -> None:
    check_text(name, value, limit)
    if not value:
        if required:
            raise ValueError(f"{name} is required")
        return
    if not TOKEN.fullmatch(str(value)):
        raise ValueError(f"{name} must be a short token (letters, digits, '_', '.', '-')")


def check_id(name: str, value: object, *, required: bool) -> None:
    if value is None and not required:
        return
    check_text(name, value, MAX_ID_CHARS)
    if not str(value).strip() or str(value) != str(value).strip():
        raise ValueError(f"{name} must be a non-empty identifier without surrounding spaces")


def preview(value: object) -> str:
    """Représentation bornée d'une valeur reçue, pour un message d'erreur."""

    if isinstance(value, str):
        text = repr(value[: MAX_PREVIEW_CHARS + 1])
    elif isinstance(value, (list, tuple, dict, set)):
        text = f"<{type(value).__name__} of {len(value)}>"
    else:
        try:
            text = repr(value)
        except ValueError:
            # `repr` d'un entier géant peut lever (limite de conversion).
            text = f"<{type(value).__name__}>"
    if len(text) <= MAX_PREVIEW_CHARS:
        return text
    return text[:MAX_PREVIEW_CHARS] + _ELLIPSIS


# ------------------------------------------------------------------ contrats à refus codé
#
# Briques communes aux contrats qui lèvent une erreur codée (`BoardError`,
# `SessionContextError`) : chaque appelant passe `fail(message) -> Exception`,
# qui porte son propre code. Une seule implémentation, mêmes messages.

Fail = Callable[[str], Exception]


def check_aware(fail: Fail, name: str, value: object, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, datetime):
        raise fail(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise fail(f"{name} must be timezone-aware")


#: Entiers des métadonnées : bornés à int64 (SQLite, JSON portable) ; NaN et
#: infinis refusés (JSON standard ne les représente pas).
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1


def freeze_runtime_metadata(
    fail: Fail, value: object, *, max_keys: int, max_key_chars: int, max_value_chars: int,
) -> Mapping[str, Any]:
    """Dict plat de scalaires JSON bornés, rendu immuable (`MappingProxyType`)."""

    if not isinstance(value, Mapping):
        raise fail("runtime_metadata must be a mapping")
    if len(value) > max_keys:
        raise fail(f"runtime_metadata holds at most {max_keys} keys")
    for key, item in value.items():
        if not isinstance(key, str) or not TOKEN.fullmatch(key) or len(key) > max_key_chars:
            raise fail(f"runtime_metadata key must be a short token, got {preview(key)}")
        if item is None or isinstance(item, bool):
            continue
        if isinstance(item, int):
            if INT64_MIN <= item <= INT64_MAX:
                continue
            raise fail(f"runtime_metadata[{key!r}] must be an integer within int64")
        if isinstance(item, float):
            if math.isfinite(item):
                continue
            raise fail(f"runtime_metadata[{key!r}] must be a finite number")
        if isinstance(item, str) and len(item) <= max_value_chars:
            continue
        raise fail(f"runtime_metadata[{key!r}] must be a JSON scalar (string <= {max_value_chars})")
    return MappingProxyType(dict(value))


def strict_keys(
    fail: Fail, name: str, payload: object, allowed: frozenset[str], *, required: frozenset[str],
) -> dict[str, Any]:
    """Objet JSON sans champ inconnu ni manquant ; rend `payload`."""

    if not isinstance(payload, dict):
        raise fail(f"{name} payload must be an object")
    unknown = sorted(str(key)[:40] for key in payload if key not in allowed)
    if unknown:
        raise fail(f"{name} has unknown fields: {unknown[:5]}")
    missing = sorted(required - payload.keys())
    if missing:
        raise fail(f"{name} is missing fields: {missing}")
    return payload


def parse_dt(fail: Fail, name: str, raw: object, *, required: bool = True) -> datetime | None:
    if raw is None and not required:
        return None
    if not isinstance(raw, str):
        raise fail(f"{name} must be an ISO 8601 string")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise fail(f"{name} is not ISO 8601: {preview(raw)}") from None


def parse_enum(fail: Fail, name: str, raw: object, enum: type[StrEnum]) -> Any:
    try:
        return enum(raw)
    except ValueError:
        raise fail(f"{name} is not a {enum.__name__}: {preview(raw)}") from None


#: Identifiant sûr comme segment de chemin : préfixe, puis minuscules ASCII,
#: chiffres, `_` ou `-`. Ni `.`, ni séparateur, ni espace : `..`, `a/b` ou
#: `C:` sont refusés avant de devenir un dossier. Minuscules seulement : NTFS
#: ignore la casse, `jctx_a` et `jctx_A` y seraient le même dossier. Les ids
#: générés (`uuid4().hex`) sont déjà en minuscules. Partagé par les Contexts
#: (`session_context`) et les Artifacts (`artifacts`).
PATH_SAFE_ID = re.compile(r"[a-z0-9_-]+")


def check_prefixed_id(fail: Fail, name: str, value: object, prefix: str) -> None:
    """`prefix` suivi d'un segment de chemin sûr (`PATH_SAFE_ID`), <= `MAX_ID_CHARS`."""

    if not isinstance(value, str):
        raise fail(f"{name} must be a string, got {preview(value)}")
    if (len(value) > MAX_ID_CHARS or not value.startswith(prefix) or len(value) == len(prefix)
            or not PATH_SAFE_ID.fullmatch(value)):
        raise fail(
            f"{name} must be {prefix!r} followed by lowercase letters, digits, '_' or '-' "
            f"(<= {MAX_ID_CHARS} chars), got {preview(value)}",
        )
