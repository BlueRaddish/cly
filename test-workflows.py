#!/usr/bin/env python3
"""One stdlib-only runnable check: python test-workflows.py. No real agents."""
from argparse import Namespace
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib/cly"))
import sessions as s
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
        check(text in str(exc))
    else:
        raise AssertionError("Expected failure: " + text)


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


with tempfile.TemporaryDirectory(prefix="cly-workflows-") as temporary:
    temp = Path(temporary)
    bash = os.environ.get("CLY_SHELL") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))
    env = {"CLY_STATE_HOME": str(temp / "state"), "CLY_LIBRARY_HOME": str(temp / "library"),
           "CLAUDE_CONFIG_DIR": str(temp / "claude"), "CODEX_HOME": str(temp / "codex"),
           "GEMINI_CLI_HOME": str(temp / "gemini"), "KIMI_CODE_HOME": str(temp / "kimi"),
           "CLY_MUSE_HOME": str(temp / "muse"), "QWEN_HOME": str(temp / "qwen"),
           "CLY_OPENCODE_HOME": str(temp / "opencode"), "CLY_SHELL": str(bash),
           "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"}
    with patch.dict(os.environ, env):
        cwd = str(temp)
        codex = jsonl(temp / "codex/sessions/2026/10/07/rollout-one.jsonl", [
            {"type": "session_meta", "payload": {"id": "codex-one", "cwd": cwd, "timestamp": "2026-10-07T12:00:00Z"}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "id": "user-response", "content": [{"type": "input_text", "text": "hello"}]}},
            {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "turn-1", "item": {"type": "UserMessage", "id": "user-event", "content": [{"type": "Text", "text": "hello"}]}}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "id": "a", "channel": "analysis", "content": "PRIVATE_REASONING"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "SECRET_TOOL_OUTPUT"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "id": "b", "channel": "final", "content": [{"type": "output_text", "text": "done"}]}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "id": "b", "phase": "final_answer", "content": [{"type": "Text", "text": "done"}]}}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "# AGENTS.md instructions\nINJECTED"}},
        ])
        item = s.claude_codex(codex, "codex")
        check(item["messages"] == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "done"}])
        codex.write_bytes(codex.read_bytes() + b'{"partial":')
        check(s.claude_codex(codex, "codex")["messages"] == item["messages"])
        malformed = jsonl(temp / "malformed.jsonl", [{"a": 1}])
        malformed.write_bytes(malformed.read_bytes() + b"bad\n{}\n")
        fails(lambda: list(s.read_records(malformed)), "Malformed JSON")
        subagent = jsonl(temp / "subagent.jsonl", [{"type": "session_meta", "payload": {"id": "child", "source": {"subagent": "spawn"}}}])
        check(s.claude_codex(subagent, "codex") is None)

        claude = jsonl(temp / "claude/projects/project/claude-one.jsonl", [
            {"sessionId": "claude-one", "cwd": cwd, "timestamp": "2026-10-07T12:00:00Z", "uuid": "u", "message": {"role": "user", "content": "question"}},
            {"sessionId": "claude-one", "uuid": "a", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "SECRET"}, {"type": "text", "text": "answer"}]}},
            {"sessionId": "claude-one", "uuid": "tool", "message": {"role": "user", "content": [{"type": "tool_result", "content": "SECRET"}]}},
        ])
        check(len(s.discover("claude")[0][0]["messages"]) == 2)
        gemini = temp / "gemini/tmp/hash/chats/session-one.json"
        gemini.parent.mkdir(parents=True)
        gemini.parent.parent.joinpath(".project_root").write_text(cwd)
        w.atomic(gemini, {"sessionId": "gemini-one", "startTime": "2026-10-07T12:00:00Z", "messages": [{"type": "user", "content": "q"}, {"type": "gemini", "content": "a"}, {"type": "tool", "content": "SECRET"}]})
        check(s.discover("gemini")[0][0]["directory"] == cwd)
        check(len(s.discover("gemini")[0][0]["messages"]) == 2)
        kimi = temp / "kimi/sessions/hash/kimi-one/state.json"
        w.atomic(kimi, {"workDir": cwd, "createdAt": "2026-10-07T12:00:00Z"})
        jsonl(kimi.parent / "context.jsonl", [{"role": "user", "content": "q"}, {"role": "assistant", "content": [{"type": "text", "text": "a"}]}])
        check(len(s.discover("kimi")[0][0]["messages"]) == 2)
        jsonl(temp / "qwen/projects/hash/chats/qwen-one.jsonl", [{"sessionId": "qwen-one", "cwd": cwd, "timestamp": "2026-10-07T12:00:00Z", "message": {"role": "user", "content": "q"}}])
        check(len(s.discover("qwen")[0][0]["messages"]) == 1)
        muse = jsonl(temp / "muse/sessions/2026/10/07/muse-one/session.jsonl", [{"retained_frame": True, "children": [{"record_json": json.dumps({"record_type": "event", "payload_type": "runtime.session.metadata", "payload": {"record": {"workspace_root": cwd}}})}]}])
        check(s.discover("muse")[0][0]["directory"] == cwd)
        (temp / "opencode").mkdir()
        with sqlite3.connect(temp / "opencode/opencode.db") as db:
            db.executescript('create table session(id,directory,title,time_created,parent_id);create table message(id,session_id,data,time_created);create table part(id,message_id,data,time_created);')
            db.execute("insert into session values(?,?,?,?,?)", ("ses_one", cwd, "Test", 1791374400000, None))
            db.execute("insert into message values(?,?,?,?)", ("msg", "ses_one", '{"role":"assistant"}', 1))
            db.execute("insert into part values(?,?,?,?)", ("part", "msg", '{"type":"text","text":"ok"}', 1))
        db.close()
        check(s.discover("opencode")[0][0]["messages"][0]["content"] == "ok")

        token = w.birth(os.getpid())
        check(bool(token) and w.alive({"pid": os.getpid(), "birth": token}))
        check(not w.alive({"pid": os.getpid(), "birth": "wrong-start"}))
        record = {"schema": 1, "run_id": "one", "pid": os.getpid(), "birth": token, "profile": "codex-test", "kind": "codex", "session_id": "codex-one", "directory": cwd, "native_root": str(temp / "codex"), "bypass": False, "baseline": []}
        w.atomic(w.state() / "runs/one.json", record)
        w.atomic(w.state() / "runs/stale.json", dict(record, run_id="stale", birth="stale"))
        check(len(w.active()) == 1)
        saved = w.save_snapshot()
        check(len(saved["sessions"]) == 1 and "baseline" not in saved["sessions"][0])
        check(w.select_snapshot("latest")["snapshot_id"] == saved["snapshot_id"])
        check(w.select_snapshot(saved["snapshot_id"][:10])["snapshot_id"] == saved["snapshot_id"])
        check(len(w.restore_plan(saved, query=False)) == 1)
        missing = json.loads(json.dumps(saved))
        missing["sessions"].append(dict(record, session_id="does-not-exist"))
        fails(lambda: w.restore_plan(missing, query=False), "nothing opened")
        unbound = json.loads(json.dumps(saved))
        unbound["sessions"][0]["session_id"] = None
        fails(lambda: w.restore_plan(unbound, query=False), "unresolved")
        fails(lambda: w.select_snapshot("../../oops"), "Invalid")
        mapped = dict(record, directory="/old/project/src")
        check(w.restored_directory(mapped, ["/old/project=" + cwd], False) == str(temp / "src"))
        check(w.restored_directory(dict(record, directory="/old/projects"), ["/old/project=" + cwd], False) == str(s.native_path("/old/projects")))
        fails(lambda: w.validate_session(dict(item, agent="../escape")), "Invalid")
        fails(lambda: w.validate_session(dict(item, messages=[{"role": "tool", "content": "secret"}])), "prose")
        sanitized = w.validate_session(dict(item, messages=[{"role": "user", "content": "ok", "tool_result": "SECRET"}]))
        check(sanitized["messages"] == [{"role": "user", "content": "ok"}])
        check(w.native_id("claude", ["-r", "claude-one"]) == "claude-one")
        check(w.native_id("opencode", ["-s", "ses_one"]) == "ses_one")
        check(w.native_id("claude", ["--session-id=claude-one"]) == "claude-one")
        fails(lambda: w.restored_directory(dict(record, home_relative="D:escape"), [], True), "Invalid")
        malformed_snapshot = json.loads(json.dumps(saved))
        malformed_snapshot["sessions"][0]["bypass"] = "false"
        fails(lambda: w.restore_plan(malformed_snapshot, query=False), "Invalid")
        with w.lock(w.library() / "test.lock"):
            fails(lambda: w.lock(w.library() / "test.lock").__enter__(), "")

        changed, index = w.capture(("claude", "codex", "gemini", "kimi", "qwen", "opencode"))
        check(changed == 6 and not index["errors"])
        check(w.capture(("claude", "codex", "gemini", "kimi", "qwen", "opencode"))[0] == 0)
        rendered = "\n".join(p.read_text(encoding="utf8") for p in w.library().rglob("*.md"))
        check("SECRET" not in rendered and "INJECTED" not in rendered and "PRIVATE_REASONING" not in rendered)
        key = w.note_key(item)
        index["sessions"][key]["published_revision"] = index["sessions"][key]["revision"]
        updated = dict(item, title="Renamed", messages=item["messages"] + [{"role": "user", "content": "more"}])
        check(w.store_session(updated, index))
        check(index["sessions"][key]["published_revision"] != index["sessions"][key]["revision"])
        packet, count = w.catch_up(index)
        check(count == 6 and packet.is_file() and "untrusted" in packet.read_text())

        writer = temp / "writer"
        (temp / "vault").mkdir()
        writer.write_text('exit 1\n', encoding="utf8")
        successes, failures = w.publish(index, writer, temp / "vault")
        check(successes == 0 and len(failures) == 6 and len(w.pending(index, "published_revision")) == 6)
        # A successful upload followed by a failed checksum cannot advance a receipt.
        writer.write_text('if [ "$1" = --check ]; then exit 1; fi\nexit 0\n')
        check(w.publish(index, writer, temp / "vault")[0] == 0)
        writer.write_text('exit 0\n')
        check(w.publish(index, writer, temp / "vault")[0] == 6)
        check(not w.pending(index, "published_revision"))

        # Revisions preserve identity paths and curated project metadata/links.
        destination = index["sessions"][key]["vault_path"]
        old_note = temp / "vault" / destination
        old_note.parent.mkdir(parents=True, exist_ok=True)
        old_note.write_text('---\ntype: session\nproject: cly\nprojects: [cly, paradesk]\n---\n\n[[1-Projects/cly/README|cly]]\n', encoding="utf8")
        revised = dict(updated, started="2026-09-30T23:00:00Z", messages=updated["messages"] + [{"role": "assistant", "content": "latest"}])
        check(w.store_session(revised, index))
        check(w.publish(index, writer, temp / "vault")[0] == 1)
        check(index["sessions"][key]["vault_path"] == destination)
        staged_note = (w.library() / "publish" / (key + ".md")).read_text(encoding="utf8")
        check("project: cly" in staged_note and "projects: [cly, paradesk]" in staged_note and "[[1-Projects/cly/README|cly]]" in staged_note and "latest" in staged_note)

        # An unrelated bad transcript cannot block a healthy selected resume.
        bad_claude = jsonl(temp / "claude/projects/project/bad.jsonl", [{"sessionId": "bad", "message": None}])
        healthy = dict(record, profile="claude-test", kind="claude", session_id="claude-one", native_root=str(temp / "claude"))
        with redirect_stderr(io.StringIO()):
            check(len(w.restore_plan(dict(saved, sessions=[healthy]), query=False)) == 1)
        _, failed_index = w.capture(("claude",))
        check(bool(failed_index["errors"]))
        _, subset_index = w.capture(("codex",))
        check(bool(subset_index["errors"]))
        index = subset_index
        bad_claude.unlink()

        # One chosen model sees the combined library; failed jobs leave receipts pending.
        def model_run(command, **kwargs):
            if kwargs.get("env", {}).get("CLY_WORKFLOW_QUERY") == "1":
                return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
            check("<session-data>" in kwargs["input"] and "claude-one" in kwargs["input"] and "codex-one" in kwargs["input"])
            return subprocess.CompletedProcess(command, 1, "", "model-failure")
        with patch.object(w.subprocess, "run", side_effect=model_run):
            fails(lambda: w.catch_up(index, "codex-test"), "pending revisions kept")
        check(len(w.pending(index, "reviewed_revision")) == 6)
        def good_model(command, **kwargs):
            if kwargs.get("env", {}).get("CLY_WORKFLOW_QUERY") == "1":
                return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
            check("--sandbox" in command and "read-only" in command)
            return subprocess.CompletedProcess(command, 0, "# Cross-agent review\n", "")
        with patch.object(w.subprocess, "run", side_effect=good_model):
            report, count = w.catch_up(index, "codex-test", "chosen-model")
        check(count == 6 and report.is_file() and not w.pending(index, "reviewed_revision"))

        plan = {"schema": 1, "source_revisions": {key: index["sessions"][key]["revision"]}, "notes": [
            {"path": "3-Resources/test-note.md", "content": "---\ntype: resource\n---\n\n# Verified finding\n", "sources": [{"agent": "codex", "session_id": "codex-one"}]}]}
        plan_path = temp / "filing-plan.json"
        w.atomic(plan_path, plan)
        check(w.file_plan(plan_path, index, writer, temp / "vault") == 1)
        check(index["sessions"][key]["filed_revision"] == index["sessions"][key]["revision"])
        plan["notes"][0]["path"] = "3-Resources/../escape.md"
        fails(lambda: w.validate_filing_plan(plan, index), "new notes")
        plan["notes"][0]["path"] = "3-Resources/existing.md"
        w.atomic(temp / "vault/3-Resources/existing.md", "keep")
        w.atomic(plan_path, plan)
        fails(lambda: w.file_plan(plan_path, index, writer, temp / "vault"), "Existing note preserved")
        check((temp / "vault/3-Resources/existing.md").read_text() == "keep")
        plan["notes"][0]["path"] = "0-Inbox/pending.md"
        w.atomic(plan_path, plan)
        writer.write_text('if [ "$1" = --check ]; then exit 1; fi\nexit 0\n')
        previous_filed = "older-revision"
        index["sessions"][key]["filed_revision"] = previous_filed
        fails(lambda: w.file_plan(plan_path, index, writer, temp / "vault"), "Partial filing")
        check(index["sessions"][key]["filed_revision"] == previous_filed)
        writer.write_text('exit 0\n')
        check(w.file_plan(plan_path, index, writer, temp / "vault") == 1)
        check(index["sessions"][key]["filed_revision"] == index["sessions"][key]["revision"])

        # Integration uses a harmless Bash stub. Raw prompts/env never persist.
        stub = temp / "agent"
        stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\nread -r release\n', encoding="utf8")
        stub.chmod(0o755)
        config = temp / "config"
        config.write_text('profile.codex-test.bin=' + str(stub).replace('\\', '/') + '\nprofile.codex-test.kind=codex\nprofile.codex-test.dir=none\nprofile.codex-test.flags=\nprofile.codex-test.env=PRIVATE_TOKEN=never-save-this\n')
        env2 = dict(os.environ, CLY_CONFIG=str(config), CLY_TRACK="1")
        child = subprocess.Popen(w.cly_command(["--here", "codex-test", "resume", "codex-one", "private-prompt"]), cwd=temp, env=env2, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **w.hidden())
        try:
            for _ in range(100):
                running = [v for v in w.active() if v["run_id"] != "one"]
                if running:
                    break
                if child.poll() is not None:
                    output, error = child.communicate()
                    raise AssertionError("Managed stub failed: " + output + error)
                time.sleep(.05)
            check(len(running) == 1)
            snapshot = w.save_snapshot()
            serialized = json.dumps(snapshot)
            check("private-prompt" not in serialized and "never-save-this" not in serialized)
            with patch.dict(os.environ, CLY_CONFIG=str(config)):
                check(len(w.restore_plan(snapshot)) == 2)
            stdout, stderr = child.communicate(input="finish\n", timeout=15)
            if child.returncode != 0:
                raise AssertionError("Managed stub exit: " + str(child.returncode) + "\n" + stdout + stderr)
            check("resume" in stdout)
            check(len(w.active()) == 1)
        finally:
            if child.poll() is None:
                child.terminate()
                child.communicate()
        with patch.object(w.shutil, "which", return_value="available"):
            for terminal in ("wt", "terminal", "tmux", "gnome-terminal", "konsole", "x-terminal-emulator"):
                commands = w.terminal_commands(w.restore_plan(saved, query=False), terminal)
                check(len(commands) == 1)
            encoded = w.terminal_commands(w.restore_plan(saved, query=False), "wt")[0][-1]
            import base64
            check("codex-one" in base64.b64decode(encoded).decode("utf-16le"))

        # Restore preview must check the terminal too, without launching it.
        with patch.object(w, "select_snapshot", return_value=saved), \
             patch.object(w, "restore_plan", return_value=[{"fixture": True}]), \
             patch.object(w, "terminal_commands", side_effect=ValueError("Terminal unavailable")) as terminal, \
             patch.object(w.subprocess, "run") as launch, \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
            check(w.main(["snapshot", "restore", "latest", "--dry-run"]) == 1)
            check("Terminal unavailable" in errors.getvalue() and terminal.called and not launch.called)
        with patch.object(w, "select_snapshot", return_value=saved), \
             patch.object(w, "restore_plan", return_value=[{"fixture": True}]), \
             patch.object(w, "terminal_commands", return_value=[["fixture-terminal"]]) as terminal, \
             patch.object(w.subprocess, "run") as launch, redirect_stdout(io.StringIO()):
            check(w.main(["snapshot", "restore", "latest", "--dry-run"]) == 0)
            check(terminal.called and not launch.called)

        # The actual detached collector is hidden, single-instance, and stoppable.
        try:
            with redirect_stdout(io.StringIO()):
                w.main(["document", "start", "--agent", "codex", "--interval", "900"])
            status = w.collector_status()
            check(status["active"])
            with redirect_stdout(io.StringIO()):
                w.main(["document", "start", "--agent", "codex"])
            check(w.collector_status()["pid"] == status["pid"])
        finally:
            with redirect_stdout(io.StringIO()):
                w.main(["document", "stop"])
        check(not w.collector_status()["active"])

        # Oversized Unicode/control-character prose is split losslessly. A
        # failed fragment is retried without paying for completed fragments.
        with patch.dict(os.environ, CLY_LIBRARY_HOME=str(temp / "large-library")), patch.object(w, "CATCH_UP_BYTES", 3500):
            large = dict(item, session_id="large", title="Large", messages=[{"role": "user", "content": '汉字🙂\n\t"\\' * 600}])
            large_index = {"schema": 1, "sessions": {}, "errors": []}
            w.store_session(large, large_index)
            parts = [json.loads(p) for p in w.session_parts(large, s.revision(large), "header")]
            recovered = "".join(message["content"] for part in parts for message in part["messages"])
            check(recovered == large["messages"][0]["content"] and len(parts) > 1)
            calls, completed = [], []
            fail_second = [True]
            def fragment_model(command, **kwargs):
                if kwargs.get("env", {}).get("CLY_WORKFLOW_QUERY") == "1":
                    return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
                prompt = kwargs["input"]
                check(len(prompt.encode()) <= w.CATCH_UP_BYTES)
                if "labeled portion" in prompt:
                    data = json.loads(prompt.split("<session-data>\n", 1)[1].split("\n</session-data>", 1)[0])
                    calls.append(data["session_part"])
                    if data["session_part"] == 2 and fail_second[0]:
                        fail_second[0] = False
                        return subprocess.CompletedProcess(command, 1, "", "fragment failed")
                    completed.extend(message["content"] for message in data["messages"])
                return subprocess.CompletedProcess(command, 0, "Compact sourced finding.", "")
            with patch.object(w.subprocess, "run", side_effect=fragment_model):
                fails(lambda: w.catch_up(large_index, "codex-test"), "completed batch receipts retained")
                check(len(w.pending(large_index, "reviewed_revision")) == 1)
                report, count = w.catch_up(large_index, "codex-test")
            check(count == 1 and calls.count(1) == 1 and calls.count(2) == 2)
            check("".join(completed) == large["messages"][0]["content"])
            check(not w.pending(large_index, "reviewed_revision"))

            # Multiple ordinary batches get a final cross-agent reconciliation.
            batch_index = {"schema": 1, "sessions": {}, "errors": []}
            for kind in ("claude", "codex", "gemini"):
                w.store_session(dict(item, agent=kind, session_id=kind + "-batch", messages=[{"role": "user", "content": "x" * 1500}]), batch_index)
            reconciliations = []
            def batch_model(command, **kwargs):
                if kwargs.get("env", {}).get("CLY_WORKFLOW_QUERY") == "1":
                    return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
                check(len(kwargs["input"].encode()) <= w.CATCH_UP_BYTES)
                if "batch_reports" in kwargs["input"]:
                    reconciliations.append(kwargs["input"])
                return subprocess.CompletedProcess(command, 0, "Concise batch evidence.", "")
            with patch.object(w.subprocess, "run", side_effect=batch_model):
                report, count = w.catch_up(batch_index, "codex-test")
            check(count == 3 and len(reconciliations) == 1 and not w.pending(batch_index, "reviewed_revision"))

            # Model plan destinations are case-insensitive; identical findings
            # merge their sources, conflicting note contents are rejected.
            sources = [{"agent": "claude", "session_id": "claude-batch"}, {"agent": "codex", "session_id": "codex-batch"}]
            revisions = {key: r["revision"] for key, r in batch_index["sessions"].items()}
            proposals = {"notes": [{"path": "3-Resources/Shared.md", "content": "---\ntype: resource\n---\nFinding", "sources": [sources[0]]},
                                   {"path": "3-Resources/shared.md", "content": "---\ntype: resource\n---\nFinding", "sources": [sources[1]]}]}
            merged = w.catch_up_plan(json.dumps(proposals), revisions, batch_index)
            check(len(merged["notes"]) == 1 and len(merged["notes"][0]["sources"]) == 2)
            proposals["notes"][1]["content"] += " changed"
            fails(lambda: w.catch_up_plan(json.dumps(proposals), revisions, batch_index), "Conflicting")
            def plan_model(command, **kwargs):
                if kwargs.get("env", {}).get("CLY_WORKFLOW_QUERY") == "1":
                    return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
                check(len(kwargs["input"].encode()) <= w.CATCH_UP_BYTES)
                if "batch_reports" in kwargs["input"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps({"notes": merged["notes"]}), "")
                return subprocess.CompletedProcess(command, 0, '{"notes":[]}', "")
            with patch.object(w, "CATCH_UP_BYTES", 5000), patch.object(w.subprocess, "run", side_effect=plan_model):
                generated, count = w.catch_up(batch_index, "codex-test", filing_plan=True)
            check(count == 3 and w.read(generated)["source_revisions"] == revisions)
            check(len(w.pending(batch_index, "filed_revision")) == 3)
            with redirect_stderr(io.StringIO()):
                check(w.main(["document", "catch-up", "--batch-bytes", "1"]) == 1)

        with patch.dict(os.environ, CLY_CONFIG="/a path/it's;$not-code", PRIVATE_TOKEN="never-copy"), patch.object(w.shutil, "which", return_value="available"):
            commands = w.terminal_commands(w.restore_plan(saved, query=False), "wt")
            decoded = base64.b64decode(commands[0][-1]).decode("utf-16le")
            check("it's" not in decoded and "it''s;$not-code" in decoded)
            check("PRIVATE_TOKEN" not in decoded and "never-copy" not in decoded)
            commands = w.terminal_commands(w.restore_plan(saved, query=False), "gnome-terminal")
            check("export CLY_CONFIG=" in commands[0][-len(w.restore_plan(saved, query=False)[0]["argv"]) - 2])



# Provider format boundaries and mocked model failure/retry regressions.
def source_boundary_checks(temp):
    checks = 0

    def check(condition):
        nonlocal checks
        assert condition
        checks += 1

    def jsonl(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        return path

    def row(sid="one", content="visible", ident="u", cwd="/project"):
        return {"sessionId": sid, "cwd": cwd, "timestamp": "2026-10-08T12:00:00Z", "uuid": ident,
                "message": {"role": "user", "content": content}}

    def codex_meta(sid="one"):
        return {"type": "session_meta", "payload": {"id": sid, "cwd": "/project", "timestamp": "2026-10-08T12:00:00Z"}}

    # Known public channels/phases and legacy unset values remain supported.
    root = temp / "public"
    records = [codex_meta()]
    public = ({}, {"channel": "commentary"}, {"channel": "final"}, {"phase": "commentary"}, {"phase": "final_answer"})
    for i, fields in enumerate(public):
        records.append({"type": "response_item", "payload": dict(fields, type="message", role="assistant", id=str(i), content="public " + str(i))})
    for i, fields in enumerate(({"channel": "reasoning"}, {"phase": "future_reasoning"}, {"channel": "analysis"}, {"phase": "summary"})):
        records.append({"type": "response_item", "payload": dict(fields, type="message", role="assistant", id="private" + str(i), content="PRIVATE_REASONING")})
    records.extend([
        {"type": "response_item", "payload": {"type": "function_call_output", "role": "tool", "content": {"unsupported": "TOOL_OUTPUT"}}},
        {"type": "response_item", "payload": {"type": "reasoning", "role": "assistant", "content": "PRIVATE_REASONING"}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "id": "legacy", "content": [{"type": "Text", "text": "legacy public"}]}}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage", "id": "private-event", "phase": "reasoning", "content": "PRIVATE_REASONING"}}},
    ])
    jsonl(root / "sessions/2026/10/08/rollout-one.jsonl", records)
    items, errors = s.discover("codex", root)
    check(not errors and len(items) == 1)
    check(len(items[0]["messages"]) == len(public) + 1)
    check("PRIVATE_REASONING" not in json.dumps(items) and "TOOL_OUTPUT" not in json.dumps(items))

    # Multiple identities inside a single file cannot be merged into the first.
    for kind in ("claude", "codex", "qwen"):
        root = temp / ("mixed-" + kind)
        records = [row("one"), row("two", "second", "v")] if kind != "codex" else [codex_meta("one"), codex_meta("two")]
        relative = "sessions/2026/10/08/rollout-one.jsonl" if kind == "codex" else "projects/hash/one.jsonl"
        jsonl(root / relative, records)
        items, errors = s.discover(kind, root)
        check(not items and any("Conflicting native session identities" in e for e in errors))

    # Sidechain and metadata-only entries are deliberately not prose failures.
    root = temp / "metadata"
    jsonl(root / "projects/hash/empty.jsonl", [{"sessionId": "empty", "cwd": "/project", "timestamp": "2026-10-08T12:00:00Z", "type": "progress"}])
    jsonl(root / "projects/hash/child.jsonl", [dict(row("child", "private sidechain"), isSidechain=True)])
    jsonl(root / "projects/hash/tool.jsonl", [dict(row("tool", ""), message={"role": "assistant", "content": None, "tool_calls": [{"secret": "tool"}]})])
    items, errors = s.discover("claude", root)
    check(not errors and {i["session_id"] for i in items} == {"empty", "tool"})
    check(all(not item["messages"] for item in items))

    # Unknown user/assistant formats report coverage failures rather than success.
    for kind in ("claude", "codex", "gemini"):
        root = temp / ("unsupported-" + kind)
        if kind == "claude":
            records = [dict(row(), message={"role": "user", "parts_v2": [{"text": "important"}]})]
            jsonl(root / "projects/hash/one.jsonl", records)
        elif kind == "codex":
            jsonl(root / "sessions/2026/10/08/rollout-one.jsonl", [codex_meta(), {"type": "conversation_v2", "payload": {"role": "user", "text": "important"}}])
        else:
            path = root / "tmp/hash/chats/session-one.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"sessionId": "one", "startTime": "2026-10-08T12:00:00Z", "messages": [{"type": "user", "parts_v2": [{"text": "important"}]}]}), encoding="utf-8")
        items, errors = s.discover(kind, root)
        check(not items and any("Unsupported conversation" in e for e in errors))
        if kind == "gemini":
            items, errors = s.discover(kind, root, with_messages=False)
            check(not errors and len(items) == 1 and not items[0]["messages"])
    for content in ({"parts_v2": ["important"]}, [{"type": "future_text", "text": "important"}], [{"type": "text", "text": 3}]):
        root = temp / ("shape-" + str(checks))
        jsonl(root / "projects/hash/one.jsonl", [row(content=content)])
        items, errors = s.discover("claude", root)
        check(not items and bool(errors))
    check(s.message_prose({"role": "tool", "content": {"unknown": "secret"}}) is None)
    check(s.prose("assistant", [{"type": "thinking", "thinking": "private"}, {"type": "tool_use", "id": "tool"}, {"type": "text", "text": "한글 café 🙂"}]) == {"role": "assistant", "content": "한글 café 🙂"})
    root = temp / "muse-metadata"
    jsonl(root / "sessions/2026/10/08/one/session.jsonl", [
        {"payload_type": "runtime.session.metadata", "payload": {"record": {"workspace_root": "/project"}}},
        {"record_type": "message", "payload": {"role": "user", "parts_v2": [{"text": "important"}]}},
    ])
    items, errors = s.discover("muse", root)
    check(not items and any("Unsupported conversation" in e for e in errors))
    items, errors = s.discover("muse", root, with_messages=False)
    check(not errors and len(items) == 1 and not items[0]["messages"])

    # Duplicate copies/prefixes dedup, but conflicting source metadata/prose do not.
    root = temp / "duplicates-valid"
    jsonl(root / "projects/a/one.jsonl", [row()])
    jsonl(root / "projects/b/two.jsonl", [row(), row(content="more", ident="v")])
    items, errors = s.discover("claude", root)
    check(not errors and len(items) == 1 and len(items[0]["messages"]) == 2)
    for conflict in (row(cwd="/other"), dict(row(), timestamp="2026-10-09T12:00:00Z"), row(content="different")):
        root = temp / ("duplicate-conflict-" + str(checks))
        jsonl(root / "projects/a/one.jsonl", [row()])
        jsonl(root / "projects/b/two.jsonl", [conflict])
        jsonl(root / "projects/c/three.jsonl", [row()])
        items, errors = s.discover("claude", root)
        check(not items and any("conflicting duplicate native session ID" in e for e in errors))

    # Incomplete-tail status reaches capture callers; completed prefixes remain
    # readable. Metadata-only checks do not need to materialize conversation tails.
    root = temp / "partial"
    path = jsonl(root / "projects/hash/one.jsonl", [row()])
    path.write_bytes(path.read_bytes() + b'{"message":')
    items, errors = s.discover("claude", root)
    check(not errors and items[0].get("_incomplete") is True and len(items[0]["messages"]) == 1)
    status = {}
    check(len(list(s.read_records(path, status))) == 1 and status.get("incomplete") is True)
    complete = jsonl(root / "early-eof.jsonl", [row()])
    status = {}
    with patch.object(s.os, "fstat", return_value=SimpleNamespace(st_size=complete.stat().st_size + 100)):
        check(len(list(s.read_records(complete, status))) == 1 and status.get("incomplete") is True)
    path.write_bytes(path.read_bytes() + b"\nbad\n")
    items, errors = s.discover("claude", root)
    check(not items and any("Malformed JSON" in e for e in errors))

    # Bad numeric source dates must remain per-file errors so another healthy
    # source in that provider can still be captured. Bad SQLite is one source.
    for timestamp in (float("inf"), 10 ** 400):
        root = temp / ("numeric-" + str(checks))
        jsonl(root / "projects/hash/bad.jsonl", [dict(row("bad"), timestamp=timestamp)])
        jsonl(root / "projects/hash/healthy.jsonl", [row("healthy")])
        items, errors = s.discover("claude", root)
        check({item["session_id"] for item in items} == {"healthy"} and len(errors) == 1)
    root = temp / "numeric-opencode"
    root.mkdir()
    with sqlite3.connect(root / "opencode.db") as db:
        db.executescript("create table session(id,directory,title,time_created,parent_id);create table message(id,session_id,data,time_created);create table part(id,message_id,data,time_created);")
        db.execute("insert into session values(?,?,?,?,?)", ("bad", "/project", "Bad", float("inf"), None))
    db.close()
    items, errors = s.discover("opencode", root)
    check(not items and len(errors) == 1)
    store_file = temp / "store-is-file"
    store_file.write_text("not a store", encoding="utf-8")
    items, errors = s.discover("claude", store_file)
    check(not items and len(errors) == 1 and "store is not a directory" in errors[0])
    return checks


with tempfile.TemporaryDirectory(prefix="cly-source-checks-") as temporary:
    checks += source_boundary_checks(Path(temporary))

def catch_fixture(folder, contents):
    os.environ["CLY_LIBRARY_HOME"] = str(folder / "library")
    os.environ["CLY_STATE_HOME"] = str(folder / "state")
    index = {"schema": 1, "sessions": {}, "errors": []}
    for i, content in enumerate(contents):
        item = {"agent": "codex", "session_id": "regression-" + str(i), "started": "2026-10-08T10:00:00+00:00",
                "directory": str(folder), "title": "Regression", "messages": [{"role": "user", "content": content}]}
        w.store_session(item, index)
    w.atomic(w.library() / "index.json", index)
    return index


def queried(command, kwargs):
    return kwargs.get("env", {}).get("CLY_WORKFLOW_QUERY") == "1"


with tempfile.TemporaryDirectory(prefix="cly-catch-up-") as temporary, patch.dict(os.environ, {}), patch.object(w, "bash", return_value="stub-bash"):
    base = Path(temporary)
    index = catch_fixture(base / "empty", ["ordinary prose"])
    model_calls = []
    def empty_model(command, **kwargs):
        if queried(command, kwargs):
            return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
        model_calls.append(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, '{"notes":[]}', "")
    with patch.object(w.subprocess, "run", side_effect=empty_model):
        path, count = w.catch_up(index, "audit", "chosen", True)
        first_calls = len(model_calls)
        again, again_count = w.catch_up(index, "audit", "chosen", True)
    proposal = w.read(path)
    check(proposal["notes"] == [] and proposal["outcome"] == "no-findings" and count == again_count == 1)
    check(len(model_calls) == first_calls == 1 and w.read(again)["outcome"] == "no-findings")
    check(all("filed_revision" not in record and "reviewed_revision" not in record for record in index["sessions"].values()))

    with patch.object(w, "CATCH_UP_BYTES", 3000):
        text = "Unicode α\n\u0001" * 2000
        index = catch_fixture(base / "fragments", [text])
        model_calls.clear()
        with patch.object(w.subprocess, "run", side_effect=empty_model):
            path, count = w.catch_up(index, "audit", "chosen", True)
            first_calls = len(model_calls)
            w.catch_up(index, "audit", "chosen", True)
        check(first_calls > 1 and len(model_calls) == first_calls)
        parts = [json.loads(prompt.split("<session-data>\n", 1)[1].rsplit("\n</session-data>", 1)[0]) for prompt in model_calls]
        pieces = [message for part in parts for message in part["messages"]]
        check("".join(piece["content"] for piece in pieces) == text)
        check(all(len(prompt.encode()) <= 3000 for prompt in model_calls))
        check(w.read(path)["outcome"] == "no-findings")

        index = catch_fixture(base / "batch-retry", ["x" * 1600, "y" * 1600, "z" * 1600])
        attempts, fail_second = [], True
        def batch_model(command, **kwargs):
            if queried(command, kwargs):
                return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
            attempts.append(kwargs["input"])
            if fail_second and len(attempts) == 2:
                return subprocess.CompletedProcess(command, 1, "", "interrupted")
            return subprocess.CompletedProcess(command, 0, "# Compact review\n", "")
        with patch.object(w.subprocess, "run", side_effect=batch_model):
            fails(lambda: w.catch_up(index, "audit", "chosen"), "pending revisions kept")
            check(sum("review_batch_receipt" in record for record in index["sessions"].values()) == 1)
            check(not any("reviewed_revision" in record for record in index["sessions"].values()))
            first_prompt = attempts[0]
            fail_second = False
            report, count = w.catch_up(index, "audit", "chosen")
        check(attempts.count(first_prompt) == 1 and count == 3)
        check(not w.pending(index, "reviewed_revision") and report.is_file())

    index = catch_fixture(base / "malformed-cache", ["ordinary prose"])
    calls = []
    def plain_model(command, **kwargs):
        if queried(command, kwargs):
            return subprocess.CompletedProcess(command, 0, "codex\0stub\0store\0", "")
        calls.append(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, "# Review\n", "")
    with patch.object(w.subprocess, "run", side_effect=plain_model):
        w.catch_up(index, "audit", "chosen")
        key, record = next(iter(index["sessions"].items()))
        del record["reviewed_revision"]
        receipt_path = w.library() / record["review_batch_receipt"]["receipt"]
        receipt = w.read(receipt_path)
        receipt["source_revisions"] = []
        w.atomic(receipt_path, receipt)
        w.catch_up(index, "audit", "chosen")
        check(len(calls) == 2)
        del record["reviewed_revision"]
        item_path = w.library() / "sessions" / (key + ".json")
        item = w.read(item_path)
        item["messages"][0]["content"] += " changed"
        w.atomic(item_path, item)
        before = len(calls)
        fails(lambda: w.catch_up(index, "audit", "chosen"), "revision mismatch")
        check(len(calls) == before)

print(f"workflow checks: {checks} passed (fixtures + managed-process integration; no live agents or terminals)")
