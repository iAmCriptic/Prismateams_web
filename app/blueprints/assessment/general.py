from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory
from flask_login import current_user

from app import db
from app.models.assessment import (
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentList,
    AssessmentRoomInspection,
    AssessmentStand,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
    AssessmentWarning,
)
from app.utils.assessment_auth import assessment_role_required, has_section_access

from .helpers import current_actor, get_setting, list_to_dict
from .ranking import SORT_LABELS, _collect_rows, _sort_rows

general_bp = Blueprint("general", __name__)


def _dashboard_stats(actor):
    roles = actor.get("roles") or []
    active_lists = (
        AssessmentList.query.filter_by(is_active=True)
        .order_by(AssessmentList.sort_order.asc(), AssessmentList.name.asc())
        .all()
    )
    primary_list = active_lists[0] if active_lists else None

    stand_count = AssessmentStand.query.count()
    eval_count = AssessmentEvaluation.query.count()
    my_eval_count = 0
    if actor.get("user_type") and actor.get("user_id"):
        my_eval_count = AssessmentEvaluation.query.filter_by(
            user_type=actor["user_type"], user_id=actor["user_id"]
        ).count()

    warning_count = AssessmentWarning.query.count() if has_section_access("warnings", roles) else None
    inspection_count = (
        AssessmentRoomInspection.query.count() if has_section_access("inspections", roles) else None
    )

    ranking_preview = []
    avg_points = None
    sort_mode = "total"
    sort_label = SORT_LABELS["total"]
    if primary_list and has_section_access("ranking", roles):
        sort_mode = (primary_list.ranking_sort or get_setting("ranking_sort_mode") or "total").lower()
        if sort_mode not in SORT_LABELS:
            sort_mode = "total"
        sort_label = SORT_LABELS[sort_mode]
        rows = _sort_rows(_collect_rows(primary_list), sort_mode)
        ranking_preview = rows[:5]
        if rows:
            key = "displayed_avg" if sort_mode == "avg" else "displayed_total"
            vals = [float(r.get(key) or 0) for r in rows if r.get("displayed_votes")]
            if vals:
                avg_points = round(sum(vals) / len(vals), 1)

    return {
        "active_list_count": len(active_lists),
        "stand_count": stand_count,
        "eval_count": eval_count,
        "my_eval_count": my_eval_count,
        "warning_count": warning_count,
        "inspection_count": inspection_count,
        "primary_list": primary_list,
        "ranking_preview": ranking_preview,
        "avg_points": avg_points,
        "sort_mode": sort_mode,
        "sort_label": sort_label,
    }


@general_bp.route("/home")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def home():
    actor = current_actor()
    is_admin = "Administrator" in (actor["roles"] or [])
    stats = _dashboard_stats(actor)
    return render_template("assessment/home.html", is_admin=is_admin, **stats)


@general_bp.route("/api/session_data")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def api_session_data():
    actor = current_actor()
    return jsonify(
        {
            "success": True,
            "logged_in": current_user.is_authenticated,
            "user_type": actor["user_type"],
            "user_id": actor["user_id"],
            "user_roles": actor["roles"],
            "display_name": getattr(current_user, "display_name", getattr(current_user, "full_name", "")),
        }
    )


@general_bp.route("/manage_list", methods=["GET"])
@assessment_role_required(["Administrator"])
def manage_list_page():
    lists = AssessmentList.query.order_by(AssessmentList.sort_order.asc(), AssessmentList.name.asc()).all()
    return render_template("assessment/manage_list.html", evaluation_lists=lists)


@general_bp.route("/api/reset_data", methods=["POST"])
@assessment_role_required(["Administrator"])
def api_reset_data():
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    list_id = data.get("list_id")
    if not action:
        return jsonify({"success": False, "message": "Aktion nicht angegeben."}), 400

    list_filter = {}
    if list_id:
        evaluation_list = AssessmentList.query.get(list_id)
        if not evaluation_list:
            return jsonify({"success": False, "message": "Bewertungsliste nicht gefunden."}), 404
        list_filter = {"list_id": list_id}

    if action == "reset_ranking":
        eval_query = AssessmentEvaluation.query
        visitor_query = AssessmentVisitorEvaluation.query
        if list_filter:
            eval_query = eval_query.filter_by(**list_filter)
            visitor_query = visitor_query.filter_by(**list_filter)
        eval_ids = [e.id for e in eval_query.all()]
        visitor_ids = [v.id for v in visitor_query.all()]
        if eval_ids:
            AssessmentEvaluationScore.query.filter(
                AssessmentEvaluationScore.evaluation_id.in_(eval_ids)
            ).delete(synchronize_session=False)
        if visitor_ids:
            AssessmentVisitorEvaluationScore.query.filter(
                AssessmentVisitorEvaluationScore.visitor_evaluation_id.in_(visitor_ids)
            ).delete(synchronize_session=False)
        eval_query.delete(synchronize_session=False)
        visitor_query.delete(synchronize_session=False)
    elif action == "reset_room_inspections":
        if list_filter:
            return jsonify({"success": False, "message": "Rauminspektionen sind nicht listenbezogen."}), 400
        AssessmentRoomInspection.query.delete()
    elif action == "reset_warnings":
        # Verwarnungen sind listenunabhängig — immer alle löschen
        AssessmentWarning.query.delete(synchronize_session=False)
    else:
        return jsonify({"success": False, "message": "Ungültige Aktion."}), 400

    db.session.commit()
    return jsonify({"success": True, "message": "Daten erfolgreich zurückgesetzt."})


@general_bp.route("/api/lists/active", methods=["GET"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def api_active_lists():
    lists = AssessmentList.query.filter_by(is_active=True).order_by(
        AssessmentList.sort_order.asc(), AssessmentList.name.asc()
    ).all()
    return jsonify({"success": True, "lists": [list_to_dict(item) for item in lists]})


@general_bp.route("/static_files/<path:filename>")
def static_files(filename):
    return send_from_directory(current_app.static_folder, filename)


@general_bp.route("/service-worker.js")
def serve_service_worker():
    return send_from_directory(current_app.root_path, "service-worker.js", mimetype="application/javascript")
