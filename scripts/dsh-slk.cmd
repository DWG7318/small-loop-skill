@echo off
rem Manual help/limited diagnostics only; automated tasks use DshAdapter's direct PowerShell channel.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0..\runtime\dsh\dsh-slk.ps1" %*
exit /b %ERRORLEVEL%
