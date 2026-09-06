import os
from datetime import datetime
from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from openpyxl import Workbook, load_workbook

from app import db
from app.models.assessment import (
    AssessmentCriterion,
    AssessmentList,
    AssessmentListSubject,
    AssessmentRole,
    AssessmentRoom,
    AssessmentStand,
    AssessmentStandType,
    AssessmentUser,
    AssessmentUserRole,
    password_hasher,
)
from app.utils.assessment_auth import assessment_role_required

from .helpers import get_or_create_default_stand_type

excel_uploads_bp = Blueprint("excel_uploads", __name__)

SAMPLE_SPECS = {
    "stands": {
        "filename": "beispiel_staende.xlsx",
        "headers": ["Standname", "Beschreibung", "Raum", "Stand-Typ"],
        "rows": [["Stand Beispiel", "Kurzbeschreibung", "Raum 1", "Essen"]],
    },
    "users": {
        "filename": "beispiel_benutzer.xlsx",
        "headers": ["Benutzername", "Password", "Anzeigename", "Rollen"],
        "rows": [["jury1", "geheim123", "Jury Mitglied", "Bewerter"]],
    },
    "criteria": {
        "filename": "beispiel_kriterien.xlsx",
        "headers": ["Name", "Maximale Punktzahl", "Beschreibung"],
        "rows": [["Kriterium 1", 10, "Beschreibung optional"]],
    },
    "subjects": {
        "filename": "beispiel_bewertungsziele.xlsx",
        "headers": ["Name", "Beschreibung"],
        "rows": [["Maskottchen A", "Optional"]],
    },
}


def _sample_dir():
    return os.path.join(current_app.static_folder, "assessment")


def _build_sample_workbook(which):
    spec = SAMPLE_SPECS[which]
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(spec["headers"])
    for row in spec["rows"]:
        worksheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


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


def _id_map_by_names(model, names, attr="name"):
    """Nach Bulk-Insert: name→id für die angegebenen Namen nachladen."""
    if not names:
        return {}
    col = getattr(model, attr)
    return {
        getattr(row, attr): row.id
        for row in model.query.filter(col.in_(list(names))).all()
    }


@excel_uploads_bp.route("/api/download_sample/<which>")
@assessment_role_required(["Administrator"])
def download_sample(which):
    spec = SAMPLE_SPECS.get(which)
    if not spec:
        return jsonify({"success": False, "message": "Unbekannte Beispieldatei."}), 404
    filename = spec["filename"]
    sample_path = os.path.join(_sample_dir(), filename)
    if os.path.isfile(sample_path):
        return send_from_directory(_sample_dir(), filename, as_attachment=True)
    return send_file(
        _build_sample_workbook(which),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@excel_uploads_bp.route("/api/import/stands", methods=["POST"])
@assessment_role_required(["Administrator"])
def import_stands():
    ws, error, code = _read_workbook(request.files.get("file"), ["Standname", "Beschreibung"])
    if error:
        return jsonify({"success": False, "message": error}), code or 400

    errors = []
    default_type = get_or_create_default_stand_type()
    room_ids = {r.name: r.id for r in AssessmentRoom.query.all()}
    type_ids = {t.name: t.id for t in AssessmentStandType.query.all()}
    stand_ids = {s.name: s.id for s in AssessmentStand.query.all()}

    parsed = []
    new_room_names = set()
    new_type_names = set()
    for index, row in enumerate(_row_dict(ws), start=2):
        name = _clean(row.get("Standname"))
        description = _clean(row.get("Beschreibung"))
        if not name or not description:
            errors.append(f"Zeile {index}: Standname und Beschreibung sind erforderlich.")
            continue
        room_name = _clean(row.get("Raum")) or None
        type_name = _clean(row.get("Stand-Typ")) or None
        if room_name and room_name not in room_ids:
            new_room_names.add(room_name)
        if type_name and type_name not in type_ids:
            new_type_names.add(type_name)
        parsed.append(
            {
                "name": name,
                "description": description,
                "room_name": room_name,
                "type_name": type_name,
            }
        )

    if new_room_names:
        db.session.bulk_insert_mappings(
            AssessmentRoom, [{"name": n} for n in sorted(new_room_names)]
        )
        db.session.flush()
        room_ids.update(_id_map_by_names(AssessmentRoom, new_room_names))

    if new_type_names:
        db.session.bulk_insert_mappings(
            AssessmentStandType,
            [{"name": n, "sort_order": 0} for n in sorted(new_type_names)],
        )
        db.session.flush()
        type_ids.update(_id_map_by_names(AssessmentStandType, new_type_names))

    stand_updates = []
    stand_inserts = []
    seen_new = set()
    for item in parsed:
        type_id = (
            type_ids.get(item["type_name"])
            if item["type_name"]
            else (default_type.id if default_type else None)
        )
        room_id = room_ids.get(item["room_name"]) if item["room_name"] else None
        existing_id = stand_ids.get(item["name"])
        if existing_id:
            stand_updates.append(
                {
                    "id": existing_id,
                    "description": item["description"],
                    "room_id": room_id,
                    "stand_type_id": type_id,
                }
            )
        elif item["name"] not in seen_new:
            seen_new.add(item["name"])
            stand_inserts.append(
                {
                    "name": item["name"],
                    "description": item["description"],
                    "room_id": room_id,
                    "stand_type_id": type_id,
                }
            )

    if stand_updates:
        db.session.bulk_update_mappings(AssessmentStand, stand_updates)
    if stand_inserts:
        db.session.bulk_insert_mappings(AssessmentStand, stand_inserts)

    db.session.commit()
    message = (
        f"Stände importiert: {len(stand_inserts)} hinzugefügt, "
        f"{len(stand_updates)} aktualisiert."
    )
    if new_room_names:
        message += f" {len(new_room_names)} Räume automatisch erstellt."
    if errors:
        message += f" {len(errors)} Zeile(n) übersprungen."
    return jsonify({"success": True, "message": message, "errors": errors})


@excel_uploads_bp.route("/api/import/users", methods=["POST"])
@assessment_role_required(["Administrator"])
def import_users():
    ws, error, code = _read_workbook(
        request.files.get("file"), ["Benutzername", "Password", "Anzeigename", "Rollen"]
    )
    if error:
        return jsonify({"success": False, "message": error}), code or 400

    errors = []
    all_roles = {role.name: role for role in AssessmentRole.query.all()}
    users_by_username = {(u.username or "").lower(): u for u in AssessmentUser.query.all()}

    user_updates = []
    user_inserts = []
    role_ids_by_username = {}
    update_id_by_username = {}
    seen_new = set()
    now = datetime.utcnow()

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

        is_admin = any(role.name == "Administrator" for role in roles)
        password_hash = password_hasher.hash(password)
        role_ids_by_username[username] = [role.id for role in roles]

        existing = users_by_username.get(username)
        if existing:
            update_id_by_username[username] = existing.id
            user_updates.append(
                {
                    "id": existing.id,
                    "display_name": display_name,
                    "password_hash": password_hash,
                    "is_admin": is_admin,
                }
            )
        elif username not in seen_new:
            seen_new.add(username)
            user_inserts.append(
                {
                    "username": username,
                    "password_hash": password_hash,
                    "display_name": display_name,
                    "is_admin": is_admin,
                    "must_change_password": False,
                    "is_active": True,
                    "theme_mode": "light",
                    "created_at": now,
                }
            )

    if user_updates:
        db.session.bulk_update_mappings(AssessmentUser, user_updates)

    if user_inserts:
        db.session.bulk_insert_mappings(AssessmentUser, user_inserts)
        db.session.flush()
        inserted_ids = _id_map_by_names(AssessmentUser, seen_new, attr="username")
    else:
        inserted_ids = {}

    user_id_by_username = {**update_id_by_username, **inserted_ids}
    touch_user_ids = list(user_id_by_username.values())
    if touch_user_ids:
        AssessmentUserRole.query.filter(
            AssessmentUserRole.user_id.in_(touch_user_ids)
        ).delete(synchronize_session=False)

        role_rows = []
        for username, user_id in user_id_by_username.items():
            for role_id in role_ids_by_username.get(username, []):
                role_rows.append(
                    {"user_id": user_id, "role_id": role_id, "created_at": now}
                )
        if role_rows:
            db.session.bulk_insert_mappings(AssessmentUserRole, role_rows)

    db.session.commit()
    message = (
        f"Benutzer importiert: {len(user_inserts)} hinzugefügt, "
        f"{len(user_updates)} aktualisiert."
    )
    return jsonify({"success": True, "message": message, "errors": errors})


@excel_uploads_bp.route("/api/import/criteria", methods=["POST"])
@assessment_role_required(["Administrator"])
def import_criteria():
    list_id = request.form.get("list_id", type=int) or request.args.get("list_id", type=int)
    if not list_id:
        default_list = AssessmentList.query.filter_by(slug="hauptbewertung").first()
        list_id = default_list.id if default_list else None
    if not list_id:
        return jsonify({"success": False, "message": "Bewertungsliste (list_id) ist erforderlich."}), 400

    ws, error, code = _read_workbook(
        request.files.get("file"), ["Name", "Maximale Punktzahl", "Beschreibung"]
    )
    if error:
        return jsonify({"success": False, "message": error}), code or 400

    errors = []
    existing_by_name = {
        c.name: c.id for c in AssessmentCriterion.query.filter_by(list_id=list_id).all()
    }

    updates = []
    inserts = []
    seen_new = set()
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

        existing_id = existing_by_name.get(name)
        if existing_id:
            updates.append(
                {
                    "id": existing_id,
                    "max_score": max_score,
                    "description": description,
                }
            )
        elif name not in seen_new:
            seen_new.add(name)
            inserts.append(
                {
                    "list_id": list_id,
                    "name": name,
                    "max_score": max_score,
                    "description": description,
                }
            )

    if updates:
        db.session.bulk_update_mappings(AssessmentCriterion, updates)
    if inserts:
        db.session.bulk_insert_mappings(AssessmentCriterion, inserts)

    db.session.commit()
    message = (
        f"Kriterien importiert: {len(inserts)} hinzugefügt, {len(updates)} aktualisiert."
    )
    return jsonify({"success": True, "message": message, "errors": errors})


@excel_uploads_bp.route("/api/import/subjects", methods=["POST"])
@assessment_role_required(["Administrator"])
def import_subjects():
    list_id = request.form.get("list_id", type=int) or request.args.get("list_id", type=int)
    evaluation_list = AssessmentList.query.get(list_id) if list_id else None
    if not evaluation_list or evaluation_list.subject_mode != "custom":
        return jsonify({"success": False, "message": "Gültige Custom-Bewertungsliste erforderlich."}), 400

    ws, error, code = _read_workbook(request.files.get("file"), ["Name", "Beschreibung"])
    if error:
        return jsonify({"success": False, "message": error}), code or 400

    errors = []
    existing_by_name = {
        s.name: s.id for s in AssessmentListSubject.query.filter_by(list_id=list_id).all()
    }

    updates = []
    inserts = []
    seen_new = set()
    for index, row in enumerate(_row_dict(ws), start=2):
        name = _clean(row.get("Name"))
        if not name:
            continue
        description = _clean(row.get("Beschreibung")) or None
        existing_id = existing_by_name.get(name)
        if existing_id:
            updates.append({"id": existing_id, "description": description})
        elif name not in seen_new:
            seen_new.add(name)
            inserts.append(
                {
                    "list_id": list_id,
                    "name": name,
                    "description": description,
                    "sort_order": 0,
                    "is_active": True,
                }
            )

    if updates:
        db.session.bulk_update_mappings(AssessmentListSubject, updates)
    if inserts:
        db.session.bulk_insert_mappings(AssessmentListSubject, inserts)

    db.session.commit()
    message = (
        f"Bewertungsziele importiert: {len(inserts)} hinzugefügt, "
        f"{len(updates)} aktualisiert."
    )
    return jsonify({"success": True, "message": message, "errors": errors})
