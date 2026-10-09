"""A single automatic checkpoint and opt-in, deduplicated login restore."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


TERMINALS = ("auto", "wt", "terminal", "tmux", "gnome-terminal", "konsole", "x-terminal-emulator")
CONTROLS = ("CLY_CONFIG", "CLY_STATE_HOME", "CLY_LIBRARY_HOME", "CLY_PYTHON", "CLY_SHELL", "CLY_TRACK",
            "CLAUDE_CONFIG_DIR", "CODEX_HOME", "GEMINI_CLI_HOME", "KIMI_CODE_HOME", "QWEN_HOME", "CLY_MUSE_HOME", "CLY_OPENCODE_HOME")
FIELDS = ("profile", "kind", "session_id", "directory", "native_root", "bypass", "resume_options", "binding", "bindings")


def folder(w):
    return w.state() / "snapshot-auto"


def boot_id(w):
    """Use an OS boot identity, rather than estimating from the wall clock."""
    if os.name == "nt":
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                   "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')"]
    elif sys.platform.startswith("linux"):
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not value:
            raise ValueError("OS boot identity is unavailable")
        return value
    elif sys.platform == "darwin":
        command = ["sysctl", "-n", "kern.boottime"]
    else:
        raise ValueError("Automatic restore is unsupported on this platform")
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30, **w.hidden())
    value = result.stdout.strip()
    if not value:
        raise ValueError("OS boot identity is unavailable")
    return value


def latest(w):
    value = w.read(folder(w) / "latest.json")
    if value is None:
        raise ValueError("No automatic snapshot yet; start tracked sessions and use snapshot auto save")
    value = w.validate_snapshot(value)
    if value.get("automatic") is not True or not isinstance(value.get("boot_id"), str):
        raise ValueError("Invalid automatic snapshot")
    return value


def inventory(records):
    # Keep only restore inputs; native discovery timestamps and PID churn do
    # not create writes. This compares one current inventory, not its history.
    return sorted(json.dumps({key: record.get(key) for key in FIELDS}, sort_keys=True, ensure_ascii=False)
                  for record in records)


def pending_restore(w, boot):
    receipt = w.read(folder(w) / "restore.json", {})
    return receipt.get("boot_id") == boot and receipt.get("status") not in (None, "complete", "same-boot", "no-snapshot", "superseded")


def tick(w, boot=None, explicit=False):
    """Capture changed, nonempty inventories without losing an earlier checkpoint."""
    boot = boot or boot_id(w)
    with w.lock(w.state() / "reload.lock"), w.lock(folder(w) / "checkpoint.lock"):
        records = w.active()
        unresolved = [record.get("profile", "unknown") for record in records
                      if record.get("kind") not in w.sessions.RESUME or not isinstance(record.get("session_id"), str)
                      or not w.sessions.ID_RE.fullmatch(record["session_id"]) or record.get("history_present") is False]
        if unresolved:
            raise ValueError("Automatic checkpoint preserved: waiting for exact readable native sessions: " + ", ".join(unresolved))
        hold = w.read(folder(w) / "hold.json", {})
        manual_ready = False
        if hold.get("status") == "waiting" and hold.get("boot_id") == boot:
            expected = {json.dumps(item) for item in hold["expected"]}
            live = {json.dumps(identity(w, record)) for record in records if record.get("session_id")}
            if not explicit and not expected.issubset(live):
                raise ValueError("Waiting for all manually restored conversations to become active; automatic checkpoint preserved")
            manual_ready = bool(records)
        pending = pending_restore(w, boot)
        if pending and not explicit and not manual_ready:
            raise ValueError("Login restore is incomplete; automatic checkpoint preserved for manual recovery")
        previous = w.read(folder(w) / "latest.json")
        if previous is not None:
            previous = latest(w)
            config = w.read(folder(w) / "config.json", {})
            receipt = w.read(folder(w) / "restore.json", {})
            if (not explicit and not manual_ready and previous["boot_id"] != boot and config.get("enabled") and config.get("restore_on_login")
                    and not (receipt.get("boot_id") == boot and receipt.get("status") in ("complete", "superseded"))):
                raise ValueError("Earlier-boot automatic checkpoint preserved until login restore completes")
            if (not explicit and not manual_ready and previous["boot_id"] != boot and receipt.get("boot_id") == boot
                    and receipt.get("status") == "complete"):
                expected = {identity(w, dict(record, directory=w.restored_directory(record, (), previous.get("host") != w.socket.gethostname())))
                            for record in previous["sessions"]}
                live = {identity(w, record) for record in records if record.get("session_id")}
                if not expected.issubset(live):
                    raise ValueError("Waiting for all restored conversations to become active; earlier checkpoint preserved")
            if not pending and not manual_ready and previous["boot_id"] == boot and inventory(previous["sessions"]) == inventory(records):
                return {"changed": False, "sessions": len(records), "snapshot_id": previous["snapshot_id"]}
        if not records:
            return {"changed": False, "sessions": 0, "retained": True}
        value = w.snapshot_value(records)
        value.update(automatic=True, boot_id=boot)
        w.atomic(folder(w) / "latest.json", value)
        if manual_ready:
            hold.update(status="superseded" if explicit else "complete", finished=w.now())
            w.atomic(folder(w) / "hold.json", hold)
            receipt = w.read(folder(w) / "restore.json", {})
            receipt.update(schema=w.SCHEMA, boot_id=boot, status="superseded", superseded=w.now(), reason="manual-restore",
                           superseded_by_snapshot_id=value["snapshot_id"])
            w.atomic(folder(w) / "restore.json", receipt)
        elif explicit and pending:
            receipt = w.read(folder(w) / "restore.json")
            receipt.update(status="superseded", superseded=w.now(), superseded_by_snapshot_id=value["snapshot_id"])
            w.atomic(folder(w) / "restore.json", receipt)
        return {"changed": True, "sessions": len(records), "snapshot_id": value["snapshot_id"]}


def identity(w, record):
    directory = os.path.normcase(os.path.abspath(os.path.normpath(str(w.sessions.native_path(record["directory"])))))
    root = record.get("native_root")
    store = os.path.normcase(os.path.abspath(os.path.normpath(str(w.sessions.native_path(root))))) if root else ("profile", record.get("profile"))
    return record.get("kind"), record.get("session_id"), store, directory


def entry_key(w, record):
    return hashlib.sha256(json.dumps(identity(w, record)).encode()).hexdigest()


def hold_restore(w, plan):
    """Caller holds reload.lock; preserve checkpoint until its launches are active."""
    with w.lock(folder(w) / "checkpoint.lock"):
        config = w.read(folder(w) / "config.json", {})
        if not config.get("enabled") or not plan:
            return False
        expected = [json.loads(value) for value in sorted({json.dumps(identity(w, item)) for item in plan})]
        w.atomic(folder(w) / "hold.json", {"schema": w.SCHEMA, "boot_id": boot_id(w), "status": "waiting",
                                          "started": w.now(), "expected": expected})
        return True


def restore_login(w, config, boot):
    """Reopen missing conversations once per boot; never terminate live agents."""
    with w.lock(w.state() / "reload.lock"), w.lock(folder(w) / "checkpoint.lock"):
        path = folder(w) / "restore.json"
        receipt = w.read(path, {})
        if receipt.get("boot_id") == boot:
            if receipt.get("status") in ("complete", "same-boot", "no-snapshot", "superseded"):
                return receipt
            if receipt.get("status") == "failed" or any(item.get("status") == "attempting" for item in receipt.get("entries", [])):
                raise ValueError("Previous login restore has an uncertain or failed outcome; use manual snapshot restore auto")
        else:
            receipt = {"schema": w.SCHEMA, "boot_id": boot, "started": w.now(), "status": "restoring", "entries": []}
        try:
            value = latest(w)
        except ValueError:
            if not (folder(w) / "latest.json").exists():
                receipt.update(status="no-snapshot", finished=w.now())
                w.atomic(path, receipt)
                return receipt
            raise
        receipt["snapshot_id"] = value["snapshot_id"]
        if value["boot_id"] == boot:
            receipt.update(status="same-boot", finished=w.now())
            w.atomic(path, receipt)
            return receipt
        w.atomic(path, receipt)
        try:
            live = {identity(w, record) for record in w.active() if record.get("session_id")}
            launched = {item["key"] for item in receipt["entries"] if item.get("status") in ("launched", "already-active")}
            records = []
            for record in value["sessions"]:
                restored = dict(record, directory=w.restored_directory(record, (), value.get("host") != w.socket.gethostname()))
                key = entry_key(w, restored)
                if key in launched:
                    continue
                if identity(w, restored) in live:
                    receipt["entries"].append({"key": key, "status": "already-active", "profile": record["profile"],
                                               "kind": record["kind"], "session_id": record.get("session_id")})
                    launched.add(key)
                else:
                    records.append(record)
            # Preflight all missing conversations before opening any terminal.
            plan = w.restore_plan(dict(value, sessions=records)) if records else []
            commands = w.terminal_commands(plan, config["terminal"]) if plan else []
            if len(commands) != len(plan):
                raise ValueError("Terminal preflight returned an incomplete launch plan")
            for item, command in zip(plan, commands):
                if not w.read(folder(w) / "config.json", config).get("enabled"):
                    raise ValueError("Automatic snapshot disabled during login restore; remaining conversations preserved")
                key = entry_key(w, item)
                # A snapshot can contain two profiles bound to one conversation.
                if key in launched or identity(w, item) in {identity(w, record) for record in w.active() if record.get("session_id")}:
                    continue
                entry = {"key": key, "profile": item["profile"], "kind": item["kind"], "session_id": item["session_id"],
                         "status": "attempting", "attempted": w.now()}
                receipt["entries"].append(entry)
                w.atomic(path, receipt)  # An interrupted launch must never be blindly retried.
                w.launch_terminal(command)
                entry.update(status="launched", finished=w.now())
                launched.add(key)
                w.atomic(path, receipt)
            receipt.update(status="complete", finished=w.now())
            w.atomic(path, receipt)
            return receipt
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            receipt.update(status="failed", error=str(exc), finished=w.now())
            w.atomic(path, receipt)
            raise


def worker_status(w):
    value = w.read(folder(w) / "worker.json", {})
    return dict(value, active=bool(value.get("pid") and w.alive(value)))


def status(w):
    config = w.read(folder(w) / "config.json", {})
    result = {"schema": w.SCHEMA, "enabled": bool(config.get("enabled")), "registered": False,
              "interval": config.get("interval", 60), "restore_on_login": config.get("restore_on_login", True),
              "terminal": config.get("terminal", "auto"), "registration_status": config.get("status"),
              "checkpoint": str(folder(w) / "latest.json"), "worker": worker_status(w),
              "restore": w.read(folder(w) / "restore.json"), "hold": w.read(folder(w) / "hold.json")}
    if config.get("enabled"):
        try:
            result["registered"] = w.registered_startup(config["registration"])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            result["error"] = str(exc)
    value = w.read(folder(w) / "latest.json")
    if value is not None:
        result.update(snapshot_id=value.get("snapshot_id"), sessions=len(value.get("sessions", [])), captured=value.get("created"))
    return result


def launcher(w):
    executable = Path(sys.executable)
    if os.name == "nt":
        executable = executable.with_name("pythonw.exe")
        if not executable.is_file():
            raise ValueError("pythonw.exe required for hidden Windows snapshot startup")
    environment = {name: os.environ[name] for name in CONTROLS if name in os.environ}
    for name, value in list(environment.items()):
        if value and name not in ("CLY_TRACK", "CLY_PYTHON", "CLY_SHELL"):
            environment[name] = str(w.sessions.native_path(value).resolve())
    environment.update(CLY_STATE_HOME=str(w.state().resolve()), CLY_TRACK="1",
                       CLY_PYTHON=str(Path(sys.executable).with_name("python.exe") if os.name == "nt" else Path(sys.executable)))
    path = (folder(w) / "startup.py").resolve()
    log = (folder(w) / "watch.log").resolve()
    content = ("import os, sys\nos.environ.update(" + repr(environment) + ")\nsys.path.insert(0, " +
               repr(str(Path(__file__).resolve().parent)) + ")\nimport workflows\nlog = open(" + repr(str(log)) +
               ", 'a', encoding='utf-8', buffering=1)\nos.chmod(" + repr(str(log)) +
               ", 0o600)\nsys.stdout = sys.stderr = log\nraise SystemExit(workflows.main(" +
               repr(["snapshot", "auto", "watch"]) + " + sys.argv[1:]))\n")
    return [str(executable), str(path)], content


def manage(w, args):
    with w.lock(folder(w) / "manage.lock"):
        path = folder(w) / "config.json"
        config = w.read(path, {})
        if args.auto_action == "disable":
            # Stop the worker cooperatively even if an external registration
            # conflict prevents removing our startup command.
            config.update(enabled=False, configured=w.now(), status="pending")
            w.atomic(path, config)
            if config.get("registration"):
                w.set_startup(config["registration"], False)
            config["status"] = "verified"
            w.atomic(path, config)
            return
        if args.interval < 1:
            raise ValueError("Interval must be positive")
        command, content = launcher(w)
        registration = w.startup_registration([*command, "--login"], purpose="snapshot")
        if config.get("enabled") and config.get("registration") != registration:
            raise ValueError("Disable existing snapshot startup before changing its command")
        w.atomic(Path(command[1]), content)
        config = {"schema": w.SCHEMA, "enabled": True, "interval": args.interval,
                  "restore_on_login": not args.no_restore_on_login, "terminal": args.terminal,
                  "configured": w.now(), "status": "pending", "registration": registration}
        w.atomic(path, config)
        w.set_startup(registration, True)
        if not w.registered_startup(registration):
            raise ValueError("Snapshot startup registration verification failed")
        config["status"] = "verified"
        w.atomic(path, config)
        # This invocation starts capture only. Login restoration is reserved for
        # the native startup command and an earlier boot's checkpoint.
        if not worker_status(w)["active"]:
            with (folder(w) / "watch.log").open("a", encoding="utf-8") as log:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         start_new_session=os.name != "nt", **w.hidden())
            deadline = time.monotonic() + 10
            while not worker_status(w)["active"]:
                if child.poll() is not None:
                    raise ValueError("Automatic snapshot worker exited before initialization; inspect snapshot auto status and watch.log")
                if time.monotonic() >= deadline:
                    raise ValueError("Automatic snapshot worker initialization timed out; inspect snapshot auto status and watch.log")
                time.sleep(0.1)


def watch(w, args):
    acquired = False
    try:
        with w.lock(folder(w) / "watch.lock"):
            acquired = True
            path = folder(w) / "worker.json"
            worker = {"schema": w.SCHEMA, "pid": os.getpid(), "birth": w.birth(os.getpid()), "started": w.now(),
                      "status": "starting", "errors": []}
            w.atomic(path, worker)
            try:
                boot = boot_id(w)
                worker.update(boot_id=boot, status="running")
                config = w.read(folder(w) / "config.json", {})
                if args.login and config.get("enabled") and config.get("restore_on_login"):
                    try:
                        worker["restore"] = restore_login(w, config, boot)
                    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                        worker["errors"] = [str(exc)]
                due = 0
                while True:
                    config = w.read(folder(w) / "config.json", {})
                    if not config.get("enabled"):
                        break
                    if time.monotonic() >= due:
                        worker["last_attempt"] = w.now()
                        try:
                            worker.update(tick(w, boot))
                            worker.update(last_success=w.now(), errors=[])
                        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                            worker["errors"] = [str(exc)]
                        w.atomic(path, worker)
                        due = time.monotonic() + max(1, config.get("interval", 60))
                    time.sleep(1)  # Disabling never waits a whole capture interval.
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                worker["errors"] = [str(exc)]
                raise
            finally:
                worker.update(status="stopped", stopped=w.now())
                w.atomic(path, worker)
        return 0
    except OSError:
        if acquired:
            raise
        return 0  # Login and enable may race; the OS lock leaves one watcher.


def add_parser(commands):
    auto = commands.add_parser("auto", help="Opt-in automatic checkpoint and login restore")
    actions = auto.add_subparsers(dest="auto_action", required=True)
    enable = actions.add_parser("enable")
    enable.add_argument("--interval", type=int, default=60)
    enable.add_argument("--no-restore-on-login", action="store_true")
    enable.add_argument("--terminal", choices=TERMINALS, default="auto")
    for name in ("disable", "status", "save"):
        actions.add_parser(name)
    worker = actions.add_parser("watch", help="Run the automatic snapshot worker")
    worker.add_argument("--login", action="store_true", help="Native startup invocation; restore earlier-boot checkpoint")


def command(w, args):
    if args.auto_action == "watch":
        return watch(w, args)
    if args.auto_action in ("enable", "disable"):
        manage(w, args)
        result = status(w)
    elif args.auto_action == "save":
        result = tick(w, explicit=True)
    else:
        result = status(w)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
