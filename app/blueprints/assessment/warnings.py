from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, send_file

from app import db
from app.models.assessment import AssessmentStand, AssessmentWarning
from app.utils.assessment_auth import assessment_role_required
from app.utils.assessment_pdf import generate_warnings_pdf
from app.utils.i18n import _

from .helpers import current_actor

warnings_bp = Blueprint("warnings", __name__)


def _warnings_payload():
    warnings = AssessmentWarning.query.order_by(AssessmentWarning.timestamp.desc()).all()
    return [
        {
            "id": w.id,
            "list_id": w.list_id,
            "stand_id": w.stand_id,
            "subject_id": w.subject_id,
            "target_name": (w.stand.name if w.stand else None)
            or (w.subject.name if w.subject else None),
            "comment": w.comment,
            "timestamp": w.timestamp.isoformat() if w.timestamp else None,
            "is_invalidated": w.is_invalidated,
            "invalidation_comment": w.invalidation_comment,
        }
        for w in warnings
    ]


@warnings_bp.route("/")
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_page():
    return render_template("assessment/warnings.html")


@warnings_bp.route("/pdf/warnings")
@assessment_role_required(["Administrator", "Verwarner"])
def pdf_warnings():
    pdf = generate_warnings_pdf(_warnings_payload())
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="verwarnungen.pdf",
    )


@warnings_bp.route("/api/items", methods=["GET", "POST", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Verwarner"])
def warnings_api():
    actor = current_actor()

    if request.method == "GET":
        targets = [
            {"id": s.id, "name": s.name}
            for s in AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()
        ]
        return jsonify(
            {
                "success": True,
                "subject_mode": "stand",
                "warnings": _warnings_payload(),
                "targets": targets,
            }
        )

    data = request.get_json(silent=True) or {}

    if request.method == "POST":
        stand_id = data.get("stand_id")
        stand = AssessmentStand.query.get(stand_id) if stand_id else None
        if not stand:
            return jsonify({"success": False, "message": _("assessment.warnings.err_stand")}), 400

        comment = (data.get("comment") or "").strip()
        if not comment:
            return jsonify({"success": False, "message": _("assessment.warnings.err_comment")}), 400

        warning = AssessmentWarning(
            list_id=None,
            stand_id=stand.id,
            subject_id=None,
            user_type=actor["user_type"],
            user_id=actor["user_id"],
            comment=comment,
        )
        db.session.add(warning)
        db.session.commit()
        return jsonify({"success": True, "message": _("assessment.warnings.saved")})

    warning_id = data.get("id")
    warning = AssessmentWarning.query.get(warning_id) if warning_id else None
    if not warning:
        return jsonify({"success": False, "message": _("assessment.warnings.err_not_found")}), 404

    if request.method == "DELETE":
        db.session.delete(warning)
        db.session.commit()
        return jsonify({"success": True, "message": _("assessment.warnings.deleted")})

    action = (data.get("action") or "update").strip().lower()

    if action == "invalidate":
        warning.is_invalidated = True
        warning.invalidation_comment = (data.get("invalidation_comment") or "").strip() or None
        warning.invalidation_timestamp = datetime.utcnow()
        warning.invalidated_by_user_id = actor["user_id"]
        db.session.commit()
        return jsonify({"success": True, "message": _("assessment.warnings.lifted")})

    if action == "reinstate":
        warning.is_invalidated = False
        warning.invalidation_comment = None
        warning.invalidation_timestamp = None
        warning.invalidated_by_user_id = None
        db.session.commit()
        return jsonify({"success": True, "message": _("assessment.warnings.reinstated")})

    if action == "update":
        comment = (data.get("comment") or "").strip()
        if not comment:
            return jsonify({"success": False, "message": _("assessment.warnings.err_comment")}), 400
        stand_id = data.get("stand_id")
        if stand_id is not None:
            stand = AssessmentStand.query.get(stand_id)
            if not stand:
                return jsonify({"success": False, "message": _("assessment.warnings.err_stand")}), 400
            warning.stand_id = stand.id
            warning.subject_id = None
        warning.comment = comment
        db.session.commit()
        return jsonify({"success": True, "message": _("assessment.warnings.updated")})

    return jsonify({"success": False, "message": _("assessment.warnings.err_action")}), 400
