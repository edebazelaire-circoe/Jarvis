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
    # Seconde reprise m-c : le corps s'arrête aussi au marqueur de début suivant (`(?=-----BEGIN )`), et un corps ne
    # contient jamais de `-----` : chaque départ ne relit que jusqu'au marqueur suivant, le coût total reste linéaire.
    re.compile(r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----(?:[^-]|-(?!----))*?"
               r"(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----|(?=-----)|\Z)"),
    # Clé PuTTY (`.ppk`) : de l'en-tête (ou de `Private-Lines:`) jusqu'à `Private-MAC:` compris, ou jusqu'au marqueur
    # PuTTY suivant (linéaire).
    re.compile(r"(?:PuTTY-User-Key-File-\d+:|Private-Lines:)(?:(?!PuTTY-User-Key-File-|Private-Lines:|Private-MAC:)[\s\S])*"
               r"(?:Private-MAC:[^\r\n]*)?"),
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

#: Noms de secret, LISTE EXPLICITE (seconde reprise m-a) : un mot qui désigne seul un secret, où qu'il soit dans le
#: nom (`OPENAI_API_KEY` → `KEY` qualifié par `API`, `refreshToken` → `TOKEN`, `DB_PASSWORD`, `client_secret`).
SECRET_NAME_WORDS = frozenset({"TOKEN", "SECRET", "PASSWORD", "PASSWD", "PWD", "PASSPHRASE", "CREDENTIAL", "CREDENTIALS",
                               "COOKIE", "AUTHORIZATION", "BEARER", "APIKEY", "ACCESSTOKEN", "AUTHTOKEN", "PRIVATEKEY",
                               "SECRETKEY", "CLIENTSECRET", "SESSIONKEY", "ACCESSKEY", "APITOKEN"})
#: `KEY` n'est un secret que précédé d'un de ces mots (`API_KEY`, `x-api-key`, `privateKey`, `Ocp-Apim-Subscription-Key`,
#: `ELEVENLABS_KEY`) ; `supersedes_key`, `idempotency_key`, `output_key`, `cache_key`, `"key": "ui.theme"` restent lisibles.
KEY_QUALIFIERS = frozenset({"API", "ACCESS", "PRIVATE", "SECRET", "SESSION", "SUBSCRIPTION", "CLIENT", "AUTH", "MASTER",
                            "ENCRYPTION", "SIGNING", "SERVICE", "LICENSE", "SHARED", "APP", "DEVELOPER", "WEBHOOK",
                            # fournisseurs dont la clé d'API s'écrit `<FOURNISSEUR>_KEY`
                            "OPENAI", "ANTHROPIC", "ELEVENLABS", "DEEPGRAM", "GOOGLE", "GEMINI", "AZURE", "PORCUPINE",
                            "PICOVOICE", "MISTRAL", "GROQ", "COHERE", "STRIPE", "SENDGRID", "TWILIO", "AWS"})
#: Mots qui font d'un nom un réglage ou un identifiant descriptif (`TOKEN_TYPE`, `MAX_TOKEN`, `token_count`,
#: `credential_ref`, `key_id`, `public_key`, `KeyError`).
DESCRIPTIVE_NAME_WORDS = frozenset({"TYPE", "KIND", "EXPIRES", "EXPIRY", "EXPIRATION", "AT", "SCOPE", "SCOPES", "URL",
                                    "URI", "HOST", "PORT", "MODE", "TIMEOUT", "LENGTH", "SIZE", "COUNT", "MAX", "MIN",
                                    "LIMIT", "ENABLED", "FILE", "PATH", "DIR", "NAME", "ID", "CACHE", "LAYOUT", "HINT",
                                    "REF", "PUBLIC", "ERROR", "EXCEPTION", "SET", "HAS", "IDEMPOTENCY", "SUPERSEDES",
                                    "OUTPUT", "SORT", "PARTITION", "PRIMARY", "DEDUPE", "USAGE", "USED", "BUDGET",
                                    "REMAINING", "ESTIMATE"})
_TRIVIAL_VALUE = re.compile(r"(?i)(?:true|false|yes|no|on|off|none|null|enabled|disabled|[0-9.:+-]*)")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
#: `NOM=valeur`, `NOM: valeur` en texte libre (`.env` collé, YAML, journal), avec les préfixes de shell `export `,
#: `$env:` (PowerShell), `set ` / `set "` (cmd) : la valeur est masquée si le nom est un secret (`named_secret`). Un
#: nom refusé est toujours réexaminé dans sa valeur (`_mask_named`, seconde reprise B1').
_NAMED_VALUE = re.compile(r"(?<![A-Za-z0-9_])((?:export\s+|\$env:|set\s+\"?)?)([A-Za-z][A-Za-z0-9_.-]{0,63})"
                          r"([\"']?[ \t]*[:=][ \t]*)"
                          r"(\\*\"[^\"\\\r\n]{1,1024}\\*\"|'[^'\r\n]{1,1024}'|(?!\[secret masqué\])[^\s\"',;\\]{1,1024})")
#: `setx NOM "valeur"` / `setx NOM valeur` (cmd, sans `=`).
_SETX = re.compile(r"(?i)(?<![A-Za-z0-9_])(setx\s+)([A-Za-z][A-Za-z0-9_.-]{0,63})(\s+)(\"[^\"\r\n]{1,1024}\"|[^\s\"]{1,1024})")
#: Paire JSON dont les guillemets sont échappés une ou plusieurs fois (JSON dans une chaîne JSON, dans un journal).
_ESCAPED_PAIR = re.compile(r'(?<!\\)(\\+")([A-Za-z][A-Za-z0-9_.-]{0,63})\1\s*:\s*\1([^"\\\r\n]{1,1024})\1')
#: Objet « nom / valeur » (tableau de variables, en-têtes HAR, configuration MCP ou Docker) :
#: `{"name": "X-Api-Key", "value": "…"}`, `{"key": "DB_PASSWORD", "value": "…"}`, guillemets échappés ou non, dans les
#: deux ordres (seconde reprise M-a).
_PAIR_NAME_FIRST = re.compile(r'(?<!\\)(\\*")(?:name|key|header|Name|Key|Header)\1\s*:\s*\1([A-Za-z][A-Za-z0-9_.-]{0,63})\1'
                              r'(\s*,\s*\1(?:value|Value)\1\s*:\s*\1)([^"\\\r\n]{1,1024})\1')
_PAIR_VALUE_FIRST = re.compile(r'(?<!\\)(\\*")(?:value|Value)\1\s*:\s*\1([^"\\\r\n]{1,1024})(\1\s*,\s*\1'
                               r'(?:name|key|header|Name|Key|Header)\1\s*:\s*\1)([A-Za-z][A-Za-z0-9_.-]{0,63})\1')
PAIR_NAME_KEYS = frozenset({"name", "key", "header"})


def sensitive_name(name: str) -> bool:
    """Le nom désigne-t-il un secret (`OPENAI_API_KEY`, `refreshToken`, `X-Api-Key`, `client_secret`) plutôt qu'un
    réglage ou un identifiant (`token_count`, `supersedes_key`, `KeyError`) ? Liste explicite : `SECRET_NAME_WORDS`,
    `KEY` qualifié (`KEY_QUALIFIERS`), jamais un mot descriptif (`DESCRIPTIVE_NAME_WORDS`)."""

    words = [word for word in re.split(r"[_.\-\s]+", _CAMEL.sub("_", name or "").upper()) if word]
    if not words or any(word in DESCRIPTIVE_NAME_WORDS for word in words):
        return False
    for index, word in enumerate(words):
        if word in SECRET_NAME_WORDS:
            return True
        if word == "KEY" and index > 0 and words[index - 1] in KEY_QUALIFIERS:
            return True
    return False


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
        text = _mask_named(text)
        text = _SETX.sub(_named_value, text)
        text = _ESCAPED_PAIR.sub(_escaped_pair, text)
        text = _PAIR_NAME_FIRST.sub(_pair_name_first, text)
        text = _PAIR_VALUE_FIRST.sub(_pair_value_first, text)
        text = _EMAIL.sub(EMAIL_MASK, text)
        for pattern, token in self._patterns:
            text = pattern.sub(token.replace("\\", "\\\\"), text)
        text = _USERS_DIR.sub(lambda match: match.group(1) + USER_MASK, text)
        if self._user is not None:
            text = self._user.sub(USER_MASK, text)
        return text

    def cell(self, value: str) -> str:
        """Une cellule de base ou un fichier de la mémoire, JSON ou non (seconde reprise m-b) : UNE passe de `text` sur
        le texte brut. Les formes JSON (paires `"NOM": "valeur"`, paires échappées à toute profondeur, objets
        `name`/`value`) sont reconnues par les expressions de `text`, sans analyser ni réécrire le JSON : une cellule
        sans secret ressort à l'identique."""

        return self.text(value)

    def structured(self, value: Any) -> Any:
        """Copie JSON : identifiants masqués entiers (`redact_structured`), contenu remplacé par sa taille, chaque
        chaîne passée par `text`. Clés et forme gardées : le résultat reste du JSON valide."""

        return self._walk(redact_structured(value, self._secrets))

    def _walk(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.cell(value)
        if isinstance(value, Mapping):
            label = next((value[key] for key in value if isinstance(key, str) and key.lower() in PAIR_NAME_KEYS
                          and isinstance(value[key], str)), None)
            if label is not None and sensitive_name(label):  # {"name": "X-Api-Key", "value": "…"}
                value = {key: (REDACTED if isinstance(key, str) and key.lower() == "value" and isinstance(item, str)
                               and secret_like(label, item.strip()) else item) for key, item in value.items()}
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
    opening = re.match(r"\\*\"|'", value)  # `"`, `\"` (JSON in a string), any escape depth, or `'`
    quote = opening.group(0) if opening and len(value) > 2 * len(opening.group(0)) and value.endswith(opening.group(0)) else ""
    bare = value[len(quote): len(value) - len(quote)] if quote else value
    if not named_secret(match.group(2), bare):
        return match.group(0)
    return f"{match.group(1)}{match.group(2)}{match.group(3)}{quote}{REDACTED}{quote}"


def _mask_named(text: str) -> str:
    """`_NAMED_VALUE` appliqué de sorte qu'un nom refusé n'avale jamais la suite : la recherche reprend au début de sa
    valeur (`$env:OPENAI_API_KEY=…` : `env` est refusé, puis `OPENAI_API_KEY` est examiné). Linéaire : chaque tour
    avance au moins d'un nom et d'un séparateur."""

    out: list[str] = []
    position = 0
    while True:
        match = _NAMED_VALUE.search(text, position)
        if match is None:
            break
        replaced = _named_value(match)
        if replaced != match.group(0):
            out.append(text[position:match.start()])
            out.append(replaced)
            position = match.end()
        else:
            out.append(text[position:match.start(4)])
            position = match.start(4)
    out.append(text[position:])
    return "".join(out)


def _pair_name_first(match: re.Match[str]) -> str:
    if not named_secret(match.group(2), match.group(4)):
        return match.group(0)
    return match.group(0)[: match.start(4) - match.start()] + REDACTED + match.group(1)


def _pair_value_first(match: re.Match[str]) -> str:
    if not named_secret(match.group(4), match.group(2)):
        return match.group(0)
    head = match.group(0)[: match.start(2) - match.start()]
    return head + REDACTED + match.group(0)[match.end(2) - match.start():]


def _escaped_pair(match: re.Match[str]) -> str:
    if not named_secret(match.group(2), match.group(3)):
        return match.group(0)
    quote = match.group(1)
    return f"{quote}{match.group(2)}{quote}: {quote}{REDACTED}{quote}"


def _path_regex(prefix: str) -> str:
    """Le préfixe, avec `\\`, `/` ou `\\\\` (JSON brut) comme séparateurs, suivi d'une fin de segment."""

    parts = [re.escape(part) for part in re.split(r"[\\/]+", prefix) if part]
    return r"[\\/]{1,2}".join(parts) + r"(?![^\\/\s\"'<>|:])"
