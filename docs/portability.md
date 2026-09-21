# Cross-platform reliability review

Reviewed 2026-09-21. These are proposed follow-up changes, not implemented fixes.
The current implementation was inspected on macOS; Windows and Linux need native runs.

## 1. Make installation select a working Bash

`bin/cly` requires Bash 4.2+, but `install.sh` does not validate the interpreter
and writes a launcher using `/usr/bin/env bash`. On this Mac, installing with
`/bin/bash` and a system-only PATH succeeds, but the installed `cly --version`
exits 2 because macOS Bash is 3.2. This was reproduced with a temporary HOME and prefix.

Detect and validate Bash before changing files. Honor `CLY_BASH` on Unix as well
as Windows; check PATH, Homebrew (both architectures), and MacPorts locations.
Pin the validated interpreter in the generated launcher. If none works, report
platform-specific installation instructions and stop before claiming success.
Keep uninstall available without the newer Bash.

Acceptance: clean macOS with only system Bash fails installation clearly; a
Homebrew or MacPorts Bash works even if later shells put system Bash first.
Linux and Windows should exercise the same minimum-version contract.

## 2. Quote paths as data in every generated launcher

`install.sh` inserts the checkout path directly inside shell double quotes.
A checkout directory containing a literal `$NAME` is therefore expanded when
the generated stub runs. This was reproduced in a temporary checkout: installation
succeeded and the installed command failed to find its target. Quotes and
backticks need the same attention. Generate shell-escaped arguments, without eval.
Windows batch launchers need their own quoting and percent-expansion tests.

Normalize `--prefix` before using it. `install.cmd` forwards `D:\bin` unchanged;
`install.sh` currently does not convert Windows drive paths to POSIX paths before
`mkdir`. Validate this with cmd and PowerShell, then share the existing path
conversion behavior where appropriate.

Acceptance: install, launch, reinstall and uninstall from paths with spaces,
Unicode, apostrophes, dollar signs, percent signs and Windows drive letters.

## 3. Test the actual installation doors on every OS

There is no CI workflow in this checkout. `test.sh` covers launch behavior well,
but only syntax-checks `install.sh`; the Windows path checks skip without cygpath.
Add Linux, macOS, Git Bash, cmd and PowerShell jobs. Treat MSYS2 as a distinct
runtime. Run installation into scratch homes/prefixes, execute the generated
command, check exact arguments and exit codes, and uninstall. Include repeat
installation, a missing agent, a missing Bash, a moved checkout, and CRLF input.

The test harness still inherits the host PATH, so whether some catalog tools are
installed can affect menu expectations. Supply controlled stubs/missing-tool
fixtures for every catalog entry before relying on the matrix.

## 4. Add a read-only `cly doctor`

Report the selected Bash and version, actual cly target, config location,
resolved agent paths and versions, missing launch directories, and which remote
and bypass capabilities each installed agent supports. Give actionable fixes.
Do not start agents, log in, start remote daemons or print credentials.

Make version/capability checks explicit at setup or doctor time, rather than
spawning every agent on each menu redraw. Defaults change upstream: Kimi's
`--yolo` now differs from `--auto`, and Codex's daemon workflow is version-dependent.

## 5. Make config portable and crash-safe

`cly_config_path` uses `~/.config` unless `CLY_CONFIG` is set. Add documented
`XDG_CONFIG_HOME` support with a deliberate migration/precedence rule, and a
consistent Windows location across cmd, PowerShell, Git Bash and MSYS2.

The profile/default writers truncate the live config directly. Write a temporary
file beside it, validate it, then replace atomically; serialize simultaneous
setup writes. Test interruption and read-only destinations. Preserve comments,
unknown keys, explicit empty flags, and a recoverable backup during migration.

Keep shared profile choices separate from machine-specific executable and directory
paths, so syncing a config does not send macOS to a Windows drive path.

## 6. Make upgrades and removal predictable

Run-in-place installation means moving or deleting the checkout breaks cly, and
pulling changes immediately updates the live command. Offer an optional stable
copy installation with an explicit update command and rollback, while retaining
the current developer workflow. Record the installed target and interpreter.

The current uninstall removes anything named `cly` or `cly.cmd` in the prefix.
Check ownership markers before removal. Legacy profile cleanup should back up
the file and reject an unmatched opening marker instead of discarding its tail.

Recommended order: interpreter detection and path quoting first; installation
matrix next; doctor, config durability and managed upgrades after that.
