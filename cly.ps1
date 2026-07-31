# cly — launch Claude Code from one fixed directory, whatever directory you are
# standing in.
#
# Claude Code keys its memory store off the working directory it was launched
# from: ~/.claude/projects/<working-dir-with-separators-mangled>/memory/. Keep
# your memories in one place and launching from anywhere else silently loads
# none of them — no error, they are just not there. cly pins the launch
# directory so that cannot happen by accident.
#
# Install:  . C:\path\to\cly.ps1   in your $PROFILE  (or run install.ps1)
#
# The launch directory is asked for once, on first use, and remembered in
# ~/.config/cly/config — the same file the bash version reads, so both shells
# agree. `cly --cly-help` lists the flags that change it.
#
# Configure by setting any of these before the call:
#   $env:CLY_BIN     the claude executable   (default: claude, found on PATH)
#   $env:CLY_FLAGS   flags passed every time (default: --remote-control
#                    --dangerously-skip-permissions)
#   $env:CLY_DIR     launch directory, overriding the config file
#   $env:CLY_CONFIG  where the config lives  (default: ~/.config/cly/config)
#
# To pass NO flags, set the PowerShell variable rather than the environment
# one: `$CLY_FLAGS = @()`. PowerShell deletes an environment variable when you
# assign it "", so $env:CLY_FLAGS has no way to say "empty" as distinct from
# "unset" — the plain variable does, and takes precedence when it exists.

function Get-ClyConfigPath {
    if ($env:CLY_CONFIG) { return $env:CLY_CONFIG }
    Join-Path $HOME '.config/cly/config'
}

# The config file is shared with the bash version, which naturally writes MSYS2
# paths like /c/Users/me — so accept one wherever a path is read. Anything else
# is handed back untouched, including ordinary relative paths.
function ConvertTo-ClyWindowsPath {
    param([string] $Path)
    if ($Path -match '^/([a-zA-Z])/(.*)$') {
        return ($Matches[1].ToUpper() + ':\' + ($Matches[2] -replace '/', '\'))
    }
    if ($Path -match '^/([a-zA-Z])/?$') {
        return ($Matches[1].ToUpper() + ':\')
    }
    $Path
}

# Returns the configured directory, or $null when there is no config yet. The
# literal 'none' is a real answer meaning "do not pin anything" — that is how
# declining at the prompt is remembered, so you are only ever asked once.
function Get-ClyConfiguredDir {
    $f = Get-ClyConfigPath
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    $last = $null
    foreach ($line in (Get-Content -LiteralPath $f)) {
        if ($line -match '^dir=(.*)$') { $last = $Matches[1] }
    }
    $last
}

function Set-ClyConfiguredDir {
    param([Parameter(Mandatory)][string] $Dir)
    $f      = Get-ClyConfigPath
    $parent = Split-Path -Parent $f
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    # LF endings and no BOM: the bash version reads this same file, and a BOM
    # would end up inside the first key it parses.
    $body = "# cly configuration`n" +
            "# Rewritten by ``cly --cly-init``; safe to edit by hand.`n" +
            "# dir=none means launch wherever you happen to be.`n" +
            "dir=$Dir`n"
    [System.IO.File]::WriteAllText($f, $body, (New-Object System.Text.UTF8Encoding $false))
}

function Show-ClyHelp {
    @'
cly — launch Claude Code from one fixed directory.

usage: cly [CLY-FLAGS] [CLAUDE ARGS ...]

Anything not listed below is passed straight through to Claude Code, so
`cly --resume`, `cly -p "..."` and the rest work as they always did.

  --cly-init [DIR]   set the launch directory and remember it. With no DIR you
                     are prompted. Creates the directory if it does not exist.
  --cly-dir DIR      launch from DIR just this once, ignoring the config
  --cly-no-dir       launch from the current directory just this once
  --cly-config       show the config file, what it says, and what would happen
  --cly-help         this help

The directory is asked for once, on first use, and stored in
~/.config/cly/config. Answer 'none' there or at the prompt to turn pinning off
without being asked again. Re-run --cly-init whenever you want to change it.
'@ | Write-Output
}

# Whether there is a human on the other end to answer a prompt. A function of
# its own so it can be stubbed when testing the prompt non-interactively.
function Test-ClyInteractive { -not [Console]::IsInputRedirected }

# Resolve and remember a launch directory. -Dir empty means ask.
function Initialize-Cly {
    param([string] $Dir)

    $default = Join-Path $HOME 'claude'

    if (-not $Dir) {
        if (-not (Test-ClyInteractive)) {
            Write-Error "cly: --cly-init needs a directory when input is redirected"
            return
        }
        Write-Output "cly: which directory should Claude Code launch from?"
        Write-Output "     It keeps a separate memory store per launch directory, so"
        Write-Output "     pinning one means the same memories load every time."
        Write-Output "     Enter a path, 'none' to launch wherever you are, or press"
        Write-Output "     Enter for the default."
        $reply = Read-Host "     [$default] "
        $Dir = if ($reply) { $reply } else { $default }
    }

    if ($Dir -eq 'none') {
        Set-ClyConfiguredDir -Dir 'none'
        Write-Output "cly: pinning turned off - cly will launch wherever you are."
        return
    }

    # ~ is not expanded by PowerShell inside a string, so a typed "~/claude"
    # would otherwise become a literal directory named "~".
    if ($Dir -eq '~')          { $Dir = $HOME }
    elseif ($Dir -like '~[/\]*') { $Dir = Join-Path $HOME $Dir.Substring(2) }

    if (-not (Test-Path -LiteralPath $Dir)) {
        try {
            New-Item -ItemType Directory -Path $Dir -Force -ErrorAction Stop | Out-Null
            Write-Output "cly: created $Dir"
        } catch {
            Write-Error "cly: cannot create $Dir"
            return
        }
    }

    # Store it absolute: a relative path would mean something different from
    # every directory you later call cly in.
    $Dir = (Resolve-Path -LiteralPath $Dir).Path
    Set-ClyConfiguredDir -Dir $Dir
    Write-Output "cly: launch directory set to $Dir"
    Write-Output "cly: stored in $(Get-ClyConfigPath)"
}

function cly {
    $passthru  = @()
    $dir       = $null
    $initDir   = $null
    $wantInit  = $false
    $wantCfg   = $false
    $wantHelp  = $false
    $noDir     = $false
    $restIsPassthru = $false

    for ($i = 0; $i -lt $args.Count; $i++) {
        $a = $args[$i]
        if ($restIsPassthru) { $passthru += $a; continue }
        switch -CaseSensitive ($a) {
            '--'            { $restIsPassthru = $true; $passthru += $a }
            '--cly-init'    {
                $wantInit = $true
                # An optional argument: take the next word only if it is not
                # itself a flag, so `--cly-init` alone still prompts.
                if ($i + 1 -lt $args.Count -and $args[$i + 1] -notlike '-*') {
                    $initDir = $args[++$i]
                }
            }
            '--cly-dir'     {
                if ($i + 1 -ge $args.Count) { Write-Error "cly: --cly-dir needs a directory"; return }
                $dir = $args[++$i]
            }
            '--cly-no-dir'  { $noDir    = $true }
            '--cly-config'  { $wantCfg  = $true }
            '--cly-help'    { $wantHelp = $true }
            default         { $passthru += $a }
        }
    }

    if ($wantHelp) { Show-ClyHelp; return }
    if ($wantInit) { Initialize-Cly -Dir $initDir; return }

    $bin = if ($env:CLY_BIN) { $env:CLY_BIN } else { 'claude' }

    # A plain $CLY_FLAGS variable wins over the environment one, and is the only
    # way to ask for no flags at all — see the header. Existence is what counts
    # here, not truthiness, which is exactly why Get-Variable is used.
    $varFlags = Get-Variable -Name CLY_FLAGS -Scope Global -ErrorAction SilentlyContinue
    if ($null -ne $varFlags) {
        $flags = @($varFlags.Value)
    } elseif ($env:CLY_FLAGS) {
        $flags = @($env:CLY_FLAGS -split '\s+' | Where-Object { $_ -ne '' })
    } else {
        $flags = @('--remote-control', '--dangerously-skip-permissions')
    }

    $configured = Get-ClyConfiguredDir

    if ($wantCfg) {
        Write-Output "config file: $(Get-ClyConfigPath)"
        if ($configured) {
            Write-Output "configured:  $configured"
        } else {
            Write-Output "configured:  (nothing yet - you will be asked on first launch)"
        }
        if ($env:CLY_DIR) { Write-Output "CLY_DIR:     $env:CLY_DIR (overrides the config)" }
        Write-Output "executable:  $bin"
        if ($flags.Count) { Write-Output "flags:       $($flags -join ' ')" }
        else              { Write-Output "flags:       (none)" }
        return
    }

    # Precedence, most specific first.
    if ($noDir) {
        $dir = $null
    } elseif ($dir) {
        # --cly-dir already set it
    } elseif ($env:CLY_DIR) {
        $dir = $env:CLY_DIR
    } elseif ($configured) {
        $dir = if ($configured -eq 'none') { $null } else { ConvertTo-ClyWindowsPath $configured }
    } elseif (Test-ClyInteractive) {
        # First use. Ask, remember, and carry on into the launch below.
        Initialize-Cly -Dir $null
        $configured = Get-ClyConfiguredDir
        $dir = if (-not $configured -or $configured -eq 'none') { $null }
               else { ConvertTo-ClyWindowsPath $configured }
    } else {
        # No config and nothing to ask with: behave like plain claude rather
        # than blocking a script on a prompt nobody can answer.
        $dir = $null
    }

    if (-not $dir) {
        & $bin @flags @passthru
        return
    }

    if (-not (Test-Path -LiteralPath $dir)) {
        # Configured but gone. Worth saying — the symptom otherwise is memories
        # quietly not loading.
        Write-Warning "cly: $dir does not exist - launching in $PWD instead."
        Write-Warning "cly: run 'cly --cly-init' to point it somewhere else."
        & $bin @flags @passthru
        return
    }

    Push-Location -LiteralPath $dir
    try     { & $bin @flags @passthru }
    finally { Pop-Location }
}
