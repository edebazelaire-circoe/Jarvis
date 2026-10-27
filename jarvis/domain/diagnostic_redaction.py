"""Masquage des diagnostics qui quittent le poste (Slice 10, `docs/release.md` › *Support bundle*).

Un texte de diagnostic (ligne de journal, sortie d'une CLI, champ d'un état JSON) peut porter un secret, une adresse,
ou un chemin qui nomme l'utilisateur Windows. Avant d'entrer dans un paquet de support ou un message affiché, il passe
ici :

1. les secrets par le masquage canonique des plugins MCP (`mcp_plugins.redact` / `redact_structured` : `Bearer`,
   JWT, `Authorization`, cookies, toute paire `token=` / `api_key:` / `password`…), plus les FORMES de clés nues
   connues (`sk-…`, `sk-ant-…`, `AIza…`, `ya29.…`, `ghp_…`, `xox?-…`, `GOCSPX-…`, `4/0…`, `AKIA…`, `sk_live_…`, bloc PEM
   `-----BEGIN … PRIVATE KEY-----`), le mot
   de passe d'une URL `schéma://utilisateur:mot de passe@hôte`, et les paires que le masquage canonique ne nomme pas
   (`pwd`, `passphrase`, `private_key`, `aws_secret_access_key`, `aws_session_token`) ;
2. les adresses électroniques → `<email>` ;
3. les racines personnelles connues (`LOCALAPPDATA`, `APPDATA`, `TEMP`, `USERPROFILE`…) → leur nom de variable
   (`%LOCALAPPDATA%`…), puis tout `C:\\Users\\<nom>` restant → `C:\\Users\\<user>`, puis le nom d'utilisateur seul.

Le contenu des conversations n'est jamais « masqué » : il n'entre pas (`CONTENT_KEYS` remplace la valeur par sa
longueur). Ce module est pur : l'environnement lui est donné.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import re
from typing import Any

from jarvis.domain.mcp_plugins import REDACTED, redact, redact_structured

#: Formes de clés reconnues même sans nom de champ (une clé collée seule dans une ligne de journal).
_KEY_SHAPES = (
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}"),            # Anthropic / OpenAI
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),                   # Google API key
    re.compile(r"\bya29\.[0-9A-Za-z_.-]{20,}"),                # Google OAuth access token
    re.compile(r"\b1//0[0-9A-Za-z_-]{20,}"),                   # Google OAuth refresh token
    re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),               # Google OAuth client secret (HV-INSTALL-02)
    re.compile(r"\b4/0[A-Za-z0-9_-]{20,}"),                   # Google OAuth authorization code
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),             # AWS access key id
    re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}"),     # Stripe
    # Blocs de clé privée (V1.2 Slice 07, reprise QA M3) : PEM (PKCS#1/#8, OpenSSH, chiffrée à l'ancienne avec ses
    # en-têtes `Proc-Type` / `DEK-Info`), PGP (`… PRIVATE KEY BLOCK`), corps compris jusqu'à la ligne de fin (ou la fin
    # du texte). Course paresseuse bornée : linéaire par marqueur de début.
    re.compile(r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----[\s\S]{0,65536}?"
               r"(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----|\Z)"),
    # Clé PuTTY (`.ppk`) : de l'en-tête (ou de `Private-Lines:`) jusqu'à `Private-MAC:` compris.
    re.compile(r"(?:PuTTY-User-Key-File-\d+:|Private-Lines:)[\s\S]{0,65536}?(?:Private-MAC:[^\r\n]*|\Z)"),
    # JWT court (`eyJ…`) que la forme canonique (24 caractères au premier segment) laisse passer.
    re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"),
)
#: `schéma://utilisateur:mot de passe@hôte` (postgres, https, smtp…) : le mot de passe, quel que soit l'hôte (QA S10 m2).
_URL_PASSWORD = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,20}://[^\s:/@'\"<>]{1,128}:)(?!\[secret masqué\])[^\s@/'\"<>]{1,256}@")
#: Paires `clé=valeur` / `clé: valeur` que le masquage canonique ne nomme pas.
_EXTRA_PAIRS = re.compile(r"(?i)(?<![A-Za-z0-9])(pwd|passphrase|private[_-]?key|(?:aws_)?secret_access_key|aws_session_token)"
                          r"([\"']?\s*[:=]\s*[\"']?)(?!\[secret masqué\])[^\s\"',;]+")
_EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_USERS_DIR = re.compile(r"(?i)\b([A-Z]:[\\/]+Users[\\/]+)(?!<user>)[^\\/\s\"'<>|:]+")
#: Variables dont la valeur est une racine personnelle, de la plus précise à la plus large.
PATH_VARIABLES = ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "ONEDRIVE", "USERPROFILE")
#: Clés dont la valeur est du contenu d'utilisateur (paroles, prompts, textes) : jamais copiée, seule sa taille.
CONTENT_KEYS = frozenset({"text", "transcript", "transcription", "prompt", "content", "utterance", "speech", "reply",
                          "body", "answer", "question", "partial", "final", "spoken", "said", "message_text",
                          "user_text", "assistant_text", "notes", "draft"})
EMAIL_MASK = "<email>"
USER_MASK = "<user>"

#: Mots (séparés par `_`, `-` ou `.`, ou fin d'un mot collé : `refreshToken`, `APIKEY`) d'un nom dont la valeur est un
#: secret quelle que soit sa forme (QA S10 x4, V1.2 S07 B1) ; jamais un morceau (`KEYBOARD_LAYOUT` reste lisible).
SECRET_NAME_WORDS = frozenset({"TOKEN", "KEY", "SECRET", "PASSWORD", "PASSWD", "PWD", "PASS", "PASSPHRASE",
                               "CREDENTIAL", "CREDENTIALS", "COOKIE", "SIGNATURE", "AUTHORIZATION", "BEARER"})
SECRET_NAME_ENDINGS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "CREDENTIAL", "CREDENTIALS")
#: Mots qui font d'un nom « sensible » un réglage descriptif (`TOKEN_TYPE`, `KEY_FILE`, `MAX_TOKEN`, `TOKEN_EXPIRES_AT`).
DESCRIPTIVE_NAME_WORDS = frozenset({"TYPE", "KIND", "EXPIRES", "EXPIRY", "EXPIRATION", "AT", "SCOPE", "SCOPES", "URL",
                                    "URI", "HOST", "PORT", "MODE", "TIMEOUT", "LENGTH", "SIZE", "COUNT", "MAX", "MIN",
                                    "LIMIT", "ENABLED", "FILE", "PATH", "DIR", "NAME", "ID", "CACHE", "LAYOUT", "HINT"})
_TRIVIAL_VALUE = re.compile(r"(?i)(?:true|false|yes|no|on|off|none|null|enabled|disabled|[0-9.:+-]*)")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
#: `NOM=valeur`, `export NOM=valeur`, `NOM: valeur` en texte libre (`.env` collé, YAML, journal) : la valeur est masquée
#: si le nom est sensible (`sensitive_name`) et la valeur non triviale (`secret_like`).
_NAMED_VALUE = re.compile(r"(?<![A-Za-z0-9_])((?:export\s+)?)([A-Za-z][A-Za-z0-9_.-]{0,63})([\"']?[ \t]*[:=][ \t]*)"
                          r"(\"[^\"\r\n]{1,1024}\"|'[^'\r\n]{1,1024}'|(?!\[secret masqué\])[^\s\"',;]{1,1024})")
#: Paire JSON dont les guillemets sont échappés une ou plusieurs fois (JSON dans une chaîne JSON, dans un journal).
_ESCAPED_PAIR = re.compile(r'(?<!\\)(\\+")([A-Za-z][A-Za-z0-9_.-]{0,63})\1\s*:\s*\1([^"\\\r\n]{1,1024})\1')
MAX_JSON_DEPTH = 6


def sensitive_name(name: str) -> bool:
    """Le nom désigne-t-il un secret (`OPENAI_API_KEY`, `refreshToken`, `X-Api-Key`) plutôt qu'un réglage descriptif ?"""

    words = [word for word in re.split(r"[_.\-\s]+", _CAMEL.sub("_", name or "").upper()) if word]
    if any(word in DESCRIPTIVE_NAME_WORDS for word in words):
        return False
    joined = "".join(words)
    return (any(word in SECRET_NAME_WORDS or word.endswith(SECRET_NAME_ENDINGS) for word in words)
            or (bool(joined) and joined.endswith(SECRET_NAME_ENDINGS)))


def named_secret(name: str, value: str) -> bool:
    """La valeur d'une clé ou d'une variable NOMMÉE comme un secret, et non triviale (identifiants, horodatages et codes
    sous un nom ordinaire restent lisibles)."""

    return sensitive_name(name) and secret_like(name, value)


def secret_like(name: str, value: str) -> bool:
    """Une valeur à masquer : non triviale, et soit nommée comme un secret (6 caractères au moins), soit, sans nom, en
    forme de jeton (8 caractères au moins sans espace, lettres ET chiffres, ou 20 caractères au moins)."""

    if not value or _TRIVIAL_VALUE.fullmatch(value) or value == REDACTED:
        return False
    if name and sensitive_name(name):
        return len(value) >= 6
    if len(value) < 8 or any(char.isspace() for char in value):
        return False
    return (any(char.isdigit() for char in value) and any(char.isalpha() for char in value)) or len(value) >= 20


def path_tokens(environ: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """(préfixe, `%VARIABLE%`) des racines personnelles, du plus long au plus court."""

    found: dict[str, str] = {}
    for name in PATH_VARIABLES:
        value = str(environ.get(name) or "").rstrip("\\/")
        if len(value) >= 4 and value not in found:
            found[value] = f"%{name}%"
    return tuple(sorted(found.items(), key=lambda item: len(item[0]), reverse=True))


class DiagnosticRedactor:
    """Masqueur lié à un poste : racines personnelles et nom d'utilisateur lus une fois dans `environ`."""

    def __init__(self, environ: Mapping[str, str], *, known_secrets: Iterable[str] = ()) -> None:
        self._tokens = path_tokens(environ)
        self._patterns = tuple((re.compile(_path_regex(prefix), re.IGNORECASE), token) for prefix, token in self._tokens)
        user = str(environ.get("USERNAME") or "").strip()
        self._user = re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])") if len(user) >= 3 else None
        self._secrets = tuple(secret for secret in known_secrets if isinstance(secret, str) and len(secret) >= 6)

    def text(self, value: object) -> str:
        """Une chaîne sans secret, sans adresse, sans racine personnelle ni nom d'utilisateur."""

        text = redact(str(value if value is not None else ""), self._secrets)
        text = _URL_PASSWORD.sub(lambda match: f"{match.group(1)}{REDACTED}@", text)
        text = _EXTRA_PAIRS.sub(lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", text)
        for shape in _KEY_SHAPES:
            text = shape.sub(REDACTED, text)
        text = _NAMED_VALUE.sub(_named_value, text)
        text = _ESCAPED_PAIR.sub(_escaped_pair, text)
        text = _EMAIL.sub(EMAIL_MASK, text)
        for pattern, token in self._patterns:
            text = pattern.sub(token.replace("\\", "\\\\"), text)
        text = _USERS_DIR.sub(lambda match: match.group(1) + USER_MASK, text)
        if self._user is not None:
            text = self._user.sub(USER_MASK, text)
        return text

    def deep(self, value: Any, depth: int = 0) -> Any:
        """Copie JSON où le CONTENU est gardé mais chaque secret masqué (V1.2 S07, cellules des bases, fichiers de la
        mémoire) : valeur d'une clé sensible masquée entière, chaîne qui est elle-même du JSON relue et masquée
        récursivement (`MAX_JSON_DEPTH` niveaux), toute autre chaîne passée par `text`."""

        if isinstance(value, str):
            return self.cell(value, depth)
        if isinstance(value, Mapping):
            out: dict[Any, Any] = {}
            for key, item in value.items():
                if isinstance(key, str) and isinstance(item, str) and named_secret(key, item.strip()):
                    out[self.text(key)] = REDACTED
                else:
                    out[self.text(key) if isinstance(key, str) else key] = self.deep(item, depth)
            return out
        if isinstance(value, list):
            return [self.deep(item, depth) for item in value]
        return value

    def cell(self, value: str, depth: int = 0) -> str:
        """Un texte qui se lit comme du JSON (objet ou liste) est masqué en structure (`deep`), sinon par `text`."""

        stripped = value.strip()
        if depth < MAX_JSON_DEPTH and stripped[:1] in ("{", "[") and stripped[-1:] in ("}", "]"):
            try:
                parsed = json.loads(stripped)
            except (ValueError, RecursionError):
                parsed = None
            if isinstance(parsed, (dict, list)):
                return json.dumps(self.deep(redact_structured(parsed, self._secrets), depth + 1), ensure_ascii=False)
        return self.text(value)

    def structured(self, value: Any) -> Any:
        """Copie JSON : identifiants masqués entiers (`redact_structured`), contenu remplacé par sa taille, chaque
        chaîne passée par `text`. Clés et forme gardées : le résultat reste du JSON valide."""

        return self._walk(redact_structured(value, self._secrets))

    def _walk(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.cell(value)
        if isinstance(value, Mapping):
            return {self.text(key) if isinstance(key, str) else key:
                    (f"<{len(item)} caractères retirés>" if isinstance(key, str) and key.lower() in CONTENT_KEYS
                     and isinstance(item, str) and item
                     else REDACTED if isinstance(key, str) and isinstance(item, str) and named_secret(key, item.strip())
                     else self._walk(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [self._walk(item) for item in value]
        return value


def _named_value(match: re.Match[str]) -> str:
    value = match.group(4)
    quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
    bare = value[1:-1] if quoted else value
    if not named_secret(match.group(2), bare):
        return match.group(0)
    quote = value[0] if quoted else ""
    return f"{match.group(1)}{match.group(2)}{match.group(3)}{quote}{REDACTED}{quote}"


def _escaped_pair(match: re.Match[str]) -> str:
    if not named_secret(match.group(2), match.group(3)):
        return match.group(0)
    quote = match.group(1)
    return f"{quote}{match.group(2)}{quote}: {quote}{REDACTED}{quote}"


def _path_regex(prefix: str) -> str:
    """Le préfixe, avec `\\`, `/` ou `\\\\` (JSON brut) comme séparateurs, suivi d'une fin de segment."""

    parts = [re.escape(part) for part in re.split(r"[\\/]+", prefix) if part]
    return r"[\\/]{1,2}".join(parts) + r"(?![^\\/\s\"'<>|:])"
