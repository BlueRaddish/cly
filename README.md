# cly

Launch [Claude Code](https://claude.ai/code) from one fixed directory, with the flags you always want, from whatever shell you happen to be in.

```console
$ pwd
/c/some/deep/repo
$ cly            # Claude Code starts in ~/claude; your shell stays put
```

## Why

Claude Code keys its memory store off the directory it was launched from:

```
~/.claude/projects/<launch-dir-with-separators-mangled>/memory/
```

There is one store per directory. If you keep your memories in one place — and you probably should — then launching from anywhere else loads **none** of them. Nothing errors. The memories are simply not there, and the first sign is Claude not knowing something you are certain you told it.

`cly` removes the failure mode by pinning the launch directory, and carries your standing flags so those cannot be forgotten either.

## Install

```sh
git clone https://github.com/BlueRaddish/cly
cd cly
./install.sh          # PowerShell or cmd: .\install
```

That writes a stub into `~/bin` that runs this clone in place, so `git pull` here is the whole of an upgrade. On Windows a `cly.cmd` goes in beside it, because PowerShell and cmd will not run an extensionless file. Re-running is safe; `--uninstall` removes the stubs; `--prefix DIR` puts them somewhere else.

`~/bin` has to be on your `PATH`. On Windows that means the **User** `PATH` in the registry — a line in `~/.bashrc` is invisible to PowerShell, cmd and anything started from the Start menu. `install.sh` checks, and prints the one-liner if it is missing.

## First run

`cly` asks two questions, once, and remembers the answers in `~/.config/cly/config`.

```console
$ cly
cly: two questions, then it will not ask again.

  Claude Code keeps a separate memory store for every directory it is
  launched from, so pinning one means the same memories load each time.

  Which directory should Claude Code launch from?
  Enter a path, or press Enter to launch wherever you happen to be.
  [none] > ~/claude

  Which flags should be passed to Claude Code on every launch?
  Enter flags, 'none' for no flags, or press Enter for the default.
  [--remote-control --dangerously-skip-permissions] >
```

Press Enter at the first question and `cly` launches wherever you are standing — the same as plain `claude`, but with your flags. Press Enter at the second and you get `--remote-control --dangerously-skip-permissions`; type `none` for no flags at all.

`cly --cly-init` asks both again. `cly --cly-init DIR` sets the directory and leaves the flags alone.

## Flags

Everything `cly` does not recognise goes to Claude Code untouched, so `cly --resume` and `cly -p "..."` work as they always did.

| Flag | Meaning |
|---|---|
| `--cly-init [DIR]` | set launch directory and standing flags; asks when `DIR` is omitted |
| `--cly-dir DIR` | launch from `DIR`, this call only |
| `--cly-no-dir` | launch from the current directory, this call only |
| `--cly-config` | show what is configured and what would run |
| `--cly-help` | show the help |

They all begin `--cly-` so that none can ever collide with a Claude Code flag. `cly --help` is therefore Claude Code's help, not `cly`'s.

## Configuration

Launch directory, most specific first: `--cly-no-dir` / `--cly-dir`, then `CLY_DIR`, then the config file, then the first-run prompt. Standing flags: `CLY_FLAGS`, then the config file, then the default.

| Variable | Default | Meaning |
|---|---|---|
| `CLY_DIR` | — | launch directory, overriding the config file |
| `CLY_FLAGS` | `--remote-control --dangerously-skip-permissions` | standing flags; empty means none |
| `CLY_BIN` | `claude` | the executable, if it is not on `PATH` under that name |
| `CLY_CONFIG` | `~/.config/cly/config` | where the config lives |
| `CLY_BASH` | — | Windows only: the `bash.exe` the shim should use |

The config is four lines and safe to edit by hand:

```
dir=/c/Users/me/claude
flags=--remote-control --dangerously-skip-permissions
```

An empty `dir=` launches wherever you are; an empty `flags=` passes none. A Windows path is understood wherever a path is read, so `dir=C:\Users\me\claude` means the same thing.

## One implementation

`bin/cly` is a bash script and is the whole program. bash, MSYS2 and WSL run it directly; PowerShell and cmd reach it through `bin/cly.cmd`, which finds a `bash.exe` and hands the invocation over with the working directory and the arguments intact. There is no second implementation to drift.

The script uses shell builtins and `mkdir` and nothing else — no `sed`, `awk` or `cygpath` — because the shim may hand it a bash whose `PATH` carries none of them.

`cly.cmd` prefers Git for Windows' `bin\bash.exe`, which starts with both `/usr/bin` and the Windows `PATH` already on `PATH` and stays in the caller's directory, so no login shell is needed. MSYS2's `usr\bin\bash.exe` is the fallback and does need `-l`. `where bash` is deliberately never consulted: on a machine with WSL it answers `C:\Windows\System32\bash.exe`, a Linux shell that cannot launch a Windows `claude.exe`.

## Behaviour in the awkward cases

- **The configured directory has been deleted** — warns, names it, and starts in the current directory. Staying quiet here looks exactly like memories mysteriously failing to load.
- **No config and no terminal to ask with** (a script, a hook, a cron job) — starts in the current directory with the default flags and writes no config, rather than blocking on a question nobody can answer, or eating the stdin meant for `claude -p`.
- **`--cly-init` with no directory and nothing to read** — exits 2 and says so.

Your shell's own working directory is untouched: `cly` is a script, so the `cd` happens in its own process.

## Tests

```sh
./test.sh
```

58 checks. No Claude Code is launched — `CLY_BIN` points at a stub that prints its working directory and arguments, which is the whole of what `cly` decides — and `CLY_CONFIG` points into a scratch directory, so the real config is unreachable from the suite. A dropping check count means a check stopped running, not that it started passing.

## A warning about the default flags

The default answer to the second question includes `--dangerously-skip-permissions`, which turns off Claude Code's permission prompts entirely — every file write, every shell command, no confirmation. That is a reasonable choice on a trusted personal machine and a bad one anywhere else. The prompt shows it before anyone accepts it, and `none` or any other answer is one keystroke away.

## License

MIT
