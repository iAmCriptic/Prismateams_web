from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func

from app import db
from app.models.assessment import (
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentRoom,
    AssessmentStand,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
)
from app.utils.assessment_auth import assessment_role_required

from .helpers import get_setting

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


def _collect_rows():
    judge_rows = (
        db.session.query(
            AssessmentStand.id.label("stand_id"),
            AssessmentStand.name.label("stand_name"),
            AssessmentRoom.name.label("room_name"),
            func.coalesce(func.sum(AssessmentEvaluationScore.score), 0).label("judge_total"),
            func.count(func.distinct(AssessmentEvaluation.id)).label("judge_votes"),
        )
        .outerjoin(AssessmentRoom, AssessmentRoom.id == AssessmentStand.room_id)
        .outerjoin(AssessmentEvaluation, AssessmentEvaluation.stand_id == AssessmentStand.id)
        .outerjoin(AssessmentEvaluationScore, AssessmentEvaluationScore.evaluation_id == AssessmentEvaluation.id)
        .group_by(AssessmentStand.id, AssessmentStand.name, AssessmentRoom.name)
        .all()
    )

    visitor_rows = (
        db.session.query(
            AssessmentStand.id.label("stand_id"),
            func.coalesce(func.sum(AssessmentVisitorEvaluationScore.score), 0).label("visitor_total"),
            func.count(func.distinct(AssessmentVisitorEvaluation.id)).label("visitor_votes"),
        )
        .outerjoin(AssessmentVisitorEvaluation, AssessmentVisitorEvaluation.stand_id == AssessmentStand.id)
        .outerjoin(
            AssessmentVisitorEvaluationScore,
            AssessmentVisitorEvaluationScore.visitor_evaluation_id == AssessmentVisitorEvaluation.id,
        )
        .group_by(AssessmentStand.id)
        .all()
    )
    visitor_map = {row.stand_id: row for row in visitor_rows}

    rows = []
    for row in judge_rows:
        v = visitor_map.get(row.stand_id)
        judge_total = int(row.judge_total or 0)
        judge_votes = int(row.judge_votes or 0)
        visitor_total = int(v.visitor_total) if v else 0
        visitor_votes = int(v.visitor_votes) if v else 0
        rows.append(
            {
                "stand_id": row.stand_id,
                "stand_name": row.stand_name,
                "room_name": row.room_name,
                "judge_total": judge_total,
                "judge_votes": judge_votes,
                "judge_avg": (judge_total / judge_votes) if judge_votes else 0.0,
                "visitor_total": visitor_total,
                "visitor_votes": visitor_votes,
                "visitor_avg": (visitor_total / visitor_votes) if visitor_votes else 0.0,
            }
        )
    return rows


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
    return rows


def _sort_rows(rows, sort_mode):
    key = "displayed_avg" if sort_mode == "avg" else "displayed_total"
    return sorted(rows, key=lambda r: r[key], reverse=True)


def _resolve_params(args):
    default_mode = (get_setting("ranking_active_mode") or "standard").lower()
    default_sort = (get_setting("ranking_sort_mode") or "total").lower()
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
    return render_template(
        "assessment/view_ranking.html",
        mode_labels=MODE_LABELS,
        sort_labels=SORT_LABELS,
    )


@ranking_bp.route("/api/ranking")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def api_ranking():
    mode, sort_mode = _resolve_params(request.args)
    rows = _sort_rows(_apply_mode(_collect_rows(), mode), sort_mode)
    return jsonify(
        {
            "success": True,
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
    mode, sort_mode = _resolve_params(request.args)
    rows = _sort_rows(_apply_mode(_collect_rows(), mode), sort_mode)
    return render_template(
        "assessment/print_ranking.html",
        ranking=rows,
        mode_label=MODE_LABELS[mode],
        sort_label=SORT_LABELS[sort_mode],
    )
