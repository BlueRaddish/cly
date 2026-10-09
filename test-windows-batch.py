#!/usr/bin/env python3
"""Run python test-windows-batch.py; disposable hidden Windows batch files only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if os.name != "nt":
    print("Windows batch checks skipped on this platform")
    raise SystemExit(0)

ROOT = Path(__file__).resolve().parent
BASH = os.environ.get("CLY_SHELL", r"C:\Program Files\Git\bin\bash.exe")
checks = 0


def check(value, message=""):
    global checks
    assert value, message
    checks += 1


with tempfile.TemporaryDirectory(prefix="cly-batch-") as temporary:
    temp = Path(temporary)
    folder = temp / "batch space's & %CLY_BATCH_PATH_TEST% ! [literal] \u6c49 folder"
    folder.mkdir()
    receipt = temp / "receipt.json"
    marker = temp / "must-not-exist.txt"
    reader = temp / "receipt.py"
    reader.write_text("import json, os, sys\nfrom pathlib import Path\nPath(os.environ['CLY_BATCH_RECEIPT']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\nprint('BATCH_OUT')\nprint('BATCH_ERR', file=sys.stderr)\n", encoding="utf-8")
    values = ["simple", "space argument", "amp&literal", 'quote"literal', "%PATH%",
              "bang!literal", "caret^literal", "", 'space " & %PATH% ! ^ end',
              "C:\\trailing\\", 'a\\\\\\"b', '\u6c49\U0001f642',
              '" & echo injected > "' + str(marker) + '" & rem "']
    base = dict(os.environ, CLY_BATCH_RECEIPT=str(receipt), CLY_BATCH_PATH_TEST="must-not-expand",
                CLY_TEST_SCRIPT=str(ROOT / "bin/cly").replace("\\", "/"),
                CLY_TEST_PATH="", MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*", CLY_TRACK="0",
                CLY_CONFIG=str(temp / "config"), CLY_STATE_HOME=str(temp / "state"),
                CODEX_HOME=str(temp / "codex"))
    for name in list(base):
        if name.startswith("CLY_BATCH_ARG_"):
            del base[name]

    def run(arguments, environment=None, input_text=None):
        env = dict(base, **(environment or {}), CLY_TEST_COUNT=str(len(arguments)))
        for index, argument in enumerate(arguments):
            env["CLY_TEST_ARG_" + str(index)] = argument
        # Inject already-parsed Bash argv as data. Native Python's Windows
        # list2cmdline cannot represent every literal quote for MSYS Bash.
        source = ('export PATH="$CLY_TEST_PATH:$PATH"; '
                  'if [ -n "${CLY_TEST_MISSING_TOOL:-}" ]; then command() { if [ "$1" = -v ] && [ "$2" = "$CLY_TEST_MISSING_TOOL" ]; then return 1; fi; builtin command "$@"; }; fi; '
                  'if [ "${CLY_TEST_FAIL_ENCODER:-0}" = 1 ]; then iconv() { return 73; }; fi; '
                  'case ${CLY_TEST_REQUIRE_X:-} in yes) test -x "$CLY_TEST_FILE" && command -v executable.cmd >/dev/null || exit 71 ;; no) test -r "$CLY_TEST_FILE" && ! test -x "$CLY_TEST_FILE" || exit 72 ;; esac; '
                  'arguments=(); for ((i=0; i<CLY_TEST_COUNT; i++)); do name=CLY_TEST_ARG_$i; arguments+=("${!name}"); done; . "$CLY_TEST_SCRIPT" "${arguments[@]}"')
        return subprocess.run([BASH, "-c", source], env=env, capture_output=True, input=input_text,
                              text=True, encoding="utf-8", errors="replace",
                              creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)

    def launched(arguments, environment=None):
        receipt.unlink(missing_ok=True)
        result = run(arguments, environment)
        check(result.returncode == 0, result.stderr)
        check(receipt.exists() and json.loads(receipt.read_text()) == values)
        check(not marker.exists())
        check("BATCH_OUT" in result.stdout and "BATCH_ERR" in result.stderr)

    for extension in ("cmd", "bat"):
        batch = folder / ("probe_" + extension + "." + extension)
        batch.write_text('@echo off\r\n"' + sys.executable + '" "' + str(reader) + '" %*\r\nexit /b %errorlevel%\r\n', encoding="utf-8")
        posix_batch = "/" + str(batch)[0].lower() + str(batch)[2:].replace("\\", "/")
        launched(["--cly-exec-agent", str(batch), *values], {"CLY_TEST_REQUIRE_X": "no", "CLY_TEST_FILE": posix_batch})
        config = temp / "config"
        config.write_text("profile.probe.bin=" + str(batch).replace("\\", "/") + "\nprofile.probe.kind=codex\nprofile.probe.dir=none\nprofile.probe.flags=\n", encoding="utf-8")
        query = run(["--here", "probe", "resume", "fixture-id"], {"CLY_WORKFLOW_QUERY": "1"})
        check(query.returncode == 0 and query.stdout.split("\0")[0] == "codex")
        launched(["--here", "probe", *values])
        config.write_text("profile.probe.bin=" + batch.stem + "\nprofile.probe.kind=codex\nprofile.probe.dir=none\nprofile.probe.flags=\n", encoding="utf-8")
        posix_folder = "/" + str(folder)[0].lower() + str(folder)[2:].replace("\\", "/")
        launched(["--here", "probe", *values], {"CLY_TEST_PATH": posix_folder})
        query = run(["--here", "probe"], {"CLY_TEST_PATH": posix_folder, "CLY_WORKFLOW_QUERY": "1"})
        check(query.returncode == 0 and batch.name in query.stdout)

    config.write_text("profile.probe.bin=" + str(batch).replace("\\", "/") + "\nprofile.probe.kind=muse\nprofile.probe.dir=none\nprofile.probe.flags=\n", encoding="utf-8")
    receipt.unlink(missing_ok=True)
    admin = run(["--here", "probe", "login", *values])
    check(admin.returncode == 0 and json.loads(receipt.read_text()) == ["login", *values])
    check(not marker.exists())

    # An initial shebang gives this synthetic batch Bash's executable status.
    # CMD reports that first line as an unknown command, then runs the real
    # batch body; its final status and literal argv must still be correct.
    executable_batch = folder / "executable.cmd"
    executable_batch.write_text("#!/bin/false\r\n" + batch.read_text(), encoding="utf-8")
    config.write_text("profile.probe.bin=executable.cmd\nprofile.probe.kind=codex\nprofile.probe.dir=none\nprofile.probe.flags=\n", encoding="utf-8")
    posix_executable_batch = posix_folder + "/" + executable_batch.name
    query = run(["--here", "probe"], {"CLY_TEST_PATH": posix_folder, "CLY_WORKFLOW_QUERY": "1",
                                        "CLY_TEST_REQUIRE_X": "yes", "CLY_TEST_FILE": posix_executable_batch})
    check(query.returncode == 0 and str(executable_batch).replace("\\", "/")[2:] in query.stdout)
    launched(["--here", "probe", *values], {"CLY_TEST_PATH": posix_folder})

    # Headless review jobs must retain piped prompt text through the batch bridge.
    reader.write_text("import json, os, sys\nfrom pathlib import Path\nPath(os.environ['CLY_BATCH_RECEIPT']).write_text(json.dumps(sys.stdin.read()), encoding='utf-8')\n", encoding="utf-8")
    receipt.unlink(missing_ok=True)
    prompt = 'first line\nsecond line " & %PATH% !\n'
    piped = run(["--cly-exec-agent", str(batch)], input_text=prompt)
    check(piped.returncode == 0, piped.stderr)
    check(receipt.exists() and json.loads(receipt.read_text()) == prompt)

    for invalid, error in (("line\nbreak", "line breaks"), ("x" * 8100, "length limit")):
        receipt.unlink(missing_ok=True)
        result = run(["--cly-exec-agent", str(batch), invalid])
        check(result.returncode != 0 and error in result.stderr)
        check(not receipt.exists() and not marker.exists())

    for tool in ("powershell.exe", "cygpath", "iconv", "base64"):
        receipt.unlink(missing_ok=True)
        result = run(["--cly-exec-agent", str(batch), "safe"], {"CLY_TEST_MISSING_TOOL": tool})
        check(result.returncode != 0 and "requires " + tool in result.stderr)
        check(not receipt.exists())
    result = run(["--cly-exec-agent", str(batch), "safe"], {"CLY_TEST_FAIL_ENCODER": "1"})
    check(result.returncode == 73 and not receipt.exists())

print(str(checks) + " Windows batch checks passed (real CMD/BAT, literal argv, no agents or GUI)")
