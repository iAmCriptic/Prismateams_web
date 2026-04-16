import os
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from app import db
from app.models.assessment import AssessmentFloorPlan, AssessmentFloorPlanObject
from app.utils.assessment_auth import assessment_role_required

map_bp = Blueprint("map", __name__)


def _plans_dir():
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "assessment", "floor_plans")
    os.makedirs(folder, exist_ok=True)
    return folder


@map_bp.route("/manage_plan")
@assessment_role_required(["Administrator"])
def manage_plan():
    return render_template("assessment/manage_plan.html")


@map_bp.route("/view_plan")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def view_plan():
    return render_template("assessment/view_plan.html")


@map_bp.route("/api/floor_plans", methods=["GET", "POST", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def floor_plans_api():
    if request.method == "GET":
        plans = AssessmentFloorPlan.query.order_by(AssessmentFloorPlan.id.desc()).all()
        return jsonify(
            {
                "success": True,
                "plans": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "image_path": p.image_path,
                        "is_active": p.is_active,
                        "width_px": p.width_px,
                        "height_px": p.height_px,
                    }
                    for p in plans
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        plan = AssessmentFloorPlan(name=data.get("name"), image_path=data.get("image_path"), is_active=False)
        db.session.add(plan)
        db.session.commit()
        return jsonify({"success": True, "id": plan.id})

    if request.method == "PUT":
        plan = AssessmentFloorPlan.query.get(data.get("id"))
        if not plan:
            return jsonify({"success": False, "message": "Plan nicht gefunden."}), 404
        for field in [
            "name",
            "image_path",
            "width_px",
            "height_px",
            "scale_point1_x",
            "scale_point1_y",
            "scale_point2_x",
            "scale_point2_y",
            "scale_distance_meters",
        ]:
            if field in data:
                setattr(plan, field, data[field])
        if data.get("is_active"):
            AssessmentFloorPlan.query.update({"is_active": False})
            plan.is_active = True
        db.session.commit()
        return jsonify({"success": True, "message": "Plan aktualisiert."})

    plan = AssessmentFloorPlan.query.get(data.get("id"))
    if not plan:
        return jsonify({"success": False, "message": "Plan nicht gefunden."}), 404
    db.session.delete(plan)
    db.session.commit()
    return jsonify({"success": True, "message": "Plan gelöscht."})


@map_bp.route("/api/floor_plan_objects", methods=["GET", "POST", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def floor_plan_objects_api():
    if request.method == "GET":
        plan_id = request.args.get("plan_id", type=int)
        query = AssessmentFloorPlanObject.query
        if plan_id:
            query = query.filter_by(plan_id=plan_id)
        objects = query.all()
        return jsonify(
            {
                "success": True,
                "objects": [
                    {
                        "id": obj.id,
                        "plan_id": obj.plan_id,
                        "type": obj.type,
                        "x": obj.x,
                        "y": obj.y,
                        "width": obj.width,
                        "height": obj.height,
                        "color": obj.color,
                        "trash_can_color": obj.trash_can_color,
                        "wc_label": obj.wc_label,
                        "power_outlet_label": obj.power_outlet_label,
                        "stand_id": obj.stand_id,
                        "custom_stand_name": obj.custom_stand_name,
                    }
                    for obj in objects
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        obj = AssessmentFloorPlanObject(**data)
        db.session.add(obj)
        db.session.commit()
        return jsonify({"success": True, "id": obj.id})

    if request.method == "PUT":
        obj = AssessmentFloorPlanObject.query.get(data.get("id"))
        if not obj:
            return jsonify({"success": False, "message": "Objekt nicht gefunden."}), 404
        for key, value in data.items():
            if hasattr(obj, key) and key != "id":
                setattr(obj, key, value)
        db.session.commit()
        return jsonify({"success": True})

    obj = AssessmentFloorPlanObject.query.get(data.get("id"))
    if not obj:
        return jsonify({"success": False, "message": "Objekt nicht gefunden."}), 404
    db.session.delete(obj)
    db.session.commit()
    return jsonify({"success": True})


@map_bp.route("/api/upload_floor_plan", methods=["POST"])
@assessment_role_required(["Administrator"])
def upload_floor_plan():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"success": False, "message": "Keine Datei hochgeladen."}), 400
    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "gif", "svg", "webp"}:
        return jsonify({"success": False, "message": "Dateityp nicht erlaubt."}), 400
    saved_name = f"{uuid4().hex}.{ext}"
    file.save(os.path.join(_plans_dir(), saved_name))
    return jsonify({"success": True, "image_path": f"/assessment/uploads/plans/{saved_name}"})


@map_bp.route("/uploads/plans/<path:filename>")
def serve_uploaded_plans(filename):
    return send_from_directory(_plans_dir(), filename)
