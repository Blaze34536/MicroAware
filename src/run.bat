@echo off
rem Starts MicroAware on Windows, setting it up first if needed. Same options as run.sh, set first, e.g.:
rem   set MICROAWARE_SOURCE=synth   (simulated fan instead of the mic)
rem   set MICROAWARE_LINK=sim       (simulated radio link)
rem   set PORT=8001
setlocal
cd /d "%~dp0"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "VENV=%ROOT%\.venv"
set "PY=%VENV%\Scripts\python.exe"
if not defined PORT set PORT=8000
set "ROOT=%~dp0.."
set "VENV=%ROOT%\.venv"
set "PY=%VENV%\Scripts\python.exe"
set PACKAGES=numpy scipy scikit-learn sounddevice fastapi "uvicorn[standard]" pyserial zfec httpx python-dotenv pytest soundfile onnxruntime

rem 1. Virtual environment (prefers Python 3.12, falls back to whatever python is on PATH)
if not exist "%PY%" (
  echo Creating virtual environment in %VENV% ...
  py -3.12 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"
  if not exist "%PY%" (
    echo Could not create the virtual environment. Install Python 3.12 from python.org and try again.
    exit /b 1
  )
)

rem 2. Packages (only installs when an import is missing)
"%PY%" -c "import numpy, scipy, sklearn, sounddevice, fastapi, uvicorn, serial, zfec, httpx, dotenv, pytest, soundfile, onnxruntime" 2>nul
if errorlevel 1 (
  echo Installing packages ...
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install %PACKAGES%
  if errorlevel 1 (
    echo Package install failed, see the errors above.
    exit /b 1
  )
)

rem 3. .env with optional keys
if not exist "%ROOT%\.env" (
  copy "%ROOT%\.env.example" "%ROOT%\.env" >nul
  echo Created .env from .env.example; add API keys there if you have them.
)

rem 4. Kp forecast model (needs internet; the app still runs without it)
if not exist "%~dp0data\kp_model.pkl" (
  echo Training the Kp forecast model ^(downloads ~16 MB^) ...
  "%PY%" -m microaware.forecast train
  if errorlevel 1 echo Forecast training failed; continuing without it.
)

echo Dashboard: http://localhost:%PORT%    Earth: http://localhost:%PORT%/earth
"%VENV%\Scripts\uvicorn.exe" --factory microaware.api:build --host 127.0.0.1 --port %PORT% %*
