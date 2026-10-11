"""Discover interactive native clients without input, focus changes or dependencies.

Windows console access runs in a hidden helper so AttachConsole never detaches
the caller. Only allowlisted environment values and binding evidence persist.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

import processes
import profiles
import sessions

ENVIRONMENT = tuple(profiles.STORE_VARIABLES.values()) + ("XDG_DATA_HOME", "CLY_RUN_ID", "CLY_STATE_HOME")
CLIENT_NAMES = re.compile(r"^(codex|claude|gemini|kimi|qwen|opencode|node|muse(?:-bin-[\w.-]+)?)(?:\.exe)?$", re.I)


def windows_details(pid):
    """Read 64-bit native process parameters; never scan arbitrary memory."""
    from ctypes import wintypes as t
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [t.DWORD, t.BOOL, t.DWORD]
    api.OpenProcess.restype = t.HANDLE
    api.CloseHandle.argtypes = [t.HANDLE]
    api.ReadProcessMemory.argtypes = [t.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    api.IsWow64Process.argtypes = [t.HANDLE, ctypes.POINTER(t.BOOL)]
    handle = api.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        wow = t.BOOL()
        if ctypes.sizeof(ctypes.c_void_p) != 8 or not api.IsWow64Process(handle, ctypes.byref(wow)) or wow.value:
            raise ValueError("Native inspection requires a 64-bit Python and client")
        def memory(address, size, partial=False):
            data, count = ctypes.create_string_buffer(size), ctypes.c_size_t()
            ok = api.ReadProcessMemory(handle, address, data, size, ctypes.byref(count))
            if not ok and not (partial and count.value):
                raise ctypes.WinError(ctypes.get_last_error())
            return data.raw[:count.value]
        def pointer(data, offset):
            return int.from_bytes(data[offset:offset + 8], "little")
        query = ctypes.WinDLL("ntdll").NtQueryInformationProcess
        query.argtypes = [t.HANDLE, t.ULONG, ctypes.c_void_p, t.ULONG, ctypes.POINTER(t.ULONG)]
        info = (ctypes.c_void_p * 6)()
        if query(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None):
            raise ValueError("Native process parameters unavailable")
        params = memory(pointer(memory(info[1], 0x28), 0x20), 0x88)
        def string(offset):
            length = int.from_bytes(params[offset:offset + 2], "little")
            if length > 65534 or length % 2:
                raise ValueError("Invalid native process string")
            return memory(pointer(params, offset + 8), length).decode("utf-16le") if length else ""
        command = string(0x70)
        shell = ctypes.WinDLL("shell32")
        shell.CommandLineToArgvW.argtypes = [t.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype = ctypes.POINTER(t.LPWSTR)
        count = ctypes.c_int()
        args = shell.CommandLineToArgvW(command, ctypes.byref(count))
        if not args:
            raise ctypes.WinError(ctypes.get_last_error())
        api.LocalFree.argtypes = [ctypes.c_void_p]
        try:
            argv = list(args[:count.value])
        finally:
            api.LocalFree(args)
        # Bound the environment read and discard all credentials immediately.
        raw, address = b"", pointer(params, 0x80)
        for offset in range(0, 131072, 4096):
            raw += memory(address + offset, 4096, partial=True)
            text = raw[:len(raw) // 2 * 2].decode("utf-16le", errors="replace")
            if "\0\0" in text:
                break
        else:
            raise ValueError("Native environment exceeds inspection limit")
        environment = {}
        for entry in text.split("\0\0", 1)[0].split("\0"):
            name, separator, value = entry.partition("=")
            if separator and name.upper() in ENVIRONMENT:
                environment[name.upper()] = value
        return {"pid": pid, "argv": argv, "directory": string(0x38), "environment": environment}
    finally:
        api.CloseHandle(handle)


def windows_console(pid):
    from ctypes import wintypes as t
    class Coord(ctypes.Structure):
        _fields_ = [("X", t.SHORT), ("Y", t.SHORT)]
    class Rect(ctypes.Structure):
        _fields_ = [("Left", t.SHORT), ("Top", t.SHORT), ("Right", t.SHORT), ("Bottom", t.SHORT)]
    class Info(ctypes.Structure):
        _fields_ = [("size", Coord), ("cursor", Coord), ("attrs", t.WORD), ("window", Rect), ("max_size", Coord)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.AttachConsole.argtypes = [t.DWORD]
    api.GetConsoleProcessList.argtypes = [ctypes.POINTER(t.DWORD), t.DWORD]
    api.CreateFileW.argtypes = [t.LPCWSTR, t.DWORD, t.DWORD, ctypes.c_void_p, t.DWORD, t.DWORD, t.HANDLE]
    api.CreateFileW.restype = t.HANDLE
    api.GetConsoleScreenBufferInfo.argtypes = [t.HANDLE, ctypes.POINTER(Info)]
    api.ReadConsoleOutputCharacterW.argtypes = [t.HANDLE, t.LPWSTR, t.DWORD, Coord, ctypes.POINTER(t.DWORD)]
    api.CloseHandle.argtypes = [t.HANDLE]
    api.FreeConsole()
    if not api.AttachConsole(pid):
        return None  # Headless clients and app servers are not terminal sessions.
    handle = None
    try:
        pids = (t.DWORD * 256)()
        count = api.GetConsoleProcessList(pids, len(pids))
        if count > len(pids) or pid not in pids[:count]:
            raise ValueError("Console process identity changed during inspection")
        handle = api.CreateFileW("CONOUT$", 0x80000000, 3, None, 3, 0, None)
        info = Info()
        if not api.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Bounded current screen/scrollback, not an unbounded transcript scan.
        start = max(0, info.window.Bottom - 200)
        size = min(info.size.X * (info.window.Bottom - start + 1), 131072)
        data, used = ctypes.create_unicode_buffer(size + 1), t.DWORD()
        if not api.ReadConsoleOutputCharacterW(handle, data, size, Coord(0, start), ctypes.byref(used)):
            raise ctypes.WinError(ctypes.get_last_error())
        return "\n".join(data.value[i:i + info.size.X].rstrip() for i in range(0, used.value, info.size.X))
    finally:
        if handle is not None:
            api.CloseHandle(handle)
        api.FreeConsole()


def probe():
    """Return live client metadata, never execute providers or send input."""
    rows = []
    if os.name == "nt":
        api, Entry = processes._windows()
        handle = api.CreateToolhelp32Snapshot(0x2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        candidates = []
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(entry)
            more = api.Process32FirstW(handle, ctypes.byref(entry))
            while more:
                if CLIENT_NAMES.fullmatch(entry.szExeFile):
                    candidates.append(int(entry.th32ProcessID))
                more = api.Process32NextW(handle, ctypes.byref(entry))
        finally:
            api.CloseHandle(handle)
        for pid in candidates:
            token = processes.birth(pid)
            if not token:
                continue
            try:
                row = windows_details(pid)
                if client(row["argv"]) is None:
                    continue
                screen = windows_console(pid)
                if not screen or not screen.strip():
                    continue
                row.update(screen=screen, birth=token)
                if processes.birth_matches(processes.birth(pid), token):
                    rows.append(row)
            except (OSError, ValueError):
                # Exiting/inaccessible candidates cannot be safely adopted.
                # Existing registry records remain unresolved and block reload.
                continue
    elif sys.platform.startswith("linux"):
        for path in Path("/proc").iterdir():
            if not path.name.isdigit():
                continue
            try:
                argv = [value.decode() for value in (path / "cmdline").read_bytes().split(b"\0") if value]
                if client(argv) is None or not (path / "fd/0").resolve().as_posix().startswith("/dev/pts/"):
                    continue
                environment = {}
                for entry in (path / "environ").read_bytes().split(b"\0"):
                    name, separator, value = entry.partition(b"=")
                    if separator and name.decode() in ENVIRONMENT:
                        environment[name.decode()] = value.decode()
                pid = int(path.name)
                rows.append({"pid": pid, "birth": processes.birth(pid), "argv": argv,
                             "directory": str((path / "cwd").resolve()), "environment": environment, "screen": None})
            except (OSError, UnicodeError):
                continue
    return rows


def client(argv):
    """Identify terminal providers; exclude headless work and shared servers."""
    if not argv:
        return None
    executable = re.split(r"[/\\]", argv[0])[-1].lower().removesuffix(".exe")
    arguments = argv[1:]
    if executable == "node":
        if not arguments:
            return None
        script = arguments[0].replace("\\", "/").lower()
        executable = next((kind for package, kind in (("@openai/codex", "codex"), ("@anthropic-ai/claude-code", "claude"),
                          ("@google/gemini-cli", "gemini"), ("@qwen-code/qwen-code", "qwen")) if package in script), "")
        arguments = arguments[1:]
    if executable.startswith("muse-bin-"):
        executable = "muse"
    if executable not in sessions.KINDS:
        return None
    # These tokens are commands only before positional input. Conservatively
    # exclude ambiguous launches rather than adopting tools as user terminals.
    if executable == "codex" and any(token in {"app-server", "exec", "e", "review", "remote-control", "mcp-server", "debug", "login", "doctor"} for token in arguments):
        return None
    if executable in {"claude", "gemini", "qwen"} and any(token in {"--print", "-p"} or token.startswith("--print=") for token in arguments):
        return None
    return executable, arguments


def canonical(value):
    return os.path.normcase(os.path.abspath(str(sessions.native_path(value))))


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def console_session(record, screen, items):
    """Require unique matching user AND assistant prose, not timestamps.

    This fallback has a ceiling: hidden/collapsed or identical fork histories
    cannot identify a client. Native lifecycle/client identity is preferred;
    ambiguity remains a preflight failure instead of reopening the wrong chat.
    """
    if not screen:
        return None
    visible = normalized(screen)
    matches = []
    for item in items:
        if canonical(item["directory"]) != canonical(record["directory"]):
            continue
        try:
            source = sessions.claude_codex(Path(item["source"]), record["kind"])
        except (OSError, ValueError):
            continue
        if not source:
            continue
        roles = set()
        for message in source["messages"]:
            content = normalized(message["content"])
            # Long independent anchors tolerate wrapping/Markdown. Short generic
            # confirmations and tool output never establish conversation identity.
            if len(content) >= 96 and any(content[start:start + 96] in visible for start in range(0, min(len(content) - 95, 2048), 96)):
                roles.add(message["role"])
        if {"user", "assistant"}.issubset(roles):
            matches.append(item["session_id"])
    return matches[0] if len(matches) == 1 else None


def empty_codex(screen):
    """Only a recognizable pristine welcome screen is a new-session restore."""
    if not screen or not re.search(r"OpenAI Codex\s*\(v[\w.-]+\)", screen):
        return False
    prompts = [line.strip()[1:].strip() for line in screen.splitlines() if line.strip().startswith("›")]
    return bool(prompts) and all(prompt in {"Ask Codex to do anything", ""} for prompt in prompts) and not re.search(r"^\s*[•◦]\s", screen, re.M)


def capture(records):
    import workflows as w
    if os.environ.get("CLY_NATIVE_DISCOVERY", "1") == "0":
        return records
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe"], capture_output=True,
                                text=True, encoding="utf-8", check=True, timeout=30, **w.hidden())
        rows = json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("Native terminal discovery failed; current sessions preserved") from exc
    if not rows:
        return records
    table = processes.snapshot()
    roots = {record[key]: record for record in records for key in ("pid", "child_pid") if key in record}
    entries = profiles.discover(configured_only=True)
    for row in rows:
        parent, seen, owner = row["pid"], set(), None
        while parent and parent not in seen:
            seen.add(parent)
            owner = owner or roots.get(parent)
            parent = table[parent].parent if parent in table else 0
        # A Node launcher and its native executable share one terminal. The
        # leaf client has the authoritative final argv; never create two entries.
        if any(other["pid"] != row["pid"] and table.get(other["pid"]) and table[other["pid"]].parent == row["pid"] for other in rows):
            continue
        if not w.birth_matches(w.birth(row["pid"]), row["birth"]):
            continue
        kind, arguments = client(row["argv"])
        environment = row["environment"]
        run_id = environment.get("CLY_RUN_ID")
        # Terminal launch is asynchronous: a supervisor can publish its run
        # after active() globbed the registry but before the native probe. Read
        # its inherited identity again and verify the live ancestor association.
        if run_id and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", run_id):
            managed = w.read(w.state() / "runs" / (run_id + ".json"))
            if (managed and managed.get("schema") == w.SCHEMA and managed.get("kind") == kind
                    and not managed.get("adopted") and w.alive(managed)
                    and any(managed.get(key) in seen for key in ("pid", "child_pid"))):
                if owner and owner.get("adopted") and owner.get("pid") == row["pid"] and owner.get("birth") == row["birth"]:
                    # Reconcile only our automatically created duplicate for this
                    # exact client; explicit user adoption records are preserved.
                    records.remove(owner)
                    roots = {pid: record for pid, record in roots.items() if record is not owner}
                    w.safe_component(owner["run_id"], "run ID")
                    (w.state() / "runs" / (owner["run_id"] + ".json")).unlink(missing_ok=True)
                    (w.state() / "runtime" / (owner["run_id"] + ".json")).unlink(missing_ok=True)
                owner = next((record for record in records if record["run_id"] == run_id), None)
                if owner is None:
                    owner = w.resolve(managed)
                    records.append(owner)
                for key in ("pid", "child_pid"):
                    if key in owner:
                        roots[owner[key]] = owner
        if owner is None:
            native_state = environment.get("CLY_STATE_HOME")
            if native_state and canonical(native_state) != canonical(w.state()):
                continue
            if not native_state and canonical(w.state()) != canonical(sessions.home() / ".local/state/cly"):
                continue  # Keep explicitly isolated registries isolated.
            store = str(sessions.root(kind, environment))
            compatible = [entry for entry in entries if entry["kind"] == kind and entry["store"] and canonical(entry["store"]) == canonical(store)]
            if len(compatible) != 1:
                raise ValueError("Native " + kind + " terminal PID " + str(row["pid"]) +
                                 " has no unique configured profile/store; snapshot inventory preserved")
            profile = compatible[0]["profile"]
            options = w.resume_options.capture(kind, arguments)
            options["origin"] = "adoption"
            owner = {"schema": w.SCHEMA, "run_id": "native-" + hashlib.sha256((str(row["pid"]) + ":" + row["birth"]).encode()).hexdigest()[:24],
                     "pid": row["pid"], "birth": row["birth"], "profile": profile, "kind": kind,
                     "directory": row["directory"], "native_root": store, "session_id": None,
                     "bypass": w.resume_options.bypass(kind, options), "resume_options": options, "started": w.now(), "adopted": True}
            for index, token in enumerate(arguments[:-1]):
                if kind == "codex" and token in {"--cd", "-C"}:
                    owner["directory"] = str(sessions.native_path(arguments[index + 1]).resolve())
            records.append(owner)
            roots[row["pid"]] = owner
        if owner.get("session_id") and owner.get("binding") != "console-prose":
            continue
        items, _ = w.catalog(owner)
        selected = w.native_id(kind, arguments)
        binding = "native-argv"
        if selected not in {item["session_id"] for item in items}:
            selected = console_session(owner, row.get("screen"), items) if kind in {"codex", "claude"} else None
            binding = "console-prose"
        if selected:
            owner.update(session_id=selected, binding=binding)
            owner.pop("restore_mode", None)
        elif kind == "codex" and empty_codex(row.get("screen")):
            owner.update(session_id=None, restore_mode="new", binding="native-welcome")
            (w.state() / "runtime" / (owner["run_id"] + ".json")).unlink(missing_ok=True)
        else:
            if owner.get("binding") == "console-prose":
                # A clear/switch can invalidate recovered prose identity while
                # the PID stays alive. Never let its cached binding mask that.
                owner["session_id"] = None
                (w.state() / "runtime" / (owner["run_id"] + ".json")).unlink(missing_ok=True)
            owner.pop("restore_mode", None)
            if owner.get("binding") == "native-welcome":
                owner["binding"] = None
            owner["discovery_reason"] = "Native client identity is not yet readable or console prose is ambiguous"
        if owner.get("adopted"):
            w.atomic(w.state() / "runs" / (owner["run_id"] + ".json"), owner)
        # For managed clients the supervisor owns its registry. Keep recovered
        # bindings separate so its final child-PID write cannot overwrite them.
        if selected:
            w.atomic(w.state() / "runtime" / (owner["run_id"] + ".json"), {"schema": 1, "run_id": owner["run_id"],
                     "kind": kind, "session_id": selected, "binding": binding, "pid": row["pid"], "birth": row["birth"]})
        w.resolve(owner)
    return records


def apply(record, state_root):
    import workflows as w
    event = w.read(state_root / "runtime" / (record["run_id"] + ".json"))
    if event:
        if (event.get("schema") != 1 or event.get("run_id") != record["run_id"] or event.get("kind") != record["kind"]
                or not isinstance(event.get("session_id"), str) or not sessions.ID_RE.fullmatch(event["session_id"])
                or not isinstance(event.get("pid"), int) or isinstance(event["pid"], bool) or event["pid"] <= 1
                or not isinstance(event.get("birth"), str) or not event["birth"]
                or event.get("binding") not in {"native-argv", "console-prose"}):
            raise ValueError("Invalid runtime session binding")
        if w.birth_matches(w.birth(event.get("pid")), event.get("birth")):
            record.update(session_id=event["session_id"], binding=event["binding"])
    return record


if __name__ == "__main__":
    if sys.argv[1:] != ["--probe"]:
        raise SystemExit("Usage: runtime.py --probe")
    print(json.dumps(probe(), ensure_ascii=True))
