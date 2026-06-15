from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from app import db
from app.models.assessment import (
    AssessmentCriterion,
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentList,
    AssessmentListSubject,
    AssessmentStand,
    AssessmentStandType,
)
from app.utils.assessment_auth import assessment_role_required

from .helpers import (
    current_actor,
    list_to_dict,
    resolve_evaluation_list_from_request,
    stands_for_list,
    subjects_for_list,
    validate_evaluation_target,
)

evaluations_bp = Blueprint("evaluations", __name__)


@evaluations_bp.route("/evaluate", methods=["GET"])
@assessment_role_required(["Administrator", "Bewerter"])
def evaluate_page():
    lists = AssessmentList.query.filter_by(is_active=True).order_by(
        AssessmentList.sort_order.asc(), AssessmentList.name.asc()
    ).all()
    return render_template("assessment/evaluation.html", evaluation_lists=lists)


@evaluations_bp.route("/api/evaluate", methods=["GET", "POST"])
@assessment_role_required(["Administrator", "Bewerter"])
def api_evaluate():
    actor = current_actor()
    evaluation_list = resolve_evaluation_list_from_request(require_active=True)
    if not evaluation_list:
        return jsonify({"success": False, "message": "Bewertungsliste nicht gefunden."}), 404

    if request.method == "GET":
        criteria = (
            AssessmentCriterion.query.filter_by(list_id=evaluation_list.id)
            .order_by(AssessmentCriterion.id.asc())
            .all()
        )
        existing_query = AssessmentEvaluation.query.filter_by(
            user_type=actor["user_type"],
            user_id=actor["user_id"],
            list_id=evaluation_list.id,
        )
        if evaluation_list.subject_mode == "stand":
            targets = stands_for_list(evaluation_list)
            existing_map = {
                item.stand_id: item.id for item in existing_query.all() if item.stand_id
            }
            target_payload = [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "stand_type_name": s.stand_type.name if s.stand_type else None,
                }
                for s in targets
            ]
            target_key = "stands"
        else:
            targets = subjects_for_list(evaluation_list)
            existing_map = {
                item.subject_id: item.id for item in existing_query.all() if item.subject_id
            }
            target_payload = [
                {"id": s.id, "name": s.name, "description": s.description} for s in targets
            ]
            target_key = "subjects"

        return jsonify(
            {
                "success": True,
                "list": list_to_dict(evaluation_list),
                target_key: target_payload,
                "criteria": [{"id": c.id, "name": c.name, "max_score": c.max_score} for c in criteria],
                "existing_evaluations": existing_map,
            }
        )

    data = request.get_json(silent=True) or {}
    list_id = data.get("list_id") or evaluation_list.id
    evaluation_list = AssessmentList.query.get(list_id)
    if not evaluation_list or not evaluation_list.is_active:
        return jsonify({"success": False, "message": "Bewertungsliste nicht gefunden."}), 404

    stand_id = data.get("stand_id")
    subject_id = data.get("subject_id")
    scores = data.get("scores") or {}
    valid, target = validate_evaluation_target(evaluation_list, stand_id=stand_id, subject_id=subject_id)
    if not valid:
        return jsonify({"success": False, "message": target}), 400
    if not isinstance(scores, dict):
        return jsonify({"success": False, "message": "Bewertungen sind erforderlich."}), 400

    eval_query = AssessmentEvaluation.query.filter_by(
        user_type=actor["user_type"],
        user_id=actor["user_id"],
        list_id=evaluation_list.id,
    )
    if evaluation_list.subject_mode == "stand":
        evaluation = eval_query.filter_by(stand_id=stand_id).first()
    else:
        evaluation = eval_query.filter_by(subject_id=subject_id).first()
    if not evaluation:
        evaluation = AssessmentEvaluation(
            user_type=actor["user_type"],
            user_id=actor["user_id"],
            list_id=evaluation_list.id,
            stand_id=stand_id if evaluation_list.subject_mode == "stand" else None,
            subject_id=subject_id if evaluation_list.subject_mode == "custom" else None,
        )
        db.session.add(evaluation)
        db.session.flush()
    else:
        evaluation.timestamp = datetime.utcnow()
        AssessmentEvaluationScore.query.filter_by(evaluation_id=evaluation.id).delete()

    criteria = {
        c.id: c.max_score
        for c in AssessmentCriterion.query.filter_by(list_id=evaluation_list.id).all()
    }
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
    list_id = request.args.get("list_id", type=int)

    query = (
        db.session.query(
            AssessmentEvaluation.id,
            AssessmentEvaluation.timestamp,
            AssessmentEvaluation.list_id,
            AssessmentList.name.label("list_name"),
            AssessmentStand.name.label("stand_name"),
            AssessmentListSubject.name.label("subject_name"),
            func.sum(AssessmentEvaluationScore.score).label("total"),
        )
        .join(AssessmentList, AssessmentList.id == AssessmentEvaluation.list_id)
        .outerjoin(AssessmentStand, AssessmentStand.id == AssessmentEvaluation.stand_id)
        .outerjoin(AssessmentListSubject, AssessmentListSubject.id == AssessmentEvaluation.subject_id)
        .outerjoin(AssessmentEvaluationScore, AssessmentEvaluationScore.evaluation_id == AssessmentEvaluation.id)
        .filter(AssessmentEvaluation.user_type == actor["user_type"], AssessmentEvaluation.user_id == actor["user_id"])
    )
    if list_id:
        query = query.filter(AssessmentEvaluation.list_id == list_id)

    rows = (
        query.group_by(
            AssessmentEvaluation.id,
            AssessmentEvaluation.timestamp,
            AssessmentEvaluation.list_id,
            AssessmentList.name,
            AssessmentStand.name,
            AssessmentListSubject.name,
        )
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
                    "list_id": row.list_id,
                    "list_name": row.list_name,
                    "target_name": row.stand_name or row.subject_name,
                    "total_score": int(row.total or 0),
                }
                for row in rows
            ],
        }
    )


@evaluations_bp.route("/print_blank", methods=["GET"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def blank_print_page():
    evaluation_list = resolve_evaluation_list_from_request(require_active=False)
    if not evaluation_list:
        evaluation_list = AssessmentList.query.order_by(AssessmentList.id.asc()).first()
    if not evaluation_list:
        return render_template("assessment/print_evaluation_template.html", stands=[], criteria=[], evaluation_list=None)

    criteria = AssessmentCriterion.query.filter_by(list_id=evaluation_list.id).order_by(AssessmentCriterion.id.asc()).all()
    if evaluation_list.subject_mode == "stand":
        targets = stands_for_list(evaluation_list)
    else:
        targets = subjects_for_list(evaluation_list)
    return render_template(
        "assessment/print_evaluation_template.html",
        stands=targets,
        criteria=criteria,
        evaluation_list=evaluation_list,
    )


@evaluations_bp.route("/print_evaluation/<int:evaluation_id>")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def print_evaluation(evaluation_id):
    evaluation = AssessmentEvaluation.query.get_or_404(evaluation_id)
    target_name = None
    if evaluation.stand_id:
        stand = AssessmentStand.query.get(evaluation.stand_id)
        target_name = stand.name if stand else None
    elif evaluation.subject_id:
        subject = AssessmentListSubject.query.get(evaluation.subject_id)
        target_name = subject.name if subject else None
    score_rows = (
        db.session.query(AssessmentCriterion.name, AssessmentEvaluationScore.score)
        .join(AssessmentEvaluationScore, AssessmentEvaluationScore.criterion_id == AssessmentCriterion.id)
        .filter(AssessmentEvaluationScore.evaluation_id == evaluation.id)
        .all()
    )
    return render_template(
        "assessment/print_evaluation.html",
        evaluation=evaluation,
        stand_name=target_name,
        score_rows=score_rows,
    )
