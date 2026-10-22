@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Setup stopped with an error. Read the message above, then press any key to close.
    pause >nul
    exit /b 1
)
echo.
echo Setup finished. Press any key to close.
pause >nul
