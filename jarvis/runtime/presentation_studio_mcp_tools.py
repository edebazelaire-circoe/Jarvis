"""La logique des outils « jarvis-presentation » (jarvis-interactive-presentation-studio, Slice 21), sans FastMCP.

**Une façade, jamais un propriétaire.** Chaque opération appelle la route de Core qui la possède (`/v1/presentation-studio/*`, par le
client typé `LocalCoreClient`) ou, pour l'explorateur et le plein écran qui vivent dans la page, le canal de commandes du Control
Center. Rien n'est stocké ici, sauf le registre de jetons de confirmation d'un processus. Pas de routeur en langage naturel : un outil
par domaine, une opération fermée (`op`), des ids lus dans l'état.

Règles qui tiennent ce module (chacune a un test) :

1. **L'acteur est `brain`, posé ici**, jamais lu des arguments. **L'origine d'un démarrage n'est jamais un argument** (Slice 14, condition d'entrée
   de la Slice 21) : elle vient du tour réel. Le Control Center, qui sert chaque tour du cerveau, atteste qu'un tour adressé de l'utilisateur est
   en vol (`presentation_studio_turn.py`) ; alors seulement ce serveur joint `origin: explicit_user_request`. Sans attestation il n'envoie rien,
   Core applique son défaut `brain_spontaneous` et refuse le démarrage (`mode_switch_refused`) : l'utilisateur le lance lui-même (bouton du lecteur).
2. **Le modèle n'invente aucun id.** Un id mal formé ou inconnu est refusé avec les ids valides lus dans l'état ; l'id par défaut (présentation,
   variante) vient de l'état (lecture en cours, explorateur ouvert, présentation unique, variante active), jamais d'une supposition.
3. **Le destructif passe par la confirmation canonique.** Archiver une branche : `archive_plan` (ensemble exact + jeton de Core) puis `archive`
   avec ce jeton. Retirer une scène et annuler la modification de l'utilisateur : jeton de ce processus, lié à la révision et aux ids exacts.
   Annuler envoie toujours `expected_entry_id` lu dans l'historique.
4. **Silencieux par défaut.** Un geste visuel réussi rend `speech: "silent"` (ligne `COMMAND_CONFIRMATION` de la matrice PRESENTATION) ; seuls un
   refus, une question de confirmation, un geste attendu de l'utilisateur ou un fait nouveau (numéro de variante créée) portent `speech: "say"`.
5. **Les textes d'auteur sont des données.** Titres, étiquettes, raisons : une ligne, bornés, listés dans `untrusted` ; la partition est lue
   sans ses `text` ni `note`.
6. **Corrélation.** Chaque appel écrit une ligne `presentation_studio.tool` (outil, op, ids, issue, durée, `correlation_id`, événement
   canonique attendu `system.presentation_studio.*`) ; le résultat rend la révision pour retrouver l'événement de Core.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Mapping, Sequence

import aiohttp

from jarvis.domain.presentation_studio import is_presentation_id
from jarvis.domain.presentation_studio_authoring_guide import draft_guide
from jarvis.domain.presentation_studio_checks import is_scene_id
from jarvis.domain.presentation_studio_scene_variants import is_scene_variant_id
from jarvis.domain.presentation_studio_template import is_template_id
from jarvis.domain.presentation_studio_variants import is_variant_id
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.presentation_studio_mcp_support import (
    BRAIN_ACTOR, CONNECT_TIMEOUT_S, MAX_LISTED, READ_TIMEOUT_S, WRITE_TIMEOUT_S, ConfirmationLedger, PresentationToolError, capped, clip,
    sentence_for,
)

ITEM_ID = re.compile(r"psi_[0-9a-f]{12}\Z")
ANCHOR_ID = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
CONTROL_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")

#: Opération -> événement canonique que Core pose à la suite (corrélation, `docs/conversation-events.md`). `None` : aucun événement.
EVENT_EDIT = "system.presentation_studio.edit_committed"
EVENT_VARIANT = "system.presentation_studio.variant_changed"
EVENT_PLAYBACK = "system.presentation_studio.playback_changed"
OPERATION_EVENTS: dict[str, str | None] = {
    "presentation_edit": EVENT_EDIT, "presentation_undo": EVENT_EDIT,
    "presentation_variant.create": EVENT_VARIANT, "presentation_variant.activate": EVENT_VARIANT,
    "presentation_variant.rename": EVENT_VARIANT, "presentation_variant.archive": EVENT_VARIANT,
    "presentation_variant.restore": EVENT_VARIANT, "presentation_variant.scene_promote": EVENT_VARIANT,
    "presentation_compose.create": EVENT_VARIANT, "presentation_draft_assemble": EVENT_VARIANT,
    "presentation_draft_finalize": EVENT_VARIANT, "presentation_play": EVENT_PLAYBACK,
}

PLAY_NAVIGATION = frozenset({"pause", "resume", "next", "previous", "goto", "reveal", "hide", "return", "stop"})
#: Ordres de scène qui s'écrivent par `presentation_edit` (le vocabulaire fermé de Slice 05 et 17, sans les formes d'annulation).
EDIT_OPS = ("control.set", "control.reset", "scene.remove", "scene.reorder", "scene.rename", "scene.source_request",
            "scene_variant.create", "scene_variant.rename", "scene_variant.select", "scene_variant.delete")
#: Ordre -> champs permis (clés exactes de Core). Tout autre champ donné est refusé, jamais ignoré en silence.
EDIT_FIELDS: dict[str, frozenset[str]] = {
    "control.set": frozenset({"scene_id", "control_id", "value", "if_current"}),
    "control.reset": frozenset({"scene_id", "control_id", "if_current"}),
    "scene.remove": frozenset({"scene_id"}),
    "scene.reorder": frozenset({"scene_id", "to_index"}),
    "scene.rename": frozenset({"scene_id", "title"}),
    "scene.source_request": frozenset({"scene_id", "intent"}),
    "scene_variant.create": frozenset({"scene_id", "label", "rationale", "from_variant"}),
    "scene_variant.rename": frozenset({"scene_id", "scene_variant_id", "label"}),
    "scene_variant.select": frozenset({"scene_id", "scene_variant_id", "drop_others"}),
    "scene_variant.delete": frozenset({"scene_id", "scene_variant_id"}),
}
EDIT_REQUIRED: dict[str, frozenset[str]] = {
    "control.set": frozenset({"scene_id", "control_id", "value"}), "control.reset": frozenset({"scene_id", "control_id"}),
    "scene.remove": frozenset({"scene_id"}), "scene.reorder": frozenset({"scene_id", "to_index"}),
    "scene.rename": frozenset({"scene_id", "title"}), "scene.source_request": frozenset({"scene_id", "intent"}),
    "scene_variant.create": frozenset({"scene_id", "label"}), "scene_variant.rename": frozenset({"scene_id", "scene_variant_id", "label"}),
    "scene_variant.select": frozenset({"scene_id", "scene_variant_id"}), "scene_variant.delete": frozenset({"scene_id", "scene_variant_id"}),
}
UNKNOWN_ID_CODES = frozenset({
    "presentation_studio_unknown_presentation", "presentation_studio_unknown_variant", "presentation_studio_unknown_scene",
    "presentation_studio_unknown_control", "presentation_studio_unknown_scene_variant", "presentation_studio_unknown_template"})


class CoreCaller:
    """Production : `LocalCoreClient` avec jeton relu (un 401 rejoue une fois). `call(fn)` rend `await fn(client)`."""

    def __init__(self, target: Any) -> None:
        from jarvis.runtime.core_forwarder import CoreLoopbackTransport

        self._transport = CoreLoopbackTransport(host=target.core_host, port=target.core_port, token_file=target.token_file)

    async def call(self, fn: Callable[[LocalCoreClient], Awaitable[Any]]) -> Any:
        try:
            return await self._transport.replay_on_401(fn)
        except ConnectionError as exc:
            raise CoreProtocolError(503, "core_unreachable", str(exc)) from None
        except TimeoutError:
            # Remotion Slice 21 (QA B2): `asyncio.TimeoutError` is `TimeoutError`; aiohttp's total timeout too. The outcome of a write is UNKNOWN
            # (a render may be queued): a coded error, never an empty one, and the model is told to read the state before trying again.
            raise CoreProtocolError(504, "core_timeout", "Core did not answer in time; the outcome is unknown") from None
        except aiohttp.ClientError as exc:
            raise CoreProtocolError(503, "core_unreachable", f"Core est injoignable ({type(exc).__name__})") from None

    async def close(self) -> None:
        await self._transport.close()


class ControlCenterCaller:
    """Le Control Center local : `request(method, route, payload) -> (status, body)`. Sert l'explorateur et le plein écran."""

    def __init__(self, target: Any, *, session_factory: Callable[[], Any] | None = None) -> None:
        self.base_url = target.base_url
        self._factory = session_factory or aiohttp.ClientSession
        self._session: Any = None

    async def request(self, method: str, route: str, payload: Any = None, *, timeout_s: float = WRITE_TIMEOUT_S) -> tuple[int, Any]:
        if self._session is None or self._session.closed:
            self._session = self._factory()
        timeout = aiohttp.ClientTimeout(total=timeout_s, connect=CONNECT_TIMEOUT_S)
        try:
            async with self._session.request(method, self.base_url + route, json=payload, timeout=timeout) as response:
                text = await response.text()
                status = response.status
        except aiohttp.ClientError as exc:
            raise PresentationToolError("control_center_unreachable", f"Refus control_center_unreachable : "
                                        f"{sentence_for('control_center_unreachable')} ({type(exc).__name__})") from None
        except TimeoutError:
            raise PresentationToolError("control_center_timeout", "Le Control Center n'a pas répondu à temps : l'issue est inconnue, "
                                        "relis presentation_inspect target explorer avant de réessayer.") from None
        try:
            body = json.loads(text) if text.strip() else None
        except ValueError:
            body = None
        return status, body

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


def _drop_none(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


class PresentationTools:
    """Les douze outils, testables contre un vrai Core (`core.call(fn)`) et un Control Center réel ou factice."""

    def __init__(self, core: Any, control_center: Any = None, *, journal: RuntimeJournal | None = None,
                 ledger: ConfirmationLedger | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._core = core
        self._cc = control_center
        self.journal = journal
        self.ledger = ledger or ConfirmationLedger()
        self._clock = clock
        #: Le plan d'archivage lu dans ce processus : `(presentation_id, variant_id) -> jeton de Core` (Core reste juge du jeton).
        self._archive_plans: dict[tuple[str, str], str] = {}

    async def close(self) -> None:
        for part in (self._core, self._cc):
            closer = getattr(part, "close", None)
            if closer is not None:
                await closer()

    # ------------------------------------------------------------------ socle : appels, erreurs, journal

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, level=level, data=data or {})
        except Exception:  # noqa: BLE001 - intentional: an unwritable journal never fails a tool call
            pass

    async def _c(self, fn: Callable[[LocalCoreClient], Awaitable[Any]]) -> Any:
        """Un appel Core ; un refus devient une erreur d'outil codée, avec les ids valides si l'id était inconnu."""

        try:
            return await self._core.call(fn)
        except CoreProtocolError as exc:
            raise await self._explain(exc) from None

    async def _explain(self, exc: CoreProtocolError) -> PresentationToolError:
        code = exc.code or f"http_{exc.status}"
        detail = clip(exc.message, 300)
        extra = ""
        conflicts = exc.details.get("conflicts") if isinstance(exc.details, Mapping) else None
        if isinstance(conflicts, list):
            extra = " conflicts=" + json.dumps(conflicts[:12], ensure_ascii=False, separators=(",", ":"))[:3000]
        choices = None
        if code in UNKNOWN_ID_CODES:
            choices = await self._choices_after_unknown()
        message = f"Refus {code} : {sentence_for(code, detail)} (Core : {detail}){extra}"
        if choices:
            message += " Ids valides : " + json.dumps(choices, ensure_ascii=False, separators=(",", ":"))[:1500]
        return PresentationToolError(code, message, choices=choices)

    async def _choices_after_unknown(self) -> dict[str, Any] | None:
        """Les présentations et variantes vivantes, pour corriger un id inconnu (meilleur effort : jamais une seconde erreur)."""

        try:
            listed = await self._core.call(lambda c: c.presentation_studio_list(limit=MAX_LISTED))
        except Exception:  # noqa: BLE001 - argued: the first error is the one the model needs; this is only a hint
            return None
        return {"presentations": [{"presentation_id": p.get("presentation_id"), "active_variant_id": p.get("active_variant_id")}
                                  for p in (listed.get("presentations") or [])[:MAX_LISTED] if isinstance(p, Mapping)]}

    def _refuse(self, tool: str, code: str, message: str, **data: Any) -> PresentationToolError:
        self._emit("presentation_studio.tool_failed", f"{tool} : {code}", level="warning",
                   data={"tool": tool, "code": code, "source": "presentation_studio_mcp", **data})
        return PresentationToolError(code, f"Refus {code} : {message}")

    async def _run(self, tool: str, op: str, ids: Mapping[str, Any], body: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        """Exécuter une opération : journal (corrélation), durée, erreurs codées. Rien du contenu n'est journalisé."""

        correlation_id = uuid.uuid4().hex[:12]
        started = self._clock()
        key = f"{tool}.{op}" if f"{tool}.{op}" in OPERATION_EVENTS else tool
        try:
            result = await body()
        except PresentationToolError as exc:
            self._emit("presentation_studio.tool_failed", f"{tool}.{op} : {exc.code}", level="warning",
                       data={"tool": tool, "op": op, "code": exc.code, "correlation_id": correlation_id, **ids})
            raise
        revision = result.get("revision") if isinstance(result.get("revision"), int) else None
        # The ids the call really acted on (defaults come from the state), so the line can be matched to the canonical event.
        resolved = {name: result[name] for name in ("presentation_id", "variant_id") if isinstance(result.get(name), str)}
        self._emit("presentation_studio.tool", f"{tool}.{op}", data={
            "tool": tool, "op": op, "correlation_id": correlation_id, "speech": result.get("speech"), "revision": revision,
            "event": OPERATION_EVENTS.get(key), "ms": round((self._clock() - started) * 1000), **{**ids, **resolved}})
        result.setdefault("op", op)
        return result

    @staticmethod
    def _ok(speech: str = "silent", say: str | None = None, **data: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "speech": speech}
        if say:
            out["say"] = say
        out.update(_drop_none(data))
        return out

    # ------------------------------------------------------------------ ids : jamais inventés

    async def _playback_view(self) -> dict[str, Any]:
        body = await self._c(lambda c: c.presentation_studio_playback_state())
        state = body.get("state") if isinstance(body, Mapping) else None
        return dict(state) if isinstance(state, Mapping) else {}

    async def _explorer_mirror(self) -> dict[str, Any]:
        if self._cc is None:
            return {}
        try:
            status, body = await self._cc.request("GET", "/api/presentation-studio/explorer/state", timeout_s=READ_TIMEOUT_S)
        except PresentationToolError:
            return {}
        return dict(body) if status == 200 and isinstance(body, Mapping) else {}

    async def _default_presentation(self, tool: str) -> str:
        """La présentation dont on parle, lue dans l'état : lecture en cours, explorateur ouvert, ou l'unique présentation."""

        state = await self._playback_view()
        if state.get("presentation_id") and state.get("phase") not in (None, "idle"):
            return str(state["presentation_id"])
        mirror = await self._explorer_mirror()
        if mirror.get("state") == "open" and is_presentation_id(mirror.get("presentation_id")):
            return str(mirror["presentation_id"])
        listed = await self._c(lambda c: c.presentation_studio_list(limit=MAX_LISTED))
        ids = [p.get("presentation_id") for p in listed.get("presentations") or [] if isinstance(p, Mapping)]
        if len(ids) == 1 and is_presentation_id(ids[0]):
            return str(ids[0])
        raise self._refuse(tool, "presentation_id_required",
                           "plusieurs présentations existent (ou aucune) : donne presentation_id, lu avec presentation_inspect "
                           "(target overview).", presentations=len(ids))

    async def _presentation(self, tool: str, value: str | None) -> str:
        if value is None:
            return await self._default_presentation(tool)
        if not is_presentation_id(value):
            raise self._refuse(tool, "invalid_id", "presentation_id mal formé : prends-le dans presentation_inspect (target overview).")
        return value

    async def _variant(self, tool: str, presentation_id: str, value: str | None) -> str:
        if value is not None:
            if not is_variant_id(value):
                raise self._refuse(tool, "invalid_id", "variant_id mal formé : prends-le dans presentation_inspect (target presentation).")
            return value
        graph = await self._c(lambda c: c.presentation_studio_graph(presentation_id))
        active = graph.get("active_variant_id")
        if not is_variant_id(active):
            raise self._refuse(tool, "variant_id_required", "aucune variante active lisible : donne variant_id.")
        return str(active)

    def _scene(self, tool: str, value: object) -> str:
        if not is_scene_id(value):
            raise self._refuse(tool, "invalid_id", "scene_id mal formé : prends-le dans presentation_inspect (target variant).")
        return str(value)

    # ------------------------------------------------------------------ lecture : état courant et choix valides

    async def inspect(self, target: str, *, presentation_id: str | None = None, variant_id: str | None = None,
                      scene_id: str | None = None, template_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
        ids = {"target": target}

        async def body() -> dict[str, Any]:
            return await self._inspect(target, presentation_id, variant_id, scene_id, template_id, kind)

        return await self._run("presentation_inspect", target, ids, body)

    async def _inspect(self, target: str, pid: str | None, vid: str | None, sid: str | None, tid: str | None,
                       kind: str | None) -> dict[str, Any]:
        tool = "presentation_inspect"
        if target == "overview":
            return await self._overview()
        if target == "draft_guide":
            return self._ok(**draft_guide(kind))
        if target == "playback":
            return self._ok(state=self._playback_summary(await self._playback_view()))
        if target == "explorer":
            return await self._explorer_and_fullscreen()
        if target == "templates":
            listed = await self._c(lambda c: c.presentation_studio_templates(kind))
            rows = [_drop_none({"template_id": t.get("template_id"), "kind": t.get("kind"), "title": clip(t.get("title")),
                                "slug": t.get("slug"), "scene_count": t.get("scene_count")})
                    for t in listed.get("templates") or [] if isinstance(t, Mapping)]
            return self._ok(templates=capped(rows), problems=(listed.get("problems") or [])[:5], untrusted=["title"])
        if target == "template":
            if not is_template_id(tid):
                raise self._refuse(tool, "invalid_id", "template_id mal formé : prends-le dans presentation_inspect (target templates).")
            found = await self._c(lambda c: c.presentation_studio_template(str(tid)))
            return self._ok(template=self._template_summary(found), availability=(found.get("prefab_availability") or [])[:12],
                            untrusted=["title"])
        presentation_id = await self._presentation(tool, pid)
        if target == "presentation":
            return await self._graph(presentation_id)
        if target == "compare":
            return self._ok(**self._compare_summary(await self._c(lambda c: c.presentation_studio_compare(presentation_id))))
        variant_id = await self._variant(tool, presentation_id, vid)
        if target == "composition":
            found = await self._c(lambda c: c.presentation_studio_composition(presentation_id, variant_id))
            return self._ok(presentation_id=presentation_id, variant_id=variant_id, **self._composition_summary(found))
        if target == "variant":
            return await self._variant_view(presentation_id, variant_id)
        if target == "score":
            return await self._score_view(presentation_id, variant_id)
        if target == "history":
            return self._ok(presentation_id=presentation_id, variant_id=variant_id, **self._history_summary(
                await self._c(lambda c: c.presentation_studio_history(presentation_id, variant_id))))
        if target == "scene":
            return await self._scene_view(presentation_id, variant_id, self._scene(tool, sid))
        if target == "choices":
            return await self._choices(presentation_id, variant_id, sid)
        raise self._refuse(tool, "unknown_target", f"target inconnue : {clip(target, 30)}.")

    def _playback_summary(self, state: Mapping[str, Any]) -> dict[str, Any]:
        keys = ("phase", "role", "presentation_id", "variant_id", "stage_object_id", "position", "scene", "item", "speaking", "next",
                "detour", "sequence", "elapsed", "armed", "follower", "mode", "art_direction", "notices", "problems", "preview",
                "last_run")
        summary = {key: state[key] for key in keys if state.get(key) is not None}
        for part in ("scene", "item"):
            if isinstance(summary.get(part), Mapping):
                summary[part] = {k: clip(v) if isinstance(v, str) else v for k, v in summary[part].items()}
        summary.setdefault("phase", "idle")
        return summary

    async def _overview(self) -> dict[str, Any]:
        listed = await self._c(lambda c: c.presentation_studio_list(limit=MAX_LISTED))
        rows = [{"presentation_id": p.get("presentation_id"), "title": clip(p.get("title")), "active_variant_id": p.get("active_variant_id"),
                 "variant_count": p.get("variant_count")} for p in listed.get("presentations") or [] if isinstance(p, Mapping)]
        playback = self._playback_summary(await self._playback_view())
        mirror = await self._explorer_mirror()
        explorer = _drop_none({"state": mirror.get("state"), "mode": mirror.get("mode"), "presentation_id": mirror.get("presentation_id"),
                               "variant_id": mirror.get("variant_id"), "reported_s_ago": mirror.get("age_s")})
        return self._ok(presentations=capped(rows), problems=(listed.get("problems") or [])[:5],
                        playback={k: playback[k] for k in ("phase", "role", "presentation_id", "variant_id") if k in playback},
                        explorer=explorer, untrusted=["title"])

    async def _explorer_and_fullscreen(self) -> dict[str, Any]:
        mirror = await self._explorer_mirror()
        fullscreen: dict[str, Any] = {}
        if self._cc is not None:
            try:
                status, body = await self._cc.request("GET", "/api/fullscreen/state", timeout_s=READ_TIMEOUT_S)
                fullscreen = dict(body) if status == 200 and isinstance(body, Mapping) else {}
            except PresentationToolError:
                fullscreen = {}
        return self._ok(explorer=_drop_none({k: mirror.get(k) for k in (
            "state", "mode", "fullscreen", "presentation_id", "variant_id", "variant_number", "explanation", "age_s")}),
            fullscreen=_drop_none({k: fullscreen.get(k) for k in ("state", "object_id", "display", "age_s")}),
            note="Miroir daté de la page : dis « dernier état rapporté il y a N s » quand tu le cites.")

    async def _graph(self, presentation_id: str) -> dict[str, Any]:
        graph = await self._c(lambda c: c.presentation_studio_graph(presentation_id))
        nodes = [_drop_none({"variant_id": n.get("variant_id"), "number": n.get("variant_number"), "title": clip(n.get("title")),
                             "parent_variant_id": n.get("parent_variant_id"), "scene_count": n.get("scene_count"),
                             "active": bool(n.get("active")) or None, "created_by": n.get("created_by"),
                             "sources": n.get("sources") or None})
                 for n in graph.get("nodes") or [] if isinstance(n, Mapping)]
        return self._ok(presentation_id=presentation_id, active_variant_id=graph.get("active_variant_id"),
                        revision=graph.get("revision"), variants=capped(nodes, 48), untrusted=["title"])

    async def _variant_view(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        variant = await self._c(lambda c: c.presentation_studio_variant(presentation_id, variant_id))
        scenes = []
        for index, scene in enumerate(variant.get("scenes") or []):
            if not isinstance(scene, Mapping):
                continue
            prefab = scene.get("prefab") if isinstance(scene.get("prefab"), Mapping) else {}
            local = scene.get("scene_variants") if isinstance(scene.get("scene_variants"), Mapping) else {}
            scenes.append(_drop_none({"scene_id": scene.get("scene_id"), "index": index, "title": clip(scene.get("title")),
                                      "prefab": prefab.get("id"), "controls": len(scene.get("controls") or []),
                                      "local_variants": len(local.get("variants") or []) or None}))
        return self._ok(presentation_id=presentation_id, variant_id=variant_id, revision=variant.get("revision"),
                        title=clip(variant.get("title")), scenes=capped(scenes, 64), has_score=bool(variant.get("score_id")),
                        has_art_direction=bool(variant.get("art_direction_id")), untrusted=["title", "scenes.items.title"])

    async def _score_view(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        found = await self._c(lambda c: c.presentation_studio_score(presentation_id, variant_id))
        score = found.get("score") if isinstance(found.get("score"), Mapping) else {}
        items = [_drop_none({"item_id": i.get("item_id"), "scene_id": i.get("scene_id"), "label": clip(i.get("label")),
                             "presenter": i.get("presenter"), "kind": i.get("kind")})
                 for i in score.get("items") or [] if isinstance(i, Mapping)]
        return self._ok(presentation_id=presentation_id, variant_id=variant_id, score_revision=score.get("revision"),
                        start_item_id=score.get("start_item_id"), items=capped(items, 48), cues=len(score.get("cues") or []),
                        sequences=len(score.get("sequences") or []), problems=(found.get("problems") or [])[:8],
                        untrusted=["items.items.label"], note="Les textes dits et les notes ne sont pas rendus ici (ce sont des données d'auteur).")

    async def _scene_view(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        described = await self._c(lambda c: c.presentation_studio_scene_controls(presentation_id, variant_id, scene_id))
        controls = []
        for control in described.get("controls") or []:
            if not isinstance(control, Mapping):
                continue
            current = control.get("current")
            controls.append(_drop_none({"control_id": control.get("control_id"), "label": clip(control.get("label")), "group": control.get("group"),
                                        "type": control.get("type"), "bounds": control.get("bounds"),
                                        "current": clip(current, 60) if isinstance(current, str) else current,
                                        "is_set": control.get("is_set")}))
        local = await self._c(lambda c: c.presentation_studio_scene_variants(presentation_id, variant_id, scene_id))
        variants = [_drop_none({"scene_variant_id": v.get("variant_id"), "label": clip(v.get("label")), "selected": bool(v.get("selected")) or None})
                    for v in local.get("variants") or [] if isinstance(v, Mapping)]
        return self._ok(presentation_id=presentation_id, variant_id=variant_id, scene_id=scene_id,
                        revision=described.get("variant_revision"), title=clip(described.get("title")),
                        prefab=described.get("prefab"), controls=capped(controls, 32), anchors=(described.get("anchors") or [])[:12],
                        scene_variants=capped(variants), problems=(described.get("problems") or [])[:6],
                        untrusted=["title", "controls.items.label", "scene_variants.items.label"])

    @staticmethod
    def _history_summary(history: Mapping[str, Any]) -> dict[str, Any]:
        def head(entry: object) -> dict[str, Any] | None:
            if not isinstance(entry, Mapping):
                return None
            return _drop_none({"entry_id": entry.get("entry_id"), "actor": entry.get("actor"), "tier": entry.get("tier"),
                               "ops": list(entry.get("ops") or [])[:8]})

        return _drop_none({"revision": history.get("revision"), "tracked": history.get("tracked"), "reason": history.get("reason"),
                           "undo_count": history.get("undo_count"), "redo_count": history.get("redo_count"),
                           "next_undo": head(history.get("next_undo")), "next_redo": head(history.get("next_redo"))})

    @staticmethod
    def _compare_summary(view: Mapping[str, Any]) -> dict[str, Any]:
        variants = [_drop_none({"variant_id": v.get("variant_id"), "number": v.get("variant_number"), "title": clip(v.get("title")),
                                "revision": v.get("revision"), "scene_count": v.get("scene_count")})
                    for v in view.get("variants") or [] if isinstance(v, Mapping)]
        structure = view.get("structure") if isinstance(view.get("structure"), Mapping) else {}
        return _drop_none({"presentation_id": view.get("presentation_id"), "active": bool(view.get("active")), "revision": view.get("revision"),
                           "layout": view.get("layout"), "mode": view.get("mode"), "pair": view.get("pair"), "variants": variants,
                           "relation": structure.get("relation"), "unmapped": {k: len(v) for k, v in (view.get("unmapped") or {}).items()} or None,
                           "links": len(view.get("links") or []), "anchors": view.get("anchors") or None,
                           "problems": (view.get("problems") or [])[:6], "untrusted": ["variants.title"]})

    @staticmethod
    def _composition_summary(found: Mapping[str, Any]) -> dict[str, Any]:
        composition = found.get("composition") if isinstance(found.get("composition"), Mapping) else {}
        dims = [_drop_none({"dimension": d.get("dimension"), "inherited": d.get("inherited"),
                            "from": [s.get("variant_number") for s in d.get("sources") or [] if isinstance(s, Mapping)]})
                for d in composition.get("dimensions") or [] if isinstance(d, Mapping)]
        return {"base_variant_id": composition.get("base_variant_id"), "dimensions": dims, "warnings": (composition.get("warnings") or [])[:6]}

    @staticmethod
    def _template_summary(found: Mapping[str, Any]) -> dict[str, Any]:
        summary = found.get("summary") if isinstance(found.get("summary"), Mapping) else {}
        return _drop_none({"template_id": summary.get("template_id"), "kind": summary.get("kind"), "title": clip(summary.get("title")),
                           "slug": summary.get("slug"), "scene_count": summary.get("scene_count")})

    async def _choices(self, presentation_id: str, variant_id: str, scene_id: str | None) -> dict[str, Any]:
        """La table des ids valides à cet instant : ce que le modèle peut nommer, et rien d'autre."""

        graph = await self._c(lambda c: c.presentation_studio_graph(presentation_id))
        variant = await self._c(lambda c: c.presentation_studio_variant(presentation_id, variant_id))
        table: dict[str, Any] = {
            "presentation_id": presentation_id, "variant_id": variant_id,
            "variant_ids": [n.get("variant_id") for n in graph.get("nodes") or [] if isinstance(n, Mapping)][:48],
            "scene_ids": [s.get("scene_id") for s in variant.get("scenes") or [] if isinstance(s, Mapping)][:64],
            "revision": variant.get("revision")}
        try:
            score = (await self._c(lambda c: c.presentation_studio_score(presentation_id, variant_id))).get("score") or {}
            table["item_ids"] = [i.get("item_id") for i in score.get("items") or [] if isinstance(i, Mapping)][:64]
        except PresentationToolError:
            table["item_ids"] = []
        if scene_id is not None:
            described = await self._c(lambda c: c.presentation_studio_scene_controls(presentation_id, variant_id, scene_id))
            table["control_ids"] = [c.get("control_id") for c in described.get("controls") or [] if isinstance(c, Mapping)][:32]
            table["anchor_ids"] = [a.get("anchor_id") for a in described.get("anchors") or [] if isinstance(a, Mapping)][:12]
            local = await self._c(lambda c: c.presentation_studio_scene_variants(presentation_id, variant_id, scene_id))
            table["scene_variant_ids"] = [v.get("variant_id") for v in local.get("variants") or [] if isinstance(v, Mapping)][:12]
        table["roles"] = ["user_presenter", "jarvis_presenter", "rehearsal"]
        return self._ok(**table)

    # ------------------------------------------------------------------ explorateur et plein écran (page)

    async def view(self, op: str, *, presentation_id: str | None = None, variant_id: str | None = None, fullscreen: bool = True) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._view(op, presentation_id, variant_id, fullscreen)

        return await self._run("presentation_view", op, {"presentation_id": presentation_id, "variant_id": variant_id}, body)

    async def _view(self, op: str, presentation_id: str | None, variant_id: str | None, fullscreen: bool) -> dict[str, Any]:
        tool = "presentation_view"
        if self._cc is None:
            raise self._refuse(tool, "control_center_unreachable", sentence_for("control_center_unreachable"))
        if op == "explorer_open":
            pid = await self._presentation(tool, presentation_id)
            vid = None if variant_id is None else await self._variant(tool, pid, variant_id)
            request = _drop_none({"action": "open", "presentation_id": pid, "variant_id": vid, "fullscreen": bool(fullscreen)})
            status, receipt = await self._cc.request("POST", "/api/presentation-studio/explorer/commands", request, timeout_s=30.0)
            return self._explorer_receipt(op, status, receipt, pid, vid)
        if op == "explorer_close":
            status, receipt = await self._cc.request("POST", "/api/presentation-studio/explorer/commands", {"action": "close"})
            return self._explorer_receipt(op, status, receipt, None, None)
        if op == "stage_fullscreen_enter":
            state = await self._playback_view()
            stage = state.get("stage_object_id")
            if not stage or state.get("phase") in (None, "idle"):
                raise self._refuse(tool, "no_run", "aucune lecture ne tourne : il n'y a pas de scène de présentation à mettre en plein écran. "
                                                    "Lance la lecture d'abord (presentation_play start).")
            return self._fullscreen_receipt(op, *await self._cc.request(
                "POST", "/api/fullscreen/commands", {"action": "enter", "object_id": stage, "keys": "host"}))
        if op == "fullscreen_exit":
            return self._fullscreen_receipt(op, *await self._cc.request("POST", "/api/fullscreen/commands", {"action": "exit"}))
        raise self._refuse(tool, "unknown_op", f"op inconnue : {clip(op, 30)}.")

    def _page_refusal(self, tool_op: str, status: int, body: Any) -> PresentationToolError:
        code = "http_%d" % status
        reason = ""
        if isinstance(body, Mapping):
            error = body.get("error")
            code = str(body.get("code") or (error.get("code") if isinstance(error, Mapping) else None) or code)
            reason = clip(body.get("reason") or (error.get("message") if isinstance(error, Mapping) else error), 200)
        return self._refuse("presentation_view", code, f"{sentence_for(code, reason)} ({reason})" if reason else sentence_for(code))

    def _explorer_receipt(self, op: str, status: int, receipt: Any, pid: str | None, vid: str | None) -> dict[str, Any]:
        if status >= 400 or not isinstance(receipt, Mapping):
            raise self._page_refusal(op, status, receipt)
        state = receipt.get("state")
        if state == "refused":
            raise self._page_refusal(op, 409, {"code": receipt.get("code"), "reason": receipt.get("reason")})
        mode = receipt.get("mode")
        armed = mode == "fullscreen_armed"
        # Un geste attendu de l'utilisateur est la seule réussite qui se dit : il ne sait pas qu'il doit cliquer.
        return self._ok("say" if armed else "silent", say=("L'explorateur est ouvert ; clique sur « Passer en plein écran » pour le plein écran."
                                                           if armed else None),
                        status=state, mode=mode, fullscreen=receipt.get("fullscreen"), needs_gesture=armed or None,
                        presentation_id=receipt.get("presentation_id") or pid, variant_id=receipt.get("variant_id") or vid,
                        explanation=receipt.get("explanation"))

    def _fullscreen_receipt(self, op: str, status: int, answer: Any) -> dict[str, Any]:
        if status >= 400 or not isinstance(answer, Mapping):
            raise self._page_refusal(op, status, answer)
        state = answer.get("state")
        if state in ("refused", "unsupported", "expired"):
            raise self._page_refusal(op, 409, {"code": answer.get("code") or f"fullscreen_{state}", "reason": answer.get("reason")})
        armed = state == "needs_gesture"
        return self._ok("say" if armed else "silent", say=("Un clic est nécessaire : clique sur l'invite « Passer en plein écran »." if armed else None),
                        status=state, needs_gesture=armed or None,
                        note="Ne dis jamais que c'est en plein écran avant que presentation_inspect target explorer ne le montre." if armed else None)

    # ------------------------------------------------------------------ lecture / répétition / navigation

    async def _addressed_user_turn(self) -> bool:
        """Un tour adressé de l'utilisateur est-il en vol ? Réponse du Control Center (`presentation_studio_turn`), `False` à la moindre panne."""

        if self._cc is None:
            return False
        try:
            status, body = await self._cc.request("GET", "/api/presentation-studio/agent/turn", timeout_s=READ_TIMEOUT_S)
        except PresentationToolError:
            return False
        return status == 200 and isinstance(body, Mapping) and body.get("addressed_user_turn") is True

    async def play(self, op: str, *, presentation_id: str | None = None, variant_id: str | None = None, role: str | None = None,
                   jarvis_speaks: bool | None = None, item_id: str | None = None, scene_id: str | None = None,
                   position: int | None = None, anchor_id: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._play(op, presentation_id, variant_id, role, jarvis_speaks, item_id, scene_id, position, anchor_id)

        return await self._run("presentation_play", op, {"presentation_id": presentation_id, "variant_id": variant_id}, body)

    async def _play(self, op: str, pid: str | None, vid: str | None, role: str | None, speaks: bool | None, item: str | None,
                    scene: str | None, position: int | None, anchor: str | None) -> dict[str, Any]:
        tool = "presentation_play"
        request: dict[str, Any] = {"actor": BRAIN_ACTOR}
        if op == "start":
            if role not in ("user_presenter", "jarvis_presenter", "rehearsal"):
                raise self._refuse(tool, "invalid_role", "role : user_presenter, jarvis_presenter ou rehearsal.")
            presentation_id = await self._presentation(tool, pid)
            request.update(presentation_id=presentation_id, role=role)
            if vid is not None:
                request["variant_id"] = await self._variant(tool, presentation_id, vid)
            if speaks is not None:
                request["jarvis_speaks"] = bool(speaks)
            # L'origine n'est jamais un argument : elle vient du tour réel, attesté par le Control Center qui sert ce tour. Sans attestation,
            # on n'envoie rien et Core applique son défaut `brain_spontaneous`, qui ne change pas le mode (le démarrage est alors refusé).
            if await self._addressed_user_turn():
                request["origin"] = "explicit_user_request"
        elif op == "goto":
            targets = {k: v for k, v in (("item_id", item), ("scene_id", scene), ("position", position)) if v is not None}
            if len(targets) != 1:
                raise self._refuse(tool, "invalid_target", "goto : exactement un de item_id, scene_id, position (1 = premier).")
            if item is not None and not ITEM_ID.fullmatch(item):
                raise self._refuse(tool, "invalid_id", "item_id mal formé : prends-le dans presentation_inspect (target score).")
            if scene is not None:
                self._scene(tool, scene)
            request.update(targets)
        elif op in ("reveal", "hide"):
            if not isinstance(anchor, str) or not ANCHOR_ID.fullmatch(anchor):
                raise self._refuse(tool, "invalid_id", "anchor_id : une ancre lue dans presentation_inspect (target scene, anchors).")
            request["anchor_id"] = anchor
        elif op not in PLAY_NAVIGATION:
            raise self._refuse(tool, "unknown_op", f"op inconnue : {clip(op, 30)}.")
        answer = await self._c(lambda c: c.presentation_studio_playback(op, request))
        status = answer.get("status")
        view = self._playback_summary(answer.get("view") if isinstance(answer.get("view"), Mapping) else answer.get("state") or {})
        if status == "refused" or status == "stage_failed":
            reason = str(answer.get("reason") or answer.get("code") or status)
            message = clip((answer.get("error") or {}).get("message") if isinstance(answer.get("error"), Mapping) else answer.get("message"), 240)
            raise self._refuse(tool, reason, f"{sentence_for(reason, message)} ({message})" if message else sentence_for(reason), state=view.get("phase"))
        # Démarrer, arrêter, naviguer : l'écran montre le résultat, rien à dire (Jarvis dit ses lignes de partition par son propre chemin).
        return self._ok("silent", status=status, state=view)

    # ------------------------------------------------------------------ édition sémantique

    def _edit_wire(self, tool: str, ops: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(ops, Sequence) or not 1 <= len(ops) <= 16:
            raise self._refuse(tool, "invalid_ops", "ops : de 1 à 16 ordres.")
        wire: list[dict[str, Any]] = []
        for index, raw in enumerate(ops):
            data = {k: v for k, v in dict(raw).items() if v is not None}
            name = data.pop("op", None)
            if name not in EDIT_FIELDS:
                raise self._refuse(tool, "unknown_op", f"ops[{index}] : op inconnue ({clip(name, 30)}) ; permises : {', '.join(EDIT_OPS)}.")
            extra = sorted(set(data) - EDIT_FIELDS[name])
            if extra:
                raise self._refuse(tool, "invalid_ops", f"ops[{index}] {name} : champs non permis {', '.join(extra)} ; permis : {', '.join(sorted(EDIT_FIELDS[name]))}.")
            missing = sorted(EDIT_REQUIRED[name] - set(data))
            if missing:
                raise self._refuse(tool, "invalid_ops", f"ops[{index}] {name} : champs manquants {', '.join(missing)}.")
            self._scene(tool, data["scene_id"])
            if "control_id" in data and not (isinstance(data["control_id"], str) and CONTROL_ID.fullmatch(data["control_id"])):
                raise self._refuse(tool, "invalid_id", f"ops[{index}] : control_id mal formé ; prends-le dans presentation_inspect (target scene).")
            if "scene_variant_id" in data:
                if not is_scene_variant_id(data["scene_variant_id"]):
                    raise self._refuse(tool, "invalid_id", f"ops[{index}] : scene_variant_id mal formé (psx_...) ; prends-le dans presentation_inspect (target scene).")
                data["variant_id"] = data.pop("scene_variant_id")
            if "from_variant" in data and not is_scene_variant_id(data["from_variant"]):
                raise self._refuse(tool, "invalid_id", f"ops[{index}] : from_variant mal formé (psx_...).")
            wire.append({"op": name, **data})
        return wire

    async def edit(self, ops: Sequence[Mapping[str, Any]], *, presentation_id: str | None = None, variant_id: str | None = None,
                   revision: int | None = None, mode: str = "commit", confirmation: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._edit(ops, presentation_id, variant_id, revision, mode, confirmation)

        return await self._run("presentation_edit", mode, {"presentation_id": presentation_id, "variant_id": variant_id,
                                                           "ops": [o.get("op") for o in ops if isinstance(o, Mapping)][:16]}, body)

    async def _edit(self, ops: Sequence[Mapping[str, Any]], pid: str | None, vid: str | None, revision: int | None, mode: str,
                    confirmation: str | None) -> dict[str, Any]:
        tool = "presentation_edit"
        if mode not in ("preview", "commit"):
            raise self._refuse(tool, "invalid_mode", "mode : preview ou commit.")
        wire = self._edit_wire(tool, ops)
        # Remotion Slice 21: a structural source change starts a sub-agent edit of the scene's source. It only follows a request of the user in
        # this turn (the attested turn, as for a presentation start or a promotion): no ambient or system-opened turn can mutate a source.
        user_origin = False
        if mode == "commit" and any(o["op"] == "scene.source_request" for o in wire):
            user_origin = await self._addressed_user_turn()
            if not user_origin:
                raise self._refuse(tool, "presentation_studio_source_request_user_only",
                                   "scene.source_request : seulement sur une demande de l'utilisateur dans ce tour ; propose-le, il le demandera.")
        presentation_id = await self._presentation(tool, pid)
        variant_id = await self._variant(tool, presentation_id, vid)
        removed = sorted(str(o["scene_id"]) for o in wire if o["op"] == "scene.remove")
        if removed and mode == "commit":
            stored = await self._c(lambda c: c.presentation_studio_variant(presentation_id, variant_id))
            key = (presentation_id, variant_id, stored.get("revision"), ",".join(removed))
            if not self.ledger.check("scene.remove", confirmation, *key):
                token = self.ledger.issue("scene.remove", *key)
                titles = {s.get("scene_id"): clip(s.get("title"), 40) for s in stored.get("scenes") or [] if isinstance(s, Mapping)}
                shown = [{"scene_id": s, "title": titles.get(s)} for s in removed][:8]
                return self._ok("say", status="confirmation_required", confirmation=token, scenes=shown, untrusted=["scenes.title"],
                                say=f"Retirer {len(removed)} scène(s) de la variante ? Dis oui pour confirmer.",
                                note="Rien n'est écrit. Après le oui de l'utilisateur, renvoie la même demande avec confirmation. "
                                     "L'annulation (presentation_undo) rétablit la scène.")
        basis = revision
        if basis is None:
            basis = (await self._c(lambda c: c.presentation_studio_variant(presentation_id, variant_id))).get("revision")
        request = {"actor": BRAIN_ACTOR, "mode": mode, "basis": {"variant_revision": basis}, "ops": wire}
        if user_origin:
            # Core records a brain source request only with this origin, and a brain source edit later needs that record (QA B1).
            request["origin"] = "explicit_user_request"
        result = await self._c(lambda c: c.presentation_studio_edit(presentation_id, variant_id, request))
        status = result.get("status")
        if status in ("stale", "refused"):
            code = str(result.get("code") or f"edit_{status}")
            message = clip(result.get("message"), 240)
            raise self._refuse(tool, code, f"{sentence_for(code, message)} ({message}) ops[{result.get('failed_index')}]"
                               if result.get("failed_index") is not None else f"{sentence_for(code, message)} ({message})")
        undo = result.get("undo") if isinstance(result.get("undo"), Mapping) else {}
        outcomes = [_drop_none({"op": o.get("op"), "status": o.get("status"), "scene_id": o.get("scene_id")})
                    for o in result.get("ops") or [] if isinstance(o, Mapping)][:16]
        if removed and mode == "commit":
            self.ledger.consume(str(confirmation))
        recorded = result.get("source_requests") or None
        # Remotion Slice 21 (real-model trace): the brain delegated BEFORE recording and told the sub-agent to record it, which an unattended
        # background turn can no longer do. The result says what is left to do and who does it.
        next_step = ("Demande de source enregistrée (rien n'est encore changé à l'écran) : un sous-agent d'arrière-plan lit la source et envoie "
                     "édite avec ce request_id, valable 30 minutes (docs/OPERATIONS.md) ; il n'appelle pas scene.source_request.") if recorded and mode == "commit" else None
        return self._ok("silent", status=status, mode=mode, committed=result.get("committed"), changed=result.get("changed"),
                        revision=result.get("revision"), tier=result.get("tier"), results=outcomes,
                        undoable=bool(undo.get("available")) or None, source_requests=recorded, next_step=next_step,
                        presentation_id=presentation_id, variant_id=variant_id)

    async def undo(self, direction: str = "undo", *, presentation_id: str | None = None, variant_id: str | None = None,
                   confirmation: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._undo(direction, presentation_id, variant_id, confirmation)

        return await self._run("presentation_undo", direction, {"presentation_id": presentation_id, "variant_id": variant_id}, body)

    async def _undo(self, direction: str, pid: str | None, vid: str | None, confirmation: str | None) -> dict[str, Any]:
        tool = "presentation_undo"
        if direction not in ("undo", "redo"):
            raise self._refuse(tool, "invalid_direction", "direction : undo ou redo.")
        presentation_id = await self._presentation(tool, pid)
        variant_id = await self._variant(tool, presentation_id, vid)
        history = await self._c(lambda c: c.presentation_studio_history(presentation_id, variant_id))
        head = history.get("next_undo" if direction == "undo" else "next_redo")
        if not isinstance(head, Mapping) or not head.get("entry_id"):
            code = "nothing_to_undo" if direction == "undo" else "nothing_to_redo"
            raise self._refuse(tool, code, "il n'y a rien à " + ("annuler" if direction == "undo" else "rétablir")
                               + (f" ({history.get('reason')})" if history.get("reason") else "") + ".")
        entry_id = str(head["entry_id"])
        # Annuler la modification de l'utilisateur (son curseur, sa saisie) se confirme : la voix n'efface pas son travail sans son accord.
        if head.get("actor") != BRAIN_ACTOR:
            key = (presentation_id, variant_id, entry_id, direction)
            if not self.ledger.check("undo", confirmation, *key):
                token = self.ledger.issue("undo", *key)
                return self._ok("say", status="confirmation_required", confirmation=token, entry_id=entry_id,
                                ops=list(head.get("ops") or [])[:8], say="C'est ta dernière modification : je l'annule ? Dis oui pour confirmer.",
                                note="Rien n'est modifié. Après le oui de l'utilisateur, renvoie la même demande avec confirmation.")
            self.ledger.consume(str(confirmation))
        request = {"actor": BRAIN_ACTOR, "expected_entry_id": entry_id}
        call = (lambda c: c.presentation_studio_undo(presentation_id, variant_id, request)) if direction == "undo" else \
               (lambda c: c.presentation_studio_redo(presentation_id, variant_id, request))
        result = await self._c(call)
        status = result.get("status")
        if status != "applied":
            code = str(result.get("code") or result.get("reason") or status or "history_refused")
            raise self._refuse(tool, code, f"{sentence_for(code, clip(result.get('message'), 200))} (état : {status}).")
        return self._ok("silent", status=status, revision=result.get("revision"), score_problems=result.get("score_problems"),
                        presentation_id=presentation_id, variant_id=variant_id)

    # ------------------------------------------------------------------ branches, variantes de scène

    async def variant(self, op: str, *, presentation_id: str | None = None, variant_id: str | None = None, title: str | None = None,
                      rationale: str | None = None, source_variant_id: str | None = None, activate: bool | None = None,
                      activate_variant_id: str | None = None, confirmation: str | None = None, confirmed: bool | None = None,
                      with_descendants: bool | None = None, scene_id: str | None = None, scene_variant_id: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._variant_op(op, presentation_id, variant_id, title, rationale, source_variant_id, activate,
                                          activate_variant_id, confirmation, confirmed, with_descendants, scene_id, scene_variant_id)

        return await self._run("presentation_variant", op, {"presentation_id": presentation_id, "variant_id": variant_id}, body)

    async def _variant_op(self, op: str, pid: str | None, vid: str | None, title: str | None, rationale: str | None,
                          source: str | None, activate: bool | None, activate_vid: str | None, confirmation: str | None,
                          confirmed: bool | None, descendants: bool | None, scene_id: str | None, scene_vid: str | None) -> dict[str, Any]:
        tool = "presentation_variant"
        presentation_id = await self._presentation(tool, pid)
        if op == "create":
            if not isinstance(title, str) or not title.strip():
                raise self._refuse(tool, "title_required", "create exige title (une ligne).")
            request = _drop_none({"actor": BRAIN_ACTOR, "title": title, "rationale": rationale, "activate": activate,
                                  "source_variant_id": None if source is None else await self._variant(tool, presentation_id, source)})
            created = await self._c(lambda c: c.presentation_studio_create_branch(presentation_id, request))
            node = created.get("node") if isinstance(created.get("node"), Mapping) else {}
            variant = created.get("variant") if isinstance(created.get("variant"), Mapping) else {}
            number = node.get("variant_number") or variant.get("variant_number")
            return self._ok("say", say=f"La variante {number} est créée." if number else "La variante est créée.", status="created",
                            variant_id=variant.get("variant_id") or node.get("variant_id"), variant_number=number,
                            activated=created.get("activated"), presentation_id=presentation_id)
        variant_id = await self._variant(tool, presentation_id, vid)
        if op == "activate":
            await self._c(lambda c: c.presentation_studio_activate(presentation_id, variant_id, {"actor": BRAIN_ACTOR}))
            return self._ok(status="activated", variant_id=variant_id, presentation_id=presentation_id)
        if op == "rename":
            if not isinstance(title, str) or not title.strip():
                raise self._refuse(tool, "title_required", "rename exige title (une ligne).")
            await self._c(lambda c: c.presentation_studio_rename(presentation_id, variant_id, {"actor": BRAIN_ACTOR, "title": title}))
            return self._ok(status="renamed", variant_id=variant_id, presentation_id=presentation_id)
        if op == "archive_plan":
            request = _drop_none({"actor": BRAIN_ACTOR,
                                  "activate_variant_id": None if activate_vid is None else await self._variant(tool, presentation_id, activate_vid)})
            answer = await self._c(lambda c: c.presentation_studio_archive_plan(presentation_id, variant_id, request))
            plan = answer.get("plan") if isinstance(answer.get("plan"), Mapping) else {}
            affected = [_drop_none({"variant_id": a.get("variant_id"), "number": a.get("variant_number"), "title": clip(a.get("title"), 40)})
                        for a in plan.get("affected") or [] if isinstance(a, Mapping)]
            token = answer.get("confirmation")
            if token:
                self._archive_plans[(presentation_id, variant_id)] = str(token)
            numbers = ", ".join(str(a.get("number")) for a in affected[:12])
            blocked = plan.get("blocked") or plan.get("blocked_reason") or None
            return self._ok("say", status="confirmation_required" if token else "blocked", confirmation=token, affected=capped(affected, 24),
                            includes_active=plan.get("includes_active"), requires_new_active=plan.get("requires_new_active") or None,
                            suggested_active=plan.get("suggested_active"), blocked=blocked, untrusted=["affected.items.title"],
                            say=(f"J'archive la branche {numbers} ({len(affected)} variante(s)) ? Dis oui pour confirmer." if token else None),
                            note="Rien n'est archivé. Après le oui de l'utilisateur, appelle archive avec confirmation et confirmed=true. "
                                 "L'archive se restaure (op restore).", presentation_id=presentation_id, variant_id=variant_id)
        if op == "archive":
            planned = self._archive_plans.get((presentation_id, variant_id))
            if confirmed is not True or not confirmation or planned != confirmation:
                raise self._refuse(tool, "presentation_studio_confirmation_required",
                                   "archiver exige archive_plan dans ce processus, le oui de l'utilisateur, puis confirmation (le jeton du plan) "
                                   "et confirmed=true. Rien n'a été archivé.")
            request = _drop_none({"actor": BRAIN_ACTOR, "confirmation": confirmation,
                                  "activate_variant_id": None if activate_vid is None else await self._variant(tool, presentation_id, activate_vid)})
            archived = await self._c(lambda c: c.presentation_studio_archive(presentation_id, variant_id, request))
            self._archive_plans.pop((presentation_id, variant_id), None)
            return self._ok("say", say="La branche est archivée ; elle se restaure.", status="archived",
                            archived=capped([a.get("variant_number") if isinstance(a, Mapping) else a
                                             for a in archived.get("archived") or archived.get("affected") or []], 24),
                            presentation_id=presentation_id, variant_id=variant_id)
        if op == "restore":
            await self._c(lambda c: c.presentation_studio_restore(presentation_id, variant_id, _drop_none(
                {"actor": BRAIN_ACTOR, "with_descendants": descendants})))
            return self._ok(status="restored", variant_id=variant_id, presentation_id=presentation_id)
        if op == "art_direction_fallback":
            stored = await self._c(lambda c: c.presentation_studio_variant(presentation_id, variant_id))
            made = await self._c(lambda c: c.presentation_studio_fallback_art_direction(
                presentation_id, variant_id, {"expected_variant_revision": stored.get("revision")}))
            art = made.get("art_direction") if isinstance(made.get("art_direction"), Mapping) else {}
            return self._ok("say", say="J'ai créé une direction artistique de repli, générée.", status="created",
                            art_direction_id=art.get("art_direction_id"), provenance="fallback", presentation_id=presentation_id,
                            variant_id=variant_id)
        if op in ("scene_preview", "scene_promote"):
            sid = self._scene(tool, scene_id)
            if not is_scene_variant_id(scene_vid):
                raise self._refuse(tool, "invalid_id", "scene_variant_id (psx_...) : prends-le dans presentation_inspect (target scene).")
            if op == "scene_preview":
                await self._c(lambda c: c.presentation_studio_scene_variant_preview(
                    presentation_id, variant_id, sid, str(scene_vid), {"actor": BRAIN_ACTOR}))
                return self._ok(status="previewing", note="Aperçu en mémoire sur la scène : rien n'est écrit ; scene_cancel_preview le retire.")
            if not isinstance(title, str) or not title.strip():
                raise self._refuse(tool, "title_required", "scene_promote exige title (une ligne).")
            promoted = await self._c(lambda c: c.presentation_studio_scene_variant_promote(
                presentation_id, variant_id, sid, str(scene_vid), _drop_none({"actor": BRAIN_ACTOR, "title": title, "rationale": rationale,
                                                                              "activate": activate})))
            node = promoted.get("node") if isinstance(promoted.get("node"), Mapping) else {}
            number = node.get("variant_number")
            return self._ok("say", say=f"La variante {number} est créée à partir de cette variante de scène." if number else None,
                            status="promoted", variant_number=number, presentation_id=presentation_id)
        if op == "scene_cancel_preview":
            await self._c(lambda c: c.presentation_studio_scene_variant_cancel_preview(presentation_id, {"actor": BRAIN_ACTOR}))
            return self._ok(status="preview_cancelled", presentation_id=presentation_id)
        raise self._refuse(tool, "unknown_op", f"op inconnue : {clip(op, 30)}.")

    # ------------------------------------------------------------------ comparaison et composition

    async def compare(self, op: str, *, presentation_id: str | None = None, variant_ids: Sequence[str] | None = None,
                      pair: Sequence[str] | None = None, mode: str | None = None, variant_id: str | None = None,
                      scene_id: str | None = None, step: str | None = None, a: Mapping[str, str] | None = None,
                      b: Mapping[str, str] | None = None, expected_revision: int | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._compare(op, presentation_id, variant_ids, pair, mode, variant_id, scene_id, step, a, b, expected_revision)

        return await self._run("presentation_compare", op, {"presentation_id": presentation_id}, body)

    async def _compare(self, op: str, pid: str | None, variant_ids: Sequence[str] | None, pair: Sequence[str] | None, mode: str | None,
                       variant_id: str | None, scene_id: str | None, step: str | None, a: Mapping[str, str] | None,
                       b: Mapping[str, str] | None, expected: int | None) -> dict[str, Any]:
        tool = "presentation_compare"
        presentation_id = await self._presentation(tool, pid)
        guard = _drop_none({"expected_revision": expected})

        def checked_variants(values: Sequence[str] | None, name: str) -> list[str]:
            if not values or any(not is_variant_id(v) for v in values):
                raise self._refuse(tool, "invalid_id", f"{name} : des variant_id lus dans presentation_inspect (target presentation).")
            return list(values)

        def link_ref(ref: Mapping[str, str] | None, name: str) -> dict[str, str]:
            if not isinstance(ref, Mapping) or not is_variant_id(ref.get("variant_id")) or not is_scene_id(ref.get("scene_id")):
                raise self._refuse(tool, "invalid_id", f"{name} : {{variant_id, scene_id}} lus dans la vue de comparaison.")
            return {"variant_id": str(ref["variant_id"]), "scene_id": str(ref["scene_id"])}

        if op == "open":
            ids = checked_variants(variant_ids, "variant_ids")
            if len(ids) not in (2, 4):
                raise self._refuse(tool, "invalid_selection", "on compare exactement 2 ou 4 variantes.")
            body = _drop_none({"variant_ids": ids, "pair": None if pair is None else checked_variants(pair, "pair"), "mode": mode, **guard})
            route = "select"
        elif op == "focus":
            body, route = {"pair": None if not pair else checked_variants(pair, "pair"), **guard}, "pair"
        elif op == "mode":
            if mode not in ("sync", "independent"):
                raise self._refuse(tool, "invalid_mode", "mode : sync ou independent.")
            body, route = {"mode": mode, **guard}, "mode"
        elif op == "navigate":
            if not is_variant_id(variant_id) or (scene_id is None) == (step is None):
                raise self._refuse(tool, "invalid_target", "navigate : variant_id et exactement un de scene_id, step.")
            body, route = _drop_none({"variant_id": variant_id, "scene_id": None if scene_id is None else self._scene(tool, scene_id),
                                      "step": step, **guard}), "navigate"
        elif op in ("link", "unlink"):
            body, route = {"a": link_ref(a, "a"), "b": link_ref(b, "b"), **guard}, "links" if op == "link" else "links/remove"
        elif op == "close":
            body, route = dict(guard), "clear"
        else:
            raise self._refuse(tool, "unknown_op", f"op inconnue : {clip(op, 30)}.")
        view = await self._c(lambda c: c.presentation_studio_compare_op(presentation_id, route, body))
        summary = self._compare_summary(view) if "variants" in view or "layout" in view else _drop_none(
            {"presentation_id": presentation_id, "active": False, "cleared": view.get("cleared"), "revision": view.get("revision")})
        if isinstance(view.get("navigation"), Mapping):
            summary["navigation"] = {k: v for k, v in view["navigation"].items() if k in ("origin", "results")}
        return self._ok("silent", **summary)

    async def compose(self, op: str, request: Mapping[str, Any], *, presentation_id: str | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._compose(op, request, presentation_id)

        return await self._run("presentation_compose", op, {"presentation_id": presentation_id}, body)

    async def _compose(self, op: str, request: Mapping[str, Any], pid: str | None) -> dict[str, Any]:
        tool = "presentation_compose"
        if op not in ("plan", "create"):
            raise self._refuse(tool, "unknown_op", "op : plan ou create.")
        presentation_id = await self._presentation(tool, pid)
        body = {k: v for k, v in dict(request).items() if v is not None}
        body["actor"] = BRAIN_ACTOR
        for key in ("base", "scenes", "narrative", "motion", "art_direction"):
            value = body.get(key)
            if isinstance(value, str) and not is_variant_id(value):
                raise self._refuse(tool, "invalid_id", f"{key} : un variant_id lu dans presentation_inspect (target presentation).")
        # Les révisions des sources viennent du graphe lu ici si le modèle n'en donne pas (le même instant que le plan) : un état qui bouge
        # entre le plan et la création est une `stale_revision`, jamais un écrasement silencieux.
        if "source_revisions" not in body:
            graph = await self._c(lambda c: c.presentation_studio_graph(presentation_id))
            named: set[Any] = {body.get(key) for key in ("base", "narrative", "motion", "art_direction")}
            scenes = body.get("scenes")
            named |= {scenes} if isinstance(scenes, str) else {seg.get("from") for seg in scenes or [] if isinstance(seg, Mapping)}
            revisions = {n.get("variant_id"): n.get("revision") for n in graph.get("nodes") or []
                         if isinstance(n, Mapping) and n.get("variant_id") in named and isinstance(n.get("revision"), int)}
            if revisions:
                body["source_revisions"] = revisions
        if op == "plan":
            plan = await self._c(lambda c: c.presentation_studio_composition_plan(presentation_id, body))
            composition = plan.get("composition") if isinstance(plan.get("composition"), Mapping) else {}
            result = composition.get("result") if isinstance(composition.get("result"), Mapping) else {}
            self._last_plan = (presentation_id, json.dumps(body, sort_keys=True, default=str))
            return self._ok(ok_plan=bool(plan.get("ok")), conflicts=(plan.get("conflicts") or [])[:12],
                            summary=clip(result.get("summary"), 160) or None, scene_count=result.get("scene_count"),
                            presentation_id=presentation_id)
        if getattr(self, "_last_plan", None) != (presentation_id, json.dumps(body, sort_keys=True, default=str)):
            raise self._refuse(tool, "plan_required", "create n'est offert qu'après un plan de la même demande, dans ce tour, qui répond ok.")
        created = await self._c(lambda c: c.presentation_studio_compose(presentation_id, body))
        node = created.get("node") if isinstance(created.get("node"), Mapping) else {}
        composition = created.get("composition") if isinstance(created.get("composition"), Mapping) else {}
        result = composition.get("result") if isinstance(composition.get("result"), Mapping) else {}
        number = node.get("variant_number")
        self._last_plan = None
        return self._ok("say", say=f"La variante {number} est créée : {clip(result.get('summary'), 160)}" if number else None,
                        status="created", variant_number=number, variant_id=(created.get("variant") or {}).get("variant_id"),
                        activated=created.get("activated"), presentation_id=presentation_id)

    # ------------------------------------------------------------------ modèles

    async def template(self, op: str, *, presentation_id: str | None = None, variant_id: str | None = None, template_id: str | None = None,
                       plan: Mapping[str, Any] | None = None, title: str | None = None, destination_variant_id: str | None = None,
                       expected_revision: int | None = None) -> dict[str, Any]:
        async def body() -> dict[str, Any]:
            return await self._template(op, presentation_id, variant_id, template_id, plan, title, destination_variant_id, expected_revision)

        return await self._run("presentation_template", op, {"presentation_id": presentation_id, "variant_id": variant_id,
                                                              "template_id": template_id}, body)

    async def _template(self, op: str, pid: str | None, vid: str | None, tid: str | None, plan: Mapping[str, Any] | None,
                        title: str | None, dest_vid: str | None, expected: int | None) -> dict[str, Any]:
        tool = "presentation_template"
        if op in ("plan", "promote"):
            presentation_id = await self._presentation(tool, pid)
            variant_id = await self._variant(tool, presentation_id, vid)
            request = {k: v for k, v in dict(plan or {}).items() if v is not None}
            # Remotion Slice 19 (QA B1): a licence acknowledgement and the keeping of assets are the USER's own acts, never the brain's,
            # whatever the plan says; and a promotion only follows a request of the user (the attested turn, as for a presentation start).
            owned = sorted(k for k in ("licence_ack", "keep_assets") if k in request)
            if owned:
                raise self._refuse(tool, "presentation_studio_template_user_only",
                                   f"{' et '.join(owned)} : l'utilisateur seul reconnaît une licence ou garde des médias (depuis la page) ; dis-lui ce que le plan montre.")
            if op == "promote" and not await self._addressed_user_turn():
                raise self._refuse(tool, "presentation_studio_template_user_only",
                                   "promote : seulement sur une demande de l'utilisateur dans ce tour ; le plan reste permis.")
            request["actor"] = BRAIN_ACTOR
            if op == "plan":
                result = await self._c(lambda c: c.presentation_studio_template_plan(presentation_id, variant_id, request))
                return self._ok(status="planned", plan=self._template_plan_view(result), presentation_id=presentation_id, variant_id=variant_id)
            result = await self._c(lambda c: c.presentation_studio_template_promote(presentation_id, variant_id, request))
            library = result.get("published_to_library") is True   # Remotion Slice 19: a whole presentation is ONE record, nothing goes to the library
            return self._ok("say", say="Le modèle est publié dans la bibliothèque." if library
                            else "Le modèle est enregistré ; aucune scène n'est publiée dans la bibliothèque.",
                            status="promoted", template_id=result.get("template_id"), published_to_library=library,
                            prefabs=capped([_drop_none({"id": p.get("id"), "version": p.get("version"), "published": p.get("published")})
                                            for p in result.get("prefabs") or [] if isinstance(p, Mapping)], 12),
                            findings=(result.get("findings") or [])[:6])
        if op == "instantiate":
            if not is_template_id(tid):
                raise self._refuse(tool, "invalid_id", "template_id mal formé : prends-le dans presentation_inspect (target templates).")
            request: dict[str, Any] = {"actor": BRAIN_ACTOR}
            if title is not None:
                request["title"] = title
            if pid is not None:
                request["presentation_id"] = await self._presentation(tool, pid)
                request["variant_id"] = await self._variant(tool, request["presentation_id"], dest_vid)
                request["expected_revision"] = expected if expected is not None else (await self._c(
                    lambda c: c.presentation_studio_variant(request["presentation_id"], request["variant_id"]))).get("revision")
            made = await self._c(lambda c: c.presentation_studio_template_instantiate(str(tid), request))
            return self._ok("say", say="Le modèle est instancié.", status="instantiated", presentation_id=made.get("presentation_id"),
                            variant_id=made.get("variant_id"), scene_ids=(made.get("scene_ids") or [])[:48],
                            art_direction_id=made.get("art_direction_id"), score_id=made.get("score_id"))
        raise self._refuse(tool, "unknown_op", f"op inconnue : {clip(op, 30)} (plan, promote, instantiate).")

    @staticmethod
    def _template_plan_view(plan: Mapping[str, Any]) -> dict[str, Any]:
        scenes = [_drop_none({"scene_id": s.get("scene_id"), "key": s.get("key"), "prefab_id": s.get("prefab_id"), "prefab_state": s.get("prefab_state"),
                              "controls": capped([_drop_none({"control_id": c.get("control_id"), "label": clip(c.get("label"), 40), "type": c.get("type"),
                                                             "eligible_dimension": c.get("eligible_dimension")})
                                                  for c in s.get("controls") or [] if isinstance(c, Mapping)], 16)})
                  for s in plan.get("scenes") or [] if isinstance(s, Mapping)]
        return _drop_none({"ok": plan.get("ok"), "kind": plan.get("kind"), "slug": plan.get("slug"), "selection_required": plan.get("selection_required"),
                           "scenes": capped(scenes, 24), "would_publish": plan.get("would_publish"), "findings": (plan.get("findings") or [])[:8],
                           "publishes_to_library": plan.get("publishes_to_library"),
                           "licences": {clip(str(k), 64): capped([str(w)[:12] for w in v], 8) for k, v in list((plan.get("licences") or {}).items())[:8]} or None,
                           "blocking": plan.get("blocking"), "untrusted": ["scenes.items.controls.items.label", "licences"]})

    # ------------------------------------------------------------------ rédaction (planificateur de la Slice 11)

    async def draft(self, op: str, *, brief: Mapping[str, Any] | None = None, draft: Mapping[str, Any] | None = None,
                    presentation_id: str | None = None, variant_id: str | None = None, activate: bool | None = None) -> dict[str, Any]:
        tool = {"check": "presentation_draft_check", "assemble": "presentation_draft_assemble", "finalize": "presentation_draft_finalize"}[op]

        async def body() -> dict[str, Any]:
            if op == "finalize":
                pid = await self._presentation(tool, presentation_id)
                vid = await self._variant(tool, pid, variant_id)
                request = _drop_none({"actor": BRAIN_ACTOR, "presentation_id": pid, "variant_id": vid, "activate": activate})
                result = await self._c(lambda c: c.presentation_studio_authoring_finalize(request))
            else:
                request = {"actor": BRAIN_ACTOR, "brief": dict(brief or {}), "draft": dict(draft or {})}
                call = (lambda c: c.presentation_studio_authoring_check(request)) if op == "check" else \
                       (lambda c: c.presentation_studio_authoring_assemble(request))
                result = await self._c(call)
            return self._draft_result(tool, op, result)

        return await self._run(tool, op, {"presentation_id": presentation_id}, body)

    def _draft_result(self, tool: str, op: str, result: Mapping[str, Any]) -> dict[str, Any]:
        status = result.get("status")
        report = result.get("report")
        if status == "refused" or (op == "check" and result.get("ok") is False):
            # Le rapport complet, tel quel : le modèle corrige tout en une fois (consigne du planificateur).
            return self._ok("silent", status="refused" if status == "refused" else "checked", ok_gate=False, report=report,
                            workflow=result.get("workflow"), note="Corrige tout ce qui est listé puis resoumets (3 tours au plus).")
        picked = {k: result.get(k) for k in ("presentation_id", "variant_ids", "scene_ids", "art_direction_id", "score_id", "provenance",
                                             "workflow", "candidates", "variant_id", "fallback") if k in result}
        say = None
        if op != "check":
            say = "La présentation est créée." if op == "assemble" else "La direction est adoptée comme présentation."
        return self._ok("say" if say else "silent", say=say, status=status, ok_gate=True if op == "check" else None, report=report, **picked)


__all__ = ["CoreCaller", "ControlCenterCaller", "EDIT_OPS", "OPERATION_EVENTS", "PresentationTools"]
