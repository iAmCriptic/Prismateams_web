from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentCriterion, AssessmentList
from app.utils.assessment_auth import assessment_role_required, get_assessment_identity

from .helpers import resolve_evaluation_list_from_request

criteria_bp = Blueprint("criteria", __name__)


@criteria_bp.route("/manage_criteria")
@assessment_role_required(["Administrator"])
def manage_criteria_page():
    lists = AssessmentList.query.order_by(AssessmentList.sort_order.asc(), AssessmentList.name.asc()).all()
    return render_template("assessment/manage_criteria.html", evaluation_lists=lists)


@criteria_bp.route("/api/criteria", methods=["GET", "POST"])
@criteria_bp.route("/api/criteria/<int:criterion_id>", methods=["GET", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def api_criteria(criterion_id=None):
    evaluation_list = resolve_evaluation_list_from_request(require_active=False)

    if request.method == "GET":
        if criterion_id:
            criterion = AssessmentCriterion.query.get(criterion_id)
            if not criterion:
                return jsonify({"success": False, "message": "Kriterium nicht gefunden."}), 404
            return jsonify(
                {
                    "success": True,
                    "criterion": {
                        "id": criterion.id,
                        "list_id": criterion.list_id,
                        "name": criterion.name,
                        "max_score": criterion.max_score,
                        "description": criterion.description,
                    },
                }
            )
        query = AssessmentCriterion.query
        if evaluation_list:
            query = query.filter_by(list_id=evaluation_list.id)
        elif request.args.get("list_id", type=int):
            query = query.filter_by(list_id=request.args.get("list_id", type=int))
        criteria = query.order_by(AssessmentCriterion.name.asc()).all()
        return jsonify(
            {
                "success": True,
                "list_id": evaluation_list.id if evaluation_list else request.args.get("list_id", type=int),
                "criteria": [
                    {
                        "id": criterion.id,
                        "list_id": criterion.list_id,
                        "name": criterion.name,
                        "max_score": criterion.max_score,
                        "description": criterion.description,
                    }
                    for criterion in criteria
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method in ("POST", "PUT", "DELETE"):
        _, _, roles = get_assessment_identity()
        if "Administrator" not in roles:
            return jsonify({"success": False, "message": "Nur Administratoren dürfen Kriterien ändern."}), 403

    if request.method == "POST":
        list_id = data.get("list_id") or (evaluation_list.id if evaluation_list else None)
        if not list_id:
            return jsonify({"success": False, "message": "Bewertungsliste ist erforderlich."}), 400
        name = (data.get("name") or "").strip()
        max_score = int(data.get("max_score") or 0)
        if not name or max_score <= 0:
            return jsonify({"success": False, "message": "Name und gültige Maximalpunktzahl sind erforderlich."}), 400
        existing = AssessmentCriterion.query.filter_by(list_id=list_id, name=name).first()
        if existing:
            return jsonify({"success": False, "message": "Kriterium existiert in dieser Liste bereits."}), 409
        criterion = AssessmentCriterion(
            list_id=list_id,
            name=name,
            max_score=max_score,
            description=(data.get("description") or "").strip() or None,
        )
        db.session.add(criterion)
        db.session.commit()
        return jsonify({"success": True, "message": "Kriterium erstellt."})

    criterion = AssessmentCriterion.query.get(criterion_id)
    if not criterion:
        return jsonify({"success": False, "message": "Kriterium nicht gefunden."}), 404

    if request.method == "PUT":
        name = (data.get("name") or criterion.name).strip()
        duplicate = AssessmentCriterion.query.filter(
            AssessmentCriterion.list_id == criterion.list_id,
            AssessmentCriterion.name == name,
            AssessmentCriterion.id != criterion_id,
        ).first()
        if duplicate:
            return jsonify({"success": False, "message": "Kriterium existiert in dieser Liste bereits."}), 409
        criterion.name = name
        criterion.max_score = int(data.get("max_score") or criterion.max_score)
        criterion.description = (data.get("description") or "").strip() or None
        db.session.commit()
        return jsonify({"success": True, "message": "Kriterium aktualisiert."})

    db.session.delete(criterion)
    db.session.commit()
    return jsonify({"success": True, "message": "Kriterium gelöscht."})
