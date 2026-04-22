@echo off
echo ================================
echo  Meto Bulk Video Downloader
echo ================================
echo.
echo Starting server...
echo Open http://localhost:5000 in your browser
echo.
echo Press Ctrl+C to stop the server
echo.

set BULK_VIDEO_HOST=127.0.0.1
set BULK_VIDEO_PORT=5000
set BULK_VIDEO_DEBUG=1

set "ROOT=%~dp0"
if exist "%ROOT%tools\ffmpeg\bin\ffmpeg.exe" (
    set "PATH=%ROOT%tools\ffmpeg\bin;%PATH%"
)

if exist "%ROOT%.venv\Scripts\python.exe" (
    "%ROOT%.venv\Scripts\python.exe" app.py
) else (
    python app.py
)
pause
