@echo off
chcp 65001 >nul 2>&1
title MCC - TRANSCRIPT
cd /d "%~dp0"

:: Demarrer Ollama si pas deja lance
tasklist /fi "imagename eq ollama.exe" 2>nul | findstr /i "ollama" >nul
if %errorlevel% neq 0 (
    start "" /min ollama serve
    timeout /t 3 /nobreak >nul
)

:: Lancer l'application
"%~dp0venv\Scripts\python.exe" "%~dp0main.py"

if %errorlevel% neq 0 (
    echo.
    echo Une erreur est survenue. Appuyez sur une touche pour fermer.
    pause
)
