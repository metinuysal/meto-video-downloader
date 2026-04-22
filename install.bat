@echo off
echo =========================================
echo   Meto Bulk Video Downloader - Install
echo =========================================
echo.

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "PY="

:: ─── Python ──────────────────────────────────────────────────────────────────
echo [1/4] Checking Python...
call :find_python
if errorlevel 1 (
    echo   Python not found. Attempting automatic installation via winget...
    call :install_python
    call :find_python
    if errorlevel 1 (
        echo.
        echo ERROR: Python installation failed.
        echo Please install Python 3.10+ manually and rerun install.bat:
        echo   https://www.python.org/downloads/
        pause
        exit /b 1
    )
)
echo   Found: %PY%
%PY% --version

:: ─── Virtual environment ─────────────────────────────────────────────────────
echo.
echo [2/4] Setting up Python virtual environment...
if not exist "%VENV_PY%" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo   Created .venv
) else (
    echo   Already exists, skipping.
)

echo   Upgrading pip / setuptools / wheel...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel --quiet
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    pause
    exit /b 1
)

echo   Installing Python dependencies...
"%VENV_PY%" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies.
    pause
    exit /b 1
)

"%VENV_PY%" -c "import flask, yt_dlp" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Dependency verification failed.
    pause
    exit /b 1
)
echo   Python dependencies OK.

:: ─── FFmpeg ──────────────────────────────────────────────────────────────────
echo.
echo [3/4] Checking FFmpeg...
if exist "%ROOT%tools\ffmpeg\bin\ffmpeg.exe" (
    echo   Found in tools\ffmpeg (bundled).
) else (
    where ffmpeg >nul 2>nul
    if not errorlevel 1 (
        echo   Found on system PATH.
    ) else (
        echo   FFmpeg not found. Installing via winget...
        where winget >nul 2>nul
        if errorlevel 1 (
            echo   WARNING: winget not available. Install FFmpeg manually and add it to PATH.
            echo   https://ffmpeg.org/download.html
        ) else (
            winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements
            if errorlevel 1 (
                echo   WARNING: FFmpeg install via winget failed. Please install manually.
                echo   https://ffmpeg.org/download.html
            ) else (
                echo   FFmpeg installed successfully.
            )
        )
    )
)

:: ─── Node.js (required by yt-dlp for YouTube signature solving) ───────────────
echo.
echo [4/4] Checking Node.js (required for YouTube downloads)...
where node >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('node --version 2^>nul') do echo   Found: %%v
) else (
    echo   Node.js not found. Installing via winget...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo   WARNING: winget not available. Install Node.js 20+ manually:
        echo   https://nodejs.org/
    ) else (
        winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo   WARNING: Node.js install via winget failed. Please install manually:
            echo   https://nodejs.org/
        ) else (
            echo   Node.js installed successfully.
            echo   NOTE: You may need to restart your terminal for Node.js to be on PATH.
        )
    )
)

:: ─── Done ────────────────────────────────────────────────────────────────────
echo.
echo =========================================
echo   Installation complete!
echo   Run start.bat to launch the app.
echo =========================================
echo.
pause
exit /b 0


:: ─── Subroutines ─────────────────────────────────────────────────────────────

:find_python
where py >nul 2>nul
if not errorlevel 1 (
    for %%v in (3.13 3.12 3.11 3.10) do (
        py -%%v --version >nul 2>nul
        if not errorlevel 1 (
            set "PY=py -%%v"
            exit /b 0
        )
    )
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        set "PY=py -3"
        exit /b 0
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
    exit /b 0
)

for %%v in (313 312 311 310) do (
    if exist "%LocalAppData%\Programs\Python\Python%%v\python.exe" (
        set "PY=%LocalAppData%\Programs\Python\Python%%v\python.exe"
        exit /b 0
    )
)
exit /b 1


:install_python
where winget >nul 2>nul
if not errorlevel 1 (
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    call :find_python
    if not errorlevel 1 exit /b 0
)

echo   Falling back to direct Python installer download...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $tmp = Join-Path $env:TEMP 'python-installer.exe'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $tmp; Start-Process -FilePath $tmp -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1' -Wait; Remove-Item $tmp -Force"
if errorlevel 1 (
    echo   Python installer fallback failed.
    exit /b 1
)
exit /b 0
