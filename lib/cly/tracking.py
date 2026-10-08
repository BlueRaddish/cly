"""Bind supported lifecycle events to a cly run, never by store timing."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import sessions

KINDS = ("claude", "codex")


def hook_config(kind):
    if kind not in KINDS:
        raise ValueError("Lifecycle hooks are supported for Claude and Codex")
    arguments = [sys.executable.replace("\\", "/"), str(Path(__file__).resolve()).replace("\\", "/"), "--event", kind]
    command = shlex.join(arguments) if kind == "claude" or os.name != "nt" else subprocess.list2cmdline(arguments)
    handler = {"type": "command", "command": command, "timeout": 5}
    if kind == "claude":
        handler["shell"] = "bash"
    return {"hooks": {"SessionStart": [{"matcher": "startup|resume|clear|compact" + ("|fork" if kind == "claude" else ""),
                                        "hooks": [handler]}]}}


def prepare(kind, command, run_id, state_root):
    """Claude accepts per-launch settings. Other providers keep native trust.

    Codex hooks require review in /hooks; its shared daemon also cannot inherit
    a TUI client's CLY_RUN_ID. Export hook_config for an explicitly configured
    local runtime; report the boundary instead of guessing daemon associations.
    """
    import workflows as w
    environment = dict(os.environ, CLY_RUN_ID=run_id, CLY_STATE_HOME=str(state_root))
    if kind != "claude":
        return command, environment, {"mode": "hooks-available" if kind == "codex" else "manual",
                                      "reason": "Install and trust lifecycle hooks in a runtime inheriting CLY_RUN_ID" if kind == "codex" else "No supported lifecycle hook integration"}
    if any(arg == "--settings" or arg.startswith("--settings=") for arg in command):
        return command, environment, {"mode": "hooks-available", "reason": "Explicit --settings preserved; merge exported lifecycle hooks"}
    path = state_root / "tracking" / "settings" / (run_id + ".json")
    w.atomic(path, hook_config(kind))
    return [command[0], "--settings", str(path), *command[1:]], environment, {"mode": "hooks", "settings": str(path)}


def receive(kind, payload=None, run_id=None):
    """Accept SessionStart only, with an inherited or explicitly supplied run ID."""
    import workflows as w
    if kind not in KINDS:
        raise ValueError("Unsupported lifecycle provider")
    if payload is None:
        raw = sys.stdin.buffer.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("Lifecycle payload exceeds 1 MiB")
        payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Lifecycle payload must be an object")
    if payload.get("hook_event_name") != "SessionStart":
        return {"accepted": False, "reason": "Only main-session SessionStart is tracked"}
    if payload.get("source") not in {"startup", "resume", "clear", "compact"} | ({"fork"} if kind == "claude" else set()):
        raise ValueError("Unsupported SessionStart source")
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sessions.ID_RE.fullmatch(sid):
        raise ValueError("Invalid lifecycle native session ID")
    run_id = run_id or os.environ.get("CLY_RUN_ID")
    if not run_id:
        return {"accepted": False, "reason": "No cly run identity inherited by this runtime"}
    w.safe_component(run_id, "run ID")
    with w.lock(w.state() / "snapshot.lock"):
        record = w.read(w.state() / "runs" / (run_id + ".json"))
        if not record or record.get("kind") != kind or not w.alive(record):
            raise ValueError("Lifecycle run is unavailable or belongs to another provider")
        transcript = payload.get("transcript_path")
        if transcript:
            if not isinstance(transcript, str):
                raise ValueError("Invalid lifecycle transcript path")
            path = sessions.native_path(transcript).resolve()
            store = sessions.native_path(record["native_root"]).resolve()
            try:
                path.relative_to(store)
            except ValueError:
                raise ValueError("Lifecycle transcript is outside this profile's native store")
            if path.exists():
                if kind == "codex":
                    first = next(sessions.read_records(path), {})
                    metadata = first.get("payload", {})
                    if sessions.is_subagent_source(metadata.get("source")):
                        return {"accepted": False, "reason": "Subagent histories are excluded"}
                    actual = metadata.get("id") or metadata.get("session_id")
                else:
                    info = sessions.claude_metadata(path, kind)
                    actual = info["session_id"] if info else None
                if actual != sid:
                    raise ValueError("Lifecycle transcript identity does not match the native session ID")
            transcript = str(path)
        prior = w.read(w.state() / "tracking" / (run_id + ".json"), {})
        event = {"schema": 1, "run_id": run_id, "kind": kind, "session_id": sid,
                 "event": "SessionStart", "source": payload["source"], "source_ref": transcript or None,
                 "revision": prior.get("revision", 0) + 1,
                 "received": datetime.now(timezone.utc).isoformat()}
        # The journal is independent of supervisor writes and contains no prompt.
        w.atomic(w.state() / "tracking" / (run_id + ".json"), event)
    return {"accepted": True, "run_id": run_id, "session_id": sid, "revision": event["revision"]}


def apply(record, state_root):
    import workflows as w
    event = w.read(state_root / "tracking" / (record["run_id"] + ".json"))
    if event:
        if event.get("schema") != 1 or event.get("run_id") != record["run_id"] or event.get("kind") != record["kind"]:
            raise ValueError("Invalid lifecycle registry")
        sid = event.get("session_id")
        if not isinstance(sid, str) or not sessions.ID_RE.fullmatch(sid):
            raise ValueError("Invalid lifecycle session identity")
        record.update(session_id=sid, binding="hook", lifecycle=event)
    return record


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--event":
            raise ValueError("Usage: tracking.py --event claude|codex")
        receive(sys.argv[2])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("cly lifecycle:", exc, file=sys.stderr)
        sys.exit(1)
