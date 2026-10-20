@echo off
rem One-click Windows build: creates dist\VidHarbor\VidHarbor.exe (+ ffmpeg, Deno)
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Get it from https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH" during setup, then run this file again.
  pause & exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller || (pause & exit /b 1)

echo Building VidHarbor.exe...
pyinstaller --noconfirm VidHarbor.spec || (pause & exit /b 1)

echo Fetching ffmpeg and Deno...
powershell -NoProfile -ExecutionPolicy Bypass -File tools\fetch_tools.ps1 -Dest dist\VidHarbor\bin || (pause & exit /b 1)

echo Checking the build...
dist\VidHarbor\VidHarbor.exe --selftest
type "%LOCALAPPDATA%\VidHarbor\selftest.txt"

echo.
echo Done. Run: dist\VidHarbor\VidHarbor.exe
echo To share it, zip the whole dist\VidHarbor folder.
pause
