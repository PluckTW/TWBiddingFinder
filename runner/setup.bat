@echo off
REM One-time setup for the TWBiddingFinder e-quotation job. Run as Administrator.
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.11+ from python.org first, then rerun.
  exit /b 1
)
if not exist ".venv-runner" py -3 -m venv .venv-runner
".venv-runner\Scripts\python.exe" -m pip install --upgrade pip
".venv-runner\Scripts\python.exe" -m pip install -r runner\requirements.txt
if errorlevel 1 (
  echo [ERROR] Package install failed. Check the network / proxy.
  exit /b 1
)
if not exist "runner\config.json" (
  copy "runner\config.example.json" "runner\config.json" >nul
  echo [ACTION] Edit runner\config.json, then run runner\setup.bat again.
  exit /b 0
)
echo Testing connections...
chcp 65001 >nul
".venv-runner\Scripts\python.exe" -X utf8 -m runner.equote_runner --check
if errorlevel 1 (
  echo [ERROR] Connection test failed. See the message above. Task NOT scheduled.
  exit /b 1
)
schtasks /Create /TN "TWBiddingFinder\EQuote" /TR "\"%~dp0run_equote.bat\"" /SC DAILY /ST 10:00 /RU SYSTEM /RL HIGHEST /F
if errorlevel 1 (
  echo [ERROR] Could not create the scheduled task. Run this file as Administrator.
  exit /b 1
)
echo [OK] Setup done. The job runs every day at 10:00.
