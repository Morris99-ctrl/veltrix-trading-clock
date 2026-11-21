@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Check your Python and internet connection.
    pause
    exit /b 1
)
python main.py
if errorlevel 1 pause
