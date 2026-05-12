@echo off
cd /d "%~dp0"
echo Installing required Python packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Python command failed. Trying py launcher...
    py -m pip install -r requirements.txt
)
echo.
echo Starting bot...
python main.py
if errorlevel 1 (
    echo.
    echo Python command failed. Trying py launcher...
    py main.py
)
pause
