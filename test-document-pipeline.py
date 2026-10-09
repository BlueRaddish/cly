#!/usr/bin/env python3
"""Isolated cly document CLI integration checks; no models, Drive or live writes.

Run: python test-document-pipeline.py from a checkout, or pass --repo CHECKOUT.
Uses the real Bash launcher, native readers and filing/publication code. A local
fake writer copies and compares bytes without contacting a remote. Optionally
pass --validator-root DIRECTORY containing an installed paralib.py to check its
real rules. Use --results REPORT.json to retain command output and check names;
the final line prints check and CLI-command counts. Standard library only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NOTES = Path(__file__).resolve().parent
DEFAULT_REPO = NOTES
OPTIONS = argparse.ArgumentParser(description=__doc__)
OPTIONS.add_argument("--repo", type=Path, default=DEFAULT_REPO)
OPTIONS.add_argument("--bash", default=os.environ.get("CLY_SHELL") or (str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe") if os.name == "nt" else shutil.which("bash")))
OPTIONS.add_argument("--validator-root", type=Path, help="Optional directory containing installed paralib.py; real rules stay outside cly")
OPTIONS.add_argument("--results", type=Path, help="Optional JSON command/check report")
ARGS = OPTIONS.parse_args()
REPO = ARGS.repo.resolve()
BASH = Path(ARGS.bash)
CHECKS = []
COMMANDS = []
ISSUES = []

FAKE_HELPER = r'''import json, os, pathlib, sys
rules = os.environ.get("TEST_RULES")
if rules:
    sys.path.insert(0, rules)
    import paralib
    paralib.VAULT = os.environ["TEST_VAULT"]
root = pathlib.Path(os.environ["TEST_REMOTE"])
control_path = pathlib.Path(os.environ["TEST_CONTROL"])
control = json.loads(control_path.read_text(encoding="utf-8"))
args = sys.argv[1:]
if args[0] == "--capabilities":
    with open(os.environ["TEST_CAP_LOG"], "a", encoding="utf-8") as stream:
        stream.write("capability probe\n")
    if not control.get("legacy") and (rules or control.get("advertise_prepare")):
        print("prepare-v1")
        sys.exit(0)
    sys.exit(2)
if args[0] == "--prepare":
    source, destination, output = pathlib.Path(args[1]), args[2], pathlib.Path(args[3])
    with open(os.environ["TEST_LOG"], "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"check": False, "prepare": True, "destination": destination}, ensure_ascii=False) + "\n")
    if control.get("prepare_fail") == destination:
        print("injected preparation error", file=sys.stderr)
        sys.exit(11)
    content = source.read_text(encoding="utf-8")
    if rules and paralib.is_note(destination):
        errors, fixes, content = paralib.validate(destination, content)
        if errors:
            print("validator: " + "; ".join(errors), file=sys.stderr)
            sys.exit(1)
    if control.get("prepare_raw_marker") and destination.startswith("2-Areas/memory/sessions/"):
        content += "\nPrepared raw publication marker.\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content.encode("utf-8"))
    sys.exit(0)
checking = args[0] == "--check"
destination, source = (args[1], pathlib.Path(args[2])) if checking else (args[1], pathlib.Path(args[0]))
target = root / destination
with open(os.environ["TEST_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"check": checking, "destination": destination}, ensure_ascii=False) + "\n")
if checking:
    if control.get("check_fail") == destination:
        print("injected verification outage", file=sys.stderr)
        sys.exit(9)
    if not target.is_file() or target.read_bytes() != source.read_bytes():
        print("byte comparison failed", file=sys.stderr)
        sys.exit(1)
    print("match: " + destination)
    sys.exit(0)
if control.get("write_fail") == destination:
    print("injected upload error", file=sys.stderr)
    sys.exit(7)
content = source.read_text(encoding="utf-8")
if rules and paralib.is_note(destination):
    errors, fixes, corrected = paralib.validate(destination, content)
    if errors:
        print("validator: " + "; ".join(errors), file=sys.stderr)
        sys.exit(1)
    content = corrected
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(content.encode("utf-8"))
if control.get("mirror_mount", True):
    mounted = pathlib.Path(os.environ["TEST_VAULT"]) / destination
    mounted.parent.mkdir(parents=True, exist_ok=True)
    mounted.write_bytes(target.read_bytes())
if control.get("after_write_fail") == destination:
    print("uploaded, but simulated confirmation failed", file=sys.stderr)
    sys.exit(8)
print("wrote and locally verified: " + destination)
'''


def check(value, name):
    assert value, name
    CHECKS.append(name)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def command(env, *args, expected=0):
    argv = [str(BASH), str(REPO / "bin/cly").replace("\\", "/"), "document", *map(str, args)]
    result = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    COMMANDS.append({"argv": ["cly", "document", *map(str, args)], "exit": result.returncode,
                     "stdout": result.stdout, "stderr": result.stderr})
    if expected is not None:
        check(result.returncode == expected, "CLI exit: " + " ".join(map(str, args)) + " => " + str(expected))
    return result


def note(title="Document pipeline test", note_type="inbox"):
    return "---\ntype: " + note_type + "\ndate: 2026-10-08\n---\n\n# " + title + "\n\nConfirmed from an isolated fixture; this is not a production finding.\n"


def index(env):
    return json.loads((Path(env["CLY_LIBRARY_HOME"]) / "index.json").read_text(encoding="utf-8"))


def make_plan(env, destination, content=None, sources=None):
    current = index(env)
    selected = sources or list(current["sessions"].values())
    return {"schema": 1, "source_revisions": {key: record["revision"] for key, record in current["sessions"].items()},
            "notes": [{"path": destination, "content": content or note(),
                       "sources": [{"agent": record["agent"], "session_id": record["session_id"]} for record in selected]}]}


def run():
    with tempfile.TemporaryDirectory(prefix="cly pipeline ") as directory:
        temp = Path(directory) / "Unicode 폴더 café"
        temp.mkdir()
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", CLY_TRACK="0",
                   CLY_STATE_HOME=str(temp / "state"), CLY_LIBRARY_HOME=str(temp / "library"),
                   CLY_CONFIG=str(temp / "config with spaces"), CLY_SHELL=str(BASH),
                   CLY_PYTHON=sys.executable.replace("\\", "/"),
                   CLAUDE_CONFIG_DIR=str(temp / "Claude source"), CODEX_HOME=str(temp / "Codex source"),
                   GEMINI_CLI_HOME=str(temp / "Gemini absent"), KIMI_CODE_HOME=str(temp / "Kimi absent"),
                   CLY_MUSE_HOME=str(temp / "Muse absent"), QWEN_HOME=str(temp / "Qwen absent"),
                   CLY_OPENCODE_HOME=str(temp / "OpenCode absent"),
                   MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*",
                   TEST_VAULT=str(temp / "local vault"), TEST_REMOTE=str(temp / "local remote"),
                   TEST_CONTROL=str(temp / "writer control.json"), TEST_LOG=str(temp / "writer log.jsonl"),
                   TEST_CAP_LOG=str(temp / "writer capability log.txt"))
        if ARGS.validator_root:
            env["TEST_RULES"] = str(ARGS.validator_root.resolve())
        else:
            env.pop("TEST_RULES", None)
        Path(env["CLY_CONFIG"]).write_text("version=2\n", encoding="utf-8")
        vault = Path(env["TEST_VAULT"])
        vault.mkdir()
        control = Path(env["TEST_CONTROL"])
        write_json(control, {})
        helper = temp / "fake writer helper.py"
        helper.write_text(FAKE_HELPER, encoding="utf-8")
        writer = temp / "local para writer"
        # The wrapper only execs a native Python child; its hidden Bash parent is
        # launched via cly's CREATE_NO_WINDOW path. The helper launches no child.
        import shlex
        writer.write_text("#!/usr/bin/env bash\nexec " + shlex.quote(sys.executable.replace("\\", "/")) + " " +
                          shlex.quote(str(helper).replace("\\", "/")) + ' "$@"\n', encoding="utf-8")
        filing = ["--para-write", str(writer), "--vault-root", str(vault)]
        claude = Path(env["CLAUDE_CONFIG_DIR"]) / "projects/project space/source.jsonl"
        codex = Path(env["CODEX_HOME"]) / "sessions/2026/10/08/rollout-source.jsonl"
        jsonl(claude, [
            {"sessionId": "same-native-id", "cwd": str(temp), "timestamp": "2026-10-08T12:00:00Z", "uuid": "c-u", "message": {"role": "user", "content": "Keep Unicode café and 한글."}},
            {"sessionId": "same-native-id", "uuid": "c-a", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "PRIVATE_REASONING"}, {"type": "text", "text": "Confirmed CLI pipeline fixture."}]}},
            {"sessionId": "same-native-id", "uuid": "c-t", "message": {"role": "user", "content": [{"type": "tool_result", "content": "SECRET_TOOL_OUTPUT"}]}},
            {"sessionId": "same-native-id", "message": {"role": "user", "content": "# AGENTS.md instructions\nINJECTED"}},
        ])
        jsonl(codex, [
            {"type": "session_meta", "payload": {"id": "same-native-id", "cwd": str(temp), "timestamp": "2026-10-08T12:01:00Z"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Use the shared library."}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": "Use verified writes."}},
        ])
        # Full actual cly launch, not a direct function call.
        command(env, "capture", "--agent", "claude", "--agent", "codex")
        current = index(env)
        check(len(current["sessions"]) == 2, "same native ID in different providers stays separate")
        check(all(record["agent"] in {"claude", "codex"} for record in current["sessions"].values()), "source provider recorded")
        combined = "\n".join(path.read_text(encoding="utf-8") for path in (Path(env["CLY_LIBRARY_HOME"]) / "sessions").glob("*/*.md"))
        check("한글" in combined and "café" in combined, "Unicode normalized prose survives real CLI")
        check(not any(marker in combined for marker in ("PRIVATE_REASONING", "SECRET_TOOL_OUTPUT", "INJECTED")), "reasoning, tools and injected instructions excluded")
        result = command(env, "capture", "--agent", "claude", "--agent", "codex")
        check("0 new/revised" in result.stdout, "unchanged capture is idempotent")
        command(env, "catch-up", "--agent", "claude")
        packet = (Path(env["CLY_LIBRARY_HOME"]) / "catch-up.md").read_text(encoding="utf-8")
        check("claude:same-native-id" in packet and "codex:same-native-id" in packet, "single refresh provider packet includes all already captured pending providers")
        check(all("reviewed_revision" not in record and "filed_revision" not in record for record in index(env)["sessions"].values()), "packet-only catch-up advances no semantic receipts")
        check(not (Path(env["CLY_LIBRARY_HOME"]) / "reviews").exists(), "packet-only catch-up calls no model")
        command(env, "capture", "--agent", "gemini")
        coverage = index(env)["providers"]["gemini"]
        check({key: coverage[key] for key in ("store_exists", "sessions_found", "prose_sessions")} ==
              {"store_exists": False, "sessions_found": 0, "prose_sessions": 0}, "missing provider store has explicit coverage")
        check(coverage["capabilities"]["capture"] == "native" and coverage["profiles"], "provider coverage includes discovery capabilities and stores")
        broken = claude.with_name("bad.jsonl")
        broken.write_text("{bad json}\n", encoding="utf-8")
        result = command(env, "catch-up", "--agent", "claude", expected=1)
        check("Malformed JSON" in result.stderr and "pending sessions" in result.stdout, "malformed source reports incomplete coverage while retaining packet")
        check(len(index(env)["sessions"]) == 2, "malformed neighbor does not delete healthy memories")
        broken.unlink()
        with claude.open("ab") as stream:
            stream.write(b'{"unfinished":')
        command(env, "capture", "--agent", "claude")
        check(not index(env)["errors"], "incomplete final native write is safely deferred")
        # Restore valid source and test empty file separately.
        claude.write_bytes(claude.read_bytes().split(b'{"unfinished":')[0])
        broken.write_text("", encoding="utf-8")
        result = command(env, "capture", "--agent", "claude", expected=1)
        check("No session identity" in result.stderr, "empty source surfaces missing identity")
        broken.unlink()
        command(env, "capture", "--agent", "claude")

        plan_path = temp / "reviewed plan.json"
        plan = make_plan(env, "0-Inbox/Unicode café 한글.md")
        write_json(plan_path, plan)
        # An unavailable mount must not be treated as an empty vault. Reject
        # before probing or invoking the writer and preserve every receipt.
        missing_root = temp / "missing vault"
        file_root = temp / "vault is a file"
        file_root.write_text("not a vault", encoding="utf-8")
        for invalid_root in (missing_root, file_root):
            for action in ("file", "publish"):
                before_index = (Path(env["CLY_LIBRARY_HOME"]) / "index.json").read_bytes()
                before_receipts = {str(path): path.read_bytes() for path in (Path(env["CLY_LIBRARY_HOME"]) / "filings").glob("*.json")}
                before_calls = {name: Path(env[name]).read_bytes() if Path(env[name]).exists() else b""
                                for name in ("TEST_LOG", "TEST_CAP_LOG")}
                arguments = [action, plan_path] if action == "file" else [action]
                command(env, *arguments, "--para-write", writer, "--vault-root", invalid_root, expected=1)
                check(before_calls == {name: Path(env[name]).read_bytes() if Path(env[name]).exists() else b""
                                       for name in before_calls}, "invalid vault root invokes no writer or capability call: " + action)
                check(before_index == (Path(env["CLY_LIBRARY_HOME"]) / "index.json").read_bytes()
                      and before_receipts == {str(path): path.read_bytes() for path in (Path(env["CLY_LIBRARY_HOME"]) / "filings").glob("*.json")},
                      "invalid vault root preserves filing/publication receipts: " + action)
        command(env, "file", plan_path, *filing)
        target = vault / plan["notes"][0]["path"]
        check(target.is_file() and "Sources:" in target.read_text(encoding="utf-8"), "curated filing creates validated Unicode destination with source citations")
        check(all(record.get("filed_revision") == record["revision"] for record in index(env)["sessions"].values()), "filed receipts advance after all destinations verify")
        before = target.read_bytes()
        command(env, "file", plan_path, *filing)
        check(target.read_bytes() == before, "same plan retry only rechecks prior verified note")
        target.write_bytes(before + b"\nHuman correction preserved.\n")
        (Path(env["TEST_REMOTE"]) / plan["notes"][0]["path"]).write_bytes(target.read_bytes())
        result = command(env, "file", plan_path, *filing, expected=1)
        check("preserved for review" in result.stderr and target.read_bytes().endswith(b"Human correction preserved.\n"), "retry protects changed existing destination")
        target.write_bytes(before)
        (Path(env["TEST_REMOTE"]) / plan["notes"][0]["path"]).write_bytes(before)
        other = make_plan(env, plan["notes"][0]["path"], note("Different plan"))
        write_json(plan_path, other)
        result = command(env, "file", plan_path, *filing, expected=1)
        check("Existing note preserved" in result.stderr and target.read_bytes() == before, "new plan cannot overwrite an existing curated note")

        for destination in ("0-Inbox/../escape.md", "/0-Inbox/absolute.md", "C:/escape.md", "0-Inbox\\bad.md", "0-Inbox/README.md", "0-Inbox//empty.md"):
            write_json(plan_path, make_plan(env, destination))
            command(env, "file", plan_path, *filing, expected=1)
        write_json(plan_path, make_plan(env, "0-Inbox/case.md"))
        duplicate = json.loads(plan_path.read_text(encoding="utf-8"))
        duplicate["notes"].append(dict(duplicate["notes"][0], path="0-Inbox/CASE.md"))
        write_json(plan_path, duplicate)
        command(env, "file", plan_path, *filing, expected=1)

        # Changed native prose invalidates a reviewed plan without losing prior
        # publication/filing receipts; new revision returns to pending queues.
        stale = make_plan(env, "0-Inbox/stale.md")
        with codex.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": "A revised fixture finding."}}) + "\n")
        command(env, "capture", "--agent", "codex")
        write_json(plan_path, stale)
        command(env, "file", plan_path, *filing, expected=1)
        check(not (vault / "0-Inbox/stale.md").exists(), "revised source rejects stale plan before writer")

        partial = make_plan(env, "0-Inbox/partial-one.md")
        partial["notes"].append(dict(partial["notes"][0], path="0-Inbox/partial-two.md"))
        write_json(plan_path, partial)
        write_json(control, {"after_write_fail": "0-Inbox/partial-two.md"})
        command(env, "file", plan_path, *filing, expected=1)
        check((vault / "0-Inbox/partial-one.md").exists() and (vault / "0-Inbox/partial-two.md").exists(), "partial upload failure simulates note reaching destination")
        check(any(record.get("filed_revision") != record["revision"] for record in index(env)["sessions"].values()), "partial failure leaves source revisions pending")
        digest = hashlib.sha256(json.dumps(partial, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        stage_folder = Path(env["CLY_LIBRARY_HOME"]) / "filings" / digest
        saved_stages = {path.name: path.read_bytes() for path in stage_folder.glob("*.md")}
        receipt_path = stage_folder.with_suffix(".json")
        prior_hashes = {path: record["sha256"] for path, record in json.loads(receipt_path.read_text(encoding="utf-8"))["destinations"].items()}
        command(env, "publish", *filing)
        check(all(record.get("vault_path") for record in index(env)["sessions"].values()), "legitimate raw publication adds source links after interrupted curated filing")
        log_before = len(Path(env["TEST_LOG"]).read_text(encoding="utf-8").splitlines())
        write_json(control, {})
        command(env, "file", plan_path, *filing)
        events = [json.loads(line) for line in Path(env["TEST_LOG"]).read_text(encoding="utf-8").splitlines()[log_before:]]
        check(all(event["check"] for event in events), "retry verifies already uploaded partial notes without overwriting")
        check(saved_stages == {path.name: path.read_bytes() for path in stage_folder.glob("*.md")}, "same-plan retry preserves staged bytes despite newly published source links")
        check(prior_hashes == {path: record["sha256"] for path, record in json.loads(receipt_path.read_text(encoding="utf-8"))["destinations"].items()}, "same-plan retry preserves content hashes after source vault_path changes")

        outage = make_plan(env, "0-Inbox/verification-outage.md")
        write_json(plan_path, outage)
        write_json(control, {"check_fail": "0-Inbox/verification-outage.md"})
        command(env, "file", plan_path, *filing, expected=1)
        write_json(control, {})
        command(env, "file", plan_path, *filing)
        check((vault / "0-Inbox/verification-outage.md").exists(), "verification outage is resumable")
        failed = make_plan(env, "0-Inbox/nonzero-write.md")
        write_json(plan_path, failed)
        write_json(control, {"write_fail": "0-Inbox/nonzero-write.md"})
        command(env, "file", plan_path, *filing, expected=1)
        check(not (vault / "0-Inbox/nonzero-write.md").exists(), "nonzero writer prevents success without destination")
        write_json(control, {})
        logs = Path(env["TEST_LOG"]).read_bytes()
        command(env, "file", plan_path, *filing, expected=1)
        events = [json.loads(line) for line in Path(env["TEST_LOG"]).read_bytes()[len(logs):].decode("utf-8").splitlines()]
        check(events and all(event["check"] for event in events), "uncertain nonzero write retry rechecks without blindly creating a missing remote note")
        # The writer's check result cannot distinguish missing/changed/offline.
        # Simulate a manual recovery after inspection, using the exact preserved
        # bytes. cly can then finish by verification alone, without a second write.
        digest = hashlib.sha256(json.dumps(failed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        staged = Path(env["CLY_LIBRARY_HOME"]) / "filings" / digest / "0.md"
        remote_recovery = Path(env["TEST_REMOTE"]) / "0-Inbox/nonzero-write.md"
        remote_recovery.parent.mkdir(parents=True, exist_ok=True)
        remote_recovery.write_bytes(staged.read_bytes())
        command(env, "file", plan_path, *filing)

        # Advertised preparation must fail closed before upload; legacy writers
        # continue using their original staged artifact without the protocol.
        preparation = make_plan(env, "0-Inbox/preparation-error.md")
        write_json(plan_path, preparation)
        write_json(control, {"advertise_prepare": True, "prepare_fail": "0-Inbox/preparation-error.md"})
        logs = Path(env["TEST_LOG"]).read_bytes()
        command(env, "file", plan_path, *filing, expected=1)
        events = [json.loads(line) for line in Path(env["TEST_LOG"]).read_bytes()[len(logs):].decode("utf-8").splitlines()]
        check(events and all(event.get("prepare") for event in events), "advertised preparation failure makes no upload or verification call")
        check(not (Path(env["TEST_REMOTE"]) / "0-Inbox/preparation-error.md").exists(), "preparation failure creates no remote note")
        write_json(control, {"legacy": True})
        legacy = make_plan(env, "0-Inbox/legacy-writer.md")
        write_json(plan_path, legacy)
        command(env, "file", plan_path, *filing)
        check((vault / "0-Inbox/legacy-writer.md").exists(), "writer without preparation capability remains supported")
        write_json(control, {})

        # Real validator normalization happens before artifact hashing/staging;
        # the corrected staged artifact is the exact upload and receipt source.
        with codex.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Type-correction pending revision fixture."}}) + "\n")
        command(env, "capture", "--agent", "codex")
        if ARGS.validator_root:
            wrong_type = make_plan(env, "0-Inbox/type-correction.md", note(note_type="area"))
            write_json(plan_path, wrong_type)
            result = command(env, "file", plan_path, *filing)
            check("type: inbox" in (vault / "0-Inbox/type-correction.md").read_text(encoding="utf-8"), "real validator corrects uploaded type")
            check(all(record.get("filed_revision") == record["revision"] for record in index(env)["sessions"].values()), "prepared corrected filing advances verified receipts")
            digest = hashlib.sha256(json.dumps(wrong_type, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            staged = Path(env["CLY_LIBRARY_HOME"]) / "filings" / digest / "0.md"
            remote = Path(env["TEST_REMOTE"]) / "0-Inbox/type-correction.md"
            check(staged.read_bytes() == remote.read_bytes(), "corrected prepared staging exactly matches remote bytes")
            receipt = json.loads((Path(env["CLY_LIBRARY_HOME"]) / "filings" / (digest + ".json")).read_text(encoding="utf-8"))
            check(receipt["destinations"]["0-Inbox/type-correction.md"]["sha256"] == hashlib.sha256(staged.read_bytes()).hexdigest(), "receipt hashes corrected prepared artifact")

        write_json(control, {"advertise_prepare": True, "prepare_raw_marker": True})
        command(env, "publish", *filing)
        write_json(control, {})
        current = index(env)
        check(all(record.get("published_revision") == record["revision"] for record in current["sessions"].values()), "raw publication advances only verified revisions")
        codex_key, codex_record = next((key, record) for key, record in current["sessions"].items() if record["agent"] == "codex")
        raw_target = vault / codex_record["vault_path"]
        publication_receipt = Path(env["CLY_LIBRARY_HOME"]) / codex_record["publication_receipt"]
        receipt = json.loads(publication_receipt.read_text(encoding="utf-8"))
        artifact = Path(env["CLY_LIBRARY_HOME"]) / "publish/revisions" / (publication_receipt.stem + ".md")
        raw_remote = Path(env["TEST_REMOTE"]) / codex_record["vault_path"]
        legacy_stage = Path(env["CLY_LIBRARY_HOME"]) / "publish" / (codex_key + ".md")
        check(b"Prepared raw publication marker." in artifact.read_bytes(), "raw publisher uses prepared revision bytes")
        check(receipt["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest(), "raw publication receipt hashes prepared artifact")
        check(artifact.read_bytes() == raw_remote.read_bytes() == legacy_stage.read_bytes(), "prepared raw revision, remote and legacy stage bytes match")
        check(receipt["status"] == "verified" and receipt["revision"] == codex_record["revision"], "prepared raw receipt records verified current revision")
        original = raw_target.read_text(encoding="utf-8")
        original = original.replace("---\n\n#", "project: cly\nmetadata:\n  nested: preserved\n---\n\n#", 1)
        original += "\n- [[1-Projects/cly/README|cly project]]\n"
        raw_target.write_bytes(original.encode("utf-8"))
        remote_raw = Path(env["TEST_REMOTE"]) / codex_record["vault_path"]
        remote_raw.write_bytes(raw_target.read_bytes())
        with codex.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Another new captured message."}}) + "\n")
        command(env, "capture", "--agent", "codex")
        command(env, "publish", *filing)
        # Remote association changed while the mounted copy still carries the
        # previous association. Refuse recapture before any upload.
        stale_mounted = raw_target.read_bytes()
        remote_raw.write_bytes(stale_mounted.replace(b"project: cly", b"project: current-remote"))
        with codex.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Stale mounted metadata fixture."}}) + "\n")
        command(env, "capture", "--agent", "codex")
        logs = Path(env["TEST_LOG"]).read_bytes()
        command(env, "publish", *filing, expected=1)
        events = [json.loads(line) for line in Path(env["TEST_LOG"]).read_bytes()[len(logs):].decode("utf-8").splitlines()]
        check(events and all(event["check"] for event in events), "stale mounted raw metadata is refused before any upload")
        check(b"project: current-remote" in remote_raw.read_bytes(), "raw publication preserves newer remote association")
        raw_target.write_bytes(remote_raw.read_bytes())
        command(env, "publish", *filing)
        published = raw_target.read_text(encoding="utf-8")
        check("project: current-remote\nmetadata:\n  nested: preserved" in published and "[[1-Projects/cly/README|cly project]]" in published, "raw recapture preserves complete frontmatter and curated project links")
        check("Another new captured message." in published, "raw recapture updates transcript body")
        # A malformed existing raw note must also survive a revised capture.
        raw_target.write_text("Existing prose without frontmatter must survive.\n", encoding="utf-8")
        remote_raw.write_bytes(raw_target.read_bytes())
        with codex.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": "Malformed existing raw note fixture."}}) + "\n")
        command(env, "capture", "--agent", "codex")
        command(env, "publish", *filing, expected=1)
        check(raw_target.read_text(encoding="utf-8") == "Existing prose without frontmatter must survive.\n", "raw publication preserves malformed existing note for manual review")
        check(index(env)["sessions"][codex_key]["published_revision"] != index(env)["sessions"][codex_key]["revision"], "failed raw publication keeps current revision pending")
        raw_target.write_bytes(published.encode("utf-8"))
        remote_raw.write_bytes(raw_target.read_bytes())
        command(env, "publish", *filing)
        bad_export = temp / "bad-export.json"
        write_json(bad_export, {"agent": "codex", "session_id": "../../bad", "started": "2026-10-08", "directory": "", "title": "bad", "messages": []})
        command(env, "import", bad_export, expected=1)
        write_json(bad_export, {"agent": "other-provider", "session_id": "exported-id", "started": "2026-10-08T00:00:00Z", "directory": str(temp), "title": "Normalized import", "messages": [{"role": "user", "content": "Imported prose"}], "api_key": "NO_COPY"})
        command(env, "import", bad_export)
        imported = next(record for record in index(env)["sessions"].values() if record["agent"] == "other-provider")
        check(imported["session_id"] == "exported-id", "unsupported provider normalized import accepted")
        exports = list((Path(env["CLY_LIBRARY_HOME"]) / "sessions/other-provider").glob("*.json"))
        check("NO_COPY" not in exports[0].read_text(encoding="utf-8"), "extra export secrets removed")
        command(env, "status")
        check(not (Path(env["CLY_STATE_HOME"]) / "document-watch.json").exists(), "test starts no collector or background worker")

        # A remote write can succeed while both confirmation and mount visibility
        # fail. A later remote edit must survive retries regardless of mount age.
        uncertain = make_plan(env, "0-Inbox/uncertain-remote.md")
        write_json(plan_path, uncertain)
        write_json(control, {"after_write_fail": "0-Inbox/uncertain-remote.md", "mirror_mount": False})
        command(env, "file", plan_path, *filing, expected=1)
        remote = Path(env["TEST_REMOTE"]) / "0-Inbox/uncertain-remote.md"
        remote.write_text("Human changed the remote note.\n", encoding="utf-8")
        check(not (vault / "0-Inbox/uncertain-remote.md").exists(), "uncertain upload test mount remains missing")
        write_json(control, {"mirror_mount": False})
        result = command(env, "file", plan_path, *filing, expected=None)
        check(result.returncode != 0 and remote.read_text(encoding="utf-8") == "Human changed the remote note.\n",
                   "uncertain upload retry must preserve changed remote note even when mounted target is missing")
        write_json(control, {})

        # Shrinking a live file to a prefix ending in a torn JSON record must
        # never replace the previously captured full conversation with a prefix.
        full = codex.read_bytes()
        codex_json = Path(env["CLY_LIBRARY_HOME"]) / "sessions" / (codex_key + ".json")
        saved = codex_json.read_bytes()
        prefix = b"\n".join(full.splitlines()[:2]) + b'\n{"unfinished":'
        codex.write_bytes(prefix)
        command(env, "capture", "--agent", "codex", expected=None)
        check(codex_json.read_bytes() == saved, "torn shortened native source must retain last full normalized conversation")
        codex.write_bytes(full.splitlines()[0] + b'\n{"unfinished":')
        result = command(env, "capture", "--agent", "codex", expected=1)
        check(codex_json.read_bytes() == saved, "torn rewrite with zero prose retains prior full normalized conversation")
        codex.write_bytes(full)
        command(env, "capture", "--agent", "codex")
        with codex.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "private_unknown_channel", "content": "PRIVATE_UNRECOGNIZED_CHANNEL"}}) + "\n")
        command(env, "capture", "--agent", "codex")
        check("PRIVATE_UNRECOGNIZED_CHANNEL" not in codex_json.read_text(encoding="utf-8"), "unrecognized private Codex channel must not enter prose library")

        # Windows treats case-only folders as aliases. Accept either canonical
        # agent identity or a rejected import; never two index entries pointing
        # at one overwritten normalized session file.
        before = codex_json.read_bytes()
        alias = json.loads(before)
        alias["agent"] = "Codex"
        alias["messages"] = [{"role": "user", "content": "CASE_ALIAS_PAYLOAD"}]
        write_json(bad_export, alias)
        result = command(env, "import", bad_export, expected=None)
        records = [record for record in index(env)["sessions"].values()
                   if record["agent"].casefold() == "codex" and record["session_id"] == alias["session_id"]]
        check(len(records) == 1 and (result.returncode == 0 or codex_json.read_bytes() == before),
                   "case-only agent import must canonicalize or reject without duplicated Windows aliases")
        # Restore native source before testing corruption of an otherwise current
        # normalized record. The source revision in the index must remain proof
        # of the actual packet data, not merely a stale cache entry.
        command(env, "capture", "--agent", "codex")
        stale = make_plan(env, "0-Inbox/normalized-index-mismatch.md")
        modified = json.loads(codex_json.read_text(encoding="utf-8"))
        modified["messages"].append({"role": "assistant", "content": "CORRUPTED_NORMALIZED_DATA"})
        write_json(codex_json, modified)
        write_json(plan_path, stale)
        logs = Path(env["TEST_LOG"]).read_bytes()
        result = command(env, "file", plan_path, *filing, expected=None)
        check(result.returncode != 0 and not (vault / "0-Inbox/normalized-index-mismatch.md").exists()
                   and Path(env["TEST_LOG"]).read_bytes() == logs,
                   "normalized JSON/index revision mismatch must reject filing before any writer call")


if __name__ == "__main__":
    try:
        run()
    finally:
        if ARGS.results:
            write_json(ARGS.results, {"checks": len(CHECKS), "passed": CHECKS, "issues": ISSUES, "commands": COMMANDS,
                "scope": "isolated actual cly CLI, local fake writer; optional real PARA validator; no live models or Drive"})
    print(str(len(CHECKS)) + " integration checks passed; " + str(len(COMMANDS)) + " actual CLI commands; " + str(len(ISSUES)) + " recorded findings")
