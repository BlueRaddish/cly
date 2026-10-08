#!/usr/bin/env python3
"""Run profile, native metadata and exact lifecycle checks without live agents."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib/cly"))
import profiles
import sessions
import tracking
import workflows


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Untrusted input should fail")


with tempfile.TemporaryDirectory(prefix="cly-discovery-") as temporary:
    temp = Path(temporary)
    stores = {name: str(temp / name) for name in profiles.STORE_VARIABLES.values()}
    environment = dict(stores, CLY_CONFIG=str(temp / "config"), CLY_STATE_HOME=str(temp / "state"),
                       CLY_LIBRARY_HOME=str(temp / "library"), OTHER_CODEX=str(temp / "other"))
    with patch.dict(os.environ, environment):
        config = temp / "config"
        config.write_text("\n".join([
            "profile.work.bin=codex.cmd",
            "profile.work.env=CODEX_HOME=$OTHER_CODEX PRIVATE_API_KEY=secret",
            "profile.personal.kind=codex",
            "profile.personal.bin=wrapper",
            "profile.unknown.bin=custom-agent",
            "profile.muse.bin=muse.cmd",
        ]), encoding="utf-8")
        sources = profiles.discover(configured_only=True)
        assert {item["profile"] for item in sources} == {"work", "personal", "unknown", "muse"}
        assert "secret" not in json.dumps(sources)
        assert sources[0]["store"] == str(temp / "other")
        assert sources[2]["store"] is None and sources[2]["capabilities"]["capture"] == "unsupported"
        assert sources[3]["capabilities"]["export"] == "manual"
        assert {x["profile"] for x in profiles.discover(["codex"])} == {"work", "personal"}
        assert sessions.is_subagent_source('{"subagent":{"thread_spawn":{"depth":1}}}')
        assert sessions.is_subagent_source({"subagent": "spawn"})
        assert sessions.is_subagent_source("subagent_review")
        assert not sessions.is_subagent_source("cli")
        assert not sessions.is_subagent_source('{"source":"cli"}')

        claude = sessions.root("claude")
        claude_log = jsonl(claude / "projects/project/claude-one.jsonl", [
            {"sessionId": "claude-one", "cwd": str(temp), "timestamp": "2026-10-08T10:00:00Z", "message": {"role": "user", "content": "Original prompt"}},
        ])
        jsonl(claude / "history.jsonl", [
            {"sessionId": "claude-one", "display": "/resume", "timestamp": 1791453600000},
            {"sessionId": "claude-one", "display": "First real prompt", "timestamp": 1791457200000},
        ])
        title_file = claude_log.with_suffix("") / "custom-title.json"
        title_file.parent.mkdir()
        title_file.write_text('{"customTitle":"Named Claude session"}', encoding="utf-8")
        claude_items, errors = sessions.discover("claude", with_messages=False)
        assert not errors and claude_items[0]["title"] == claude_items[0]["name"] == "Named Claude session"
        assert claude_items[0]["_updated"] == 1791457200

        muse = sessions.root("muse")
        muse_log = jsonl(muse / "sessions/2026/10/08/muse-one/session.jsonl", [
            {"recorded_at": 1791453600000000, "payload_type": "runtime.session.metadata", "payload": {"record": {"workspace_root": str(temp)}}},
        ])
        # A metadata request must not read later native prose/events.
        muse_log.write_bytes(muse_log.read_bytes() + b'not recognized native event\n')
        muse_items, errors = sessions.discover("muse", with_messages=False)
        assert not errors and muse_items[0]["directory"] == str(temp)
        with sqlite3.connect(muse / "session-index.db") as db:
            db.execute("create table sessions(session_id,session_log_path,workspace_root,title,created_at_us,updated_at_us,session_name,msp_parent_session_id)")
            db.execute("insert into sessions values(?,?,?,?,?,?,?,?)", ("muse-one", str(muse_log), str(temp), "Generated title", 1791453600000000, 1791457200000000, "Named Muse session", None))
        db.close()
        muse_items, errors = sessions.discover("muse", with_messages=False)
        assert not errors and muse_items[0]["title"] == "Named Muse session" and muse_items[0]["_updated"] == 1791457200

        store = sessions.root("codex")
        first = jsonl(store / "sessions/2026/10/08/rollout-main.jsonl", [
            {"type": "session_meta", "payload": {"id": "main", "cwd": str(temp), "source": "cli", "timestamp": "2026-10-08T10:00:00Z"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "hello"}},
        ])
        child = jsonl(store / "sessions/2026/10/08/rollout-child.jsonl", [
            {"type": "session_meta", "payload": {"id": "child", "cwd": str(temp), "source": {"subagent": "spawn"}, "timestamp": "2026-10-08T10:00:00Z"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "child prompt"}},
        ])
        indexonly = jsonl(store / "sessions/2026/10/08/rollout-index.jsonl", [
            {"type": "session_meta", "payload": {"id": "index", "cwd": str(temp), "source": "vscode", "timestamp": "2026-10-08T10:00:00Z"}},
        ])
        with sqlite3.connect(store / "state_9.sqlite") as db:
            db.execute("create table threads(id,cwd,created_at,updated_at,title,name,rollout_path,source)")
            db.execute("insert into threads values(?,?,?,?,?,?,?,?)", ("main", str(temp), 1791453600, 1791457200, "First prompt", "My named conversation", str(first), "cli"))
            db.execute("insert into threads values(?,?,?,?,?,?,?,?)", ("child", str(temp), 1791453600, 1791457200, "randomized key", None, str(child), '{"subagent":{"thread_spawn":{"depth":1}}}'))
        db.close()
        jsonl(store / "session_index.jsonl", [{"id": "main", "thread_name": "Older name", "updated_at": "2026-10-08T11:00:00Z"},
                                               {"id": "index", "thread_name": "Old index title"},
                                               {"id": "index", "thread_name": "Latest index title"}])
        metadata, errors = sessions.discover("codex", with_messages=False)
        assert not errors and {x["session_id"] for x in metadata} == {"main", "index"}
        by_id = {x["session_id"]: x for x in metadata}
        assert by_id["main"]["title"] == by_id["main"]["name"] == "My named conversation"
        assert by_id["main"]["_updated"] == 1791457200
        assert by_id["index"]["title"] == "Latest index title"
        captures, errors = sessions.discover("codex")
        assert not errors and {x["session_id"] for x in captures} == {"main", "index"}
        assert captures[0]["title"] in {"My named conversation", "Latest index title"}

        run = {"schema": 1, "run_id": "run", "kind": "codex", "profile": "personal", "pid": os.getpid(),
               "birth": workflows.birth(os.getpid()), "native_root": str(store), "directory": str(temp), "session_id": None}
        workflows.atomic(workflows.state() / "runs/run.json", run)
        payload = {"hook_event_name": "SessionStart", "session_id": "main", "transcript_path": str(first),
                   "source": "startup", "prompt": "DO NOT CAPTURE THIS"}
        receipt = tracking.receive("codex", payload, "run")
        assert receipt["accepted"] and receipt["revision"] == 1
        assert workflows.resolve(dict(run))["session_id"] == "main"
        switched = dict(payload, session_id="index", transcript_path=str(indexonly), source="resume")
        assert tracking.receive("codex", switched, "run")["revision"] == 2
        resolved = workflows.resolve(dict(run))
        assert resolved["session_id"] == "index" and resolved["binding"] == "hook"
        assert "DO NOT CAPTURE THIS" not in (workflows.state() / "tracking/run.json").read_text()
        assert not tracking.receive("codex", dict(payload, session_id="child", transcript_path=str(child)), "run")["accepted"]
        assert not tracking.receive("codex", dict(payload, hook_event_name="SubagentStart"), "run")["accepted"]
        rejected(lambda: tracking.receive("codex", dict(payload, transcript_path=str(temp / "outside.jsonl")), "run"))
        rejected(lambda: tracking.receive("codex", dict(payload, session_id="index"), "run"))
        rejected(lambda: tracking.receive("codex", payload, "../outside"))
        assert "SessionStart" in tracking.hook_config("claude")["hooks"]
        command, env, status = tracking.prepare("claude", ["claude", "--continue"], "claude-run", workflows.state())
        assert command[1] == "--settings" and env["CLY_RUN_ID"] == "claude-run" and status["mode"] == "hooks"
        command, env, status = tracking.prepare("claude", ["claude", "--settings", "user.json"], "claude-run", workflows.state())
        assert command == ["claude", "--settings", "user.json"] and status["mode"] == "hooks-available"
        command, env, status = tracking.prepare("codex", ["codex", "resume", "main"], "codex-run", workflows.state())
        assert command == ["codex", "resume", "main"] and status["mode"] == "hooks-available"

        claude_run = dict(run, kind="claude", run_id="claude-hook", native_root=str(claude))
        workflows.atomic(workflows.state() / "runs/claude-hook.json", claude_run)
        hook = tracking.hook_config("claude")["hooks"]["SessionStart"][0]["hooks"][0]
        assert hook["shell"] == "bash" and "\\" not in hook["command"]
        hook_input = dict(payload, session_id="claude-one", transcript_path=str(claude_log))
        hook_env = dict(os.environ, CLY_RUN_ID="claude-hook")
        shell = os.environ.get("CLY_SHELL") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else "bash")
        process = subprocess.run([shell, "-c", hook["command"]], input=json.dumps(hook_input).encode(),
                                 env=hook_env, capture_output=True, **workflows.hidden())
        assert process.returncode == 0, process.stderr
        assert not process.stdout
        assert workflows.resolve(dict(claude_run))["session_id"] == "claude-one"

        # The collector visits every profile store, even two of the same agent.
        other = Path(sources[0]["store"])
        jsonl(other / "sessions/2026/10/08/rollout-other.jsonl", [
            {"type": "session_meta", "payload": {"id": "other", "cwd": str(temp), "source": "cli", "timestamp": "2026-10-08T10:00:00Z"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Other profile"}},
        ])
        changed, library = workflows.capture(["codex"])
        assert changed == 2 and not library["errors"]
        provider = library["providers"]["codex"]
        assert provider["sessions_found"] == 3 and provider["prose_sessions"] == 2
        assert {x["profile"] for x in provider["profiles"]} == {"work", "personal"}
        assert provider["capabilities"]["capture"] == "native"
        changed, library = workflows.capture(["codex"])
        assert changed == 0 and not library["errors"]

print("Profile discovery, subagent filtering, session names, lifecycle switches and multi-store capture passed.")
