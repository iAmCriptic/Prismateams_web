from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from app import db
from app.models.assessment import (
    AssessmentCriterion,
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentList,
    AssessmentListSubject,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
    AssessmentWarning,
)
from app.blueprints.assessment.helpers import list_to_dict
from app.utils.assessment_auth import assessment_role_required

lists_bp = Blueprint("lists", __name__)


@lists_bp.route("/manage_lists")
@assessment_role_required(["Administrator"])
def manage_lists_page():
    return render_template("assessment/manage_lists.html")


@lists_bp.route("/manage_lists/<int:list_id>/subjects")
@assessment_role_required(["Administrator"])
def manage_list_subjects_page(list_id):
    evaluation_list = AssessmentList.query.get_or_404(list_id)
    if evaluation_list.subject_mode != "custom":
        return redirect(url_for("assessment.lists.manage_lists_page"))
    return render_template(
        "assessment/manage_list_subjects.html",
        evaluation_list=evaluation_list,
    )


@lists_bp.route("/api/lists", methods=["GET", "POST"])
@lists_bp.route("/api/lists/<int:list_id>", methods=["GET", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter"])
def api_lists(list_id=None):
    if request.method == "GET":
        if list_id:
            evaluation_list = AssessmentList.query.get(list_id)
            if not evaluation_list:
                return jsonify({"success": False, "message": "Liste nicht gefunden."}), 404
            payload = list_to_dict(evaluation_list, include_filter=True)
            payload["criteria_count"] = AssessmentCriterion.query.filter_by(list_id=list_id).count()
            payload["subjects_count"] = AssessmentListSubject.query.filter_by(list_id=list_id).count()
            return jsonify({"success": True, "list": payload})

        lists = AssessmentList.query.order_by(
            AssessmentList.sort_order.asc(), AssessmentList.name.asc()
        ).all()
        return jsonify(
            {
                "success": True,
                "lists": [list_to_dict(item, include_filter=True) for item in lists],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "Name ist erforderlich."}), 400
        subject_mode = (data.get("subject_mode") or "stand").strip()
        if subject_mode not in ("stand", "custom"):
            return jsonify({"success": False, "message": "Ungültiger Listenmodus."}), 400

        evaluation_list = AssessmentList(
            name=name,
            slug=AssessmentList.make_slug(name),
            description=(data.get("description") or "").strip() or None,
            subject_mode=subject_mode,
            is_active=bool(data.get("is_active", True)),
            sort_order=int(data.get("sort_order") or 0),
            enable_visitor_rating=bool(data.get("enable_visitor_rating", True)),
            ranking_mode=(data.get("ranking_mode") or "standard").strip(),
            ranking_sort=(data.get("ranking_sort") or "total").strip(),
            welcome_label=(data.get("welcome_label") or "").strip() or None,
        )
        evaluation_list.set_stand_type_id_list(data.get("stand_type_ids") or [])
        db.session.add(evaluation_list)
        db.session.commit()
        return jsonify({"success": True, "message": "Bewertungsliste erstellt.", "list_id": evaluation_list.id})

    evaluation_list = AssessmentList.query.get(list_id)
    if not evaluation_list:
        return jsonify({"success": False, "message": "Liste nicht gefunden."}), 404

    if request.method == "PUT":
        name = (data.get("name") or evaluation_list.name).strip()
        evaluation_list.name = name
        if data.get("slug"):
            evaluation_list.slug = AssessmentList.make_slug(data["slug"], exclude_id=list_id)
        evaluation_list.description = (data.get("description") or "").strip() or None
        if "subject_mode" in data:
            mode = (data.get("subject_mode") or "").strip()
            if mode in ("stand", "custom"):
                evaluation_list.subject_mode = mode
        if "stand_type_ids" in data:
            evaluation_list.set_stand_type_id_list(data.get("stand_type_ids") or [])
        if "is_active" in data:
            evaluation_list.is_active = bool(data.get("is_active"))
        if "sort_order" in data:
            evaluation_list.sort_order = int(data.get("sort_order") or 0)
        if "enable_visitor_rating" in data:
            evaluation_list.enable_visitor_rating = bool(data.get("enable_visitor_rating"))
        if data.get("ranking_mode"):
            evaluation_list.ranking_mode = data["ranking_mode"].strip()
        if data.get("ranking_sort"):
            evaluation_list.ranking_sort = data["ranking_sort"].strip()
        evaluation_list.welcome_label = (data.get("welcome_label") or "").strip() or None
        db.session.commit()
        return jsonify({"success": True, "message": "Bewertungsliste aktualisiert."})

    AssessmentCriterion.query.filter_by(list_id=list_id).delete()
    AssessmentListSubject.query.filter_by(list_id=list_id).delete()
    db.session.delete(evaluation_list)
    db.session.commit()
    return jsonify({"success": True, "message": "Bewertungsliste gelöscht."})


@lists_bp.route("/api/lists/<int:list_id>/subjects", methods=["GET", "POST"])
@lists_bp.route("/api/lists/<int:list_id>/subjects/<int:subject_id>", methods=["GET", "PUT", "DELETE"])
@assessment_role_required(["Administrator"])
def api_list_subjects(list_id, subject_id=None):
    evaluation_list = AssessmentList.query.get(list_id)
    if not evaluation_list:
        return jsonify({"success": False, "message": "Liste nicht gefunden."}), 404
    if evaluation_list.subject_mode != "custom":
        return jsonify({"success": False, "message": "Diese Liste verwendet keine eigenen Bewertungsziele."}), 400

    if request.method == "GET":
        if subject_id:
            subject = AssessmentListSubject.query.filter_by(id=subject_id, list_id=list_id).first()
            if not subject:
                return jsonify({"success": False, "message": "Ziel nicht gefunden."}), 404
            return jsonify(
                {
                    "success": True,
                    "subject": {
                        "id": subject.id,
                        "name": subject.name,
                        "description": subject.description,
                        "sort_order": subject.sort_order,
                        "is_active": subject.is_active,
                    },
                }
            )
        subjects = AssessmentListSubject.query.filter_by(list_id=list_id).order_by(
            AssessmentListSubject.sort_order.asc(), AssessmentListSubject.name.asc()
        ).all()
        return jsonify(
            {
                "success": True,
                "subjects": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "sort_order": s.sort_order,
                        "is_active": s.is_active,
                    }
                    for s in subjects
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "Name ist erforderlich."}), 400
        subject = AssessmentListSubject(
            list_id=list_id,
            name=name,
            description=(data.get("description") or "").strip() or None,
            sort_order=int(data.get("sort_order") or 0),
            is_active=bool(data.get("is_active", True)),
        )
        db.session.add(subject)
        db.session.commit()
        return jsonify({"success": True, "message": "Bewertungsziel erstellt."})

    subject = AssessmentListSubject.query.filter_by(id=subject_id, list_id=list_id).first()
    if not subject:
        return jsonify({"success": False, "message": "Ziel nicht gefunden."}), 404

    if request.method == "PUT":
        subject.name = (data.get("name") or subject.name).strip()
        subject.description = (data.get("description") or "").strip() or None
        if "sort_order" in data:
            subject.sort_order = int(data.get("sort_order") or 0)
        if "is_active" in data:
            subject.is_active = bool(data.get("is_active"))
        db.session.commit()
        return jsonify({"success": True, "message": "Bewertungsziel aktualisiert."})

    db.session.delete(subject)
    db.session.commit()
    return jsonify({"success": True, "message": "Bewertungsziel gelöscht."})
