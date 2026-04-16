from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentRoom
from app.utils.assessment_auth import assessment_role_required, get_assessment_identity

rooms_bp = Blueprint("rooms", __name__)


@rooms_bp.route("/manage_rooms")
@assessment_role_required(["Administrator"])
def manage_rooms_page():
    return render_template("assessment/manage_rooms.html")


@rooms_bp.route("/api/rooms", methods=["GET", "POST"])
@rooms_bp.route("/api/rooms/<int:room_id>", methods=["GET", "PUT", "DELETE"])
@assessment_role_required(["Administrator"])
def api_rooms(room_id=None):
    if request.method == "GET":
        if room_id:
            room = AssessmentRoom.query.get(room_id)
            if not room:
                return jsonify({"success": False, "message": "Raum nicht gefunden."}), 404
            return jsonify({"success": True, "room": {"id": room.id, "name": room.name}})

        rooms = AssessmentRoom.query.order_by(AssessmentRoom.name.asc()).all()
        return jsonify({"success": True, "rooms": [{"id": room.id, "name": room.name} for room in rooms]})

    data = request.get_json(silent=True) or {}
    if request.method in ("POST", "PUT", "DELETE"):
        _, _, roles = get_assessment_identity()
        if "Administrator" not in roles:
            return jsonify({"success": False, "message": "Nur Administratoren dürfen Räume ändern."}), 403

    if request.method == "POST":
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "Raumname ist erforderlich."}), 400
        if AssessmentRoom.query.filter_by(name=name).first():
            return jsonify({"success": False, "message": "Raumname existiert bereits."}), 409
        db.session.add(AssessmentRoom(name=name))
        db.session.commit()
        return jsonify({"success": True, "message": "Raum erfolgreich erstellt."})

    room = AssessmentRoom.query.get(room_id)
    if not room:
        return jsonify({"success": False, "message": "Raum nicht gefunden."}), 404

    if request.method == "PUT":
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "Raumname ist erforderlich."}), 400
        room.name = name
        db.session.commit()
        return jsonify({"success": True, "message": "Raum aktualisiert."})

    db.session.delete(room)
    db.session.commit()
    return jsonify({"success": True, "message": "Raum gelöscht."})
