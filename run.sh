#!/bin/bash

# Team Portal - Entwicklungs-Startskript

echo "🚀 Team Portal wird gestartet..."

# Prüfe ob Virtual Environment existiert
if [ ! -d "venv" ]; then
    echo "❌ Virtual Environment nicht gefunden!"
    echo "Erstelle Virtual Environment..."
    python3 -m venv venv
fi

# Aktiviere Virtual Environment
echo "📦 Aktiviere Virtual Environment..."
source venv/bin/activate

# Prüfe ob .env existiert
if [ ! -f ".env" ]; then
    echo "⚠️  .env nicht gefunden!"
    echo "Kopiere env.example zu .env..."
    cp env.example .env
    echo "✅ Bitte .env bearbeiten und Konfiguration anpassen!"
    echo "Dann 'run.sh' erneut ausführen."
    exit 1
fi

# Installiere Dependencies
echo "📥 Installiere Dependencies..."
pip install -q -r requirements.txt

# Erstelle Upload-Verzeichnisse
echo "📁 Erstelle Upload-Verzeichnisse..."
mkdir -p uploads/{files,chat,manuals,profile_pics}

# Starte Anwendung
echo "✨ Starte Team Portal..."
echo "🌐 Öffne http://localhost:5000 in deinem Browser"
echo ""
python app.py



