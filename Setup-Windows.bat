@echo off
setlocal
cd /d "%~dp0"
title Foldmark Setup

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 goto no_python
  set "PYTHON_CMD=python"
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto old_python

echo Creating the private app environment...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 goto failed

echo Installing Microsoft MarkItDown and desktop components...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo.
echo Setup complete. Double-click Start-Windows.bat to use the app.
pause
exit /b 0

:no_python
echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
echo During installation, select "Add Python to PATH", then run this setup again.
pause
exit /b 1

:old_python
echo Python 3.10 or newer is required. Download it from https://www.python.org/downloads/
pause
exit /b 1

:failed
echo.
echo Setup did not finish. Check your internet connection and the message above.
pause
exit /b 1
