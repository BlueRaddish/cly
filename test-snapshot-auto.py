#!/usr/bin/env python3
"""Run python test-snapshot-auto.py. No UI, startup settings, or live agents."""
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib/cly"))
import snapshot_auto as a
import workflows as w

checks = 0


def check(value):
    global checks
    assert value
    checks += 1


def fails(call, text):
    try:
        call()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        check(text.lower() in str(exc).lower())
    else:
        raise AssertionError("Expected failure: " + text)


with tempfile.TemporaryDirectory(prefix="cly-auto-test-") as temporary:
    temp = Path(temporary)
    record = {"schema": 1, "run_id": "fixture", "pid": 41001, "birth": "fixture-start", "profile": "codex-test",
              "kind": "codex", "session_id": "one", "directory": str(temp), "native_root": str(temp / "store"),
              "bypass": False, "binding": "hook", "history_present": True, "resume_options": ["--sandbox", "workspace-write"]}
    config = {"enabled": True, "restore_on_login": True, "interval": 60, "terminal": "auto"}

    @contextmanager
    def case(name):
        with patch.dict(os.environ, {"CLY_STATE_HOME": str(temp / name)}), patch.object(w, "active", return_value=[deepcopy(record)]):
            yield

    def checkpoint(boot="before", records=None):
        value = w.snapshot_value(deepcopy(records if records is not None else [record]))
        value.update(automatic=True, boot_id=boot)
        w.atomic(a.folder(w) / "latest.json", value)
        return value

    def plan(value):
        return [dict(item, argv=["fixture-agent", item["session_id"]]) for item in value["sessions"]]

    def terminals(value, selected):
        return [["fixture-terminal", item["session_id"]] for item in value]

    with case("capture"):
        first = a.tick(w, "boot")
        check(first["changed"] and first["sessions"] == 1)
        saved = a.latest(w)
        check(saved["sessions"][0]["resume_options"] == record["resume_options"])
        check(not list((w.state() / "snapshots").glob("*.json")))
        check(not a.tick(w, "boot")["changed"])
        changed = dict(record, pid=99999, birth="new-start", history_present=True, lifecycle={"timestamp": "new"})
        with patch.object(w, "active", return_value=[changed]):
            check(not a.tick(w, "boot")["changed"])
        for field, value in (("profile", "different"), ("session_id", "two"), ("directory", str(temp / "other")),
                             ("native_root", str(temp / "new-store")), ("bypass", True),
                             ("resume_options", ["--sandbox", "danger-full-access"]), ("binding", "manual")):
            with patch.object(w, "active", return_value=[dict(record, **{field: value})]):
                check(a.tick(w, "boot")["changed"])
            a.tick(w, "boot")
        before = (a.folder(w) / "latest.json").read_bytes()
        with patch.object(w, "active", return_value=[]):
            check(a.tick(w, "boot")["retained"])
        check((a.folder(w) / "latest.json").read_bytes() == before)
        with patch.object(w, "active", side_effect=ValueError("native capture error")):
            fails(lambda: a.tick(w, "boot"), "native capture error")
        check((a.folder(w) / "latest.json").read_bytes() == before)
        with patch.object(w, "snapshot_value", side_effect=ValueError("build failure")), patch.object(w, "active", return_value=[dict(record, session_id="changed")]):
            fails(lambda: a.tick(w, "boot"), "build failure")
        check((a.folder(w) / "latest.json").read_bytes() == before)
        check(len(list(a.folder(w).glob("latest*.json"))) == 1)

    with case("capture-native-failure"):
        checkpoint("boot")
        before = (a.folder(w) / "latest.json").read_bytes()
        for change in ({"session_id": None}, {"history_present": False, "discovery_errors": ["database unreadable"]},
                       {"kind": "unsupported"}):
            with patch.object(w, "active", return_value=[dict(record, **change)]):
                fails(lambda: a.tick(w, "boot"), "exact readable")
                fails(lambda: a.tick(w, "boot", explicit=True), "exact readable")
            check((a.folder(w) / "latest.json").read_bytes() == before)
        with patch.object(w, "active", return_value=[dict(record, discovery_errors=["unrelated corrupt history"], history_present=True)]):
            check(not a.tick(w, "boot")["changed"])

    with case("restore-same"), patch.object(w, "restore_plan") as preflight, patch.object(w, "launch_terminal", create=True) as launch:
        checkpoint("now")
        check(a.restore_login(w, config, "now")["status"] == "same-boot")
        check(not preflight.called and not launch.called)

    with case("restore-new"), patch.object(w, "restore_plan", side_effect=plan), patch.object(w, "terminal_commands", side_effect=terminals), patch.object(w, "launch_terminal", create=True) as launch:
        checkpoint()
        with patch.object(w, "active", return_value=[]):
            result = a.restore_login(w, config, "now")
            check(result["status"] == "complete" and result["entries"][0]["status"] == "launched")
            check(launch.call_count == 1)
            a.restore_login(w, config, "now")
            check(launch.call_count == 1)
        check(a.tick(w, "now")["changed"])
        check(a.latest(w)["boot_id"] == "now")

    with case("restore-not-ready"), patch.object(w, "restore_plan", side_effect=plan), patch.object(w, "terminal_commands", side_effect=terminals), patch.object(w, "launch_terminal", create=True):
        checkpoint(records=[record, dict(record, session_id="two")])
        before = (a.folder(w) / "latest.json").read_bytes()
        with patch.object(w, "active", return_value=[]):
            check(a.restore_login(w, config, "now")["status"] == "complete")
            fails(lambda: a.tick(w, "now"), "all restored conversations")
        fails(lambda: a.tick(w, "now"), "all restored conversations")
        check((a.folder(w) / "latest.json").read_bytes() == before)
        with patch.object(w, "active", return_value=[record, dict(record, session_id="two")]):
            check(a.tick(w, "now")["changed"])

    with case("same-conversation"), patch.object(w, "restore_plan") as preflight, patch.object(w, "launch_terminal", create=True) as launch:
        checkpoint(records=[dict(record, profile="older-profile")])
        check(a.restore_login(w, config, "now")["entries"][0]["status"] == "already-active")
        check(not preflight.called and not launch.called)

    with case("duplicate-conversation"), patch.object(w, "restore_plan", side_effect=plan), patch.object(w, "terminal_commands", side_effect=terminals), patch.object(w, "launch_terminal", create=True) as launch:
        checkpoint(records=[record, dict(record, profile="alias")])
        with patch.object(w, "active", return_value=[]):
            check(a.restore_login(w, config, "now")["status"] == "complete")
        check(launch.call_count == 1)

    with case("different-native-store"), patch.object(w, "restore_plan", side_effect=plan), patch.object(w, "terminal_commands", side_effect=terminals), patch.object(w, "launch_terminal", create=True) as launch:
        checkpoint(records=[record, dict(record, profile="other-store", native_root=str(temp / "another-store"))])
        check(a.restore_login(w, config, "now")["status"] == "complete")
        check(launch.call_count == 1)
        check(a.identity(w, record) != a.identity(w, dict(record, native_root=str(temp / "another-store"))))
        legacy = dict(record, native_root=None)
        check(a.identity(w, legacy) != a.identity(w, dict(legacy, profile="alias")))

    with case("partial"), patch.object(w, "restore_plan", side_effect=plan), patch.object(w, "terminal_commands", side_effect=terminals):
        old = checkpoint(records=[record, dict(record, session_id="two")])
        before = (a.folder(w) / "latest.json").read_bytes()
        launches = []

        def launch(command, **kwargs):
            receipt = w.read(a.folder(w) / "restore.json")
            check(receipt["entries"][-1]["status"] == "attempting")
            launches.append(command)
            if len(launches) == 2:
                raise subprocess.CalledProcessError(5, command)
            return subprocess.CompletedProcess(command, 0)

        with patch.object(w, "active", return_value=[]), patch.object(w, "launch_terminal", side_effect=launch, create=True):
            fails(lambda: a.restore_login(w, config, "now"), "exit status 5")
            receipt = w.read(a.folder(w) / "restore.json")
            check(receipt["status"] == "failed")
            check([item["status"] for item in receipt["entries"]] == ["launched", "attempting"])
            fails(lambda: a.restore_login(w, config, "now"), "uncertain")
            check(len(launches) == 2)
        fails(lambda: a.tick(w, "now"), "preserved")
        check((a.folder(w) / "latest.json").read_bytes() == before)
        check(a.tick(w, "now", explicit=True)["changed"])
        receipt = w.read(a.folder(w) / "restore.json")
        check(receipt["status"] == "superseded" and receipt["snapshot_id"] == old["snapshot_id"])
        check(not a.pending_restore(w, "now"))

    with case("receipt-crash"), patch.object(w, "restore_plan", side_effect=plan), patch.object(w, "terminal_commands", side_effect=terminals), patch.object(w, "launch_terminal", create=True) as launch:
        old = checkpoint()
        entry = {"key": a.entry_key(w, record), "status": "launched"}
        w.atomic(a.folder(w) / "restore.json", {"boot_id": "now", "status": "restoring", "snapshot_id": old["snapshot_id"], "entries": [entry]})
        with patch.object(w, "active", return_value=[]):
            check(a.restore_login(w, config, "now")["status"] == "complete")
        check(not launch.called)

    with case("preflight"), patch.object(w, "restore_plan", side_effect=ValueError("missing native history")), patch.object(w, "launch_terminal", create=True) as launch:
        checkpoint()
        before = (a.folder(w) / "latest.json").read_bytes()
        with patch.object(w, "active", return_value=[]):
            fails(lambda: a.restore_login(w, config, "now"), "missing native history")
        check(not launch.called)
        fails(lambda: a.tick(w, "now"), "preserved")
        check((a.folder(w) / "latest.json").read_bytes() == before)

    with case("login-race"):
        checkpoint()
        w.atomic(a.folder(w) / "config.json", config)
        fails(lambda: a.tick(w, "now"), "until login restore")

    with case("reload-lock"):
        checkpoint("now")
        before = (a.folder(w) / "latest.json").read_bytes()
        with w.lock(w.state() / "reload.lock"):
            fails(lambda: a.tick(w, "now"), "")
        check((a.folder(w) / "latest.json").read_bytes() == before)

    with case("manual-restore-hold"), patch.object(a, "boot_id", return_value="now"):
        checkpoint("before")
        before = (a.folder(w) / "latest.json").read_bytes()
        w.atomic(a.folder(w) / "config.json", config)
        w.atomic(a.folder(w) / "restore.json", {"boot_id": "now", "status": "failed", "entries": [{"status": "attempting"}]})
        desired = [dict(record, session_id="manual-one"), dict(record, session_id="manual-two")]
        with w.lock(w.state() / "reload.lock"):
            check(a.hold_restore(w, desired))
        fails(lambda: a.tick(w, "now"), "manually restored")
        check((a.folder(w) / "latest.json").read_bytes() == before)
        with patch.object(w, "active", return_value=desired), patch.object(w, "snapshot_value", side_effect=ValueError("manual capture failure")):
            fails(lambda: a.tick(w, "now"), "manual capture failure")
        check(w.read(a.folder(w) / "hold.json")["status"] == "waiting")
        check(w.read(a.folder(w) / "restore.json")["status"] == "failed")
        check((a.folder(w) / "latest.json").read_bytes() == before)
        with patch.object(w, "active", return_value=desired):
            check(a.tick(w, "now")["changed"])
        check(w.read(a.folder(w) / "hold.json")["status"] == "complete")
        check(w.read(a.folder(w) / "restore.json")["status"] == "superseded")
        check({item["session_id"] for item in a.latest(w)["sessions"]} == {"manual-one", "manual-two"})
        with w.lock(w.state() / "reload.lock"):
            check(a.hold_restore(w, desired))
        check(a.tick(w, "now", explicit=True)["changed"])
        check(w.read(a.folder(w) / "hold.json")["status"] == "superseded")

    with case("hold-disabled"), patch.object(a, "boot_id") as boot:
        check(not a.hold_restore(w, [record]))
        check(not boot.called and not (a.folder(w) / "hold.json").exists())

    with case("duplicate-worker"), patch.object(a, "boot_id") as boot:
        with w.lock(a.folder(w) / "watch.lock"):
            check(a.watch(w, SimpleNamespace(login=False)) == 0)
        check(not boot.called)

    with case("cooperative-disable"), patch.object(a, "boot_id", return_value="now"), patch.object(w, "birth", return_value="worker-start"):
        w.atomic(a.folder(w) / "config.json", config)

        def disable(seconds):
            check(seconds == 1)
            w.atomic(a.folder(w) / "config.json", dict(config, enabled=False))

        with patch.object(a.time, "sleep", side_effect=disable), patch.object(a, "restore_login") as restore:
            check(a.watch(w, SimpleNamespace(login=False)) == 0)
        worker = w.read(a.folder(w) / "worker.json")
        check(worker["status"] == "stopped" and worker["birth"] == "worker-start")
        check(worker["changed"] and not restore.called)

    args = w.parser().parse_args(["snapshot", "auto", "enable"])
    check(args.interval == 60 and not args.no_restore_on_login and args.terminal == "auto")
    check(w.parser().parse_args(["snapshot", "auto", "watch", "--login"]).login)
    check(w.parser().parse_args(["snapshot", "auto", "enable", "--no-restore-on-login"]).no_restore_on_login)

    with case("enable"), patch.object(a, "launcher", return_value=(["fixture-pythonw", str(temp / "enable-launcher.py")], "fixture script")), patch.object(w, "startup_registration", return_value={"backend": "fixture", "name": "owned", "value": "command"}) as registration, patch.object(w, "set_startup") as install, patch.object(w, "registered_startup", return_value=True), patch.object(a.subprocess, "Popen") as spawn, patch.object(a, "worker_status", side_effect=[{"active": False}, {"active": True}, {"active": True}]):
        a.manage(w, args)
        check(registration.call_args.kwargs["purpose"] == "snapshot")
        check(registration.call_args.args[0][-1] == "--login")
        check(install.call_args.args[1] is True)
        check(w.read(a.folder(w) / "config.json")["status"] == "verified")
        check(spawn.call_count == 1 and "--login" not in spawn.call_args.args[0])
        check(spawn.call_args.kwargs["stdin"] == subprocess.DEVNULL)
        check(a.status(w)["registered"])

    with case("worker-failed"), patch.object(a, "launcher", return_value=(["fixture-pythonw", str(temp / "failed-launcher.py")], "fixture script")), patch.object(w, "startup_registration", return_value={"backend": "fixture", "name": "owned", "value": "command"}), patch.object(w, "set_startup"), patch.object(w, "registered_startup", return_value=True), patch.object(a.subprocess, "Popen") as spawn, patch.object(a, "worker_status", return_value={"active": False}):
        spawn.return_value.poll.return_value = 1
        fails(lambda: a.manage(w, args), "exited before initialization")

    with case("registration-conflict"), patch.object(a, "launcher", return_value=(["fixture-pythonw", str(temp / "conflict-launcher.py")], "fixture script")), patch.object(w, "startup_registration", return_value={"backend": "fixture", "name": "owned", "value": "command"}), patch.object(w, "set_startup", side_effect=ValueError("changed externally")), patch.object(a.subprocess, "Popen") as spawn:
        fails(lambda: a.manage(w, args), "changed externally")
        check(w.read(a.folder(w) / "config.json")["status"] == "pending")
        check(not spawn.called)
        fails(lambda: a.manage(w, SimpleNamespace(auto_action="disable")), "changed externally")
        check(w.read(a.folder(w) / "config.json")["enabled"] is False)

    with case("verification-failure"), patch.object(a, "launcher", return_value=(["fixture-pythonw", str(temp / "verify-launcher.py")], "fixture script")), patch.object(w, "startup_registration", return_value={"backend": "fixture", "name": "owned", "value": "command"}), patch.object(w, "set_startup"), patch.object(w, "registered_startup", return_value=False), patch.object(a.subprocess, "Popen") as spawn:
        fails(lambda: a.manage(w, args), "verification failed")
        check(not spawn.called)

    with case("controls"), patch.dict(os.environ, {"UNRELATED_SECRET": "do-not-copy", "CLY_SHELL": "fixture-bash", "CLY_TRACK": "0"}), patch.object(Path, "is_file", return_value=True):
        command, content = a.launcher(w)
        check("do-not-copy" not in content and "UNRELATED_SECRET" not in content)
        check("fixture-bash" in content and "CLY_PYTHON" in content)
        check("'CLY_TRACK': '1'" in content)
        check(command[1].endswith("snapshot-auto" + os.sep + "startup.py"))

print(str(checks) + " automatic snapshot checks passed")
