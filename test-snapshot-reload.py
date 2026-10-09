#!/usr/bin/env python3
"""Run python test-snapshot-reload.py. Fixtures and disposable hidden processes only."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib/cly"))
import processes as p
import workflows as w

checks = 0


def check(value):
    global checks
    assert value
    checks += 1


def fails(call, text):
    try:
        call()
    except (ValueError, OSError) as exc:
        check(text.lower() in str(exc).lower())
    else:
        raise AssertionError("Expected failure: " + text)


class Input(io.StringIO):
    def __init__(self, terminal=True):
        super().__init__()
        self.terminal = terminal

    def isatty(self):
        return self.terminal


with tempfile.TemporaryDirectory(prefix="cly-reload-") as directory:
    temp = Path(directory)
    record = {"schema": 1, "run_id": "one", "pid": 41001, "birth": "one-start",
              "child_pid": 41002, "child_birth": "child-start", "profile": "codex-test",
              "kind": "codex", "session_id": "codex-one", "directory": str(temp),
              "native_root": str(temp / "codex"), "bypass": False}
    extra = dict(record, run_id="other", pid=42001, birth="other-start",
                 child_pid=42002, child_birth="other-child", profile="claude-test",
                 kind="claude", session_id="claude-extra")
    snapshot = {"schema": 1, "snapshot_id": "2026-10-08T120000Z-test", "created": w.now(),
                "host": socket.gethostname(), "sessions": [deepcopy(record)]}
    plan = [{"profile": record["profile"], "kind": record["kind"],
             "session_id": record["session_id"], "directory": str(temp), "argv": ["fixture-agent"]}]
    commands = [["fixture-terminal", "first"]]
    targets = (p.ProcessIdentity(41001, "one-start", 1, ("one",)),
               p.ProcessIdentity(41002, "child-start", 41001, ("one",)),
               p.ProcessIdentity(42001, "other-start", 1, ("other",)))

    def run_case(name, flags=(), answer="reload", terminal=True, restore_error=None,
                 terminal_error=None, stop_error=None, race=False, launch_fail_at=None,
                 custom_plan=None, extra_commands=None, real_restore=False,
                 snapshot_value=None, process_error=None, initial_records=None,
                 restore_error_on=1, terminal_error_on=1, write_error=None):
        case = temp / name
        initial = [deepcopy(record), deepcopy(extra)] if initial_records is None else deepcopy(initial_records)
        live = {"records": deepcopy(initial), "reads": 0}
        events = []
        stdout, stderr = io.StringIO(), io.StringIO()
        mocks = {}

        def active():
            live["reads"] += 1
            records = deepcopy(live["records"])
            if race and live["reads"] > 1 and records:
                records[0]["session_id"] = "switched-conversation"
            return records

        def restore(value, *args, **kwargs):
            events.append("restore-preflight")
            if restore_error and events.count("restore-preflight") == restore_error_on:
                raise ValueError(restore_error)
            return custom_plan or deepcopy(plan)

        def terminals(value, selected):
            events.append("terminal-preflight")
            if terminal_error and events.count("terminal-preflight") == terminal_error_on:
                raise ValueError(terminal_error)
            return extra_commands or deepcopy(commands)

        def process_plan(value):
            events.append("process-preflight")
            check({r["run_id"] for r in value} == {r["run_id"] for r in initial})
            if process_error:
                raise ValueError(process_error)
            return targets if initial else ()

        def confirmation(*args):
            events.append("confirm")
            if isinstance(answer, Exception):
                raise answer
            return answer

        def stop(value, *args, **kwargs):
            if not initial:
                check(value == ())
                events.append("stop-empty")
                return
            events.append("stop")
            check(value == targets)
            # The recoverable pre-reload state must already be on disk.
            backups = [w.read(path) for path in (w.state() / "snapshots").glob("*.json")]
            check(any({r["run_id"] for r in v["sessions"]} == {"one", "other"} for v in backups))
            receipts = [w.read(path) for path in (w.state() / "reloads").glob("*.json")]
            check(len(receipts) == 1 and receipts[0]["status"] == "stopping")
            if stop_error:
                raise ValueError(stop_error)
            live["records"] = []

        def launch(command, *args, **kwargs):
            events.append("launch")
            number = events.count("launch")
            if launch_fail_at == number:
                raise subprocess.CalledProcessError(7, command)
            return subprocess.CompletedProcess(command, 0)

        environment = {"CLY_STATE_HOME": str(case / "state"), "CLY_LIBRARY_HOME": str(case / "library")}
        atomic = w.atomic

        def write(path, value):
            if Path(path).parent.name == write_error:
                raise OSError("Fixture disk write failed")
            return atomic(path, value)

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, environment))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            stack.enter_context(patch.object(sys, "stdin", Input(terminal)))
            stack.enter_context(patch("builtins.input", side_effect=confirmation))
            stack.enter_context(patch.object(w, "select_snapshot", return_value=deepcopy(snapshot_value or snapshot)))
            stack.enter_context(patch.object(w, "active", side_effect=active))
            stack.enter_context(patch.object(w, "atomic", side_effect=write))
            if not real_restore:
                mocks["restore"] = stack.enter_context(patch.object(w, "restore_plan", side_effect=restore))
            mocks["terminal"] = stack.enter_context(patch.object(w, "terminal_commands", side_effect=terminals))
            mocks["plan"] = stack.enter_context(patch.object(p, "plan", side_effect=process_plan))
            mocks["stop"] = stack.enter_context(patch.object(p, "stop", side_effect=stop))
            mocks["launch"] = stack.enter_context(patch.object(w.subprocess, "run", side_effect=launch))
            result = w.main(["snapshot", "reload", *flags])
        return {"code": result, "output": stdout.getvalue() + stderr.getvalue(),
                "events": events, "mocks": mocks, "case": case}

    def unchanged(result):
        check("stop" not in result["events"] and "launch" not in result["events"])

    dry = run_case("dry", flags=("--dry-run",), terminal=False)
    check(dry["code"] == 0)
    unchanged(dry)
    check("confirm" not in dry["events"])
    check(record["session_id"] in dry["output"] and extra["session_id"] in dry["output"])
    check(not list(dry["case"].rglob("*.json")))

    cancelled = run_case("cancelled", answer="no")
    check(cancelled["code"] == 2)
    unchanged(cancelled)
    eof = run_case("eof", answer=EOFError())
    check(eof["code"] == 2)
    unchanged(eof)

    nonterminal = run_case("nonterminal", terminal=False)
    check(nonterminal["code"] != 0 and "--yes" in nonterminal["output"])
    unchanged(nonterminal)

    bad_restore = run_case("bad-restore", flags=("--yes",), restore_error="Restore preflight failed")
    check(bad_restore["code"] != 0)
    unchanged(bad_restore)

    unbound_snapshot = deepcopy(snapshot)
    unbound_snapshot["sessions"][0]["session_id"] = None
    unbound = run_case("unbound", flags=("--yes",), real_restore=True, snapshot_value=unbound_snapshot)
    check(unbound["code"] != 0 and "unresolved" in unbound["output"])
    unchanged(unbound)

    bad_terminal = run_case("bad-terminal", flags=("--yes",), terminal_error="Terminal unavailable")
    check(bad_terminal["code"] != 0)
    unchanged(bad_terminal)

    changed_restore = run_case("changed-restore", restore_error="History disappeared", restore_error_on=2)
    check(changed_restore["code"] != 0)
    unchanged(changed_restore)
    check(not list(changed_restore["case"].rglob("*.json")))

    changed_terminal = run_case("changed-terminal", terminal_error="Terminal disappeared", terminal_error_on=2)
    check(changed_terminal["code"] != 0)
    unchanged(changed_terminal)

    bad_process = run_case("bad-process", flags=("--yes",), process_error="Unsafe shutdown target")
    check(bad_process["code"] != 0)
    unchanged(bad_process)

    backup_failure = run_case("backup-failure", flags=("--yes",), write_error="snapshots")
    check(backup_failure["code"] != 0)
    unchanged(backup_failure)
    receipt_failure = run_case("receipt-failure", flags=("--yes",), write_error="reloads")
    check(receipt_failure["code"] != 0)
    unchanged(receipt_failure)

    changed = run_case("changed", race=True)
    check(changed["code"] != 0)
    unchanged(changed)

    stopped = run_case("stopped", flags=("--yes",), terminal=False)
    check(stopped["code"] == 0)
    check(stopped["events"].index("restore-preflight") < stopped["events"].index("stop"))
    check(stopped["events"].index("terminal-preflight") < stopped["events"].index("stop"))
    check(stopped["events"].index("stop") < stopped["events"].index("launch"))
    check("confirm" not in stopped["events"])
    complete_receipt = w.read(next((stopped["case"] / "state/reloads").glob("*.json")))
    check(complete_receipt["status"] == "complete" and complete_receipt["opened"] == [0])
    check(complete_receipt["snapshot_id"] == snapshot["snapshot_id"])
    check(complete_receipt["recovery_snapshot_id"] and complete_receipt["recovery_snapshot_id"] != snapshot["snapshot_id"])

    failed_stop = run_case("failed-stop", flags=("--yes",), stop_error="Still running")
    check(failed_stop["code"] != 0)
    check("stop" in failed_stop["events"] and "launch" not in failed_stop["events"])
    stop_receipt = w.read(next((failed_stop["case"] / "state/reloads").glob("*.json")))
    check(stop_receipt["status"] == "failed" and stop_receipt["failed_phase"] == "stop" and stop_receipt["opened"] == [])

    failed_launch = run_case("failed-launch", flags=("--yes",), launch_fail_at=2,
                             extra_commands=[["fixture-terminal", "first"], ["fixture-terminal", "second"]])
    check(failed_launch["code"] != 0)
    check(failed_launch["events"].count("launch") == 2)
    check("snapshot restore" in failed_launch["output"])
    launch_receipt = w.read(next((failed_launch["case"] / "state/reloads").glob("*.json")))
    check(launch_receipt["status"] == "failed" and launch_receipt["failed_phase"] == "open" and launch_receipt["opened"] == [0])

    empty = run_case("empty", terminal=False, initial_records=[])
    check(empty["code"] == 0 and "confirm" not in empty["events"] and "stop" not in empty["events"])
    check(empty["events"].count("launch") == 1 and not list((empty["case"] / "state/snapshots").glob("*.json")))
    empty_receipt = w.read(next((empty["case"] / "state/reloads").glob("*.json")))
    check(empty_receipt["status"] == "complete" and empty_receipt["recovery_snapshot_id"] is None)

    forced = run_case("forced", flags=("--yes", "--force"))
    check(forced["code"] == 0 and forced["mocks"]["stop"].call_args.kwargs["force"] is True)

    parsed = w.parser().parse_args(["snapshot", "reload", "2026-10-08", "--dry-run", "--yes",
                                    "--force", "--skip-unresolved", "--map-dir", "OLD=NEW", "--terminal", "tmux"])
    check(parsed.selector == "2026-10-08" and parsed.dry_run and parsed.yes and parsed.force)
    check(parsed.skip_unresolved and parsed.map_dir == ["OLD=NEW"] and parsed.terminal == "tmux")

    # Legacy non-Linux Unix state suffixes are volatile, not process identity.
    stable_birth = "Thu Oct 8 12:00:00 2026"
    legacy_birth = "Thu Oct  8 12:00:00 2026"
    with patch.object(p, "os", SimpleNamespace(name="posix")), patch.object(p.sys, "platform", "darwin"):
        check(p.birth_matches(stable_birth, legacy_birth + " R+"))
        check(p.birth_matches(stable_birth, legacy_birth + " Ss"))
        check(not p.birth_matches(stable_birth, "Thu Oct 8 12:00:01 2026 R+"))
        check(w.birth_matches(stable_birth, legacy_birth + " Ss"))
        response = subprocess.CompletedProcess([], 0, "  Thu Oct  8 12:00:00 2026    R+\n", "")
        with patch.object(p.subprocess, "run", return_value=response) as ps:
            check(p.birth(61001) == stable_birth and w.birth(61001) == stable_birth)
            check(ps.call_args.args[0] == ["ps", "-p", "61001", "-o", "lstart=", "-o", "stat="])
        response.stdout = "Thu Oct 8 12:00:00 2026 Z+\n"
        with patch.object(p.subprocess, "run", return_value=response):
            check(p.birth(61001) is None)

    with patch.object(p, "snapshot", return_value={}):
        for corrupt in ({"pid": 61001}, {"birth": "100"}, {"pid": True, "birth": "100"},
                        {"pid": 61001, "birth": "100", "child_pid": 61002},
                        {"pid": 61001, "birth": "100", "child_birth": "120"}):
            fails(lambda record=corrupt: p.plan([record]), "Invalid tracked process identity")

    # New descendants after review must fail before either shutdown backend.
    def token(value):
        return str(value) if os.name == "nt" or sys.platform.startswith("linux") else datetime(2026, 10, 8, 12, 0, value - 90).strftime("%a %b %d %H:%M:%S %Y")

    table = {61001: p.ProcessIdentity(61001, token(100), 1),
             61002: p.ProcessIdentity(61002, token(120), 61001),
             61003: p.ProcessIdentity(61003, token(130), 61002),
             62001: p.ProcessIdentity(62001, token(90), 1)}
    root_record = {"run_id": "fixture-graph", "pid": 61001, "birth": token(100)}
    with patch.object(p, "snapshot", return_value=table), patch.object(p, "birth", side_effect=lambda pid: table[pid].birth):
        frozen = p.plan([root_record])
        check({item.pid for item in frozen} == {61001, 61002, 61003})
        fails(lambda: p.plan([dict(root_record, pid=True)]), "Invalid")
        table[61004] = p.ProcessIdentity(61004, token(140), 61001)
        with patch.object(p, "_windows_stop") as windows_stop, patch.object(p, "_unix_stop") as unix_stop:
            fails(lambda: p.stop(frozen), "family changed")
            check(not windows_stop.called and not unix_stop.called)
        table[61004] = p.ProcessIdentity(61004, "", 61001)
        fails(lambda: p.plan([root_record]), "Cannot verify")
        with patch.object(p.os, "getpid", return_value=61001), patch.object(p.os, "getppid", return_value=62001):
            with patch.object(p, "_family", wraps=p._family) as family:
                fails(lambda: p.plan([root_record]), "own process")
                check(not family.called)

    # Real verification uses only two newly created hidden fixture families.
    # Their start identities remain checked at stop time; no agent PID is used.
    marker = temp / "child-pid.txt"
    parent_code = "\n".join([
        "import os, subprocess, sys, time",
        "from pathlib import Path",
        "hidden = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}",
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],",
        "    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden)",
        "Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')",
        "time.sleep(120)",
    ])
    child_pid, owned = None, []
    parent = subprocess.Popen([sys.executable, "-c", parent_code, str(marker)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **w.hidden())
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **w.hidden())
    try:
        parent_birth, unrelated_birth = p.birth(parent.pid), p.birth(unrelated.pid)
        owned = [p.ProcessIdentity(parent.pid, parent_birth, os.getpid(), ("fixture-family",)),
                 p.ProcessIdentity(unrelated.pid, unrelated_birth, os.getpid(), ("unrelated",))]
        deadline = time.monotonic() + 10
        while not marker.is_file() and time.monotonic() < deadline:
            if parent.poll() is not None:
                raise AssertionError("Disposable family failed: " + parent.communicate()[1].decode())
            time.sleep(0.05)
        check(marker.is_file())
        child_pid = int(marker.read_text())
        child_birth = p.birth(child_pid)
        owned.append(p.ProcessIdentity(child_pid, child_birth, parent.pid, ("fixture-family",)))
        check(bool(parent_birth and child_birth and unrelated_birth))
        family = p.plan([{"run_id": "fixture-family", "pid": parent.pid, "birth": parent_birth,
                          "child_pid": child_pid, "child_birth": child_birth}])
        # Windows app-execution aliases can add console host descendants.
        check({parent.pid, child_pid} <= {target.pid for target in family})
        check(unrelated.pid not in {target.pid for target in family})
        check(p.plan([{"run_id": "stale", "pid": unrelated.pid, "birth": "wrong-start"}]) == ())
        p.stop((p.ProcessIdentity(unrelated.pid, "wrong-start", os.getpid()),), timeout=0.1, force=True)
        check(p.birth(unrelated.pid) == unrelated_birth)
        fails(lambda: p.plan([{"run_id": "self", "pid": os.getpid(), "birth": p.birth(os.getpid())}]), "own process")
        p.stop(family, timeout=2.0, force=True)
        parent.wait(timeout=5)
        check(p.birth(parent.pid) is None and p.birth(child_pid) is None)
        check(all(p.birth(target.pid) != target.birth for target in family))
        check(p.birth(unrelated.pid) == unrelated_birth and unrelated.poll() is None)
    finally:
        cleanup = p.plan([{"run_id": "fixture-cleanup", "pid": target.pid, "birth": target.birth} for target in owned])
        p.stop(cleanup, timeout=2.0, force=True)
        for process in (parent, unrelated):
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

print(str(checks) + " snapshot reload checks passed")
