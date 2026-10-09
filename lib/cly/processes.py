"""Verified process-family shutdown for snapshot reload; standard library only."""
from dataclasses import dataclass, replace
from datetime import datetime
import errno
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    birth: str
    parent: int
    run_ids: tuple = ()


def _windows():
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    api.GetProcessTimes.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.TerminateProcess.restype = wintypes.BOOL
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(api, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        function.restype = wintypes.BOOL
    return api, Entry


def _windows_birth(api, handle):
    import ctypes
    from ctypes import wintypes
    result = api.WaitForSingleObject(handle, 0)
    if result == 0:
        return None
    if result != 258:
        raise ctypes.WinError(ctypes.get_last_error())
    stamps = [wintypes.FILETIME() for _ in range(4)]
    if not api.GetProcessTimes(handle, *(ctypes.byref(value) for value in stamps)):
        raise ctypes.WinError(ctypes.get_last_error())
    return str((stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime)


def _linux_info(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[1]), fields[19] if fields[0] != "Z" else ""
    except (OSError, ValueError, IndexError):
        return None


def birth(pid):
    """Return the same live start identity used by the run registry."""
    if os.name == "nt":
        api, _ = _windows()
        handle = api.OpenProcess(0x1000 | 0x100000, False, int(pid))
        if not handle:
            return None
        try:
            return _windows_birth(api, handle)
        finally:
            api.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        item = _linux_info(int(pid))
        return item[1] or None if item else None
    result = subprocess.run(["ps", "-p", str(int(pid)), "-o", "lstart=", "-o", "stat="],
                            capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    return " ".join(value.split()[:-1]) if result.returncode == 0 and value and not value.split()[-1].startswith("Z") else None


def birth_matches(actual, expected):
    """Accept legacy Unix registry timestamps which included volatile ps state."""
    if not actual or not isinstance(actual, str) or not isinstance(expected, str):
        return False
    if os.name == "nt" or sys.platform.startswith("linux"):
        return actual == expected
    def stable(value):
        fields = value.split()
        if fields and re.fullmatch(r"[RSDTtWXIZU][<NLsl+]*", fields[-1]):
            fields.pop()
        return " ".join(fields)
    return stable(actual) == stable(expected)


def snapshot():
    """Enumerate parents and start identities without inspecting process arguments."""
    result = {}
    if os.name == "nt":
        import ctypes
        api, Entry = _windows()
        handle = api.CreateToolhelp32Snapshot(0x2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(entry)
            more = api.Process32FirstW(handle, ctypes.byref(entry))
            if not more and ctypes.get_last_error() != 18:
                raise ctypes.WinError(ctypes.get_last_error())
            while more:
                pid = int(entry.th32ProcessID)
                if pid:
                    process = api.OpenProcess(0x1000 | 0x100000, False, pid)
                    token = None
                    if process:
                        try:
                            token = _windows_birth(api, process)
                        finally:
                            api.CloseHandle(process)
                        if token is not None:
                            result[pid] = ProcessIdentity(pid, token, int(entry.th32ParentProcessID))
                    elif ctypes.get_last_error() != 87:
                        result[pid] = ProcessIdentity(pid, "", int(entry.th32ParentProcessID))
                more = api.Process32NextW(handle, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            api.CloseHandle(handle)
    elif sys.platform.startswith("linux"):
        for path in Path("/proc").iterdir():
            if path.name.isdigit():
                item = _linux_info(int(path.name))
                if item and item[1]:
                    result[int(path.name)] = ProcessIdentity(int(path.name), item[1], item[0])
    else:
        values = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, check=True)
        for line in values.stdout.splitlines():
            pid, parent = map(int, line.split())
            result[pid] = ProcessIdentity(pid, birth(pid) or "", parent)
    return result


def _protected(table):
    protected = {os.getpid()}
    current = table.get(os.getpid())
    while current and current.parent > 0 and current.parent not in protected:
        protected.add(current.parent)
        current = table.get(current.parent)
    # Always protect the direct parent even if enumeration missed this process.
    protected.add(os.getppid())
    return protected


def _descendant(parent, child):
    if not parent.birth or not child.birth:
        return False
    if os.name == "nt" or sys.platform.startswith("linux"):
        return int(child.birth) >= int(parent.birth)
    # ps lstart has second precision on non-Linux Unix; birth rechecks still
    # guard signals, but same-second PID reuse needs a native identity API.
    started = lambda value: datetime.strptime(" ".join(value.split()[:5]), "%a %b %d %H:%M:%S %Y")
    return started(child.birth) >= started(parent.birth)


def _family(roots, table):
    children = {}
    for item in table.values():
        children.setdefault(item.parent, []).append(item)
    selected = dict(roots)
    pending = list(roots.values())
    while pending:
        parent = pending.pop()
        for child in children.get(parent.pid, ()):
            if child.pid in selected:
                continue
            if not child.birth:
                raise ValueError("Cannot verify descendant process " + str(child.pid))
            if _descendant(parent, child):
                child = replace(child, run_ids=parent.run_ids)
                selected[child.pid] = child
                pending.append(child)
    return selected


def plan(records):
    """Freeze verified registry roots and their descendants for confirmation."""
    table, roots = snapshot(), {}
    for record in records:
        if not isinstance(record, dict) or not any(key in record for key in ("pid", "child_pid")):
            raise ValueError("Invalid tracked process identity")
        for pid_key, birth_key in (("pid", "birth"), ("child_pid", "child_birth")):
            pid, token = record.get(pid_key), record.get(birth_key)
            if pid_key not in record and birth_key not in record:
                continue
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or not isinstance(token, str) or not token:
                raise ValueError("Invalid tracked process identity")
            item = table.get(pid)
            if item and not item.birth:
                raise ValueError("Cannot verify tracked process " + str(pid))
            if item and birth_matches(item.birth, token) and birth_matches(birth(pid), token):
                run_ids = tuple(sorted(set(roots.get(pid, item).run_ids + (str(record.get("run_id", "")),))))
                roots[pid] = replace(item, run_ids=run_ids)
    selected = _family(roots, table)
    if selected.keys() & _protected(table):
        raise ValueError("Reload would stop its own process or an ancestor; run it from a separate terminal")
    return tuple(selected[pid] for pid in sorted(selected))


def _shutdown_order(targets):
    by_pid = {item.pid: item for item in targets}
    def depth(item):
        seen = {item.pid}
        while item.parent in by_pid and item.parent not in seen:
            seen.add(item.parent)
            item = by_pid[item.parent]
        return len(seen)
    return sorted(targets, key=depth, reverse=True)


def _windows_stop(targets, timeout):
    import ctypes
    api, _ = _windows()
    handles = []
    try:
        # Open and verify every handle before stopping anything. A handle
        # remains attached to its original process even if the PID is reused.
        for item in targets:
            handle = api.OpenProcess(0x1000 | 0x100000 | 0x1, False, item.pid)
            if not handle:
                code = ctypes.get_last_error()
                if code == 87:  # The original process already exited.
                    continue
                raise ctypes.WinError(code)
            handles.append((item, handle))
            if _windows_birth(api, handle) != item.birth:
                api.CloseHandle(handle)
                handles.pop()
        for item, handle in handles:
            if _windows_birth(api, handle) == item.birth and not api.TerminateProcess(handle, 1):
                # It may have exited between the identity check and terminate.
                if api.WaitForSingleObject(handle, 0) != 0:
                    raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + timeout
        for item, handle in handles:
            wait = api.WaitForSingleObject(handle, max(0, int((deadline - time.monotonic()) * 1000)))
            if wait != 0:
                raise ValueError("Process shutdown incomplete for PID " + str(item.pid) + "; nothing reopened")
    finally:
        for _, handle in handles:
            api.CloseHandle(handle)


def _unix_stop(targets, timeout, force):
    descriptors = {}
    try:
        for item in targets:
            if birth(item.pid) != item.birth:
                continue
            if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                try:
                    descriptors[item.pid] = os.pidfd_open(item.pid)
                except ProcessLookupError:
                    continue
                except OSError as exc:
                    if exc.errno not in {errno.ENOSYS, errno.EINVAL}:
                        raise
                if birth(item.pid) != item.birth:
                    continue
        def send(item, signum):
            if birth(item.pid) != item.birth:
                return
            try:
                if item.pid in descriptors:
                    signal.pidfd_send_signal(descriptors[item.pid], signum)
                else:
                    # Unix without pidfds has a check/signal race. A native
                    # handle API is the upgrade path; never signal a group.
                    os.kill(item.pid, signum)
            except ProcessLookupError:
                pass
        def wait():
            deadline = time.monotonic() + timeout
            remaining = [item for item in targets if birth(item.pid) == item.birth]
            while remaining and time.monotonic() < deadline:
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                remaining = [item for item in remaining if birth(item.pid) == item.birth]
            return remaining
        # Check permission for the entire selected family before sending any
        # terminating signal; an elevated child must not cause a partial stop.
        for item in targets:
            send(item, 0)
        for item in targets:
            send(item, signal.SIGTERM)
        remaining = wait()
        if remaining and force:
            for item in remaining:
                send(item, signal.SIGKILL)
            remaining = wait()
        if remaining:
            raise ValueError("Process shutdown incomplete for PID(s) " + ", ".join(str(item.pid) for item in remaining) + "; nothing reopened")
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)


def stop(targets, timeout=5.0, force=False):
    """Stop only verified targets, or fail before reopening any sessions."""
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Shutdown timeout must be positive and finite")
    targets = tuple(targets)
    if any(not isinstance(item, ProcessIdentity) or not isinstance(item.pid, int)
           or isinstance(item.pid, bool) or item.pid <= 1 or not isinstance(item.birth, str)
           or not item.birth for item in targets):
        raise ValueError("Invalid shutdown target")
    if len({item.pid for item in targets}) != len(targets):
        raise ValueError("Duplicate shutdown target")
    if not targets:
        return
    table = snapshot()
    if {item.pid for item in targets} & _protected(table):
        raise ValueError("Reload would stop its own process or an ancestor; run it from a separate terminal")
    if any(table.get(item.pid) and not table[item.pid].birth for item in targets):
        raise ValueError("Cannot verify tracked shutdown process; nothing reopened")
    live = {item.pid: item for item in targets if table.get(item.pid) and table[item.pid].birth == item.birth}
    current = _family(live, table)
    if current.keys() - live.keys():
        raise ValueError("Tracked process family changed after confirmation; preview and confirm reload again")
    # A family can spawn after this last enumeration. Its membership cannot be
    # frozen cross-platform with stdlib; only confirmed identities are stopped.
    ordered = _shutdown_order(live.values())
    if os.name == "nt":
        _windows_stop(ordered, timeout)
    else:
        _unix_stop(ordered, timeout, force)
