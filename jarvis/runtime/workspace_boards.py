"""Transport et outils Board/Session du serveur MCP `jarvis-workspace` (handoff board-session, Slice 05 ;
déplacés de `jarvis-console` par la Slice 06 de board-memory-workspace-inspector).

Le cerveau fait ce que l'interface fait sur les Boards et les Sessions, **par
les mêmes routes** : `/api/boards*` et `/api/sessions*` du Control Center
(`jarvis/runtime/board_routes.py`), relais de Core, et `/api/workspace/*`
(`jarvis/runtime/workspace_relay.py`) pour la mémoire, l'historique et les
liens (outils dans `workspace_mcp.py`, même transport `BoardTools.call`).
Jamais Core directement : le Control Center est l'unique entrée UI/MCP
(`docs/boards.md` › *Ownership*), et c'est lui qui diffère une demande du
cerveau pendant son propre tour.

- Un **Board** est un espace de travail durable (titre, nature, résumé de
  contexte, références). Basculer déplace la conversation et la voix sur ce
  Board ; le Board quitté garde son travail de fond.
- Une **Session** est un épisode de conversation. `session_new` ouvre un fil
  neuf sur le **même** Board, sans toucher ni aux Boards ni aux tâches.

**Demandes du cerveau.** `board_switch` et `session_new` envoient
`origin: "brain"`. Pendant un tour de l'agent (le cas normal : l'outil est
appelé *pendant* le tour), le Control Center répond 202 `scheduled` et
applique la demande dès la fin du tour ; hors tour, il l'applique tout de
suite. L'outil rend l'un ou l'autre tel quel : `status` `scheduled` ou
`applied`, jamais un « fait » qui ne l'est pas encore. Deux demandes du même
tour : une seconde nouvelle Session est **fusionnée** avec la première
(`merged: true`, une seule s'ouvre) ; une seconde bascule **remplace** la
première (`replaced_board_id`), la dernière gagne (`board_routes.py`).

**Réponses pour la voix** (reprise QA Slice 05, B2) : `note` est une seule
phrase courte, sans vocabulaire interne, que le cerveau peut dire telle quelle
(« Nouvelle session à la fin de ta réponse. »). Les faits (la voix suit, le
travail de fond continue, rien n'est annulé) sont dans les descriptions des
outils, pas dans la note.

Aucun outil bas niveau (voix, autorité de parole, liaison de cerveau) : la
bascule est une transaction de Core qui garde seule ses invariants.

Refus : l'enveloppe `{"error": {code, message}}` du relais (ou `{ok: false,
code, error}` de la garde d'origine du Control Center) devient une erreur
d'outil (`WorkspaceToolError`) qui porte le code stable (`board_not_found`,
`board_archived`, `memory_conflict`, …), une phrase qui dit quoi faire, et le
message tel quel, attribué à qui l'a écrit : `Core` pour un code de Core,
`Control Center` pour un refus du relais lui-même (`RELAY_CODES`) ou un corps
qui n'est pas l'enveloppe JSON.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote

import aiohttp

from jarvis.runtime.core_sessions import CORE_TRANSITION_TIMEOUT_S

BOARDS_ROUTE = "/api/boards"
ACTIVE_BOARD_ROUTE = "/api/boards/active"
PENDING_ROUTE = "/api/boards/pending"
SWITCH_ROUTE = "/api/boards/switch"
CURRENT_SESSION_ROUTE = "/api/sessions/current"
NEW_SESSION_ROUTE = "/api/sessions/new"
#: Origine des demandes de ces outils (`board_routes.ORIGINS`).
BRAIN_ORIGIN = "brain"

#: Champs qu'un outil écrit sur un Board : ceux de l'écran, nature comprise (Slice 06). `scene_ref` et
#: `runtime_metadata` sont éditables par Core mais appartiennent au runtime.
BOARD_EDIT_FIELDS = ("title", "board_kind", "context_summary", "task_refs", "artifact_refs", "project_refs")

READ_TIMEOUT_S = 15.0
#: Une bascule ou une nouvelle Session immédiate (hors tour) attend le relais,
#: qui attend Core jusqu'à `CORE_TRANSITION_TIMEOUT_S` (150 s : activation du
#: CLI par l'hôte, 60 s, puis sa restauration éventuelle). L'outil attend plus
#: longtemps que le relais : sa réponse (même un 504 « issue inconnue ») arrive
#: toujours avant cette échéance (QA 06/07, point 3 ; c'était 45 s).
TRANSITION_TIMEOUT_S = CORE_TRANSITION_TIMEOUT_S + 20.0
#: Réponse du relais quand Core n'a pas répondu à temps à une transition.
UNKNOWN_CODE = "core_transition_timeout"
#: La note d'une issue inconnue : une phrase courte, vraie, à dire telle quelle.
UNKNOWN_NOTE = "Je vérifie si c'est fait."

CONNECT_TIMEOUT_S = 3.0

#: Ce que chaque code stable veut dire pour le cerveau, et quoi faire ensuite.
#: Le message de Core suit toujours : c'est la cause réelle.
ERROR_SENTENCES: dict[str, str] = {
    "board_not_found": "Ce Board n'existe pas. Appelle board_list pour les identifiants.",
    "board_archived": "Ce Board est archivé : il ne s'ouvre plus et ne se modifie plus.",
    "board_is_active": "C'est le Board actif : il ne s'archive pas. Bascule d'abord sur un autre Board.",
    "session_closed": "Cette Session est déjà close (une autre a été ouverte entre-temps). Relis session_current.",
    "session_not_found": "Aucune Session ouverte : Core n'a pas fini de démarrer. Réessaie dans un instant.",
    "binding_not_found": ("La conversation du Board actif est introuvable chez Core : rien n'a été fait. "
                          "Propose une nouvelle session (session_new) ; si l'erreur revient, dis-le à "
                          "l'utilisateur."),
    "binding_conflict": ("Conflit de liaison entre la Session et le Board : rien n'a été écrit. Relis "
                         "session_current puis réessaie une fois ; si ça recommence, dis-le à l'utilisateur."),
    "brain_not_foreground": "Ce cerveau n'a plus la parole : un autre Board est au premier plan.",
    "board_activation_failed": ("Le cerveau du Board cible n'a pas pu démarrer : rien n'a changé, "
                                "le Board actuel reste actif."),
    "board_switch_rolled_back": ("La bascule a échoué après l'activation et a été annulée : "
                                 "le Board précédent reste actif, rien n'a été écrit."),
    "invalid_title": "Titre refusé (1 à 120 caractères, une ligne, sans espace autour) : rien n'a été écrit.",
    "context_summary_too_long": "Résumé trop long (1 500 caractères au plus) : condense-le, rien n'a été écrit.",
    "invalid_board": "Argument refusé par Core : rien n'a été écrit.",
    "invalid_session": "Demande de Session refusée par Core : rien n'a été fait.",
    "invalid_binding": "Liaison refusée par Core : rien n'a été fait.",
    "invalid_request": "Requête refusée : rien n'a été fait.",
    "core_unreachable": "Core est injoignable : rien n'a été lu ni écrit.",
    "core_unconfigured": "Le Control Center ne connaît pas Core : rien n'a été lu ni écrit.",
    "core_unavailable": "Core n'est pas prêt : rien n'a été lu ni écrit. Réessaie dans un instant.",
    "core_transition_timeout": ("Core n'a pas répondu à temps : l'issue est inconnue. Relis session_current "
                                "avant de réessayer."),
    # Mémoire, historique et liens (`/api/workspace/*`, Slice 06 board-memory-workspace-inspector).
    "core_timeout": "Core n'a pas répondu à temps : l'issue est inconnue. Relis (arbre, fichier) avant de réessayer.",
    "forbidden_origin": "Le Control Center refuse cette origine : rien n'a été lu ni écrit.",
    "artifact_not_found": "Cet Artifact n'existe pas : cherche-le avec artifact_search.",
    "invalid_artifact": "Identifiant d'Artifact refusé : rien n'a été fait.",
    "context_not_found": "Ce Context n'existe pas.",
    "memory_path_invalid": "Chemin refusé (relatif à memory/, segments simples, 240 caractères au plus).",
    "memory_path_escape": "Chemin hors de la mémoire du Board (absolu, lecteur ou ..) : refusé.",
    "memory_not_found": "Rien à ce chemin dans la mémoire de ce Board : relis board_memory_tree.",
    "memory_exists": "Un fichier existe déjà à ce chemin : rien n'a été écrit (mode replace ou append pour le changer).",
    "memory_conflict": ("Conflit : le fichier a changé depuis ta lecture (expected_sha256), ou dossier/fichier "
                        "inattendu, ou dossier non vide sans recursive. Relis puis réessaie."),
    "memory_too_large": "Trop gros (256 Kio par appel) : découpe.",
    "memory_not_text": "Fichier binaire ou non UTF-8 : il ne se lit ni ne s'écrit en texte.",
    "board_memory_unsafe": "Mémoire du Board refusée (lien, jonction ou dossier remplacé) : rien n'a été fait.",
    "board_memory_failed": "Le disque de la mémoire du Board est en défaut.",
    "workspace_ledger_failed": ("Le changement A ÉTÉ appliqué, mais sa ligne d'activité n'a pas pu être écrite : "
                                "ne le refais pas."),
    "workspace_failed": "Erreur interne du workspace de Core.",
}

#: Codes que le relais du Control Center écrit lui-même (`board_routes.py`) : pas des refus de Core.
RELAY_CODES = frozenset({"invalid_request", "core_unreachable", "core_unconfigured", "core_transition_timeout",
                         "core_timeout", "forbidden_origin", "http_error"})


class BoardTools:
    """La logique des outils Board/Session et le transport du serveur, sans FastMCP : testable contre un Control
    Center réel ou factice.

    `http` rend la session aiohttp partagée du serveur (`WorkspaceTools._http`) ;
    `error` fabrique l'erreur d'outil du serveur (`WorkspaceToolError`) ;
    `emit` écrit dans le journal du serveur.
    """

    def __init__(
        self,
        base_url: str,
        *,
        http: Callable[[], Awaitable[Any]],
        error: Callable[[str, str], Exception],
        emit: Callable[..., None],
    ) -> None:
        self._base_url = base_url
        self._http = http
        self._error = error
        self._emit = emit

    # ------------------------------------------------------------------ transport

    async def call(self, tool: str, method: str, route: str, *, payload: Any = None,
                    params: Mapping[str, str] | None = None, timeout_s: float = READ_TIMEOUT_S,
                    unknown_ok: bool = False) -> tuple[int, Any]:
        """Un aller-retour vers le Control Center ; tout refus devient une erreur d'outil codée et journalisée.

        `unknown_ok` (transitions seulement) : un 504 `core_transition_timeout` n'est pas un refus mais une
        issue **inconnue** ; il est rendu tel quel, l'outil le dit sans prétendre à un échec.
        """

        session = await self._http()
        timeout = aiohttp.ClientTimeout(total=timeout_s, connect=CONNECT_TIMEOUT_S)
        try:
            async with session.request(method, self._base_url + route, json=payload, params=params,
                                       timeout=timeout) as response:
                status = response.status
                text = await response.text()
        except aiohttp.ClientError as exc:
            self._failed(tool, "control_center_unreachable", route, exception_type=type(exc).__name__)
            raise self._error(
                "control_center_unreachable",
                f"Le Control Center est injoignable ({type(exc).__name__}) : rien n'a été lu ni écrit. "
                "Dis à l'utilisateur que l'interface de JARVIS doit tourner.",
            ) from None
        except TimeoutError:
            self._failed(tool, "control_center_timeout", route)
            raise self._error(
                "control_center_timeout",
                f"Le Control Center n'a pas répondu en {timeout_s:g} s : l'issue est inconnue. "
                "Relis l'état (board_get_active, session_current) avant de réessayer.",
            ) from None
        try:
            body = json.loads(text) if text.strip() else None
        except ValueError:
            body = None
        if status >= 400:
            error = body.get("error") if isinstance(body, dict) else None
            error = error if isinstance(error, dict) else {}
            if not error and isinstance(body, dict) and body.get("ok") is False and isinstance(body.get("code"), str):
                # Refus de la garde d'origine du Control Center (`{"ok": false, "code", "error"}`) : son code.
                error = {"code": body["code"], "message": body.get("error")}
            code = str(error.get("code") or f"http_{status}")
            detail = str(error.get("message") or text.strip()[:300] or f"HTTP {status}")[:400]
            # Qui a écrit ce refus : Core (code de Core relayé), ou le Control Center (refus du relais,
            # ou corps sans enveloppe : page d'erreur aiohttp, route absente...).
            source = "Core" if error.get("code") and code not in RELAY_CODES else "Control Center"
            if unknown_ok and status == 504 and code == UNKNOWN_CODE:
                self._emit("board.tool_unknown", f"{tool} : issue inconnue (Core n'a pas répondu à temps)",
                           level="warning", data={"tool": tool, "code": code, "route": route, "status": status})
                return status, {"unknown": True, "detail": detail}
            self._failed(tool, code, route, status=status, source=source)
            raise self._error(code, _refusal(code, detail, source))
        if not isinstance(body, dict):
            self._failed(tool, "control_center_bad_response", route, status=status)
            raise self._error("control_center_bad_response",
                              f"Réponse illisible du Control Center sur {route} (HTTP {status}).")
        return status, body

    def _failed(self, tool: str, code: str, route: str, **data: Any) -> None:
        self._emit("board.tool_failed", f"{tool} : {code}", level="warning",
                   data={"tool": tool, "code": code, "route": route, **data})

    def _done(self, tool: str, message: str, **data: Any) -> None:
        self._emit("board.tool", f"{tool} : {message}", data={"tool": tool, **data})

    def _bad_shape(self, tool: str, route: str) -> Exception:
        self._failed(tool, "control_center_bad_response", route)
        return self._error("control_center_bad_response", f"Réponse inattendue du Control Center sur {route}.")

    # ------------------------------------------------------------------ Boards

    async def list_boards(self, include_archived: bool = False) -> dict[str, Any]:
        params = {"include_archived": "true"} if include_archived else None
        _, body = await self.call("board_list", "GET", BOARDS_ROUTE, params=params)
        boards, active = body.get("boards"), body.get("active_board_id")
        if not isinstance(boards, list) or not all(isinstance(board, dict) for board in boards):
            raise self._bad_shape("board_list", BOARDS_ROUTE)
        self._done("board_list", f"{len(boards)} Board(s)", count=len(boards), include_archived=include_archived)
        return {"active_board_id": active, "boards": [_summary(board, board.get("board_id") == active)
                                                      for board in boards]}

    async def get_board(self, board_id: str) -> dict[str, Any]:
        return await self._board("board_get", "GET", _board_route(board_id), board_id=board_id)

    async def get_active(self) -> dict[str, Any]:
        return await self._board("board_get_active", "GET", ACTIVE_BOARD_ROUTE)

    async def create_board(self, title: str, **fields: Any) -> dict[str, Any]:
        payload = {"title": title, **{name: value for name, value in fields.items() if value is not None}}
        return await self._board("board_create", "POST", BOARDS_ROUTE, payload=payload)

    async def update_board(self, board_id: str, **fields: Any) -> dict[str, Any]:
        payload = {name: value for name, value in fields.items() if value is not None}
        if not payload:
            self._failed("board_update", "invalid_board", _board_route(board_id), reason="no_field")
            raise self._error("invalid_board", "Rien à modifier : donne au moins un champ (title, board_kind, "
                                               "context_summary, task_refs, artifact_refs, project_refs). "
                                               "Rien n'a été écrit.")
        return await self._board("board_update", "PATCH", _board_route(board_id), payload=payload,
                                 board_id=board_id)

    async def archive_board(self, board_id: str) -> dict[str, Any]:
        return await self._board("board_archive", "POST", _board_route(board_id) + "/archive", payload={},
                                 board_id=board_id)

    async def _board(self, tool: str, method: str, route: str, *, payload: Any = None,
                     board_id: str | None = None) -> dict[str, Any]:
        _, body = await self.call(tool, method, route, payload=payload)
        board = body.get("board")
        if not isinstance(board, dict):
            raise self._bad_shape(tool, route)
        self._done(tool, str(board.get("board_id")), board_id=board.get("board_id"),
                   fields=sorted(payload) if isinstance(payload, dict) else None)
        return _detail(board, bool(body.get("active")))

    async def switch_board(self, board_id: str) -> dict[str, Any]:
        """Basculer sur `board_id`. Vérifié d'abord (existe, pas archivé, pas déjà actif), puis demandé avec
        `origin: brain` : une demande différée ne rend son refus qu'au journal, donc on le rend ici avant."""

        _, body = await self.call("board_switch", "GET", _board_route(board_id))
        board = body.get("board")
        if not isinstance(board, dict):
            raise self._bad_shape("board_switch", _board_route(board_id))
        title = str(board.get("title") or board_id)
        if board.get("status") == "archived":
            self._failed("board_switch", "board_archived", _board_route(board_id), board_id=board_id)
            raise self._error("board_archived", _refusal("board_archived", f"board {board_id} is archived", "Core"))
        active = body.get("active") is True
        if active and not await self._switch_pending_elsewhere(board_id):
            self._done("board_switch", "déjà actif", board_id=board_id, status="unchanged")
            return {"status": "unchanged", "board_id": board_id, "title": title,
                    "note": f"Déjà sur « {title} »."}
        # Actif mais une bascule vers un autre Board attend la fin du tour : celle-ci la remplace
        # (la dernière gagne, `board_routes.py`), donc on reste ici — ce n'est pas `unchanged`.
        status, answer = await self.call("board_switch", "POST", SWITCH_ROUTE,
                                          payload={"board_id": board_id, "origin": BRAIN_ORIGIN},
                                          timeout_s=TRANSITION_TIMEOUT_S, unknown_ok=True)
        if status == 504:
            return {"status": "unknown", "board_id": board_id, "title": title, "note": UNKNOWN_NOTE}
        if status == 202:
            replaced = answer.get("replaced_board_id")
            self._done("board_switch", "programmée", board_id=board_id, status="scheduled",
                       merged=bool(answer.get("merged")), replaced_board_id=replaced)
            note = f"Tu restes sur « {title} »." if active else f"Passage sur « {title} » à la fin de ta réponse."
            return {"status": "scheduled", "board_id": board_id, "title": title,
                    "replaced_board_id": replaced if isinstance(replaced, str) else None, "note": note}
        if answer.get("changed") is False:
            self._done("board_switch", "déjà actif", board_id=board_id, status="unchanged")
            return {"status": "unchanged", "board_id": board_id, "title": title, "note": f"Déjà sur « {title} »."}
        self._done("board_switch", "appliquée", board_id=board_id, status="applied",
                   changed=answer.get("changed"))
        return {"status": "applied", "board_id": board_id, "title": title,
                "previous_board_id": answer.get("previous_board_id"), "note": f"Tu es sur « {title} »."}

    async def _switch_pending_elsewhere(self, board_id: str) -> bool:
        """Une bascule du cerveau vers un **autre** Board attend-elle la fin du tour ? (reprise QA Slice 05, B3)"""

        _, body = await self.call("board_switch", "GET", PENDING_ROUTE)
        pending = body.get("pending")
        if not isinstance(pending, list):
            raise self._bad_shape("board_switch", PENDING_ROUTE)
        return any(isinstance(item, dict) and item.get("action") == "switch" and item.get("board_id") != board_id
                   for item in pending)

    # ------------------------------------------------------------------ Sessions

    async def current_session(self) -> dict[str, Any]:
        session, binding = await self._current("session_current")
        self._done("session_current", str(session.get("jarvis_session_id")),
                   jarvis_session_id=session.get("jarvis_session_id"))
        return {"jarvis_session_id": session.get("jarvis_session_id"), "started_at": session.get("started_at"),
                "active_board_id": session.get("active_board_id"),
                "visited_board_ids": list(session.get("visited_board_ids") or []),
                "conversation_id": binding.get("conversation_id")}

    async def new_session(self) -> dict[str, Any]:
        """Nouvelle Session sur le même Board. `expected_session_id` = la Session lue juste avant.

        Un second appel dans le même tour est **fusionné** par le Control Center avec la demande en
        attente (`merged: true`, `scheduled`) : une seule Session s'ouvre. Hors tour, le premier appel
        s'applique aussitôt ; un second qui viserait la Session déjà close serait refusé par Core
        (`session_closed`), jamais une seconde Session."""

        session, _ = await self._current("session_new")
        expected = session.get("jarvis_session_id")
        board_id = session.get("active_board_id")
        status, answer = await self.call("session_new", "POST", NEW_SESSION_ROUTE,
                                          payload={"origin": BRAIN_ORIGIN, "expected_session_id": expected},
                                          timeout_s=TRANSITION_TIMEOUT_S, unknown_ok=True)
        if status == 504:
            return {"status": "unknown", "closed_session_id": expected, "board_id": board_id,
                    "note": UNKNOWN_NOTE}
        if status == 202:
            merged = bool(answer.get("merged"))
            self._done("session_new", "programmée", status="scheduled", closed_session_id=expected, merged=merged)
            return {"status": "scheduled", "closed_session_id": expected, "board_id": board_id, "merged": merged,
                    "note": "Nouvelle session à la fin de ta réponse."}
        opened = answer.get("session")
        if not isinstance(opened, dict):
            raise self._bad_shape("session_new", NEW_SESSION_ROUTE)
        self._done("session_new", "ouverte", status="applied", closed_session_id=expected,
                   jarvis_session_id=opened.get("jarvis_session_id"))
        return {"status": "applied", "closed_session_id": expected, "board_id": opened.get("active_board_id"),
                "jarvis_session_id": opened.get("jarvis_session_id"), "note": "Nouvelle session ouverte."}

    async def _current(self, tool: str) -> tuple[dict[str, Any], dict[str, Any]]:
        _, body = await self.call(tool, "GET", CURRENT_SESSION_ROUTE)
        session, binding = body.get("session"), body.get("binding")
        if not isinstance(session, dict) or not isinstance(binding, dict):
            raise self._bad_shape(tool, CURRENT_SESSION_ROUTE)
        return session, binding


def _board_route(board_id: str) -> str:
    return f"{BOARDS_ROUTE}/{quote(board_id, safe='')}"


def _refusal(code: str, detail: str, source: str) -> str:
    """Phrase d'erreur d'outil : le code, quoi faire, puis la cause réelle attribuée à qui l'a écrite."""

    sentence = ERROR_SENTENCES.get(code, "Refusé.")
    return f"Refus {code} : {sentence} ({source} : {detail})"


def _summary(board: Mapping[str, Any], active: bool) -> dict[str, Any]:
    """Ligne de `board_list` : de quoi reconnaître un Board, sans son contenu (board_get le rend)."""

    return {"board_id": board.get("board_id"), "title": board.get("title"),
            "board_kind": board.get("board_kind") or "empty", "status": board.get("status"), "active": active,
            "interaction_mode": board.get("interaction_mode"), "last_opened_at": board.get("last_opened_at")}


def _detail(board: Mapping[str, Any], active: bool) -> dict[str, Any]:
    """Un Board tel que le cerveau le lit : l'écran, sans `scene_ref` ni `runtime_metadata` (runtime)."""

    return {**_summary(board, active), "context_summary": board.get("context_summary") or "",
            "task_refs": list(board.get("task_refs") or []), "artifact_refs": list(board.get("artifact_refs") or []),
            "project_refs": list(board.get("project_refs") or []), "updated_at": board.get("updated_at")}
