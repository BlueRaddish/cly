# cly

One command in front of every coding agent on the machine. A bare `cly` offers a menu of agents; `cly --resume` lists the sessions of all of them, newest first, and reopens the one you pick where it was born; `-x` adds the agent's own skip-the-prompts flag. A **profile** pins an executable, standing flags and a launch directory under a name, so `cly claude` starts [Claude Code](https://claude.ai/code) where its memories live whatever directory you are standing in.

```console
$ cly                # a menu: claude, codex, gemini, kimi, qwen, opencode, deepseek, meta
$ cly .              # the default profile — Claude Code, in ~/claude
$ cly -x codex       # codex, right here, with its approval prompts off
$ cly -r             # every agent's sessions on one screen; Enter resumes the one in hand
$ cly -x -c          # the newest session of any agent, resumed, prompts off
```

## Why

Claude Code keys its memory store off the directory it was launched from:

```
~/.claude/projects/<launch-dir-with-separators-mangled>/memory/
```

There is one store per directory. If you keep your memories in one place — and you probably should — then launching from anywhere else loads **none** of them. Nothing errors. The memories are simply not there, and the first sign is Claude not knowing something you are certain you told it.

`cly` removes the failure mode by pinning the launch directory, and carries your standing flags so those cannot be forgotten either. A profile does the same for every other tool you run. And because every one of those tools keeps its own session store in its own shape, `cly -r` reads all of them and shows one list.

## Install

```sh
git clone https://github.com/BlueRaddish/cly
cd cly
./install.sh          # PowerShell or cmd: .\install
```

That writes a stub into `~/bin` that runs this clone in place, so `git pull` here is the whole of an upgrade. On Windows a `cly.cmd` goes in beside it, because PowerShell and cmd will not run an extensionless file. Re-running is safe; `--uninstall` removes the stubs; `--prefix DIR` puts them somewhere else.

`~/bin` has to be on your `PATH`. On Windows that means the **User** `PATH` in the registry — a line in `~/.bashrc` is invisible to PowerShell, cmd and anything started from the Start menu. `install.sh` checks, and prints the one-liner if it is missing.

Nothing is configured by the install. The first `cly`, `cly init`, or `cly .` asks.

## First run

```console
$ cly
cly 4.1.0 — which agent?

    1  claude    Claude Code  installed, no profile yet
    2  codex     Codex        installed, no profile yet
    3  gemini    Gemini CLI   not installed: npm install -g @google/gemini-cli
    4  kimi      Kimi Code    not installed: npm install -g @moonshot-ai/kimi-code
    5  qwen      Qwen Code    not installed: npm install -g @qwen-code/qwen-code
    6  opencode  OpenCode     not installed: npm install -g opencode-ai
    7  deepseek  DeepSeek     not installed: ollama, from https://ollama.com/download
    8  meta      Llama        not installed: ollama, from https://ollama.com/download, then: ollama pull llama3.1
```

Move with the arrows and press Enter, or `x` to launch with the agent's prompts skipped; `/` searches the list. Picking a tool that is installed but has no profile asks the setup questions and then launches it; picking one that is not installed prints how to get it and how to sign in. `cly init NAME` asks the same questions on their own:

```console
$ cly init claude
  Which flags should claude be given on every launch?
  Enter flags, 'none' for no flags, or press Enter to keep the default.
  (Claude/Codex defaults enable remote control and skip permission prompts.)
  [--remote-control --dangerously-skip-permissions] >

  Claude Code keeps a separate memory store for every directory it is
  launched from, so pinning one means the same memories load each time.
  Which directory should claude launch from?
  Enter a path, or press Enter to launch wherever you are standing.
  [here] > ~/claude
```

Two questions per profile, three if the name is not something on your `PATH`. The first profile you make becomes the one `cly .` launches, and a later one never takes that over silently.

## The grammar

```
cly [OPTION...] [PROFILE|.] [AGENT-ARG...]
```

**The first word is always cly's. Everything after the profile name is always the agent's.** Neither can claim the other's flags, which is why nothing here needs a `--cly-` prefix. With no profile named at all, cly offers the menu.

```console
$ cly claude --model opus   # claude --remote-control --dangerously-skip-permissions --model opus
$ cly -x claude             # claude --remote-control --dangerously-skip-permissions
$ cly -x codex --search     # starts remote control, then codex --remote unix:// --dangerously-bypass-approvals-and-sandbox --search
$ cly --dir ~/work codex    # cly takes --dir; codex gets nothing extra
$ cly one --help            # the agent's help, because it is after the name
$ cly --help                # cly's help, because it is before one
```

| Command | Meaning |
|---|---|
| `cly` | pick an agent from the menu, then launch it |
| `cly .` | launch the default profile |
| `cly NAME` | launch the profile called `NAME` |
| `cly init [NAME]` | set up a profile; with no `NAME`, the one `.` launches |
| `cly config [NAME]` | show what is configured, and what would run |
| `cly help` | the full help |
| `cly version` | the version |

| Option | Meaning |
|---|---|
| `-x, --bypass` | skip the agent's permission prompts, with its own flag |
| `-r, --resume` | list every agent's sessions and resume the one picked; with a `PROFILE`, only that agent's |
| `-c, --continue` | resume the newest session without asking |
| `-d, --dir DIR` | launch from `DIR`, this call only |
| `--here` | launch from the current directory, this call only |
| `-h, --help` | show cly's help |
| `-V, --version` | show the version |

Options go **before** the profile name. Exit status is `0` when the agent was launched or a command did its work, `1` when the config file could not be read or written, and `2` for a usage error, nothing picked, or a profile that could not be set up.

## Resuming

```console
$ cly -r
cly 4.1.0 — which session?                                                      1/30
up/down move · type to filter · Enter resume · Esc quit · 30 of 76 · CLY_ROWS=60 shows more
    #  agent     last      where                       title
    1  claude    2m ago    ~/claude                    Upgrade cly into a funnel for multiple agents
    2  claude    7m ago    ~/claude                    the shell is still running the review right
    3  codex     2d ago    ~                           Continue interrupted conversation
    4  gemini    3d ago    ~/work/site                 Refactor the header component
    5  kimi      4d ago    ~/work/api                  Kimi fixes the build
```

The screen is modelled on the one `claude --resume` shows. Arrows, PgUp/PgDn, Home/End move the bar; Enter resumes; `x` resumes with the agent's prompts skipped, as if `-x` had been typed; `/` starts a search (`codex` keeps only Codex's rows, a word keeps the rows whose title has it); digits go to a row by number; Esc steps back — out of the search with the list as it left it, then clearing it, then leaving the screen. Outside a search, letters do nothing, so nothing typed by accident is a command. `cly -c` skips the screen and resumes the newest session; `-x` before either adds the bypass flag.

A session is resumed **in the directory it was started in** — every agent keys its store or its own picker on that directory — by the profile of its kind, with that profile's standing flags, or by the bare agent when no profile has that kind. `cly -r NAME` narrows the list to one agent; `cly -r .` to the default profile's. Without a terminal (`cly -r < /dev/null`, a script) the list is printed once and the exit status is 2.

Each kind's store, and what cly reads from it:

| Kind | Index read | Resume words |
|---|---|---|
| `claude` | `~/.claude/history.jsonl` — every typed prompt with its session id, directory and time; the name from `/rename` (`custom-title.json` beside the transcript) is the title; a session whose transcript has been cleaned up is not offered | `--resume ID` |
| `codex` | `~/.codex/history.jsonl` and `session_index.jsonl`; the directory comes from the session's rollout file, and a session without one is not offered | `resume ID` |
| `gemini` | `~/.gemini/tmp/*/chats/session-*.json*`, newest first by name; the directory from the project's `.project_root` or `~/.gemini/projects.json` | `--resume ID` |
| `kimi` | `~/.kimi-code/session_index.jsonl`, then each session's `state.json` for title, directory and time | `--session ID` |
| `qwen`, `opencode` | not listed: a per-directory tree that cannot be mapped back to a directory, and a database. `-x` still knows their flags | — |

The transcripts themselves are never read — opening one costs a disk access each and they can number in the hundreds — so the list appears in about a second, and every session is on it. The screen shows `CLY_ROWS` rows at once (default 15) and scrolls; twice that many files are opened per store without an index — the newest Gemini and Kimi sessions, and the Codex directories read before the screen (the rest are read when their row is picked).

## Agents

`-x` knows the skip-the-prompts flag of six kinds, `-r` the session store of four:

| Kind | Skip prompts | Sign in |
|---|---|---|
| `claude` | `--dangerously-skip-permissions` | `claude`, then `/login` |
| `codex` | `--dangerously-bypass-approvals-and-sandbox` | `codex login` |
| `gemini` | `--yolo` | `gemini`, then pick "Login with Google" |
| `kimi` | `--yolo` | `kimi`, then `/login` |
| `qwen` | `--yolo` | `qwen`, then `/auth` (a key or a coding plan) |
| `opencode` | `--auto` | `opencode auth login` |

A profile's kind is its executable's name, so `profile.codex.bin=codex` needs nothing more; `profile.NAME.kind=KIND` says otherwise when the executable is not the agent.

**DeepSeek and Llama are routes, not kinds.** No terminal agent signs you in with a DeepSeek account, and Meta hosts no Llama API any more. The menu's `deepseek` and `meta` entries set up Claude Code through [Ollama](https://ollama.com) — `ollama signin` for DeepSeek's hosted models, `ollama pull llama3.1` for Llama on your own machine — as a profile of kind `claude`:

```
profile.deepseek.bin=ollama
profile.deepseek.flags=launch claude --model deepseek-v4-pro --
profile.deepseek.dir=none
profile.deepseek.kind=claude
```

Everything after the `--` is Claude Code's, which is where `-x` and `--resume` land, and the sessions appear under `claude` in the list. The model name is whatever `ollama.com/search?c=cloud` lists; the setup question offers one and Enter keeps it. The key-based route exists too — DeepSeek's Anthropic-compatible endpoint, with the key kept out of the config:

```
profile.deepseek.bin=claude
profile.deepseek.env=ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic ANTHROPIC_AUTH_TOKEN=$DEEPSEEK_API_KEY
```

Claude Code and Codex are exercised on the machine this was written on. Gemini CLI, Kimi Code, Qwen Code and OpenCode are handled from their documentation and source as of September 2026 — the flags and the store layouts — and the Ollama routes from Ollama's; the suite feeds cly stores shaped that way, but a real one may have moved. If one has, `cly -r NAME` says so by listing nothing, and the fix is one of the small functions named after the kind in `bin/cly`.

## Profiles

A profile is a name with an executable, flags and a launch directory of its own, and optionally a kind and an environment:

```
default=claude

profile.claude.bin=claude
profile.claude.flags=--remote-control --dangerously-skip-permissions
profile.claude.dir=/c/Users/me/claude

profile.codex.bin=codex
profile.codex.flags=--remote-control --dangerously-bypass-approvals-and-sandbox
profile.codex.dir=none
```

Every line but the name is optional. A profile with no `bin=` is named after the tool it runs, so `profile.codex.dir=none` alone is enough for `cly codex`. A profile with no `dir=` launches wherever you are standing, and `none` says so explicitly — usually what you want for a tool with no memory store to pin. A profile gets **no flags it did not ask for**: standing flags belong to the profile that asked for them, and another tool would choke on them. `kind=` and `env=` are described above; `env=` values of the form `$NAME` are read from your environment at launch, so a key never has to sit in the file.

`default=NAME` is which profile `cly .` launches, and the row the menu starts on. With exactly one profile configured you can leave it out — there is nothing else `.` could mean. With several and no `default=` line, `cly .` says so and asks you to run `cly init`.

## Configuration

Launch directory, most specific first: `--here` / `--dir`, then `CLY_DIR`, then the profile — or, when resuming, the session's own directory. Flags: `CLY_FLAGS`, then the profile. Executable: `CLY_BIN`, then the profile's `bin=`, then the profile's own name.

| Variable | Default | Meaning |
|---|---|---|
| `CLY_DIR` | — | launch directory, overriding the profile |
| `CLY_FLAGS` | — | flags, overriding the profile; empty means none |
| `CLY_BIN` | — | the executable, overriding the profile |
| `CLY_CONFIG` | `~/.config/cly/config` | where the config lives |
| `CLY_ROWS` | `15` | rows the screen shows at once; twice that many files opened per store without an index |
| `CLY_BASH` | — | Windows only: the `bash.exe` the shim should use |

The agents' own variables are honoured for their stores: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME`, `KIMI_CODE_HOME`.

The config file is `key=value` lines and safe to edit by hand; `cly init` rewrites the profile it was given and leaves every other line — comments, other profiles, the profile's own `kind=` and `env=` — exactly where it was. A Windows path is understood wherever a path is read, so `dir=C:\Users\me\claude` means the same thing.

## Coming from v3

v4 gave the bare `cly` and `--resume` to cly itself, and moved the permission bypass out of the standing flags and onto `-x`.

| v3 | v4 |
|---|---|
| `cly` — a help screen | `cly` — the menu (the help screen when there is no terminal) |
| `cly . --resume` — the agent's own picker | still the agent's own picker; `cly -r` is the one across every agent |
| `profile.claude.flags=--remote-control --dangerously-skip-permissions` | `profile.claude.flags=--remote-control`, and `cly -x .` |

A v3 config keeps working unchanged: a bypass flag left in `flags=` still applies on every launch, and `-x` does not add it twice. Taking it out of the file is what makes `-x` mean something. A v2 config (top-level `dir=` and `flags=`) is still read as the `claude` profile, as before.

## One implementation

`bin/cly` is a bash script and is the whole program — bash 4.2 or later, which every Linux, Git for Windows and MSYS2 has; macOS ships 3.2 and needs Homebrew's. bash, MSYS2 and WSL run it directly; PowerShell and cmd reach it through `bin/cly.cmd`, which finds a `bash.exe` and hands the invocation over with the working directory and the arguments intact. There is no second implementation to drift.

The script uses shell builtins and `mkdir` and nothing else — not even `cat`, whose absence would otherwise break writing the config file — because the shim may hand it a bash whose `PATH` carries none of them. `cygpath` is the one exception, reached through `command -v` and falling back to parameter expansion when it is missing. `test.sh` checks that it stays that way, and the suite itself runs with a `PATH` it owns so it tests cly rather than the machine.

The session lists and the screen are built the same way: each store's index is read whole with `$(<file)` and split in the shell (`mapfile` reads 128 bytes at a time and is 25x slower on these sizes), and nothing in that path forks — a `$(...)` costs 30–80 ms on Windows, and the index has one line per prompt ever typed. The screen is ANSI escapes and `read -n1`; the terminal's size is asked of the terminal itself. It is drawn the way Ink draws Claude Code's own picker — the frame is printed, and each redraw moves the cursor back up over it and prints it again — because through Git's bash a plain conhost window does not honour clear-screen or an alternate screen, and cursor-up does work there.

`cly.cmd` prefers Git for Windows' `bin\bash.exe`, which starts with both `/usr/bin` and the Windows `PATH` already on `PATH` and stays in the caller's directory, so no login shell is needed. MSYS2's `usr\bin\bash.exe` is the fallback and does need `-l`. `where bash` is deliberately never consulted: on a machine with WSL it answers `C:\Windows\System32\bash.exe`, a Linux shell that cannot launch a Windows `claude.exe`.

## Behaviour in the awkward cases

- **The configured directory has been deleted** — warns, names it, and starts in the current directory. Staying quiet here looks exactly like memories mysteriously failing to load.
- **The session's directory has been deleted** — the same: warns, and resumes where you are standing.
- **A name with no profile, and no terminal to ask at** (a script, a hook, a cron job) — exits 2 and names the profiles that do exist, rather than blocking on a question nobody can answer, or eating the stdin meant for `claude -p`.
- **A name that is neither a profile nor a program** — exits 2 and says both — and, for a name from the menu, what to install and how to sign in.
- **`-x` on a kind cly does not know** — exits 2 and names the config key that would teach it, or says to put the flag in `flags=` instead.
- **Several profiles and no default** — exits 2 rather than picking one.

Your shell's own working directory is untouched: `cly` is a script, so the `cd` happens in its own process.

## Tests

```sh
./test.sh
```

No agent is launched — `CLY_BIN` points at a stub that prints its working directory, its arguments and the environment it was given, which is the whole of what `cly` decides — and `CLY_CONFIG` and the four store variables point into a scratch directory, so the real config and the real session stores are unreachable from the suite. The stores it builds are shaped as the agents write theirs. A dropping check count means a check stopped running, not that it started passing.

## Remote control and permission defaults

New Claude and Codex profiles default to remote control and permission bypass. `cly init` displays these flags before saving; enter `none` to disable both, or supply your own flags. Existing profiles keep their explicit flags. `-x` remains available for other profiles and does not duplicate an existing bypass flag.

Claude receives `--remote-control --dangerously-skip-permissions`. For Codex, the standing `--remote-control` marker tells cly to run `codex remote-control start`, then connect the terminal using `--remote unix://` with `--dangerously-bypass-approvals-and-sandbox`. Startup failure stops the launch. This also applies when resuming through a configured Codex profile, and requires a Codex version supporting these commands. Arguments after the profile name remain native agent arguments; put the Codex marker in `profile.NAME.flags`, not after the profile name.

These defaults allow commands and writes without permission prompts (and disable Codex's sandbox). Use explicit profile flags or `CLY_FLAGS=''` for launches that should retain permission checks. See the [Codex command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli#codex-remote-control) for remote-control setup.

## License

MIT
