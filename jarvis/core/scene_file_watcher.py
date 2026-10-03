"""Fenêtres de scène liées à un fichier : le résumé suit le fichier (demande de l'utilisateur, 2026-10-02).

Un objet de scène dont la charge porte `source_path` n'est plus une copie figée :
Core relit le fichier quand il change et réécrit `summary` avec son contenu,
sans tour du cerveau. Qui modifie le fichier n'importe pas (JARVIS, un
sous-agent, l'utilisateur à la main) : la veille ne regarde que le disque.

Une boucle sonde l'instantané de la scène une fois par `poll_s` : pour chaque
objet lié, la signature `(mtime_ns, taille)` du fichier. Une signature
différente de la dernière lue relance la lecture ; le résumé n'est réécrit que
s'il diffère, par une commande `patch_object` du cerveau (la fenêtre est une
composition du cerveau ou de l'utilisateur, jamais du runtime). Aucune
inscription à gérer : changer ou retirer `source_path`, archiver l'objet, tout
passe par la scène elle-même.

Limites assumées : le résumé tient 2 000 caractères (borne du domaine), le
début du fichier est montré et la coupe est dite ; un fichier binaire est
annoncé comme tel ; un fichier absent n'est annoncé qu'après deux sondes
consécutives (un remplacement par suppression puis création ne clignote pas).
La sonde est une interrogation, pas une notification du système : un
changement apparaît au plus tard après `poll_s` (1 s par défaut).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from dataclasses import replace

from jarvis.core.v2_services import NullDiagnosticSink
from jarvis.domain.scene import (
    MAX_PAYLOAD_SUMMARY_CHARS,
    SceneActor,
    SceneCommand,
    SceneObject,
    SceneObjectFields,
    SceneOp,
)
from jarvis.ports.v2 import DiagnosticSink

SCENE_FILE_REFRESHED_KIND = "core.scene.file_refreshed"
SCENE_FILE_REFRESH_FAILED_KIND = "core.scene.file_refresh_failed"

POLL_S = 1.0
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

    def __init__(self, scene, *, diagnostics: DiagnosticSink | None = None, poll_s: float = POLL_S) -> None:
        if poll_s <= 0:
            raise ValueError("poll_s must be positive")
        self._scene = scene
        self._diagnostics: DiagnosticSink = diagnostics or NullDiagnosticSink()
        self._poll_s = poll_s
        self._task: asyncio.Task | None = None
        #: object_id -> (chemin, dernière signature traitée)
        self._seen: dict[str, tuple[str, Signature]] = {}
        #: Objets dont le fichier manquait à la sonde précédente.
        self._missing_once: set[str] = set()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run(), name="jarvis-scene-file-watcher")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Scène indisponible ou fermée : on réessaie à la sonde suivante.
                pass
            await asyncio.sleep(self._poll_s)

    async def poll_once(self) -> int:
        """Une sonde : rend le nombre de résumés réécrits."""

        snapshot = await self._scene.snapshot()
        bound = {item.object_id: item for item in snapshot.objects if item.payload.source_path}
        for gone in set(self._seen) - set(bound):
            self._seen.pop(gone, None)
            self._missing_once.discard(gone)
        if not bound:
            return 0
        signatures = await asyncio.to_thread(lambda: {oid: _signature(item.payload.source_path) for oid, item in bound.items()})
        refreshed = 0
        for object_id, item in bound.items():
            path = item.payload.source_path
            signature = signatures[object_id]
            if self._seen.get(object_id) == (path, signature):
                continue
            if signature == _MISSING and object_id not in self._missing_once and object_id in self._seen:
                self._missing_once.add(object_id)
                continue
            self._missing_once.discard(object_id)
            # La signature retenue est celle d'avant la lecture : une écriture
            # pendant la lecture déclenche une nouvelle lecture à la sonde suivante.
            summary = await asyncio.to_thread(_summary_for, path, signature)
            self._seen[object_id] = (path, signature)
            if await self._write(object_id, summary):
                refreshed += 1
        return refreshed

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
