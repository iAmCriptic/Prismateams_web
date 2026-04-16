from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentStand, AssessmentWarning
from app.utils.assessment_auth import assessment_role_required

from .helpers import current_actor

warnings_bp = Blueprint("warnings", __name__)


@warnings_bp.route("/")
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_page():
    return render_template("assessment/warnings.html")


@warnings_bp.route("/api/items", methods=["GET", "POST", "PUT"])
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_api():
    actor = current_actor()
    if request.method == "GET":
        warnings = AssessmentWarning.query.order_by(AssessmentWarning.timestamp.desc()).all()
        stands = AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()
        return jsonify(
            {
                "success": True,
                "warnings": [
                    {
                        "id": w.id,
                        "stand_id": w.stand_id,
                        "stand_name": w.stand.name if w.stand else None,
                        "comment": w.comment,
                        "timestamp": w.timestamp.isoformat() if w.timestamp else None,
                        "is_invalidated": w.is_invalidated,
                        "invalidation_comment": w.invalidation_comment,
                    }
                    for w in warnings
                ],
                "stands": [{"id": s.id, "name": s.name} for s in stands],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        warning = AssessmentWarning(
            stand_id=data.get("stand_id"),
            user_type=actor["user_type"],
            user_id=actor["user_id"],
            comment=(data.get("comment") or "").strip(),
        )
        if not warning.stand_id or not warning.comment:
            return jsonify({"success": False, "message": "Stand und Kommentar sind erforderlich."}), 400
        db.session.add(warning)
        db.session.commit()
        return jsonify({"success": True, "message": "Verwarnung gespeichert."})

    warning_id = data.get("id")
    warning = AssessmentWarning.query.get(warning_id)
    if not warning:
        return jsonify({"success": False, "message": "Eintrag nicht gefunden."}), 404
    warning.is_invalidated = True
    warning.invalidation_comment = (data.get("invalidation_comment") or "").strip()
    warning.invalidation_timestamp = datetime.utcnow()
    warning.invalidated_by_user_id = actor["user_id"]
    db.session.commit()
    return jsonify({"success": True, "message": "Verwarnung wurde invalidiert."})
