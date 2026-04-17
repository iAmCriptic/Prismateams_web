import os

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from openpyxl import load_workbook

from app import db
from app.models.assessment import (
    AssessmentCriterion,
    AssessmentRole,
    AssessmentRoom,
    AssessmentStand,
    AssessmentUser,
)
from app.utils.assessment_auth import assessment_role_required

excel_uploads_bp = Blueprint("excel_uploads", __name__)


def _sample_dir():
    return os.path.join(current_app.static_folder, "assessment")


def _row_dict(ws):
    headers = [str(cell.value).strip() if cell.value is not None else "" for cell in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(cell is not None and str(cell).strip() for cell in row):
            continue
        yield {headers[i]: row[i] for i in range(len(headers))}


def _read_workbook(upload_file, required_columns):
    if not upload_file or not upload_file.filename:
        return None, "Keine Datei empfangen.", 400
    if not upload_file.filename.lower().endswith(".xlsx"):
        return None, "Bitte eine .xlsx-Datei hochladen.", 400
    try:
        workbook = load_workbook(upload_file, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return None, f"Datei konnte nicht gelesen werden: {exc}", 400
    ws = workbook.active
    headers = [str(cell.value).strip() if cell.value is not None else "" for cell in ws[1]]
    missing = [col for col in required_columns if col not in headers]
    if missing:
        return None, f"Excel-Datei muss die Spalten enthalten: {', '.join(required_columns)}.", 400
    return ws, None, None


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


@excel_uploads_bp.route("/api/download_sample/<which>")
@assessment_role_required(["Administrator"])
def download_sample(which):
    mapping = {
        "stands": "beispiel_staende.xlsx",
        "users": "beispiel_benutzer.xlsx",
        "criteria": "beispiel_kriterien.xlsx",
    }
    filename = mapping.get(which)
    if not filename:
        return jsonify({"success": False, "message": "Unbekannte Beispieldatei."}), 404
    return send_from_directory(_sample_dir(), filename, as_attachment=True)


@excel_uploads_bp.route("/api/import/stands", methods=["POST"])
@assessment_role_required(["Administrator"])
def import_stands():
    ws, error, code = _read_workbook(request.files.get("file"), ["Standname", "Beschreibung", "Raum"])
    if error:
        return jsonify({"success": False, "message": error}), code or 400

    added, updated, errors, rooms_created = 0, 0, [], 0

    for index, row in enumerate(_row_dict(ws), start=2):
        name = _clean(row.get("Standname"))
        if not name:
            continue
        description = _clean(row.get("Beschreibung")) or None
        room_name = _clean(row.get("Raum")) or None

        room = None
        if room_name:
            room = AssessmentRoom.query.filter_by(name=room_name).first()
            if not room:
                room = AssessmentRoom(name=room_name)
                db.session.add(room)
                db.session.flush()
                rooms_created += 1

        existing = AssessmentStand.query.filter_by(name=name).first()
        if existing:
            existing.description = description
            existing.room_id = room.id if room else None
            updated += 1
        else:
            db.session.add(
                AssessmentStand(
                    name=name,
                    description=description,
                    room_id=room.id if room else None,
                )
            )
            added += 1

    db.session.commit()
    message = f"Stände importiert: {added} hinzugefügt, {updated} aktualisiert."
    if rooms_created:
        message += f" {rooms_created} Räume automatisch erstellt."
    return jsonify({"success": True, "message": message, "errors": errors})


@excel_uploads_bp.route("/api/import/users", methods=["POST"])
@assessment_role_required(["Administrator"])
def import_users():
    ws, error, code = _read_workbook(
        request.files.get("file"), ["Benutzername", "Password", "Anzeigename", "Rollen"]
    )
    if error:
        return jsonify({"success": False, "message": error}), code or 400

    added, updated, errors = 0, 0, []
    all_roles = {role.name: role for role in AssessmentRole.query.all()}

    for index, row in enumerate(_row_dict(ws), start=2):
        username = _clean(row.get("Benutzername")).lower()
        password = _clean(row.get("Password"))
        display_name = _clean(row.get("Anzeigename")) or username
        roles_text = _clean(row.get("Rollen"))

        if not username or not password or not roles_text:
            errors.append(f"Zeile {index}: Pflichtfelder fehlen.")
            continue

        role_names = [r.strip() for r in roles_text.split(",") if r.strip()]
        roles = [all_roles[name] for name in role_names if name in all_roles]
        if not roles:
            errors.append(f"Zeile {index}: Keine gültigen Rollen für '{username}'.")
            continue

        user = AssessmentUser.query.filter_by(username=username).first()
        if user:
            user.display_name = display_name
            user.set_password(password)
            user.roles = roles
            user.is_admin = any(role.name == "Administrator" for role in roles)
            updated += 1
        else:
            user = AssessmentUser(username=username, display_name=display_name, is_active=True)
            user.set_password(password)
            user.roles = roles
            user.is_admin = any(role.name == "Administrator" for role in roles)
            db.session.add(user)
            added += 1

    db.session.commit()
    message = f"Benutzer importiert: {added} hinzugefügt, {updated} aktualisiert."
    return jsonify({"success": True, "message": message, "errors": errors})


@excel_uploads_bp.route("/api/import/criteria", methods=["POST"])
@assessment_role_required(["Administrator"])
def import_criteria():
    ws, error, code = _read_workbook(
        request.files.get("file"), ["Name", "Maximale Punktzahl", "Beschreibung"]
    )
    if error:
        return jsonify({"success": False, "message": error}), code or 400

    added, updated, errors = 0, 0, []

    for index, row in enumerate(_row_dict(ws), start=2):
        name = _clean(row.get("Name"))
        max_raw = row.get("Maximale Punktzahl")
        description = _clean(row.get("Beschreibung")) or None
        if not name or max_raw is None:
            errors.append(f"Zeile {index}: Pflichtfelder fehlen.")
            continue
        try:
            max_score = int(max_raw)
        except (TypeError, ValueError):
            errors.append(f"Zeile {index}: Maximalpunktzahl ist nicht numerisch.")
            continue
        if max_score <= 0:
            errors.append(f"Zeile {index}: Maximalpunktzahl muss > 0 sein.")
            continue

        existing = AssessmentCriterion.query.filter_by(name=name).first()
        if existing:
            existing.max_score = max_score
            existing.description = description
            updated += 1
        else:
            db.session.add(
                AssessmentCriterion(name=name, max_score=max_score, description=description)
            )
            added += 1

    db.session.commit()
    message = f"Kriterien importiert: {added} hinzugefügt, {updated} aktualisiert."
    return jsonify({"success": True, "message": message, "errors": errors})
