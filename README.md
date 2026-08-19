# cly

Launch an agent CLI — [Claude Code](https://claude.ai/code), codex, whatever you run — from a directory you pin once, with the flags you always want, from whatever shell you happen to be in.

```console
$ pwd
/c/some/deep/repo
$ cly .          # Claude Code starts in ~/claude; your shell stays put
$ cly codex      # codex, its own flags, right where you are standing
```

## Why

Claude Code keys its memory store off the directory it was launched from:

```
~/.claude/projects/<launch-dir-with-separators-mangled>/memory/
```

There is one store per directory. If you keep your memories in one place — and you probably should — then launching from anywhere else loads **none** of them. Nothing errors. The memories are simply not there, and the first sign is Claude not knowing something you are certain you told it.

`cly` removes the failure mode by pinning the launch directory, and carries your standing flags so those cannot be forgotten either. A **profile** does the same for every other tool you run, each with its own executable, flags and directory.

## Install

```sh
git clone https://github.com/BlueRaddish/cly
cd cly
./install.sh          # PowerShell or cmd: .\install
```

That writes a stub into `~/bin` that runs this clone in place, so `git pull` here is the whole of an upgrade. On Windows a `cly.cmd` goes in beside it, because PowerShell and cmd will not run an extensionless file. Re-running is safe; `--uninstall` removes the stubs; `--prefix DIR` puts them somewhere else.

`~/bin` has to be on your `PATH`. On Windows that means the **User** `PATH` in the registry — a line in `~/.bashrc` is invisible to PowerShell, cmd and anything started from the Start menu. `install.sh` checks, and prints the one-liner if it is missing.

Nothing is configured by the install. The first `cly init`, or the first `cly .`, asks.

## First run

```console
$ cly init
cly: setting up the profile that 'cly .' launches.

  Which tool should 'cly .' launch?
  Enter a name — claude, codex, gemini, whatever you run.
  [claude] >

  Which flags should claude be given on every launch?
  Enter flags, 'none' for no flags, or press Enter to take the default.
  [--remote-control --dangerously-skip-permissions] >

  Claude Code keeps a separate memory store for every directory it is
  launched from, so pinning one means the same memories load each time.
  Which directory should claude launch from?
  Enter a path, or press Enter to launch wherever you are standing.
  [here] > ~/claude
```

Two questions per profile, three if the name is not something on your `PATH`. `cly init NAME` sets up any other profile the same way; the first profile you make becomes the one `cly .` launches, and a later one never takes that over silently.

You do not have to run `init` at all. `cly .` with nothing configured runs it for you, and naming a tool you have not set up yet offers to set it up on the spot:

```console
$ cly codex
cly: no codex profile yet — codex is on your PATH.

  Which flags should codex be given on every launch?
  ...
```

That is the whole story on a new machine: clone, install, name the tool you want.

## The grammar

```
cly [OPTION...] <PROFILE|.> [AGENT-ARG...]
```

**The first word is always cly's. Everything after the profile name is always the agent's.** Neither can claim the other's flags, which is why nothing here needs a `--cly-` prefix any more.

```console
$ cly . --resume            # claude --remote-control ... --resume
$ cly codex --search        # codex --search, plus whatever codex's profile carries
$ cly --dir ~/work codex    # cly takes --dir; codex gets nothing extra
$ cly one --help            # the agent's help, because it is after the name
$ cly --help                # cly's help, because it is before one
```

A bare `cly` prints a short screen and launches nothing: with no first word, anything it did would be a guess.

| Command | Meaning |
|---|---|
| `cly .` | launch the default profile |
| `cly NAME` | launch the profile called `NAME` |
| `cly init [NAME]` | set up a profile; with no `NAME`, the one `.` launches |
| `cly config [NAME]` | show what is configured, and what would run |
| `cly help` | the full help |
| `cly version` | the version |

| Option | Meaning |
|---|---|
| `-d, --dir DIR` | launch from `DIR`, this call only |
| `--here` | launch from the current directory, this call only |
| `-h, --help` | show cly's help |
| `-V, --version` | show the version |

Options go **before** the profile name. Exit status is `0` when the agent was launched or a command did its work, `1` when the config file could not be read or written, and `2` for a usage error or a profile that could not be set up.

## Profiles

A profile is a name with an executable, flags and a launch directory of its own:

```
default=claude

profile.claude.bin=claude
profile.claude.flags=--remote-control --dangerously-skip-permissions
profile.claude.dir=/c/Users/me/claude

profile.codex.bin=codex
profile.codex.flags=--search
profile.codex.dir=none
```

Every line but the name is optional. A profile with no `bin=` is named after the tool it runs, so `profile.codex.dir=none` alone is enough for `cly codex`. A profile with no `dir=` launches wherever you are standing, and `none` says so explicitly — usually what you want for a tool with no memory store to pin. A profile gets **no flags it did not ask for**: standing flags belong to the profile that asked for them, and another tool would choke on them.

`default=NAME` is which profile `cly .` launches. With exactly one profile configured you can leave it out — there is nothing else `.` could mean. With several and no `default=` line, `cly .` says so and asks you to run `cly init`.

## Configuration

Launch directory, most specific first: `--here` / `--dir`, then `CLY_DIR`, then the profile. Flags: `CLY_FLAGS`, then the profile. Executable: `CLY_BIN`, then the profile's `bin=`, then the profile's own name.

| Variable | Default | Meaning |
|---|---|---|
| `CLY_DIR` | — | launch directory, overriding the profile |
| `CLY_FLAGS` | — | flags, overriding the profile; empty means none |
| `CLY_BIN` | — | the executable, overriding the profile |
| `CLY_CONFIG` | `~/.config/cly/config` | where the config lives |
| `CLY_BASH` | — | Windows only: the `bash.exe` the shim should use |

The config file is `key=value` lines and safe to edit by hand; `cly init` rewrites the profile it was given and leaves every other line — comments, other profiles, anything you added — exactly where it was. A Windows path is understood wherever a path is read, so `dir=C:\Users\me\claude` means the same thing.

## Coming from v2

v3 moved every one of cly's own words to the front, where nothing can collide with an agent flag, and deleted the `--cly-` prefix that existed to prevent that collision. The old forms are gone, not deprecated.

| v2 | v3 |
|---|---|
| `cly` | `cly .` |
| `cly --resume` | `cly . --resume` |
| `cly --cly-init [DIR]` | `cly init [NAME]` |
| `cly --cly-config` | `cly config` |
| `cly --cly-help` | `cly help`, or `cly --help` |
| `cly --cly-dir DIR` | `cly --dir DIR NAME` |
| `cly --cly-no-dir` | `cly --here NAME` |
| `cly --cly-use NAME` | `cly NAME` |

**Your v2 config keeps working.** Top-level `dir=` and `flags=` lines are read as the definition of a profile called `claude`, and as the default, which is what they always meant; `cly config` says when it is doing that. Nothing is rewritten behind your back — the next `cly init claude` writes the new shape, and a real `profile.claude.` section supersedes the old lines when both are present.

## One implementation

`bin/cly` is a bash script and is the whole program. bash, MSYS2 and WSL run it directly; PowerShell and cmd reach it through `bin/cly.cmd`, which finds a `bash.exe` and hands the invocation over with the working directory and the arguments intact. There is no second implementation to drift.

The script uses shell builtins and `mkdir` and nothing else — not even `cat`, whose absence would otherwise break writing the config file — because the shim may hand it a bash whose `PATH` carries none of them. `cygpath` is the one exception, reached through `command -v` and falling back to parameter expansion when it is missing. `test.sh` checks that it stays that way, and the suite itself runs with a `PATH` it owns so it tests cly rather than the machine.

`cly.cmd` prefers Git for Windows' `bin\bash.exe`, which starts with both `/usr/bin` and the Windows `PATH` already on `PATH` and stays in the caller's directory, so no login shell is needed. MSYS2's `usr\bin\bash.exe` is the fallback and does need `-l`. `where bash` is deliberately never consulted: on a machine with WSL it answers `C:\Windows\System32\bash.exe`, a Linux shell that cannot launch a Windows `claude.exe`.

## Behaviour in the awkward cases

- **The configured directory has been deleted** — warns, names it, and starts in the current directory. Staying quiet here looks exactly like memories mysteriously failing to load.
- **A name with no profile, and no terminal to ask at** (a script, a hook, a cron job) — exits 2 and names the profiles that do exist, rather than blocking on a question nobody can answer, or eating the stdin meant for `claude -p`.
- **A name that is neither a profile nor a program** — exits 2 and says both, and offers `cly init NAME` for the case where you meant it anyway.
- **Several profiles and no default** — exits 2 rather than picking one.

Your shell's own working directory is untouched: `cly` is a script, so the `cd` happens in its own process.

## Tests

```sh
./test.sh
```

150 checks. No agent is launched — `CLY_BIN` points at a stub that prints its working directory and arguments, which is the whole of what `cly` decides — and `CLY_CONFIG` points into a scratch directory, so the real config is unreachable from the suite. A dropping check count means a check stopped running, not that it started passing.

## A warning about the default flags

Setting up a profile that runs Claude Code offers `--remote-control --dangerously-skip-permissions` as the default answer, and the second of those turns off Claude Code's permission prompts entirely — every file write, every shell command, no confirmation. That is a reasonable choice on a trusted personal machine and a bad one anywhere else. It is offered, never assumed: the prompt shows it before anyone accepts it, and `none` or any other answer is one keystroke away. No other profile is offered flags at all.

## License

MIT
