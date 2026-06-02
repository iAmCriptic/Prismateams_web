from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentStand, AssessmentStandType
from app.utils.assessment_auth import assessment_role_required, get_assessment_identity

stand_types_bp = Blueprint("stand_types", __name__)


@stand_types_bp.route("/manage_stand_types")
@assessment_role_required(["Administrator"])
def manage_stand_types_page():
    return render_template("assessment/manage_stand_types.html")


@stand_types_bp.route("/api/stand_types", methods=["GET", "POST"])
@stand_types_bp.route("/api/stand_types/<int:type_id>", methods=["GET", "PUT", "DELETE"])
@assessment_role_required(["Administrator"])
def api_stand_types(type_id=None):
    if request.method == "GET":
        if type_id:
            stand_type = AssessmentStandType.query.get(type_id)
            if not stand_type:
                return jsonify({"success": False, "message": "Stand-Typ nicht gefunden."}), 404
            return jsonify(
                {
                    "success": True,
                    "stand_type": {
                        "id": stand_type.id,
                        "name": stand_type.name,
                        "sort_order": stand_type.sort_order,
                        "color": stand_type.color,
                    },
                }
            )
        types = AssessmentStandType.query.order_by(
            AssessmentStandType.sort_order.asc(), AssessmentStandType.name.asc()
        ).all()
        return jsonify(
            {
                "success": True,
                "stand_types": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "sort_order": t.sort_order,
                        "color": t.color,
                        "stand_count": AssessmentStand.query.filter_by(stand_type_id=t.id).count(),
                    }
                    for t in types
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "Name ist erforderlich."}), 400
        if AssessmentStandType.query.filter_by(name=name).first():
            return jsonify({"success": False, "message": "Stand-Typ existiert bereits."}), 409
        stand_type = AssessmentStandType(
            name=name,
            sort_order=int(data.get("sort_order") or 0),
            color=(data.get("color") or "").strip() or None,
        )
        db.session.add(stand_type)
        db.session.commit()
        return jsonify({"success": True, "message": "Stand-Typ erstellt."})

    stand_type = AssessmentStandType.query.get(type_id)
    if not stand_type:
        return jsonify({"success": False, "message": "Stand-Typ nicht gefunden."}), 404

    if request.method == "PUT":
        name = (data.get("name") or stand_type.name).strip()
        existing = AssessmentStandType.query.filter(
            AssessmentStandType.name == name, AssessmentStandType.id != type_id
        ).first()
        if existing:
            return jsonify({"success": False, "message": "Stand-Typ existiert bereits."}), 409
        stand_type.name = name
        stand_type.sort_order = int(data.get("sort_order") if data.get("sort_order") is not None else stand_type.sort_order)
        stand_type.color = (data.get("color") or "").strip() or None
        db.session.commit()
        return jsonify({"success": True, "message": "Stand-Typ aktualisiert."})

    if AssessmentStand.query.filter_by(stand_type_id=type_id).count():
        return jsonify(
            {"success": False, "message": "Stand-Typ wird noch von Ständen verwendet und kann nicht gelöscht werden."}
        ), 409
    db.session.delete(stand_type)
    db.session.commit()
    return jsonify({"success": True, "message": "Stand-Typ gelöscht."})
