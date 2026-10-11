#!/usr/bin/env python3
"""Run python test-snapshot-runtime.py; stdlib checks and isolated Windows ConPTY.

No real agents, user terminals, input injection or desktop windows are used.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib/cly"))
import runtime as r
import workflows as w
import snapshot_auto as a

QUESTION = "Please prepare a detailed visual walkthrough of the terminal workspace, including its navigation, browser controls and recovery behavior."
ANSWER = "I will create an interactive walkthrough with guided tasks, preserved workspace context, keyboard navigation and a clear recovery path for interrupted actions."
SCREEN = "› " + QUESTION + "\n• " + ANSWER + "\n› Ask Codex to do anything"
WELCOME = "OpenAI Codex (v0.test)\nmodel: test\ndirectory: fixture\n› Ask Codex to do anything"


def history(path, directory, sid="one"):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "session_meta", "payload": {"id": sid, "cwd": str(directory), "source": "cli"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": QUESTION}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": ANSWER}}]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def rejected(call, text):
    try:
        call()
    except ValueError as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError("Expected rejection: " + text)


def unit():
    with tempfile.TemporaryDirectory(prefix="cly-runtime-") as temporary:
        directory = Path(temporary)
        store, state, config = directory / "codex", directory / "state", directory / "config"
        config.write_text("profile.codex.bin=codex\nprofile.codex.env=CODEX_HOME=" + str(store) + "\n", encoding="utf-8")
        source = store / "sessions/2026/10/11/rollout-one.jsonl"
        history(source, directory)
        row = {"pid": 44001, "birth": "native-start", "argv": ["codex.exe", "resume", "--sandbox", "workspace-write", "one"],
               "directory": str(directory), "environment": {"CLY_STATE_HOME": str(state), "CODEX_HOME": str(store)}, "screen": SCREEN}
        table = {44001: w.processes.ProcessIdentity(44001, "native-start", 44000)}
        environment = {"CLY_STATE_HOME": str(state), "CLY_CONFIG": str(config), "CODEX_HOME": str(store)}
        with patch.dict(os.environ, environment), patch.object(w.processes, "snapshot", return_value=table), \
                patch.object(w, "birth", side_effect=lambda pid: table[pid].birth if pid in table else None), \
                patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([row]))):
            adopted = r.capture([])
            assert len(adopted) == 1 and adopted[0]["session_id"] == "one" and adopted[0]["binding"] == "native-argv"
            assert adopted[0]["history_present"] and adopted[0]["resume_options"]["args"] == ["--sandbox", "workspace-write"]
            assert len(w.active()) == 1  # Repeated capture never adopts the wrapper twice.
            assert len(w.restore_plan(w.snapshot_value(adopted), query=False)) == 1
            isolated = dict(row, environment=dict(row["environment"], CLY_STATE_HOME=str(directory / "other-state")))
            with patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([isolated]))):
                assert not r.capture([])
            # A stale/PID-reused client cannot be adopted or bound.
            with patch.object(w, "birth", return_value="reused-start"):
                assert not r.capture([])
            # Both launcher and native child are visible in the same console.
            wrapper = dict(row, pid=44000, birth="wrapper-start", argv=["node.exe", "/@openai/codex/bin/codex.js", "resume", "one"])
            table[44000] = w.processes.ProcessIdentity(44000, "wrapper-start", 1)
            with patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([wrapper, row]))):
                assert len(r.capture([])) == 1
            # A managed registry may appear between active()'s glob and probe.
            # It must win over adoption, including a duplicate from that race.
            late = dict(adopted[0], run_id="late-managed", pid=44000, birth="wrapper-start", adopted=False,
                        child_pid=44001, child_birth="native-start")
            w.atomic(state / "runs/late-managed.json", late)
            inherited = dict(row, environment=dict(row["environment"], CLY_RUN_ID="late-managed"))
            with patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([inherited]))):
                late_capture = r.capture([])
                assert len(late_capture) == 1 and late_capture[0]["run_id"] == "late-managed"
                assert not late_capture[0].get("adopted")
                reconciled = r.capture([dict(adopted[0])])
                assert len(reconciled) == 1 and reconciled[0]["run_id"] == "late-managed"
                assert not (state / "runs" / (adopted[0]["run_id"] + ".json")).exists()
            (state / "runs/late-managed.json").unlink()
            managed = dict(adopted[0], session_id=None, binding=None, run_id="managed", adopted=False)
            unbound = dict(row, argv=["codex.exe"])
            with patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([unbound]))):
                bound = r.capture([managed])
                assert bound[0]["session_id"] == "one" and bound[0]["binding"] == "console-prose"
                assert w.resolve(dict(managed, session_id=None))["session_id"] == "one"
            journal = (state / "runtime/managed.json").read_text()
            assert QUESTION not in journal and ANSWER not in journal and "screen" not in journal
            items, _ = w.catalog(managed)
            assert r.console_session(managed, SCREEN, items) == "one"
            assert r.console_session(dict(managed, directory=str(directory / "wrong")), SCREEN, items) is None
            assert r.console_session(managed, "› " + QUESTION, items) is None
            assert r.console_session(managed, "• " + ANSWER, items) is None
            assert r.console_session(managed, "yes done thanks", items) is None
            twin = store / "sessions/2026/10/11/rollout-twin.jsonl"
            history(twin, directory, "twin")
            assert r.console_session(managed, SCREEN, w.catalog(managed)[0]) is None
            twin.unlink()
            fresh = dict(managed, run_id="welcome", session_id=None, binding=None)
            welcome = dict(unbound, screen=WELCOME)
            with patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([welcome]))):
                value = w.snapshot_value(r.capture([fresh]))
                plan = w.restore_plan(value, query=False)
                assert len(plan) == 1 and plan[0]["restore_mode"] == "new"
                assert w.is_new_session(value["sessions"][0])
                assert not w.is_new_session(dict(value["sessions"][0], session_id="one"))
                assert not w.is_new_session(dict(value["sessions"][0], binding=None))
                assert "resume" not in plan[0]["argv"] and plan[0]["restore_key"] == "welcome"
                assert a.identity(w, value["sessions"][0]) == a.identity(w, plan[0])
                assert a.identity(w, dict(value["sessions"][0], run_id="different")) != a.identity(w, value["sessions"][0])
            # Missing IDs never silently become empty sessions.
            unknown = w.snapshot_value([dict(fresh, restore_mode=None, binding=None)])
            rejected(lambda: w.restore_plan(unknown, query=False), "unresolved")
            assert r.empty_codex(WELCOME)
            assert not r.empty_codex(WELCOME + "\n› " + QUESTION)
            assert not r.empty_codex(SCREEN)
            assert not r.empty_codex(WELCOME + "\n• " + ANSWER)
            # A recovered client can clear or switch without changing PID.
            with patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([welcome]))):
                cleared = r.capture([dict(bound[0])])[0]
                assert cleared.get("session_id") is None and cleared.get("restore_mode") == "new"
            with patch.object(r.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps([dict(unbound, screen="› short new request")]))):
                changed = r.capture([cleared])[0]
                assert changed.get("restore_mode") is None and changed.get("session_id") is None
            with patch.dict(os.environ, {"CLY_NATIVE_DISCOVERY": "0"}):
                assert r.capture([]) == []
        assert r.client(["codex.exe", "app-server", "--listen", "unix://"]) is None
        assert r.client(["codex.exe", "exec", "prompt"]) is None
        assert r.client(["claude.exe", "--print", "prompt"]) is None
        assert r.client(["node.exe", "unrelated.js"]) is None
        assert r.client(["muse-bin-1.4.4-R5419.1.exe", "resume", "--yolo", "one"]) == ("muse", ["resume", "--yolo", "one"])


def host():
    """Run a disposable unregistered Node client in this private ConPTY."""
    mode, receipt, script = sys.argv[2:]
    # Bind stdio to this disposable console, never the user's terminal.
    sys.stdin = open("CONIN$", "r", encoding="utf-8")
    sys.stdout = open("CONOUT$", "w", encoding="utf-8")
    sys.stderr = open("CONOUT$", "w", encoding="utf-8")
    directory = Path.cwd()
    store = Path(os.environ["CODEX_HOME"])
    history(store / "sessions/2026/10/11/rollout-one.jsonl", directory)
    if mode == "ambiguous":
        history(store / "sessions/2026/10/11/rollout-twin.jsonl", directory, "twin")
    ready = directory / "ready"
    arguments = ["resume", "--yolo", "one"] if mode == "resume" else []
    child = subprocess.Popen([shutil.which("node"), script, *arguments], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            assert child.poll() is None, "Disposable native client exited"
            time.sleep(0.05)
        assert ready.exists()
        before = w.agent_console()
        records = w.active()
        assert w.agent_console() == before, "Discovery detached the caller's console"
        assert len(records) == 1, records
        record = records[0]
        assert record["pid"] == child.pid and record["adopted"]
        if mode in {"resume", "unbound"}:
            assert record["session_id"] == "one", record
            assert len(w.restore_plan(w.snapshot_value(records))) == 1
        elif mode == "welcome":
            assert record.get("restore_mode") == "new", record
            plan = w.restore_plan(w.snapshot_value(records))
            assert "resume" not in plan[0]["argv"]
            assert a.tick(w, "fixture-boot", explicit=True)["sessions"] == 1
        else:
            assert record.get("session_id") is None, record
            rejected(lambda: w.restore_plan(w.snapshot_value(records)), "unresolved")
        assert len(w.active()) == 1
        Path(receipt).write_text(json.dumps({"mode": mode, "binding": record.get("binding"), "session_id": record.get("session_id"),
                                           "restore_mode": record.get("restore_mode"), "caller_console_preserved": True}), encoding="utf-8")
    finally:
        child.terminate()
        child.wait(timeout=5)
        for path in (w.state() / "runs").glob("*.json"):
            path.unlink()


def windows():
    node = shutil.which("node")
    if os.name != "nt" or not node:
        print("Windows ConPTY native-discovery integration skipped")
        return
    spec = importlib.util.spec_from_file_location("console_fixture", ROOT / "test-snapshot-console.py")
    console = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(console)
    results = []
    with tempfile.TemporaryDirectory(prefix="cly-runtime-console-") as temporary:
        for mode in ("resume", "unbound", "welcome", "ambiguous"):
            directory = Path(temporary) / mode
            directory.mkdir()
            script = directory / "@openai/codex/fixture.js"
            script.parent.mkdir(parents=True)
            screen = WELCOME if mode == "welcome" else SCREEN
            script.write_text("const fs=require('fs'); process.stdout.write(" + json.dumps(screen + "\n") + ");"
                              "fs.writeFileSync('ready','ok');setInterval(()=>{},1000);", encoding="utf-8")
            store, config = directory / "codex", directory / "config"
            config.write_text("profile.codex.bin=" + node.replace("\\", "/") + "\nprofile.codex.kind=codex\n"
                              "profile.codex.env=CODEX_HOME=" + str(store) + "\nprofile.codex.dir=none\n", encoding="utf-8")
            env = dict(os.environ, CLY_STATE_HOME=str(directory / "state"), CLY_CONFIG=str(config), CODEX_HOME=str(store),
                       CLY_SHELL=os.environ.get("CLY_SHELL") or r"C:\Program Files\Git\bin\bash.exe", CLY_TRACK="0")
            for name in ("CLY_BIN", "CLY_FLAGS", "CLY_DIR", "CLY_DOCUMENT_JOB", "CLY_WORKFLOW_QUERY", "CLY_NATIVE_DISCOVERY", "CLY_RUN_ID"):
                env.pop(name, None)
            receipt = directory / "receipt.json"
            console.conpty([sys.executable, str(Path(__file__)), "--host", mode, str(receipt), str(script)], env, directory)
            results.append(json.loads(receipt.read_text(encoding="utf-8")))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--host"]:
        host()
    else:
        unit()
        windows()
        print("Native snapshot discovery, safe binding, welcome restore and ambiguity checks passed")
