@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================================
echo   VELTRIX TRADING CLOCK - WINDOWS DESKTOP INSTALLER
echo ================================================================
echo.
echo This one-time setup builds a standalone Windows app, installs it
echo under your Windows user profile, and creates a desktop shortcut.
echo VS Code is not required. Python is needed only for this build step.
echo.

set "PY_LAUNCHER=python"
where py >nul 2>&1
if not errorlevel 1 set "PY_LAUNCHER=py -3"
%PY_LAUNCHER% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.10 or newer was not found.
    echo Install 64-bit Python from https://www.python.org/downloads/windows/
    echo Enable the Python launcher or Add Python to PATH, then run this file again.
    pause
    exit /b 1
)

%PY_LAUNCHER% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo ERROR: Veltrix requires Python 3.10 or newer to build.
    pause
    exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
    echo Creating an isolated build environment...
    %PY_LAUNCHER% -m venv .venv-build
    if errorlevel 1 goto :failed
)

set "BUILD_PY=%CD%\.venv-build\Scripts\python.exe"
echo.
echo If you have an existing Veltrix project or AppData folder, enter its full path now.
echo This lets the installer migrate your settings, market/calendar caches, old OHLC cache, Regime datasets, focus history and alarm audio.
set "MIGRATION_SOURCE="
set /p "MIGRATION_SOURCE=Existing Veltrix project/AppData folder (press Enter to skip): "
if not defined MIGRATION_SOURCE set "MIGRATION_SOURCE=%CD%"
set "MIGRATION_SOURCE=%MIGRATION_SOURCE:"=%"
if not exist "%MIGRATION_SOURCE%\main.py" if not exist "%MIGRATION_SOURCE%\config.json" (
    echo ERROR: The selected folder must contain main.py or config.json.
    echo You may select your old project folder or %%LOCALAPPDATA%%\Veltrix Trading Clock.
    pause
    exit /b 1
)

echo Installing application and packaging dependencies...
"%BUILD_PY%" -m pip install --require-hashes -r requirements-build.lock.txt
if errorlevel 1 goto :failed

echo Installing optional MP3 playback support...
"%BUILD_PY%" -m pip install --require-hashes --only-binary=:all: --retries 1 --timeout 30 -r requirements-audio.lock.txt
if errorlevel 1 echo WARNING: pygame could not be installed. Veltrix will use the system-bell fallback.

echo.
echo Building the standalone Veltrix application...
"%BUILD_PY%" -m PyInstaller --clean --noconfirm veltrix_windows.spec
if errorlevel 1 goto :failed

if not exist "dist\Veltrix Trading Clock\VeltrixTradingClock.exe" (
    echo ERROR: The Windows executable was not created.
    goto :failed
)

echo.
echo Installing Veltrix and creating shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\installer\Install-Veltrix.ps1" -SourceDir "%CD%" -MigrationSourceDir "%MIGRATION_SOURCE%" -BuiltAppDir "%CD%\dist\Veltrix Trading Clock"
if errorlevel 1 goto :failed

echo.
echo ================================================================
echo   INSTALLATION COMPLETE
echo ================================================================
echo Double-click the Veltrix Trading Clock icon on your desktop.
echo You can close this window. VS Code is not needed to run Veltrix.
echo.
pause
exit /b 0

:failed
echo.
echo BUILD OR INSTALL FAILED. Review the error shown above.
pause
exit /b 1
