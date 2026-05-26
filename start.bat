@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title PDF OCR Webapp

echo =====================================================
echo  PDF ^> Markdown OCR  —  powered by Ollama glm-ocr
echo =====================================================
echo.

:: --------------------------------------------------
:: 0. Ollama: assicurati che l'eseguibile sia disponibile
::    - aggiunge temporaneamente la cartella a PATH per questa sessione
::    - aggiunge persistentemente (utente) la cartella a PATH se mancante
::    - avvia `ollama serve` in background se non è già in esecuzione
:: --------------------------------------------------
set "OLLAMA_DIR=%LOCALAPPDATA%\Programs\Ollama"
if exist "%OLLAMA_DIR%\ollama.exe" (
    echo [*] Trovato Ollama in %OLLAMA_DIR%
    call :_ensure_ollama_in_path
    call :_ensure_ollama_in_userpath

    :: Avvia ollama serve se non già in esecuzione
    tasklist /FI "IMAGENAME eq ollama.exe" | find /I "ollama.exe" >nul 2>&1
    if errorlevel 1 (
        echo [*] Avvio Ollama server in background...
        start "Ollama" /MIN "%OLLAMA_DIR%\ollama.exe" serve
        timeout /t 2 /nobreak >nul
    ) else (
        echo [*] Ollama sembra già in esecuzione.
    )
) else (
    echo [WARN] Ollama non trovato in %OLLAMA_DIR%. Se desideri posso provare a installarlo.
)

:: --------------------------------------------------
:: 1. Verifica Python
:: --------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Python non trovato. Installalo da https://python.org
    pause & exit /b 1
)

:: --------------------------------------------------
:: 2. Crea venv se non esiste
:: --------------------------------------------------
if not exist .venv (
    echo [1/3] Creazione ambiente virtuale Python...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRORE] Impossibile creare il venv.
        pause & exit /b 1
    )
)

:: --------------------------------------------------
:: 3. Installa dipendenze
:: --------------------------------------------------
echo [2/3] Installazione dipendenze...
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q --no-warn-script-location
if errorlevel 1 (
    echo [ERRORE] Installazione dipendenze fallita.
    pause & exit /b 1
)

:: --------------------------------------------------
:: 4. Avvia server Python (uvicorn)
:: --------------------------------------------------
echo [3/3] Avvio server...
echo.
echo  ^> Apri il browser su:  http://localhost:8080
echo  ^> Premi Ctrl+C per fermare il server.
echo.
echo  Lo stato di Ollama puo' essere verificato con:
echo    ollama --version
echo    ollama list
echo    ollama ps
echo.

:: Avvia il server in background e apri il browser
start "Uvicorn Server" /MIN cmd /c "python -m uvicorn app:app --host 0.0.0.0 --port 8080"
timeout /t 3 /nobreak >nul
start "" "http://localhost:8080"

pause

:: --------------------------------------------------
:: Subroutine: assicurati che OLLAMA_DIR sia in PATH di sessione
:: --------------------------------------------------
:_ensure_ollama_in_path
echo !PATH! | findstr /I /C:"%OLLAMA_DIR%" >nul
if errorlevel 1 (
    set "PATH=%OLLAMA_DIR%;!PATH!"
    echo [*] Aggiunta la cartella Ollama a PATH per la sessione corrente
)
goto :eof

:: --------------------------------------------------
:: Subroutine: assicurati che OLLAMA_DIR sia nella PATH utente (registro)
:: --------------------------------------------------
:_ensure_ollama_in_userpath
rem Aggiunge Ollama alla PATH utente usando PowerShell (robusto contro caratteri speciali)
powershell -NoProfile -Command "$p=(Get-ItemProperty -Path 'HKCU:\\Environment' -Name 'PATH' -ErrorAction SilentlyContinue).PATH; if(-not $p){ Set-ItemProperty -Path 'HKCU:\\Environment' -Name 'PATH' -Value '%OLLAMA_DIR%'; Write-Output '[*] PATH utente creata con Ollama' } elseif($p.IndexOf('%OLLAMA_DIR%', [System.StringComparison]::InvariantCultureIgnoreCase) -lt 0){ Set-ItemProperty -Path 'HKCU:\\Environment' -Name 'PATH' -Value ($p + ';' + '%OLLAMA_DIR%'); Write-Output '[*] Aggiunta Ollama alla PATH utente' } else { Write-Output '[*] Ollama gia presente nella PATH utente' }"
goto :eof
