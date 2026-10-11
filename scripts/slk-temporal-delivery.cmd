@echo off
if not exist "%~dp0..\runtime\python\python.exe" (
  echo Python runtime is missing. 1>&2
  exit /b 2
)
"%~dp0..\runtime\python\python.exe" -B -m slk_temporal.delivery_client %*
exit /b %ERRORLEVEL%
