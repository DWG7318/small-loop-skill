@echo off
if not exist "%~dp0..\runtime\temporal\temporal.exe" (
  echo Temporal runtime is missing. 1>&2
  exit /b 2
)
"%~dp0..\runtime\temporal\temporal.exe" %*
exit /b %ERRORLEVEL%
