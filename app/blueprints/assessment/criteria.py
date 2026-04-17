from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models.assessment import AssessmentCriterion
from app.utils.assessment_auth import assessment_role_required, get_assessment_identity

criteria_bp = Blueprint("criteria", __name__)


@criteria_bp.route("/manage_criteria")
@assessment_role_required(["Administrator"])
def manage_criteria_page():
    return render_template("assessment/manage_criteria.html")


@criteria_bp.route("/api/criteria", methods=["GET", "POST"])
@criteria_bp.route("/api/criteria/<int:criterion_id>", methods=["GET", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def api_criteria(criterion_id=None):
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
                        "name": criterion.name,
                        "max_score": criterion.max_score,
                        "description": criterion.description,
                    },
                }
            )
        criteria = AssessmentCriterion.query.order_by(AssessmentCriterion.name.asc()).all()
        return jsonify(
            {
                "success": True,
                "criteria": [
                    {
                        "id": criterion.id,
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
        name = (data.get("name") or "").strip()
        max_score = int(data.get("max_score") or 0)
        if not name or max_score <= 0:
            return jsonify({"success": False, "message": "Name und gültige Maximalpunktzahl sind erforderlich."}), 400
        criterion = AssessmentCriterion(
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
        criterion.name = (data.get("name") or criterion.name).strip()
        criterion.max_score = int(data.get("max_score") or criterion.max_score)
        criterion.description = (data.get("description") or "").strip() or None
        db.session.commit()
        return jsonify({"success": True, "message": "Kriterium aktualisiert."})

    db.session.delete(criterion)
    db.session.commit()
    return jsonify({"success": True, "message": "Kriterium gelöscht."})
