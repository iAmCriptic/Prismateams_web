from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentRoom, AssessmentStand
from app.utils.assessment_auth import assessment_role_required, get_assessment_identity

stands_bp = Blueprint("stands", __name__)


@stands_bp.route("/manage_stand")
@assessment_role_required(["Administrator"])
def manage_stand_page():
    return render_template("assessment/manage_stands.html")


@stands_bp.route("/api/stands", methods=["GET", "POST"])
@stands_bp.route("/api/stands/<int:stand_id>", methods=["GET", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def api_stands(stand_id=None):
    if request.method == "GET":
        if stand_id:
            stand = AssessmentStand.query.get(stand_id)
            if not stand:
                return jsonify({"success": False, "message": "Stand nicht gefunden."}), 404
            return jsonify(
                {
                    "success": True,
                    "stand": {
                        "id": stand.id,
                        "name": stand.name,
                        "description": stand.description,
                        "room_id": stand.room_id,
                        "room_name": stand.room.name if stand.room else None,
                    },
                }
            )
        stands = AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()
        return jsonify(
            {
                "success": True,
                "stands": [
                    {
                        "id": stand.id,
                        "name": stand.name,
                        "description": stand.description,
                        "room_id": stand.room_id,
                        "room_name": stand.room.name if stand.room else None,
                    }
                    for stand in stands
                ],
                "rooms": [{"id": room.id, "name": room.name} for room in AssessmentRoom.query.order_by(AssessmentRoom.name.asc()).all()],
            }
        )

    if request.method in ("POST", "PUT", "DELETE"):
        _, _, roles = get_assessment_identity()
        if "Administrator" not in roles:
            return jsonify({"success": False, "message": "Nur Administratoren dürfen Stände ändern."}), 403

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "Standname ist erforderlich."}), 400
        stand = AssessmentStand(
            name=name,
            description=(data.get("description") or "").strip() or None,
            room_id=data.get("room_id"),
        )
        db.session.add(stand)
        db.session.commit()
        return jsonify({"success": True, "message": "Stand erfolgreich erstellt."})

    stand = AssessmentStand.query.get(stand_id)
    if not stand:
        return jsonify({"success": False, "message": "Stand nicht gefunden."}), 404

    if request.method == "PUT":
        stand.name = (data.get("name") or stand.name).strip()
        stand.description = (data.get("description") or "").strip() or None
        stand.room_id = data.get("room_id")
        db.session.commit()
        return jsonify({"success": True, "message": "Stand aktualisiert."})

    db.session.delete(stand)
    db.session.commit()
    return jsonify({"success": True, "message": "Stand gelöscht."})
