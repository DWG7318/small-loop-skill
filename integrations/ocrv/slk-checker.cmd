@echo off
if /I "%~1"=="--slk-post-d1" (
  python "%~dp0slk_checker_post_d1.py" %*
) else if /I "%~1"=="--slk-complete-d1" (
  python "%~dp0slk_checker_post_d1.py" %*
) else if /I "%~1"=="--slk-manage-incomplete" (
  python "%~dp0slk_checker_post_d1.py" %*
) else (
  python "%~dp0slk_checker_adapter.py" %*
)
exit /b %ERRORLEVEL%
