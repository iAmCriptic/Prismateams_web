#!/usr/bin/env python3
"""
Deployment-Skript für das Team Portal.
Dieses Skript bereitet die Anwendung für das Deployment vor.
"""

import os
import sys
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_requirements():
    """Überprüft, ob alle erforderlichen Abhängigkeiten installiert sind."""
    print("🔍 Überprüfe Abhängigkeiten...")
    
    try:
        import flask
        import flask_sqlalchemy
        import flask_login
        import flask_mail
        import argon2
        import cryptography
        print("✅ Alle Python-Abhängigkeiten sind installiert")
        return True
    except ImportError as e:
        print(f"❌ Fehlende Abhängigkeit: {e}")
        print("💡 Führen Sie 'pip install -r requirements.txt' aus")
        return False

def check_environment():
    """Überprüft die Umgebungsvariablen."""
    print("\n🌍 Überprüfe Umgebungsvariablen...")
    
    required_vars = ['SECRET_KEY']
    optional_vars = ['DATABASE_URI', 'MAIL_SERVER', 'MAIL_USERNAME', 'MAIL_PASSWORD']
    
    missing_required = []
    for var in required_vars:
        if not os.environ.get(var):
            missing_required.append(var)
    
    if missing_required:
        print(f"❌ Fehlende erforderliche Umgebungsvariablen: {', '.join(missing_required)}")
        return False
    
    print("✅ Erforderliche Umgebungsvariablen sind gesetzt")
    
    missing_optional = []
    for var in optional_vars:
        if not os.environ.get(var):
            missing_optional.append(var)
    
    if missing_optional:
        print(f"⚠️  Fehlende optionale Umgebungsvariablen: {', '.join(missing_optional)}")
        print("💡 Diese sind für erweiterte Funktionen erforderlich")
    
    return True

def init_database():
    """Initialisiert die Datenbank."""
    print("\n🗄️  Initialisiere Datenbank...")
    
    try:
        result = subprocess.run([
            sys.executable, 
            os.path.join(os.path.dirname(__file__), 'init_database.py')
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Datenbank erfolgreich initialisiert")
            return True
        else:
            print(f"❌ Datenbank-Initialisierung fehlgeschlagen:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Fehler bei der Datenbank-Initialisierung: {e}")
        return False

def check_file_permissions():
    """Überprüft Dateiberechtigungen."""
    print("\n📁 Überprüfe Dateiberechtigungen...")
    
    required_dirs = ['uploads', 'uploads/files', 'uploads/chat', 'uploads/manuals', 'uploads/profile_pics']
    
    for directory in required_dirs:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                print(f"✅ Verzeichnis erstellt: {directory}")
            except Exception as e:
                print(f"❌ Kann Verzeichnis nicht erstellen {directory}: {e}")
                return False
        else:
            print(f"✅ Verzeichnis existiert: {directory}")
    
    return True

def run_tests():
    """Führt grundlegende Tests durch."""
    print("\n🧪 Führe grundlegende Tests durch...")
    
    try:
        from app import create_app, db
        from app.models import User
        
        app = create_app(os.getenv('FLASK_ENV', 'development'))
        
        with app.app_context():
            db.session.execute(db.text('SELECT 1'))
            print("✅ Datenbankverbindung funktioniert")
            
            user_count = User.query.count()
            print(f"✅ User-Model funktioniert ({user_count} Benutzer)")
            
        return True
        
    except Exception as e:
        print(f"❌ Test fehlgeschlagen: {e}")
        return False

def main():
    """Hauptfunktion für das Deployment."""
    print("=" * 60)
    print("🚀 TEAM PORTAL - DEPLOYMENT")
    print("=" * 60)
    print(f"📅 Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🐍 Python: {sys.version}")
    print(f"📂 Arbeitsverzeichnis: {os.getcwd()}")
    
    checks = [
        ("Abhängigkeiten", check_requirements),
        ("Umgebungsvariablen", check_environment),
        ("Dateiberechtigungen", check_file_permissions),
        ("Datenbank", init_database),
        ("Tests", run_tests)
    ]
    
    all_passed = True
    
    for check_name, check_func in checks:
        print(f"\n{'='*20} {check_name} {'='*20}")
        if not check_func():
            print(f"❌ {check_name} fehlgeschlagen!")
            all_passed = False
        else:
            print(f"✅ {check_name} erfolgreich!")
    
    print("\n" + "="*60)
    
    if all_passed:
        print("🎉 DEPLOYMENT ERFOLGREICH!")
        print("✅ Die Anwendung ist bereit für den Start")
        print("\n💡 Starten Sie die Anwendung mit:")
        print("   python app.py")
        print("   oder")
        print("   gunicorn -w 4 -b 0.0.0.0:5000 app:app")
        return 0
    else:
        print("❌ DEPLOYMENT FEHLGESCHLAGEN!")
        print("⚠️  Bitte beheben Sie die oben genannten Probleme")
        return 1

if __name__ == '__main__':
    sys.exit(main())
