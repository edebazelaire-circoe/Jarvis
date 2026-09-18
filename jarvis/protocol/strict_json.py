"""Décodage JSON strict des corps de requête de la boucle locale.

Partagé par les routes canoniques de Voice et par le transport de la scène
(Core et proxy du Control Center) : une clé en double ou un nombre non fini
(`NaN`, `Infinity`) sont des erreurs de l'appelant, jamais une valeur retenue
en silence. Seules des `ValueError` sortent d'ici, que les frontières HTTP
traduisent en 400.
"""

from __future__ import annotations

import json


def _unique_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _refuse_nonfinite(_value: str) -> object:
    raise ValueError("nonfinite JSON number")


def loads_strict_json(raw: bytes, *, invalid_message: str) -> object:
    """Décoder `raw` (UTF-8). Clé en double, nombre non fini : `ValueError` explicite.

    Texte illisible (UTF-8 invalide, JSON mal formé, imbrication trop
    profonde) : `ValueError(invalid_message)`, la cause réelle chaînée.
    """

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_refuse_nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(invalid_message) from exc
