@echo off
setlocal

REM Build a Windows .exe for the maritime route planner.
REM Run this script from the repository root on a Windows machine.

where py >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python launcher 'py' was not found. Please install Python 3 for Windows and add it to PATH.
    exit /b 1
)

if not exist .venv (
    echo [INFO] Creating virtual environment...
    py -m venv .venv
)

call .venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to activate virtual environment.
    exit /b 1
)

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 exit /b 1

echo [INFO] Installing build dependencies...
python -m pip install -r requirements-windows.txt
if %ERRORLEVEL% NEQ 0 exit /b 1

echo [INFO] Building Maritime Route Planner executable...
pyinstaller --noconfirm maritime_route_planner.spec
if %ERRORLEVEL% NEQ 0 exit /b 1

echo.
echo [SUCCESS] Build completed.
echo [OUTPUT] dist\MaritimeRoutePlanner\MaritimeRoutePlanner.exe
endlocal
