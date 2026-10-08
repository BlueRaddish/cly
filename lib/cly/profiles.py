"""Discover configured stores without executing profiles or copying secrets."""
import os
import re

import sessions

STORE_VARIABLES = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME",
                   "gemini": "GEMINI_CLI_HOME", "kimi": "KIMI_CODE_HOME",
                   "qwen": "QWEN_HOME", "muse": "CLY_MUSE_HOME",
                   "opencode": "CLY_OPENCODE_HOME", "antigrav": "ANTIGRAVITY_APP_DATA_DIR",
                   "agy": "ANTIGRAVITY_APP_DATA_DIR"}


def capabilities(kind):
    native = kind in sessions.KINDS
    return {"capture": "partial" if kind in {"kimi", "qwen"} else "unsupported" if kind == "muse" or not native else "native",
            "resume": "native" if native else "unsupported",
            "export": "normalized" if native and kind != "muse" else "manual",
            "tracking": "hooks" if kind in {"claude", "codex"} else "manual"}


def configured():
    path = sessions.native_path(os.environ.get("CLY_CONFIG", sessions.home() / ".config/cly/config"))
    values, legacy = {}, False
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        if line.startswith("#"):
            continue
        if line.startswith(("dir=", "flags=")):
            legacy = True
        match = re.fullmatch(r"profile\.([A-Za-z0-9_-]+)\.([^=]+)=(.*)", line)
        if match:
            name, key, value = match.groups()
            # Launch flags, API endpoints and credentials never enter discovery.
            if key in {"bin", "kind", "env"}:
                values.setdefault(name, {})[key] = value
            else:
                values.setdefault(name, {})
    if legacy:
        values.setdefault("claude", {"bin": "claude"})
    return values


def discover(kinds=None, configured_only=False):
    """List all profiles, plus unconfigured native kinds when requested.

    Profile env is cly's whitespace-separated NAME=VALUE format, not shell code.
    Only store-path values are retained; no executable or credential is exposed.
    """
    values = configured()
    entries = []
    present = set()
    for name, value in values.items():
        executable = re.split(r"[/\\]", value.get("bin") or name)[-1]
        kind = value.get("kind") or re.sub(r"\.(exe|cmd)$", "", executable, flags=re.I)
        if kinds is not None and kind not in kinds:
            continue
        present.add(kind)
        errors, paths = [], dict(os.environ)
        for entry in value.get("env", "").split():
            variable, separator, content = entry.partition("=")
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
                errors.append(name + ": invalid profile environment entry")
                continue
            if variable not in set(STORE_VARIABLES.values()) | {"XDG_DATA_HOME", "JETSKI_APP_DATA_DIR"}:
                continue
            match = re.match(r"^\$([A-Za-z_][A-Za-z0-9_]*)", content)
            if match:
                # Match cly_exec's indirect prefix expansion (suffix is dropped).
                content = os.environ.get(match.group(1), "")
            paths[variable] = content
        store = str(sessions.root(kind, paths)) if kind in sessions.KINDS else paths.get(STORE_VARIABLES.get(kind, "")) or None
        candidates = []
        if kind in {"antigrav", "agy", "antigravity"} and not store:
            store = paths.get("JETSKI_APP_DATA_DIR") or None
        if kind in {"antigrav", "agy", "antigravity"} and not store:
            # Observed local directories are discovery candidates; their native
            # protobuf histories still require export until a reader is verified.
            candidates = [str(sessions.home() / ".gemini" / name) for name in
                          ("antigravity-cli", "antigravity", "antigravity-ide")
                          if (sessions.home() / ".gemini" / name / "conversations").is_dir()]
            cli_store = sessions.home() / ".gemini/antigravity-cli"
            # The installed agy CLI logs this app-data path in common.go:178.
            # IDE directories remain candidates, never silently substituted.
            store = str(cli_store) if (cli_store / "conversations").is_dir() else None
        if kind not in sessions.KINDS:
            errors.append(name + ": native store format unsupported; normalized export/import required")
        entries.append({"profile": name, "kind": kind, "store": store,
                        "store_exists": bool(store and sessions.native_path(store).exists()),
                        "capabilities": capabilities(kind), "errors": errors, "configured": True,
                        "store_candidates": candidates})
    if not configured_only:
        for kind in kinds if kinds is not None else sessions.KINDS:
            if kind not in present:
                store = sessions.root(kind)
                entries.append({"profile": kind, "kind": kind, "store": str(store),
                                "store_exists": store.exists(), "capabilities": capabilities(kind),
                                "errors": [], "configured": False})
    return entries
