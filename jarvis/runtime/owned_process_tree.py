"""Windows job-process containment, before any child instruction can execute.

This owns process lifetime, not action permissions or external-service effects.
No breakaway flag is enabled.

POSIX (macOS, Slice 08 of V1.2, `docs/macos-portability.md`): `PosixProcessGroupAPI` puts the child in its own
session/process group (`start_new_session`, see `spawn_kwargs(tree)`) and kills the whole group
(`killpg`). It is weaker than a job object and says so: the child runs from its first instruction (no suspended
start), a descendant that calls `setsid()` leaves the group, and nothing kills the group if the owner itself dies
(no `KILL_ON_JOB_CLOSE`). Written and tested with simulated platform only; never executed on a Mac.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
import signal
import sys

IS_WINDOWS = os.name == "nt"

CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = 0x08000000


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in (
        "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")]
    _fields_ += [(name, w.DWORD) for name in (
        "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                ("th32OwnerProcessID", w.DWORD), ("tpBasePri", w.LONG), ("tpDeltaPri", w.LONG), ("dwFlags", w.DWORD)]


class WindowsJobAPI:
    def __init__(self):
        if os.name != "nt":
            raise OSError("owned_process_tree_unavailable")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "IsProcessInJob": ([w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, ctypes.POINTER(_ThreadEntry)], w.BOOL),
            "Thread32Next": ([w.HANDLE, ctypes.POINTER(_ThreadEntry)], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
        }
        for name, (args, result) in signatures.items():
            method = getattr(self.api, name)
            method.argtypes, method.restype = args, result

    @staticmethod
    def _check(value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())
        return value

    def _close_temporary(self, handle):
        primary = sys.exception()
        try:
            self._check(self.api.CloseHandle(handle))
        except OSError:
            if primary is None:
                raise
            primary.add_note("temporary Windows handle cleanup also failed")

    def create(self):
        handle = self._check(self.api.CreateJobObjectW(None, None))
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE, no BREAKAWAY.
        try:
            self._check(self.api.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self._close_temporary(handle)
            raise
        return handle

    def assign(self, handle, pid):
        process = self._check(self.api.OpenProcess(0x0100 | 0x0001, False, pid))  # SET_QUOTA | TERMINATE
        try:
            self._check(self.api.AssignProcessToJobObject(handle, process))
        finally:
            self._close_temporary(process)

    def resume(self, pid):
        # asyncio's subprocess API does not expose the initial thread handle.
        # The process is still suspended, so enumerate and resume its initial
        # thread using documented Toolhelp/OpenThread/ResumeThread APIs.
        snapshot = self.api.CreateToolhelp32Snapshot(0x4, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = False
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            present = self.api.Thread32First(snapshot, ctypes.byref(entry))
            while present:
                if entry.th32OwnerProcessID == pid:
                    thread = self._check(self.api.OpenThread(0x0002, False, entry.th32ThreadID))
                    try:
                        previous = self.api.ResumeThread(thread)
                        if previous == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        resumed |= previous > 0
                    finally:
                        self._close_temporary(thread)
                present = self.api.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self._close_temporary(snapshot)
        if not resumed:
            raise OSError("owned_process_initial_thread_unavailable")

    def terminate(self, handle):
        self._check(self.api.TerminateJobObject(handle, 1))

    def contains(self, handle, pid):
        process = self._check(self.api.OpenProcess(0x1000, False, pid))  # QUERY_LIMITED_INFORMATION
        try:
            member = w.BOOL()
            self._check(self.api.IsProcessInJob(process, handle, ctypes.byref(member)))
            return bool(member.value)
        finally:
            self._close_temporary(process)

    def active(self, handle):
        accounting = _Accounting()
        self._check(self.api.QueryInformationJobObject(handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None))
        return accounting.ActiveProcesses

    def close(self, handle):
        self._check(self.api.CloseHandle(handle))


class _ProcessGroup:
    """Mutable handle of `PosixProcessGroupAPI`: the group id once a child is attached."""

    __slots__ = ("pgid",)

    def __init__(self):
        self.pgid: int | None = None


class PosixProcessGroupAPI:
    """Same contract as `WindowsJobAPI`, by process group. Functions are injectable for simulated-platform tests."""

    def __init__(self, *, killpg=None, getpgid=None):
        killpg = killpg if killpg is not None else getattr(os, "killpg", None)
        getpgid = getpgid if getpgid is not None else getattr(os, "getpgid", None)
        if killpg is None or getpgid is None:
            raise OSError("owned_process_tree_unavailable")
        self._killpg, self._getpgid = killpg, getpgid

    def create(self):
        return _ProcessGroup()

    def assign(self, handle, pid):
        # `start_new_session=True` made the child a session and group leader: its group id IS its pid. Anything
        # else means the child was not started with `spawn_kwargs(tree)`, and killing "its" group could hit ours.
        if self._getpgid(pid) != pid:
            raise OSError("owned_process_tree_not_isolated")
        handle.pgid = pid

    def resume(self, pid):
        """Nothing to resume: POSIX cannot start a child suspended (documented weakness)."""

    def terminate(self, handle):
        if handle.pgid is None:
            return
        try:
            self._killpg(handle.pgid, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            pass  # intentional: the whole group is already gone, which is the requested outcome

    def contains(self, handle, pid):
        try:
            return handle.pgid is not None and self._getpgid(pid) == handle.pgid
        except ProcessLookupError:
            return False

    def active(self, handle):
        if handle.pgid is None:
            return 0
        try:
            self._killpg(handle.pgid, 0)
        except ProcessLookupError:
            return 0
        except PermissionError:
            return 1  # a member exists but belongs to someone else now: still not empty for us
        return 1  # killpg cannot count members; "at least one" is all `close_if_empty` needs

    def close(self, handle):
        handle.pgid = None


def spawn_kwargs(tree) -> dict:
    """Spawn arguments for a child `tree` will own: `{"creationflags": tree.creationflags}` on Windows (exactly the
    pre-Slice-08 argument), `{"start_new_session": True}` on POSIX (`creationflags` must be 0 there)."""

    return {"creationflags": tree.creationflags} if IS_WINDOWS else {"start_new_session": True}


def default_api():
    """Job object on Windows, process group elsewhere (`OSError` if neither exists)."""

    return WindowsJobAPI() if IS_WINDOWS else PosixProcessGroupAPI()


class OwnedProcessTree:
    """Keep the job handle until the kernel confirms its entire membership empty."""
    # Windows: start suspended, attach to the job, then resume. POSIX: `creationflags` must be 0 (Popen refuses
    # anything else); the isolation comes from `start_new_session` instead.
    creationflags = (CREATE_SUSPENDED | CREATE_NO_WINDOW) if IS_WINDOWS else 0
    start_new_session = not IS_WINDOWS

    def __init__(self, *, api=None):
        self.api = api if api is not None else default_api()
        self.handle = self.api.create()

        self.attached = False
        self.termination_requested = False

    def attach_and_resume(self, pid: int):
        if self.handle is None or self.attached or self.termination_requested:
            raise OSError("owned_process_tree_cannot_reopen")
        self.api.assign(self.handle, pid)
        self.attached = True
        self.api.resume(pid)

    def terminate(self):
        if self.handle is not None and not self.termination_requested:
            self.api.terminate(self.handle)
            self.termination_requested = True

    def close_if_empty(self) -> bool:
        if self.handle is None:
            return True
        if self.api.active(self.handle) != 0:
            return False
        self.api.close(self.handle)
        self.handle = None
        return True
