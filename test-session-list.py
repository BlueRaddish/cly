"""Run with Python; checks native identity filtering and launcher name lookup."""
import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "lib/cly"))
import session_list


def run(args, env, input=None):
    shell = os.environ.get("CLY_SHELL") or shutil.which("bash")
    if os.name == "nt":
        shell = os.environ.get("CLY_SHELL") or r"C:\Program Files\Git\bin\bash.exe"
    return subprocess.run([shell, str(BASE / "bin/cly").replace("\\", "/"), *args],
                          env=env, input=input, capture_output=True, text=True,
                          encoding="utf-8", timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    store = root / "codex"
    rolls = store / "sessions/2026/10/08"
    rolls.mkdir(parents=True)
    one, child = "user-one", "child-one"
    for sid, source in ((one, "vscode"), (child, {"subagent": {"thread_spawn": {"parent_thread_id": one}}})):
        path = rolls / ("rollout-" + sid + ".jsonl")
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": sid, "timestamp": "2026-10-08T12:00:00Z", "cwd": str(root), "source": source}}) + "\n", encoding="utf-8")
    with closing(sqlite3.connect(store / "state_5.sqlite")) as db:
        db.execute("create table threads(id text,cwd text,created_at integer,updated_at integer,title text,name text,rollout_path text,source text)")
        for sid, source, title, name in ((one, "vscode", "Old title", "Named project"),
                                       (child, json.dumps({"subagent": {"thread_spawn": {}}}), "", "random-child-key")):
            db.execute("insert into threads values(?,?,?,?,?,?,?,?)", (sid, str(root), 1791450000, 1791460000, title, name,
                                                                      str(rolls / ("rollout-" + sid + ".jsonl")), source))
        db.commit()
    (store / "session_index.jsonl").write_text(json.dumps({"id": one, "thread_name": "Stale name"}) + "\n", encoding="utf-8")
    stub = root / "stub"
    stub.write_text('#!/usr/bin/env bash\nprintf "PROFILE_ENV=%s\\n" "$CODEX_HOME"\nprintf "ARG=%s\\n" "$@"\n', encoding="utf-8")
    stub.chmod(0o755)
    config = root / "config"
    config.write_text("profile.personal.bin=codex\nprofile.personal.flags=\nprofile.personal.env=CODEX_HOME=$TEST_STORE\n", encoding="utf-8")
    env = dict(os.environ, CLY_CONFIG=str(config), TEST_STORE=str(store), CLY_BIN=str(stub).replace("\\", "/"),
               CLY_TRACK="0", CLY_SESSION_READER="auto", PYTHONUTF8="1")
    for variable in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "GEMINI_CLI_HOME", "KIMI_CODE_HOME", "CLY_MUSE_HOME", "QWEN_HOME", "CLY_OPENCODE_HOME"):
        env[variable] = str(root / "empty" / variable)
    original = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        items, errors = session_list.inventory("codex")
        assert not errors, errors
        assert [(item["session_id"], item["title"], item["profile"]) for item in items] == [(one, "Named project", "personal")]
        assert session_list.epoch(items[0]["_updated"]) == 1791460000
    finally:
        os.environ.clear()
        os.environ.update(original)
    result = run(["--list-sessions"], env)
    assert result.returncode == 0, result.stderr
    rows = [line.split("\x1f") for line in result.stdout.splitlines()]
    assert len(rows) == 1 and len(rows[0]) == 5 and rows[0][2:] == [one, str(root), "Named project"], rows
    result = run(["--find", "Named project"], env)
    assert result.returncode == 2 and "Named project" in result.stdout and "random-child-key" not in result.stdout, result
    result = run(["--find", "missing"], env)
    assert result.returncode == 2 and "Named project" not in result.stdout, result
    result = run(["--session", "codex:" + child], env)
    assert result.returncode == 2 and "session not found" in result.stderr, result
    result = run(["--session", "codex:" + one], env)
    assert result.returncode == 0 and "ARG=resume\nARG=user-one" in result.stdout, result
    assert str(store) in result.stdout, result
    result = run(["-r"], dict(env, CLY_ASSUME_TTY="1"), "nNamed project\n")
    assert result.returncode == 0 and "ARG=user-one" in result.stdout, result
    result = run(["--find", "Named project"], dict(env, CLY_ASSUME_TTY="1"), "\n")
    assert result.returncode == 0 and "ARG=user-one" in result.stdout, result
    assert session_list.clean("title\x1b[2J\x1f\n한글") == "title [2J  한글"
    assert len(session_list.terminal_title({"title": "prompt" * 22000})) == 240
    assert session_list.terminal_title({"title": "name" * 200, "name": "name" * 200}) == "name" * 200

print("Session list checks passed")
