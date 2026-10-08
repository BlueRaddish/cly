"""Read provider stores as data; normalize only user/assistant prose.

The Claude/Codex representation pairing follows the user's existing PARA
collector. No provider config, credentials, reasoning, or tool output is copied.
"""
from collections import defaultdict, deque
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

KINDS = ("claude", "codex", "gemini", "kimi", "muse", "qwen", "opencode")
RESUME = {"claude": "--resume", "codex": "resume", "gemini": "--resume",
          "kimi": "--session", "muse": "resume", "qwen": "--resume",
          "opencode": "--session", "antigrav": "--conversation", "agy": "--conversation"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
INJECTED = ("<environment_context>", "<system-reminder>", "<permissions instructions>",
            "# AGENTS.md instructions", "<turn_aborted>", "Caveat: The messages below",
            "<local-command-", "<command-name>")


def home():
    return Path(os.environ.get("USERPROFILE") or Path.home())


def native_path(value):
    value = str(value).removeprefix("\\\\?\\")
    if os.name == "nt" and re.match(r"^/[a-zA-Z]/", value):
        value = value[1] + ":" + value[2:]
    return Path(value).expanduser()


def root(kind, environment=None):
    environment = os.environ if environment is None else environment
    defaults = {"claude": ("CLAUDE_CONFIG_DIR", home() / ".claude"),
                "codex": ("CODEX_HOME", home() / ".codex"),
                "gemini": ("GEMINI_CLI_HOME", home() / ".gemini"),
                "kimi": ("KIMI_CODE_HOME", home() / ".kimi-code"),
                "qwen": ("QWEN_HOME", home() / ".qwen"),
                "muse": ("CLY_MUSE_HOME", Path(environment.get("XDG_DATA_HOME", home() / ".local/share")) / "muse"),
                "opencode": ("CLY_OPENCODE_HOME", Path(environment.get("XDG_DATA_HOME", home() / ".local/share")) / "opencode")}
    variable, default = defaults[kind]
    return native_path(environment.get(variable) or default)


def is_subagent_source(source):
    """Codex stores source as an enum object in rollouts and JSON in SQLite."""
    if isinstance(source, str):
        if source.startswith("subagent"):
            return True
        try:
            source = json.loads(source)
        except ValueError:
            return False
    return isinstance(source, dict) and "subagent" in source


def read_records(path, status=None):
    """Take a finite file prefix; retry incomplete final writes next capture."""
    with Path(path).open("rb") as stream:
        remaining = os.fstat(stream.fileno()).st_size
        number = 0
        while remaining:
            line = stream.readline(remaining)
            if not line:
                break
            remaining -= len(line)
            number += 1
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                if not remaining and not line.endswith(b"\n"):
                    if status is not None:
                        status["incomplete"] = True
                    break
                raise ValueError(f"Malformed JSON at {path}:{number}")
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{number}")
            yield value


def text(content):
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        raise ValueError("Unsupported conversation content shape")
    parts = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("Unsupported conversation content block")
        kind = block.get("type")
        if kind in {"text", "Text", "input_text", "output_text"}:
            if not isinstance(block.get("text"), str):
                raise ValueError("Conversation text block needs string text")
            parts.append(block["text"])
        elif kind not in {"thinking", "redacted_thinking", "reasoning", "reasoning_text", "summary_text", "tool_use", "tool_result",
                          "server_tool_use", "web_search_tool_result", "web_fetch_tool_result",
                          "mcp_tool_use", "mcp_tool_result", "image", "Image", "LocalImage", "image_url", "input_image",
                          "output_image", "document", "file", "input_file", "audio", "input_audio", "output_audio"}:
            raise ValueError("Unsupported conversation content block: " + str(kind))
    return "\n".join(parts)


def prose(role, content):
    if role not in {"user", "assistant"}:
        return None
    value = text(content).strip()
    if not value or value.startswith(INJECTED):
        return None
    return {"role": role, "content": value}


def message_prose(message):
    """Unknown prose fields fail explicitly; metadata-only messages stay empty."""
    if message.get("role") not in {"user", "assistant"}:
        return None
    if "content" not in message or message["content"] in (None, "", []):
        metadata = {"role", "id", "uuid", "type", "timestamp", "channel", "phase", "turn_id",
                    "internal_chat_message_metadata_passthrough", "model", "usage", "stop_reason",
                    "stop_sequence", "index", "status", "metadata", "content", "thoughts", "thinking",
                    "reasoning", "reasoning_content", "tool_calls", "function_call", "name"}
        fields = [key for key, value in message.items() if key not in metadata and value not in (None, "", [], {})]
        if fields:
            raise ValueError("Unsupported conversation content fields: " + ", ".join(fields))
    return prose(message["role"], message.get("content"))


def public_assistant(message):
    # New channels/phases may contain reasoning. Accept known public values and
    # legacy records without those fields; unknown values must never become prose.
    public = {None, "", "commentary", "final", "final_answer"}
    return message.get("role") != "assistant" or message.get("channel") in public and message.get("phase") in public


def session(kind, sid, cwd, started, path, messages=None, title=""):
    if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
        raise ValueError("Invalid native session ID in " + str(path))
    explicit_started = bool(started)
    started = started or datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()
    if isinstance(started, (int, float)):
        started = datetime.fromtimestamp(started / (1000 if started > 10**11 else 1), timezone.utc).isoformat()
    datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    return {"agent": kind, "session_id": sid, "directory": str(cwd or ""),
            "started": str(started), "source": str(path), "title": title or f"{kind}:{sid}",
            "messages": messages or [], "_started_explicit": explicit_started}


def claude_codex(path, kind):
    sid = cwd = started = current_turn = ""
    messages, representations, seen, paired = [], [], {}, set()
    status, sidechain = {}, False
    unmatched = {"response": defaultdict(deque), "event": defaultdict(deque)}
    for row in read_records(path, status):
        representation, turn = "response", ""
        if kind == "claude" or kind == "qwen":
            if row.get("isSidechain"):
                sidechain = True
                continue
            candidate = row.get("sessionId", "")
            if candidate and sid and candidate != sid:
                raise ValueError("Conflicting native session identities in " + str(path))
            sid = sid or candidate
            cwd = cwd or row.get("cwd", "")
            started = started or row.get("timestamp", "")
            if row.get("isMeta"):
                continue
            message = row.get("message", {})
            if not message and row.get("role") in {"user", "assistant"}:
                raise ValueError("Unsupported conversation record in " + str(path))
        else:
            payload = row.get("payload", {})
            if row.get("type") == "session_meta":
                candidate = payload.get("id") or payload.get("session_id", "")
                if candidate and sid and candidate != sid:
                    raise ValueError("Conflicting native session identities in " + str(path))
                if not sid:
                    source = payload.get("source")
                    if is_subagent_source(source):
                        return None
                    sid = candidate
                    cwd = payload.get("cwd", "")
                    started = payload.get("timestamp") or row.get("timestamp", "")
                continue
            if row.get("type") == "event_msg" and payload.get("type") == "task_started":
                current_turn = payload.get("turn_id", "")
                continue
            if row.get("type") == "event_msg" and payload.get("type") == "task_complete":
                current_turn = ""
                continue
            if row.get("type") == "response_item" and payload.get("type") == "message":
                message = payload
                turn = (message.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id") or current_turn
                if not public_assistant(message):
                    continue
            elif row.get("type") == "event_msg" and payload.get("type") == "item_completed":
                item = payload.get("item", {})
                if item.get("type") not in {"UserMessage", "AgentMessage"}:
                    if item.get("role") in {"user", "assistant"}:
                        raise ValueError("Unsupported conversation item: " + str(item.get("type")))
                    continue
                message = dict(item, role="user" if item["type"] == "UserMessage" else "assistant")
                if not public_assistant(message):
                    continue
                representation, turn = "event", payload.get("turn_id", "")
            else:
                non_prose = {"reasoning", "function_call", "function_call_output", "custom_tool_call",
                             "custom_tool_call_output", "web_search_call", "computer_call", "computer_call_output"}
                if row.get("type") != "turn_context" and payload.get("type") not in non_prose and payload.get("role") in {"user", "assistant"}:
                    raise ValueError("Unsupported conversation record: " + str(row.get("type")))
                continue
        normalized = message_prose(message)
        if not normalized:
            continue
        ident = row.get("uuid") or message.get("id")
        identity = (normalized["role"], ident) if ident else None
        if identity and identity in seen:
            index = seen[identity]
            if representation == "event":
                messages[index] = normalized
            if representations[index] != representation:
                paired.add(index)
            continue
        key = (turn, normalized["content"]) if kind == "codex" and turn and normalized["role"] == "user" else None
        if key:
            other = "event" if representation == "response" else "response"
            pending = unmatched[other][key]
            while pending and pending[0] in paired:
                pending.popleft()
            if pending:
                index = pending.popleft()
                paired.add(index)
                if identity:
                    seen[identity] = index
                if representation == "event":
                    messages[index] = normalized
                continue
        index = len(messages)
        if identity:
            seen[identity] = index
        messages.append(normalized)
        representations.append(representation)
        if key:
            unmatched[representation][key].append(index)
    if not sid:
        if sidechain:
            return None
        raise ValueError("No session identity in " + str(path))
    item = session(kind, sid, cwd, started, path, messages)
    if status.get("incomplete"):
        item["_incomplete"] = True
    return item


def claude_metadata(path, kind):
    sid = cwd = started = ""
    for row in read_records(path):
        if row.get("isSidechain"):
            return None
        sid = sid or row.get("sessionId", "")
        cwd = cwd or row.get("cwd", "")
        started = started or row.get("timestamp", "")
        if sid and cwd:
            break
    if not sid:
        raise ValueError("No session identity in " + str(path))
    return session(kind, sid, cwd, started, path)


def muse_session(path, with_messages=True):
    sid = Path(path).parent.name
    cwd = started = title = ""
    messages = []
    status = {}
    for outer in read_records(path, status):
        rows = [json.loads(c["record_json"]) for c in outer.get("children", [])] if outer.get("retained_frame") else [outer]
        for row in rows:
            payload = row.get("payload", {})
            if row.get("recorded_at") and not started:
                started = datetime.fromtimestamp(row["recorded_at"] / 1_000_000, timezone.utc).isoformat()
            if row.get("payload_type") == "runtime.session.metadata":
                cwd = payload.get("record", {}).get("workspace_root", cwd)
            if row.get("payload_type") in {"runtime.session.name_changed", "runtime.session.title_changed"}:
                title = payload.get("name") or payload.get("title") or title
            if with_messages and row.get("record_type") == "message":
                msg = payload.get("message", payload)
                normalized = message_prose(msg)
                if normalized:
                    messages.append(normalized)
            if not with_messages and cwd:
                break
        if not with_messages and cwd:
            break
    item = session("muse", sid, cwd, started, path, messages, title)
    if status.get("incomplete"):
        item["_incomplete"] = True
    return item


def gemini_session(path, with_messages=True):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    project = Path(path).parent.parent
    project_root = project / ".project_root"
    cwd = project_root.read_text(encoding="utf-8").strip() if project_root.exists() else data.get("cwd", "")
    messages = []
    for item in data.get("messages", []) if with_messages else []:
        role = {"gemini": "assistant", "user": "user", "assistant": "assistant"}.get(item.get("type") or item.get("role"))
        if normalized := message_prose(dict(item, role=role)):
            messages.append(normalized)
    return session("gemini", data.get("sessionId") or data.get("id"), cwd, data.get("startTime"), path, messages, data.get("summary", ""))


def kimi_session(path, with_messages=True):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    directory = Path(path).parent
    context = directory / "context.jsonl"
    wire = directory / "agents/main/wire.jsonl"
    messages = []
    status = {}
    if not with_messages:
        pass
    elif context.exists():
        for row in read_records(context, status):
            if normalized := message_prose(row):
                messages.append(normalized)
    elif wire.exists():
        raise ValueError("Kimi wire-only format needs a normalized export; use document import")
    cwd = data.get("workDir") or data.get("cwd")
    # Newer Kimi stores cwd in the top-level session index.
    index = directory.parents[1] / "session_index.jsonl"
    if not cwd and index.exists():
        for entry in read_records(index):
            if entry.get("session_id") == directory.name or entry.get("sessionId") == directory.name:
                cwd = entry.get("work_dir") or entry.get("workDir")
    item = session("kimi", data.get("sessionId") or data.get("id") or directory.name,
                   cwd, data.get("createdAt") or data.get("created_at"), path, messages, data.get("title", ""))
    if status.get("incomplete"):
        item["_incomplete"] = True
    return item


def opencode_sessions(store, with_messages):
    database = store / "opencode.db"
    if not database.exists():
        return []
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        result = []
        for info in db.execute("select id,directory,title,time_created from session where parent_id is null"):
            messages = []
            if with_messages:
                for message in db.execute("select id,data from message where session_id=? order by time_created,id", (info["id"],)):
                    body = json.loads(message["data"])
                    if body.get("role") not in {"user", "assistant"}:
                        continue
                    parts = [json.loads(p[0]) for p in db.execute("select data from part where message_id=? order by time_created,id", (message["id"],))]
                    parts = [p for p in parts if p.get("type") == "text" and not p.get("synthetic") and not p.get("ignored")]
                    if normalized := prose(body["role"], parts):
                        messages.append(normalized)
            started = datetime.fromtimestamp(info["time_created"] / 1000, timezone.utc).isoformat()
            result.append(session("opencode", info["id"], info["directory"], started, database, messages, info["title"]))
        return result


def muse_metadata(store):
    database = store / "session-index.db"
    if not database.exists():
        return []
    result = []
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute("pragma table_info(sessions)")}
        required = {"session_id", "session_log_path", "workspace_root", "title", "created_at_us", "updated_at_us"}
        if not required.issubset(columns):
            return []
        selected = [name for name in (*sorted(required), "session_name", "msp_parent_session_id") if name in columns]
        for row in db.execute("select " + ",".join(selected) + " from sessions"):
            info = dict(row)
            if info.get("msp_parent_session_id"):
                continue
            path = native_path(info["session_log_path"])
            if not path.exists():
                continue
            item = session("muse", info["session_id"], info["workspace_root"],
                           info["created_at_us"] / 1_000_000 if info["created_at_us"] else "", path,
                           title=info.get("session_name") or info["title"])
            item["name"] = info.get("session_name") or ""
            if info["updated_at_us"]:
                item["_updated"] = info["updated_at_us"] / 1_000_000
            result.append(item)
    return result


def codex_metadata(store):
    """Read the newest schema's public metadata; older stores use rollouts."""
    databases = sorted((p for p in store.glob("state_*.sqlite") if p.stem.split("_")[-1].isdigit()),
                       key=lambda p: int(p.stem.split("_")[-1]), reverse=True)
    result = {}
    if not databases:
        return result
    with closing(sqlite3.connect(databases[0].as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute("pragma table_info(threads)")}
        wanted = [name for name in ("id", "cwd", "created_at", "created_at_ms", "updated_at", "updated_at_ms", "title", "name", "rollout_path", "source") if name in columns]
        if not {"id", "cwd", "created_at", "title", "rollout_path", "source"}.issubset(columns):
            return result
        for row in db.execute("select " + ",".join(wanted) + " from threads"):
            info = dict(row)
            if is_subagent_source(info["source"]):
                result[info["id"]] = None
                continue
            path = native_path(info["rollout_path"]) if info["rollout_path"] else None
            if not path or not path.exists():
                continue
            item = session("codex", info["id"], info["cwd"], info.get("created_at_ms") or info["created_at"], path,
                           title=info.get("name") or info["title"])
            item["name"] = info.get("name") or ""
            stamp = info.get("updated_at_ms") or info.get("updated_at") or info.get("created_at_ms") or info["created_at"]
            item["_updated"] = stamp / 1000 if stamp > 10**11 else stamp
            result[info["id"]] = item
    return result


def codex_names(store):
    result = {}
    index = store / "session_index.jsonl"
    if index.exists():
        for row in read_records(index):
            sid = row.get("id") or row.get("session_id")
            if isinstance(sid, str) and ID_RE.fullmatch(sid) and isinstance(row.get("thread_name"), str):
                result[sid] = row
    return result


def prompt_history(store, kind):
    result = {}
    history = store / "history.jsonl"
    if not history.exists():
        return result
    for row in read_records(history):
        sid = row.get("session_id") if kind == "codex" else row.get("sessionId")
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
            continue
        info = result.setdefault(sid, {})
        value = row.get("text") if kind == "codex" else row.get("display")
        if isinstance(value, str) and value and not value.startswith(INJECTED):
            if not info.get("title") or info["title"].startswith("/") and not value.startswith("/"):
                info["title"] = value[:120]
        stamp = row.get("ts") if kind == "codex" else row.get("timestamp")
        if isinstance(stamp, (int, float)):
            info["_updated"] = max(info.get("_updated", 0), stamp / 1000 if stamp > 10**11 else stamp)
    return result


def claude_title(item, history):
    info = history.get(item["session_id"], {})
    if info.get("title"):
        item["title"] = info["title"]
    if info.get("_updated"):
        item["_updated"] = info["_updated"]
    path = Path(item["source"]).with_suffix("") / "custom-title.json"
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8-sig")).get("customTitle")
        if not isinstance(value, str):
            raise ValueError("Invalid native custom title: " + str(path))
        if value:
            item["name"] = item["title"] = value


def discover(kind, store=None, with_messages=True):
    store = native_path(store) if store else root(kind)
    result, errors = [], []
    if not store.exists():
        return result, errors
    if kind == "opencode":
        try:
            return opencode_sessions(store, with_messages), errors
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError) as exc:
            return [], [f"opencode: {exc}"]
    patterns = {"claude": ["projects/*/*.jsonl"], "codex": ["sessions/*/*/*/rollout-*.jsonl", "archived_sessions/rollout-*.jsonl"],
                "gemini": ["tmp/*/chats/session-*.json"], "kimi": ["sessions/*/*/state.json"],
                "muse": ["sessions/*/*/*/*/session.jsonl"], "qwen": ["projects/*/chats/*.jsonl", "projects/*/*.jsonl"]}
    paths = sorted({p for pattern in patterns[kind] for p in store.glob(pattern)})
    # Codex uses indexed metadata; Claude/Qwen stop at an identifying prefix.
    # Other providers currently scan files; large stores can use native indexes.
    metadata, names, history = {}, {}, {}
    if kind == "muse" and not with_messages:
        try:
            result = muse_metadata(store)
            indexed = {os.path.normcase(str(native_path(item["source"]).resolve())) for item in result}
            paths = [path for path in paths if os.path.normcase(str(path.resolve())) not in indexed]
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError) as exc:
            errors.append(f"muse: session metadata index: {exc}")
    if kind in {"claude", "qwen", "codex"}:
        try:
            history = prompt_history(store, kind)
        except (OSError, ValueError) as exc:
            errors.append(f"{kind}: prompt history: {exc}")
    if kind == "codex":
        try:
            metadata = codex_metadata(store)
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            pass  # Older Codex versions persist only rollout metadata.
        try:
            names = codex_names(store)
        except (OSError, ValueError) as exc:
            errors.append(f"codex: session name index: {exc}")
        if not with_messages:
            result.extend(item for item in metadata.values() if item)
    for path in paths:
        try:
            if kind == "codex" and not with_messages:
                with path.open(encoding="utf-8") as stream:
                    row = json.loads(stream.readline())
                payload = row.get("payload", {})
                source = payload.get("source")
                if is_subagent_source(source):
                    continue
                if (payload.get("id") or payload.get("session_id")) in metadata:
                    continue
                item = session(kind, payload.get("id") or payload.get("session_id"), payload.get("cwd"), payload.get("timestamp"), path)
            elif kind in {"claude", "qwen"} and not with_messages:
                item = claude_metadata(path, kind)
            else:
                parser = {"claude": lambda p: claude_codex(p, kind), "codex": lambda p: claude_codex(p, kind),
                          "qwen": lambda p: claude_codex(p, kind), "gemini": lambda p: gemini_session(p, with_messages),
                          "kimi": lambda p: kimi_session(p, with_messages), "muse": lambda p: muse_session(p, with_messages)}[kind]
                item = parser(path)
            if item:
                if kind in {"claude", "qwen"}:
                    claude_title(item, history)
                if kind == "codex" and item["session_id"] in metadata:
                    info = metadata[item["session_id"]]
                    if info is None:
                        continue
                    for key in ("title", "name", "_updated"):
                        item[key] = info[key]
                if not with_messages:
                    item["messages"] = []
                result.append(item)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"{kind}: {path}: {exc}")
    for item in result:
        if "_updated" not in item:
            try:
                item["_updated"] = Path(item["source"]).stat().st_mtime
            except OSError as exc:
                errors.append(f"{kind}: {item['source']}: {exc}")
                item["_updated"] = datetime.fromisoformat(item["started"].replace("Z", "+00:00")).timestamp()
        if kind == "codex":
            name = names.get(item["session_id"], {})
            if not item.get("name") and name.get("thread_name"):
                item["name"] = item["title"] = name["thread_name"]
            prompt = history.get(item["session_id"], {})
            if item["title"] == "codex:" + item["session_id"] and prompt.get("title"):
                item["title"] = prompt["title"]
            if prompt.get("_updated"):
                item["_updated"] = max(item["_updated"], prompt["_updated"])
            if name.get("updated_at"):
                try:
                    item["_updated"] = max(item["_updated"], datetime.fromisoformat(name["updated_at"].replace("Z", "+00:00")).timestamp())
                except (ValueError, TypeError):
                    errors.append("codex: invalid name-index timestamp for " + item["session_id"])
    unique, ambiguous = {}, set()
    for item in result:
        key = item["session_id"]
        if key in ambiguous:
            continue
        previous = unique.get(key)
        if previous:
            directories = [os.path.normcase(str(native_path(entry["directory"]))) if entry["directory"] else "" for entry in (previous, item)]
            different_directory = all(directories) and directories[0] != directories[1]
            different_start = (previous.get("_started_explicit") and item.get("_started_explicit")
                               and datetime.fromisoformat(previous["started"].replace("Z", "+00:00"))
                               != datetime.fromisoformat(item["started"].replace("Z", "+00:00")))
            size = min(len(previous["messages"]), len(item["messages"]))
            different_prose = previous["messages"][:size] != item["messages"][:size]
            if different_directory or different_start or different_prose:
                errors.append(f"{kind}: conflicting duplicate native session ID {key}: {previous['source']} and {item['source']}")
                ambiguous.add(key)
                del unique[key]
                continue
        if key not in unique or len(item["messages"]) > len(unique[key]["messages"]):
            unique[key] = item
    return list(unique.values()), errors


def revision(item):
    return hashlib.sha256(json.dumps({k: item[k] for k in ("agent", "session_id", "directory", "started", "title", "messages")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def markdown(item):
    date = item["started"]
    header = {"type": "session", "agent": item["agent"], "session-id": item["session_id"],
              "date": date, "directory": item["directory"], "title": item["title"]}
    lines = ["---"] + [key + ": " + json.dumps(value, ensure_ascii=False) for key, value in header.items()] + ["---", "", "# " + item["title"], "", "Raw conversation capture; prose claims are not execution evidence.", ""]
    for message in item["messages"]:
        lines += ["## " + message["role"].title(), "", message["content"], ""]
    return "\n".join(lines).replace("\r\n", "\n") + "\n"
