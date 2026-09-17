"""Règle unique d'un lien d'entrée d'artefact (handoff jarvis-constellation-scene-runtime, Slice 09, reprise QA).

Décision du PM : une URL n'est un **lien** (page) et n'a un **hôte** (`scene_get`, cerveau) que si une
règle prudente l'accepte, la même des deux côtés : `link_host` ici, `linkOf` dans
`jarvis/runtime/control_center_scene_layout.js`. Les deux sont vérifiées contre le même corpus
(`tests/fixtures/scene_link_corpus.json`, test Python et test node). Sinon : texte seulement, pas d'hôte.

Acceptée seulement si :

- elle commence exactement par `http://` ou `https://`, et sa **longueur encodée** (`link_length`,
  la forme percent-encodée que le navigateur met dans `href`, majorée) fait au plus 2 048 ;
- elle ne contient nulle part de barre oblique inverse, de blanc, de caractère de contrôle, de marque
  bidi, de caractère invisible, ni de point pleine chasse ou idéographique (refusés, jamais normalisés) ;
- son autorité (entre `//` et le premier `/`, `?` ou `#`) n'a ni `@` (identifiants) ni `%` ;
- son hôte est, au choix :
  - un nom ASCII à étiquettes pointées standard (`[a-z0-9]([a-z0-9-]*[a-z0-9])?`, 1 à 63 caractères
    chacune, 253 au total, aucune étiquette `xn--` : un nom international n'est pas un lien) ;
  - une IPv4 pointée stricte (4 nombres 0–255 sans zéro initial) ; un nom dont la dernière étiquette est
    numérique (`0x7f.1`, `2130706433`, `1.2.3`) n'en est pas un et est refusé ;
  - une IPv6 entre crochets, en chiffres hexadécimaux et `:` seulement (sans IPv4 incluse) ;
- son port éventuel est un nombre de 0 à 65535.

L'hôte rendu est en minuscules ; une IPv6 est rendue entre crochets, compressée comme le fait le
navigateur (RFC 5952 : groupes sans zéros initiaux, plus longue suite d'au moins deux groupes nuls
remplacée par `::`, la première à égalité).
"""

from __future__ import annotations

import re

MAX_LINK_CHARS = 2048
#: Blancs, contrôles C0/C1 et DEL, espace insécable, marques bidi et caractères invisibles, séparateurs
#: de ligne, points pleine chasse et idéographiques, barre oblique inverse.
_UNSAFE = re.compile(
    "[\\u0000-\\u0020\\u007f-\\u00a0\\u00ad\\u061c\\u180e\\u200b-\\u200f\\u2028-\\u202f\\u205f-\\u206f"
    "\\u3000\\u3002\\ufeff\\uff0e\\uff61\\\\]"
)
_NAME_HOST = re.compile(r"\A([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?\Z")
_IPV6_HOST = re.compile(r"\A\[([0-9A-Fa-f:]+)\](?::([0-9]{1,5}))?\Z")
_LABEL = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_NUMERIC_LABEL = re.compile(r"\A(?:[0-9]+|0x[0-9a-f]*)\Z")
_OCTET = re.compile(r"\A(?:0|[1-9][0-9]{0,2})\Z")
#: ASCII gardé tel quel par l'encodage d'URL (RFC 3986 : non réservés, réservés, `%`) ; tout autre
#: caractère ASCII compte comme `%XX`.
_URL_ASCII = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/?#[]@!$&()*+,;=%")


def link_length(url: str) -> int:
    """Longueur de l'URL percent-encodée, majorée ; calculée à l'identique par `linkLength` (page).

    Par point de code : ASCII de `_URL_ASCII` 1, autre ASCII 3 (`%XX`), non-ASCII 3 × ses octets UTF-8,
    substitut isolé 9 (encodé comme U+FFFD) ; + 1 si rien ne suit l'autorité ou si elle est suivie de `?`
    ou `#` (le navigateur ajoute `/`). Jamais inférieure à la longueur de `href`.
    """

    total = 0
    for char in url:
        code = ord(char)
        if code < 0x80:
            total += 1 if char in _URL_ASCII else 3
        elif 0xD800 <= code <= 0xDFFF:
            total += 9
        else:
            total += 3 * (2 if code < 0x800 else 3 if code < 0x10000 else 4)
    rest = url.split("://", 1)[1] if "://" in url else ""
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if not rest[len(authority):].startswith("/"):
        total += 1
    return total


def _ipv6(text: str) -> str | None:
    if text.count("::") > 1:
        return None
    if "::" in text:
        head, tail = text.split("::")
        left = head.split(":") if head else []
        right = tail.split(":") if tail else []
        if len(left) + len(right) > 7:
            return None
        groups = left + ["0"] * (8 - len(left) - len(right)) + right
    else:
        groups = text.split(":")
        if len(groups) != 8:
            return None
    if any(not re.fullmatch(r"[0-9A-Fa-f]{1,4}", group) for group in groups):
        return None
    values = [format(int(group, 16), "x") for group in groups]
    best_start, best_length, start = -1, 0, -1
    for index, value in enumerate([*values, "end"]):
        if value == "0":
            start = index if start < 0 else start
            continue
        if start >= 0 and index - start > best_length:
            best_start, best_length = start, index - start
        start = -1
    if best_length < 2:
        return "[" + ":".join(values) + "]"
    head = ":".join(values[:best_start])
    tail = ":".join(values[best_start + best_length:])
    return f"[{head}::{tail}]"


def link_host(url: object) -> str | None:
    """L'hôte d'une URL qui peut être un lien, ou `None` : alors ni lien ni hôte."""

    # `len` ≤ `link_length` : le premier test borne le calcul sans changer la règle.
    if not isinstance(url, str) or not url or len(url) > MAX_LINK_CHARS or _UNSAFE.search(url):
        return None
    if link_length(url) > MAX_LINK_CHARS:
        return None
    if url.startswith("https://"):
        rest = url[len("https://"):]
    elif url.startswith("http://"):
        rest = url[len("http://"):]
    else:
        return None
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "@" in authority or "%" in authority:
        return None
    ipv6 = _IPV6_HOST.match(authority)
    if ipv6:
        host, port = _ipv6(ipv6.group(1)), ipv6.group(2)
    else:
        name = _NAME_HOST.match(authority)
        if not name:
            return None
        host, port = name.group(1).lower(), name.group(2)
        labels = host.split(".")
        if len(host) > 253 or any(not _LABEL.match(label) or label.startswith("xn--") for label in labels):
            return None
        if _NUMERIC_LABEL.match(labels[-1]) and not (len(labels) == 4 and all(
                _OCTET.match(label) and int(label) <= 255 for label in labels)):
            return None
    if host is None or (port is not None and int(port) > 65535):
        return None
    return host
