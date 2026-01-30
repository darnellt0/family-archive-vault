@echo off
title Family Archive - Curator Dashboard
echo.
echo ========================================
echo   FAMILY ARCHIVE VAULT - CURATOR
echo ========================================
echo.

cd /d %~dp0
call .venv\Scripts\activate

echo Starting curator dashboard...
echo Will open in your browser shortly
echo.
echo Press Ctrl+C to stop
echo.

streamlit run curator/main.py

pause
