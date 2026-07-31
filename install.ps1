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
    foreach ($line in (Get-Content -LiteralPath $ProfilePath)) {
        if     ($line -eq $marker)  { $skip = $true;  continue }
        elseif ($line -eq $endMark) { $skip = $false; continue }
        if (-not $skip) { $kept += $line }
    }
}

if ($Uninstall) {
    Set-Content -LiteralPath $ProfilePath -Value $kept -Encoding utf8
    Write-Output "cly: removed from $ProfilePath"
    return
}

$block = @($marker)
if ($Dir) { $block += "`$env:CLY_DIR = '$Dir'" }
$block += ". '$src'"
$block += $endMark

Set-Content -LiteralPath $ProfilePath -Value ($kept + $block) -Encoding utf8

Write-Output "cly: installed into $ProfilePath"
if ($Dir) { Write-Output "cly: launch directory set to $Dir" }
Write-Output "cly: open a new shell, or run: . `$PROFILE"
