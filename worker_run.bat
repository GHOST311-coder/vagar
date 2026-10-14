@echo off
if not defined VAGAR_PYTHON set VAGAR_PYTHON=C:\Python310\python.exe
REM Vagar worker launcher — SELF-HEALING (2026-10-14).
REM Loops forever: if agent.py exits or crashes, wait 10s and restart it.
REM Duplicate guard: if another worker_run.bat is already running, exit so
REM two loops can never fight over the same agent.py process.

powershell -noprofile -c "$c = @(Get-CimInstance Win32_Process -Filter 'Name=''cmd.exe''' | Where-Object { $_.CommandLine -like '*worker_run.bat*' }).Count; if ($c -gt 1) { exit 1 } else { exit 0 }"
if %ERRORLEVEL%==1 (
  echo [worker_run] another worker_run.bat is already running; exiting.
  exit /b 0
)

:loop
powershell -noprofile -c "Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -match 'agent.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 4 /nobreak >nul
echo [worker_run] starting agent.py at %DATE% %TIME%
%VAGAR_PYTHON% -u %~dp0agent.py dev >> %~dp0worker_task.log 2>&1
echo [worker_run] agent.py exited at %DATE% %TIME%; restarting in 10s
timeout /t 10 /nobreak >nul
goto loop
