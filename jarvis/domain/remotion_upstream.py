"""Origine amont d'un modèle Remotion : liste blanche, archive tar épinglée, licence (Slice 18, `docs/remotion-import.md`).

Pur : aucune E/S réseau ni disque. Trois responsabilités, toutes de VÉRIFICATION d'une chose venue d'ailleurs :

- **Origine** (`parse_origin`, `redirect_refusal`) : seul `https://github.com/<propriétaire>/<dépôt>` est accepté, le propriétaire
  doit figurer dans la liste blanche réglée par l'utilisateur, le commit est un SHA complet (jamais une branche ni une étiquette,
  qui bougent). L'adresse de téléchargement est CONSTRUITE (`codeload.github.com/.../tar.gz/<sha>`), jamais reprise telle quelle.
- **Archive** (`read_tar_source`) : un `tar.gz` lu en flux, borné, sans rien écrire sur disque. Lien, périphérique, chemin qui
  sort de la racine (zip-slip), doublon (casse comprise), bombe de décompression, SHA du commit non attesté : l'archive est refusée.
- **Licence** (`classify_licence`) : l'identifiant SPDX de la licence DU MODÈLE, jamais celle de Remotion (le moteur a sa propre
  licence, qui peut exiger une licence d'entreprise : `REMOTION_RUNTIME_LICENCE`). Inconnue, absente, `UNLICENSED`, copyleft,
  non commerciale ou propre à Remotion : refusée.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import re
import tarfile
from typing import Any, Iterator, Mapping, Protocol
from urllib.parse import urlsplit
import zlib

#: Hôtes dont l'archive peut venir (point d'entrée puis redirections). Aucun autre hôte, quelle que soit la liste des propriétaires.
ARCHIVE_HOST = "codeload.github.com"
REPOSITORY_HOST = "github.com"
REDIRECT_HOSTS = frozenset({ARCHIVE_HOST, REPOSITORY_HOST})
MAX_REDIRECTS = 3

DEFAULT_ALLOWED_OWNERS: tuple[str, ...] = ("remotion-dev",)
MAX_ALLOWED_OWNERS = 32

MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
MAX_UNPACKED_BYTES = 96 * 1024 * 1024
MAX_ENTRIES = 6000
MAX_READ_BYTES = 24 * 1024 * 1024
MAX_PATH_LENGTH = 240

_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SUBDIR = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+){0,5}\Z")

#: La licence du MOTEUR, à ne jamais confondre avec celle du modèle : écrite telle quelle dans `catalog.runtime_license`.
REMOTION_RUNTIME_LICENCE = "Remotion License (company licence may be required)"


class UpstreamErrorCode:
    """Codes typés des refus d'import (`UpstreamRefusal.code`). Un code par cause, jamais un message générique."""

    ORIGIN_INVALID = "origin_invalid"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"
    COMMIT_NOT_PINNED = "commit_not_pinned"
    REDIRECT_REFUSED = "redirect_refused"
    FETCH_FAILED = "fetch_failed"
    FETCH_TIMEOUT = "fetch_timeout"
    FETCH_TOO_LARGE = "fetch_too_large"
    ARCHIVE_INVALID = "archive_invalid"
    ARCHIVE_LINK = "archive_link"
    ARCHIVE_PATH = "archive_path"
    ARCHIVE_DUPLICATE = "archive_duplicate"
    ARCHIVE_TOO_LARGE = "archive_too_large"
    ARCHIVE_COMMIT_MISMATCH = "archive_commit_mismatch"
    LICENSE_MISSING = "license_missing"
    LICENSE_UNKNOWN = "license_unknown"
    LICENSE_UNLICENSED = "license_unlicensed"
    LICENSE_RESTRICTED = "license_restricted"
    LICENSE_CONFLICT = "license_conflict"


class UpstreamRefusal(ValueError):
    """Refus typé : `code` (`UpstreamErrorCode`), `message` d'une phrase sans chemin du poste, `details` bornés."""

    def __init__(self, code: str, message: str, details: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = tuple(item[:200] for item in details[:20])

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            body["details"] = list(self.details)
        return body


# ------------------------------------------------------------------ origine

@dataclass(frozen=True, slots=True)
class UpstreamOrigin:
    owner: str
    repo: str
    commit: str

    @property
    def repository_url(self) -> str:
        return f"https://{REPOSITORY_HOST}/{self.owner}/{self.repo}"

    @property
    def archive_url(self) -> str:
        return f"https://{ARCHIVE_HOST}/{self.owner}/{self.repo}/tar.gz/{self.commit}"

    @property
    def name(self) -> str:
        return f"{self.owner}/{self.repo}"

    def path_prefix(self) -> str:
        return f"/{self.owner}/{self.repo}/".lower()


def normalise_owners(raw: object) -> tuple[str, ...]:
    """Liste blanche des propriétaires depuis les réglages : tolérante (une entrée illisible est écartée, jamais une exception),
    en minuscules, sans doublon ; vide ou absente -> la valeur par défaut. Les HÔTES ne se règlent pas."""

    if raw is None:
        return DEFAULT_ALLOWED_OWNERS
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_ALLOWED_OWNERS
    owners: list[str] = []
    for item in raw[:MAX_ALLOWED_OWNERS]:
        if isinstance(item, str) and _OWNER.fullmatch(item.strip()) and item.strip().lower() not in owners:
            owners.append(item.strip().lower())
    return tuple(owners) or DEFAULT_ALLOWED_OWNERS


def parse_origin(repo_url: object, commit: object, allowed_owners: tuple[str, ...]) -> UpstreamOrigin:
    """Valide l'adresse du dépôt et le commit ; rend l'origine ou lève `UpstreamRefusal` (jamais d'accès réseau)."""

    if not isinstance(repo_url, str) or not repo_url.strip() or len(repo_url) > 200 or any(c.isspace() or ord(c) < 32 for c in repo_url):
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_INVALID, "repo_url must be https://github.com/<owner>/<repo>")
    try:
        parts = urlsplit(repo_url)
        port = parts.port
    except ValueError:
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_INVALID, "repo_url is not a valid address") from None
    if parts.scheme != "https":
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_INVALID, "only https addresses are accepted")
    if parts.username is not None or parts.password is not None or port is not None or parts.query or parts.fragment:
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_INVALID, "the address must not carry credentials, a port, a query or a fragment")
    if (parts.hostname or "").lower() != REPOSITORY_HOST:
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_NOT_ALLOWED,
                              f"host {(parts.hostname or '')[:60]!r} is not an allowed origin (only {REPOSITORY_HOST} repositories)")
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) != 2:
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_INVALID, "repo_url must name exactly one repository: https://github.com/<owner>/<repo>")
    owner, repo = segments[0], segments[1].removesuffix(".git")
    if not _OWNER.fullmatch(owner) or not _REPO.fullmatch(repo) or repo in (".", ".."):
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_INVALID, "owner or repository name is not valid")
    if owner.lower() not in allowed_owners:
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_NOT_ALLOWED,
                              f"owner {owner!r} is not in the import allowlist {list(allowed_owners)}: add it in the settings first",
                              tuple(allowed_owners))
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        raise UpstreamRefusal(UpstreamErrorCode.COMMIT_NOT_PINNED,
                              "commit must be a full 40-character lowercase hexadecimal SHA (a branch or a tag moves, a SHA does not)")
    return UpstreamOrigin(owner, repo, commit)


def valid_subdir(raw: object) -> str:
    """Sous-dossier du projet Remotion dans le dépôt (monorepo) : relatif, sans `..`, `""` = racine."""

    if raw in (None, ""):
        return ""
    if not isinstance(raw, str) or not _SUBDIR.fullmatch(raw) or any(part in (".", "..") for part in raw.split("/")):
        raise UpstreamRefusal(UpstreamErrorCode.ORIGIN_INVALID, "subdir must be a short relative path (letters, digits, . _ -)")
    return raw


def redirect_refusal(origin: UpstreamOrigin, location: str) -> str | None:
    """Pourquoi une redirection est refusée (`None` = acceptée) : https, hôte de `REDIRECT_HOSTS`, sans identifiants ni port, et
    chemin DU MÊME dépôt (un dépôt transféré vers un autre propriétaire n'est pas suivi : l'utilisateur ne l'a pas autorisé)."""

    try:
        parts = urlsplit(location)
        port = parts.port
    except ValueError:
        return "redirect target is not a valid address"
    if parts.scheme != "https":
        return "redirect target is not https"
    if parts.username is not None or parts.password is not None or port is not None:
        return "redirect target carries credentials or a port"
    host = (parts.hostname or "").lower()
    if host not in REDIRECT_HOSTS:
        return f"redirect to host {host[:60]!r} is not allowed"
    if not parts.path.lower().startswith(origin.path_prefix()):
        return "redirect leaves the pinned repository"
    return None


# ------------------------------------------------------------------ archive

@dataclass(frozen=True, slots=True)
class TarContent:
    """Ce qu'une lecture d'archive rend : fichiers pertinents (octets), liste des chemins vus, oversize, commit attesté."""

    files: Mapping[str, bytes]
    paths: tuple[str, ...]
    oversize: frozenset[str]
    commit: str
    entries: int


class _BoundedGunzip:
    """Flux gzip -> octets, plafonné : une bombe de décompression lève `archive_too_large` au lieu de remplir la mémoire."""

    def __init__(self, data: bytes, limit: int) -> None:
        self._source = io.BytesIO(data)
        self._z = zlib.decompressobj(wbits=31)
        self._buffer = b""
        self._total = 0
        self._limit = limit
        self._done = False

    def read(self, size: int = -1) -> bytes:
        while (size < 0 or len(self._buffer) < size) and not self._done:
            chunk = self._source.read(64 * 1024)
            if not chunk:
                self._done = True
                try:
                    out = self._z.flush()
                except zlib.error:
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, "archive is not a complete gzip stream") from None
                self._buffer += out
                self._total += len(out)
                break
            try:
                out = self._z.decompress(chunk, self._limit - self._total + 1)
            except zlib.error:
                raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, "archive is not a valid gzip stream") from None
            self._total += len(out)
            if self._total > self._limit or self._z.unconsumed_tail:
                raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_TOO_LARGE, f"archive unpacks to more than {self._limit} bytes")
            self._buffer += out
        if size < 0:
            data, self._buffer = self._buffer, b""
        else:
            data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data


class Selector(Protocol):
    def __call__(self, relative_path: str, size: int) -> int | None:
        """Taille maximale à LIRE pour ce fichier (chemin relatif à la racine du dépôt), `None` = ne pas le lire."""


def read_tar_source(data: bytes, *, expected_commit: str, select: Selector) -> TarContent:
    """Lit un `tar.gz` de GitHub (`codeload`) en mémoire, en flux. Refuse l'archive entière (`UpstreamRefusal`) pour :
    lien symbolique ou physique, périphérique, chemin absolu / `..` / antislash / lecteur / NUL, deux membres au même nom (casse
    comprise), plusieurs racines, plus de `MAX_ENTRIES` membres, plus de `MAX_UNPACKED_BYTES` décompressés, commit attesté
    (en-tête pax `comment`) absent ou différent de `expected_commit`. N'écrit rien sur disque ; ne lit que les fichiers que
    `select` désigne."""

    if len(data) > MAX_DOWNLOAD_BYTES:
        raise UpstreamRefusal(UpstreamErrorCode.FETCH_TOO_LARGE, f"archive is {len(data)} bytes, at most {MAX_DOWNLOAD_BYTES}")
    stream = _BoundedGunzip(data, MAX_UNPACKED_BYTES)
    files: dict[str, bytes] = {}
    paths: list[str] = []
    oversize: set[str] = set()
    seen: set[str] = set()
    root: str | None = None
    read_total = 0
    entries = 0
    try:
        archive = tarfile.open(fileobj=stream, mode="r|")  # type: ignore[arg-type]
    except tarfile.TarError:
        raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, "archive is not a tar stream") from None
    try:
        with archive:
            for member in _members(archive):
                entries += 1
                if entries > MAX_ENTRIES:
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_TOO_LARGE, f"archive has more than {MAX_ENTRIES} entries")
                name = member.name
                label = name[:80]
                if member.issym() or member.islnk():
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_LINK, f"{label}: links are refused")
                if not (member.isfile() or member.isdir()):
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_LINK, f"{label}: only files and directories are accepted")
                problem = _name_problem(name)
                if problem:
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_PATH, f"{label}: {problem}")
                first, _, rest = name.strip("/").partition("/")
                if root is None:
                    root = first
                elif first != root:
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_PATH, f"{label}: the archive has more than one top-level folder")
                folded = name.strip("/").lower()
                if folded in seen:
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_DUPLICATE, f"{label}: two members have the same name (or differ only by case)")
                seen.add(folded)
                if member.isdir() or not rest:
                    continue
                paths.append(rest)
                limit = select(rest, member.size)
                if limit is None:
                    continue
                if member.size > limit:
                    oversize.add(rest)
                    continue
                read_total += member.size
                if read_total > MAX_READ_BYTES:
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_TOO_LARGE, f"selected files exceed {MAX_READ_BYTES} bytes")
                handle = archive.extractfile(member)
                body = b"" if handle is None else handle.read(member.size + 1)
                if len(body) != member.size:
                    raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, f"{label}: member does not match its header")
                files[rest] = body
            pax = dict(archive.pax_headers)
    except UpstreamRefusal:
        raise
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as exc:
        raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, f"archive cannot be read ({type(exc).__name__})") from None
    attested = str(pax.get("comment", "")).strip().lower()
    if attested != expected_commit:
        raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_COMMIT_MISMATCH,
                              "the archive does not attest the pinned commit" if not attested
                              else "the archive was made from another commit than the pinned one")
    if root is None or not paths:
        raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, "archive holds no file")
    return TarContent(files, tuple(paths), frozenset(oversize), attested, entries)


def _members(archive: tarfile.TarFile) -> Iterator[tarfile.TarInfo]:
    while True:
        member = archive.next()
        if member is None:
            return
        yield member


def _name_problem(name: str) -> str | None:
    if "\x00" in name or "\\" in name:
        return "path contains a NUL or a backslash"
    if name.startswith("/") or re.match(r"[A-Za-z]:", name):
        return "path is absolute"
    if len(name) > MAX_PATH_LENGTH:
        return "path is too long"
    parts = name.strip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "path leaves the archive root (.. or empty segment)"
    return None


# ------------------------------------------------------------------ licence

@dataclass(frozen=True, slots=True)
class Licence:
    spdx: str
    source: str  # "file" (LICENSE du dépôt) ou "package.json"
    text: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"spdx": self.spdx, "source": self.source}


#: Identifiants SPDX redistribuables. Tout le reste est refusé : on n'élargit que par une revue de licence écrite ici.
PERMITTED_LICENCES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense", "CC0-1.0"})
_RESTRICTED_SPDX = re.compile(r"(?i)(gpl|agpl|lgpl|mpl|eupl|cddl|epl|sspl|busl|-nc|noncommercial|-nd|remotion)")
LICENCE_FILES = ("license", "license.md", "license.txt", "licence", "licence.md", "licence.txt", "copying", "copying.md", "unlicense")
MAX_LICENCE_BYTES = 32 * 1024


def is_licence_file(relative_path: str) -> bool:
    return "/" not in relative_path and relative_path.lower() in LICENCE_FILES


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def classify_licence_text(text: str) -> str | None:
    """SPDX d'un texte de licence connu, `RESTRICTED:<nom>` pour une licence reconnue mais refusée, `None` = inconnue."""

    w = _words(text)
    if "remotion license" in w or "company license" in w and "remotion" in w:
        return "RESTRICTED:Remotion-License"
    for needle, name in (("gnu affero general public license", "AGPL"), ("gnu lesser general public license", "LGPL"),
                         ("gnu general public license", "GPL"), ("mozilla public license", "MPL"),
                         ("european union public licence", "EUPL"), ("european union public license", "EUPL"),
                         ("server side public license", "SSPL"), ("business source license", "BUSL"),
                         ("eclipse public license", "EPL"), ("common development and distribution license", "CDDL")):
        if needle in w:
            return f"RESTRICTED:{name}"
    if "creative commons" in w and "cc0" not in w and "zero" not in w:
        return "RESTRICTED:Creative-Commons"
    if "noncommercial" in w or "non commercial" in w:
        return "RESTRICTED:NonCommercial"
    if "apache license" in w and "version 2 0" in w:
        return "Apache-2.0"
    if "permission is hereby granted free of charge" in w and "the software is provided as is" in w:
        return "MIT"
    if "redistribution and use in source and binary forms" in w:
        if "neither the name" in w or "the names of its contributors" in w:
            return "BSD-3-Clause"
        return "BSD-2-Clause"
    if "permission to use copy modify and or distribute this software for any purpose with or without fee" in w:
        return "ISC" if "provided that the above copyright notice" in w else "0BSD"
    if "this is free and unencumbered software released into the public domain" in w:
        return "Unlicense"
    if "cc0 1 0 universal" in w or "creative commons zero" in w:
        return "CC0-1.0"
    return None


def classify_licence(files: Mapping[str, bytes], package_json: Mapping[str, Any] | None) -> Licence:
    """Licence DU MODÈLE (jamais celle de Remotion) : le fichier du dépôt d'abord, `package.json` ensuite. Lève `UpstreamRefusal`
    (`license_*`) quand elle n'est pas redistribuable ou pas établie. Un désaccord fichier / `package.json` est refusé aussi."""

    declared = package_json.get("license") if isinstance(package_json, Mapping) else None
    declared = declared.strip() if isinstance(declared, str) else ""
    texts = [(name, files[name]) for name in sorted(files) if is_licence_file(name)]
    from_file: str | None = None
    text = ""
    for name, body in texts:
        verdict = classify_licence_text(body.decode("utf-8", errors="replace"))
        if verdict is None:
            raise UpstreamRefusal(UpstreamErrorCode.LICENSE_UNKNOWN,
                                  f"{name}: the licence text is not one of the reviewed licences {sorted(PERMITTED_LICENCES)}")
        if verdict.startswith("RESTRICTED:"):
            raise UpstreamRefusal(UpstreamErrorCode.LICENSE_RESTRICTED,
                                  f"{name}: licence {verdict.split(':', 1)[1]} does not allow redistribution as a Jarvis prefab")
        from_file, text = verdict, body.decode("utf-8", errors="replace")[:MAX_LICENCE_BYTES]
        break
    if declared.upper() in ("UNLICENSED", "SEE LICENSE IN LICENSE") and from_file is None:
        raise UpstreamRefusal(UpstreamErrorCode.LICENSE_UNLICENSED,
                              f"package.json declares {declared!r} and the repository has no licence file: nothing allows redistribution")
    if from_file is not None:
        if declared and declared.upper() not in ("SEE LICENSE IN LICENSE", from_file.upper()):
            raise UpstreamRefusal(UpstreamErrorCode.LICENSE_CONFLICT,
                                  f"the licence file reads {from_file} but package.json declares {declared!r}: the author contradicts themselves")
        return Licence(from_file, "file", text)
    if not declared:
        raise UpstreamRefusal(UpstreamErrorCode.LICENSE_MISSING,
                              "the repository has no licence file and package.json declares no licence: all rights are reserved by default")
    if _RESTRICTED_SPDX.search(declared):
        raise UpstreamRefusal(UpstreamErrorCode.LICENSE_RESTRICTED, f"package.json declares {declared[:60]!r}, which is not redistributable here")
    for permitted in PERMITTED_LICENCES:
        if declared.lower() == permitted.lower():
            return Licence(permitted, "package.json")
    raise UpstreamRefusal(UpstreamErrorCode.LICENSE_UNKNOWN, f"package.json declares {declared[:60]!r}, which is not a reviewed licence")
