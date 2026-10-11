@echo off
call "%~dp0..\runtime\ocrv\slk-checker.cmd" %*
exit /b %ERRORLEVEL%
