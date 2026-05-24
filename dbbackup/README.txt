METO Bulk Video Downloader — dbbackup/
======================================

Bundled empty database
----------------------
bulk_video.db
  Pre-initialized SQLite file (schema/migrations applied, no videos).
  install.bat copies it to the project root on first setup if no database exists yet.
  You can also copy it manually next to app.py.

MySQL / PostgreSQL users can ignore this folder — use your own DB backup tools.

Download backup (from the app)
------------------------------
Settings → Database Backup → Download ZIP

Save a copy here
----------------
Settings → Database Backup → Save copy to dbbackup/

Restore from your own backup
----------------------------
Option A — automatic (install.bat):
  1. Put your backup zip here as restore.zip
  2. Run install.bat
  3. install.bat restores bulk_video.db to the project root

Option B — manual:
  1. Extract bulk_video.db from your zip
  2. Place it in the project root (next to app.py)
  3. Run start.bat

Notes
-----
- User backup *.zip files in this folder are not committed to git
- restore.zip always overwrites the existing database when install.bat runs
- Video files stay in the videos/ folder; back those up separately if needed
