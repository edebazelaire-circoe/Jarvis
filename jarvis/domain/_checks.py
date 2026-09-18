"""Contrôles de validation partagés par les contrats du domaine.

Module privé du paquet `jarvis.domain` : `work_state` et `scene` y prennent les
mêmes règles de texte, de jeton et d'identifiant, avec les mêmes messages.
Pur : aucune E/S, aucune dépendance hors bibliothèque standard.
"""

from __future__ import annotations

import re

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
