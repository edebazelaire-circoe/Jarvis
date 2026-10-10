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
import posixpath
import hashlib
import re
import tarfile
import time
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
#: Échéance de lecture de l'archive (décompression comprise) : une archive piégée ne tient pas l'import plus longtemps.
READ_DEADLINE_S = 20.0
MAX_PATH_LENGTH = 240

_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
_REPO = re.compile(r"(?=.*[A-Za-z0-9])[A-Za-z0-9._-]{1,100}\Z")
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
    IMPORT_TIMEOUT = "import_timeout"


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
    path = posixpath.normpath(parts.path).lower() + "/" if ".." not in parts.path.split("/") else ""
    if not path.startswith(origin.path_prefix()):
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
    """Flux gzip -> octets, plafonné et PRESSÉ : une bombe de décompression lève `archive_too_large` au lieu de remplir la mémoire, et
    l'échéance de l'import (`deadline`, horloge monotone) lève `import_timeout`. Linéaire : un tampon `bytearray` dont on retire la tête
    (jamais de recopie du reste), des tranches de décompression bornées par la demande."""

    def __init__(self, data: bytes, limit: int, deadline: float | None = None, clock=time.monotonic) -> None:
        self._source = memoryview(data)
        self._at = 0
        self._z = zlib.decompressobj(wbits=31)
        self._buffer = bytearray()
        self._total = 0
        self._limit = limit
        self._deadline = deadline
        self._clock = clock
        self._done = False

    def _check_time(self) -> None:
        if self._deadline is not None and self._clock() > self._deadline:
            raise UpstreamRefusal(UpstreamErrorCode.IMPORT_TIMEOUT, "reading the archive took too long")

    def read(self, size: int = -1) -> bytes:
        want = size if size >= 0 else self._limit + 1
        while len(self._buffer) < want and not self._done:
            self._check_time()
            try:
                if self._z.unconsumed_tail:
                    feed = self._z.unconsumed_tail
                elif self._at < len(self._source):
                    feed = self._source[self._at:self._at + 64 * 1024].tobytes()
                    self._at += len(feed)
                else:
                    self._done = True
                    out = self._z.flush()
                    self._total += len(out)
                    self._buffer += out
                    if not self._z.eof:
                        raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, "archive is not a complete gzip stream")
                    break
                out = self._z.decompress(feed, max(want - len(self._buffer), 64 * 1024))
            except zlib.error:
                raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, "archive is not a valid gzip stream") from None
            self._total += len(out)
            if self._total > self._limit:
                raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_TOO_LARGE, f"archive unpacks to more than {self._limit} bytes")
            self._buffer += out
            if self._z.eof and not self._z.unconsumed_tail:
                self._done = True
        data = bytes(self._buffer[:want])
        del self._buffer[:want]
        return data


class Selector(Protocol):
    def __call__(self, relative_path: str, size: int) -> int | None:
        """Taille maximale à LIRE pour ce fichier (chemin relatif à la racine du dépôt), `None` = ne pas le lire."""


def read_tar_source(data: bytes, *, expected_commit: str, select: Selector, deadline_s: float = READ_DEADLINE_S,
                    clock=time.monotonic) -> TarContent:
    """Lit un `tar.gz` de GitHub (`codeload`) en mémoire, en flux. Refuse l'archive entière (`UpstreamRefusal`) pour :
    lien symbolique ou physique, périphérique, chemin absolu / `..` / antislash / lecteur / NUL, deux membres au même nom (casse
    comprise), plusieurs racines, plus de `MAX_ENTRIES` membres, plus de `MAX_UNPACKED_BYTES` décompressés, commit attesté
    (en-tête pax `comment`) absent ou différent de `expected_commit`. N'écrit rien sur disque ; ne lit que les fichiers que
    `select` désigne."""

    if len(data) > MAX_DOWNLOAD_BYTES:
        raise UpstreamRefusal(UpstreamErrorCode.FETCH_TOO_LARGE, f"archive is {len(data)} bytes, at most {MAX_DOWNLOAD_BYTES}")
    deadline = clock() + deadline_s
    stream = _BoundedGunzip(data, MAX_UNPACKED_BYTES, deadline, clock)
    files: dict[str, bytes] = {}
    paths: list[str] = []
    oversize: set[str] = set()
    seen: set[str] = set()
    root: str | None = None
    read_total = 0
    entries = 0
    try:
        archive = tarfile.open(fileobj=stream, mode="r|", bufsize=1024 * 1024)  # type: ignore[arg-type]
    except tarfile.TarError:
        raise UpstreamRefusal(UpstreamErrorCode.ARCHIVE_INVALID, "archive is not a tar stream") from None
    try:
        with archive:
            for member in _members(archive):
                if clock() > deadline:
                    raise UpstreamRefusal(UpstreamErrorCode.IMPORT_TIMEOUT, "reading the archive took too long")
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
MAX_LICENCE_BYTES = 32 * 1024
MAX_LICENCE_FILES = 8

#: Empreintes SHA-256 des textes CANONIQUES (mots normalisés : minuscules, ponctuation retirée, titre, ligne de copyright et
#: « all rights reserved » retirés ; Apache-2.0 : jusqu'à « END OF TERMS AND CONDITIONS »), calculées sur les textes de l'API de
#: licences de GitHub (`tests/fakes/licenses/*.txt`, vérifiées par `test_remotion_upstream`). Un texte qui n'est pas EXACTEMENT l'un
#: d'eux (un paragraphe de plus, une clause « Commons », « usage personnel »...) n'est pas reconnu.
CANONICAL_LICENCE_HASHES: dict[str, tuple[str, ...]] = {
    "0BSD": ("25a274d52b3014d9bd64e0f3362fd279ac1655f163d5c518f6b9f6c43354802c",),
    "Apache-2.0": ("e80c728dad9283541363fd9f60e4c0527fadc838f92f45f514c14da7f0a481ad",
                   "594673f8fe0542761280c31fa6f0d1eca9f491e533af6c2c1fef40b1c4229b47"),
    "BSD-2-Clause": ("a56fee4b2f66331ed54da4950ef9c9391453fd1490b4d8ea202bc29683bcbd30",),
    "BSD-3-Clause": ("9b83d3dee0616d07b82a272dd9bf5134a9f402b750f5ee6188458073b0a32ff2",),
    "CC0-1.0": ("96bdc7f63190fb4bd1ae584b890300ed7517d858b34c945642a3b9b2f1612a5f",),
    "ISC": ("217da0747cec63a2e734185db11cbaa819bcd9e5b83cd12f812128fffe66e26a",),
    "MIT": ("0cf21bdfd1964a97a8615e128534845826afbc887edc95aa5c925cbf64386b5c",),
    "Unlicense": ("fd1b07be5f4f94926b6ea4df3943b05ab90c1a1f3b1a3d574ae7ab58bca58fff",),
}
_TITLES = ("the mit license", "mit license", "the isc license", "isc license", "bsd 2 clause license", "bsd 3 clause license",
           "the bsd 2 clause license", "the bsd 3 clause license", "bsd 2 clause simplified license", "bsd 3 clause new or revised license",
           "zero clause bsd license", "bsd zero clause license", "the unlicense", "unlicense")
#: Mots qui font d'un texte AUTRE chose qu'une permission générale : restriction d'usage ajoutée à une licence connue.
_RESTRICTION_WORDS = re.compile(r"commons clause|personal use|non commercial|noncommercial|not for commercial|no commercial|monetis|monetiz|"
                                r"educational use only|may not sell|you may not use|without the prior written permission|"
                                r"for non profit|research use only|evaluation only")
_END_OF_APACHE = "end of terms and conditions"


def is_licence_file(relative_path: str) -> bool:
    """Un fichier de licence à la racine (ou du sous-dossier du projet) : `LICENSE`, `LICENSE.md`, `LICENSE-MIT`, `COPYING`, `UNLICENSE`..."""

    name = relative_path.lower()
    return "/" not in relative_path and len(name) <= 40 and name.startswith(("license", "licence", "copying", "unlicense"))


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def canonical_words(text: str) -> str:
    """Mots du corps d'une licence : paragraphes de copyright et « all rights reserved » retirés, titre connu retiré."""

    paragraphs = re.split(r"\n\s*\n", text.replace("\r", ""))
    kept = [p for p in paragraphs if not re.match(r"\s*(copyright|\(c\)|©)", p, re.I)]
    kept = [re.sub(r"(?im)^\s*all rights reserved\.?\s*$", "", p) for p in kept]
    words = _words("\n\n".join(kept))
    for title in sorted(_TITLES, key=len, reverse=True):
        if words.startswith(title + " "):
            return words[len(title) + 1:]
    return words


def canonical_key(text: str) -> str | None:
    """SPDX d'un texte QUI EST un texte canonique (aucune différence autre que titre, copyright, mise en forme), sinon `None`."""

    words = canonical_words(text)
    cut = words.find(_END_OF_APACHE)
    candidates = [words]  # Apache-2.0 : le texte entier avec son annexe, ou le corps seul (rien après « END OF TERMS »)
    if cut >= 0 and not words[cut + len(_END_OF_APACHE):].strip():
        candidates.append(words[:cut + len(_END_OF_APACHE)])
    for candidate in candidates:
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        for spdx, known in CANONICAL_LICENCE_HASHES.items():
            if digest in known:
                return spdx
    return None


def classify_licence_text(text: str) -> str | None:
    """SPDX d'un texte de licence reconnu EXACTEMENT, `RESTRICTED:<nom>` pour une licence reconnue mais refusée ou un texte qui
    ajoute une restriction, `None` = inconnue. Une licence connue AVEC un paragraphe de plus n'est jamais acceptée."""

    w = _words(text)
    if "remotion license" in w or ("company license" in w and "remotion" in w):
        return "RESTRICTED:Remotion-License"
    for needle, name in (("gnu affero general public license", "AGPL"), ("gnu lesser general public license", "LGPL"),
                         ("gnu general public license", "GPL"), ("mozilla public license", "MPL"),
                         ("european union public licence", "EUPL"), ("european union public license", "EUPL"),
                         ("server side public license", "SSPL"), ("business source license", "BUSL"),
                         ("eclipse public license", "EPL"), ("common development and distribution license", "CDDL")):
        if needle in w:
            return f"RESTRICTED:{name}"
    exact = canonical_key(text)
    if exact is not None:
        return exact
    if "creative commons" in w:
        return "RESTRICTED:Creative-Commons"
    if _RESTRICTION_WORDS.search(w):
        return "RESTRICTED:Added-Restriction"
    return None


def classify_licence(files: Mapping[str, bytes], package_json: Mapping[str, Any] | None) -> Licence:
    """Licence DU MODÈLE (jamais celle de Remotion) : TOUS les fichiers de licence sont examinés et doivent dire la même chose, puis
    `package.json` doit être d'accord. Lève `UpstreamRefusal` (`license_*`) quand elle n'est pas redistribuable ou pas établie."""

    declared = package_json.get("license") if isinstance(package_json, Mapping) else None
    declared = declared.strip() if isinstance(declared, str) else ""
    texts = [(name, files[name]) for name in sorted(files) if is_licence_file(name)][:MAX_LICENCE_FILES]
    verdicts: dict[str, str] = {}
    first_text = ""
    for name, body in texts:
        text = body.decode("utf-8", errors="replace")
        verdict = classify_licence_text(text)
        if verdict is None:
            raise UpstreamRefusal(UpstreamErrorCode.LICENSE_UNKNOWN,
                                  f"{name}: the licence text is not exactly one of the reviewed licences {sorted(PERMITTED_LICENCES)}")
        if verdict.startswith("RESTRICTED:"):
            raise UpstreamRefusal(UpstreamErrorCode.LICENSE_RESTRICTED,
                                  f"{name}: licence {verdict.split(':', 1)[1]} does not allow redistribution as a Jarvis prefab")
        verdicts[name] = verdict
        first_text = first_text or text[:MAX_LICENCE_BYTES]
    if len(set(verdicts.values())) > 1:
        raise UpstreamRefusal(UpstreamErrorCode.LICENSE_CONFLICT,
                              "the licence files disagree: " + ", ".join(f"{name}={spdx}" for name, spdx in sorted(verdicts.items())))
    from_file = next(iter(verdicts.values()), None)
    if declared.upper() in ("UNLICENSED", "SEE LICENSE IN LICENSE") and from_file is None:
        raise UpstreamRefusal(UpstreamErrorCode.LICENSE_UNLICENSED,
                              f"package.json declares {declared!r} and the repository has no licence file: nothing allows redistribution")
    if from_file is not None:
        if declared and declared.upper() not in ("SEE LICENSE IN LICENSE", from_file.upper()):
            raise UpstreamRefusal(UpstreamErrorCode.LICENSE_CONFLICT,
                                  f"the licence file reads {from_file} but package.json declares {declared!r}: the author contradicts themselves")
        return Licence(from_file, "file", first_text)
    if not declared:
        raise UpstreamRefusal(UpstreamErrorCode.LICENSE_MISSING,
                              "the repository has no licence file and package.json declares no licence: all rights are reserved by default")
    if _RESTRICTED_SPDX.search(declared):
        raise UpstreamRefusal(UpstreamErrorCode.LICENSE_RESTRICTED, f"package.json declares {declared[:60]!r}, which is not redistributable here")
    for permitted in PERMITTED_LICENCES:
        if declared.lower() == permitted.lower():
            return Licence(permitted, "package.json")
    raise UpstreamRefusal(UpstreamErrorCode.LICENSE_UNKNOWN, f"package.json declares {declared[:60]!r}, which is not a reviewed licence")
