@echo off
rem Run from source without building an .exe (handy while changing the code)
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || (pause & exit /b 1)
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt || (pause & exit /b 1)
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\fetch_tools.ps1 -Dest bin
) else (
  call .venv\Scripts\activate.bat
)
start "" pythonw -m vidharbor
