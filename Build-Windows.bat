@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  call Setup-Windows.bat
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto failed

REM Directory mode, not --onefile: a onefile build unpacks itself on every
REM launch, which is slow with MarkItDown's dependencies.
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed ^
  --name "MarkItDown Desktop" ^
  --additional-hooks-dir=. ^
  --collect-all markitdown ^
  app.py
if errorlevel 1 goto failed

REM Signing is optional. Without it Windows SmartScreen warns on first run.
if defined WINDOWS_CERT_PATH (
  echo Signing with %WINDOWS_CERT_PATH% ...
  signtool sign /f "%WINDOWS_CERT_PATH%" /p "%WINDOWS_CERT_PASSWORD%" /fd sha256 ^
    /tr http://timestamp.digicert.com /td sha256 ^
    "dist\MarkItDown Desktop\MarkItDown Desktop.exe"
  if errorlevel 1 goto failed
) else (
  echo Built unsigned. Set WINDOWS_CERT_PATH and WINDOWS_CERT_PASSWORD to sign.
)

echo Build complete: dist\MarkItDown Desktop\MarkItDown Desktop.exe
pause
exit /b 0

:failed
echo Build failed. Review the error above.
pause
exit /b 1
