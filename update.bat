@echo off
echo ================================
echo  Meto Bulk Video Downloader - Update
echo ================================
echo.

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

echo Checking FFmpeg...
if exist "%ROOT%tools\ffmpeg\bin\ffmpeg.exe" (
    set "PATH=%ROOT%tools\ffmpeg\bin;%PATH%"
) else (
    where ffmpeg >nul 2>nul
    if errorlevel 1 (
        echo FFmpeg not found. Run install.bat to set it up.
        pause
        exit /b 1
    )
)

echo.
echo Updating yt-dlp...
if exist "%VENV_PY%" (
    "%VENV_PY%" -m pip install --upgrade yt-dlp
) else (
    python -m pip install --upgrade yt-dlp
)
if errorlevel 1 (
    echo ERROR: Failed to update yt-dlp.
    pause
    exit /b 1
)

echo.
echo Updating Flask and other dependencies...
if exist "%VENV_PY%" (
    "%VENV_PY%" -m pip install --upgrade -r requirements.txt
) else (
    python -m pip install --upgrade -r requirements.txt
)
if errorlevel 1 (
    echo ERROR: Failed to update dependencies.
    pause
    exit /b 1
)

echo.
echo ================================
echo  Update complete!
echo ================================
pause
