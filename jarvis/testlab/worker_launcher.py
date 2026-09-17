"""Starting, watching and killing one Test Lab worker process tree.

Binding contract: `docs/testlab.md` ("Supervisor and workers"). This module owns
the process mechanics and nothing else, so the supervisor can be tested with a
fake launcher and no real process.

Process primitives (READINESS B4.4): `asyncio.create_subprocess_exec` only.
`scripts/verify_release.py` forbids the blocking subprocess helpers and any
shell execution under `jarvis/`, and the command line carries only the job file
path: run data goes through the job document, never through arguments.

Containment:

- Windows: `jarvis.runtime.owned_process_tree.OwnedProcessTree` (create
  suspended, assign to a Job Object with `KILL_ON_JOB_CLOSE` and no breakaway,
  resume). Killing the job kills the worker and everything it started, and the
  kernel kills the whole tree if the supervisor itself dies, so a worker can
  never outlive its supervisor.
- POSIX fallback: `start_new_session=True` gives the worker its own process
  group, killed with `os.killpg`. A process group is NOT killed when the parent
  dies, so on POSIX an orphaned worker can survive a supervisor crash; adoption
  handles that case by refusing to touch a run whose worker lock is still held.

stderr is captured rather than inherited (the `scripts/supervisor_v2.py` idiom):
it is the only place a brutal death leaves a trace. It is tee'd to a bounded
file in the run scratch and to a small in-memory tail.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
import os
from pathlib import Path
import signal
import sys
from typing import Protocol

from jarvis.testlab.jobs import JOB_FILE_NAME, STDERR_LOG_NAME, WorkerJob

#: Worker module started as `python -m <WORKER_MODULE> <job.json>`.
WORKER_MODULE = "jarvis.testlab.worker"
#: Lines of stderr kept in memory for the failure detail (same budget as `supervisor_v2`).
STDERR_TAIL_LINES = 40
#: Hard cap of the stderr file committed as an artifact.
MAX_STDERR_BYTES = 256 * 1024
#: How long a tree kill waits for the process to be reaped before giving up on `wait`.
KILL_WAIT_S = 10.0
#: Attempts to close an emptied Windows Job Object handle after the worker exits.
JOB_CLOSE_ATTEMPTS = 10
JOB_CLOSE_DELAY_S = 0.05


class WorkerProcess(Protocol):
    """One live worker, as the supervisor sees it."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...

    async def wait(self) -> int: ...

    async def kill_tree(self) -> None:
        """Kill the worker and everything it started. Idempotent."""
        ...

    def stderr_tail(self) -> str:
        """The last captured stderr lines, unredacted (the supervisor redacts before storing)."""
        ...

    async def aclose(self) -> None:
        """Release the pump task and the platform handle. Never raises."""
        ...


class WorkerLauncher(Protocol):
    async def launch(self, job: WorkerJob, *, environ: Mapping[str, str], cwd: Path) -> WorkerProcess: ...


class SubprocessWorkerLauncher:
    """The real launcher: one Python subprocess per run, contained in a job object or a process group."""

    def __init__(self, *, python_executable: str | None = None, module: str = WORKER_MODULE) -> None:
        self.python_executable = python_executable or sys.executable
        self.module = module

    async def launch(self, job: WorkerJob, *, environ: Mapping[str, str], cwd: Path) -> WorkerProcess:
        scratch = Path(job.scratch_root)
        tree = _OwnedTree.create()
        try:
            process = await asyncio.create_subprocess_exec(
                self.python_executable, "-m", self.module, str(scratch / JOB_FILE_NAME),
                cwd=str(cwd), env=dict(environ),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                **tree.spawn_arguments())
        except BaseException:
            tree.discard()
            raise
        worker = _SubprocessWorker(process, tree, scratch / STDERR_LOG_NAME)
        try:
            tree.adopt(process.pid)
        except BaseException:
            # The child may be suspended (Windows) and would never run: kill it rather
            # than leave a frozen process behind, then report the spawn failure.
            await worker.kill_tree()
            await worker.aclose()
            raise
        worker.start_pump()
        return worker


class _SubprocessWorker:
    """Adapter around `asyncio.subprocess.Process` plus its containment handle."""

    def __init__(self, process: asyncio.subprocess.Process, tree: _OwnedTree, stderr_path: Path) -> None:
        self._process = process
        self._tree = tree
        self._stderr_path = stderr_path
        self._tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._pump: asyncio.Task[None] | None = None
        self._killed = False

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    def start_pump(self) -> None:
        self._pump = asyncio.create_task(self._pump_stderr(), name=f"testlab-worker-stderr-{self.pid}")

    async def _pump_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        written = 0
        handle = None
        try:
            handle = open(self._stderr_path, "a", encoding="utf-8")
        except OSError:
            # intentional: the stderr file is evidence, not the run. Without it the
            # in-memory tail still reaches the failure detail.
            handle = None
        try:
            while True:
                try:
                    raw = await stream.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    raw = await stream.read(MAX_STDERR_BYTES)  # a single enormous line
                if not raw:
                    return
                line = raw.decode("utf-8", errors="replace").rstrip()
                self._tail.append(line)
                if handle is not None and written < MAX_STDERR_BYTES:
                    written += len(raw)
                    handle.write(line + "\n")
                    handle.flush()
        except OSError:
            return  # the pipe or the file died with the worker; the tail keeps what it has
        finally:
            if handle is not None:
                handle.close()

    async def wait(self) -> int:
        return await self._process.wait()

    async def kill_tree(self) -> None:
        if self._process.returncode is not None and self._killed:
            return
        self._killed = True
        self._tree.kill(self._process)
        try:
            await asyncio.wait_for(self._process.wait(), timeout=KILL_WAIT_S)
        except asyncio.TimeoutError:
            # Captured: an unreapable process is a platform fault, not a run outcome. The
            # supervisor still records a terminal run; the job handle keeps the tree contained.
            return

    def stderr_tail(self) -> str:
        return "\n".join(self._tail)

    async def aclose(self) -> None:
        pump = self._pump
        self._pump = None
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        await self._tree.release(self._process)


class _OwnedTree:
    """Platform containment of one worker tree: Windows Job Object, or a POSIX process group."""

    def __init__(self, owned: object | None) -> None:
        self._owned = owned

    @classmethod
    def create(cls) -> _OwnedTree:
        if os.name != "nt":
            return cls(None)
        from jarvis.runtime.owned_process_tree import OwnedProcessTree

        return cls(OwnedProcessTree())

    def spawn_arguments(self) -> dict[str, object]:
        if self._owned is None:
            # POSIX: its own session and process group, so `killpg` reaches the whole tree.
            return {"start_new_session": True}
        return {"creationflags": self._owned.creationflags}

    def adopt(self, pid: int) -> None:
        if self._owned is not None:
            self._owned.attach_and_resume(pid)

    def kill(self, process: asyncio.subprocess.Process) -> None:
        if self._owned is not None:
            self._owned.terminate()
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            # The group is already gone, or this platform refuses it: fall back to the
            # process itself, which is still better than leaving the run running.
            if process.returncode is None:
                process.kill()

    def discard(self) -> None:
        """Release the handle of a spawn that never happened."""
        if self._owned is not None:
            self._owned.terminate()
            self._owned.close_if_empty()
            self._owned = None

    async def release(self, process: asyncio.subprocess.Process) -> None:
        """End the containment of a finished run, taking any survivor with it.

        A worker may exit while something it started is still alive. That
        grandchild belongs to the run, not to the host, so it goes: on Windows by
        terminating the job once the grace has passed (closing the handle would do
        the same, `KILL_ON_JOB_CLOSE`), on POSIX by killing the process group.
        """
        owned = self._owned
        if owned is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                pass  # intentional: the group is already gone, which is the normal case
            return
        for _ in range(JOB_CLOSE_ATTEMPTS):
            try:
                if owned.close_if_empty():
                    self._owned = None
                    return
            except OSError:
                self._owned = None
                return  # the handle is already unusable; nothing left to release
            await asyncio.sleep(JOB_CLOSE_DELAY_S)
        try:
            owned.terminate()
            owned.close_if_empty()
        except OSError:
            pass  # intentional: the handle dies with this process, which kills the job anyway
        self._owned = None
