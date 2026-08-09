@echo off
rem install.cmd - the Windows-side door to install.sh.
rem
rem install.sh is a bash script, and someone who has just cloned this repo on
rem Windows is standing in PowerShell or cmd, where `./install.sh` is not a
rem thing you can run. This finds a bash and hands the invocation over, so
rem `.\install` works from the shell you are already in.
rem
rem Arguments are forwarded unchanged: install --prefix D:\bin, install
rem --uninstall and install --help all behave as documented for install.sh.
rem
rem CLY_BASH points at a bash.exe outright, when the ones looked for below are
rem not the one you want.

setlocal

set "CLY_SETUP=%~dp0install.sh"
set "CLY_RUNNER="
set "CLY_LOGIN="

if not exist "%CLY_SETUP%" (
    >&2 echo install: cannot find install.sh next to this launcher.
    >&2 echo install: expected it at %CLY_SETUP%
    exit /b 1
)

rem The same search as cly.cmd, and for the same reasons: Git for Windows'
rem bin\bash.exe needs no login shell, MSYS2's does, and `where bash` is not
rem asked because on a machine with WSL it answers with a Linux shell.
if defined CLY_BASH if exist "%CLY_BASH%" set "CLY_RUNNER=%CLY_BASH%"
if not defined CLY_RUNNER if exist "%ProgramFiles%\Git\bin\bash.exe" set "CLY_RUNNER=%ProgramFiles%\Git\bin\bash.exe"
if not defined CLY_RUNNER if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "CLY_RUNNER=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined CLY_RUNNER if exist "%LOCALAPPDATA%\Programs\Git\bin\bash.exe" set "CLY_RUNNER=%LOCALAPPDATA%\Programs\Git\bin\bash.exe"

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
    >&2 echo install: no bash found - cly is a bash script and needs one to run.
    >&2 echo install: install Git for Windows, or set CLY_BASH to a bash.exe.
    exit /b 1
)

set "CLY_SETUP=%CLY_SETUP:\=/%"
set "MSYS_NO_PATHCONV=1"
set "MSYS2_ARG_CONV_EXCL=*"
set "CHERE_INVOKING=1"
if not defined MSYSTEM set "MSYSTEM=UCRT64"

if defined CLY_LOGIN (
    "%CLY_RUNNER%" -l "%CLY_SETUP%" %*
) else (
    "%CLY_RUNNER%" "%CLY_SETUP%" %*
)
exit /b %ERRORLEVEL%
