@echo off
REM Diamond Certificate Portal - Windows launcher (first run installs everything into .venv)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv || (echo Python 3.10-3.13 64-bit is required: https://www.python.org/downloads/ & pause & exit /b 1)
)
REM (re)install whenever requirements.txt differs from the copy saved after the last install
fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if errorlevel 1 (
  echo Installing packages, this takes a few minutes the first time...
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
  copy /y requirements.txt .venv\requirements.installed >nul
)
if "%OCR_BACKEND%"=="" set OCR_BACKEND=auto
echo Opening http://localhost:8000
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
