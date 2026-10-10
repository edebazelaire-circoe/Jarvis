"""Routes Presentation Studio du Control Center : relais de Core (handoff jarvis-interactive-presentation-studio, Slice 05).

Core possède les Presentations et l'API d'édition (`jarvis/protocol/presentation_studio_routes.py`,
`PresentationStudioEditService`, seule autorité de validation). Le Control Center n'en garde **rien** :
`/api/presentation-studio/presentations<reste>` est relayé vers `/v1/presentation-studio/presentations<reste>` (même
mécanique que `prefab_relay.py` : paramètres paire par paire, chaque paramètre de route ré-encodé, statut et JSON de
Core rendus tels quels, erreurs et résultats `refused`/`stale` compris ; Core injoignable 503, délai 504). Contrat :
`docs/presentation-studio.md` › *Semantic edit contract*.

| Control Center | Core |
| --- | --- |
| `GET /api/presentation-studio/presentations` | `GET /v1/presentation-studio/presentations` |
| `GET .../presentations/{presentation_id}` | idem |
| `GET .../presentations/{presentation_id}/variants/{variant_id}` | idem |
| `GET .../variants/{variant_id}/scenes/{scene_id}/controls` | idem |
| `GET .../variants/{variant_id}/scenes/{scene_id}/control-suggestions` | idem |
| `POST .../variants/{variant_id}/edits` | idem, **`actor` forcé à `user`** |
| `POST .../variants/{variant_id}/source-edits` | idem (Slice 06, rechargement à chaud), **`actor` forcé à `user`** ; attend le rapport de montage |
| `POST .../presentations/mount-reports` | idem (Slice 06) : ce que l'hôte a observé pour un cadre `presentation-studio.*` |
| `GET .../presentations/{presentation_id}/reloads` | idem (Slice 06) : derniers rechargements, scènes non confirmées |
| `GET .../variants/{variant_id}/history` | idem (Slice 08) |
| `GET .../variants/{variant_id}/art-direction` | idem (Slice 07, **lecture seule** : le chip de l'inspecteur ; création, remplacement, repli et candidates restent hors du relais) |
| `POST .../variants/{variant_id}/undo` et `.../redo` | idem, **`actor` forcé à `user`** (Slice 08) |
| `POST /api/presentation-studio/presentations` | idem (Slice 20, **creation**), **`actor` force a `user`** ; corps `{title, engine?, experimental_confirmed?, reason?}` : la SEULE porte par laquelle un moteur est nomme ; `slidecar` exige `experimental_confirmed: true` |
| `POST .../presentations/{presentation_id}/experiment` | idem (Slice 20) : copie « experience Slidecar » = NOUVEAU document, **`actor` force a `user`** ; corps `{experimental_confirmed, reason?}` |
| `GET /api/presentation-studio/engine` | `GET /v1/presentation-studio/engine` (Slice 20) : moteur par defaut, etat de chaque moteur, registre des usages de Slidecar |
| `GET /api/presentation-studio/playback` | `GET /v1/presentation-studio/playback` : « où en est-on » (Slice 12) |
| `POST /api/presentation-studio/playback/{verb}` | idem, **`actor` forcé à `user`** ; `verb` : `start stop pause resume next previous goto detour return reveal hide edit` (Slice 12) |

**Jamais relayés** à la page : `GET .../playback/armed` (les phrases des cues armées) et `POST .../cues/satisfied` (le suiveur
de cues parle à Core directement, avec le jeton porteur ; la page n'a aucune raison d'en lire le contenu).

**Une seule porte d'écriture** (hors création Slice 20 ci-dessus). Le relais n'expose ni `PUT` de variante, ni validation brute : la page ne peut
modifier une Presentation que par l'API d'édition (niveaux 1 et 2, `/edits`, et son annuler/rétablir, qui en est une édition) ou par
le rechargement à chaud (niveau 3, `/source-edits`), donc avec les mêmes refus, la même base (`basis`) et le même enregistrement
d'annulation que la voix. `mount-reports` n'écrit pas de document : il dit ce que le navigateur a vu. Le corps doit être un objet
JSON ; son `actor` est **remplacé** par `user`,
quoi qu'il dise (même règle que `/api/prefabs/events`) : la page de l'utilisateur ne parle jamais au nom du cerveau.
Le journal (`presentation_studio.request.relayed`) note le statut, le code et le mode, jamais les valeurs ni une intention.

**Garde.** `/api/presentation-studio` est dans `READ_GUARDED_ROUTES` : **toutes** les méthodes exigent un Host de
bouclage, un Origin de bouclage s'il existe et jamais `Sec-Fetch-Site: cross-site` (un cadre de prefab, `Origin: null`,
ne peut rien lire ni écrire ici).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from aiohttp import web

from jarvis.domain.presentation_studio_edit import MAX_EDIT_BODY_BYTES
from jarvis.domain.presentation_studio_playback_requests import Verb
from jarvis.domain.presentation_studio_reload import MAX_SOURCE_BODY_BYTES
from jarvis.protocol.client import PLAYBACK_PREFIX, STUDIO_PREFIX
from jarvis.protocol.strict_json import loads_strict_json, read_bounded
from jarvis.runtime.capture_relay import CaptureRelayRoutes, _code_of, _error
from jarvis.runtime.journal import RuntimeJournal

STUDIO_ROUTE = "/api/presentation-studio/presentations"
CORE_PREFIX = STUDIO_PREFIX
#: Préfixes servis par ce module (gardés en lecture comme en écriture par le Control Center).
GUARDED_PREFIXES = ("/api/presentation-studio",)

#: (méthode, action, chemin relatif sous `STUDIO_ROUTE` et `CORE_PREFIX`).
_READ_ROUTES = (
    ("GET", "studio_list", ""),
    ("GET", "studio_get", "/{presentation_id}"),
    ("GET", "studio_variant", "/{presentation_id}/variants/{variant_id}"),
    ("GET", "studio_controls", "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/controls"),
    ("GET", "studio_suggestions", "/{presentation_id}/variants/{variant_id}/scenes/{scene_id}/control-suggestions"),
    ("GET", "studio_reloads", "/{presentation_id}/reloads"),
    ("GET", "studio_history", "/{presentation_id}/variants/{variant_id}/history"),
    ("GET", "studio_art_direction", "/{presentation_id}/variants/{variant_id}/art-direction"),
)
PLAYBACK_ROUTE = "/api/presentation-studio/playback"
ENGINE_ROUTE = "/api/presentation-studio/engine"
CORE_ENGINE = "/v1/presentation-studio/engine"
EXPERIMENT_PATH = "/{presentation_id}/experiment"
#: Slice 20 : les cles que la page peut envoyer. `actor` est toleree (comme sur les autres routes) mais REMPLACEE par `user`; `engine` seulement a la creation.
CREATE_KEYS = frozenset({"title", "engine", "experimental_confirmed", "reason", "actor"})
EXPERIMENT_KEYS = frozenset({"experimental_confirmed", "reason", "actor"})
EDIT_PATH = "/{presentation_id}/variants/{variant_id}/edits"
SOURCE_EDIT_PATH = "/{presentation_id}/variants/{variant_id}/source-edits"
#: Une édition de source attend la rafale, la publication et le rapport de montage (8 s) : plus que le délai ordinaire.
SOURCE_EDIT_TIMEOUT_S = 45.0
UNDO_PATH = "/{presentation_id}/variants/{variant_id}/undo"
REDO_PATH = "/{presentation_id}/variants/{variant_id}/redo"
#: Les écritures relayées : (chemin relatif, action journalisée, délai). Toutes à acteur forcé `user`.
_WRITE_ROUTES = ((EDIT_PATH, "studio_edit", None), (UNDO_PATH, "studio_undo", None), (REDO_PATH, "studio_redo", None),
                 (SOURCE_EDIT_PATH, "studio_source_edit", SOURCE_EDIT_TIMEOUT_S))


class PresentationStudioRelayRoutes(CaptureRelayRoutes):
    """Relais `/api/presentation-studio/presentations*` -> Core. Voir l'en-tête."""

    JOURNAL_PREFIX = "presentation_studio.request"
    MAX_BODY_BYTES = MAX_SOURCE_BODY_BYTES

    def routes(self) -> list[web.RouteDef]:
        return [*(web.route(method, STUDIO_ROUTE + path, self._relay(action, CORE_PREFIX + path))
                  for method, action, path in _READ_ROUTES),
                *(web.post(STUDIO_ROUTE + path, self._forced(path, action, timeout_s=timeout))
                  for path, action, timeout in _WRITE_ROUTES),
                web.post(STUDIO_ROUTE, self._forced("", "studio_create", allowed=CREATE_KEYS, door_key="engine")),
                web.post(STUDIO_ROUTE + EXPERIMENT_PATH, self._forced(EXPERIMENT_PATH, "studio_experiment", allowed=EXPERIMENT_KEYS, door_key="")),
                web.get(ENGINE_ROUTE, self._relay("studio_engine", CORE_ENGINE)),
                web.post(STUDIO_ROUTE + "/mount-reports", self._relay("studio_mount_report", CORE_PREFIX + "/mount-reports")),
                web.get(PLAYBACK_ROUTE, self._relay("studio_playback", PLAYBACK_PREFIX)),
                *(web.post(f"{PLAYBACK_ROUTE}/{verb.value}", self._forced(f"/{verb.value}", f"studio_playback_{verb.value}",
                                                                           prefix=PLAYBACK_PREFIX))
                  for verb in Verb)]

    def _forced(self, path: str, action: str, *, prefix: str = CORE_PREFIX, timeout_s: float | None = None,
                allowed: frozenset[str] | None = None, door_key: str | None = None):
        async def handler(request: web.Request) -> web.Response:
            return await self._forward_forced(request, path, action, prefix=prefix, timeout_s=timeout_s, allowed=allowed,
                                              door_key=door_key)

        return handler

    async def edit(self, request: web.Request) -> web.Response:
        """`POST .../edits` : corps objet, `actor` remplacé par `user`, relayé à Core ; résultat rendu tel quel."""

        return await self._forward_forced(request, EDIT_PATH, "studio_edit")

    async def _forward_forced(self, request: web.Request, template: str, action: str, *,
                              prefix: str = CORE_PREFIX, timeout_s: float | None = None,
                              allowed: frozenset[str] | None = None, door_key: str | None = None) -> web.Response:
        """Une écriture du Studio (édition, source, annuler, rétablir, lecture) : corps objet, `actor` remplacé par `user`, résultat de Core rendu tel quel."""

        if request.query:
            return _error(400, "invalid_request", "unexpected query parameters")
        try:
            raw = (await read_bounded(request.content, self.MAX_BODY_BYTES) if request.can_read_body else b"") or b""
            body = loads_strict_json(raw, invalid_message="body must be JSON")
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        if not isinstance(body, dict):
            return _error(400, "invalid_request", "body must be a JSON object")
        if allowed is not None:
            # Slice 20 : la page ne parle que de ce que la route prevoit; son `actor`, s'il y en a un, est ecrase juste apres.
            extra = sorted(set(body) - allowed)
            if extra:
                return _error(400, "invalid_request", f"unexpected keys {', '.join(extra[:6])}; allowed {', '.join(sorted(allowed))}")
        # Slice 20 (QA F1) : une route qui NOMME un moteur (creation avec `engine`, copie « experience ») n'est ouverte qu'a la page elle-meme.
        # Un navigateur envoie toujours `Sec-Fetch-Site: same-origin` pour un fetch de la page ; curl, un script ou un outil Bash n'en
        # envoient pas. Barriere d'acces occasionnel, PAS une frontiere : un client qui forge l'en-tete passe (docs/SECURITY.md).
        if door_key is not None and (door_key == "" or door_key in body) and request.headers.get("Sec-Fetch-Site") != "same-origin":
            self._journal.emit(f"{self.JOURNAL_PREFIX}.engine_door_refused", "Choix de moteur refuse : requete qui ne vient pas de la page",
                               level="warning", data={"action": action, "sec_fetch_site": request.headers.get("Sec-Fetch-Site")})
            return _error(403, "presentation_studio_engine_selection_refused",
                          "the engine can only be chosen from the Control Center page itself (same-origin request required)")
        body["actor"] = "user"
        path = prefix + template.format(**{k: quote(v, safe="") for k, v in request.match_info.items()})
        forced = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, payload = await self._forward("POST", path, action=action, params=None, body=forced, timeout_s=timeout_s)
        outcome: dict[str, Any] = payload if isinstance(payload, dict) else {}
        self._journal.emit(f"{self.JOURNAL_PREFIX}.relayed", f"{action} relayé à Core (HTTP {status})",
                           level="info" if status < 400 else "warning",
                           data={"action": action, "status": status, "result": outcome.get("status"),
                                 "mode": outcome.get("mode"), "tier": outcome.get("tier"),
                                 "command": outcome.get("command"), "code": _code_of(payload)})
        if payload is None:
            return _error(status if status >= 400 else 502, "http_error", f"Core answered HTTP {status} without JSON")
        return web.json_response(payload, status=status)

