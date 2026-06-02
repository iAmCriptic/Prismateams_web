from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import (
    AssessmentList,
    AssessmentListSubject,
    AssessmentStand,
    AssessmentWarning,
)
from app.utils.assessment_auth import assessment_role_required

from .helpers import resolve_evaluation_list_from_request, stands_for_list, subjects_for_list, validate_evaluation_target

warnings_bp = Blueprint("warnings", __name__)


@warnings_bp.route("/")
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_page():
    lists = AssessmentList.query.filter_by(is_active=True).order_by(
        AssessmentList.sort_order.asc(), AssessmentList.name.asc()
    ).all()
    return render_template("assessment/warnings.html", evaluation_lists=lists)


@warnings_bp.route("/api/items", methods=["GET", "POST", "PUT"])
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_api():
    from .helpers import current_actor

    actor = current_actor()
    evaluation_list = resolve_evaluation_list_from_request(require_active=False)

    if request.method == "GET":
        query = AssessmentWarning.query
        if evaluation_list:
            query = query.filter_by(list_id=evaluation_list.id)
        warnings = query.order_by(AssessmentWarning.timestamp.desc()).all()

        targets = []
        if evaluation_list:
            if evaluation_list.subject_mode == "stand":
                targets = [{"id": s.id, "name": s.name} for s in stands_for_list(evaluation_list)]
            else:
                targets = [{"id": s.id, "name": s.name} for s in subjects_for_list(evaluation_list)]
        else:
            targets = [{"id": s.id, "name": s.name} for s in AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()]

        return jsonify(
            {
                "success": True,
                "list_id": evaluation_list.id if evaluation_list else None,
                "subject_mode": evaluation_list.subject_mode if evaluation_list else "stand",
                "warnings": [
                    {
                        "id": w.id,
                        "list_id": w.list_id,
                        "stand_id": w.stand_id,
                        "subject_id": w.subject_id,
                        "target_name": (w.stand.name if w.stand else None) or (w.subject.name if w.subject else None),
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
        list_id = data.get("list_id")
        if not list_id and evaluation_list:
            list_id = evaluation_list.id
        evaluation_list = AssessmentList.query.get(list_id) if list_id else None
        if not evaluation_list:
            return jsonify({"success": False, "message": "Bewertungsliste ist erforderlich."}), 400

        stand_id = data.get("stand_id")
        subject_id = data.get("subject_id")
        valid, _ = validate_evaluation_target(evaluation_list, stand_id=stand_id, subject_id=subject_id)
        if not valid:
            return jsonify({"success": False, "message": _}), 400

        warning = AssessmentWarning(
            list_id=evaluation_list.id,
            stand_id=stand_id if evaluation_list.subject_mode == "stand" else None,
            subject_id=subject_id if evaluation_list.subject_mode == "custom" else None,
            user_type=actor["user_type"],
            user_id=actor["user_id"],
            comment=(data.get("comment") or "").strip(),
        )
        if not warning.comment:
            return jsonify({"success": False, "message": "Kommentar ist erforderlich."}), 400
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
