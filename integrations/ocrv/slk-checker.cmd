@echo off
if /I "%~1"=="--slk-post-d1" (
  python "%~dp0slk_checker_post_d1.py" %*
) else if /I "%~1"=="--slk-worker-recovery" (
  python "%~dp0slk_checker_recovery.py" %*
) else if /I "%~1"=="--slk-existing-terminal" (
  python "%~dp0slk_checker_recovery.py" %*
) else (
  python "%~dp0slk_checker_adapter.py" %*
)
exit /b %ERRORLEVEL%
