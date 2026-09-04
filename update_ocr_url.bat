@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"

if exist "C:\Users\meesa\Downloads\final land\.venv\Scripts\python.exe" (
    "C:\Users\meesa\Downloads\final land\.venv\Scripts\python.exe" "%SCRIPT_DIR%update_ocr_url.py" %*
) else if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%update_ocr_url.py" %*
) else (
    python "%SCRIPT_DIR%update_ocr_url.py" %*
)

exit /b %ERRORLEVEL%
