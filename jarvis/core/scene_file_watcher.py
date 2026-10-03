"""Fenêtres de scène liées à un fichier : le résumé suit le fichier (demande de l'utilisateur, 2026-10-02/03).

Un objet de scène dont la charge porte `source_path` n'est plus une copie figée :
Core relit le fichier quand il change et réécrit `summary` avec son contenu,
sans tour du cerveau. Qui modifie le fichier n'importe pas (JARVIS, un
sous-agent, un éditeur, l'utilisateur à la main).

Par événements, sans sondage : le système de fichiers prévient
(`FileChangeNotifier`, `ReadDirectoryChangesW`) dès qu'un fichier lié change ;
la veille relit alors ce fichier, après 50 ms de calme (une écriture produit
plusieurs notifications). La scène, elle, réveille la veille quand une révision
paraît (`wait_for_revision`) : un objet nouvellement lié est lu aussitôt et son
dossier mis sous surveillance, un lien retiré ou un objet archivé relâche la
surveillance. Aucune minuterie ne relit un fichier qui n'a pas changé.
`notify_changed(chemin)` est le même événement poussé de l'intérieur (un
chemin d'écriture de Core qui voudrait ne pas attendre le noyau).

Le résumé n'est réécrit que s'il diffère, par une commande `patch_object` du
cerveau (la fenêtre est une composition du cerveau ou de l'utilisateur, jamais
du runtime).

Limites assumées : le résumé tient 2 000 caractères (borne du domaine), le
début du fichier est montré et la coupe est dite ; un fichier binaire est
annoncé comme tel ; un fichier absent n'est annoncé qu'après une seconde
vérification 0,5 s plus tard (un remplacement par suppression puis création ne
clignote pas). Hors couverture : un dossier réseau qui ne transmet pas les
notifications, et tout système autre que Windows (le résumé n'est alors lu
qu'à la liaison, et la veille le dit dans les diagnostics).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path

from jarvis.core.v2_services import NullDiagnosticSink
from jarvis.domain.scene import (
    MAX_PAYLOAD_SUMMARY_CHARS,
    SceneActor,
    SceneCommand,
    SceneObject,
    SceneObjectFields,
    SceneOp,
)
from jarvis.ports.file_changes import NotifierFactory, normalize
from jarvis.ports.v2 import DiagnosticSink

SCENE_FILE_REFRESHED_KIND = "core.scene.file_refreshed"
SCENE_FILE_REFRESH_FAILED_KIND = "core.scene.file_refresh_failed"
SCENE_FILE_WATCH_UNAVAILABLE_KIND = "core.scene.file_watch_unavailable"

#: Calme exigé après la dernière notification d'un fichier avant de le relire.
DEBOUNCE_S = 0.05
#: Délai de la seconde vérification d'un fichier absent.
MISSING_CONFIRM_S = 0.5
#: Attente maximale d'une révision de scène (borne de réveil, jamais une relecture).
SCENE_WAIT_S = 30.0
RETRY_S = 1.0
#: Octets lus au plus : la scène ne montre que 2 000 caractères.
MAX_READ_BYTES = 64 * 1024
_TRUNCATED_NOTE = "\n… (suite du fichier non affichée)"
_MISSING = ("missing",)

Signature = tuple


def render_file_summary(raw: bytes, *, truncated_source: bool = False) -> str:
    """Texte de résumé d'un contenu de fichier : une chaîne valide pour `ScenePayload.summary`, jamais plus de 2 000 caractères."""

    if b"\x00" in raw[:4096]:
        return "(fichier binaire : aperçu impossible)"
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch if ch >= " " or ch in "\n\t" else " " for ch in text)
    if len(text) <= MAX_PAYLOAD_SUMMARY_CHARS and not truncated_source:
        return text
    room = MAX_PAYLOAD_SUMMARY_CHARS - len(_TRUNCATED_NOTE)
    return text[:room].rstrip() + _TRUNCATED_NOTE


def _signature(path: str) -> Signature:
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return _MISSING
    except OSError as exc:
        return ("error", type(exc).__name__)
    return (stat.st_mtime_ns, stat.st_size)


def _read(path: str) -> tuple[bytes, bool]:
    with open(path, "rb") as handle:
        raw = handle.read(MAX_READ_BYTES + 1)
    return raw[:MAX_READ_BYTES], len(raw) > MAX_READ_BYTES


def _summary_for(path: str, signature: Signature) -> str:
    if signature == _MISSING:
        return f"Fichier introuvable : {path}"[:MAX_PAYLOAD_SUMMARY_CHARS]
    try:
        raw, truncated = _read(path)
    except OSError as exc:
        return f"Fichier illisible ({type(exc).__name__}) : {path}"[:MAX_PAYLOAD_SUMMARY_CHARS]
    return render_file_summary(raw, truncated_source=truncated)


class SceneFileWatcher:
    """Tient à jour le résumé des objets de scène liés à un fichier (`ScenePayload.source_path`)."""

    def __init__(self, scene, *, diagnostics: DiagnosticSink | None = None, debounce_s: float = DEBOUNCE_S,
                 missing_confirm_s: float = MISSING_CONFIRM_S, notifier_factory: NotifierFactory | None = None) -> None:
        self._scene = scene
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._debounce_s = debounce_s
        self._missing_confirm_s = missing_confirm_s
        self._notifier_factory = notifier_factory
        self._notifier = None
        self._task: asyncio.Task | None = None
        #: object_id -> chemin normalisé déjà pris en charge
        self._linked: dict[str, str] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._jobs: set[asyncio.Task] = set()
        self._unavailable_said = False
        self._directories: set[str] = set()

    def start(self) -> None:
        if self._task is None:
            loop = asyncio.get_running_loop()
            if self._notifier_factory is not None:
                self._notifier = self._notifier_factory(loop, self.notify_changed)
            self._task = loop.create_task(self._run(), name="jarvis-scene-file-watcher")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        jobs, self._jobs = list(self._jobs), set()
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        notifier, self._notifier = self._notifier, None
        if notifier is not None:
            await asyncio.to_thread(notifier.close)

    def notify_changed(self, path: str) -> None:
        """Événement « ce fichier a changé » (du système de fichiers ou d'un chemin d'écriture de Core). Dans la boucle."""

        key = normalize(path)
        prefix = key.rstrip(os.sep) + os.sep
        for object_id, linked in list(self._linked.items()):
            # Chemin exact, ou dossier entier suspect (débordement du tampon du noyau).
            if linked == key or linked.startswith(prefix):
                self._schedule(object_id, self._debounce_s, confirm_missing=True)

    # ------------------------------------------------------------ boucle

    async def _run(self) -> None:
        while True:
            try:
                snapshot = await self._scene.snapshot()
                await self._reconcile(snapshot)
                await self._scene.wait_for_revision(snapshot.revision, timeout_s=SCENE_WAIT_S)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Scène indisponible ou fermée : on la rejoint dès qu'elle revient.
                await asyncio.sleep(RETRY_S)

    async def _reconcile(self, snapshot) -> None:
        """Aligner les liens suivis et les dossiers surveillés sur la scène ; lire les liens nouveaux."""

        bound = {item.object_id: normalize(item.payload.source_path)
                 for item in snapshot.objects if item.payload.source_path}
        for gone in set(self._linked) - set(bound):
            self._linked.pop(gone, None)
            self._cancel(gone)
        fresh = [oid for oid, path in bound.items() if self._linked.get(oid) != path]
        notifier = self._notifier
        directories = {os.path.dirname(path) for path in bound.values()}
        if directories != self._directories:
            self._directories = directories
            ok = bool(notifier is not None) and await asyncio.to_thread(self._sync_watches, notifier, directories)
            if directories and not ok and not self._unavailable_said:
                self._unavailable_said = True
                self._emit(SCENE_FILE_WATCH_UNAVAILABLE_KIND,
                           "notifications du système de fichiers indisponibles : fichiers lus à la liaison seulement",
                           "warning", {"platform": os.name})
        for object_id in fresh:
            self._linked[object_id] = bound[object_id]
            self._schedule(object_id, 0.0, confirm_missing=False)

    @staticmethod
    def _sync_watches(notifier, directories: set[str]) -> bool:
        ok = all([notifier.watch(directory) for directory in directories])
        notifier.keep_only(directories)
        return ok

    # ------------------------------------------------------------ relecture

    def _cancel(self, object_id: str) -> None:
        timer = self._timers.pop(object_id, None)
        if timer is not None:
            timer.cancel()

    def _schedule(self, object_id: str, delay: float, *, confirm_missing: bool) -> None:
        self._cancel(object_id)
        loop = asyncio.get_running_loop()
        self._timers[object_id] = loop.call_later(delay, self._launch, object_id, confirm_missing)

    def _launch(self, object_id: str, confirm_missing: bool) -> None:
        self._timers.pop(object_id, None)
        job = asyncio.get_running_loop().create_task(self._refresh(object_id, confirm_missing))
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    async def _refresh(self, object_id: str, confirm_missing: bool) -> bool:
        """Relire le fichier lié à l'objet et réécrire le résumé s'il diffère. Rend vrai si réécrit."""

        try:
            item = (await self._scene.snapshot()).get_object(object_id)
            if item is None or not item.payload.source_path:
                return False
            path = item.payload.source_path
            signature = await asyncio.to_thread(_signature, path)
            if signature == _MISSING and confirm_missing:
                # Un remplacement par suppression puis création ne doit pas clignoter.
                self._schedule(object_id, self._missing_confirm_s, confirm_missing=False)
                return False
            summary = await asyncio.to_thread(_summary_for, path, signature)
            return await self._write(object_id, summary)
        except asyncio.CancelledError:
            raise
        except Exception:
            return False  # scène fermée : la prochaine notification réessaie

    async def _write(self, object_id: str, summary: str) -> bool:
        current: SceneObject | None = (await self._scene.snapshot()).get_object(object_id)
        if current is None or not current.payload.source_path or current.payload.summary == summary:
            return False
        command = SceneCommand(
            op=SceneOp.PATCH_OBJECT, actor=SceneActor.BRAIN, object_id=object_id,
            fields=SceneObjectFields(payload=replace(current.payload, summary=summary)),
        )
        try:
            update = await self._scene.apply(command)
        except Exception as exc:
            self._emit(SCENE_FILE_REFRESH_FAILED_KIND, "résumé lié à un fichier non réécrit", "warning",
                       {"object_id": object_id, "error": f"{type(exc).__name__}: {exc}"})
            return False
        if update.patch is None:
            return False
        self._emit(SCENE_FILE_REFRESHED_KIND, "résumé réécrit depuis le fichier lié", "info",
                   {"object_id": object_id, "chars": len(summary), "name": Path(current.payload.source_path).name})
        return True

    def _emit(self, kind: str, message: str, level: str, data: dict) -> None:
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            pass
