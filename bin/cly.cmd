@echo off
rem cly.cmd - the Windows-side door to cly.
rem
rem cly is one bash script. This hands the invocation over to a bash, with the
rem current directory and the arguments intact, so that `cly . --resume` means
rem the same thing typed into PowerShell, cmd, a Windows Terminal tab, VS
rem Code's terminal or the Run box as it does in Git Bash or MSYS2.
rem
rem PowerShell and cmd both prefer a .cmd over an extensionless file of the
rem same name, and bash only ever looks for the exact name, so `cly` lands here
rem on Windows and on the script itself everywhere else. Neither side needs to
rem know about the other.
rem
rem CLY_BASH points at a bash.exe outright, when the ones looked for below are
rem not the one you want.

setlocal

set "CLY_SCRIPT=%~dp0cly"
set "CLY_RUNNER="
set "CLY_LOGIN="

if not exist "%CLY_SCRIPT%" (
    >&2 echo cly: cannot find the cly script next to this launcher.
    >&2 echo cly: expected it at %CLY_SCRIPT%
    exit /b 1
)

rem Git for Windows' bin\bash.exe is looked for first and run WITHOUT -l: it
rem already starts with /usr/bin and the Windows PATH both on PATH, so mkdir
rem and claude.exe are equally reachable, and it stays in the caller's
rem directory. That is one process and no profile - the cheapest door there is.
rem
rem `where bash` is deliberately not used to find one. On a machine with WSL
rem installed it answers C:\Windows\System32\bash.exe, which is a Linux shell
rem that cannot launch a Windows claude.exe.
if defined CLY_BASH if exist "%CLY_BASH%" set "CLY_RUNNER=%CLY_BASH%"
if not defined CLY_RUNNER if exist "%ProgramFiles%\Git\bin\bash.exe" set "CLY_RUNNER=%ProgramFiles%\Git\bin\bash.exe"
if not defined CLY_RUNNER if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "CLY_RUNNER=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined CLY_RUNNER if exist "%LOCALAPPDATA%\Programs\Git\bin\bash.exe" set "CLY_RUNNER=%LOCALAPPDATA%\Programs\Git\bin\bash.exe"

rem MSYS2 next, and this one does need -l: its usr\bin\bash.exe starts with
rem neither /usr/bin nor the Windows PATH, so without a login shell it can find
rem neither mkdir nor claude. CHERE_INVOKING stops the login profile wandering
rem off to $HOME, which would silently defeat the whole point of cly.
if not defined CLY_RUNNER if defined CLY_MSYS_ROOT if exist "%CLY_MSYS_ROOT%\usr\bin\bash.exe" (
    set "CLY_RUNNER=%CLY_MSYS_ROOT%\usr\bin\bash.exe"
    set "CLY_LOGIN=1"
)
if not defined CLY_RUNNER if exist "%SystemDrive%\msys64\usr\bin\bash.exe" (
    set "CLY_RUNNER=%SystemDrive%\msys64\usr\bin\bash.exe"
    set "CLY_LOGIN=1"
)
if not defined CLY_RUNNER if exist "C:\msys64\usr\bin\bash.exe" (
    set "CLY_RUNNER=C:\msys64\usr\bin\bash.exe"
    set "CLY_LOGIN=1"
)

if not defined CLY_RUNNER (
    >&2 echo cly: no bash found - cly is a bash script and needs one to run.
    >&2 echo cly: install Git for Windows, or set CLY_BASH to a bash.exe.
    exit /b 1
)

rem Forward slashes: bash is about to read this as a path, and some backslash
rem pairs are escape sequences to it even inside quotes.
set "CLY_SCRIPT=%CLY_SCRIPT:\=/%"

rem Stop msys rewriting arguments that merely look like paths on the way in.
rem `cly . -p "/status of the build"` is an ordinary argument, not a filename.
set "MSYS_NO_PATHCONV=1"
set "MSYS2_ARG_CONV_EXCL=*"
set "CHERE_INVOKING=1"
if not defined MSYSTEM set "MSYSTEM=UCRT64"

if defined CLY_LOGIN (
    "%CLY_RUNNER%" -l "%CLY_SCRIPT%" %*
) else (
    "%CLY_RUNNER%" "%CLY_SCRIPT%" %*
)
exit /b %ERRORLEVEL%
