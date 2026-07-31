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

To pin a directory other than the default at install time:

```sh
./install.sh --dir ~/claude
```
```powershell
.\install.ps1 -Dir C:\Users\me\claude
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLY_DIR` | `$HOME/claude` | Directory to launch from |
| `CLY_BIN` | `claude` | The executable, if it is not on `PATH` under that name |
| `CLY_FLAGS` | `--remote-control --dangerously-skip-permissions` | Flags passed on every call |

Arguments you pass go through untouched: `cly --resume`, `cly -p "..."`, all fine.

To pass **no** flags at all:

```sh
export CLY_FLAGS=""          # bash
```
```powershell
$CLY_FLAGS = @()             # PowerShell — the variable, not $env:
```

PowerShell deletes an environment variable when you assign it `""`, so `$env:CLY_FLAGS` cannot express "empty" as distinct from "unset". The plain `$CLY_FLAGS` variable can, and takes precedence over the environment one when it exists.

## Behaviour when the directory is missing

- **`CLY_DIR` set but missing** — warns, then starts in the current directory. You asked for something specific and did not get it, so it says so.
- **`CLY_DIR` unset and `~/claude` missing** — starts in the current directory, silently. You never asked for directory pinning, so there is nothing to complain about; `cly` is then just `claude` plus your default flags.

Either way your shell's own working directory is untouched when Claude Code exits — bash runs the body in a subshell, PowerShell uses `Push-Location`/`Pop-Location` in a `finally`.

## A warning about the default flags

The default `CLY_FLAGS` includes `--dangerously-skip-permissions`, which turns off Claude Code's permission prompts entirely — every file write, every shell command, no confirmation. That is a deliberate choice for a trusted personal machine and a bad one anywhere else.

If you do not want it:

```sh
export CLY_FLAGS="--remote-control"
```

## License

MIT
