from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentStand, AssessmentWarning
from app.utils.assessment_auth import assessment_role_required

warnings_bp = Blueprint("warnings", __name__)


@warnings_bp.route("/")
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_page():
    return render_template("assessment/warnings.html")


@warnings_bp.route("/api/items", methods=["GET", "POST", "PUT"])
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_api():
    from .helpers import current_actor

    actor = current_actor()

    if request.method == "GET":
        warnings = AssessmentWarning.query.order_by(AssessmentWarning.timestamp.desc()).all()
        targets = [
            {"id": s.id, "name": s.name}
            for s in AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()
        ]
        return jsonify(
            {
                "success": True,
                "subject_mode": "stand",
                "warnings": [
                    {
                        "id": w.id,
                        "list_id": w.list_id,
                        "stand_id": w.stand_id,
                        "subject_id": w.subject_id,
                        "target_name": (w.stand.name if w.stand else None)
                        or (w.subject.name if w.subject else None),
                        "comment": w.comment,
                        "timestamp": w.timestamp.isoformat() if w.timestamp else None,
                        "is_invalidated": w.is_invalidated,
                        "invalidation_comment": w.invalidation_comment,
                    }
                    for w in warnings
                ],
                "targets": targets,
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        stand_id = data.get("stand_id")
        stand = AssessmentStand.query.get(stand_id) if stand_id else None
        if not stand:
            return jsonify({"success": False, "message": "Stand ist erforderlich."}), 400

        comment = (data.get("comment") or "").strip()
        if not comment:
            return jsonify({"success": False, "message": "Kommentar ist erforderlich."}), 400

        warning = AssessmentWarning(
            list_id=None,
            stand_id=stand.id,
            subject_id=None,
            user_type=actor["user_type"],
            user_id=actor["user_id"],
            comment=comment,
        )
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
