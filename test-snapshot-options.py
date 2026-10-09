#!/usr/bin/env python3
"""Stdlib regression check: python test-snapshot-options.py. No live agents."""
from argparse import Namespace
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib/cly"))
import resume_options as r
import workflows as w

checks = 0


def check(value):
    global checks
    assert value
    checks += 1


def fails(call, message):
    try:
        call()
    except ValueError as exc:
        check(message in str(exc))
    else:
        raise AssertionError("Expected: " + message)


with tempfile.TemporaryDirectory(prefix="cly-options-") as temporary:
    temp = Path(temporary)
    store = temp / "codex"
    source = store / "sessions/2026/10/09/rollout-options.jsonl"
    source.parent.mkdir(parents=True)
    metadata = {"type": "session_meta", "payload": {"id": "options-session", "cwd": str(temp), "timestamp": "2026-10-09T00:00:00Z"}}

    def history(contexts=()):
        source.write_text("".join(json.dumps(row) + "\n" for row in [metadata, *contexts]), encoding="utf-8")

    def context(mode, approval="never", timestamp="2026-10-09T01:00:00Z", **policy):
        return {"type": "turn_context", "timestamp": timestamp,
                "payload": {"sandbox_policy": dict(type=mode, **policy), "approval_policy": approval}}

    history()
    config, stub = temp / "config", temp / "agent"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\nread -r release\n', encoding="utf-8")
    stub.chmod(0o755)
    bash = os.environ.get("CLY_SHELL") or (r"C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
    environment = {"CLY_STATE_HOME": str(temp / "state"), "CLY_CONFIG": str(config), "CODEX_HOME": str(store),
                   "CLY_SHELL": str(bash), "CLY_TRACK": "1", "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"}

    def configure(flags):
        config.write_text("profile.options.bin=" + str(stub).replace("\\", "/") + "\nprofile.options.kind=codex\nprofile.options.dir=none\nprofile.options.flags=" + flags + "\n", encoding="utf-8")

    def launch(argv, changed_context=None):
        child = subprocess.Popen(argv, cwd=temp, env=dict(os.environ), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **w.hidden())
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                active = w.active()
                if active:
                    check(len(active) == 1)
                    if changed_context:
                        changed_context["timestamp"] = datetime.now(timezone.utc).isoformat()
                        history([changed_context])
                    saved = w.save_snapshot()
                    break
                if child.poll() is not None:
                    output, errors = child.communicate()
                    raise AssertionError(output + errors)
                time.sleep(.05)
            else:
                raise AssertionError("Stub was not tracked")
            output, errors = child.communicate("finish\n", timeout=15)
            check(child.returncode == 0)
            check(not w.active())
            return saved, output.splitlines()
        finally:
            if child.poll() is None:
                child.terminate()
                child.communicate()

    with patch.dict(os.environ, environment):
        bypass = r.BYPASS["codex"]
        cases = [("explicit", [], "", [bypass, "--model", "fixture-model", "--search"]),
                 ("cly-x", ["-x"], "", ["--model", "fixture-model"]),
                 ("standing", [], bypass + " --model fixture-model --search", []),
                 ("scalar", [], "", ["-s", "read-only", "-a", "on-request", "--add-dir", str(temp / "extra"), "-c", "model_reasoning_effort=high"]),
                 ("empty", [], "", [])]
        for name, own, flags, native in cases:
            configure(flags)
            saved, original = launch(w.cly_command(["--here", *own, "options", "resume", "options-session", *native, "PRIVATE_PROMPT"]))
            serialized = json.dumps(saved)
            check("PRIVATE_PROMPT" not in serialized)
            check("resume_options" in saved["sessions"][0])
            # A later profile edit and caller override must not contaminate restore.
            configure("--sandbox workspace-write --search --model changed-model")
            with patch.dict(os.environ, CLY_FLAGS="--model environment-model"):
                plan = w.restore_plan(saved)
                _, restored = launch(plan[0]["argv"])
            check(restored == ["resume", "options-session", *saved["sessions"][0]["resume_options"]["args"]])
            check("changed-model" not in restored and "environment-model" not in restored)
            check(saved["sessions"][0]["bypass"] == (name in {"explicit", "cly-x", "standing"}))
            if name == "explicit":
                check(restored == original[:-1])

        configure("")
        history()
        stamp = datetime.now(timezone.utc).isoformat()
        # A new native turn records an in-client change from launch full access.
        changed = context("workspace-write", "on-request", stamp, network_access=True, writable_roots=[str(temp / "extra")])
        saved, _ = launch(w.cly_command(["--here", "options", "resume", "options-session", bypass]), changed)
        options = saved["sessions"][0]["resume_options"]
        check(not saved["sessions"][0]["bypass"] and options["permissions"] == "native-history")
        check("workspace-write" in options["args"] and "sandbox_workspace_write.network_access=true" in options["args"])
        check(bypass not in options["args"] and str(temp / "extra") in options["args"])

        # Adoption can read previous exact history when no launch policy is known.
        history([context("danger-full-access")])
        with redirect_stdout(io.StringIO()):
            w.snapshot_command(Namespace(action="adopt", pid=os.getpid(), profile="options", kind="codex",
                                         session_id="options-session", directory=str(temp), bypass=False, resume_arg=[]))
        adopted = w.active()
        check(len(adopted) == 1 and adopted[0]["bypass"])
        check(adopted[0]["resume_options"]["permissions"] == "native-history")
        w.atomic(w.state() / "runs" / (adopted[0]["run_id"] + ".json"), dict(adopted[0], birth="stale"))

        # Explicit adoption settings win over pre-adoption historical policy.
        with redirect_stdout(io.StringIO()):
            w.snapshot_command(Namespace(action="adopt", pid=os.getpid(), profile="options", kind="codex",
                                         session_id="options-session", directory=str(temp), bypass=False,
                                         resume_arg=["--sandbox", "read-only", "--ask-for-approval", "on-request"]))
        adopted = w.active()
        check(len(adopted) == 1 and not adopted[0]["bypass"])
        check(adopted[0]["resume_options"]["args"] == ["--sandbox", "read-only", "--ask-for-approval", "on-request"])

        unknown = r.capture("codex", ["--api-key=PRIVATE_TOKEN", "--config", "credentials.token=PRIVATE_TOKEN", "PRIVATE_PROMPT"])
        check("PRIVATE" not in json.dumps(unknown))
        check(unknown["omitted_flags"] == ["--api-key", "--config"])
        unsafe = dict(saved, sessions=[dict(saved["sessions"][0], resume_options=unknown)])
        fails(lambda: w.restore_plan(unsafe, query=False), "unsupported launch options")
        for args in (["--unknown", "value"], ["--model"], ["--sandbox", "wide-open"], ["--config", "hooks.command=evil"], ["--model", "bad\nvalue"]):
            fails(lambda args=args: r.validate("codex", {"args": args}), "saved")
        check(r.capture("codex", ["--remote", "unix://", "resume", "options-session", bypass])["args"] == [bypass])
        check(r.capture("codex", ["--", "--model", "PRIVATE_PROMPT"])["args"] == [])
        check(r.capture("claude", ["--resume", "--model", "fixture"])["args"] == ["--model", "fixture"])
        check(r.bypass("claude", r.capture("claude", ["--permission-mode", "bypassPermissions"])))
        check(r.capture("claude", ["--model", "fixture", "--dangerously-skip-permissions", "--settings", "PRIVATE_SETTINGS"])["omitted_flags"] == ["--settings"])
        check("--wrapper-command" in r.capture("claude", ["launch", "claude", "--model", "fixture", "--", "--dangerously-skip-permissions"])["omitted_flags"])
        check(not r.bypass("codex", r.capture("codex", ["--model", "never", "--profile", "danger-full-access"])))
        check(r.capture("codex", ["--approve-for-me"])["permissions"] == "launch")
        check(r.bypass("codex", r.capture("codex", ["-c", 'sandbox_mode="danger-full-access"', "-c", 'approval_policy="never"'])))
        base = {"kind": "codex", "session_id": "options-session", "started": "2026-10-09T00:00:00Z",
                "resume_options": r.capture("codex", ["--add-dir", str(temp / "removed"), "--sandbox", "danger-full-access"])}
        history([context("workspace-write", writable_roots=[], network_access=False)])
        r.native(base, source)
        check(str(temp / "removed") not in base["resume_options"]["args"])
        history([context("unsupported-mode")])
        fails(lambda: r.native(base, source), "cannot be represented")
        history([context("workspace-write", approval={"granular": {}})])
        fails(lambda: r.native(base, source), "cannot be represented")
        foreign = dict(base, session_id="other-session")
        fails(lambda: r.native(foreign, source), "identity mismatch")
        fails(lambda: r.validate("codex", {"args": [], "permissions": []}), "permission source")
        bad_config = r.capture("codex", ["-c", "sandbox_workspace_write.network_access=PRIVATE_TOKEN"])
        check(bad_config["omitted_flags"] == ["-c"] and not bad_config["args"])
        history()
        legacy = dict(saved, sessions=[{key: value for key, value in saved["sessions"][0].items() if key != "resume_options"}])
        with redirect_stderr(io.StringIO()) as errors:
            check(len(w.restore_plan(legacy, query=False)) == 1)
        check("legacy snapshot" in errors.getvalue())

print(str(checks) + " snapshot option checks passed (disposable agents; no live terminals)")
