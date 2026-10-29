"""Rail permanent des presentations (refonte du display du mode presentation) : etat d'affichage, etat de travail, demandes d'ecran.

Trois choses, un seul module, **aucune ne touche au schema d'un document de presentation** :

1. **Masquee / archivee** (persistant). Un fichier `rail.json` a cote de `presentation.json` (`FilePresentationStudioStore.read_rail` /
   `write_rail`, ecriture atomique, balayage des temporaires deja couvert). Le manifeste (`schema_version` 3) ne bouge pas : pas
   d'etape `UPGRADES`, pas d'instantane `tests/schema` (ce n'est pas `jarvis.sqlite3`). Un fichier absent veut dire « visible, non
   archivee ». *Masquer* retire la presentation du rail (elle reste lisible, jouable, listee par `presentation_inspect`) ; *archiver* est
   la « suppression » restaurable : le dossier n'est JAMAIS supprime, la presentation sort du rail et refuse la lecture et l'ouverture
   tant qu'elle n'est pas restauree. Archiver exige la confirmation de l'utilisateur (`confirmed`) quand l'acteur est le cerveau.
2. **Etat de travail** (memoire seulement, jamais persiste : un etat de travail est un fait d'execution). `working` (bleu) tant qu'un
   agent edite, `done` (vert) quand il a fini ou que rien ne s'est passe, `problem` (orange) apres un echec, jusqu'a l'acquittement ou
   au prochain travail. Alimente par les outils MCP du cerveau (`/work`), par l'evenement `edit_committed` (prolonge un travail en
   cours) et par les echecs de l'API d'edition.
3. **Demandes d'ecran** (memoire seulement). Le cerveau demande « ouvre la fenetre de cette presentation », « masque le rail » : Core
   tient la derniere demande (numerotee) que la page lit a son rythme, et le miroir de ce que la page a rapporte.
4. **A revoir** (persistant, rail actif S07, D10). Cle additive optionnelle `unreviewed: {since, label}` de `rail.json` (le schema reste v1 :
   un Core plus ancien ignore la cle et la perd a sa prochaine ecriture, il degrade en « pas jaune »). Posee quand le cerveau rapporte un
   travail `success` ; effacee par l'action `review` (acteur `user` seulement : ouvrir depuis le rail, « Marquer comme vu »). Une ligne en
   `problem` ne la rapporte jamais (le probleme garde son traitement).
5. **Apercu** (memoire, borne). La ligne porte `preview` = le plus recent `presentation_still` `complete` rendu d'un snapshot de cette
   presentation, a defaut sa plus recente `presentation_video` `complete` (la page en montre la premiere image, 2026-10-29)
   (`{artifact_id, kind, width, height}`, lu par `/api/artifacts/{id}/payload`, jamais un chemin), ou `null`, et `type: {engine}`.

Contrat : `docs/presentation-studio.md` > *Rail des presentations*.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import json
import time
from typing import Any

from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, ArtifactKind, ArtifactQuery, ArtifactRelationKind, ArtifactState
from jarvis.domain.presentation_artifacts import SourceProvenance
from jarvis.domain.presentation_studio import PresentationStudioError, is_presentation_id, stamp
from jarvis.domain.presentation_studio_checks import PresentationStudioErrorCode as C, clip
from jarvis.ports.artifacts import RelationDirection

RAIL_SCHEMA = "jarvis.presentation_studio.rail"
RAIL_SCHEMA_VERSION = 1
ACTORS = ("user", "brain")
ACTIONS = ("hide", "show", "archive", "restore", "rename", "acknowledge", "review")

WORKING, DONE, PROBLEM = "working", "done", "problem"
WORK_EVENTS = ("begin", "success", "failure", "ack")
#: Un travail annonce sans nouvelle d'un agent redevient « termine » apres ce delai (l'agent a fini, ou s'est tu).
WORK_TTL_S = 90.0
#: Apres un succes, le bleu reste ce temps : l'agent enchaine souvent l'edition suivante.
SETTLE_S = 20.0
MAX_TRACKED = 256
MAX_LABEL = 40
MAX_MESSAGE = 160

#: Screen requests of the brain. `open_window` / `close_window` are retired with the floating window host (native-studio-playback-fix
#: Slice 09): `presentation_view window_open|close` now opens or closes Variants through its own command channel, with a receipt.
UI_ACTIONS = ("show_rail", "hide_rail")
#: Une demande d'ecran plus vieille que cela n'est plus appliquee par une page qui vient de s'ouvrir.
UI_REQUEST_FRESH_S = 30.0
#: Apercus : les N `presentation_still` complets les plus recents sont lus en UNE requete par lecture du rail ; au plus
#: `PREVIEW_RESOLVES` lignees nouvelles (still -> snapshot -> presentation) resolues par lecture ; lignees gardees (immuables) dans un
#: cache LRU de `PREVIEW_LINEAGE_MAX` entrees. La carte n'est recalculee que si l'ensemble des stills recents change.
PREVIEW_SCAN = 64
PREVIEW_RESOLVES = 16
PREVIEW_LINEAGE_MAX = 512


@dataclass(frozen=True, slots=True)
class RailFlags:
    hidden: bool = False
    archived: bool = False
    hidden_at: str | None = None
    archived_at: str | None = None
    #: `{since, label}` : travail du cerveau termine que l'utilisateur n'a pas encore revu (cle additive, schema v1).
    unreviewed: Mapping[str, str] | None = None

    def to_document(self) -> dict[str, Any]:
        document = {"schema": RAIL_SCHEMA, "schema_version": RAIL_SCHEMA_VERSION, "hidden": self.hidden, "archived": self.archived,
                    "hidden_at": self.hidden_at, "archived_at": self.archived_at}
        if self.unreviewed is not None:
            document["unreviewed"] = dict(self.unreviewed)
        return document


def parse_rail(text: str) -> RailFlags:
    """`rail.json`. Vide : les valeurs par defaut. Plus recent que ce Core, ou illisible : refuse, jamais devine."""

    if not text.strip():
        return RailFlags()
    try:
        data = json.loads(text)
    except ValueError:
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, "rail.json: not JSON") from None
    if not isinstance(data, dict) or data.get("schema") != RAIL_SCHEMA:
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, "rail.json: not a rail document")
    version = data.get("schema_version")
    if type(version) is not int or version < 1:
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, "rail.json: bad schema_version")
    if version > RAIL_SCHEMA_VERSION:
        raise PresentationStudioError(C.UNSUPPORTED_SCHEMA_VERSION, "rail.json is newer than this JARVIS reads")
    hidden, archived = data.get("hidden"), data.get("archived")
    if type(hidden) is not bool or type(archived) is not bool:
        raise PresentationStudioError(C.CORRUPT_DOCUMENT, "rail.json: hidden and archived must be booleans")
    return RailFlags(hidden, archived, _when(data.get("hidden_at")), _when(data.get("archived_at")), _unreviewed(data.get("unreviewed")))


def _unreviewed(value: object) -> dict[str, str] | None:
    """Cle optionnelle : absente ou mal formee = « rien a revoir » (jamais une erreur : un rail lisible ne devient pas illisible pour elle)."""

    since = _when(value.get("since")) if isinstance(value, dict) else None
    if since is None:
        return None
    label = value.get("label")
    return {"since": since, "label": clip(label, MAX_LABEL) if isinstance(label, str) else ""}


def _when(value: object) -> str | None:
    return value[:40] if isinstance(value, str) and value else None


@dataclass(slots=True)
class _Work:
    state: str = DONE
    label: str = ""
    code: str | None = None
    message: str | None = None
    deadline: float = 0.0
    since: float = 0.0
    touched: float = 0.0


class PresentationWorkTracker:
    """Etat de travail par presentation, en memoire. Horloge monotone injectable (les tests ne dorment pas)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, ttl_s: float = WORK_TTL_S, settle_s: float = SETTLE_S) -> None:
        self._clock, self._ttl, self._settle = clock, ttl_s, settle_s
        self._rows: dict[str, _Work] = {}
        #: Compteur de changements : la page ne repeint que si le chiffre bouge.
        self.revision = 0

    def report(self, presentation_id: str, event: str, *, label: str | None = None, code: str | None = None,
               message: str | None = None) -> dict[str, Any]:
        if event not in WORK_EVENTS:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "event must be " + ", ".join(WORK_EVENTS))
        now = self._clock()
        row = self._rows.get(presentation_id)
        if row is None:
            if len(self._rows) >= MAX_TRACKED:
                self._rows.pop(next(iter(self._rows)))
            row = self._rows[presentation_id] = _Work(since=now)
        before = self._effective(row, now)
        if event == "begin":
            row.state, row.code, row.message = WORKING, None, None
            row.deadline, row.since = now + self._ttl, now if before != WORKING else row.since
        elif event == "success":
            if row.state == PROBLEM:
                row.state, row.code, row.message = WORKING, None, None  # a later success supersedes an old problem
            if row.state != WORKING:
                row.state, row.since = WORKING, now
            row.deadline = now + self._settle
        elif event == "failure":
            row.state, row.code, row.message = PROBLEM, (clip(code, MAX_LABEL) if code else None), (clip(message, MAX_MESSAGE) if message else None)
            row.since = now
        else:  # ack
            if row.state == PROBLEM:
                row.state, row.code, row.message = DONE, None, None
                row.since = now
        if label:
            row.label = clip(label, MAX_LABEL)
        row.touched = now
        if self._effective(row, now) != before or event in ("failure", "begin"):
            self.revision += 1
        return self.snapshot(presentation_id)

    def touch(self, presentation_id: str) -> None:
        """Un commit d'edition prolonge un travail EN COURS ; il n'en declenche jamais un (l'edition de l'utilisateur n'est pas du travail d'agent)."""

        row = self._rows.get(presentation_id)
        now = self._clock()
        if row is not None and self._effective(row, now) == WORKING:
            row.deadline = max(row.deadline, now + self._settle)
            row.touched = now

    def fail(self, presentation_id: str, code: str, message: str | None = None) -> None:
        self.report(presentation_id, "failure", code=code, message=message)

    def _effective(self, row: _Work, now: float) -> str:
        if row.state == WORKING and now >= row.deadline:
            return DONE
        return row.state

    def snapshot(self, presentation_id: str) -> dict[str, Any]:
        row = self._rows.get(presentation_id)
        if row is None:
            return {"state": DONE, "label": "", "age_s": None}
        now = self._clock()
        state = self._effective(row, now)
        if state != row.state:  # the window ran out: settle for good, once
            row.state = state
            row.since = row.deadline
            self.revision += 1
        out: dict[str, Any] = {"state": state, "label": row.label, "age_s": round(max(0.0, now - row.since), 1)}
        if state == PROBLEM:
            out.update(code=row.code, message=row.message)
        return out

    def forget(self, presentation_id: str) -> None:
        self._rows.pop(presentation_id, None)


@dataclass(slots=True)
class _Display:
    seq: int = 0
    action: str | None = None
    presentation_id: str | None = None
    at: float = 0.0
    reported: dict[str, Any] = field(default_factory=dict)
    reported_at: float | None = None


class PresentationRail:
    """Le rail vu par Core : liste + drapeaux persistants + etat de travail + demandes d'ecran."""

    def __init__(self, studio: PresentationStudioService, *, tracker: PresentationWorkTracker | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._studio = studio
        self.tracker = tracker or PresentationWorkTracker(clock=clock)
        self._clock = clock
        self._display = _Display()
        self._playback: Any = None
        self._artifacts: Any = None
        #: still artifact_id -> presentation_id ("" = lignee illisible) ; immuable une fois ecrite, donc cachable sans expiration.
        self._lineage: OrderedDict[str, str] = OrderedDict()
        self._preview_key: tuple[str, ...] | None = None
        self._preview_map: dict[str, dict[str, Any]] = {}

    def bind_playback(self, playback: Any) -> None:
        self._playback = playback

    def bind_artifacts(self, artifacts: Any) -> None:
        """Registre d'Artifacts (`ArtifactService`) : source des apercus. Absent : `preview` vaut toujours `null`."""

        self._artifacts = artifacts

    # ------------------------------------------------------------ lecture

    async def overview(self) -> dict[str, Any]:
        """Toutes les presentations (masquees et archivees comprises, drapeaux a l'appui) : la page range, l'agent lit."""

        listing = await self._studio.list_presentations()
        rows: list[dict[str, Any]] = []
        problems: list[dict[str, str]] = [dict(p) for p in listing.problems]
        previews = await self.previews()
        for summary in listing.presentations:
            pid = summary["presentation_id"]
            try:
                flags = await self._flags(pid)
            except PresentationStudioError as exc:
                flags = RailFlags()
                problems.append({"presentation_id": pid, "code": exc.code.value, "message": exc.message})
            work = self.tracker.snapshot(pid)
            rows.append({**summary, "hidden": flags.hidden, "archived": flags.archived, "work": work,
                         # a problem keeps its own treatment: never reported as "to review" (D10 precedence)
                         "unreviewed": None if work["state"] == PROBLEM or flags.unreviewed is None else dict(flags.unreviewed),
                         "preview": previews.get(pid), "type": {"engine": summary.get("engine")}})
        # newest first inside each group; groups: visible, hidden, archived (stable sorts)
        rows.sort(key=lambda r: (r["updated_at"], r["presentation_id"]), reverse=True)
        rows.sort(key=lambda r: (r["archived"], r["hidden"]))
        return {"presentations": rows, "problems": problems[:8], "work_revision": self.tracker.revision, "ui": self.ui_view(),
                "playing": self._playing_id()}

    async def _flags(self, presentation_id: str) -> RailFlags:
        text = await self._studio.run_blocking("read_rail", presentation_id, self._studio.store.read_rail, presentation_id)
        return parse_rail(text)

    async def previews(self) -> dict[str, dict[str, Any]]:
        """`presentation_id -> {artifact_id, kind, width, height}` : le plus recent still complet de chaque presentation, a defaut sa
        plus recente video complete (la page en tire la premiere image : retour utilisateur du 2026-10-29). Borne (voir
        `PREVIEW_*`), jamais un chemin. Un registre en echec garde la derniere carte connue (l'apercu se replie sinon sur la vignette typee)
        et se dit au journal."""

        if self._artifacts is None:
            return {}
        try:
            page = await self._artifacts.query(ArtifactQuery(kinds=(ArtifactKind.PRESENTATION_STILL, ArtifactKind.PRESENTATION_VIDEO),
                                                             states=(ArtifactState.COMPLETE,), limit=PREVIEW_SCAN))
        except Exception as exc:  # noqa: BLE001 - capture: a failing registry costs the previews (traced), never the rail itself
            self._studio.trace("core.presentation_studio.rail_preview_unavailable", "Apercus du rail indisponibles", level="warning",
                               data={"error": type(exc).__name__, "message": str(exc)[:160]})
            return dict(self._preview_map)
        key = tuple(a.artifact_id for a in page.items)
        if key == self._preview_key:
            return dict(self._preview_map)
        found: dict[str, dict[str, Any]] = {}
        videos: dict[str, dict[str, Any]] = {}
        resolves, complete = 0, True
        for still in page.items:  # newest first
            owner = self._lineage.get(still.artifact_id)
            if owner is None:
                if resolves >= PREVIEW_RESOLVES:
                    complete = False
                    continue
                resolves += 1
                try:
                    owner = await self._owner_of(still)
                except Exception as exc:  # noqa: BLE001 - capture: a transient read error is traced, not cached, retried next read
                    self._studio.trace("core.presentation_studio.rail_preview_unavailable", "Apercu du rail indisponible", level="warning",
                                       data={"artifact_id": still.artifact_id, "error": type(exc).__name__, "message": str(exc)[:160]})
                    complete = False
                    continue
                self._lineage[still.artifact_id] = owner
                while len(self._lineage) > PREVIEW_LINEAGE_MAX:
                    self._lineage.popitem(last=False)
            else:
                self._lineage.move_to_end(still.artifact_id)
            shelf = found if still.kind is ArtifactKind.PRESENTATION_STILL else videos
            if owner and owner not in shelf:
                shelf[owner] = {"artifact_id": still.artifact_id, "kind": still.kind.value, "width": still.width, "height": still.height}
        found = {**videos, **found}  # a still always wins over a video of the same presentation
        self._preview_map = found
        self._preview_key = key if complete else None  # an unfinished resolve is finished by the next read
        return dict(found)

    async def _owner_of(self, still: Artifact) -> str:
        """Presentation d'un still : son origine `rendered_from` (un snapshot), dont la provenance nomme la source. Illisible : "" (signale)."""

        try:
            origins = await self._artifacts.relations(still.artifact_id, RelationDirection.ORIGINS)
            origin = next((r.origin_artifact_id for r in origins if r.relation is ArtifactRelationKind.RENDERED_FROM), None)
            if origin is None:
                raise ArtifactError(ArtifactErrorCode.INVALID_RELATION, f"still {still.artifact_id} has no rendered_from origin")
            return SourceProvenance.of_snapshot(await self._artifacts.get(origin)).presentation_id
        except ArtifactError as exc:
            self._studio.trace("core.presentation_studio.rail_preview_lineage", "Lignee d'apercu illisible", level="warning",
                               data={"artifact_id": still.artifact_id, "code": exc.code.value})
            return ""

    def _playing_id(self) -> str | None:
        running = None if self._playback is None else self._playback.running_variant()
        return running[0] if running else None

    # ------------------------------------------------------------ ecriture (persistante)

    async def act(self, presentation_id: str, raw: object) -> dict[str, Any]:
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation")
        body = self._body(raw)
        action, actor = body["action"], body["actor"]
        if action == "acknowledge":
            return {"presentation_id": presentation_id, "work": self.tracker.report(presentation_id, "ack")}
        if action == "review":
            if actor != "user":
                raise PresentationStudioError(C.INVALID_PRESENTATION, "review is the user's gesture: only actor user marks a presentation as seen")
            return await self._review(presentation_id)
        if action == "rename":
            return await self._rename(presentation_id, body)
        if action == "archive":
            if actor == "brain" and body.get("confirmed") is not True:
                raise PresentationStudioError(C.CONFIRMATION_REQUIRED,
                                              "archiving a presentation needs the user's yes: ask first, then pass confirmed=true")
            if self._playing_id() == presentation_id:
                raise PresentationStudioError(C.VARIANT_IN_PLAYBACK, "this presentation is being played: stop the playback first")
        async with self._studio.exclusive():
            await self._studio.load_presentation_locked(presentation_id)  # unknown presentation -> 404, nothing written
            current = await self._flags(presentation_id)
            now = stamp(self._studio.now())
            changed = {"hide": not current.hidden, "show": current.hidden, "archive": not current.archived,
                       "restore": current.archived}[action]
            flags = current
            if action == "hide":
                flags = replace(current, hidden=True, hidden_at=now)
            elif action == "show":
                flags = replace(current, hidden=False, hidden_at=None)
            elif action == "archive":
                flags = replace(current, archived=True, archived_at=now)
            elif action == "restore":
                flags = replace(current, archived=False, archived_at=None)
            if changed:
                await self._write(presentation_id, flags)
        self._studio.trace("core.presentation_studio.rail_changed", "Etat d'affichage du rail change",
                           data={"presentation_id": presentation_id, "action": action, "actor": actor, "changed": changed})
        return {"presentation_id": presentation_id, "action": action, "changed": changed, "hidden": flags.hidden,
                "archived": flags.archived, "restorable": flags.archived}

    async def _write(self, presentation_id: str, flags: RailFlags) -> None:
        await self._studio.run_blocking("write_rail", presentation_id, self._studio.store.write_rail, presentation_id,
                                        json.dumps(flags.to_document(), ensure_ascii=False, indent=2) + "\n")

    async def _review(self, presentation_id: str) -> dict[str, Any]:
        async with self._studio.exclusive():
            await self._studio.load_presentation_locked(presentation_id)
            current = await self._flags(presentation_id)
            changed = current.unreviewed is not None
            if changed:
                await self._write(presentation_id, replace(current, unreviewed=None))
        self.tracker.revision += int(changed)
        self._studio.trace("core.presentation_studio.rail_changed", "Etat d'affichage du rail change",
                           data={"presentation_id": presentation_id, "action": "review", "actor": "user", "changed": changed})
        return {"presentation_id": presentation_id, "action": "review", "changed": changed, "hidden": current.hidden,
                "archived": current.archived, "restorable": current.archived, "unreviewed": None}

    async def _mark_unreviewed(self, presentation_id: str, label: str | None) -> None:
        """Le cerveau a fini un travail : jaune jusqu'a ce que l'utilisateur le revoie. Deja marque : rien n'est reecrit (le `since` reste le
        premier travail non revu). Appele sous le verrou exclusif."""

        current = await self._flags(presentation_id)
        if current.unreviewed is not None:
            return
        mark = {"since": stamp(self._studio.now()), "label": clip(label, MAX_LABEL) if label else ""}
        await self._write(presentation_id, replace(current, unreviewed=mark))
        self.tracker.revision += 1
        self._studio.trace("core.presentation_studio.rail_unreviewed", "Travail du cerveau a revoir",
                           data={"presentation_id": presentation_id, "label": mark["label"]})

    async def _rename(self, presentation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        title = body.get("title")
        if not isinstance(title, str):
            raise PresentationStudioError(C.INVALID_PRESENTATION, "rename needs a title")
        title = " ".join(title.split())
        async with self._studio.exclusive():
            current = await self._studio.load_presentation_locked(presentation_id)
        if title == current.title:
            return {"presentation_id": presentation_id, "action": "rename", "changed": False, "title": current.title, "revision": current.revision}
        document = current.to_document()
        saved = await self._studio.save_presentation(presentation_id, {
            "expected_revision": current.revision, "title": title, "active_variant_id": current.active_variant_id,
            "resources": document.get("resources", [])})
        return {"presentation_id": presentation_id, "action": "rename", "changed": True, "title": saved.title, "revision": saved.revision}

    @staticmethod
    def _body(raw: object) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise PresentationStudioError(C.INVALID_PRESENTATION, "body must be a JSON object")
        unknown = set(raw) - {"action", "actor", "confirmed", "title"}
        if unknown:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "unknown key: " + ", ".join(sorted(map(str, unknown))))
        if raw.get("action") not in ACTIONS:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "action must be " + ", ".join(ACTIONS))
        actor = raw.get("actor", "user")
        if actor not in ACTORS:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "actor must be user or brain")
        if "confirmed" in raw and type(raw["confirmed"]) is not bool:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "confirmed must be a boolean")
        return {**raw, "actor": actor}

    # ------------------------------------------------------------ etat de travail (memoire)

    async def report_work(self, presentation_id: str, raw: object) -> dict[str, Any]:
        if not is_presentation_id(presentation_id):
            raise PresentationStudioError(C.UNKNOWN_PRESENTATION, "unknown presentation")
        if not isinstance(raw, dict) or set(raw) - {"event", "label", "code", "message"}:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "body: {event, label?, code?, message?}")
        for key in ("label", "code", "message"):
            if key in raw and not isinstance(raw[key], str):
                raise PresentationStudioError(C.INVALID_PRESENTATION, f"{key} must be a string")
        event = str(raw.get("event"))
        async with self._studio.exclusive():
            await self._studio.load_presentation_locked(presentation_id)
            work = self.tracker.report(presentation_id, event, label=raw.get("label"), code=raw.get("code"), message=raw.get("message"))
            if event == "success":
                try:
                    await self._mark_unreviewed(presentation_id, raw.get("label"))
                except PresentationStudioError as exc:  # unreadable rail.json: the work state stands, the yellow is lost and said
                    self._studio.trace("core.presentation_studio.rail_unreviewed_failed", "Marque « a revoir » non ecrite", level="warning",
                                       data={"presentation_id": presentation_id, "code": exc.code.value, "message": exc.message})
        return {"presentation_id": presentation_id, "work": work}

    def forget(self, presentation_id: str) -> None:
        """Purge definitive (`core/presentation_studio_purge.py`) : l'etat de travail, l'apercu et une demande d'ecran qui nommaient
        la presentation effacee sont oublies."""

        self.tracker.forget(presentation_id)
        self.tracker.revision += 1
        self._preview_map.pop(presentation_id, None)
        self._preview_key = None
        if self._display.presentation_id == presentation_id:
            self._display.presentation_id = None

    def on_edit_committed(self, presentation_id: str) -> None:
        self.tracker.touch(presentation_id)

    def on_edit_failed(self, presentation_id: str, code: str) -> None:
        self.tracker.fail(presentation_id, code)

    # ------------------------------------------------------------ demandes d'ecran (memoire)

    def request_ui(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) - {"action", "presentation_id"}:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "body: {action, presentation_id?}")
        action = raw.get("action")
        if action not in UI_ACTIONS:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "action must be " + ", ".join(UI_ACTIONS))
        pid = raw.get("presentation_id")
        if pid is not None and not is_presentation_id(pid):
            raise PresentationStudioError(C.INVALID_PRESENTATION, "presentation_id is malformed")
        self._display.seq += 1
        self._display.action, self._display.presentation_id, self._display.at = action, pid, self._clock()
        return self.ui_view()

    def report_ui(self, raw: object) -> dict[str, Any]:
        """Ce que la page constate : rail visible ? Variantes ouvert, sur quelle presentation ? (consultatif, date ; Slice 09 : `variants_open`
        remplace `window_open`, la fenetre de presentation est retiree)."""

        allowed = {"rail_visible", "variants_open", "presentation_id", "applied_seq"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise PresentationStudioError(C.INVALID_PRESENTATION, "body: {rail_visible, variants_open, presentation_id, applied_seq?}")
        pid = raw.get("presentation_id")
        if pid is not None and not is_presentation_id(pid):
            raise PresentationStudioError(C.INVALID_PRESENTATION, "presentation_id is malformed")
        for key in ("rail_visible", "variants_open"):
            if type(raw.get(key)) is not bool:
                raise PresentationStudioError(C.INVALID_PRESENTATION, f"{key} must be a boolean")
        self._display.reported = {"rail_visible": raw["rail_visible"], "variants_open": raw["variants_open"], "presentation_id": pid,
                                  "applied_seq": raw.get("applied_seq") if type(raw.get("applied_seq")) is int else None}
        self._display.reported_at = self._clock()
        return self.ui_view()

    def ui_view(self) -> dict[str, Any]:
        d, now = self._display, self._clock()
        request = None if d.action is None else {"seq": d.seq, "action": d.action, "presentation_id": d.presentation_id,
                                                 "age_s": round(max(0.0, now - d.at), 1), "fresh": now - d.at <= UI_REQUEST_FRESH_S}
        reported = None if d.reported_at is None else {**d.reported, "reported_s_ago": round(max(0.0, now - d.reported_at), 1)}
        return {"seq": d.seq, "request": request, "reported": reported}
