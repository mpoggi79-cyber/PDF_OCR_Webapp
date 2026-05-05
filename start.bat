@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PDF OCR Webapp

echo =====================================================
echo  PDF ^> Markdown OCR  —  powered by Ollama glm-ocr
echo =====================================================
echo.

:: 1. Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Python non trovato. Installalo da https://python.org
    pause & exit /b 1
)

:: 2. Crea venv se non esiste
if not exist .venv (
    echo [1/3] Creazione ambiente virtuale Python...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRORE] Impossibile creare il venv.
        pause & exit /b 1
    )
)

:: 3. Installa dipendenze
echo [2/3] Installazione dipendenze...
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q --no-warn-script-location
if errorlevel 1 (
    echo [ERRORE] Installazione dipendenze fallita.
    pause & exit /b 1
)

:: 4. Avvia server
echo [3/3] Avvio server...
echo.
echo  ^> Apri il browser su:  http://localhost:8080
echo  ^> Premi Ctrl+C per fermare il server.
echo.
echo  Assicurati che Ollama sia in esecuzione:
echo    ollama serve
echo    ollama pull glm-ocr:latest
echo.

python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload

pause
