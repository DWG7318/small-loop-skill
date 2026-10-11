@echo off
rem Manual help/limited diagnostics only; CMD does not preserve arbitrary task text.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0dsh-slk.ps1" %*
exit /b %ERRORLEVEL%
