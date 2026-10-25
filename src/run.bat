@echo off
rem Starts MicroAware on Windows. Same options as run.sh, set first, e.g.:
rem   set MICROAWARE_SOURCE=synth   (simulated fan instead of the mic)
rem   set MICROAWARE_LINK=sim       (simulated radio link)
rem   set PORT=8001
setlocal
cd /d "%~dp0"
if not defined PORT set PORT=8000
set "UVICORN=%~dp0..\.venv\Scripts\uvicorn.exe"
if not exist "%UVICORN%" (
  echo No virtual environment found at %~dp0..\.venv
  echo Create it from the repo folder first:
  echo   py -3.12 -m venv .venv
  echo   .venv\Scripts\pip install numpy scipy scikit-learn sounddevice fastapi "uvicorn[standard]" pyserial zfec httpx python-dotenv pytest soundfile onnxruntime
  exit /b 1
)
echo Dashboard: http://localhost:%PORT%    Earth: http://localhost:%PORT%/earth
"%UVICORN%" --factory microaware.api:build --host 127.0.0.1 --port %PORT% %*
