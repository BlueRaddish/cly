"""Capture validated resume options without persisting prompts or credentials."""
from datetime import datetime
import re

import sessions

BYPASS = {"codex": "--dangerously-bypass-approvals-and-sandbox", "claude": "--dangerously-skip-permissions",
          "gemini": "--yolo", "qwen": "--yolo", "muse": "--yolo", "kimi": "--auto", "opencode": "--auto"}
VALUES = {"--model", "-m"}
CODEX_VALUES = {"--sandbox", "-s", "--ask-for-approval", "-a", "--add-dir", "--profile", "-p",
                "--enable", "--disable", "--config", "-c"}
CONFIG_KEYS = {"model", "model_reasoning_effort", "model_reasoning_summary", "service_tier", "web_search",
               "approval_policy", "sandbox_mode", "sandbox_workspace_write.network_access",
               "sandbox_workspace_write.exclude_tmpdir_env_var", "sandbox_workspace_write.exclude_slash_tmp"}
PERMISSION_FLAGS = {"--sandbox", "-s", "--ask-for-approval", "-a", "--dangerously-bypass-approvals-and-sandbox", "--yolo", "--approve-for-me"}


def option_sets(kind):
    values = VALUES | (CODEX_VALUES if kind == "codex" else {"--permission-mode", "--add-dir"} if kind == "claude" else set())
    switches = {BYPASS[kind]} if kind in BYPASS else set()
    if kind == "codex":
        switches |= {"--yolo", "--search", "--oss", "--no-alt-screen", "--no-daemon", "--approve-for-me"}
        values |= {"--local-provider"}
    elif kind == "claude":
        switches |= {"--remote-control", "--allow-dangerously-skip-permissions"}
    elif kind in {"gemini", "qwen", "muse", "kimi"}:
        switches |= {"--yolo", "-y"}
    return values, switches


def valid_value(flag, value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid saved resume option value")
    if flag in {"--sandbox", "-s"} and value not in {"read-only", "workspace-write", "danger-full-access"}:
        raise ValueError("Invalid saved sandbox mode")
    if flag in {"--ask-for-approval", "-a"} and value not in {"never", "on-request"}:
        raise ValueError("Invalid saved approval policy")
    if flag in {"--config", "-c"}:
        key, separator, content = value.partition("=")
        if not separator or key not in CONFIG_KEYS or not re.fullmatch(r'[A-Za-z0-9_.-]+|"[A-Za-z0-9_.-]+"', content):
            raise ValueError("Unsupported saved config override")
        if key == "sandbox_mode":
            valid_value("--sandbox", content.strip('"'))
        elif key == "approval_policy":
            valid_value("--ask-for-approval", content.strip('"'))
        elif key.startswith("sandbox_workspace_write.") and content not in {"true", "false"}:
            raise ValueError("Invalid saved sandbox config override")


def capture(kind, arguments):
    values, switches = option_sets(kind)
    result, omitted, permission = [], [], False
    if kind == "claude" and arguments[:2] == ["launch", "claude"]:
        # Ollama dispatch is a wrapper command, not scalar Claude options.
        # Refuse its replay until a dedicated wrapper adapter is available.
        omitted.append("--wrapper-command")
    i = 0
    while i < len(arguments):
        token = arguments[i]
        if token == "--":
            break  # Everything after the option delimiter is literal input.
        flag, equals, value = token.partition("=")
        i += 1
        if flag in values:
            if not equals:
                if i == len(arguments):
                    raise ValueError("Missing saved resume option value: " + flag)
                value = arguments[i]
                i += 1
            try:
                valid_value(flag, value)
            except ValueError:
                omitted.append(flag)
                continue
            result.extend([flag, value])
            permission |= flag in {"--sandbox", "-s", "--ask-for-approval", "-a", "--permission-mode"} or flag in {"--config", "-c"} and value.partition("=")[0] in {"approval_policy", "sandbox_mode"}
        elif token in switches:
            result.append(token)
            permission |= token in PERMISSION_FLAGS or token == BYPASS.get(kind) or token == "-y"
        elif flag in {sessions.RESUME.get(kind), "--session-id", "--resume", "-r"} or kind == "codex" and flag in {"--remote", "--remote-auth-token-env"}:
            # Session identity is stored separately. Remote connections are
            # transport, not a permission override; restore Codex locally.
            if not equals and i < len(arguments) and not arguments[i].startswith("-"):
                i += 1
        elif re.fullmatch(r"--[A-Za-z0-9][A-Za-z0-9-]*|-[A-Za-z]", flag):
            omitted.append(flag)
            if not equals and i < len(arguments) and not arguments[i].startswith("-"):
                i += 1
    return {"args": result, "omitted_flags": sorted(set(omitted)), "permissions": "launch" if permission else "unknown", "origin": "launch"}


def validate(kind, options):
    if not isinstance(options, dict) or not isinstance(options.get("args"), list) or len(options["args"]) > 256:
        raise ValueError("Invalid saved resume options")
    if not all(isinstance(arg, str) and len(arg) <= 4096 and not any(ord(c) < 32 for c in arg) for arg in options["args"]):
        raise ValueError("Invalid saved resume arguments")
    captured = capture(kind, options["args"])
    if captured["args"] != options["args"] or captured["omitted_flags"]:
        raise ValueError("Unsupported saved resume arguments")
    if not isinstance(options.get("permissions", "unknown"), str) or options.get("permissions", "unknown") not in {"unknown", "launch", "native-history"}:
        raise ValueError("Invalid saved permission source")
    if not isinstance(options.get("origin", "launch"), str) or options.get("origin", "launch") not in {"launch", "adoption", "legacy"}:
        raise ValueError("Invalid saved option origin")
    omitted = options.get("omitted_flags", [])
    if not isinstance(omitted, list) or not all(isinstance(flag, str) and re.fullmatch(r"--[A-Za-z0-9][A-Za-z0-9-]*|-[A-Za-z]", flag) for flag in omitted):
        raise ValueError("Invalid omitted resume options")
    return options


def bypass(kind, options):
    args = validate(kind, options)["args"]
    if BYPASS.get(kind) in args or "--yolo" in args or "-y" in args:
        return True
    mode = approval = None
    for i, arg in enumerate(args[:-1]):
        if arg in {"--sandbox", "-s"}:
            mode = args[i + 1]
        elif arg in {"--ask-for-approval", "-a"}:
            approval = args[i + 1]
        elif kind == "claude" and arg == "--permission-mode" and args[i + 1] == "bypassPermissions":
            return True
        elif arg in {"--config", "-c"}:
            key, _, value = args[i + 1].partition("=")
            if key == "sandbox_mode":
                mode = value.strip('"')
            elif key == "approval_policy":
                approval = value.strip('"')
    return kind == "codex" and mode == "danger-full-access" and approval == "never"


def native(record, source):
    """Refresh exact Codex history's recorded policy, never a nearby session.

    This finite O(history bytes) read also catches in-client /permissions changes
    after a turn. If histories become costly, cache a verified prefix offset.
    An idle change with no native record cannot be observed here.
    """
    if record["kind"] != "codex":
        return
    options = record.get("resume_options", {"args": [], "omitted_flags": [], "permissions": "unknown", "origin": "legacy"})
    validate("codex", options)
    latest = None
    identity = False
    for row in sessions.read_records(source):
        payload = row.get("payload", {})
        if row.get("type") in {"session_meta", "turn_context"} and not isinstance(payload, dict):
            raise ValueError("Invalid native permission record")
        if row.get("type") == "session_meta":
            if (payload.get("id") or payload.get("session_id")) != record["session_id"] or sessions.is_subagent_source(payload.get("source")):
                raise ValueError("Native permission history identity mismatch")
            identity = True
        if row.get("type") == "turn_context" and identity:
            # A pre-launch turn must not override explicitly requested options.
            if options.get("permissions") != "unknown" and record.get("started"):
                if not isinstance(row.get("timestamp"), str) or datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) < datetime.fromisoformat(record["started"].replace("Z", "+00:00")):
                    continue
            latest = payload
    if not latest:
        return
    policy, approval = latest.get("sandbox_policy", {}), latest.get("approval_policy")
    if not isinstance(policy, dict):
        raise ValueError("Invalid native sandbox policy")
    mode = policy.get("type")
    if not isinstance(mode, str) or not isinstance(approval, str) or mode not in {"read-only", "workspace-write", "danger-full-access"} or approval not in {"never", "on-request"}:
        raise ValueError("Native permission policy cannot be represented by saved resume options")
    args, i = [], 0
    while i < len(options["args"]):
        flag = options["args"][i]
        i += 1
        if flag in {"--sandbox", "-s", "--ask-for-approval", "-a", "--add-dir"}:
            i += 1
        elif flag in PERMISSION_FLAGS:
            continue
        elif flag in {"--config", "-c"} and (options["args"][i].partition("=")[0] in {"sandbox_mode", "approval_policy"} or options["args"][i].startswith("sandbox_workspace_write.")):
            i += 1
        else:
            args.append(flag)
            if flag in option_sets("codex")[0]:
                args.append(options["args"][i])
                i += 1
    args += ["--sandbox", mode, "--ask-for-approval", approval]
    if mode == "workspace-write":
        for key in ("network_access", "exclude_tmpdir_env_var", "exclude_slash_tmp"):
            value = policy.get(key, False)
            if not isinstance(value, bool):
                raise ValueError("Invalid native sandbox policy")
            args += ["--config", "sandbox_workspace_write." + key + "=" + str(value).lower()]
        roots = policy.get("writable_roots")
        if roots is None:
            profile = latest.get("permission_profile", {})
            if not isinstance(profile, dict) or not isinstance(profile.get("file_system", {}), dict):
                raise ValueError("Invalid native permission profile")
            entries = profile.get("file_system", {}).get("entries", [])
            if not isinstance(entries, list) or not all(isinstance(entry, dict) and isinstance(entry.get("path", {}), dict) and (entry.get("path", {}).get("type") != "path" or isinstance(entry["path"].get("path"), str)) for entry in entries):
                raise ValueError("Invalid native permission entries")
            roots = [entry["path"]["path"] for entry in entries if entry.get("access") == "write" and entry.get("path", {}).get("type") == "path"]
        if not isinstance(roots, list):
            raise ValueError("Invalid native writable roots")
        for root in roots:
            valid_value("--add-dir", root)
            if not any(args[n:n + 2] == ["--add-dir", root] for n in range(len(args))):
                args += ["--add-dir", root]
    updated = dict(options, args=args, permissions="native-history")
    validate("codex", updated)
    record.update(resume_options=updated, bypass=bypass("codex", updated))
