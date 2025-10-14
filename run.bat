@echo off
REM Team Portal - Entwicklungs-Startskript (Windows)

echo.
echo ========================================
echo   Team Portal wird gestartet...
echo ========================================
echo.

REM Pruefe ob Virtual Environment existiert
if not exist "venv\" (
    echo Virtual Environment nicht gefunden!
    echo Erstelle Virtual Environment...
    python -m venv venv
)

REM Aktiviere Virtual Environment
echo Aktiviere Virtual Environment...
call venv\Scripts\activate.bat

REM Pruefe ob .env existiert
if not exist ".env" (
    echo.
    echo WARNUNG: .env nicht gefunden!
    echo Kopiere env.example zu .env...
    copy env.example .env
    echo.
    echo Bitte .env bearbeiten und Konfiguration anpassen!
    echo Dann run.bat erneut ausfuehren.
    pause
    exit /b 1
)

REM Installiere Dependencies
echo Installiere Dependencies...
pip install -q -r requirements.txt

REM Erstelle Upload-Verzeichnisse
echo Erstelle Upload-Verzeichnisse...
if not exist "uploads\files" mkdir uploads\files
if not exist "uploads\chat" mkdir uploads\chat
if not exist "uploads\manuals" mkdir uploads\manuals
if not exist "uploads\profile_pics" mkdir uploads\profile_pics

REM Starte Anwendung
echo.
echo ========================================
echo   Team Portal gestartet!
echo   URL: http://localhost:5000
echo ========================================
echo.
python app.py



