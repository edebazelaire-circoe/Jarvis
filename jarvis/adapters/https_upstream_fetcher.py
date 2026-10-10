"""Adaptateur réel du port `UpstreamFetcher` : HTTPS vers GitHub, borné (Slice 18, `docs/remotion-import.md` §2).

Garanties, toutes testées : HTTPS seulement (certificat vérifié, contexte par défaut), un hôte de `REDIRECT_HOSTS` seulement et le
chemin du MÊME dépôt à chaque redirection (au plus `MAX_REDIRECTS`), aucune redirection suivie automatiquement, taille bornée
(`MAX_DOWNLOAD_BYTES`, comptée pendant la lecture), délai global borné, pas de proxy ni d'identifiants, corps jamais interprété ici.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from jarvis.domain.remotion_upstream import (
    MAX_DOWNLOAD_BYTES, MAX_REDIRECTS, UpstreamErrorCode as E, UpstreamOrigin, UpstreamRefusal, redirect_refusal,
)
from jarvis.ports.upstream_fetcher import FetchedArchive

DEFAULT_DEADLINE_S = 30.0
SOCKET_TIMEOUT_S = 10.0
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


class HttpsUpstreamFetcher:
    def __init__(self, *, deadline_s: float = DEFAULT_DEADLINE_S, context: ssl.SSLContext | None = None,
                 clock=time.monotonic) -> None:
        self._deadline_s = deadline_s
        self._context = context or ssl.create_default_context()
        self._clock = clock

    def fetch(self, origin: UpstreamOrigin) -> FetchedArchive:
        started = self._clock()
        url = origin.archive_url
        for hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            remaining = self._deadline_s - (self._clock() - started)
            if remaining <= 0:
                raise UpstreamRefusal(E.FETCH_TIMEOUT, f"the download took more than {self._deadline_s:.0f} s")
            connection = http.client.HTTPSConnection(parts.hostname, 443, timeout=min(SOCKET_TIMEOUT_S, remaining), context=self._context)
            try:
                connection.request("GET", parts.path or "/", headers={"User-Agent": "Jarvis-Importer", "Accept-Encoding": "identity",
                                                                      "Accept": "application/gzip, application/octet-stream"})
                response = connection.getresponse()
                if response.status in _REDIRECT_STATUS:
                    location = response.getheader("Location") or ""
                    response.read(0)
                    target = urljoin(url, location)
                    why = redirect_refusal(origin, target) if location else "redirect without a Location header"
                    if why:
                        raise UpstreamRefusal(E.REDIRECT_REFUSED, why)
                    url = target
                    continue
                if response.status == 404:
                    raise UpstreamRefusal(E.FETCH_FAILED, "GitHub does not know this commit in that repository (404)")
                if response.status != 200:
                    raise UpstreamRefusal(E.FETCH_FAILED, f"GitHub answered HTTP {response.status}")
                declared = response.getheader("Content-Length")
                if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                    raise UpstreamRefusal(E.FETCH_TOO_LARGE, f"the archive is {declared} bytes, at most {MAX_DOWNLOAD_BYTES}")
                body = bytearray()
                read = getattr(response, "read1", response.read)  # une lecture partielle : le délai se vérifie à chaque morceau
                while True:
                    left = self._deadline_s - (self._clock() - started)
                    if left <= 0:
                        raise UpstreamRefusal(E.FETCH_TIMEOUT, f"the download took more than {self._deadline_s:.0f} s")
                    sock = getattr(connection, "sock", None)
                    if sock is not None:  # le délai d'UNE lecture suit le temps qu'il reste, jamais plus de SOCKET_TIMEOUT_S
                        sock.settimeout(min(SOCKET_TIMEOUT_S, left))
                    chunk = read(64 * 1024)
                    if not chunk:
                        break
                    body += chunk
                    if len(body) > MAX_DOWNLOAD_BYTES:
                        raise UpstreamRefusal(E.FETCH_TOO_LARGE, f"the archive is larger than {MAX_DOWNLOAD_BYTES} bytes")
                return FetchedArchive(bytes(body), url, hop)
            except UpstreamRefusal:
                raise
            except (socket.timeout, TimeoutError):
                raise UpstreamRefusal(E.FETCH_TIMEOUT, "the connection timed out") from None
            except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
                raise UpstreamRefusal(E.FETCH_FAILED, f"the download failed ({type(exc).__name__})") from None
            finally:
                connection.close()
        raise UpstreamRefusal(E.REDIRECT_REFUSED, f"more than {MAX_REDIRECTS} redirects")
