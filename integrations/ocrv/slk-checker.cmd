@echo off
setlocal
set "slk_python=python"
if exist "%~dp0..\python\python.exe" set "slk_python=%~dp0..\python\python.exe"
if exist "%~dp0bin\opencodereview.exe" if not exist "%~dp0..\python\python.exe" (
  echo Python runtime is missing. 1>&2
  exit /b 2
)
if /I "%~1"=="--slk-post-d1" (
  "%slk_python%" -B "%~dp0slk_checker_post_d1.py" %*
) else if /I "%~1"=="--slk-complete-d1" (
  "%slk_python%" -B "%~dp0slk_checker_post_d1.py" %*
) else if /I "%~1"=="--slk-manage-incomplete" (
  "%slk_python%" -B "%~dp0slk_checker_post_d1.py" %*
) else (
  "%slk_python%" -B "%~dp0slk_checker_adapter.py" %*
)
exit /b %ERRORLEVEL%
