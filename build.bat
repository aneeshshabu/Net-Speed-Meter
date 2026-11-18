@echo off
title Building NetSpeedMeter
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

echo Installing required tools...
%PY% -m pip install --upgrade pyinstaller psutil
if errorlevel 1 goto fail

echo.
echo Building NetSpeedMeter.exe ...
%PY% -m PyInstaller --onefile --noconsole --name NetSpeedMeter netspeed.pyw
if errorlevel 1 goto fail

echo.
echo ==========================================================
echo  Done! Your file is here:  dist\NetSpeedMeter.exe
echo  Send that single file to your relative.
echo ==========================================================
pause
exit /b 0

:fail
echo.
echo Something went wrong. Make sure Python is installed
echo and "Add Python to PATH" was ticked during installation.
pause
exit /b 1
