from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentRoom, AssessmentRoomInspection
from app.utils.assessment_auth import assessment_role_required

from .helpers import current_actor

inspections_bp = Blueprint("inspections", __name__)


@inspections_bp.route("/room_inspections")
@assessment_role_required(["Administrator", "Inspektor"])
def room_inspections_page():
    return render_template("assessment/room_inspections.html")


@inspections_bp.route("/api/room_inspections", methods=["GET", "POST"])
@assessment_role_required(["Administrator", "Inspektor"])
def room_inspections_api():
    actor = current_actor()
    if request.method == "GET":
        rooms = AssessmentRoom.query.order_by(AssessmentRoom.name.asc()).all()
        inspections = AssessmentRoomInspection.query.all()
        inspection_map = {item.room_id: item for item in inspections}
        return jsonify(
            {
                "success": True,
                "rooms": [
                    {
                        "id": room.id,
                        "name": room.name,
                        "inspection": (
                            {
                                "is_clean": inspection_map[room.id].is_clean,
                                "comment": inspection_map[room.id].comment,
                                "inspection_timestamp": inspection_map[room.id].inspection_timestamp.isoformat()
                                if inspection_map[room.id].inspection_timestamp
                                else None,
                            }
                            if room.id in inspection_map
                            else None
                        ),
                    }
                    for room in rooms
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    room_id = data.get("room_id")
    room = AssessmentRoom.query.get(room_id)
    if not room:
        return jsonify({"success": False, "message": "Raum nicht gefunden."}), 404

    inspection = AssessmentRoomInspection.query.get(room_id)
    if not inspection:
        inspection = AssessmentRoomInspection(room_id=room_id)
        db.session.add(inspection)

    inspection.inspector_user_type = actor["user_type"]
    inspection.inspector_user_id = actor["user_id"]
    inspection.inspection_timestamp = datetime.utcnow()
    inspection.is_clean = bool(data.get("is_clean", False))
    inspection.comment = (data.get("comment") or "").strip() or None
    db.session.commit()
    return jsonify({"success": True, "message": "Inspektion gespeichert."})
