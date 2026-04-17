import math
import os
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from app import db
from app.models.assessment import (
    AssessmentFloorPlan,
    AssessmentFloorPlanObject,
    AssessmentStand,
)
from app.utils.assessment_auth import assessment_role_required


map_bp = Blueprint("map", __name__)


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}


def _plans_dir():
    base = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isabs(base):
        base = os.path.abspath(base)
    target = os.path.join(base, "assessment", "floor_plans")
    os.makedirs(target, exist_ok=True)
    return target


def _allowed_filename(filename):
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS


def _remove_stored_image(stored_name):
    if not stored_name:
        return
    path = os.path.join(_plans_dir(), stored_name)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _extract_stored_name(image_path):
    if not image_path:
        return None
    return os.path.basename(image_path.rstrip("/"))


def _plan_image_url(plan):
    stored_name = _extract_stored_name(plan.image_path) if plan else None
    if not stored_name:
        return None
    return url_for("assessment.map.serve_uploaded_plans", filename=stored_name)


def _compute_pixels_per_meter(plan):
    if (
        plan.scale_point1_x is None
        or plan.scale_point1_y is None
        or plan.scale_point2_x is None
        or plan.scale_point2_y is None
        or not plan.scale_distance_meters
    ):
        return None
    dx = plan.scale_point2_x - plan.scale_point1_x
    dy = plan.scale_point2_y - plan.scale_point1_y
    distance_px = math.hypot(dx, dy)
    if distance_px <= 0 or plan.scale_distance_meters <= 0:
        return None
    return distance_px / plan.scale_distance_meters


def _plan_to_dict(plan):
    if not plan:
        return None
    return {
        "id": plan.id,
        "name": plan.name,
        "image_path": plan.image_path,
        "image_url": _plan_image_url(plan),
        "is_active": bool(plan.is_active),
        "width_px": plan.width_px,
        "height_px": plan.height_px,
        "scale_point1_x": plan.scale_point1_x,
        "scale_point1_y": plan.scale_point1_y,
        "scale_point2_x": plan.scale_point2_x,
        "scale_point2_y": plan.scale_point2_y,
        "scale_distance_meters": plan.scale_distance_meters,
        "pixels_per_meter": _compute_pixels_per_meter(plan),
    }


def _object_to_dict(obj, stand_lookup=None):
    stand_lookup = stand_lookup or {}
    stand_name = stand_lookup.get(obj.stand_id) if obj.stand_id else None
    return {
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
        "stand_name": stand_name,
        "custom_stand_name": obj.custom_stand_name,
    }


@map_bp.route("/manage_plan")
@assessment_role_required(["Administrator"])
def manage_plan():
    return render_template("assessment/manage_plan.html")


@map_bp.route("/view_plan")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def view_plan():
    return render_template("assessment/view_plan.html")


# -----------------------------------------------------------------------------
# Bereichs-spezifische API, die direkt vom Konva-Editor genutzt wird.
# -----------------------------------------------------------------------------

@map_bp.route("/api/upload_floor_plan", methods=["POST"])
@assessment_role_required(["Administrator"])
def upload_floor_plan():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"success": False, "message": "Keine Datei hochgeladen."}), 400
    if not _allowed_filename(file.filename):
        return jsonify({"success": False, "message": "Dateityp nicht erlaubt."}), 400

    original_name = secure_filename(file.filename)
    ext = original_name.rsplit(".", 1)[-1].lower()
    stored_name = f"{uuid4().hex}.{ext}"
    file.save(os.path.join(_plans_dir(), stored_name))
    image_path = url_for("assessment.map.serve_uploaded_plans", filename=stored_name)

    existing = AssessmentFloorPlan.query.filter_by(name=original_name).first()
    # Alle aktiven Pläne deaktivieren.
    AssessmentFloorPlan.query.update({"is_active": False})

    if existing:
        # Alte Bilddatei entfernen, falls unterschiedlich.
        old_stored = _extract_stored_name(existing.image_path)
        if old_stored and old_stored != stored_name:
            _remove_stored_image(old_stored)
        # Objekte des vorherigen Plans zurücksetzen (wie im Original).
        AssessmentFloorPlanObject.query.filter_by(plan_id=existing.id).delete()
        existing.image_path = image_path
        existing.is_active = True
        existing.width_px = None
        existing.height_px = None
        existing.scale_point1_x = None
        existing.scale_point1_y = None
        existing.scale_point2_x = None
        existing.scale_point2_y = None
        existing.scale_distance_meters = None
        plan = existing
        message = "Lageplan erfolgreich aktualisiert und als aktiv gesetzt."
    else:
        plan = AssessmentFloorPlan(
            name=original_name,
            image_path=image_path,
            is_active=True,
        )
        db.session.add(plan)
        message = "Lageplan erfolgreich hochgeladen und als aktiv gesetzt."

    db.session.commit()

    return jsonify({
        "success": True,
        "message": message,
        "plan": _plan_to_dict(plan),
    })


@map_bp.route("/api/set_active_plan", methods=["POST"])
@assessment_role_required(["Administrator"])
def set_active_plan():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")
    if not plan_id:
        return jsonify({"success": False, "message": "Plan-ID fehlt."}), 400
    plan = AssessmentFloorPlan.query.get(plan_id)
    if not plan:
        return jsonify({"success": False, "message": "Plan nicht gefunden."}), 404
    AssessmentFloorPlan.query.update({"is_active": False})
    plan.is_active = True
    db.session.commit()
    return jsonify({"success": True, "message": "Lageplan erfolgreich als aktiv gesetzt."})


@map_bp.route("/api/get_active_plan")
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def get_active_plan():
    plan = AssessmentFloorPlan.query.filter_by(is_active=True).order_by(AssessmentFloorPlan.id.desc()).first()
    if not plan:
        return jsonify({"success": False, "message": "Kein aktiver Lageplan gefunden."}), 404

    stands = AssessmentStand.query.order_by(AssessmentStand.name.asc()).all()
    stand_lookup = {stand.id: stand.name for stand in stands}
    objects = AssessmentFloorPlanObject.query.filter_by(plan_id=plan.id).all()

    return jsonify({
        "success": True,
        "plan": _plan_to_dict(plan),
        "objects": [_object_to_dict(o, stand_lookup) for o in objects],
        "available_stands": [{"id": s.id, "name": s.name} for s in stands],
    })


@map_bp.route("/api/save_floor_plan_object", methods=["POST"])
@assessment_role_required(["Administrator"])
def save_floor_plan_object():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")
    obj_type = data.get("type")
    if not plan_id or not obj_type:
        return jsonify({"success": False, "message": "Fehlende Daten (plan_id/type)."}), 400

    plan = AssessmentFloorPlan.query.get(plan_id)
    if not plan:
        return jsonify({"success": False, "message": "Plan nicht gefunden."}), 404

    object_id = data.get("id")
    obj = AssessmentFloorPlanObject.query.get(object_id) if object_id else None
    if not obj:
        obj = AssessmentFloorPlanObject(plan_id=plan.id, type=obj_type)
        db.session.add(obj)

    obj.plan_id = plan.id
    obj.type = obj_type
    for field in ("x", "y", "width", "height"):
        if field in data and data[field] is not None:
            setattr(obj, field, float(data[field]))
    for field in ("color", "trash_can_color", "wc_label", "power_outlet_label", "custom_stand_name"):
        if field in data:
            value = data[field]
            setattr(obj, field, value if value not in ("", None) else None)
    if "stand_id" in data:
        stand_id = data["stand_id"]
        obj.stand_id = int(stand_id) if stand_id not in (None, "", "null") else None

    db.session.commit()

    stand_name = None
    if obj.stand_id:
        stand = AssessmentStand.query.get(obj.stand_id)
        stand_name = stand.name if stand else None

    return jsonify({
        "success": True,
        "message": "Objekt gespeichert.",
        "object_id": obj.id,
        "object": _object_to_dict(obj, {obj.stand_id: stand_name} if obj.stand_id else {}),
    })


@map_bp.route("/api/delete_floor_plan_object/<int:object_id>", methods=["DELETE"])
@assessment_role_required(["Administrator"])
def delete_floor_plan_object(object_id):
    obj = AssessmentFloorPlanObject.query.get(object_id)
    if not obj:
        return jsonify({"success": False, "message": "Objekt nicht gefunden."}), 404
    db.session.delete(obj)
    db.session.commit()
    return jsonify({"success": True, "message": "Objekt gelöscht."})


@map_bp.route("/api/update_plan_scale", methods=["POST"])
@assessment_role_required(["Administrator"])
def update_plan_scale():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")
    if not plan_id:
        return jsonify({"success": False, "message": "Plan-ID fehlt."}), 400
    plan = AssessmentFloorPlan.query.get(plan_id)
    if not plan:
        return jsonify({"success": False, "message": "Plan nicht gefunden."}), 404

    required = ("scale_point1_x", "scale_point1_y", "scale_point2_x", "scale_point2_y", "scale_distance_meters")
    if any(data.get(k) is None for k in required):
        return jsonify({"success": False, "message": "Fehlende Skalierungsdaten."}), 400

    plan.scale_point1_x = float(data["scale_point1_x"])
    plan.scale_point1_y = float(data["scale_point1_y"])
    plan.scale_point2_x = float(data["scale_point2_x"])
    plan.scale_point2_y = float(data["scale_point2_y"])
    plan.scale_distance_meters = float(data["scale_distance_meters"])
    if data.get("width_px") is not None:
        plan.width_px = float(data["width_px"])
    if data.get("height_px") is not None:
        plan.height_px = float(data["height_px"])
    db.session.commit()
    return jsonify({
        "success": True,
        "message": "Skalierungsdaten erfolgreich aktualisiert.",
        "pixels_per_meter": _compute_pixels_per_meter(plan),
    })


# -----------------------------------------------------------------------------
# Generische CRUD-Routen (bleiben als Fallback/Backward Compat verfügbar).
# -----------------------------------------------------------------------------

@map_bp.route("/api/floor_plans", methods=["GET", "POST", "PUT", "DELETE"])
@assessment_role_required(["Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"])
def floor_plans_api():
    if request.method == "GET":
        plans = AssessmentFloorPlan.query.order_by(AssessmentFloorPlan.id.desc()).all()
        return jsonify({
            "success": True,
            "plans": [_plan_to_dict(p) for p in plans],
        })

    data = request.get_json(silent=True) or {}
    if request.method == "POST":
        plan = AssessmentFloorPlan(name=data.get("name"), image_path=data.get("image_path"), is_active=False)
        db.session.add(plan)
        db.session.commit()
        return jsonify({"success": True, "id": plan.id, "plan": _plan_to_dict(plan)})

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
        return jsonify({"success": True, "message": "Plan aktualisiert.", "plan": _plan_to_dict(plan)})

    plan = AssessmentFloorPlan.query.get(data.get("id"))
    if not plan:
        return jsonify({"success": False, "message": "Plan nicht gefunden."}), 404
    stored_name = _extract_stored_name(plan.image_path)
    db.session.delete(plan)
    db.session.commit()
    _remove_stored_image(stored_name)
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
        stand_lookup = {s.id: s.name for s in AssessmentStand.query.all()}
        return jsonify({
            "success": True,
            "objects": [_object_to_dict(o, stand_lookup) for o in objects],
        })

    data = request.get_json(silent=True) or {}
    allowed = {
        "plan_id", "type", "x", "y", "width", "height", "color", "trash_can_color",
        "wc_label", "power_outlet_label", "stand_id", "custom_stand_name",
    }

    if request.method == "POST":
        payload = {k: v for k, v in data.items() if k in allowed}
        obj = AssessmentFloorPlanObject(**payload)
        db.session.add(obj)
        db.session.commit()
        return jsonify({"success": True, "id": obj.id})

    if request.method == "PUT":
        obj = AssessmentFloorPlanObject.query.get(data.get("id"))
        if not obj:
            return jsonify({"success": False, "message": "Objekt nicht gefunden."}), 404
        for key, value in data.items():
            if key in allowed:
                setattr(obj, key, value)
        db.session.commit()
        return jsonify({"success": True})

    obj = AssessmentFloorPlanObject.query.get(data.get("id"))
    if not obj:
        return jsonify({"success": False, "message": "Objekt nicht gefunden."}), 404
    db.session.delete(obj)
    db.session.commit()
    return jsonify({"success": True})


@map_bp.route("/uploads/plans/<path:filename>")
def serve_uploaded_plans(filename):
    return send_from_directory(_plans_dir(), filename)
