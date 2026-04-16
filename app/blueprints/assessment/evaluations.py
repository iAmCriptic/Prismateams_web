from datetime import datetime

from flask import Blueprint, jsonify, make_response, render_template, request
from sqlalchemy import func

from app import db
from app.models.assessment import (
    AssessmentCriterion,
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentStand,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
)
from app.utils.assessment_auth import assessment_role_required

from .helpers import create_visitor_token, current_actor, hash_visitor_token

evaluations_bp = Blueprint("evaluations", __name__)


@evaluations_bp.route("/evaluate", methods=["GET"])
@assessment_role_required(["Administrator", "Bewerter"])
def evaluate_page():
    return render_template("assessment/evaluation.html")


@evaluations_bp.route("/api/evaluate", methods=["GET", "POST"])
@assessment_role_required(["Administrator", "Bewerter"])
def api_evaluate():
    actor = current_actor()
    if request.method == "GET":
        stands = AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()
        criteria = AssessmentCriterion.query.order_by(AssessmentCriterion.id.asc()).all()
        existing = AssessmentEvaluation.query.filter_by(user_type=actor["user_type"], user_id=actor["user_id"]).all()
        existing_map = {item.stand_id: item.id for item in existing}

        return jsonify(
            {
                "success": True,
                "stands": [{"id": s.id, "name": s.name, "description": s.description} for s in stands],
                "criteria": [{"id": c.id, "name": c.name, "max_score": c.max_score} for c in criteria],
                "existing_evaluations": existing_map,
            }
        )

    data = request.get_json(silent=True) or {}
    stand_id = data.get("stand_id")
    scores = data.get("scores") or {}
    if not stand_id or not isinstance(scores, dict):
        return jsonify({"success": False, "message": "Stand und Bewertungen sind erforderlich."}), 400

    evaluation = AssessmentEvaluation.query.filter_by(
        user_type=actor["user_type"], user_id=actor["user_id"], stand_id=stand_id
    ).first()
    if not evaluation:
        evaluation = AssessmentEvaluation(user_type=actor["user_type"], user_id=actor["user_id"], stand_id=stand_id)
        db.session.add(evaluation)
        db.session.flush()
    else:
        evaluation.timestamp = datetime.utcnow()
        AssessmentEvaluationScore.query.filter_by(evaluation_id=evaluation.id).delete()

    criteria = {c.id: c.max_score for c in AssessmentCriterion.query.all()}
    for criterion_id_raw, score in scores.items():
        criterion_id = int(criterion_id_raw)
        if criterion_id not in criteria:
            continue
        try:
            score_value = int(score)
        except (TypeError, ValueError):
            continue
        if 0 <= score_value <= criteria[criterion_id]:
            db.session.add(
                AssessmentEvaluationScore(
                    evaluation_id=evaluation.id,
                    criterion_id=criterion_id,
                    score=score_value,
                )
            )

    db.session.commit()
    return jsonify({"success": True, "message": "Bewertung gespeichert."})


@evaluations_bp.route("/view_my_evaluations")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def view_my_evaluations_page():
    return render_template("assessment/view_my_evaluations.html")


@evaluations_bp.route("/api/my_evaluations")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def api_my_evaluations():
    actor = current_actor()
    rows = (
        db.session.query(
            AssessmentEvaluation.id,
            AssessmentEvaluation.timestamp,
            AssessmentStand.name.label("stand_name"),
            func.sum(AssessmentEvaluationScore.score).label("total"),
        )
        .join(AssessmentStand, AssessmentStand.id == AssessmentEvaluation.stand_id)
        .outerjoin(AssessmentEvaluationScore, AssessmentEvaluationScore.evaluation_id == AssessmentEvaluation.id)
        .filter(AssessmentEvaluation.user_type == actor["user_type"], AssessmentEvaluation.user_id == actor["user_id"])
        .group_by(AssessmentEvaluation.id, AssessmentEvaluation.timestamp, AssessmentStand.name)
        .order_by(AssessmentEvaluation.timestamp.desc())
        .all()
    )
    return jsonify(
        {
            "success": True,
            "evaluations": [
                {
                    "id": row.id,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                    "stand_name": row.stand_name,
                    "total_score": int(row.total or 0),
                }
                for row in rows
            ],
        }
    )


@evaluations_bp.route("/print_blank", methods=["GET"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def blank_print_page():
    stands = AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()
    criteria = AssessmentCriterion.query.order_by(AssessmentCriterion.id.asc()).all()
    return render_template(
        "assessment/print_evaluation_template.html",
        stands=stands,
        criteria=criteria,
    )


@evaluations_bp.route("/print_evaluation/<int:evaluation_id>")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def print_evaluation(evaluation_id):
    evaluation = AssessmentEvaluation.query.get_or_404(evaluation_id)
    stand = AssessmentStand.query.get(evaluation.stand_id)
    score_rows = (
        db.session.query(AssessmentCriterion.name, AssessmentEvaluationScore.score)
        .join(AssessmentEvaluationScore, AssessmentEvaluationScore.criterion_id == AssessmentCriterion.id)
        .filter(AssessmentEvaluationScore.evaluation_id == evaluation.id)
        .all()
    )
    return render_template(
        "assessment/print_evaluation.html",
        evaluation=evaluation,
        stand=stand,
        score_rows=score_rows,
    )


@evaluations_bp.route("/visitor_rate/<int:stand_id>", methods=["GET", "POST"])
def visitor_rate(stand_id):
    stand = AssessmentStand.query.get_or_404(stand_id)
    criteria = AssessmentCriterion.query.order_by(AssessmentCriterion.id.asc()).all()

    if request.method == "GET":
        return render_template("assessment/visitor_rate.html", stand=stand, criteria=criteria)

    data = request.get_json(silent=True) or {}
    scores = data.get("scores") or {}
    token, should_set_cookie = create_visitor_token()
    token_hash = hash_visitor_token(token)

    existing = AssessmentVisitorEvaluation.query.filter_by(stand_id=stand_id, visitor_token_hash=token_hash).first()
    if existing:
        return jsonify({"success": False, "message": "Sie haben diesen Stand bereits bewertet."}), 409

    visitor_eval = AssessmentVisitorEvaluation(
        stand_id=stand_id,
        visitor_token_hash=token_hash,
    )
    db.session.add(visitor_eval)
    db.session.flush()

    criterion_map = {c.id: c.max_score for c in criteria}
    for criterion_id_raw, score_value in scores.items():
        criterion_id = int(criterion_id_raw)
        if criterion_id not in criterion_map:
            continue
        value = int(score_value)
        if 0 <= value <= criterion_map[criterion_id]:
            db.session.add(
                AssessmentVisitorEvaluationScore(
                    visitor_evaluation_id=visitor_eval.id,
                    criterion_id=criterion_id,
                    score=value,
                )
            )

    db.session.commit()
    response = make_response(jsonify({"success": True, "message": "Vielen Dank für Ihre Bewertung."}))
    if should_set_cookie:
        response.set_cookie("assessment_visitor_id", token, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
