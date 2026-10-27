"""Masquage des diagnostics qui quittent le poste (Slice 10, `docs/release.md` › *Support bundle*).

Un texte de diagnostic (ligne de journal, sortie d'une CLI, champ d'un état JSON) peut porter un secret, une adresse,
ou un chemin qui nomme l'utilisateur Windows. Avant d'entrer dans un paquet de support ou un message affiché, il passe
ici :

1. les secrets par le masquage canonique des plugins MCP (`mcp_plugins.redact` / `redact_structured` : `Bearer`,
   JWT, `Authorization`, cookies, toute paire `token=` / `api_key:` / `password`…), plus les FORMES de clés nues
   connues (`sk-…`, `sk-ant-…`, `AIza…`, `ya29.…`, `ghp_…`, `xox?-…`, `GOCSPX-…`, `4/0…`, `AKIA…`, `sk_live_…`), le mot
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
        text = _EMAIL.sub(EMAIL_MASK, text)
        for pattern, token in self._patterns:
            text = pattern.sub(token.replace("\\", "\\\\"), text)
        text = _USERS_DIR.sub(lambda match: match.group(1) + USER_MASK, text)
        if self._user is not None:
            text = self._user.sub(USER_MASK, text)
        return text

    def structured(self, value: Any) -> Any:
        """Copie JSON : identifiants masqués entiers (`redact_structured`), contenu remplacé par sa taille, chaque
        chaîne passée par `text`. Clés et forme gardées : le résultat reste du JSON valide."""

        return self._walk(redact_structured(value, self._secrets))

    def _walk(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {self.text(key) if isinstance(key, str) else key:
                    (f"<{len(item)} caractères retirés>" if isinstance(key, str) and key.lower() in CONTENT_KEYS
                     and isinstance(item, str) and item else self._walk(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [self._walk(item) for item in value]
        return value


def _path_regex(prefix: str) -> str:
    """Le préfixe, avec `\\`, `/` ou `\\\\` (JSON brut) comme séparateurs, suivi d'une fin de segment."""

    parts = [re.escape(part) for part in re.split(r"[\\/]+", prefix) if part]
    return r"[\\/]{1,2}".join(parts) + r"(?![^\\/\s\"'<>|:])"
