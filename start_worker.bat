@echo off
title Family Archive - Worker
echo.
echo ========================================
echo   FAMILY ARCHIVE VAULT - WORKER
echo ========================================
echo.

cd /d %~dp0
call .venv\Scripts\activate

echo Starting worker...
echo Processing files from Google Drive
echo.
echo Press Ctrl+C to stop
echo.

python -m worker.main

pause
