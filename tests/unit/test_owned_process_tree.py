"""Controlled kernel boundary plus a Windows-only harmless Python process tree."""
import asyncio
import os
import sys

import pytest

from jarvis.runtime.owned_process_tree import CREATE_NO_WINDOW, CREATE_SUSPENDED, OwnedProcessTree


class Kernel:
    def __init__(self):
        self.calls = []
        self.active_count = 0
        self.failure = None

    def create(self):
        self.calls.append("create")
        return 123

    def assign(self, handle, pid):
        self.calls.append(("assign", handle, pid))
        if self.failure == "assign":
            raise OSError("assign failed")
        self.active_count = 1

    def resume(self, pid):
        self.calls.append(("resume", pid))
        if self.failure == "resume":
            raise OSError("resume failed")

    def terminate(self, handle):
        self.calls.append(("terminate", handle))

    def active(self, handle):
        return self.active_count

    def close(self, handle):
        self.calls.append(("close", handle))
        if self.failure == "close":
            raise OSError("close failed")


def test_assignment_precedes_resume_and_termination_does_not_fabricate_empty_membership():
    api = Kernel()
    tree = OwnedProcessTree(api=api)
    assert tree.creationflags == CREATE_SUSPENDED | CREATE_NO_WINDOW
    tree.attach_and_resume(456)
    assert api.calls == ["create", ("assign", 123, 456), ("resume", 456)]
    tree.terminate()
    tree.terminate()
    assert api.calls.count(("terminate", 123)) == 1
    assert tree.close_if_empty() is False
    assert tree.handle == 123
    api.active_count = 0
    assert tree.close_if_empty() is True
    assert tree.close_if_empty() is True
    tree.terminate()
    assert api.calls.count(("close", 123)) == 1


@pytest.mark.parametrize("phase", ["assign", "resume"])
def test_failed_start_retains_the_handle_and_never_resumes_an_unassigned_process(phase):
    api = Kernel()
    api.failure = phase
    tree = OwnedProcessTree(api=api)
    with pytest.raises(OSError, match=phase):
        tree.attach_and_resume(456)
    assert tree.handle == 123
    if phase == "assign":
        assert ("resume", 456) not in api.calls
    tree.terminate()
    api.active_count = 0
    assert tree.close_if_empty()


def test_failed_job_handle_close_remains_retryable():
    api = Kernel()
    tree = OwnedProcessTree(api=api)
    api.failure = "close"
    with pytest.raises(OSError):
        tree.close_if_empty()
    assert tree.handle == 123
    api.failure = None
    assert tree.close_if_empty()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object integration")
async def test_real_windows_job_contains_and_terminates_controlled_python_parent_and_child(tmp_path):
    # No agent CLI, network or inference. The parent and child only wait.
    tree = OwnedProcessTree()
    process = None
    child_pid_file = tmp_path / "controlled-child.pid"
    script = (
        "import subprocess,sys,time,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", script, str(child_pid_file),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            creationflags=tree.creationflags)
        assert not child_pid_file.exists()  # Suspended process has executed no instruction.
        tree.attach_and_resume(process.pid)
        async with asyncio.timeout(5):
            while not child_pid_file.exists():
                await asyncio.sleep(.01)
        child_pid = int(child_pid_file.read_text())
        assert child_pid != process.pid
        assert tree.api.contains(tree.handle, process.pid)
        assert tree.api.contains(tree.handle, child_pid)
        # venv redirectors can add descendants; all belong to this same job.
        assert tree.api.active(tree.handle) >= 2
        tree.terminate()
        await asyncio.wait_for(process.wait(), 3)
        async with asyncio.timeout(3):
            while not tree.close_if_empty():
                await asyncio.sleep(.01)
        assert tree.handle is None
    finally:
        tree.terminate()
        if process is not None and process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 3)
        async with asyncio.timeout(3):
            while not tree.close_if_empty():
                await asyncio.sleep(.01)
