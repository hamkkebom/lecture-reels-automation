@echo off
rem Starts the submission fetcher (keeps checking every 5 minutes).
rem ASCII only on purpose: cmd misreads non-ASCII text in batch files.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" fetcher_launch.py
) else (
  where py >nul 2>nul && (py -3 fetcher_launch.py) || (python fetcher_launch.py)
)
pause
