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
echo Starting dashboard...
echo Open http://127.0.0.1:5000 in your browser.
python dashboard.py
if errorlevel 1 (
    echo.
    echo Python command failed. Trying py launcher...
    py dashboard.py
)
pause
