@echo off
REM Daily job (called by Task Scheduler). Output goes to runner\logs\equote.log
cd /d "%~dp0.."
if not exist "runner\logs" mkdir "runner\logs"
".venv-runner\Scripts\python.exe" -X utf8 -m runner.equote_runner >> "runner\logs\equote.log" 2>&1
