@echo off
if not exist "%~dp0..\runtime\python\python.exe" (
    echo FAIL SLK_TRANSPORT: Python runtime is missing: "%~dp0..\runtime\python\python.exe" 1>&2
    exit /b 2
)
"%~dp0..\runtime\python\python.exe" "%~dp0slk-transport.pyz" %*
exit /b %ERRORLEVEL%
