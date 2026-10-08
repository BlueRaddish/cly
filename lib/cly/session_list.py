"""Metadata-only session inventory shared by the launcher and its name lookup."""
from datetime import datetime, timezone
import argparse
import json
import os
import sys

import profiles
import sessions


def epoch(value):
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            number = int(value)
            return number // 1000 if number > 100000000000 else number
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int((stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp())
    except (ValueError, TypeError, OverflowError):
        return 0


def clean(value):
    # Native titles are untrusted terminal data. Preserve printable Unicode.
    return "".join(" " if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in str(value or ""))


def terminal_title(item):
    value = clean(item["title"])
    # Native fallback titles can contain a whole prompt (>100 KB). Bound their
    # preview before Bash sorts rows; named sessions retain their full name.
    return value if item.get("name") else value[:240]


def inventory(kind=None, profile=None):
    sources = profiles.discover()
    sources = [source for source in sources if (not kind or source["kind"] == kind)
               and (not profile or source["profile"] == profile)]
    selected, ambiguous, errors, seen = {}, set(), [], set()
    for source in sources:
        errors.extend(source.get("errors", []))
        store = source.get("store")
        identity = (source["kind"], os.path.normcase(str(sessions.native_path(store).resolve()))) if store else None
        if not store or identity in seen or source["kind"] not in sessions.KINDS:
            continue
        seen.add(identity)
        items, failures = sessions.discover(source["kind"], store, with_messages=False)
        errors.extend(failures)
        for item in items:
            key = (item["agent"], item["session_id"])
            if key in ambiguous:
                continue
            if key in selected:
                # A native ID duplicated across stores cannot safely select a
                # profile. Require the caller to choose one with cly -r NAME.
                del selected[key]
                ambiguous.add(key)
                errors.append(f"Ambiguous {key[0]}:{key[1]}; choose a profile with cly -r PROFILE")
                continue
            item = dict(item, profile=source.get("profile") or "", store=store)
            selected[key] = item
    return list(selected.values()), errors


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind")
    parser.add_argument("--profile")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    items, errors = inventory(args.kind, args.profile)
    if args.json:
        print(json.dumps({"sessions": items, "errors": errors}, ensure_ascii=False))
    else:
        for error in errors:
            print("cly: " + clean(error), file=sys.stderr)
        for item in items:
            title = json.dumps(terminal_title(item), ensure_ascii=False)[1:-1]
            fields = [epoch(item.get("_updated") or item.get("updated") or item["started"]), item["agent"],
                      item["session_id"], item["directory"], title, item["profile"], item["store"]]
            print("\x1f".join(clean(field) for field in fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
