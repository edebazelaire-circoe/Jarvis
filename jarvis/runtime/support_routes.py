"""« Signaler un problème », côté Control Center (V1.2 Slice 07, `docs/support-report.md`).

Le Control Center relève ce que lui seul connaît (Board actif chez Core, rapport de préparation, réglages, modèle
configuré), le remet au service du paquet (`support_bundle.collect_bundle`, mode complet), fait écrire `report.md`
(`support_report.generate_report`) puis le zip, et exécute les actes EXPLICITES de l'utilisateur.

| Route | Effet |
| --- | --- |
| `GET /api/support/preview` | aperçu sans effet de bord : catégories incluses, masquées, exclues, omises ; taille approximative ; Board actif ; destination et transport ; paquets déjà prêts |
| `POST /api/support/reports` | `{description, consent: true}` → crée le paquet (consentement exigé : 400 `support_consent_required`) |
| `POST /api/support/reports/{name}/send` | envoi vers la destination configurée (`support_send`) ; un échec garde le zip (502, code nommé) |
| `POST /api/support/reports/{name}/save` | copie dans `Documents\\Jarvis` (`ExportDestination`, sans écrasement) |
| `GET /api/support/reports/{name}/download` | le zip, en pièce jointe : « Télécharger… » choisit l'emplacement dans le navigateur |
| `POST /api/support/destination` | `{support_email}` : remplace la destination dans les réglages (vide : retour au défaut) |

Erreurs : `{"error": {code, message, detail}}` ; chaque échec va au journal (`support.report.*`, niveau `error`), le
chemin normal aussi (`info`). Une seule création à la fois (409 `support_report_busy`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
import zipfile

from aiohttp import web

from jarvis.runtime import support_bundle as SB
from jarvis.runtime import support_send as SS
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.support_report import AI_TIMEOUT_S, generate_report
from jarvis.runtime.support_snapshot import MAX_DATABASE_BYTES, MEMORY_BUDGET_BYTES, SnapshotError, memory_root

#: Échéances : lecture de Core pour l'aperçu, rapport de préparation, remise à la messagerie.
CORE_READ_TIMEOUT_S = 3.0
HEALTH_TIMEOUT_S = 12.0
SEND_TIMEOUT_S = 30.0
#: Paquets récents montrés dans l'aperçu.
RECENT_SHOWN = 5


class SupportRouteError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.status, self.code, self.detail = status, code, detail


def _error(status: int, code: str, message: str, detail: str = "") -> web.Response:
    return web.json_response({"error": {"code": code, "message": message, "detail": detail}}, status=status)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


class SupportReportService:
    """Aperçu, création, envoi, enregistrement. Une instance par Control Center ; tout est injectable (tests)."""

    def __init__(self, *, runtime_root: Path, journal: RuntimeJournal, settings: Callable[[], Mapping[str, Any]],
                 update_settings: Callable[[Callable[[dict[str, Any]], None]], None] | None = None,
                 active_board: Callable[[], Awaitable[Mapping[str, Any] | None]] | None = None,
                 health: Callable[[], Awaitable[Mapping[str, Any]]] | None = None,
                 model_factory: Callable[[Path], tuple[Any, str | None]] | None = None,
                 transport: SS.SupportTransport | None = None,
                 sources_factory: Callable[[], SB.BundleSources] | None = None,
                 export_destination: Callable[[], Any] | None = None,
                 environ: Mapping[str, str] | None = None) -> None:
        self._runtime_root = Path(runtime_root)
        self._journal = journal
        self._settings = settings
        self._update_settings = update_settings
        self._active_board = active_board
        self._health = health
        self._model_factory = model_factory
        self._environ = os.environ if environ is None else environ
        self._transport = transport or SS.transport_from_environment(self._environ, runtime_root=self._runtime_root)
        self._sources_factory = sources_factory or (lambda: SB.sources_from_environment(self._environ))
        self._export_destination = export_destination
        self._busy: asyncio.Lock = asyncio.Lock()
        self._started: float | None = None
        #: Envois en cours par paquet : un second « Envoyer » pendant qu'une messagerie attend est refusé (QA S07 m3).
        self._sending: dict[str, asyncio.Future] = {}
        swept = SB.sweep_work_folders(self.support_dir)  # raw base copies left by a hard stop (QA S07 m4)
        if swept:
            self._emit("support.report.work_swept", f"{len(swept)} dossier(s) de travail orphelin(s) retiré(s)",
                       count=len(swept))

    @property
    def support_dir(self) -> Path:
        return self._runtime_root / SB.SUPPORT_DIR

    def destination(self) -> str:
        return SS.resolve_destination(self._settings(), self._environ)

    def _emit(self, kind: str, message: str, *, level: str = "info", **data: Any) -> None:
        self._journal.emit(kind, message, level=level, data={key: value for key, value in data.items() if value is not None})

    # ------------------------------------------------------------ lectures

    async def _board(self) -> dict[str, Any] | None:
        if self._active_board is None:
            return None
        try:
            board = await asyncio.wait_for(self._active_board(), timeout=CORE_READ_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - captured: the bundle then reads the active board from the state base
            self._emit("support.report.board_unknown", f"Board actif illisible chez Core : {type(exc).__name__}",
                       level="warning", code="support_board_unknown", error_type=type(exc).__name__)
            return None
        if not isinstance(board, Mapping) or not isinstance(board.get("board_id"), str):
            return None
        return {key: board[key] for key in ("board_id", "title", "board_kind") if isinstance(board.get(key), str)}

    def _recent(self) -> list[dict[str, Any]]:
        try:
            names = sorted((p for p in self.support_dir.iterdir() if SB.BUNDLE_NAME.fullmatch(p.name)), reverse=True)
        except OSError:
            return []  # intentional: no support folder yet
        return [{"name": p.name, "bytes": _size(p)} for p in names[:RECENT_SHOWN]]

    async def preview(self) -> dict[str, Any]:
        """Ce que le paquet contiendra, sans rien écrire."""

        board = await self._board()
        sources = self._sources_factory()

        def sizes() -> dict[str, Any]:
            databases = {}
            for relative in SB.DATABASES:
                path = sources.data_root / relative
                total = _size(path) + _size(path.with_name(path.name + "-wal"))
                databases[relative] = {"bytes": total, "included": 0 < total <= MAX_DATABASE_BYTES}
            memory_bytes, memory_state = 0, "absent"
            board_id = (board or {}).get("board_id")
            if board_id:
                try:
                    root = memory_root(sources.data_root, board_id)
                    memory_bytes = sum(os.path.getsize(os.path.join(folder, name))
                                       for folder, _dirs, names in os.walk(root, followlinks=False) for name in names)
                    memory_state = "included"
                except SnapshotError as exc:
                    memory_state = str(exc)
                except OSError as exc:
                    memory_state = f"unreadable:{type(exc).__name__}"
            # Bounded tails: each log, the error journal and the trace are cut at `MAX_FILE_BYTES` in the bundle.
            logs = sum(min(_size(path), SB.MAX_FILE_BYTES) for path in (
                *(sources.runtime_root / "logs" / f"{role}.log" for role in SB.LOG_ROLES),
                sources.runtime_root / "errors.jsonl", sources.runtime_root / "trace.jsonl"))
            return {"databases": databases, "memory": (memory_bytes, memory_state), "logs": logs}

        found = await asyncio.to_thread(sizes)
        db_bytes = sum(item["bytes"] for item in found["databases"].values() if item["included"])
        memory_bytes, memory_state = found["memory"]
        logs_bytes = found["logs"]
        approx = db_bytes + min(memory_bytes, MEMORY_BUDGET_BYTES) + logs_bytes
        included = [
            {"id": "report", "label": "Rapport de diagnostic (report.md) et manifeste", "masked": True},
            {"id": "logs", "label": "Journaux et erreurs récentes", "masked": True, "bytes": logs_bytes},
            {"id": "state_databases", "label": "Bases d'état (conversations récentes, Boards, missions)", "masked": True,
             "bytes": db_bytes},
            {"id": "board_memory", "label": "Mémoire du Board actif (fichiers texte)", "masked": True,
             "bytes": memory_bytes, "state": memory_state},
            {"id": "settings", "label": "Réglages, sans aucune clé", "masked": True},
            {"id": "health", "label": "Version, système et état de préparation", "masked": True},
        ]
        excluded = [{"id": name, "label": label} for name, label in (
            ("credential_vault", "Coffre des identifiants et clés d'API"),
            ("tokens", "Jetons et mots de passe (masqués partout)"),
            ("media", "Présentations, rendus et médias lourds"),
            ("runtimes", "Runtimes privés, caches et sauvegardes"),
            ("other_boards", "Autres Boards et contexte global"))]
        return {"destination": self.destination(), "default_destination": SS.DEFAULT_SUPPORT_EMAIL,
                "transport": SS.describe_transport(self._transport), "active_board": board,
                "included": included, "excluded": excluded, "approx_bytes": approx,
                "send_limit_bytes": SS.MAX_SEND_BYTES,
                "retention": {"keep": SB.KEEP_BUNDLES, "max_age_days": SB.MAX_BUNDLE_AGE_S // 86400},
                "recent": self._recent(), "busy": self._busy.locked(),
                "busy_elapsed_s": round(time.monotonic() - self._started, 1) if self._started and self._busy.locked() else None}

    # ------------------------------------------------------------ création

    async def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if payload.get("consent") is not True:
            raise SupportRouteError(400, "support_consent_required",
                                    "Cochez la case de consentement avant de créer le paquet.")
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise SupportRouteError(400, "invalid_request", "Description illisible.", "description must be text")
        if self._busy.locked():
            raise SupportRouteError(409, "support_report_busy", "Un paquet est déjà en cours de préparation.")
        async with self._busy:
            self._started = time.monotonic()
            try:
                return await self._create(str(description or ""))
            finally:
                self._started = None

    async def _create(self, description: str) -> dict[str, Any]:
        started = time.monotonic()
        SB.sweep_work_folders(self.support_dir)  # under the creation lock: no other creation is using one
        self._emit("support.report.started", "Rapport de problème demandé", has_description=bool(description.strip()))
        board = await self._board()
        health = None
        if self._health is not None:
            try:
                health = dict(await asyncio.wait_for(self._health(), timeout=HEALTH_TIMEOUT_S))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - captured: the health part is omitted and the manifest says it
                self._emit("support.report.health_unavailable", f"État de préparation illisible : {type(exc).__name__}",
                           level="warning", code="support_health_unavailable", error_type=type(exc).__name__)
        sources = self._sources_factory()
        sources.full, sources.description, sources.active_board, sources.health = True, description, board, health
        try:
            self.support_dir.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix=".work-", dir=self.support_dir))
        except OSError as exc:
            raise self._failed("support_folder_unavailable", "Le dossier de support n'a pas pu être préparé.", exc) from exc
        try:
            try:
                collected = await asyncio.to_thread(SB.collect_bundle, sources, work)
            except OSError as exc:
                raise self._failed("support_collect_failed", "La collecte du diagnostic a échoué.", exc) from exc
            model, label = (None, None)
            if self._model_factory is not None:
                cli_dir = work / "model"
                cli_dir.mkdir(exist_ok=True)
                try:
                    model, label = self._model_factory(cli_dir)
                except Exception as exc:  # noqa: BLE001 - captured: no model means the factual report, said in it
                    self._emit("support.report.model_unavailable", f"Modèle indisponible : {type(exc).__name__}: {exc}",
                               level="warning", code="support_model_unavailable", error_type=type(exc).__name__)
            result = await generate_report(collected.evidence, model, redact=collected.redact, timeout_s=AI_TIMEOUT_S,
                                           model_label=label)
            try:
                path = await asyncio.to_thread(SB.write_archive, self.support_dir, collected, result.text,
                                               report_kind=result.kind, report_meta=result.meta)
            except OSError as exc:
                raise self._failed("support_write_failed", "Le paquet n'a pas pu être écrit.", exc) from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)
        removed = SB.prune_support_folder(self.support_dir, protect=path)
        size = _size(path)
        omitted = [e.to_dict() for e in collected.manifest if e.status in ("omitted", "refused") and not e.path.startswith("data/")]
        if result.kind != "ai":
            self._emit("support.report.ai_failed", f"Rapport IA non écrit ({result.meta.get('ai_status')}) : rapport factuel",
                       level="warning", code=f"support_ai_{result.meta.get('ai_status')}",
                       detail=str(result.meta.get("ai_detail") or "")[:200])
        if omitted:
            self._emit("support.report.omissions", f"{len(omitted)} élément(s) omis ou refusés",
                       count=len(omitted), reasons=sorted({str(e.get('reason')).split(':')[0] for e in omitted})[:10])
        self._emit("support.report.created", f"Paquet de support écrit : {path.name}", name=path.name, bytes=size,
                   report_kind=result.kind, ai_status=result.meta.get("ai_status"), cost_usd=result.meta.get("cost_usd"),
                   duration_s=round(time.monotonic() - started, 1), pruned=len(removed))
        return {"bundle": {"name": path.name, "bytes": size, "report_kind": result.kind,
                           "ai_status": result.meta.get("ai_status"), "ai_detail": result.meta.get("ai_detail"),
                           "unknown_mentions": result.meta.get("unknown_mentions") or [],
                           "omitted": omitted[:20], "sendable": size <= SS.MAX_SEND_BYTES},
                "destination": self.destination(), "transport": SS.describe_transport(self._transport),
                "duration_s": round(time.monotonic() - started, 1)}

    def _failed(self, code: str, message: str, exc: BaseException) -> SupportRouteError:
        self._emit("support.report.failed", f"{message} {type(exc).__name__}: {str(exc)[:200]}", level="error",
                   code=code, error_type=type(exc).__name__)
        return SupportRouteError(500, code, message + " Réessayez ; le détail est dans le journal de JARVIS.",
                                 f"{type(exc).__name__}: {str(exc)[:200]}")

    # ------------------------------------------------------------ actes

    def bundle_path(self, name: str) -> Path:
        if not SB.BUNDLE_NAME.fullmatch(name or ""):
            raise SupportRouteError(400, "support_bundle_name_invalid", "Nom de paquet invalide.")
        path = self.support_dir / name
        if not path.is_file() or path.is_symlink():
            raise SupportRouteError(404, "support_bundle_missing", "Ce paquet n'existe plus (rétention ou nettoyage).")
        return path

    async def send(self, name: str) -> dict[str, Any]:
        path = self.bundle_path(name)
        size = _size(path)
        destination = self.destination()
        if size > SS.MAX_SEND_BYTES:
            self._emit("support.report.send_failed", "Paquet trop gros pour un courriel", level="error",
                       code="support_bundle_too_large", name=name, bytes=size)
            self._pending(name, True)
            raise SupportRouteError(413, "support_bundle_too_large",
                                    "Ce paquet est trop gros pour un courriel : enregistrez-le et transmettez-le autrement.",
                                    f"{size} bytes > {SS.MAX_SEND_BYTES}")
        running = self._sending.get(name)
        if running is not None and not running.done():
            raise SupportRouteError(409, "support_send_in_progress",
                                    "Un envoi de ce paquet attend encore votre messagerie : terminez-le dans sa fenêtre.")
        subject, body = SS.mail_text(path, description=_description_of(path))
        self._emit("support.report.send_started", f"Envoi demandé ({self._transport.name})", name=name,
                   transport=self._transport.name)
        task = asyncio.ensure_future(asyncio.to_thread(self._transport.send, path, to=destination, subject=subject, body=body))
        self._sending[name] = task
        task.add_done_callback(lambda _done: self._sending.pop(name, None) if self._sending.get(name) is task else None)
        try:
            outcome = await asyncio.wait_for(asyncio.shield(task), timeout=SEND_TIMEOUT_S)
        except asyncio.TimeoutError:
            task.add_done_callback(lambda done: self._late(name, done))
            self._emit("support.report.send_waiting", "La messagerie n'a pas encore rendu la main", level="warning",
                       code="support_send_waiting", name=name, waited_s=SEND_TIMEOUT_S)
            return {"status": "waiting", "bundle": name, "destination": destination,
                    "message": f"La messagerie n'a pas répondu après {int(SEND_TIMEOUT_S)} s : si une fenêtre de rédaction "
                               "est ouverte, terminez l'envoi depuis celle-ci. Le paquet reste disponible."}
        except SS.SupportSendError as exc:
            self._emit("support.report.send_failed", f"Envoi échoué : {exc.code}", level="error", code=exc.code,
                       name=name, transport=self._transport.name, detail=exc.detail[:200])
            self._pending(name, True)
            raise SupportRouteError(502, exc.code, f"{exc} Le paquet est conservé jusqu'à son enregistrement (30 jours au "
                                    "plus) : enregistrez-le pour le transmettre.", exc.detail) from exc
        self._pending(name, False)
        self._emit("support.report.sent", outcome.message, name=name, transport=self._transport.name, status=outcome.status)
        return {"status": outcome.status, "message": outcome.message, "bundle": name, "destination": destination}

    def _late(self, name: str, done: asyncio.Future) -> None:
        error = done.exception() if not done.cancelled() else None
        if error is not None:
            self._emit("support.report.send_failed", f"Envoi échoué après l'échéance : {type(error).__name__}",
                       level="error", code=getattr(error, "code", "support_send_failed"), name=name)
        else:
            self._emit("support.report.sent", "Messagerie rendue après l'échéance", name=name, transport=self._transport.name)

    async def save(self, name: str) -> dict[str, Any]:
        from jarvis.domain.document_export import ExportError
        path = self.bundle_path(name)
        try:
            destination = self._export_destination() if self._export_destination else _default_export(self._sources_factory())
            outcome = await asyncio.to_thread(destination.copy_in, path, stem=path.stem, extension=".zip",
                                              expected_size=None, expected_sha256=None)
        except ExportError as exc:
            self._emit("support.report.save_failed", f"Enregistrement refusé : {exc.code.value}", level="error",
                       code=f"support_save_{exc.code.value}", name=name)
            raise SupportRouteError(409, f"support_save_{exc.code.value}",
                                    "Le paquet n'a pas pu être copié dans Documents\\Jarvis. Utilisez « Télécharger… ».",
                                    exc.detail) from exc
        label = getattr(destination, "label", "Documents\\Jarvis")
        self._pending(name, False)
        self._emit("support.report.saved", "Paquet copié dans le dossier d'export", name=name, file_name=outcome.file_name)
        return {"status": "saved", "file_name": outcome.file_name, "root": label,
                "message": f"Paquet enregistré dans {label} sous le nom {outcome.file_name}."}

    def _pending(self, name: str, pending: bool) -> None:
        try:
            SB.set_pending(self.support_dir, name, pending)
        except OSError as exc:
            self._emit("support.report.pending_unwritable", f"Liste des paquets à garder non écrite : {type(exc).__name__}",
                       level="warning", code="support_pending_unwritable", name=name)

    def downloaded(self, name: str) -> None:
        self._pending(name, False)

    def set_destination(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        value = payload.get(SS.SUPPORT_EMAIL_SETTING)
        if not isinstance(value, str) or (value.strip() and not SS.valid_email(value.strip())):
            raise SupportRouteError(400, "support_destination_invalid", "Adresse de destination invalide.")
        if self._update_settings is None:
            raise SupportRouteError(503, "support_settings_unavailable", "Les réglages ne peuvent pas être écrits ici.")

        def apply(settings: dict[str, Any]) -> None:
            if value.strip():
                settings[SS.SUPPORT_EMAIL_SETTING] = value.strip()
            else:
                settings.pop(SS.SUPPORT_EMAIL_SETTING, None)

        self._update_settings(apply)
        self._emit("support.destination.changed", "Destination des rapports de support modifiée",
                   default=not value.strip())
        return {"destination": self.destination(), "default_destination": SS.DEFAULT_SUPPORT_EMAIL}


def _description_of(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as bundle:
            return bundle.read("context/description.txt").decode("utf-8", errors="replace")[:2000]
    except (KeyError, OSError, zipfile.BadZipFile):
        return ""  # intentional: no description in this bundle; the mail body just omits it


def _default_export(sources: SB.BundleSources) -> Any:
    from jarvis.adapters.export_destination import ExportDestination
    return ExportDestination.from_environment(data_root=sources.data_root, environ=dict(sources.environ))


class SupportReportRoutes:
    def __init__(self, service: SupportReportService, *, journal: RuntimeJournal) -> None:
        self._service = service
        self._journal = journal

    def routes(self) -> list[web.RouteDef]:
        return [
            web.get("/api/support/preview", self.preview),
            web.post("/api/support/reports", self.create),
            web.post("/api/support/reports/{name}/send", self.send),
            web.post("/api/support/reports/{name}/save", self.save),
            web.get("/api/support/reports/{name}/download", self.download),
            web.post("/api/support/destination", self.destination),
        ]

    async def _guard(self, name: str, call: Callable[[], Awaitable[Any]]) -> web.Response:
        try:
            return web.json_response(await call())
        except SupportRouteError as exc:
            return _error(exc.status, exc.code, str(exc), exc.detail)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced: 500 with its cause, journaled at error
            self._journal.emit(f"support.{name}.failed", f"{name} : {type(exc).__name__}: {str(exc)[:200]}", level="error",
                               data={"code": f"support_{name}_failed", "error_type": type(exc).__name__})
            return _error(500, f"support_{name}_failed", "Une erreur inattendue est survenue. Réessayez ; le détail est "
                          "dans le journal de JARVIS.", f"{type(exc).__name__}: {str(exc)[:200]}")

    async def _body(self, request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise SupportRouteError(400, "invalid_request", "Demande mal formée.", "body is not JSON") from None
        if not isinstance(payload, dict):
            raise SupportRouteError(400, "invalid_request", "Demande mal formée.", "body is not an object")
        return payload

    async def preview(self, request: web.Request) -> web.Response:
        del request
        return await self._guard("preview", self._service.preview)

    async def create(self, request: web.Request) -> web.Response:
        async def run() -> dict[str, Any]:
            return await self._service.create(await self._body(request))
        return await self._guard("create", run)

    async def send(self, request: web.Request) -> web.Response:
        return await self._guard("send", lambda: self._service.send(request.match_info["name"]))

    async def save(self, request: web.Request) -> web.Response:
        return await self._guard("save", lambda: self._service.save(request.match_info["name"]))

    async def download(self, request: web.Request) -> web.StreamResponse:
        try:
            path = self._service.bundle_path(request.match_info["name"])
        except SupportRouteError as exc:
            return _error(exc.status, exc.code, str(exc), exc.detail)
        self._journal.emit("support.report.downloaded", "Paquet téléchargé par la page", data={"name": path.name})
        self._service.downloaded(path.name)
        return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"',
                                               "Content-Type": "application/zip", "Cache-Control": "no-store"})

    async def destination(self, request: web.Request) -> web.Response:
        async def run() -> dict[str, Any]:
            return self._service.set_destination(await self._body(request))
        return await self._guard("destination", run)


__all__ = ["SupportReportRoutes", "SupportReportService", "SupportRouteError"]
