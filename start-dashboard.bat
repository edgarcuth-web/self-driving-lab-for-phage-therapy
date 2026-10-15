@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python -m phage_lab dashboard
) else (
    py -3 -m phage_lab dashboard
)
if errorlevel 1 pause
