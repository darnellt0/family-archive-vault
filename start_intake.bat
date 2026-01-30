@echo off
title Family Archive - Intake Web App
echo.
echo ========================================
echo   FAMILY ARCHIVE VAULT - INTAKE
echo ========================================
echo.

cd /d %~dp0
call .venv\Scripts\activate

echo Starting intake web app on http://localhost:8000
echo.
echo Press Ctrl+C to stop
echo.

python -m intake_webapp.main

pause
