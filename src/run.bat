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

if exist "%PY%" goto have_venv
echo Setting up MicroAware for the first time.
call :find_python || goto fail
echo Creating .venv with %BASE%
%BASE% -m venv "%VENV%" || goto fail
:have_venv

rem reinstall only when requirements.txt changed since the last install
fc /b "%ROOT%\requirements.txt" "%VENV%\requirements.installed" >nul 2>&1 && goto have_packages
echo Installing packages. The first time takes a few minutes.
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install --timeout 120 -r "%ROOT%\requirements.txt" || goto fail
copy /y "%ROOT%\requirements.txt" "%VENV%\requirements.installed" >nul
:have_packages

if exist "%ROOT%\.env" goto have_env
copy "%ROOT%\.env.example" "%ROOT%\.env" >nul
echo Created .env. Add Gemini and ElevenLabs keys there for AI explanations and voice; everything works without them.
:have_env

if exist "data\kp_model.pkl" goto have_forecast
echo Training the space-weather forecaster. Downloads about 16 MB once.
"%PY%" -m microaware.forecast train || echo Forecaster not trained, probably no internet. MicroAware runs without it; run.bat tries again next time.
:have_forecast

echo.
echo Dashboard: http://localhost:%PORT%    Earth: http://localhost:%PORT%/earth
"%PY%" -m uvicorn --factory microaware.api:build --host 127.0.0.1 --port %PORT% %*
exit /b %errorlevel%

:find_python
rem zfec has no Windows build for Python 3.14 yet, so prefer 3.12 and stay at 3.10-3.13
for %%C in ("py -3.12" "py -3.13" "py -3.11" "py -3.10" "python") do (
  %%~C -c "import sys; sys.exit(not (3, 10) <= sys.version_info[:2] <= (3, 13))" >nul 2>&1 && (
    set "BASE=%%~C"
    exit /b 0
  )
)
echo Python 3.10 to 3.13 is needed. Install 3.12 with:  winget install Python.Python.3.12
echo or from https://www.python.org/downloads/ - tick "Add python.exe to PATH". Then run this again.
exit /b 1

:fail
echo.
echo Setup failed; see the messages above. Fix the problem and run run.bat again.
pause
exit /b 1
