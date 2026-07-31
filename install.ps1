<#
.SYNOPSIS
    Wire cly.ps1 into your PowerShell profile.

.DESCRIPTION
    Adds a single dot-source line pointing at cly.ps1 where it already sits, so
    `git pull` in this directory updates the installed function too. Re-running
    is safe: the block is replaced, never duplicated.

.PARAMETER ProfilePath
    Which profile to edit. Defaults to $PROFILE for the PowerShell edition you
    run this with — run it under both powershell.exe and pwsh.exe if you use
    both, since they keep separate profiles.

.PARAMETER Dir
    Sets CLY_DIR in the profile, pinning the launch directory. Omit to let cly
    use its default of $HOME\claude.

.PARAMETER Uninstall
    Remove the block instead of adding it.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Dir C:\Users\me\claude
    .\install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string] $ProfilePath = $PROFILE,
    [string] $Dir,
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

$selfDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$src     = Join-Path $selfDir 'cly.ps1'
$marker  = '# >>> cly >>>'
$endMark = '# <<< cly <<<'

if (-not (Test-Path -LiteralPath $src)) {
    throw "install: cannot find $src"
}

# Set-Content -Encoding utf8 emits a BOM on Windows PowerShell 5.1, and a BOM
# is not what a profile that had none should suddenly grow. Write UTF-8 without
# one, with the platform newline, so the file comes back the way it went in.
function Write-ClyProfile {
    param([string] $Path, [string[]] $Lines)
    $text = ($Lines -join [Environment]::NewLine) + [Environment]::NewLine
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding $false))
}

# The profile file may not exist yet, and neither may its directory.
$profileDir = Split-Path -Parent $ProfilePath
if ($profileDir -and -not (Test-Path -LiteralPath $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
}

# Strip any previous block first — that is what makes re-running idempotent and
# gives -Uninstall its behaviour for free.
$kept = @()
if (Test-Path -LiteralPath $ProfilePath) {
    $skip = $false
    # -Encoding UTF8 is not optional: Windows PowerShell 5.1's Get-Content
    # defaults to the system ANSI codepage, so a profile containing any
    # non-ASCII character (an em-dash in a comment is enough) would be read as
    # mojibake and written back that way — corrupting lines this script has no
    # business touching. Reading UTF-8 is safe for a pure-ASCII file too.
    foreach ($line in (Get-Content -LiteralPath $ProfilePath -Encoding UTF8)) {
        if     ($line -eq $marker)  { $skip = $true;  continue }
        elseif ($line -eq $endMark) { $skip = $false; continue }
        if (-not $skip) { $kept += $line }
    }
}

if ($Uninstall) {
    Write-ClyProfile -Path $ProfilePath -Lines $kept
    Write-Output "cly: removed from $ProfilePath"
    return
}

$block = @($marker, ". '$src'", $endMark)

Write-ClyProfile -Path $ProfilePath -Lines ($kept + $block)
Write-Output "cly: installed into $ProfilePath"

# -Dir seeds the config file rather than setting CLY_DIR, because CLY_DIR
# overrides the config permanently — `cly --cly-init` would then appear to do
# nothing. Seeding the config leaves it editable the normal way.
if ($Dir) {
    . $src   # for Get-ClyConfigPath / Set-ClyConfiguredDir / Initialize-Cly
    Initialize-Cly -Dir $Dir
} else {
    Write-Output "cly: you will be asked for a launch directory the first time you run it."
}

Write-Output "cly: open a new shell, or run: . `$PROFILE"
