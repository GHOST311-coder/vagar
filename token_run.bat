@echo off
if not defined VAGAR_PYTHON set VAGAR_PYTHON=C:\Python310\python.exe
REM Vagar token server launcher — SELF-HEALING (2026-10-14).
REM Loops forever: if token_server.py exits or crashes, wait 10s and restart.
REM Duplicate guard: if another token_run.bat is already running, exit so
REM two loops can never fight over port 7999.

powershell -noprofile -c "$c = @(Get-CimInstance Win32_Process -Filter 'Name=''cmd.exe''' | Where-Object { $_.CommandLine -like '*token_run.bat*' }).Count; if ($c -gt 1) { exit 1 } else { exit 0 }"
if %ERRORLEVEL%==1 (
  echo [token_run] another token_run.bat is already running; exiting.
  exit /b 0
)

:loop
REM If something else is already serving port 7999, stand down.
powershell -noprofile -c "if ((Test-NetConnection 127.0.0.1 -Port 7999 -InformationLevel Quiet)) { exit 0 } else { exit 1 }"
if %ERRORLEVEL%==0 (
  echo [token_run] port 7999 already served by another instance; exiting.
  exit /b 0
)
powershell -noprofile -c "Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -match 'token_server.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 /nobreak >nul
echo [token_run] starting token_server.py at %DATE% %TIME%
%VAGAR_PYTHON% -u %~dp0token_server.py >> %~dp0token_task.log 2>&1
echo [token_run] token_server.py exited at %DATE% %TIME%; restarting in 10s
timeout /t 10 /nobreak >nul
goto loop
