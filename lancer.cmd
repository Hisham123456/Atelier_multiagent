@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
if not exist ".venv\atelier-installed" (
  ".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
  if errorlevel 1 goto failed
  type nul > ".venv\atelier-installed"
)
".venv\Scripts\python.exe" -m atelier --open-browser
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Le lancement a echoue. Consulte le message ci-dessus.
pause
exit /b 1
