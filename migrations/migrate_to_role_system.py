"""
Migration zum Rollensystem.
Setzt für alle bestehenden Benutzer has_full_access=True.
Erstellt die user_module_roles Tabelle.
"""
import sys
import os

# Füge das Projektverzeichnis zum Python-Pfad hinzu
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app import create_app, db
from app.models.user import User
from app.models.role import UserModuleRole
from sqlalchemy import inspect, text

def migrate():
    """Führt die Migration zum Rollensystem durch."""
    app = create_app('default')
    
    with app.app_context():
        print("[INFO] Starte Migration zum Rollensystem...")
        
        try:
            # Prüfe ob user_module_roles Tabelle existiert
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'user_module_roles' not in tables:
                print("[INFO] Erstelle user_module_roles Tabelle...")
                UserModuleRole.__table__.create(db.engine, checkfirst=True)
                print("[OK] Tabelle user_module_roles erstellt")
            else:
                print("[INFO] Tabelle user_module_roles existiert bereits")
            
            # Prüfe ob has_full_access Spalte existiert
            if 'users' in tables:
                columns = {col['name'] for col in inspector.get_columns('users')}
                
                if 'has_full_access' not in columns:
                    print("[INFO] Füge has_full_access Spalte zu users Tabelle hinzu...")
                    with db.engine.begin() as conn:
                        conn.execute(text("ALTER TABLE users ADD COLUMN has_full_access BOOLEAN DEFAULT FALSE NOT NULL"))
                    print("[OK] Spalte has_full_access hinzugefügt")
                    # Nach dem Hinzufügen der Spalte müssen wir die Session neu laden
                    db.session.expire_all()
                else:
                    print("[INFO] Spalte has_full_access existiert bereits")
            
            # Setze has_full_access=True für alle bestehenden Benutzer
            print("[INFO] Setze has_full_access=True für alle bestehenden Benutzer...")
            # Verwende direkte SQL-Abfrage um sicherzustellen, dass die Spalte existiert
            with db.engine.begin() as conn:
                result = conn.execute(text("UPDATE users SET has_full_access = TRUE WHERE has_full_access = FALSE OR has_full_access IS NULL"))
                updated_count = result.rowcount
            print(f"[OK] {updated_count} Benutzer aktualisiert (has_full_access=True)")
            
            print("[OK] Migration erfolgreich abgeschlossen!")
            
        except Exception as e:
            db.session.rollback()
            print(f"[FEHLER] Migration fehlgeschlagen: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    migrate()

