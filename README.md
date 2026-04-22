# ![METO](https://img.shields.io/badge/METO-8B5CF6?style=for-the-badge) Bulk Video Downloader

Local web UI for queuing and downloading videos into per-project folders using `yt-dlp`, with a SQLite library for browsing, tags, and favorites.

## About

**METO Bulk Video Downloader** is a local-first app for organizing downloads into projects, managing a queue, and browsing your library (tags, favorites, and metadata backed by SQLite).

- **Website:** [metinuysal.net](https://metinuysal.net)
- **GitHub:** [github.com/metinuysal](https://github.com/metinuysal)

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Or on Windows:

```bat
start.bat
```

Open http://localhost:5000

## Open-source utilities

This project uses open-source utilities, including:

- `yt-dlp` for media extraction and downloads
- `Flask` for the local web UI and API endpoints
- `SQLite` for lightweight local data storage

## Docker

Build and run:

```bash
docker build -t bulk-video .
```

Run (PowerShell):

```powershell
docker run --rm -p 5000:5000 -v "${PWD}\data:/data" bulk-video
```

Run (bash):

```bash
docker run --rm -p 5000:5000 -v "$(pwd)/data:/data" bulk-video
```

Or with Compose:

```bash
docker compose up --build
```

Data persists in `./data` (SQLite DB + downloaded videos).
For Dokploy (and similar platforms), the container honors `PORT` and will bind to `0.0.0.0`.

## Configuration

Environment variables:


- `SECRET_KEY` (required when `BULK_VIDEO_DEBUG` is false)
- `BULK_VIDEO_HOST` (default `127.0.0.1`)
- `BULK_VIDEO_PORT` (default `5000`)
- `BULK_VIDEO_DEBUG` (default `0`)
- `BULK_VIDEO_DB_PATH` (default `./bulk_video.db`)
- `BULK_VIDEO_VIDEO_DIR` (default `./videos`)

## Notes

- This app is intended to run locally. If you expose it to your network, add authentication and CSRF protection first.
