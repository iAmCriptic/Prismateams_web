from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func

from app import db
from app.models.assessment import (
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentList,
    AssessmentListSubject,
    AssessmentRoom,
    AssessmentStand,
    AssessmentStandType,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
)
from app.utils.assessment_auth import assessment_role_required

from .helpers import get_evaluation_list, get_setting, list_to_dict, resolve_evaluation_list_from_request, stands_for_list

ranking_bp = Blueprint("ranking", __name__)


MODE_LABELS = {
    "standard": "Standard (Jury)",
    "visitor": "Besucherrangliste",
    "combined": "Kombiniert (50/50)",
}
SORT_LABELS = {
    "total": "Gesamtpunktzahl",
    "avg": "Ø-Punktzahl",
}


def _collect_stand_rows(evaluation_list):
    list_id = evaluation_list.id
    stand_ids = [s.id for s in stands_for_list(evaluation_list)]
    if not stand_ids:
        return []

    judge_rows = (
        db.session.query(
            AssessmentStand.id.label("target_id"),
            AssessmentStand.name.label("target_name"),
            AssessmentRoom.name.label("room_name"),
            AssessmentStandType.name.label("stand_type_name"),
            func.coalesce(func.sum(AssessmentEvaluationScore.score), 0).label("judge_total"),
            func.count(func.distinct(AssessmentEvaluation.id)).label("judge_votes"),
        )
        .filter(AssessmentStand.id.in_(stand_ids))
        .outerjoin(AssessmentStandType, AssessmentStandType.id == AssessmentStand.stand_type_id)
        .outerjoin(AssessmentRoom, AssessmentRoom.id == AssessmentStand.room_id)
        .outerjoin(
            AssessmentEvaluation,
            (AssessmentEvaluation.stand_id == AssessmentStand.id) & (AssessmentEvaluation.list_id == list_id),
        )
        .outerjoin(AssessmentEvaluationScore, AssessmentEvaluationScore.evaluation_id == AssessmentEvaluation.id)
        .group_by(AssessmentStand.id, AssessmentStand.name, AssessmentRoom.name, AssessmentStandType.name)
        .all()
    )

    visitor_rows = (
        db.session.query(
            AssessmentStand.id.label("target_id"),
            func.coalesce(func.sum(AssessmentVisitorEvaluationScore.score), 0).label("visitor_total"),
            func.count(func.distinct(AssessmentVisitorEvaluation.id)).label("visitor_votes"),
        )
        .filter(AssessmentStand.id.in_(stand_ids))
        .outerjoin(
            AssessmentVisitorEvaluation,
            (AssessmentVisitorEvaluation.stand_id == AssessmentStand.id)
            & (AssessmentVisitorEvaluation.list_id == list_id),
        )
        .outerjoin(
            AssessmentVisitorEvaluationScore,
            AssessmentVisitorEvaluationScore.visitor_evaluation_id == AssessmentVisitorEvaluation.id,
        )
        .group_by(AssessmentStand.id)
        .all()
    )
    visitor_map = {row.target_id: row for row in visitor_rows}

    rows = []
    for row in judge_rows:
        v = visitor_map.get(row.target_id)
        judge_total = int(row.judge_total or 0)
        judge_votes = int(row.judge_votes or 0)
        visitor_total = int(v.visitor_total) if v else 0
        visitor_votes = int(v.visitor_votes) if v else 0
        rows.append(
            {
                "target_id": row.target_id,
                "target_name": row.target_name,
                "room_name": row.room_name,
                "stand_type_name": row.stand_type_name,
                "judge_total": judge_total,
                "judge_votes": judge_votes,
                "judge_avg": (judge_total / judge_votes) if judge_votes else 0.0,
                "visitor_total": visitor_total,
                "visitor_votes": visitor_votes,
                "visitor_avg": (visitor_total / visitor_votes) if visitor_votes else 0.0,
            }
        )
    return rows


def _collect_subject_rows(evaluation_list):
    list_id = evaluation_list.id
    subjects = AssessmentListSubject.query.filter_by(list_id=list_id, is_active=True).all()
    if not subjects:
        return []

    subject_ids = [s.id for s in subjects]
    judge_rows = (
        db.session.query(
            AssessmentListSubject.id.label("target_id"),
            AssessmentListSubject.name.label("target_name"),
            func.coalesce(func.sum(AssessmentEvaluationScore.score), 0).label("judge_total"),
            func.count(func.distinct(AssessmentEvaluation.id)).label("judge_votes"),
        )
        .filter(AssessmentListSubject.id.in_(subject_ids))
        .outerjoin(
            AssessmentEvaluation,
            (AssessmentEvaluation.subject_id == AssessmentListSubject.id)
            & (AssessmentEvaluation.list_id == list_id),
        )
        .outerjoin(AssessmentEvaluationScore, AssessmentEvaluationScore.evaluation_id == AssessmentEvaluation.id)
        .group_by(AssessmentListSubject.id, AssessmentListSubject.name)
        .all()
    )

    visitor_rows = (
        db.session.query(
            AssessmentListSubject.id.label("target_id"),
            func.coalesce(func.sum(AssessmentVisitorEvaluationScore.score), 0).label("visitor_total"),
            func.count(func.distinct(AssessmentVisitorEvaluation.id)).label("visitor_votes"),
        )
        .filter(AssessmentListSubject.id.in_(subject_ids))
        .outerjoin(
            AssessmentVisitorEvaluation,
            (AssessmentVisitorEvaluation.subject_id == AssessmentListSubject.id)
            & (AssessmentVisitorEvaluation.list_id == list_id),
        )
        .outerjoin(
            AssessmentVisitorEvaluationScore,
            AssessmentVisitorEvaluationScore.visitor_evaluation_id == AssessmentVisitorEvaluation.id,
        )
        .group_by(AssessmentListSubject.id)
        .all()
    )
    visitor_map = {row.target_id: row for row in visitor_rows}

    rows = []
    for row in judge_rows:
        v = visitor_map.get(row.target_id)
        judge_total = int(row.judge_total or 0)
        judge_votes = int(row.judge_votes or 0)
        visitor_total = int(v.visitor_total) if v else 0
        visitor_votes = int(v.visitor_votes) if v else 0
        rows.append(
            {
                "target_id": row.target_id,
                "target_name": row.target_name,
                "room_name": None,
                "stand_type_name": None,
                "judge_total": judge_total,
                "judge_votes": judge_votes,
                "judge_avg": (judge_total / judge_votes) if judge_votes else 0.0,
                "visitor_total": visitor_total,
                "visitor_votes": visitor_votes,
                "visitor_avg": (visitor_total / visitor_votes) if visitor_votes else 0.0,
            }
        )
    return rows


def _collect_rows(evaluation_list):
    if evaluation_list.subject_mode == "custom":
        return _collect_subject_rows(evaluation_list)
    return _collect_stand_rows(evaluation_list)


def _apply_mode(rows, mode):
    for row in rows:
        if mode == "visitor":
            row["displayed_total"] = row["visitor_total"]
            row["displayed_avg"] = row["visitor_avg"]
            row["displayed_votes"] = row["visitor_votes"]
        elif mode == "combined":
            row["displayed_total"] = row["judge_total"] + row["visitor_total"]
            row["displayed_avg"] = (row["judge_avg"] + row["visitor_avg"]) / 2
            row["displayed_votes"] = row["judge_votes"] + row["visitor_votes"]
        else:
            row["displayed_total"] = row["judge_total"]
            row["displayed_avg"] = row["judge_avg"]
            row["displayed_votes"] = row["judge_votes"]
        row["stand_name"] = row["target_name"]
        row["stand_id"] = row["target_id"]
    return rows


def _sort_rows(rows, sort_mode):
    key = "displayed_avg" if sort_mode == "avg" else "displayed_total"
    return sorted(rows, key=lambda r: r[key], reverse=True)


def _resolve_params(args, evaluation_list):
    default_mode = (evaluation_list.ranking_mode or get_setting("ranking_active_mode") or "standard").lower()
    default_sort = (evaluation_list.ranking_sort or get_setting("ranking_sort_mode") or "total").lower()
    mode = (args.get("mode") or default_mode).lower()
    sort_mode = (args.get("sort") or default_sort).lower()
    if mode not in MODE_LABELS:
        mode = default_mode if default_mode in MODE_LABELS else "standard"
    if sort_mode not in SORT_LABELS:
        sort_mode = default_sort if default_sort in SORT_LABELS else "total"
    return mode, sort_mode


@ranking_bp.route("/view_ranking")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def view_ranking():
    lists = AssessmentList.query.filter_by(is_active=True).order_by(
        AssessmentList.sort_order.asc(), AssessmentList.name.asc()
    ).all()
    return render_template(
        "assessment/view_ranking.html",
        mode_labels=MODE_LABELS,
        sort_labels=SORT_LABELS,
        evaluation_lists=lists,
    )


@ranking_bp.route("/api/ranking")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def api_ranking():
    evaluation_list = resolve_evaluation_list_from_request(require_active=True)
    if not evaluation_list:
        return jsonify({"success": False, "message": "Bewertungsliste nicht gefunden."}), 404
    mode, sort_mode = _resolve_params(request.args, evaluation_list)
    rows = _sort_rows(_apply_mode(_collect_rows(evaluation_list), mode), sort_mode)
    return jsonify(
        {
            "success": True,
            "list": list_to_dict(evaluation_list),
            "mode": mode,
            "mode_label": MODE_LABELS[mode],
            "sort_mode": sort_mode,
            "sort_label": SORT_LABELS[sort_mode],
            "ranking": rows,
        }
    )


@ranking_bp.route("/print_ranking")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def print_ranking():
    evaluation_list = resolve_evaluation_list_from_request(require_active=True)
    if not evaluation_list:
        evaluation_list = AssessmentList.query.first()
    mode, sort_mode = _resolve_params(request.args, evaluation_list) if evaluation_list else ("standard", "total")
    rows = _sort_rows(_apply_mode(_collect_rows(evaluation_list), mode), sort_mode) if evaluation_list else []
    return render_template(
        "assessment/print_ranking.html",
        ranking=rows,
        mode_label=MODE_LABELS.get(mode, mode),
        sort_label=SORT_LABELS.get(sort_mode, sort_mode),
        evaluation_list=evaluation_list,
    )
