@echo off
echo ================================
echo  Meto Bulk Video Downloader - Install
echo ================================
echo.

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "PY="

call :find_python
if errorlevel 1 (
    echo Python not found. Attempting automatic installation...
    call :install_python
    call :find_python
    if errorlevel 1 (
        echo ERROR: Python installation failed.
        echo Install Python 3.10+ and rerun install.bat:
        echo https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

echo Using Python: %PY%
%PY% --version

if not exist "%VENV_PY%" (
    echo.
    echo Creating virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo Upgrading pip/setuptools/wheel...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip/setuptools/wheel.
    pause
    exit /b 1
)

echo Installing dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Verifying installed packages...
"%VENV_PY%" -c "import flask, yt_dlp" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Dependency verification failed.
    pause
    exit /b 1
)

echo.
echo Checking FFmpeg...
if exist "%ROOT%tools\ffmpeg\bin\ffmpeg.exe" (
    echo FFmpeg already installed in tools\ffmpeg.
) else (
    where ffmpeg >nul 2>nul
    if errorlevel 1 (
        echo FFmpeg not found. Trying winget installation...
        where winget >nul 2>nul
        if errorlevel 1 (
            echo ERROR: winget is not available. Install FFmpeg manually and ensure it is on PATH.
            pause
            exit /b 1
        )
        winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo ERROR: Failed to install FFmpeg via winget.
            pause
            exit /b 1
        )
    )
)

echo.
echo ================================
echo  Installation complete!
echo  Run start.bat to launch the app.
echo ================================
pause

exit /b 0

:find_python
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 --version >nul 2>nul
    if not errorlevel 1 (
        set "PY=py -3.12"
        exit /b 0
    )
    py -3.11 --version >nul 2>nul
    if not errorlevel 1 (
        set "PY=py -3.11"
        exit /b 0
    )
    py -3.10 --version >nul 2>nul
    if not errorlevel 1 (
        set "PY=py -3.10"
        exit /b 0
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

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
    exit /b 0
)
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
    exit /b 0
)
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
    set "PY=%LocalAppData%\Programs\Python\Python310\python.exe"
    exit /b 0
)
exit /b 1

:install_python
echo Attempting Python installation via winget...
where winget >nul 2>nul
if not errorlevel 1 (
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    call :find_python
    if not errorlevel 1 exit /b 0
)

echo Falling back to official Python installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $tmp = Join-Path $env:TEMP 'python-installer.exe'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $tmp; Start-Process -FilePath $tmp -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1' -Wait; Remove-Item $tmp -Force"
if errorlevel 1 (
    echo Python installer fallback failed.
    exit /b 1
)

exit /b 0
