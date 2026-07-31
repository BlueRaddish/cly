# cly

Launch [Claude Code](https://claude.ai/code) from one fixed directory, whatever directory you happen to be standing in.

```console
$ pwd
/c/some/deep/repo
$ cly            # Claude Code starts in ~/claude, your shell stays put
```

## Why

Claude Code keys its memory store off the working directory it was launched from:

```
~/.claude/projects/<working-dir-with-separators-mangled>/memory/
```

There is one such store per directory you launch from. If you keep your memories in one place — and you probably should — then launching from anywhere else loads **none** of them. Nothing errors. The memories are simply not there, and the first sign is Claude not knowing something you are certain you told it.

`cly` removes the failure mode by pinning the launch directory. It also carries whatever flags you always want, so they cannot be forgotten either.

## Install

```sh
git clone https://github.com/BlueRaddish/cly
cd cly
./install.sh                 # bash: appends a source line to ~/.bashrc
```

```powershell
.\install.ps1                # PowerShell: appends a dot-source line to $PROFILE
```

Both installers point at the files where they already sit, so `git pull` here updates the installed function. Both are idempotent — re-run them freely — and both take `--uninstall` / `-Uninstall`.

PowerShell 5.1 and PowerShell 7 keep **separate** profiles. If you use both, run `install.ps1` under each.

## Choosing the directory

The first time you run `cly` it asks where Claude Code should launch from, and remembers the answer in `~/.config/cly/config`. You are only asked once.

```console
$ cly
cly: which directory should Claude Code launch from?
     It keeps a separate memory store per launch directory, so
     pinning one means the same memories load every time.
     Enter a path, 'none' to launch wherever you are, or press
     Enter for the default.
     [/home/me/claude] >
```

Answer `none` to turn pinning off — `cly` then behaves like plain `claude` with your default flags, and stops asking.

To set it without being asked, or to change it later:

```sh
cly --cly-init ~/claude      # set and remember; creates the directory if needed
cly --cly-init               # ask again, interactively
```

The installers also take a directory, if you would rather decide at install time:

```sh
./install.sh --dir ~/claude
```
```powershell
.\install.ps1 -Dir C:\Users\me\claude
```

## Flags

`cly` claims a few flags of its own. Everything else is passed straight through to Claude Code, so `cly --resume` and `cly -p "..."` work as they always did.

| Flag | Meaning |
|---|---|
| `--cly-init [DIR]` | set the launch directory and remember it; prompts when `DIR` is omitted |
| `--cly-dir DIR` | launch from `DIR` just this once |
| `--cly-no-dir` | launch from the current directory just this once |
| `--cly-config` | show the config file, what it says, and what would happen |
| `--cly-help` | list these |

They are prefixed `--cly-` so that they cannot collide with a Claude Code flag now or later.

## Configuration

Precedence, most specific first: `--cly-dir` / `--cly-no-dir`, then `CLY_DIR`, then the config file, then the first-use prompt.

| Variable | Default | Meaning |
|---|---|---|
| `CLY_DIR` | — | Launch directory, overriding the config file |
| `CLY_CONFIG` | `~/.config/cly/config` | Where the config lives |
| `CLY_BIN` | `claude` | The executable, if it is not on `PATH` under that name |
| `CLY_FLAGS` | `--remote-control --dangerously-skip-permissions` | Flags passed on every call |

Both shells read and write the **same** config file, and each accepts the other's path style — bash stores `/c/Users/me/claude`, PowerShell stores `C:\Users\me\claude`, and either one is understood on the way back in.

Arguments you pass go through untouched: `cly --resume`, `cly -p "..."`, all fine.

To pass **no** flags at all:

```sh
export CLY_FLAGS=""          # bash
```
```powershell
$CLY_FLAGS = @()             # PowerShell — the variable, not $env:
```

PowerShell deletes an environment variable when you assign it `""`, so `$env:CLY_FLAGS` cannot express "empty" as distinct from "unset". The plain `$CLY_FLAGS` variable can, and takes precedence over the environment one when it exists.

## Behaviour in the awkward cases

- **The configured directory has been deleted** — warns, names it, and starts in the current directory. The symptom of staying quiet here would be memories mysteriously not loading.
- **No config yet and nothing to prompt with** (a script, a hook, a cron job) — starts in the current directory and writes no config, rather than blocking forever on a question nobody can answer.
- **`--cly-init` with no directory and no terminal** — refuses, rather than guessing.

Your shell's own working directory is untouched when Claude Code exits — bash runs the launch in a subshell, PowerShell uses `Push-Location`/`Pop-Location` in a `finally`.

## A warning about the default flags

The default `CLY_FLAGS` includes `--dangerously-skip-permissions`, which turns off Claude Code's permission prompts entirely — every file write, every shell command, no confirmation. That is a deliberate choice for a trusted personal machine and a bad one anywhere else.

If you do not want it:

```sh
export CLY_FLAGS="--remote-control"
```

## License

MIT
