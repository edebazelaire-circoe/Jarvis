"""Route du bac à sable d'une scène Remotion : la réponse HTTP, sans serveur (handoff
jarvis-remotion-presentation-integration, Slice 06 ; `docs/remotion-isolation.md`).

`SandboxResponder.respond(method, raw_path, host_header, range_header)` rend `(status, en-têtes, corps)` pour les deux seules
routes de l'origine dédiée :

    GET /page/<scene-clé>/<host-clé>      le document du cadre (CSP à nonce neuf, `integrity` des scripts)
    GET /f/<clé>/scene.js | host.js | public/<asset>   un fichier de la sortie de compilation

Le Player (Slice 10) la monte sur un **second écouteur de boucle locale** (autre adresse et autre port que Core), jamais sur
l'origine de Core. Rien n'est câblé ici : cette classe n'ouvre aucun socket et ne démarre aucun processus. Les fichiers
viennent de `RemotionCompiler.resolve_output_file` (la seule porte, SHA-256 vérifié) ; rien d'autre n'est lisible par cette route.

Défenses de la route : méthode GET/HEAD seulement ; `Host` dans une liste (ré-association DNS) ; chemin lexical (aucun `%`,
`..`, antislash) ; type de contenu fixé par l'extension ; aucune réponse ne porte de cookie ni de jeton ; erreurs uniformes
et sans chemin disque (404 pour un fichier inconnu, 500 pour un cache illisible, journalisé).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import re
import secrets

from jarvis.domain import remotion_sandbox as sb
from jarvis.domain.remotion_compile import RemotionCompileError

BOOTSTRAP_FILES = ("remotion_sandbox_protocol.js", "remotion_sandbox_child.js")
_RANGE = re.compile(r"bytes=(\d{0,12})-(\d{0,12})\Z")
MAX_SERVED_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SandboxResponse:
    status: int
    headers: dict[str, str]
    body: bytes = b""


def load_bootstrap(runtime_dir: Path | None = None) -> str:
    """Protocole puis amorce, concaténés : le script en ligne de la page du cadre."""

    folder = runtime_dir or Path(__file__).resolve().parent
    return "\n".join((folder / name).read_text(encoding="utf-8") for name in BOOTSTRAP_FILES)


@dataclass
class SandboxResponder:
    """`resolve_file(clé, chemin) -> Path` est `RemotionCompiler.resolve_output_file`. `allowed_hosts` : les `Host:` acceptés
    (`127.77.0.2:18000`). `embedder_origin` : l'origine de la page qui héberge le cadre (Control Center), seule autorisée à
    l'encadrer (`frame-ancestors`) et seule destinataire des messages du cadre."""

    resolve_file: Callable[[str, str], Path]
    embedder_origin: str
    sandbox_origin: str
    allowed_hosts: frozenset[str]
    bootstrap_js: str
    nonce_factory: Callable[[], str] = field(default=lambda: secrets.token_urlsafe(18))
    trace: Callable[[str, str, dict], None] | None = None

    def __post_init__(self) -> None:
        sb.assert_distinct_origins(self.embedder_origin, self.sandbox_origin)

    # ------------------------------------------------------------------ public

    def respond(self, method: str, raw_path: str, host_header: str | None, range_header: str | None = None) -> SandboxResponse:
        if method not in ("GET", "HEAD"):
            return self._plain(405, "method not allowed", {"Allow": "GET, HEAD"})
        if (host_header or "").lower() not in self.allowed_hosts:
            return self._plain(421, "misdirected request")
        try:
            target = sb.parse_sandbox_path(raw_path)
        except sb.SandboxContractError:
            return self._plain(404, "not found")
        try:
            response = self._page(target) if target.kind == "page" else self._file(target, range_header)
        except FileNotFoundError:
            return self._plain(404, "not found")
        except (RemotionCompileError, OSError) as exc:
            code = exc.code.value if isinstance(exc, RemotionCompileError) else type(exc).__name__
            missing = isinstance(exc, RemotionCompileError) and "has no compiled file" in exc.message
            self._trace("remotion.sandbox.unavailable" if not missing else "remotion.sandbox.unknown_file",
                        "Fichier de sortie introuvable ou illisible", {"path": raw_path[:120], "code": code})
            return self._plain(404 if missing else 500, "not found" if missing else "unavailable")
        sb.assert_no_ambient_authority(response.headers)
        if method == "HEAD":
            return SandboxResponse(response.status, response.headers, b"")
        return response

    # ------------------------------------------------------------------ routes

    def _page(self, target: sb.SandboxTarget) -> SandboxResponse:
        assert target.scene_key and target.host_key
        host_bytes = self._read(target.host_key, "host.js")
        scene_bytes = self._read(target.scene_key, "scene.js")
        nonce = self.nonce_factory()
        page = sb.build_sandbox_page(nonce=nonce, scene_key=target.scene_key, host_key=target.host_key,
                                     host_integrity=sb.sri(host_bytes), scene_integrity=sb.sri(scene_bytes),
                                     embedder_origin=self.embedder_origin, bootstrap_js=self.bootstrap_js)
        body = page.encode("utf-8")
        headers = sb.page_headers(nonce, self.embedder_origin)
        headers["Content-Length"] = str(len(body))
        return SandboxResponse(200, headers, body)

    def _file(self, target: sb.SandboxTarget, range_header: str | None) -> SandboxResponse:
        assert target.key and target.file
        data = self._read(target.key, target.file)
        headers = sb.file_headers(target.file, len(data))
        if range_header:
            match = _RANGE.fullmatch(range_header.strip())
            if match is None or (match.group(1) == "" and match.group(2) == ""):
                return self._plain(416, "range not satisfiable", {"Content-Range": f"bytes */{len(data)}"})
            start, end = match.groups()
            if start == "":  # suffix: last N bytes
                first, last = max(len(data) - int(end), 0), len(data) - 1
            else:
                first, last = int(start), min(int(end), len(data) - 1) if end else len(data) - 1
            if first > last or first >= len(data):
                return self._plain(416, "range not satisfiable", {"Content-Range": f"bytes */{len(data)}"})
            part = data[first:last + 1]
            headers.update({"Content-Range": f"bytes {first}-{last}/{len(data)}", "Content-Length": str(len(part))})
            return SandboxResponse(206, headers, part)
        return SandboxResponse(200, headers, data)

    # ------------------------------------------------------------------ internes

    def _read(self, key: str, relative: str) -> bytes:
        path = self.resolve_file(key, relative)
        size = path.stat().st_size
        if size > MAX_SERVED_BYTES:
            raise OSError("file too large to serve")
        return path.read_bytes()

    def _plain(self, status: int, text: str, extra: dict[str, str] | None = None) -> SandboxResponse:
        body = text.encode("ascii")
        headers = {**sb.common_headers(), "Content-Type": "text/plain; charset=utf-8", "Content-Length": str(len(body)),
                   "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; sandbox", **(extra or {})}
        return SandboxResponse(status, headers, body)

    def _trace(self, kind: str, message: str, data: dict) -> None:
        if self.trace is not None:
            self.trace(kind, message, data)
