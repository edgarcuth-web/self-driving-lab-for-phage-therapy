@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required. Install Python and enable Add to PATH.
  pause
  exit /b 1
)
python -m phage_lab dashboard %*
if errorlevel 1 pause
