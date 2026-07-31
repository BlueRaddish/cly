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
# Configure by setting any of these before the call:
#   $env:CLY_DIR    directory to launch from  (default: $HOME\claude)
#   $env:CLY_BIN    the claude executable     (default: claude, found on PATH)
#   $env:CLY_FLAGS  flags passed every time   (default: --remote-control
#                   --dangerously-skip-permissions)
#
# To pass NO flags, set the PowerShell variable rather than the environment
# one: `$CLY_FLAGS = @()`. PowerShell deletes an environment variable when you
# assign it "", so $env:CLY_FLAGS has no way to say "empty" as distinct from
# "unset" — the plain variable does, and takes precedence when it exists.
#
# Push-Location/Pop-Location rather than a bare Set-Location, so your prompt is
# still where you left it when Claude Code exits. The finally block means that
# holds even if you Ctrl-C out of it.
function cly {
    $dir = if ($env:CLY_DIR) { $env:CLY_DIR } else { Join-Path $HOME 'claude' }
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

    if (-not (Test-Path -LiteralPath $dir)) {
        if ($env:CLY_DIR) {
            # You asked for a specific directory and it is not there — worth
            # saying, because the symptom otherwise is memories not loading.
            Write-Warning "cly: CLY_DIR=$dir does not exist - starting in $PWD instead."
        }
        # Nothing configured and no ~\claude to default to: behave like plain
        # claude. Nobody asked for the directory pinning, so do not complain.
        & $bin @flags @args
        return
    }

    Push-Location -LiteralPath $dir
    try     { & $bin @flags @args }
    finally { Pop-Location }
}
