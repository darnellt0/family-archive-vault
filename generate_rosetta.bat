@echo off
title Family Archive - Rosetta Stone Generator
echo.
echo ========================================
echo   FAMILY ARCHIVE VAULT - ROSETTA
echo ========================================
echo.

cd /d %~dp0
call .venv\Scripts\activate

echo Generating static Rosetta Stone site...
echo.

python -m rosetta.main

echo.
echo ========================================
echo   GENERATION COMPLETE
echo ========================================
echo.

pause
