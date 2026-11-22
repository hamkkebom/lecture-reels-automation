@echo off
rem Run once on a new work PC. ASCII only on purpose.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" fetcher_install.py
) else (
  where py >nul 2>nul && (py -3 fetcher_install.py) || (python fetcher_install.py)
)
if errorlevel 9009 echo Python is not installed. Install it from https://www.python.org/downloads/ and run this again.
pause
