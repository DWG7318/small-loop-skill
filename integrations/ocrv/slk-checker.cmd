@echo off
if /I "%~1"=="--slk-worker-recovery" (
  python "%~dp0slk_checker_recovery.py" %*
) else (
  python "%~dp0slk_checker_adapter.py" %*
)
exit /b %ERRORLEVEL%
