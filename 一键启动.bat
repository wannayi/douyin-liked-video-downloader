@echo off
setlocal EnableExtensions
chcp 65001 >nul

pushd "%~dp0" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Cannot open the project directory.
    goto :error
)
if not exist "%~dp0app.py" (
    echo ERROR: app.py was not found. Please keep this BAT file in the project folder.
    goto :error
)
if not exist "%~dp0data" mkdir "%~dp0data" >nul 2>&1
set "STARTUP_LOG=%~dp0data\startup.log"

title Douyin Liked Video Downloader
echo ========================================
echo       Douyin Liked Video Downloader
echo ========================================
echo.

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "PLAYWRIGHT_MARKER=%~dp0.playwright-ready"

if not exist "%VENV_PYTHON%" (
    echo [1/5] Creating Python virtual environment...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%~dp0.venv"
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            echo ERROR: Python 3.10 or newer was not found.
            goto :error
        )
        python -m venv "%~dp0.venv"
    )
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        goto :error
    )
) else (
    echo [1/5] Python virtual environment is ready.
)

"%VENV_PYTHON%" -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo [2/5] Installing Python dependencies...
    "%VENV_PYTHON%" -m pip install -r "%~dp0requirements.txt" 2>>"%STARTUP_LOG%"
    if errorlevel 1 (
        echo ERROR: Dependency installation failed. Check your network and retry.
        goto :error
    )
) else (
    echo [2/5] Python dependencies are ready.
)

if not exist "%PLAYWRIGHT_MARKER%" (
    echo [3/5] Installing Playwright Chromium...
    "%VENV_PYTHON%" -m playwright install chromium 2>>"%STARTUP_LOG%"
    if errorlevel 1 (
        echo ERROR: Playwright browser installation failed.
        goto :error
    )
    >"%PLAYWRIGHT_MARKER%" echo ready
) else (
    echo [3/5] Playwright browser is ready.
)

if not exist "%~dp0config.json" (
    echo [4/5] Creating config.json...
    copy /Y "%~dp0config.example.json" "%~dp0config.json" >nul
    if errorlevel 1 (
        echo ERROR: Failed to create config.json.
        goto :error
    )
) else (
    echo [4/5] config.json already exists.
)

echo [5/5] Installing or updating the daily 05:00 task...
"%VENV_PYTHON%" "%~dp0app.py" install-task --config "%~dp0config.json" 2>>"%STARTUP_LOG%"
if errorlevel 1 (
    echo WARNING: The scheduled task could not be installed. The current run will continue.
) else (
    echo The daily 05:00 task is ready.
)

if not exist "%~dp0data\login.success" (
    echo.
    echo First run: a Douyin login window will open.
    echo Complete the login, then return here and press Enter once.
    "%VENV_PYTHON%" "%~dp0app.py" login --config "%~dp0config.json" 2>>"%STARTUP_LOG%"
    if errorlevel 1 (
        echo ERROR: Login was not completed.
        goto :error
    )
)

echo.
echo Scanning the liked list and downloading new videos...
"%VENV_PYTHON%" "%~dp0app.py" run --config "%~dp0config.json" 2>>"%STARTUP_LOG%"
if errorlevel 2 (
    echo.
    echo The login may have expired. Opening the login window again.
    "%VENV_PYTHON%" "%~dp0app.py" login --config "%~dp0config.json" 2>>"%STARTUP_LOG%"
    if errorlevel 1 goto :error
    "%VENV_PYTHON%" "%~dp0app.py" run --config "%~dp0config.json" 2>>"%STARTUP_LOG%"
)
if errorlevel 1 goto :error

echo.
echo Done. Videos: %~dp0downloads
echo Log: %~dp0data\run.log
pause
exit /b 0

:error
echo.
echo Startup failed. Check the messages above.
echo Detailed error output: %STARTUP_LOG%
echo This window will stay open. Type exit to close it.
cmd /k
exit /b 1
