@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title MCC - TRANSCRIPT - Mise a jour

echo.
echo  ============================================================
echo       MCC - TRANSCRIPT - MISE A JOUR
echo  ============================================================
echo.
echo  Ce programme va verifier si une nouvelle version est
echo  disponible sur GitHub et la telecharger si necessaire.
echo.
echo  Vos donnees (enregistrements, modeles, parametres)
echo  ne seront PAS modifiees.
echo.

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "PYTHON=%APP_DIR%\venv\Scripts\python.exe"

:: Verifier que le venv existe
if not exist "%PYTHON%" (
    echo  [ERREUR] L'application n'est pas installee correctement.
    echo  Lancez d'abord INSTALLER.bat
    echo.
    pause
    exit /b 1
)

:: Verifier la connexion internet
echo  [...] Verification de la connexion internet...
ping -n 1 -w 3000 github.com >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERREUR] Pas de connexion internet.
    echo  La mise a jour necessite une connexion internet.
    echo.
    pause
    exit /b 1
)
echo  [OK] Connexion internet disponible.
echo.

:: Lancer le script de mise a jour
"%PYTHON%" "%APP_DIR%\updater.py"

echo.
pause
