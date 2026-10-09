"""Contrat d'exécution isolée d'une scène Remotion : CSP, en-têtes, iframe, routes, page (handoff
jarvis-remotion-presentation-integration, Slice 06 ; `docs/remotion-isolation.md`).

Le `scene.js` compilé (Slice 05) est du code **non fiable** qui s'exécute dans le navigateur de l'utilisateur. La
frontière de sécurité, par couches indépendantes :

1. une **origine dédiée** : une autre adresse de boucle locale ET un autre port que Core / le Control Center (jamais l'origine
   de Core ; des cookies se partagent entre ports d'un même hôte, d'où l'autre adresse) ;
2. un `<iframe sandbox="allow-scripts">` (jamais `allow-same-origin` : origine opaque, ni stockage, ni cookies, ni
   `parent.document`) et le même `sandbox` posé par l'**en-tête** CSP du document ;
3. une **CSP** `default-src 'none'`, scripts par nonce, `connect-src 'none'`, images/médias/polices de l'origine dédiée ;
4. un protocole `postMessage` typé, borné, vérifié par source (`jarvis/runtime/remotion_sandbox_protocol.js`) ;
5. un chien de garde de l'hôte (ping/pong) qui retire le cadre d'une scène figée.

Ce module est **pur** : constructeurs d'en-têtes, de CSP, de page et d'analyse de chemin. La route qui les sert est
`jarvis.runtime.remotion_sandbox.SandboxResponder` ; le Player (Slice 10) la monte, rien n'est câblé ici.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlparse

from jarvis.domain.remotion_compile import CACHE_KEY, HOST_FILE, PUBLIC_DIR, SCENE_FILE
from jarvis.domain.remotion_source import ASSET_EXTENSIONS, ASSET_ROOT, source_path_problem

#: Valeur exacte de l'attribut `sandbox` du cadre et de la directive CSP `sandbox` du document. Jamais `allow-same-origin`,
#: `allow-popups`, `allow-forms`, `allow-top-navigation`, `allow-modals`, `allow-downloads`, `allow-pointer-lock`.
SANDBOX_VALUE = "allow-scripts"
FORBIDDEN_SANDBOX_TOKENS = frozenset({"allow-same-origin", "allow-popups", "allow-popups-to-escape-sandbox", "allow-forms",
                                      "allow-top-navigation", "allow-top-navigation-by-user-activation", "allow-modals",
                                      "allow-downloads", "allow-pointer-lock", "allow-presentation", "allow-orientation-lock"})
#: Attributs de l'`<iframe>` que l'hôte pose (le Player de la Slice 10 les reprend tels quels).
IFRAME_ATTRIBUTES = {"sandbox": SANDBOX_VALUE, "allow": "", "referrerpolicy": "no-referrer", "loading": "eager"}
#: Fonctions du navigateur retirées au document (Permissions-Policy) : aucune n'a de sens dans une scène.
PERMISSIONS_POLICY = ("accelerometer=(), autoplay=(self), camera=(), clipboard-read=(), clipboard-write=(), display-capture=(), "
                      "geolocation=(), gyroscope=(), hid=(), magnetometer=(), microphone=(), midi=(), payment=(), "
                      "publickey-credentials-get=(), serial=(), usb=(), xr-spatial-tracking=()")

PAGE_PREFIX = "/page/"
FILE_PREFIX = "/f/"
MAX_PATH_CHARS = 240
NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")
#: Les seuls fichiers servis d'une entrée de cache : jamais `compile.json`, jamais un fichier non déclaré.
SERVABLE_ROOT_FILES = frozenset({SCENE_FILE, HOST_FILE})

CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
    ".otf": "font/otf", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".mp4": "video/mp4", ".webm": "video/webm",
}
FONT_EXTENSIONS = frozenset({".woff2", ".woff", ".ttf", ".otf"})
#: Extensions lues en CORS par un document d'origine opaque : polices (`@font-face`) et scripts (`integrity` exige CORS).
CORS_EXTENSIONS = FONT_EXTENSIONS | {".js"}


class SandboxContractError(ValueError):
    """Une valeur qui romprait le contrat (nonce, origine, chemin) : jamais servie."""


# ------------------------------------------------------------------ origines

def _canonical_host(host: str) -> str:
    """Hôte canonique : `localhost` ou IPv4 en notation pointée stricte (via `ipaddress` : ni zéros initiaux, ni forme décimale ou
    hexadécimale, ni `127.1`). Deux écritures d'une même adresse ne doivent pas faire croire à deux hôtes."""

    if host == "localhost":
        return host
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        raise SandboxContractError("an origin host is a dotted-quad IPv4 address or localhost") from None
    if str(address) != host or not address.is_loopback:
        raise SandboxContractError("an origin host must be a canonical loopback address (127.x.x.x) or localhost")
    return str(address)


def origin_of(url: str) -> str:
    """`scheme://hôte[:port]` canonique d'une URL http(s) de boucle locale (IPv4 pointée 127.x.x.x ou `localhost`), sinon
    `SandboxContractError`. Pas d'identifiants, de chemin, de requête ni de fragment."""

    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise SandboxContractError("not an origin") from None
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not host or "@" in parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SandboxContractError("an origin is scheme://host[:port] and nothing else")
    if port is not None and not 1 <= port <= 65535:
        raise SandboxContractError("origin port out of range")
    return f"{parsed.scheme}://{_canonical_host(host)}" + (f":{port}" if port is not None else "")


def assert_distinct_origins(embedder: str, sandbox: str) -> None:
    """L'origine du bac à sable ne doit partager avec celle de Core ni l'hôte (cookies communs entre ports) ni, a fortiori, le port."""

    first, second = urlparse(origin_of(embedder)), urlparse(origin_of(sandbox))
    if first.hostname == second.hostname:
        raise SandboxContractError("the sandbox origin must use another host than the embedder (cookies are shared between ports)")


# ------------------------------------------------------------------ en-têtes

def page_csp(nonce: str, embedder_origin: str) -> str:
    """CSP du document du bac à sable (en-tête, pas de `<meta>` : `frame-ancestors` et `sandbox` n'existent qu'en en-tête)."""

    if not NONCE.fullmatch(nonce):
        raise SandboxContractError("nonce must be 16 to 64 base64url characters")
    ancestors = origin_of(embedder_origin)
    return "; ".join([
        "default-src 'none'",
        f"script-src 'nonce-{nonce}'",
        "style-src 'unsafe-inline'",
        "img-src 'self' data:",
        "media-src 'self' data:",  # Remotion's Player unlocks audio with a data: silent clip; a data: URL carries its own bytes, it cannot exfiltrate
        "font-src 'self'",
        "connect-src 'none'",
        "frame-src 'none'",
        "child-src 'none'",
        "worker-src 'none'",
        "object-src 'none'",
        "manifest-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        f"frame-ancestors {ancestors}",
        f"sandbox {SANDBOX_VALUE}",
    ])


#: CSP d'un fichier servi (script, image...) ouvert directement : aucun contenu actif, même un SVG ouvert en document.
FILE_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; sandbox"


def embedder_frame_src(sandbox_origin: str) -> str:
    """Directive `frame-src` de la page qui monte le cadre : le bac à sable **seul**. Elle empêche une scène de naviguer son cadre
    ailleurs (`location.href`). N'y mettre AUCUNE autre origine (ni le visualiseur ni Core) : un cadre qui peut naviguer vers
    une origine de Jarvis y charge une page de Jarvis ; la page qui monte un cadre Remotion n'en porte donc pas d'autre
    (`docs/remotion-isolation.md` §4). La Slice 10 l'applique et le teste elle-même."""

    return "frame-src " + origin_of(sandbox_origin)


def common_headers() -> dict[str, str]:
    return {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Permissions-Policy": PERMISSIONS_POLICY,
            "Cross-Origin-Resource-Policy": "cross-origin", "Cross-Origin-Opener-Policy": "same-origin",
            "X-DNS-Prefetch-Control": "off"}


def page_headers(nonce: str, embedder_origin: str) -> dict[str, str]:
    return {**common_headers(), "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": page_csp(nonce, embedder_origin),
            "Cache-Control": "no-store"}


def file_content_type(path: str) -> str | None:
    extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return CONTENT_TYPES.get(extension)


def file_headers(path: str, length: int) -> dict[str, str]:
    """En-têtes d'un fichier servi : type fixé par l'extension (jamais sniffé), CSP sans contenu actif, aucun cookie. Les polices
    et les scripts portent `Access-Control-Allow-Origin: *` (le document est d'origine opaque : un `@font-face` est une requête
    CORS, et `integrity` sur un script en exige une) ; ce sont des fichiers non secrets de la scène elle-même, lus sans cookie
    (`crossorigin="anonymous"`)."""

    content_type = file_content_type(path)
    if content_type is None:
        raise SandboxContractError("no content type for this file")
    headers = {**common_headers(), "Content-Type": content_type, "Content-Length": str(length), "Content-Security-Policy": FILE_CSP,
               "Cache-Control": "private, max-age=31536000, immutable", "Accept-Ranges": "bytes"}
    if "." + path.rsplit(".", 1)[-1].lower() in CORS_EXTENSIONS:
        headers["Access-Control-Allow-Origin"] = "*"
    return headers


def assert_no_ambient_authority(headers: dict[str, str]) -> None:
    """Une réponse du bac à sable ne pose jamais de cookie ni de jeton (testé sur chaque réponse)."""

    lowered = {name.lower() for name in headers}
    if lowered & {"set-cookie", "authorization", "www-authenticate", "set-cookie2"}:
        raise SandboxContractError("a sandbox response must not carry cookies or credentials")


# ------------------------------------------------------------------ chemins

@dataclass(frozen=True, slots=True)
class SandboxTarget:
    """Ce qu'un chemin demande : la page d'une scène (`scene_key`, `host_key`) ou un fichier (`key`, `file`)."""

    kind: str  # "page" | "file"
    scene_key: str | None = None
    host_key: str | None = None
    key: str | None = None
    file: str | None = None


def parse_sandbox_path(raw_path: str) -> SandboxTarget:
    """`/page/<scene-clé>/<host-clé>` ou `/f/<clé>/scene.js|host.js|public/<asset>`. Lexical : aucun pourcentage, aucun `..`,
    aucun antislash, clés du compilateur, assets selon `source_path_problem`. `SandboxContractError` pour tout le reste."""

    path = raw_path.split("?", 1)[0].split("#", 1)[0]
    if len(path) > MAX_PATH_CHARS or "%" in path or "\\" in path or "\x00" in path or not path.isascii():
        raise SandboxContractError("path refused")
    if path.startswith(PAGE_PREFIX):
        parts = path[len(PAGE_PREFIX):].split("/")
        if len(parts) == 2 and parts[0].startswith("scene-") and parts[1].startswith("host-") and all(CACHE_KEY.fullmatch(p) for p in parts):
            return SandboxTarget("page", scene_key=parts[0], host_key=parts[1])
        raise SandboxContractError("page path refused")
    if path.startswith(FILE_PREFIX):
        key, _, relative = path[len(FILE_PREFIX):].partition("/")
        if not CACHE_KEY.fullmatch(key) or not relative:
            raise SandboxContractError("file path refused")
        if relative in SERVABLE_ROOT_FILES:
            if relative == SCENE_FILE and not key.startswith("scene-") or relative == HOST_FILE and not key.startswith("host-"):
                raise SandboxContractError("file does not belong to this key")
            return SandboxTarget("file", key=key, file=relative)
        if relative.startswith(PUBLIC_DIR + "/") and key.startswith("scene-") \
                and source_path_problem(relative, root=ASSET_ROOT, extensions=ASSET_EXTENSIONS) is None:
            return SandboxTarget("file", key=key, file=relative)
    raise SandboxContractError("path refused")


# ------------------------------------------------------------------ page

def sri(data: bytes) -> str:
    """Valeur `integrity` (SHA-384) d'un fichier : le navigateur refuse un script qui n'est plus celui que Core a vérifié."""

    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")


def _js_literal(value: object) -> str:
    """Littéral JS d'une valeur JSON, sûr dans un `<script>` (`<`, `>`, `&`, U+2028/9 échappés)."""

    return (json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def build_sandbox_page(*, nonce: str, scene_key: str, host_key: str, host_integrity: str, scene_integrity: str,
                       embedder_origin: str, bootstrap_js: str) -> str:
    """Le document du bac à sable. Ordre du contrat : charset, host.js (React, Remotion, Player), le script en ligne (protocole + amorce, nonce)
    qui pose `remotion_staticBase` et écoute l'hôte, puis scene.js ; le Player est monté à `init`. Tous les scripts portent
    le nonce ; `host.js` et `scene.js` portent aussi `integrity`. Aucun script sans nonce n'est exécutable (CSP)."""

    if not NONCE.fullmatch(nonce) or not (CACHE_KEY.fullmatch(scene_key) and CACHE_KEY.fullmatch(host_key)):
        raise SandboxContractError("nonce or cache key malformed")
    if "</script" in bootstrap_js.lower() or "<!--" in bootstrap_js:
        raise SandboxContractError("the bootstrap script cannot be inlined safely")
    config = {"embedder": origin_of(embedder_origin), "staticBase": f"{FILE_PREFIX}{scene_key}/{PUBLIC_DIR}"}
    # Ordre : host.js (de confiance), puis l'amorce, puis scene.js (hostile). L'amorce prend ses références (postMessage du
    # parent, écouteurs) AVANT que le code de la scène ne puisse les remplacer, et écoute déjà ses erreurs de chargement.
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="x-dns-prefetch-control" content="off">'
        "<title>scene</title>"
        "<style>html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:transparent}#root{width:100%;height:100%}</style>"
        "</head><body><div id=\"root\"></div>"
        f'<script nonce="{nonce}" src="{FILE_PREFIX}{host_key}/{HOST_FILE}" integrity="{host_integrity}" crossorigin="anonymous"></script>'
        f'<script nonce="{nonce}">window.__JARVIS_SANDBOX_CONFIG__={_js_literal(config)};\n{bootstrap_js}\n</script>'
        f'<script nonce="{nonce}" src="{FILE_PREFIX}{scene_key}/{SCENE_FILE}" integrity="{scene_integrity}" crossorigin="anonymous"></script>'
        "</body></html>"
    )
