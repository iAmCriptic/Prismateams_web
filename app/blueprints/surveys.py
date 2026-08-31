"""Survey module blueprint."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from app import db
from app.models.survey import (
    DEFAULT_SURVEY_SETTINGS,
    SURVEY_LOGIC_ACTIONS,
    SURVEY_LOGIC_OPERATORS,
    SURVEY_QUESTION_TYPES,
    Survey,
    SurveyAnswer,
    SurveyEmailVerification,
    SurveyLogicRule,
    SurveyPage,
    SurveyQuestion,
    SurveyResponse,
    SurveyResponseLock,
)
from app.utils.access_control import check_module_access
from app.utils.bot_protection import get_template_context, validate_bot_protection
from app.utils.common import is_module_enabled, portal_now_naive
from app.utils.email_sender import generate_confirmation_code, render_and_send_portal_email
from app.utils.i18n import translate
from app.utils.module_visibility import (
    accessible_query,
    apply_section_filter,
    apply_visibility_from_form,
    can_edit_item,
    can_view_item,
    parse_section_args,
    visibility_form_context,
    visibility_nav_context,
)
from app.utils.survey_analytics import build_survey_summary, export_responses_csv
from app.utils.survey_logic import (
    answers_from_request,
    build_logic_payload,
    get_visible_pages,
    get_visible_questions,
    validate_required_answers,
)

surveys_bp = Blueprint('surveys', __name__, url_prefix='/surveys')

ALLOWED_HEADER_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EMAIL_VERIFY_SESSION_KEY = 'survey_verified_{token}'
RESPONSE_SESSION_KEY = 'survey_response_{token}'


def _surveys_denied():
    flash(translate('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('surveys.index'))


def _surveys_form_kwargs(survey=None):
    section, filter_team_id = parse_section_args('surveys', current_user)
    pre_section = section if section in ('private', 'public', 'team') else None
    ctx = visibility_form_context(
        'surveys',
        current_user,
        item=survey,
        preselect_section=pre_section,
        preselect_team_id=filter_team_id,
    )
    ctx['section_filter'] = section
    ctx['filter_team_id'] = filter_team_id
    return ctx


def _sidebar_context():
    section, filter_team_id = parse_section_args('surveys', current_user)
    ctx = visibility_nav_context('surveys', current_user, section, filter_team_id)
    return ctx


def _get_survey_or_404(survey_id: int, require_edit: bool = False):
    survey = Survey.query.get_or_404(survey_id)
    if require_edit:
        if not can_edit_item(current_user, survey, 'surveys'):
            return None, _surveys_denied()
    elif not can_view_item(current_user, survey, 'surveys'):
        return None, _surveys_denied()
    return survey, None


def _survey_bot_template_context(bot_context: str) -> dict:
    ctx = get_template_context()
    ctx['bot_context'] = bot_context
    return ctx


def _survey_by_public_token(token: str):
    return Survey.query.filter_by(public_token=token, is_publicly_fillable=True, is_active=True).first()


def _build_fill_view_context(survey, page_arg=1):
    """Shared rendering context for public fill and editor preview."""
    settings = survey.get_settings()
    pages = get_visible_pages(survey, {})
    layout_mode = survey.layout_mode or 'scroll'
    current_page = int(page_arg) - 1
    if layout_mode == 'pages' and pages:
        current_page = max(0, min(current_page, len(pages) - 1))
        visible_pages = [pages[current_page]]
    else:
        visible_pages = pages
        current_page = 0

    pages_with_questions = []
    for page in visible_pages:
        pages_with_questions.append({
            'page': page,
            'questions': get_visible_questions(page, {}, survey),
        })

    return {
        'survey': survey,
        'pages': visible_pages,
        'pages_with_questions': pages_with_questions,
        'all_pages': pages,
        'layout_mode': layout_mode,
        'current_page_index': current_page,
        'settings': settings,
        'logic_rules': build_logic_payload(survey),
    }


def _normalize_email(email: str) -> str:
    return (email or '').strip().lower()


def _upload_dir(survey_id: int, response_id: int | None = None) -> str:
    base = os.path.join(current_app.config['UPLOAD_FOLDER'], 'surveys', str(survey_id))
    if response_id:
        base = os.path.join(base, str(response_id))
    os.makedirs(base, exist_ok=True)
    return base


def _save_header_image(survey: Survey, file) -> str | None:
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_HEADER_EXTENSIONS:
        return None
    filename = secure_filename(f'header_{survey.id}_{uuid.uuid4().hex[:8]}.{ext}')
    path = os.path.join(_upload_dir(survey.id), filename)
    file.save(path)
    rel = os.path.join('surveys', str(survey.id), filename).replace('\\', '/')
    return rel


def _create_default_page(survey: Survey):
    page = SurveyPage(survey_id=survey.id, title='Seite 1', page_order=0)
    db.session.add(page)
    db.session.flush()
    return page


def _survey_structure_payload(survey: Survey) -> dict:
    page_ui = survey.get_settings().get('page_ui') or {}
    pages = []
    for page in survey.pages:
        questions = []
        for q in page.questions:
            questions.append({
                'id': q.id,
                'question_type': q.question_type,
                'label': q.label,
                'description': q.description,
                'is_required': q.is_required,
                'question_order': q.question_order,
                'config': q.get_config(),
            })
        ui = page_ui.get(str(page.id), {})
        pages.append({
            'id': page.id,
            'title': page.title,
            'description': page.description,
            'page_order': page.page_order,
            'show_title': bool(ui.get('show_title')),
            'show_description': bool(ui.get('show_description', page.description)),
            'questions': questions,
        })
    return {
        'id': survey.id,
        'title': survey.title,
        'description': survey.description,
        'header_image_path': survey.header_image_path,
        'layout_mode': survey.layout_mode,
        'is_active': survey.is_active,
        'is_publicly_fillable': survey.is_publicly_fillable,
        'public_token': survey.public_token,
        'settings': survey.get_settings(),
        'pages': pages,
        'logic_rules': build_logic_payload(survey),
        'question_types': list(SURVEY_QUESTION_TYPES),
        'logic_operators': list(SURVEY_LOGIC_OPERATORS),
        'logic_actions': list(SURVEY_LOGIC_ACTIONS),
    }


def _apply_structure(survey: Survey, data: dict):
    survey.title = (data.get('title') or survey.title or 'Neue Umfrage')[:255]
    survey.description = data.get('description')
    survey.layout_mode = data.get('layout_mode') or survey.layout_mode or 'scroll'
    if 'settings' in data:
        survey.set_settings(data['settings'])

    id_map: dict[int, int] = {}
    page_id_map: dict[int, int] = {}

    existing_pages = {p.id: p for p in survey.pages}
    seen_page_ids = set()
    pages_data = data.get('pages') or []
    page_ui: dict[str, dict] = {}

    if not pages_data:
        if not survey.pages:
            _create_default_page(survey)
        return

    for idx, page_data in enumerate(pages_data):
        page_id = page_data.get('id')
        page = existing_pages.get(page_id) if page_id and page_id > 0 else None
        if not page:
            page = SurveyPage(survey_id=survey.id)
            db.session.add(page)
        page.title = page_data.get('title') or f'Seite {idx + 1}'
        page.description = page_data.get('description')
        page.page_order = page_data.get('page_order', idx)
        db.session.flush()
        if page.id:
            page_ui[str(page.id)] = {
                'show_title': bool(page_data.get('show_title')),
                'show_description': bool(page_data.get('show_description')),
            }
        if page_data.get('id'):
            page_id_map[page_data['id']] = page.id
        if page.id:
            seen_page_ids.add(page.id)

        existing_questions = {q.id: q for q in page.questions}
        seen_q_ids = set()
        for qidx, q_data in enumerate(page_data.get('questions') or []):
            q_id = q_data.get('id')
            question = existing_questions.get(q_id) if q_id and q_id > 0 else None
            if not question:
                question = SurveyQuestion(page_id=page.id)
                db.session.add(question)
            qtype = q_data.get('question_type') or 'short_text'
            if qtype not in SURVEY_QUESTION_TYPES:
                qtype = 'short_text'
            question.question_type = qtype
            question.label = (q_data.get('label') or 'Neue Frage')[:500]
            question.description = q_data.get('description')
            question.is_required = bool(q_data.get('is_required'))
            question.question_order = q_data.get('question_order', qidx)
            question.set_config(q_data.get('config') or {})
            db.session.flush()
            if q_data.get('id'):
                id_map[q_data['id']] = question.id
            if question.id:
                seen_q_ids.add(question.id)

        for qid, question in existing_questions.items():
            if qid not in seen_q_ids:
                db.session.delete(question)

    for pid, page in existing_pages.items():
        if pid not in seen_page_ids:
            db.session.delete(page)

    if page_ui:
        settings = survey.get_settings()
        settings['page_ui'] = page_ui
        survey.set_settings(settings)

    def _remap_id(val, mapping):
        if val is None:
            return None
        return mapping.get(val, val if val > 0 else None)

    existing_rules = {r.id: r for r in survey.logic_rules}
    seen_rule_ids = set()
    for ridx, rule_data in enumerate(data.get('logic_rules') or []):
        rid = rule_data.get('id')
        rule = existing_rules.get(rid) if rid and rid > 0 else None
        if not rule:
            rule = SurveyLogicRule(survey_id=survey.id)
            db.session.add(rule)
        src_q = _remap_id(rule_data.get('source_question_id'), id_map)
        if not src_q:
            continue
        rule.source_question_id = src_q
        rule.operator = rule_data.get('operator') or 'equals'
        rule.action = rule_data.get('action') or 'goto_page'
        rule.target_page_id = _remap_id(rule_data.get('target_page_id'), page_id_map)
        rule.target_question_id = _remap_id(rule_data.get('target_question_id'), id_map)
        rule.rule_order = rule_data.get('rule_order', ridx)
        rule.set_value(rule_data.get('value'))
        db.session.flush()
        if rule.id:
            seen_rule_ids.add(rule.id)

    for rid, rule in existing_rules.items():
        if rid not in seen_rule_ids:
            db.session.delete(rule)


def _check_email_lock(survey: Survey, email: str) -> bool:
    settings = survey.get_settings()
    if not settings.get('one_response_per_email'):
        return False
    normalized = _normalize_email(email)
    if not normalized:
        return False
    return SurveyResponseLock.query.filter_by(survey_id=survey.id, email_normalized=normalized).first() is not None


def _verified_email_for_survey(token: str) -> str | None:
    return session.get(EMAIL_VERIFY_SESSION_KEY.format(token=token))


def _get_or_create_draft_response(survey: Survey, token: str) -> SurveyResponse:
    session_key = RESPONSE_SESSION_KEY.format(token=token)
    resp_id = session.get(session_key)
    if resp_id:
        resp = SurveyResponse.query.filter_by(id=resp_id, survey_id=survey.id).first()
        if resp:
            return resp
    resp = SurveyResponse(survey_id=survey.id, status='draft')
    resp.ensure_public_token()
    db.session.add(resp)
    db.session.commit()
    session[session_key] = resp.id
    return resp


# --- Internal routes ---

@surveys_bp.route('/')
@login_required
@check_module_access('module_surveys')
def index():
    if not is_module_enabled('module_surveys'):
        flash(translate('surveys.flash.module_disabled'), 'warning')
        return redirect(url_for('dashboard.index'))

    search_query = (request.args.get('q') or '').strip()
    section, filter_team_id = parse_section_args('surveys', current_user)
    query = accessible_query(current_user, Survey, 'surveys')
    if section in ('private', 'team', 'public'):
        query = apply_section_filter(query, Survey, section, filter_team_id)

    if search_query:
        like = f'%{search_query}%'
        query = query.filter(or_(Survey.title.ilike(like), Survey.description.ilike(like)))

    surveys = query.order_by(Survey.updated_at.desc()).all()
    ctx = _sidebar_context()
    return render_template(
        'surveys/index.html',
        surveys=surveys,
        search_query=search_query,
        **ctx,
    )


@surveys_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_surveys')
def create():
    form_kwargs = _surveys_form_kwargs()
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash(translate('surveys.create.title_required'), 'danger')
            return render_template(
                'surveys/create.html',
                title=request.form.get('title', ''),
                **form_kwargs,
            )

        survey = Survey(
            title=title[:255],
            created_by=current_user.id,
        )
        apply_visibility_from_form(survey, 'surveys', current_user)
        survey.set_settings(DEFAULT_SURVEY_SETTINGS)
        survey.ensure_public_token()
        db.session.add(survey)
        db.session.flush()
        _create_default_page(survey)
        db.session.commit()
        flash(translate('surveys.flash.created'), 'success')
        return redirect(url_for('surveys.edit', survey_id=survey.id))

    return render_template('surveys/create.html', title='', **form_kwargs)


@surveys_bp.route('/<int:survey_id>/edit')
@login_required
@check_module_access('module_surveys')
def edit(survey_id):
    survey, denied = _get_survey_or_404(survey_id, require_edit=True)
    if denied:
        return denied
    if not survey.pages:
        _create_default_page(survey)
        db.session.commit()
    public_url = None
    if survey.is_publicly_fillable and survey.public_token:
        public_url = url_for('surveys.public_fill', token=survey.public_token, _external=True)
    return render_template(
        'surveys/edit.html',
        survey=survey,
        structure_json=json.dumps(_survey_structure_payload(survey)),
        public_url=public_url,
        preview_url=url_for('surveys.preview', survey_id=survey.id),
        **_sidebar_context(),
    )


@surveys_bp.route('/<int:survey_id>/preview')
@login_required
@check_module_access('module_surveys')
def preview(survey_id):
    survey, denied = _get_survey_or_404(survey_id, require_edit=True)
    if denied:
        return denied
    ctx = _build_fill_view_context(survey, request.args.get('page', 1))
    header_image_url = None
    if survey.header_image_path:
        header_image_url = url_for('surveys.header_image_view', survey_id=survey.id)
    return render_template(
        'surveys/public/fill.html',
        is_preview=True,
        preview_back_url=url_for('surveys.edit', survey_id=survey.id),
        header_image_url=header_image_url,
        token=None,
        draft=None,
        **ctx,
    )


@surveys_bp.route('/<int:survey_id>/api/structure', methods=['GET', 'POST'])
@login_required
@check_module_access('module_surveys')
def api_structure(survey_id):
    survey, denied = _get_survey_or_404(survey_id, require_edit=True)
    if denied:
        return denied
    if request.method == 'GET':
        return jsonify(_survey_structure_payload(survey))

    data = request.get_json(silent=True) or {}
    try:
        _apply_structure(survey, data)
        if 'title' in data:
            survey.title = (data.get('title') or survey.title)[:255]
        if 'description' in data:
            survey.description = data.get('description')
        db.session.commit()
        return jsonify({'ok': True, 'structure': _survey_structure_payload(survey)})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Survey structure save failed')
        return jsonify({'ok': False, 'error': str(exc)}), 400


@surveys_bp.route('/<int:survey_id>/header-image', methods=['POST'])
@login_required
@check_module_access('module_surveys')
def header_image(survey_id):
    survey, denied = _get_survey_or_404(survey_id, require_edit=True)
    if denied:
        return denied
    file = request.files.get('header_image')
    rel = _save_header_image(survey, file)
    if not rel:
        return jsonify({'ok': False, 'error': 'invalid_file'}), 400
    survey.header_image_path = rel
    db.session.commit()
    return jsonify({'ok': True, 'header_image_path': rel, 'url': url_for('surveys.header_image_view', survey_id=survey.id)})


@surveys_bp.route('/<int:survey_id>/header-image/view')
@login_required
@check_module_access('module_surveys')
def header_image_view(survey_id):
    survey, denied = _get_survey_or_404(survey_id)
    if denied:
        return denied
    if not survey.header_image_path:
        return redirect(url_for('static', filename='img/placeholder.png'))
    from flask import send_from_directory
    directory = os.path.join(current_app.config['UPLOAD_FOLDER'], 'surveys', str(survey.id))
    filename = survey.header_image_path.split('/')[-1]
    return send_from_directory(directory, filename)


@surveys_bp.route('/<int:survey_id>/toggle-public-fill', methods=['POST'])
@login_required
@check_module_access('module_surveys')
def toggle_public_fill(survey_id):
    survey, denied = _get_survey_or_404(survey_id, require_edit=True)
    if denied:
        return jsonify({'ok': False, 'error': 'denied'}), 403
    data = request.get_json(silent=True) or {}
    if 'enabled' in data:
        survey.is_publicly_fillable = bool(data['enabled'])
    else:
        survey.is_publicly_fillable = not survey.is_publicly_fillable
    survey.ensure_public_token()
    db.session.commit()
    public_url = url_for('surveys.public_fill', token=survey.public_token, _external=True) if survey.is_publicly_fillable else None
    return jsonify({
        'ok': True,
        'is_publicly_fillable': survey.is_publicly_fillable,
        'public_url': public_url,
    })


@surveys_bp.route('/<int:survey_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_surveys')
def delete(survey_id):
    survey, denied = _get_survey_or_404(survey_id, require_edit=True)
    if denied:
        return denied
    db.session.delete(survey)
    db.session.commit()
    flash(translate('surveys.flash.deleted'), 'success')
    return redirect(url_for('surveys.index'))


@surveys_bp.route('/<int:survey_id>/duplicate', methods=['POST'])
@login_required
@check_module_access('module_surveys')
def duplicate(survey_id):
    survey, denied = _get_survey_or_404(survey_id)
    if denied:
        return denied
    copy = Survey(
        title=f'{survey.title} (Kopie)',
        description=survey.description,
        created_by=current_user.id,
        visibility=survey.visibility,
        team_id=survey.team_id,
        layout_mode=survey.layout_mode,
        is_active=False,
        is_publicly_fillable=False,
    )
    copy.set_settings(survey.get_settings())
    copy.ensure_public_token()
    db.session.add(copy)
    db.session.flush()

    page_map = {}
    for page in survey.pages:
        new_page = SurveyPage(
            survey_id=copy.id,
            title=page.title,
            description=page.description,
            page_order=page.page_order,
        )
        db.session.add(new_page)
        db.session.flush()
        page_map[page.id] = new_page.id
        for q in page.questions:
            nq = SurveyQuestion(
                page_id=new_page.id,
                question_type=q.question_type,
                label=q.label,
                description=q.description,
                is_required=q.is_required,
                question_order=q.question_order,
            )
            nq.set_config(q.get_config())
            db.session.add(nq)

    db.session.commit()
    flash(translate('surveys.flash.duplicated'), 'success')
    return redirect(url_for('surveys.edit', survey_id=copy.id))


@surveys_bp.route('/<int:survey_id>/results')
@login_required
@check_module_access('module_surveys')
def results(survey_id):
    survey, denied = _get_survey_or_404(survey_id)
    if denied:
        return denied
    responses = SurveyResponse.query.filter_by(survey_id=survey.id).order_by(SurveyResponse.created_at.desc()).all()
    summary = build_survey_summary(survey, responses)
    return render_template(
        'surveys/results.html',
        survey=survey,
        responses=responses,
        summary=summary,
        preview_url=url_for('surveys.preview', survey_id=survey.id),
        **_sidebar_context(),
    )


@surveys_bp.route('/<int:survey_id>/results/<int:response_id>')
@login_required
@check_module_access('module_surveys')
def result_detail(survey_id, response_id):
    survey, denied = _get_survey_or_404(survey_id)
    if denied:
        return denied
    resp = SurveyResponse.query.filter_by(id=response_id, survey_id=survey.id).first_or_404()
    answer_map = {a.question_id: a for a in resp.answers}
    return render_template(
        'surveys/result_detail.html',
        survey=survey,
        response=resp,
        answer_map=answer_map,
        **_sidebar_context(),
    )


@surveys_bp.route('/<int:survey_id>/export.csv')
@login_required
@check_module_access('module_surveys')
def export_csv(survey_id):
    survey, denied = _get_survey_or_404(survey_id)
    if denied:
        return denied
    responses = SurveyResponse.query.filter_by(survey_id=survey.id).all()
    csv_data = export_responses_csv(survey, responses)
    filename = f'survey_{survey.id}_export.csv'
    return Response(
        csv_data,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )


@surveys_bp.route('/<int:survey_id>/files/<int:response_id>/<path:filename>')
@login_required
@check_module_access('module_surveys')
def download_file(survey_id, response_id, filename):
    survey, denied = _get_survey_or_404(survey_id)
    if denied:
        return denied
    resp = SurveyResponse.query.filter_by(id=response_id, survey_id=survey.id).first_or_404()
    for ans in resp.answers:
        if ans.file_path and ans.file_path.endswith(filename):
            from flask import send_from_directory
            directory = os.path.dirname(os.path.join(current_app.config['UPLOAD_FOLDER'], ans.file_path))
            return send_from_directory(directory, os.path.basename(ans.file_path))
    return _surveys_denied()


# --- Public routes ---

@surveys_bp.route('/fill/<token>')
def public_fill(token):
    survey = _survey_by_public_token(token)
    if not survey:
        flash(translate('surveys.public.not_found'), 'danger')
        return render_template('surveys/public/not_found.html')

    settings = survey.get_settings()
    verified_email = _verified_email_for_survey(token)

    if settings.get('require_email_verification') and not verified_email:
        if current_user.is_authenticated and current_user.is_email_confirmed and current_user.email:
            verified_email = current_user.email
            session[EMAIL_VERIFY_SESSION_KEY.format(token=token)] = verified_email
        else:
            return render_template(
                'surveys/public/verify_email.html',
                survey=survey,
                token=token,
                **_survey_bot_template_context('survey_verify'),
            )

    if verified_email and _check_email_lock(survey, verified_email):
        return render_template('surveys/public/already_submitted.html', survey=survey)

    ctx = _build_fill_view_context(survey, request.args.get('page', 1))

    draft = _get_or_create_draft_response(survey, token)
    if verified_email and not draft.respondent_email:
        draft.respondent_email = verified_email
        db.session.commit()

    return render_template(
        'surveys/public/fill.html',
        token=token,
        draft=draft,
        is_preview=False,
        preview_back_url=None,
        header_image_url=None,
        **_survey_bot_template_context('survey_submit'),
        **ctx,
    )


@surveys_bp.route('/fill/<token>/verify-email', methods=['POST'])
def public_verify_email(token):
    survey = _survey_by_public_token(token)
    if not survey:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    ok, err = validate_bot_protection(request, 'survey_verify')
    if not ok:
        flash(translate('surveys.public.bot_blocked'), 'danger')
        return redirect(url_for('surveys.public_fill', token=token))

    email = _normalize_email(request.form.get('email'))
    if not email or '@' not in email:
        flash(translate('surveys.public.invalid_email'), 'danger')
        return redirect(url_for('surveys.public_fill', token=token))

    if _check_email_lock(survey, email):
        flash(translate('surveys.public.already_submitted'), 'warning')
        return redirect(url_for('surveys.public_fill', token=token))

    code = generate_confirmation_code()
    expires = datetime.utcnow() + timedelta(hours=24)
    existing = SurveyEmailVerification.query.filter_by(survey_id=survey.id, email=email).first()
    if existing:
        existing.code = code
        existing.expires_at = expires
        existing.verified_at = None
    else:
        db.session.add(SurveyEmailVerification(
            survey_id=survey.id,
            email=email,
            code=code,
            expires_at=expires,
        ))
    db.session.commit()

    subject = translate('surveys.public.verify_email_subject', title=survey.title)
    plain_text = translate('surveys.public.verify_email_body', code=code, title=survey.title)
    try:
        from app.utils.email_sender import _portal_name
        render_and_send_portal_email(
            subject=subject,
            recipients=[email],
            template_name='emails/confirmation_code.html',
            body_text=plain_text,
            confirmation_code=code,
            user=None,
        )
    except Exception:
        current_app.logger.exception('Survey verification email failed')

    session[f'survey_pending_email_{token}'] = email
    flash(translate('surveys.public.code_sent'), 'info')
    return render_template(
        'surveys/public/confirm_code.html',
        survey=survey,
        token=token,
        email=email,
        **_survey_bot_template_context('survey_confirm'),
    )


@surveys_bp.route('/fill/<token>/confirm-code', methods=['POST'])
def public_confirm_code(token):
    survey = _survey_by_public_token(token)
    if not survey:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    ok, err = validate_bot_protection(request, 'survey_confirm')
    if not ok:
        flash(err or translate('surveys.public.bot_blocked'), 'danger')
        return redirect(url_for('surveys.public_fill', token=token))

    email = session.get(f'survey_pending_email_{token}') or _normalize_email(request.form.get('email'))
    code = (request.form.get('code') or '').strip()
    if not email or not code:
        flash(translate('surveys.public.invalid_code'), 'danger')
        return redirect(url_for('surveys.public_fill', token=token))

    row = SurveyEmailVerification.query.filter_by(survey_id=survey.id, email=email, code=code).first()
    if not row or row.expires_at < datetime.utcnow():
        flash(translate('surveys.public.invalid_code'), 'danger')
        return redirect(url_for('surveys.public_fill', token=token))

    row.verified_at = datetime.utcnow()
    session[EMAIL_VERIFY_SESSION_KEY.format(token=token)] = email
    session.pop(f'survey_pending_email_{token}', None)
    db.session.commit()
    flash(translate('surveys.public.email_verified'), 'success')
    return redirect(url_for('surveys.public_fill', token=token))


@surveys_bp.route('/fill/<token>/submit', methods=['POST'])
def public_submit(token):
    survey = _survey_by_public_token(token)
    if not survey:
        flash(translate('surveys.public.not_found'), 'danger')
        return render_template('surveys/public/not_found.html')

    ok, err = validate_bot_protection(request, 'survey_submit')
    if not ok:
        flash(translate('surveys.public.captcha_required'), 'danger')
        return redirect(url_for('surveys.public_fill', token=token))

    settings = survey.get_settings()
    verified_email = _verified_email_for_survey(token)
    if settings.get('require_email_verification') and not verified_email:
        flash(translate('surveys.public.verify_required'), 'warning')
        return redirect(url_for('surveys.public_fill', token=token))

    if verified_email and _check_email_lock(survey, verified_email):
        return render_template('surveys/public/already_submitted.html', survey=survey)

    all_questions = survey.all_questions()
    answers = answers_from_request(request.form, request.files, all_questions)
    errors = validate_required_answers(survey, answers)
    if errors:
        flash(translate('surveys.public.required_missing', fields=', '.join(errors)), 'danger')
        return redirect(url_for('surveys.public_fill', token=token))

    draft = _get_or_create_draft_response(survey, token)
    draft.status = 'submitted'
    draft.submitted_at = portal_now_naive()
    draft.respondent_email = verified_email or draft.respondent_email
    draft.email_verified_at = datetime.utcnow() if verified_email else None
    if current_user.is_authenticated:
        draft.user_id = current_user.id
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr) or ''
    draft.ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:32]
    draft.ensure_public_token()

    for question in all_questions:
        qid = str(question.id)
        val = answers.get(qid)
        ans = SurveyAnswer.query.filter_by(response_id=draft.id, question_id=question.id).first()
        if not ans:
            ans = SurveyAnswer(response_id=draft.id, question_id=question.id)
            db.session.add(ans)

        if question.question_type == 'file_upload':
            f = request.files.get(f'q_{question.id}')
            if f and f.filename:
                ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
                cfg = question.get_config()
                allowed = cfg.get('allowed_extensions') or ['pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx']
                if ext in allowed:
                    fname = secure_filename(f'{question.id}_{uuid.uuid4().hex[:8]}.{ext}')
                    dest = _upload_dir(survey.id, draft.id)
                    fpath = os.path.join(dest, fname)
                    f.save(fpath)
                    rel = os.path.join('surveys', str(survey.id), str(draft.id), fname).replace('\\', '/')
                    ans.file_path = rel
                    ans.value_text = f.filename
        elif question.question_type == 'multiple_choice':
            ans.set_value_json(val if isinstance(val, list) else [val] if val else [])
        else:
            ans.value_text = str(val) if val is not None else None
            ans.value_json = None

    if verified_email and settings.get('one_response_per_email'):
        normalized = _normalize_email(verified_email)
        lock = SurveyResponseLock.query.filter_by(survey_id=survey.id, email_normalized=normalized).first()
        if not lock:
            db.session.add(SurveyResponseLock(
                survey_id=survey.id,
                email_normalized=normalized,
                response_id=draft.id,
            ))

    db.session.commit()
    session[RESPONSE_SESSION_KEY.format(token=token)] = draft.id
    return redirect(url_for('surveys.public_done', token=token, response_token=draft.public_token))


@surveys_bp.route('/fill/<token>/done')
def public_done(token):
    survey = _survey_by_public_token(token)
    if not survey:
        return render_template('surveys/public/not_found.html')
    response_token = request.args.get('response_token')
    settings = survey.get_settings()
    return render_template(
        'surveys/public/done.html',
        survey=survey,
        token=token,
        settings=settings,
        response_token=response_token,
    )


@surveys_bp.route('/public/header/<token>')
def public_header(token):
    survey = _survey_by_public_token(token)
    if not survey or not survey.header_image_path:
        return redirect(url_for('static', filename='img/placeholder.png'))
    from flask import send_from_directory
    directory = os.path.join(current_app.config['UPLOAD_FOLDER'], 'surveys', str(survey.id))
    filename = survey.header_image_path.split('/')[-1]
    return send_from_directory(directory, filename)
