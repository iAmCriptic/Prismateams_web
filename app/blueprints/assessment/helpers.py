from datetime import datetime

from flask import abort, request

from app import db
from app.models.assessment import (
    AssessmentAppSetting,
    AssessmentList,
    AssessmentListSubject,
    AssessmentStand,
    AssessmentStandType,
    AssessmentUser,
)
from app.utils.assessment_auth import get_assessment_identity


def current_actor():
    user_type, user_id, roles = get_assessment_identity()
    return {"user_type": user_type, "user_id": user_id, "roles": roles}


def get_setting(key, default_value=None):
    entry = AssessmentAppSetting.query.filter_by(setting_key=key).first()
    if not entry or entry.setting_value is None:
        return default_value
    return entry.setting_value


def set_setting(key, value):
    entry = AssessmentAppSetting.query.filter_by(setting_key=key).first()
    if not entry:
        entry = AssessmentAppSetting(setting_key=key, setting_value=str(value))
    else:
        entry.setting_value = str(value)
    return entry


def utcnow():
    return datetime.utcnow()


def get_or_create_default_stand_type():
    default_type = AssessmentStandType.query.filter_by(name="Allgemein").first()
    if not default_type:
        default_type = AssessmentStandType(name="Allgemein", sort_order=0)
        db.session.add(default_type)
        db.session.flush()
    return default_type


def actor_is_admin(actor=None):
    actor = actor or current_actor()
    return "Administrator" in (actor.get("roles") or [])


def lists_for_actor(actor=None, require_active=True):
    """Aktive Listen, die der Actor bewerten/sehen darf.

    - Assessment-Administrator / Portal-Admin: immer alle Listen
    - Assessment-User ohne Zuordnung: alle Listen
    - Assessment-User mit Zuordnung: nur zugeordnete Listen
    - Portal-Nutzer ohne Admin (z.B. Bewerter): alle Listen
    """
    actor = actor or current_actor()
    query = AssessmentList.query
    if require_active:
        query = query.filter_by(is_active=True)
    query = query.order_by(AssessmentList.sort_order.asc(), AssessmentList.name.asc())

    if actor_is_admin(actor):
        return query.all()

    if actor.get("user_type") == "ass" and actor.get("user_id"):
        user = AssessmentUser.query.get(actor["user_id"])
        if user is not None:
            assigned = list(user.evaluation_lists or [])
            if assigned:
                allowed_ids = {lst.id for lst in assigned}
                return [lst for lst in query.all() if lst.id in allowed_ids]

    return query.all()


def actor_can_access_list(evaluation_list, actor=None):
    if not evaluation_list:
        return False
    allowed = {lst.id for lst in lists_for_actor(actor, require_active=False)}
    return evaluation_list.id in allowed


def get_evaluation_list(list_id=None, slug=None, require_active=True):
    if list_id:
        evaluation_list = AssessmentList.query.get(list_id)
    elif slug:
        evaluation_list = AssessmentList.query.filter_by(slug=slug).first()
    else:
        evaluation_list = None
    if not evaluation_list:
        return None
    if require_active and not evaluation_list.is_active:
        return None
    return evaluation_list


def resolve_evaluation_list_from_request(require_active=True, actor=None):
    actor = actor or current_actor()
    allowed = lists_for_actor(actor, require_active=require_active)
    allowed_ids = {lst.id for lst in allowed}

    list_id = request.args.get("list_id", type=int) or (request.get_json(silent=True) or {}).get("list_id")
    slug = request.args.get("list_slug") or (request.get_json(silent=True) or {}).get("list_slug")
    evaluation_list = get_evaluation_list(list_id=list_id, slug=slug, require_active=require_active)

    if evaluation_list and evaluation_list.id not in allowed_ids:
        return None

    if not evaluation_list and list_id is None and not slug:
        evaluation_list = allowed[0] if allowed else None

    return evaluation_list


def stands_for_list(evaluation_list):
    query = AssessmentStand.query.order_by(AssessmentStand.name.asc())
    type_ids = evaluation_list.get_stand_type_id_list()
    if type_ids:
        query = query.filter(AssessmentStand.stand_type_id.in_(type_ids))
    return query.all()


def subjects_for_list(evaluation_list):
    return (
        AssessmentListSubject.query.filter_by(list_id=evaluation_list.id, is_active=True)
        .order_by(AssessmentListSubject.sort_order.asc(), AssessmentListSubject.name.asc())
        .all()
    )


def list_to_dict(evaluation_list, include_filter=False):
    data = {
        "id": evaluation_list.id,
        "name": evaluation_list.name,
        "slug": evaluation_list.slug,
        "description": evaluation_list.description,
        "subject_mode": evaluation_list.subject_mode,
        "is_active": evaluation_list.is_active,
        "sort_order": evaluation_list.sort_order,
        "ranking_sort": evaluation_list.ranking_sort,
        "welcome_label": evaluation_list.welcome_label,
    }
    if include_filter:
        data["stand_type_ids"] = evaluation_list.get_stand_type_id_list()
    return data


def validate_evaluation_target(evaluation_list, stand_id=None, subject_id=None):
    if evaluation_list.subject_mode == "stand":
        if not stand_id:
            return False, "Stand ist erforderlich."
        stand = AssessmentStand.query.get(stand_id)
        if not stand:
            return False, "Stand nicht gefunden."
        type_ids = evaluation_list.get_stand_type_id_list()
        if type_ids and stand.stand_type_id not in type_ids:
            return False, "Stand gehört nicht zu dieser Bewertungsliste."
        return True, stand
    if not subject_id:
        return False, "Bewertungsziel ist erforderlich."
    subject = AssessmentListSubject.query.filter_by(
        id=subject_id, list_id=evaluation_list.id, is_active=True
    ).first()
    if not subject:
        return False, "Bewertungsziel nicht gefunden."
    return True, subject


def require_evaluation_list():
    evaluation_list = resolve_evaluation_list_from_request()
    if not evaluation_list:
        abort(404)
    return evaluation_list
