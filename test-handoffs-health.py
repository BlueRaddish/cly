#!/usr/bin/env python3
"""Run python test-handoffs-health.py. Isolated files; no agents or startup edits."""
from argparse import Namespace
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib/cly"))
import handoffs as h
import profiles
import sessions
import workflows as w

checks = 0


def check(value):
    global checks
    assert value
    checks += 1


def fails(call, match):
    try:
        call()
    except (ValueError, OSError) as exc:
        check(match in str(exc))
    else:
        raise AssertionError("Expected failure: " + match)


with tempfile.TemporaryDirectory(prefix="cly-handoff-") as directory:
    temp = Path(directory)
    env = {"CLY_STATE_HOME": str(temp / "state"), "CLY_LIBRARY_HOME": str(temp / "source")}
    item = {"agent": "codex", "session_id": "test-session", "title": "Named work", "directory": "/original/project",
            "started": "2026-10-08T12:00:00Z", "messages": [{"role": "user", "content": "Selected context"}]}
    project = temp / "project"
    project.mkdir()
    context = project / "decisions.md"
    context.write_text("Verified decision v1\n", encoding="utf-8")
    args = Namespace(file=temp / "handoff-v1.json", session=["codex:test-session"], context=[context],
                     project="test-project", project_root=project, target_agent="claude")
    with patch.dict(os.environ, env):
        index = {"schema": 1, "sessions": {}, "errors": []}
        w.store_session(item, index)
        w.atomic(w.library() / "index.json", index)
        receipt = h.export(w, args)
        packet = h.load(w, args.file)
        check(receipt["sha256"] == hashlib.sha256(args.file.read_bytes()).hexdigest())
        check(packet["payload"]["contexts"][0]["source"]["uri"] == "project://test-project/decisions.md")
        check(h.export(w, args)["revision"] == receipt["revision"])
        preview = h.render(w, args.file)
        check("Selected context" in preview and "Verified decision v1" in preview and packet["revision"] in preview)
        tampered = json.loads(args.file.read_text())
        tampered["payload"]["sessions"][0]["session"]["title"] = "tampered"
        fails(lambda: h.validate(w, tampered), "checksum")
        tampered["revision"] = h.digest(tampered["payload"])
        fails(lambda: h.validate(w, tampered), "revision mismatch")
        invalid = json.loads(args.file.read_text())
        invalid["payload"]["sessions"][0]["session"]["messages"][0]["role"] = "tool"
        invalid["revision"] = h.digest(invalid["payload"])
        fails(lambda: h.validate(w, invalid), "prose")
        invalid = json.loads(args.file.read_text())
        invalid["payload"]["sessions"][0]["session"]["started"] = "not-a-date"
        invalid["revision"] = h.digest(invalid["payload"])
        fails(lambda: h.validate(w, invalid), "Invalid isoformat")
        args.context = [temp / "outside.txt"]
        args.context[0].write_text("outside", encoding="utf-8")
        fails(lambda: h.export(w, args), "outside project root")
        args.context = [context]
        args.project = None
        fails(lambda: h.export(w, args), "project context")
        args.project = "test-project"

    with patch.dict(os.environ, dict(env, CLY_LIBRARY_HOME=str(temp / "receiver"))):
        imported = h.import_packet(w, args.file)
        check(all(entry["status"] == "imported" for entry in imported["outcomes"]))
        check(all(entry["status"] == "current" for entry in h.import_packet(w, args.file)["outcomes"]))
        received = w.read(w.library() / "index.json")
        check(w.captured_session(w.note_key(item), received["sessions"][w.note_key(item)]) == item)
        check(imported["source_packet"] and Path(imported["source_packet"]).is_file())

    # Sender changes flow forward; stale and sibling data never overwrite receivers.
    with patch.dict(os.environ, env):
        context.write_text("Verified decision v2\n", encoding="utf-8")
        updated = dict(item, messages=item["messages"] + [{"role": "assistant", "content": "Verified continuation"}])
        w.store_session(updated, index)
        w.atomic(w.library() / "index.json", index)
        args.file = temp / "handoff-v2.json"
        second = h.export(w, args)
        packet2 = h.load(w, args.file)
        check(packet2["handoff_id"] == packet["handoff_id"] and packet2["revision"] != packet["revision"])
        check(packet2["payload"]["contexts"][0]["parent_revision"] == packet["payload"]["contexts"][0]["revision"])
        args.file = temp / "handoff-copy.json"
        check(h.export(w, args)["revision"] == second["revision"])
        args.file = temp / "handoff-v1.json"
        fails(lambda: h.export(w, args), "Existing handoff preserved")

    with patch.dict(os.environ, dict(env, CLY_LIBRARY_HOME=str(temp / "receiver"))):
        check(all(entry["status"] == "imported" for entry in h.import_packet(w, temp / "handoff-v2.json")["outcomes"]))
        outcomes = h.import_packet(w, temp / "handoff-v1.json")["outcomes"]
        check(outcomes[0]["status"] == "stale" and outcomes[1]["status"] == "conflict")
        received = w.read(w.library() / "index.json")
        divergent = dict(updated, messages=[{"role": "user", "content": "Independent sibling"}])
        w.store_session(divergent, received)
        w.atomic(w.library() / "index.json", received)
        check(h.import_packet(w, temp / "handoff-v2.json")["outcomes"][0]["status"] == "conflict")
        check(w.captured_session(w.note_key(item), received["sessions"][w.note_key(item)]) == divergent)

    with patch.dict(os.environ, env):
        missing = {"profile": "missing", "kind": "codex", "configured": True, "store_exists": False, "errors": []}
        with patch.object(profiles, "discover", return_value=[missing]):
            status = w.document_status(index)
            check(status["schema"] == 1 and status["type"] == "cly-document-health" and status["health"] == "warning")
            check(status["sources"] == [missing] and status["pending_exports"][0]["session_id"] == "test-session")
        # Explicit startup CLI is exercised with its OS registration boundary mocked.
        startup = Namespace(startup_action="enable", interval=60, agent=["codex"])
        operations = []
        with patch.object(w, "set_startup", side_effect=lambda registration, enabled: operations.append(enabled)), patch.object(w, "registered_startup", return_value=True), redirect_stdout(io.StringIO()):
            w.startup_command(startup)
            check(w.startup_status()["enabled"] and w.startup_status()["registered"])
            compile((w.state() / "document-startup.py").read_text(), "startup", "exec")
            startup.startup_action = "disable"
            w.startup_command(startup)
            check(not w.startup_status()["enabled"] and operations == [True, False])
        with patch.object(w, "capture", return_value=(0, dict(index, last_capture=w.now(), errors=[]))), patch.object(w.time, "sleep", side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()):
            try:
                w.watcher(Namespace(agent=["codex"], interval=1))
            except KeyboardInterrupt:
                pass
        health = w.read(w.state() / "document-health.json")
        check(health["last_success"] and health["consecutive_errors"] == 0)
        check(not w.collector_status()["active"])
        w.atomic(w.state() / "document-health.json", dict(health, last_attempt=w.now(), errors=["collector source failure"]))
        with patch.object(profiles, "discover", return_value=[]):
            check(w.document_status(index)["health"] == "error")
        w.atomic(w.state() / "document-health.json", health)
        writer = temp / "writer"
        writer.write_text("unused", encoding="utf-8")
        calls = []
        def uncertain(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 1, "", "offline")
        with patch.object(w, "bash", return_value="bash"), patch.object(w.subprocess, "run", side_effect=uncertain):
            check(w.publish(index, writer, temp / "vault")[0] == 0)
            count = len(calls)
            check(w.publish(index, writer, temp / "vault")[0] == 0)
            check(len(calls) == count + 1 and "--check" in calls[-1])
            with patch.object(profiles, "discover", return_value=[]):
                check(w.document_status(index)["health"] == "error")
        check(index["sessions"][w.note_key(item)].get("published_revision") != sessions.revision(updated))
        calls.clear()
        with patch.object(w, "bash", return_value="bash"), patch.object(w.subprocess, "run", side_effect=lambda command, **kwargs: (calls.append(command) or subprocess.CompletedProcess(command, 0, "verified", ""))):
            check(w.publish(index, writer, temp / "vault")[0] == 1)
            check(len(calls) == 1 and "--check" in calls[0])
        publication = w.read(w.publication_paths(w.note_key(item), sessions.revision(updated))[0])
        check(publication["status"] == "verified" and publication["sha256"] and publication["verified"])

print(checks, "handoff/health checks passed")

