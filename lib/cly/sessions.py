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


def root(kind):
    defaults = {"claude": ("CLAUDE_CONFIG_DIR", home() / ".claude"),
                "codex": ("CODEX_HOME", home() / ".codex"),
                "gemini": ("GEMINI_CLI_HOME", home() / ".gemini"),
                "kimi": ("KIMI_CODE_HOME", home() / ".kimi-code"),
                "qwen": ("QWEN_HOME", home() / ".qwen"),
                "muse": ("CLY_MUSE_HOME", Path(os.environ.get("XDG_DATA_HOME", home() / ".local/share")) / "muse"),
                "opencode": ("CLY_OPENCODE_HOME", Path(os.environ.get("XDG_DATA_HOME", home() / ".local/share")) / "opencode")}
    variable, default = defaults[kind]
    return native_path(os.environ.get(variable, default))


def read_records(path):
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
                    break
                raise ValueError(f"Malformed JSON at {path}:{number}")
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{number}")
            yield value


def text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict)
                     and b.get("type") in {"text", "Text", "input_text", "output_text"})


def prose(role, content):
    value = text(content).strip()
    if role not in {"user", "assistant"} or not value or value.startswith(INJECTED):
        return None
    return {"role": role, "content": value}


def session(kind, sid, cwd, started, path, messages=None, title=""):
    if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
        raise ValueError("Invalid native session ID in " + str(path))
    started = started or datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()
    if isinstance(started, (int, float)):
        started = datetime.fromtimestamp(started / (1000 if started > 10**11 else 1), timezone.utc).isoformat()
    datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    return {"agent": kind, "session_id": sid, "directory": str(cwd or ""),
            "started": str(started), "source": str(path), "title": title or f"{kind}:{sid}",
            "messages": messages or []}


def claude_codex(path, kind):
    sid = cwd = started = current_turn = ""
    messages, representations, seen, paired = [], [], {}, set()
    unmatched = {"response": defaultdict(deque), "event": defaultdict(deque)}
    for row in read_records(path):
        representation, turn = "response", ""
        if kind == "claude" or kind == "qwen":
            sid = sid or row.get("sessionId", "")
            cwd = cwd or row.get("cwd", "")
            started = started or row.get("timestamp", "")
            if row.get("isMeta") or row.get("isSidechain"):
                continue
            message = row.get("message", {})
        else:
            payload = row.get("payload", {})
            if row.get("type") == "session_meta":
                if not sid:
                    source = payload.get("source")
                    if isinstance(source, str) and source.startswith("subagent") or isinstance(source, dict) and "subagent" in source:
                        return None
                    sid = payload.get("id") or payload.get("session_id", "")
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
                if message.get("channel") in {"analysis", "summary"} or message.get("phase") in {"analysis", "summary"}:
                    continue
            elif row.get("type") == "event_msg" and payload.get("type") == "item_completed":
                item = payload.get("item", {})
                if item.get("type") not in {"UserMessage", "AgentMessage"}:
                    continue
                if item.get("type") == "AgentMessage" and item.get("phase") not in {"commentary", "final_answer"}:
                    continue
                message = dict(item, role="user" if item["type"] == "UserMessage" else "assistant")
                representation, turn = "event", payload.get("turn_id", "")
            else:
                continue
        normalized = prose(message.get("role"), message.get("content"))
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
        raise ValueError("No session identity in " + str(path))
    return session(kind, sid, cwd, started, path, messages)


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


def muse_session(path):
    sid = Path(path).parent.name
    cwd = started = title = ""
    messages = []
    for outer in read_records(path):
        rows = [json.loads(c["record_json"]) for c in outer.get("children", [])] if outer.get("retained_frame") else [outer]
        for row in rows:
            payload = row.get("payload", {})
            if row.get("recorded_at") and not started:
                started = datetime.fromtimestamp(row["recorded_at"] / 1_000_000, timezone.utc).isoformat()
            if row.get("payload_type") == "runtime.session.metadata":
                cwd = payload.get("record", {}).get("workspace_root", cwd)
            if row.get("payload_type") in {"runtime.session.name_changed", "runtime.session.title_changed"}:
                title = payload.get("name") or payload.get("title") or title
            if row.get("record_type") == "message":
                msg = payload.get("message", payload)
                normalized = prose(msg.get("role"), msg.get("content"))
                if normalized:
                    messages.append(normalized)
    return session("muse", sid, cwd, started, path, messages, title)


def gemini_session(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    project = Path(path).parent.parent
    project_root = project / ".project_root"
    cwd = project_root.read_text(encoding="utf-8").strip() if project_root.exists() else data.get("cwd", "")
    messages = []
    for item in data.get("messages", []):
        role = {"gemini": "assistant", "user": "user", "assistant": "assistant"}.get(item.get("type") or item.get("role"))
        if normalized := prose(role, item.get("content")):
            messages.append(normalized)
    return session("gemini", data.get("sessionId") or data.get("id"), cwd, data.get("startTime"), path, messages, data.get("summary", ""))


def kimi_session(path, with_messages=True):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    directory = Path(path).parent
    context = directory / "context.jsonl"
    wire = directory / "agents/main/wire.jsonl"
    messages = []
    if not with_messages:
        pass
    elif context.exists():
        for row in read_records(context):
            if normalized := prose(row.get("role"), row.get("content")):
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
    return session("kimi", data.get("sessionId") or data.get("id") or directory.name,
                   cwd, data.get("createdAt") or data.get("created_at"), path, messages, data.get("title", ""))


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
    codex_metadata = {}
    if kind == "codex" and not with_messages:
        databases = sorted(store.glob("state_*.sqlite"), key=lambda p: int(p.stem.split("_")[-1]), reverse=True)
        if databases:
            try:
                with closing(sqlite3.connect(databases[0].as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
                    db.row_factory = sqlite3.Row
                    for row in db.execute("select id,cwd,created_at,title,rollout_path,source from threads"):
                        if str(row["source"]).startswith("subagent") or not Path(row["rollout_path"]).exists():
                            continue
                        codex_metadata[row["id"]] = session(kind, row["id"], row["cwd"], datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat(), row["rollout_path"], title=row["title"])
                return list(codex_metadata.values()), errors
            except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
                pass  # Older Codex versions persist only rollout metadata.
    for path in paths:
        try:
            if kind == "codex" and not with_messages:
                with path.open(encoding="utf-8") as stream:
                    row = json.loads(stream.readline())
                payload = row.get("payload", {})
                source = payload.get("source")
                if isinstance(source, dict) and "subagent" in source or isinstance(source, str) and source.startswith("subagent"):
                    continue
                item = session(kind, payload.get("id") or payload.get("session_id"), payload.get("cwd"), payload.get("timestamp"), path)
            elif kind in {"claude", "qwen"} and not with_messages:
                item = claude_metadata(path, kind)
            else:
                parser = {"claude": lambda p: claude_codex(p, kind), "codex": lambda p: claude_codex(p, kind),
                          "qwen": lambda p: claude_codex(p, kind), "gemini": gemini_session,
                          "kimi": lambda p: kimi_session(p, with_messages), "muse": muse_session}[kind]
                item = parser(path)
            if item:
                if not with_messages:
                    item["messages"] = []
                result.append(item)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"{kind}: {path}: {exc}")
    unique = {}
    for item in result:
        key = item["session_id"]
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
