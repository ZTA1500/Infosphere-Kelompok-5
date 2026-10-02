@echo off
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

rem A .venv copied from another computer points at that computer's Python and
rem will not run here (and a GitHub zip has none) - check it, otherwise build it.
"%PY%" -c "import flask, pandas, jsonschema" >nul 2>&1 && goto venv_ok

echo First run on this computer: setting up Python packages. This takes a few minutes...
set "BASEPY="
py -3.10 -c "import sys" >nul 2>&1 && set "BASEPY=py -3.10"
if not defined BASEPY (py -3 -c "import sys" >nul 2>&1 && set "BASEPY=py -3")
if not defined BASEPY (python -c "import sys" >nul 2>&1 && set "BASEPY=python")
if not defined BASEPY (
  echo.
  echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run this file again.
  pause
  exit /b 1
)
%BASEPY% -m venv --clear .venv
if errorlevel 1 (
  echo Could not create the .venv folder.
  pause
  exit /b 1
)
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Installing packages failed - check your internet connection and run this file again.
  pause
  exit /b 1
)

:venv_ok
rem Admin credentials live in .env (hashed). First run: create them.
if not exist ".env" (
  echo No .env found - let's set the admin password first.
  "%PY%" scripts\set_admin_password.py
)

echo Starting Infosphere server. The first start can take a few minutes...
start "Infosphere Server" "%PY%" app.py

rem Open the browser only once the server answers, so nobody lands on an error page.
where curl >nul 2>&1
if errorlevel 1 (
  timeout /t 40 /nobreak >nul
  goto open_browser
)
set /a tries=0
:wait_server
timeout /t 2 /nobreak >nul
curl -s -o nul http://127.0.0.1:5000/healthz && goto open_browser
set /a tries+=1
if %tries% lss 300 goto wait_server
echo The server did not start within 10 minutes - check the "Infosphere Server" window for errors.
pause
exit /b 1

:open_browser
start "" http://127.0.0.1:5000/landing
