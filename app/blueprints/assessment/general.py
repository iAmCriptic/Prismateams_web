from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory
from flask_login import current_user

from app import db
from app.models.assessment import (
    AssessmentCriterion,
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentList,
    AssessmentListSubject,
    AssessmentRoom,
    AssessmentRoomInspection,
    AssessmentStand,
    AssessmentUser,
    AssessmentUserList,
    AssessmentUserRole,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
    AssessmentWarning,
)
from app.utils.assessment_auth import assessment_role_required, has_section_access

from .helpers import current_actor, get_setting, list_to_dict, lists_for_actor
from .ranking import SORT_LABELS, _collect_rows, _sort_rows

general_bp = Blueprint("general", __name__)


def _dashboard_stats(actor):
    roles = actor.get("roles") or []
    active_lists = lists_for_actor(actor, require_active=True)
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
    lists = lists_for_actor(require_active=False)
    return render_template("assessment/manage_list.html", evaluation_lists=lists)


def _wipe_evaluations(*, list_id=None, stand_ids=None):
    eval_query = AssessmentEvaluation.query
    visitor_query = AssessmentVisitorEvaluation.query
    if list_id is not None:
        eval_query = eval_query.filter_by(list_id=list_id)
        visitor_query = visitor_query.filter_by(list_id=list_id)
    if stand_ids is not None:
        if not stand_ids:
            return
        eval_query = eval_query.filter(AssessmentEvaluation.stand_id.in_(stand_ids))
        visitor_query = visitor_query.filter(AssessmentVisitorEvaluation.stand_id.in_(stand_ids))
    eval_ids = [item.id for item in eval_query.all()]
    visitor_ids = [item.id for item in visitor_query.all()]
    if eval_ids:
        AssessmentEvaluationScore.query.filter(
            AssessmentEvaluationScore.evaluation_id.in_(eval_ids)
        ).delete(synchronize_session=False)
        AssessmentEvaluation.query.filter(AssessmentEvaluation.id.in_(eval_ids)).delete(
            synchronize_session=False
        )
    if visitor_ids:
        AssessmentVisitorEvaluationScore.query.filter(
            AssessmentVisitorEvaluationScore.visitor_evaluation_id.in_(visitor_ids)
        ).delete(synchronize_session=False)
        AssessmentVisitorEvaluation.query.filter(
            AssessmentVisitorEvaluation.id.in_(visitor_ids)
        ).delete(synchronize_session=False)


GLOBAL_RESET_ACTIONS = {
    "reset_warnings",
    "reset_room_inspections",
    "reset_accounts",
    "reset_stands",
    "reset_criteria_lists",
    "reset_rooms",
}


@general_bp.route("/api/reset_data", methods=["POST"])
@assessment_role_required(["Administrator"])
def api_reset_data():
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    list_id = data.get("list_id")
    if not action:
        return jsonify({"success": False, "message": "Aktion nicht angegeben."}), 400

    if action in GLOBAL_RESET_ACTIONS:
        list_id = None

    list_filter = {}
    if list_id:
        evaluation_list = AssessmentList.query.get(list_id)
        if not evaluation_list:
            return jsonify({"success": False, "message": "Bewertungsliste nicht gefunden."}), 404
        list_filter = {"list_id": list_id}

    if action == "reset_ranking":
        _wipe_evaluations(list_id=list_id if list_filter else None)
    elif action == "reset_room_inspections":
        AssessmentRoomInspection.query.delete(synchronize_session=False)
    elif action == "reset_warnings":
        AssessmentWarning.query.delete(synchronize_session=False)
    elif action == "reset_accounts":
        actor = current_actor()
        keep_id = actor["user_id"] if actor.get("user_type") == "ass" and actor.get("user_id") else None
        query = AssessmentUser.query
        if keep_id is not None:
            query = query.filter(AssessmentUser.id != keep_id)
        user_ids = [user.id for user in query.all()]
        if user_ids:
            AssessmentUserRole.query.filter(AssessmentUserRole.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            AssessmentUserList.query.filter(AssessmentUserList.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            AssessmentUser.query.filter(AssessmentUser.id.in_(user_ids)).delete(synchronize_session=False)
    elif action == "reset_stands":
        stand_ids = [stand.id for stand in AssessmentStand.query.all()]
        _wipe_evaluations(stand_ids=stand_ids)
        if stand_ids:
            AssessmentWarning.query.filter(AssessmentWarning.stand_id.in_(stand_ids)).delete(
                synchronize_session=False
            )
        AssessmentStand.query.delete(synchronize_session=False)
    elif action == "reset_criteria_lists":
        _wipe_evaluations()
        AssessmentUserList.query.delete(synchronize_session=False)
        AssessmentEvaluationScore.query.delete(synchronize_session=False)
        AssessmentVisitorEvaluationScore.query.delete(synchronize_session=False)
        AssessmentCriterion.query.delete(synchronize_session=False)
        AssessmentWarning.query.update({AssessmentWarning.list_id: None, AssessmentWarning.subject_id: None}, synchronize_session=False)
        AssessmentListSubject.query.delete(synchronize_session=False)
        AssessmentList.query.delete(synchronize_session=False)
    elif action == "reset_rooms":
        AssessmentRoomInspection.query.delete(synchronize_session=False)
        AssessmentStand.query.update({AssessmentStand.room_id: None}, synchronize_session=False)
        AssessmentRoom.query.delete(synchronize_session=False)
    else:
        return jsonify({"success": False, "message": "Ungültige Aktion."}), 400

    db.session.commit()
    return jsonify({"success": True, "message": "Daten erfolgreich zurückgesetzt."})


@general_bp.route("/api/lists/active", methods=["GET"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def api_active_lists():
    lists = lists_for_actor(require_active=True)
    return jsonify({"success": True, "lists": [list_to_dict(item) for item in lists]})


@general_bp.route("/static_files/<path:filename>")
def static_files(filename):
    return send_from_directory(current_app.static_folder, filename)


@general_bp.route("/service-worker.js")
def serve_service_worker():
    return send_from_directory(current_app.root_path, "service-worker.js", mimetype="application/javascript")
