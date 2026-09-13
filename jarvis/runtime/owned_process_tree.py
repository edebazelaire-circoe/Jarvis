"""Windows job-process containment, before any child instruction can execute.

This owns process lifetime, not action permissions or external-service effects.
No breakaway flag is enabled. Other platforms are explicitly unavailable here.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
import sys

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


class OwnedProcessTree:
    """Keep the job handle until the kernel confirms its entire membership empty."""
    creationflags = CREATE_SUSPENDED | CREATE_NO_WINDOW

    def __init__(self, *, api=None):
        self.api = api if api is not None else WindowsJobAPI()
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
