#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.assessment import AssessmentAppSetting, AssessmentRole, AssessmentUser
from sqlalchemy import inspect, text


DEFAULT_ROLES = ["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"]
DEFAULT_SETTINGS = {
    "welcome_title": "Willkommen im Bewertungstool",
    "welcome_subtitle": "Bewerten, Ränge prüfen und Verwaltung – alles an einem Ort.",
    "module_label": "Bewertung",
    "logo_url": "",
    "ranking_sort_mode": "total",
    "ranking_active_mode": "standard",
}


def _ensure_theme_column():
    inspector = inspect(db.engine)
    if "ass_users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("ass_users")}
    if "theme_mode" in columns:
        return
    dialect = db.engine.dialect.name
    if dialect == "mysql":
        stmt = "ALTER TABLE ass_users ADD COLUMN theme_mode VARCHAR(16) NOT NULL DEFAULT 'light'"
    else:
        stmt = "ALTER TABLE ass_users ADD COLUMN theme_mode VARCHAR(16) NOT NULL DEFAULT 'light'"
    with db.engine.begin() as connection:
        connection.execute(text(stmt))


def migrate():
    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        db.create_all()
        _ensure_theme_column()

        role_map = {}
        for role_name in DEFAULT_ROLES:
            role = AssessmentRole.query.filter_by(name=role_name).first()
            if not role:
                role = AssessmentRole(name=role_name)
                db.session.add(role)
                db.session.flush()
            role_map[role_name] = role

        admin = AssessmentUser.query.filter_by(username="admin").first()
        if not admin:
            admin = AssessmentUser(
                username="admin",
                display_name="Administrator",
                is_admin=True,
                must_change_password=True,
                is_active=True,
            )
            admin.set_password("password")
            db.session.add(admin)
            db.session.flush()

        if role_map["Administrator"] not in admin.roles:
            admin.roles.append(role_map["Administrator"])

        for key, value in DEFAULT_SETTINGS.items():
            setting = AssessmentAppSetting.query.filter_by(setting_key=key).first()
            if not setting:
                db.session.add(AssessmentAppSetting(setting_key=key, setting_value=value))

        db.session.commit()
        print("[OK] Assessment module migration erfolgreich ausgefuehrt")
        return True


if __name__ == "__main__":
    migrate()
