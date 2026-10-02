"""Le disque des Contexts et des Artifacts ne fige jamais la boucle de Core (handoff
session-context-recording, Slice 11, enquête sur l'arrêt de ~12 s).

Sur l'hôte, une ouverture de fichier a pris jusqu'à 11 s (antivirus, mémoire
tendue) : tout appel disque synchrone sur la boucle d'événements fige alors
toutes les routes de Core (statut des captures, Board, tours). Ici chaque
appel disque des dossiers de Context et des payloads d'Artifact dort 0,4 s ;
un témoin mesure l'écart le plus long entre deux battements de la boucle.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time

from jarvis.adapters.fake_capture import FakeCaptureSources, FakeOneShotSource
from jarvis.core.context_enrichment import SUMMARY_FILE, ContextEnrichmentWorker
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.capture import CaptureChannel
from jarvis.ports.context_enrichment import EnrichmentReply

SLOW_S = 0.4
#: Bien en deçà de SLOW_S : un seul appel disque sur la boucle ferait échouer le test.
MAX_GAP_S = 0.2


class Slow:
    """Délègue à l'adaptateur réel après `time.sleep` : un disque lent, vu de la boucle."""

    def __init__(self, inner, slow: set[str]) -> None:  # noqa: ANN001
        self._inner = inner
        self._slow = slow
        self.calls: list[str] = []

    def __getattr__(self, name: str):  # noqa: ANN204
        attr = getattr(self._inner, name)
        if name not in self._slow or not callable(attr):
            return attr

        def call(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            self.calls.append(name)
            time.sleep(SLOW_S)
            return attr(*args, **kwargs)

        return call


class Ticker:
    def __init__(self) -> None:
        self.max_gap = 0.0
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            self.max_gap = max(self.max_gap, now - last)
            last = now

    async def __aenter__(self) -> Ticker:
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0.02)
        return self

    async def __aexit__(self, *exc) -> None:  # noqa: ANN002
        assert self._task is not None
        # Laisse battre la boucle après la dernière opération : sinon un blocage final n'est jamais mesuré.
        await asyncio.sleep(0.05)
        self._task.cancel()


async def test_context_folder_io_runs_off_the_loop(tmp_path):
    app = JarvisCoreApplication(data_root=tmp_path)
    await app.start()
    try:
        slow = Slow(app.sessions._workspaces, {"ensure", "write_handoff", "read_summary", "write_file",  # noqa: SLF001
                                               "read_file", "check_files"})
        app.sessions._workspaces = slow  # noqa: SLF001
        conversation = (await app.sessions.current()).binding.conversation_id
        first = (await app.sessions.current_context()).context.context_id
        async with Ticker() as ticker:
            await app.sessions.current_context()
            created = await app.sessions.create_context(title="B", handoff_summary="relais", source_context_ids=[first])
            assert created.handoff_path is not None
            block = await app.sessions.session_context(conversation)
            assert block is not None and block.context_id == created.context.context_id
            written = await app.sessions.write_active_context_files(created.context.context_id,
                                                                    (("summary.md", "# B\n"),))
            assert written is not None
            assert await asyncio.to_thread(app.sessions.read_context_file, written, "summary.md", 1024) == ("# B\n",
                                                                                                           False)
            await app.sessions.activate_context(first)
        assert {"ensure", "write_handoff", "read_summary", "write_file"} <= set(slow.calls)
        assert ticker.max_gap < MAX_GAP_S, f"loop blocked {ticker.max_gap:.3f} s"
    finally:
        await app.stop()


async def test_screenshot_payload_and_deletion_run_off_the_loop(tmp_path):
    sources = FakeCaptureSources(one_shot={CaptureChannel.SCREEN: lambda: FakeOneShotSource()})
    app = JarvisCoreApplication(data_root=tmp_path, capture_sources=sources)
    await app.start()
    try:
        slow = Slow(app.artifacts._payloads, {"write_payload", "remove_folder"})  # noqa: SLF001
        app.artifacts._payloads = slow  # noqa: SLF001
        async with Ticker() as ticker:
            record = await app.captures.screenshot()
            assert record.state.value == "complete" and record.artifact_id is not None
            result = await app.artifacts.delete(record.artifact_id)
            assert record.artifact_id in result.artifact_ids and not result.orphan_folders
        assert slow.calls == ["write_payload", "remove_folder"]
        assert ticker.max_gap < MAX_GAP_S, f"loop blocked {ticker.max_gap:.3f} s"
    finally:
        await app.stop()


class _ImageModel:
    """Modèle factice sans réseau : décrit les images, réécrit le résumé."""

    model = "fake-haiku"
    supports_images = True

    async def complete(self, prompt, *, timeout_s, images=()):  # noqa: ANN001, ANN201
        text = "Un éditeur de code." if images else "# Travail\n- capture vue"
        return EnrichmentReply(text=text, model=self.model, cost_usd=0.0)


async def test_enrichment_summary_and_screenshot_reads_run_off_the_loop(tmp_path):
    sources = FakeCaptureSources(one_shot={CaptureChannel.SCREEN: lambda: FakeOneShotSource()})
    app = JarvisCoreApplication(data_root=tmp_path, capture_sources=sources)
    await app.start()
    try:
        await app.context_enrichment.close()  # pas de boucle concurrente : un tour mesuré à la main
        record = await app.captures.screenshot()
        assert record.state.value == "complete"
        view = await app.sessions.current_context()
        await asyncio.to_thread(app.sessions._workspaces.write_file, Path(view.workspace_path),  # noqa: SLF001
                                SUMMARY_FILE, "# Avant\n")
        workspaces = Slow(app.sessions._workspaces, {"read_file"})  # noqa: SLF001
        payloads = Slow(app.artifacts._payloads, {"inspect", "read_range"})  # noqa: SLF001
        app.sessions._workspaces, app.artifacts._payloads = workspaces, payloads  # noqa: SLF001
        model = _ImageModel()
        worker = ContextEnrichmentWorker(app.sessions, app.artifacts, lambda: model, debounce_s=0, min_interval_s=0)
        async with Ticker() as ticker:
            assert await worker.tick() == "round"
        assert {"inspect", "read_range"} <= set(payloads.calls)
        assert workspaces.calls.count("read_file") >= 2  # curseur, puis summary.md
        assert ticker.max_gap < MAX_GAP_S, f"loop blocked {ticker.max_gap:.3f} s"
    finally:
        await app.stop()
