#!/usr/bin/env python3
"""Stdlib runtime check: python test-snapshot-console.py. No windows or agents."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib/cly"))
import workflows as w


def console_info():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    api.GetConsoleProcessList.restype = wintypes.DWORD
    api.GetConsoleWindow.argtypes = []
    api.GetConsoleWindow.restype = wintypes.HWND
    api.GetStdHandle.argtypes = [wintypes.DWORD]
    api.GetStdHandle.restype = wintypes.HANDLE
    api.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.GetConsoleMode.restype = wintypes.BOOL
    values = (wintypes.DWORD * 64)()
    count = api.GetConsoleProcessList(values, len(values))
    assert count <= len(values), "Disposable test console unexpectedly contains over 64 processes"
    modes = []
    for number in (-10, -11, -12):
        mode = wintypes.DWORD()
        modes.append(bool(api.GetConsoleMode(api.GetStdHandle(number), ctypes.byref(mode))))
    return {"pid": os.getpid(), "processes": list(values[:count]), "window": api.GetConsoleWindow(),
            "modes": modes, "isatty": [stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)],
            "options": w.agent_console()}


def fixture():
    mode, receipt, parent = sys.argv[2:5]
    if mode == "probe":
        value = console_info()
        run_id = os.environ.get("CLY_RUN_ID")
        record = w.read(w.state() / "runs" / (run_id + ".json")) if run_id else None
        value["managed"] = bool(record and record.get("profile") == "console-probe")
        value["supervisor"] = record.get("pid") if record else None
        Path(receipt).write_text(json.dumps(value), encoding="utf-8")
        if os.environ.get("CLY_CONSOLE_CAPTURE") == "1":
            print("cly-console-stdout-marker")
            print("cly-console-stderr-marker", file=sys.stderr)
        return
    if mode != "headless":
        # This test host inherits the tool's redirected handles. Model an
        # interactive terminal's stdio using its private in-memory console.
        assert console_info()["processes"] == [os.getpid()], "ConPTY fixture is not isolated"
        import msvcrt
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        api.SetStdHandle.restype = wintypes.BOOL
        for name, number, device, direction in (("stdin", -10, "CONIN$", "r"),
                                                ("stdout", -11, "CONOUT$", "w"),
                                                ("stderr", -12, "CONOUT$", "w")):
            stream = open(device, direction, encoding="utf-8")
            assert api.SetStdHandle(number, msvcrt.get_osfhandle(stream.fileno()))
            setattr(sys, name, stream)
    Path(parent).write_text(json.dumps(console_info()), encoding="utf-8")
    if mode == "legacy":
        # Reproduce the former bug through the real workflow supervisor.
        w.agent_console = w.hidden
        code = w.main(["run", "--profile", "console-probe", "--kind", "codex", "--bypass", "0", "--",
                       os.environ["CLY_PYTHON"], str(Path(__file__)), "--fixture", "probe", receipt, parent])
    else:
        command = w.cly_command(["--here", "console-probe", str(Path(__file__)), "--fixture", "probe", receipt, parent])
        options = w.agent_console()
        options.update(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        if mode == "redirected":
            # Console attachment must survive pipes/files replacing stdio.
            options.update(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = subprocess.run(command, check=False, timeout=20, **options)
        code = result.returncode
        if mode == "redirected":
            assert b"cly-console-stdout-marker" in result.stdout and b"cly-console-stderr-marker" in result.stderr, "Redirected batch launch lost captured output"
        if code and mode == "redirected":
            print(result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace"), file=sys.stderr)
    raise SystemExit(code)


def cleanup(environment, pid=None):
    """Stop only verified disposable processes under this test's own state."""
    records = [w.read(path) for path in (Path(environment["CLY_STATE_HOME"]) / "runs").glob("*.json")]
    token = w.birth(pid) if pid else None
    if token:
        records.append({"pid": pid, "birth": token, "run_id": "console-fixture"})
    w.processes.stop(w.processes.plan(records), timeout=2, force=True)


def conpty(command, environment, directory):
    """Run a finite disposable client in an in-memory Windows pseudoconsole."""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    size_t = ctypes.c_size_t

    class Coord(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class Startup(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.POINTER(wintypes.BYTE)), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class StartupEx(ctypes.Structure):
        _fields_ = [("StartupInfo", Startup), ("lpAttributeList", ctypes.c_void_p)]

    class Information(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    api.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p, wintypes.DWORD]
    api.CreatePipe.restype = wintypes.BOOL
    api.CreatePseudoConsole.argtypes = [Coord, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    api.CreatePseudoConsole.restype = wintypes.LONG
    api.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
    api.ClosePseudoConsole.restype = None
    api.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(size_t)]
    api.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    api.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, size_t, ctypes.c_void_p, size_t, ctypes.c_void_p, ctypes.c_void_p]
    api.UpdateProcThreadAttribute.restype = wintypes.BOOL
    api.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    api.DeleteProcThreadAttributeList.restype = None
    api.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                 wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                 ctypes.POINTER(StartupEx), ctypes.POINTER(Information)]
    api.CreateProcessW.restype = wintypes.BOOL
    api.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    api.ReadFile.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.GetExitCodeProcess.restype = wintypes.BOOL
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL

    pipes, pseudo, info, attribute, reader = [], wintypes.HANDLE(), Information(), None, None
    output = bytearray()
    try:
        for _ in range(2):
            read, write = wintypes.HANDLE(), wintypes.HANDLE()
            if not api.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            pipes.extend([read.value, write.value])
        result = api.CreatePseudoConsole(Coord(100, 30), pipes[0], pipes[3], 0, ctypes.byref(pseudo))
        if result < 0:
            raise OSError("CreatePseudoConsole failed: " + hex(result & 0xffffffff))
        def drain():
            buffer, count = ctypes.create_string_buffer(8192), wintypes.DWORD()
            while api.ReadFile(pipes[2], buffer, len(buffer), ctypes.byref(count), None):
                output.extend(buffer.raw[:count.value])
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        size = size_t()
        api.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attribute = ctypes.create_string_buffer(size.value)
        if not api.InitializeProcThreadAttributeList(attribute, 1, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        # HPCON is the attribute value itself, not a pointer to an HPCON.
        if not api.UpdateProcThreadAttribute(attribute, 0, 0x00020016, pseudo, ctypes.sizeof(pseudo), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = StartupEx()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.lpAttributeList = ctypes.cast(attribute, ctypes.c_void_p)
        text = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        env = ctypes.create_unicode_buffer("\0".join(key + "=" + value for key, value in sorted(environment.items())) + "\0\0")
        if not api.CreateProcessW(command[0], text, None, None, False, 0x00080000 | 0x00000400, env, str(directory),
                                  ctypes.byref(startup), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        for index in (0, 3):
            api.CloseHandle(pipes[index])
            pipes[index] = None
        assert api.WaitForSingleObject(info.hProcess, 30000) == 0, "Disposable ConPTY fixture timed out"
        code = wintypes.DWORD()
        assert api.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        assert code.value == 0, output.decode(errors="replace")
    finally:
        cleanup_error = None
        try:
            # Only this test's isolated registry and disposable host are in
            # scope. A failed client may leave a detached supervisor behind.
            cleanup(environment, info.dwProcessId if info.hProcess else None)
        except (OSError, ValueError) as exc:
            cleanup_error = exc
        if info.hProcess:
            if api.WaitForSingleObject(info.hProcess, 0) == 258:
                api.TerminateProcess(info.hProcess, 1)
                api.WaitForSingleObject(info.hProcess, 5000)
            api.CloseHandle(info.hProcess)
        if info.hThread:
            api.CloseHandle(info.hThread)
        if attribute is not None:
            api.DeleteProcThreadAttributeList(attribute)
        if pseudo:
            api.ClosePseudoConsole(pseudo)
        if reader:
            reader.join(timeout=5)
        for handle in pipes:
            if handle:
                api.CloseHandle(handle)
        if cleanup_error:
            raise AssertionError("Disposable process cleanup failed: " + str(cleanup_error)) from cleanup_error


def main():
    if os.name != "nt":
        assert w.agent_console() == {}
        print("Windows ConPTY runtime check skipped on this platform")
        return
    python = sys.executable
    bash = os.environ.get("CLY_SHELL") or r"C:\Program Files\Git\bin\bash.exe"
    assert Path(bash).is_file() or shutil.which(bash), "Git Bash is required for the actual managed-launch check"
    with tempfile.TemporaryDirectory(prefix="cly-console-") as temporary:
        directory = Path(temporary)
        config = directory / "config"
        batch = directory / "probe.cmd"
        batch.write_text('@echo off\n"' + python + '" %*\n', encoding="utf-8")
        env = dict(os.environ, CLY_CONFIG=str(config), CLY_PYTHON=python, CLY_SHELL=bash, CLY_TRACK="1",
                   CLY_STATE_HOME=str(directory / "state"), CODEX_HOME=str(directory / "codex"),
                   MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")
        for name in ("CLY_BIN", "CLY_FLAGS", "CLY_DIR", "CLY_DOCUMENT_JOB", "CLY_WORKFLOW_QUERY"):
            env.pop(name, None)
        results = {}
        cases = [("exe", mode) for mode in ("inherited", "redirected", "legacy", "headless")]
        cases += [("cmd", mode) for mode in ("inherited", "redirected", "headless")]
        for form, mode in cases:
            label = form + "-" + mode
            executable = python if form == "exe" else str(batch)
            config.write_text("profile.console-probe.bin=" + executable.replace("\\", "/") + "\n"
                              "profile.console-probe.kind=codex\nprofile.console-probe.dir=none\n"
                              "profile.console-probe.flags=\n", encoding="utf-8")
            receipt, parent = directory / (label + ".json"), directory / (label + "-parent.json")
            command = [python, str(Path(__file__)), "--fixture", mode, str(receipt), str(parent)]
            env["CLY_CONSOLE_CAPTURE"] = "1" if mode in {"redirected", "headless"} else "0"
            if mode == "headless":
                try:
                    result = subprocess.run(command, env=env, cwd=directory, capture_output=True, check=True, timeout=30, **w.hidden())
                    assert b"cly-console-stdout-marker" in result.stdout and b"cly-console-stderr-marker" in result.stderr, label + " lost captured output"
                finally:
                    cleanup(env)
            else:
                conpty(command, env, directory)
            value = json.loads(receipt.read_text(encoding="utf-8"))
            host = json.loads(parent.read_text(encoding="utf-8"))
            assert value["managed"], mode + " bypassed the real managed supervisor"
            if mode != "headless":
                assert host["processes"] == [host["pid"]], "ConPTY fixture unexpectedly shares another session's console"
            if mode in {"inherited", "redirected"}:
                assert host["processes"] and value["processes"], mode + " lost console attachment"
                assert value["window"] == host["window"], mode + " opened another console"
                assert value["supervisor"] in value["processes"], mode + " separated child from supervisor console"
                assert value["options"] == {}, mode + " still requests CREATE_NO_WINDOW"
                assert value["modes"] == ([True] * 3 if mode == "inherited" else [False] * 3), (mode, host, value)
            else:
                assert value["window"] is None, (mode, host, value)
                assert value["options"] == ({} if value["processes"] else w.hidden()), mode
                if mode == "legacy":
                    assert not any(value["modes"]), "Legacy no-window launch retained console stdio unexpectedly"
                    assert value["supervisor"] not in value["processes"], "Legacy child unexpectedly kept its parent's console"
            if mode == "headless":
                assert host["window"] is None, "Headless host opened a console window"
                assert host["options"] == ({} if host["processes"] else w.hidden()), "Headless host changed console attachment"
            results[label] = {"parent_console_window": bool(host["window"]), "child_console_window": bool(value["window"]),
                             "stdio_console_modes": value["modes"],
                             "same_console": value["window"] == host["window"] if host["window"] else None,
                             "managed": value["managed"]}
        assert not list((directory / "state/runs").glob("*.json")), "Disposable run registry was not cleaned up"
        print(json.dumps(results, indent=2))
        print("Windows ConPTY managed-launch check passed; no desktop windows or real agents launched")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fixture":
        fixture()
    else:
        main()
