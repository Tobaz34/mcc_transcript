@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

title MCC - TRANSCRIPT - Installation

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "VENV_DIR=%APP_DIR%\venv"
set "MODELS_DIR=%APP_DIR%\models"
set "LOGS_DIR=%APP_DIR%\logs"
set "OUTPUT_DIR=%APP_DIR%\output"
set "PYTHON_CMD="
set "ERRORS_COUNT=0"

echo.
echo  ============================================================
echo       MCC - TRANSCRIPT - INSTALLATION AUTOMATIQUE
echo  ============================================================
echo.
echo  Ce programme va installer tout ce qui est necessaire :
echo    1. Verifier Python
echo    2. Creer l environnement virtuel
echo    3. Installer les dependances Python
echo    4. Verifier Ollama
echo    5. Telecharger le modele Mistral
echo    6. Telecharger le modele Whisper
echo    7. Creer les raccourcis
echo.
echo  Connexion internet requise.
echo  Duree estimee : 15 a 30 minutes.
echo.
pause

echo.
echo  ============================================================
echo  VERIFICATION DU SYSTEME
echo  ============================================================
echo.

if not exist "%APP_DIR%\requirements.txt" (
    echo  [ERREUR] requirements.txt manquant. Installation incomplete.
    pause
    exit /b 1
)
echo  [OK] Fichiers du projet presents.

echo test > "%APP_DIR%\_test_write.tmp" 2>nul
if not exist "%APP_DIR%\_test_write.tmp" (
    echo  [ERREUR] Impossible d ecrire dans le dossier.
    echo  Lancez en tant qu administrateur ou deplacez le dossier.
    pause
    exit /b 1
)
del "%APP_DIR%\_test_write.tmp" >nul 2>&1
echo  [OK] Droits d ecriture OK.

echo  [...] Verification internet...
ping -n 1 -w 3000 pypi.org >nul 2>&1
if !errorlevel! neq 0 (
    ping -n 1 -w 3000 google.com >nul 2>&1
    if !errorlevel! neq 0 (
        echo  [ERREUR] Pas de connexion internet.
        pause
        exit /b 1
    )
)
echo  [OK] Connexion internet OK.

echo.
echo  ============================================================
echo  ETAPE 1/7 : Recherche de Python
echo  ============================================================
echo.

echo  [...] Recherche de Python...

py -3 --version >nul 2>&1
if !errorlevel!==0 (
    for /f "tokens=*" %%i in ('py -3 --version 2^>^&1') do set "PY_VER=%%i"
    echo !PY_VER! | findstr /c:"Python 3" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON_CMD=py -3"
        echo  [OK] Python trouve via py launcher : !PY_VER!
        goto :python_ok
    )
)

python --version >nul 2>&1
if !errorlevel!==0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set "PY_VER=%%i"
    echo !PY_VER! | findstr /c:"Python 3" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON_CMD=python"
        echo  [OK] Python trouve : !PY_VER!
        goto :python_ok
    )
)

python3 --version >nul 2>&1
if !errorlevel!==0 (
    for /f "tokens=*" %%i in ('python3 --version 2^>^&1') do set "PY_VER=%%i"
    echo !PY_VER! | findstr /c:"Python 3" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON_CMD=python3"
        echo  [OK] Python trouve : !PY_VER!
        goto :python_ok
    )
)

echo.
echo  [ATTENTION] Python non trouve.
echo.
where winget >nul 2>&1
if !errorlevel!==0 (
    echo  [...] Installation de Python 3.11 via winget...
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    if !errorlevel!==0 (
        echo.
        echo  [OK] Python installe.
        echo.
        echo  *** FERMEZ cette fenetre et RELANCEZ INSTALLER.bat ***
        echo  Windows doit rafraichir le PATH.
        echo.
        pause
        exit /b 0
    )
)

echo.
echo  [ERREUR] Python introuvable et installation auto echouee.
echo.
echo  Installez Python manuellement :
echo    1. Allez sur https://www.python.org/downloads/
echo    2. Telechargez Python 3.11+
echo    3. COCHEZ "Add Python to PATH" avant d installer
echo    4. Relancez INSTALLER.bat
echo.
pause
exit /b 1

:python_ok

echo.
echo  ============================================================
echo  ETAPE 2/7 : Environnement virtuel
echo  ============================================================
echo.

set "VENV_OK=0"
if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python.exe" -c "print(1)" >nul 2>&1
    if !errorlevel!==0 set "VENV_OK=1"
)

if !VENV_OK!==1 (
    echo  [OK] Environnement virtuel existant et fonctionnel.
) else (
    if exist "%VENV_DIR%" (
        echo  [...] Suppression du venv corrompu...
        rmdir /s /q "%VENV_DIR%" >nul 2>&1
    )
    echo  [...] Creation de l environnement virtuel...
    !PYTHON_CMD! -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo  [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
    if not exist "%VENV_DIR%\Scripts\python.exe" (
        echo  [ERREUR] Le venv n a pas ete cree correctement.
        pause
        exit /b 1
    )
    echo  [OK] Environnement virtuel cree.
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PIP=%VENV_DIR%\Scripts\pip.exe"

echo  [...] Mise a jour de pip...
"%PYTHON%" -m pip install --upgrade pip >nul 2>&1
echo  [OK] Pip pret.

echo.
echo  ============================================================
echo  ETAPE 3/7 : Dependances Python
echo  ============================================================
echo.

echo  [...] Installation des packages (5 a 10 minutes)...
echo.
"%PYTHON%" -m pip install -r "%APP_DIR%\requirements.txt"
if !errorlevel! neq 0 (
    echo.
    echo  [...] Nouvel essai...
    timeout /t 5 /nobreak >nul
    "%PYTHON%" -m pip install --no-cache-dir -r "%APP_DIR%\requirements.txt"
    if !errorlevel! neq 0 (
        echo.
        echo  [ERREUR] Installation des dependances echouee.
        echo  Verifiez internet / antivirus / proxy.
        pause
        exit /b 1
    )
)
echo.
echo  [OK] Dependances installees.

echo.
echo  ============================================================
echo  ETAPE 4/7 : Ollama
echo  ============================================================
echo.

set "OLLAMA_OK=0"
where ollama >nul 2>&1
if !errorlevel!==0 set "OLLAMA_OK=1"

if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
    set "OLLAMA_OK=1"
)

if !OLLAMA_OK!==1 (
    echo  [OK] Ollama installe.
    goto :ollama_ready
)

echo  [...] Ollama non trouve. Tentative d installation...
where winget >nul 2>&1
if !errorlevel!==0 (
    winget install Ollama.Ollama --accept-package-agreements --accept-source-agreements
    if !errorlevel!==0 (
        echo  [OK] Ollama installe.
        set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
        goto :ollama_ready
    )
)

echo.
echo  [ATTENTION] Ollama non installe.
echo  Installez-le depuis : https://ollama.com/download
echo  Le compte rendu ne fonctionnera pas sans Ollama.
echo.
set /a ERRORS_COUNT+=1
pause
goto :skip_ollama

:ollama_ready

echo  [...] Demarrage du service Ollama...
ollama list >nul 2>&1
if !errorlevel! neq 0 (
    start "" /min ollama serve
    timeout /t 8 /nobreak >nul
)

echo.
echo  ============================================================
echo  ETAPE 5/7 : Modele Mistral
echo  ============================================================
echo.

ollama list 2>nul | findstr /i "mistral" >nul 2>&1
if !errorlevel!==0 (
    echo  [OK] Mistral deja installe.
) else (
    echo  [...] Telechargement de Mistral 4 Go - 10 a 20 min...
    echo  NE FERMEZ PAS cette fenetre.
    echo.
    ollama pull mistral
    if !errorlevel! neq 0 (
        echo  [ATTENTION] Echec. Plus tard : ollama pull mistral
        set /a ERRORS_COUNT+=1
    ) else (
        echo  [OK] Mistral telecharge.
    )
)

:skip_ollama

echo.
echo  ============================================================
echo  ETAPE 6/7 : Modele Whisper
echo  ============================================================
echo.

if not exist "%APP_DIR%\setup_models.py" (
    echo  [ATTENTION] setup_models.py manquant.
    set /a ERRORS_COUNT+=1
    goto :skip_whisper
)

echo  [...] Telechargement du modele Whisper (5-20 min)...
echo  NE FERMEZ PAS cette fenetre.
echo.
"%PYTHON%" "%APP_DIR%\setup_models.py"
if !errorlevel! neq 0 (
    echo  [ATTENTION] Echec. Relancez setup_models.py plus tard.
    set /a ERRORS_COUNT+=1
) else (
    echo  [OK] Whisper configure.
)

:skip_whisper

echo.
echo  ============================================================
echo  ETAPE 7/7 : Raccourcis
echo  ============================================================
echo.

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"
if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

echo  [OK] Dossiers crees.

if exist "%APP_DIR%\creer_raccourci.py" (
    echo  [...] Creation du raccourci bureau...
    "%PYTHON%" "%APP_DIR%\creer_raccourci.py"
    if !errorlevel!==0 (
        echo  [OK] Raccourci cree.
    ) else (
        echo  Raccourci non cree. Utilisez LANCER.bat directement.
    )
)

echo.
echo  ============================================================
if !ERRORS_COUNT!==0 (
    echo       INSTALLATION TERMINEE AVEC SUCCES !
) else (
    echo       INSTALLATION TERMINEE - !ERRORS_COUNT! avertissement(s)
)
echo.
echo  Pour lancer : double-cliquez sur LANCER.bat
echo  ============================================================
echo.
pause
