"""Protokollführung module blueprint."""

from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_

from app import db
from app.models.protocol import (
    PROTOCOL_STATUS_DRAFT,
    PROTOCOL_STATUS_FINALIZED,
    Protocol,
    ProtocolAgendaItem,
)
from app.utils.access_control import check_module_access
from app.utils.common import is_module_enabled, portal_now_naive
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

protocols_bp = Blueprint('protocols', __name__, url_prefix='/protocols')


def _denied():
    flash(translate('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('protocols.index'))


def _form_kwargs(protocol=None):
    section, filter_team_id = parse_section_args('protocols', current_user)
    pre_section = section if section in ('public', 'team') else None
    ctx = visibility_form_context(
        'protocols',
        current_user,
        item=protocol,
        preselect_section=pre_section,
        preselect_team_id=filter_team_id,
    )
    ctx.update(visibility_nav_context('protocols', current_user, section, filter_team_id))
    return ctx


def _sidebar_context():
    section, filter_team_id = parse_section_args('protocols', current_user)
    return visibility_nav_context('protocols', current_user, section, filter_team_id)


def _get_protocol(protocol_id: int, require_edit: bool = False, allow_finalized_edit: bool = False):
    protocol = Protocol.query.get_or_404(protocol_id)
    if require_edit:
        if not can_edit_item(current_user, protocol, 'protocols'):
            return None, _denied()
        if protocol.is_finalized and not allow_finalized_edit:
            flash(translate('protocols.flash.finalized_readonly'), 'warning')
            return None, redirect(url_for('protocols.view', protocol_id=protocol.id))
    elif not can_view_item(current_user, protocol, 'protocols'):
        return None, _denied()
    return protocol, None


def _parse_date(raw: str):
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(raw: str):
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _now_defaults():
    now = portal_now_naive()
    return now.date(), now.time().replace(second=0, microsecond=0)


def _visibility_label(protocol: Protocol) -> str:
    if protocol.visibility == 'team' and protocol.team:
        return protocol.team.name
    if protocol.visibility == 'public':
        return translate('visibility.form.public')
    if protocol.visibility == 'team':
        return translate('visibility.nav.team')
    return protocol.visibility or '—'


def _apply_meta_from_form(protocol: Protocol):
    title = (request.form.get('title') or '').strip()
    if title:
        protocol.title = title[:255]
    meeting_date = _parse_date(request.form.get('meeting_date'))
    if meeting_date:
        protocol.meeting_date = meeting_date
    start_time = _parse_time(request.form.get('start_time'))
    if start_time:
        protocol.start_time = start_time
    protocol.participants_text = (request.form.get('participants_text') or '').strip() or None
    protocol.excused_text = (request.form.get('excused_text') or '').strip() or None
    protocol.absent_text = (request.form.get('absent_text') or '').strip() or None
    apply_visibility_from_form(protocol, 'protocols', current_user)


def _sync_agenda_from_form(protocol: Protocol):
    """Replace agenda items from form lists titles[] / item_ids[]."""
    titles = request.form.getlist('titles')
    item_ids = request.form.getlist('item_ids')
    existing = {item.id: item for item in protocol.agenda_items}
    seen = set()
    position = 0
    for idx, title in enumerate(titles):
        title = (title or '').strip()
        if not title:
            continue
        raw_id = item_ids[idx] if idx < len(item_ids) else ''
        try:
            item_id = int(raw_id) if raw_id else 0
        except (TypeError, ValueError):
            item_id = 0
        item = existing.get(item_id) if item_id else None
        if not item:
            item = ProtocolAgendaItem(protocol_id=protocol.id)
            db.session.add(item)
        item.title = title[:500]
        item.position = position
        db.session.flush()
        seen.add(item.id)
        position += 1

    for item_id, item in existing.items():
        if item_id not in seen:
            db.session.delete(item)


# --- Routes ---

@protocols_bp.route('/')
@login_required
@check_module_access('module_protocols')
def index():
    if not is_module_enabled('module_protocols'):
        flash(translate('protocols.flash.module_disabled'), 'warning')
        return redirect(url_for('dashboard.index'))

    search_query = (request.args.get('q') or '').strip()
    section, filter_team_id = parse_section_args('protocols', current_user)
    query = accessible_query(current_user, Protocol, 'protocols')
    if section in ('team', 'public'):
        query = apply_section_filter(query, Protocol, section, filter_team_id)

    if search_query:
        like = f'%{search_query}%'
        query = query.filter(
            or_(
                Protocol.title.ilike(like),
                Protocol.participants_text.ilike(like),
            )
        )

    protocols = query.order_by(Protocol.meeting_date.desc(), Protocol.updated_at.desc()).all()
    ctx = _sidebar_context()
    return render_template(
        'protocols/index.html',
        protocols=protocols,
        search_query=search_query,
        visibility_label=_visibility_label,
        **ctx,
    )


@protocols_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_protocols')
def create():
    form_kwargs = _form_kwargs()
    default_date, default_time = _now_defaults()
    form_data = {
        'title': '',
        'meeting_date': default_date.isoformat(),
        'start_time': default_time.strftime('%H:%M'),
        'participants_text': '',
        'excused_text': '',
        'absent_text': '',
    }

    if request.method == 'POST':
        form_data.update({
            'title': request.form.get('title', ''),
            'meeting_date': request.form.get('meeting_date', form_data['meeting_date']),
            'start_time': request.form.get('start_time', form_data['start_time']),
            'participants_text': request.form.get('participants_text', ''),
            'excused_text': request.form.get('excused_text', ''),
            'absent_text': request.form.get('absent_text', ''),
        })
        title = (form_data['title'] or '').strip()
        meeting_date = _parse_date(form_data['meeting_date']) or default_date
        start_time = _parse_time(form_data['start_time']) or default_time
        if not title:
            flash(translate('protocols.create.title_required'), 'danger')
            return render_template('protocols/create.html', form=form_data, **form_kwargs)

        protocol = Protocol(
            title=title[:255],
            meeting_date=meeting_date,
            start_time=start_time,
            participants_text=(form_data['participants_text'] or '').strip() or None,
            excused_text=(form_data['excused_text'] or '').strip() or None,
            absent_text=(form_data['absent_text'] or '').strip() or None,
            status=PROTOCOL_STATUS_DRAFT,
            created_by=current_user.id,
        )
        apply_visibility_from_form(protocol, 'protocols', current_user)
        db.session.add(protocol)
        db.session.commit()
        flash(translate('protocols.flash.created'), 'success')
        return redirect(url_for('protocols.edit_agenda', protocol_id=protocol.id))

    return render_template('protocols/create.html', form=form_data, **form_kwargs)


@protocols_bp.route('/<int:protocol_id>/meta', methods=['GET', 'POST'])
@login_required
@check_module_access('module_protocols')
def edit_meta(protocol_id):
    protocol, denied = _get_protocol(protocol_id, require_edit=True)
    if denied:
        return denied

    form_kwargs = _form_kwargs(protocol)
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash(translate('protocols.create.title_required'), 'danger')
        else:
            _apply_meta_from_form(protocol)
            db.session.commit()
            flash(translate('protocols.flash.saved'), 'success')
            return redirect(url_for('protocols.edit_agenda', protocol_id=protocol.id))

    form_data = {
        'title': protocol.title,
        'meeting_date': protocol.meeting_date.isoformat() if protocol.meeting_date else '',
        'start_time': protocol.start_time.strftime('%H:%M') if protocol.start_time else '',
        'participants_text': protocol.participants_text or '',
        'excused_text': protocol.excused_text or '',
        'absent_text': protocol.absent_text or '',
    }
    return render_template(
        'protocols/create.html',
        form=form_data,
        protocol=protocol,
        editing=True,
        **form_kwargs,
    )


@protocols_bp.route('/<int:protocol_id>/agenda', methods=['GET', 'POST'])
@login_required
@check_module_access('module_protocols')
def edit_agenda(protocol_id):
    protocol, denied = _get_protocol(protocol_id, require_edit=True)
    if denied:
        return denied

    if request.method == 'POST':
        _sync_agenda_from_form(protocol)
        db.session.commit()
        action = (request.form.get('action') or 'save').strip()
        if action == 'continue':
            items = (
                ProtocolAgendaItem.query
                .filter_by(protocol_id=protocol.id)
                .order_by(ProtocolAgendaItem.position)
                .all()
            )
            if not items:
                flash(translate('protocols.agenda.min_one'), 'warning')
                return redirect(url_for('protocols.edit_agenda', protocol_id=protocol.id))
            flash(translate('protocols.flash.saved'), 'success')
            return redirect(url_for('protocols.edit_item', protocol_id=protocol.id, item_id=items[0].id))
        flash(translate('protocols.flash.saved'), 'success')
        return redirect(url_for('protocols.edit_agenda', protocol_id=protocol.id))

    return render_template(
        'protocols/agenda.html',
        protocol=protocol,
        **_sidebar_context(),
    )


@protocols_bp.route('/<int:protocol_id>/item/<int:item_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_protocols')
def edit_item(protocol_id, item_id):
    protocol, denied = _get_protocol(protocol_id, require_edit=True)
    if denied:
        return denied

    item = ProtocolAgendaItem.query.filter_by(id=item_id, protocol_id=protocol.id).first_or_404()
    items = list(protocol.agenda_items)
    idx = next((i for i, it in enumerate(items) if it.id == item.id), 0)
    prev_item = items[idx - 1] if idx > 0 else None
    next_item = items[idx + 1] if idx + 1 < len(items) else None

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if title:
            item.title = title[:500]
        item.content_html = request.form.get('content_html') or ''
        db.session.commit()
        action = (request.form.get('action') or 'save').strip()
        if action == 'finalize':
            if not protocol.agenda_items:
                flash(translate('protocols.agenda.min_one'), 'warning')
                return redirect(url_for('protocols.edit_agenda', protocol_id=protocol.id))
            now = portal_now_naive()
            protocol.status = PROTOCOL_STATUS_FINALIZED
            protocol.end_time = now.time().replace(second=0, microsecond=0)
            protocol.finalized_at = now
            db.session.commit()
            flash(translate('protocols.flash.finalized'), 'success')
            return redirect(url_for('protocols.view', protocol_id=protocol.id))
        if action == 'next' and next_item:
            return redirect(url_for('protocols.edit_item', protocol_id=protocol.id, item_id=next_item.id))
        if action == 'prev' and prev_item:
            return redirect(url_for('protocols.edit_item', protocol_id=protocol.id, item_id=prev_item.id))
        flash(translate('protocols.flash.saved'), 'success')
        return redirect(url_for('protocols.edit_item', protocol_id=protocol.id, item_id=item.id))

    return render_template(
        'protocols/edit_item.html',
        protocol=protocol,
        item=item,
        items=items,
        item_index=idx,
        prev_item=prev_item,
        next_item=next_item,
        **_sidebar_context(),
    )


@protocols_bp.route('/<int:protocol_id>/item/<int:item_id>/autosave', methods=['POST'])
@login_required
@check_module_access('module_protocols')
def autosave_item(protocol_id, item_id):
    protocol, denied = _get_protocol(protocol_id, require_edit=True)
    if denied:
        return jsonify({'ok': False, 'error': 'denied'}), 403

    item = ProtocolAgendaItem.query.filter_by(id=item_id, protocol_id=protocol.id).first()
    if not item:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if title:
        item.title = title[:500]
    if 'content_html' in data:
        item.content_html = data.get('content_html') or ''
    db.session.commit()
    return jsonify({'ok': True})


@protocols_bp.route('/<int:protocol_id>/view')
@login_required
@check_module_access('module_protocols')
def view(protocol_id):
    protocol, denied = _get_protocol(protocol_id)
    if denied:
        return denied
    can_edit = can_edit_item(current_user, protocol, 'protocols') and protocol.is_draft
    return render_template(
        'protocols/view.html',
        protocol=protocol,
        can_edit=can_edit,
        visibility_label=_visibility_label(protocol),
        **_sidebar_context(),
    )


@protocols_bp.route('/<int:protocol_id>/finalize', methods=['POST', 'GET'])
@login_required
@check_module_access('module_protocols')
def finalize(protocol_id):
    protocol, denied = _get_protocol(protocol_id, require_edit=True)
    if denied:
        return denied

    if request.method == 'GET':
        # Safety: prefer POST from forms; GET redirects to view with hint
        return redirect(url_for('protocols.view', protocol_id=protocol.id))

    if not protocol.agenda_items:
        flash(translate('protocols.agenda.min_one'), 'warning')
        return redirect(url_for('protocols.edit_agenda', protocol_id=protocol.id))

    now = portal_now_naive()
    protocol.status = PROTOCOL_STATUS_FINALIZED
    protocol.end_time = now.time().replace(second=0, microsecond=0)
    protocol.finalized_at = now
    db.session.commit()
    flash(translate('protocols.flash.finalized'), 'success')
    return redirect(url_for('protocols.view', protocol_id=protocol.id))


@protocols_bp.route('/<int:protocol_id>/pdf')
@login_required
@check_module_access('module_protocols')
def pdf(protocol_id):
    protocol, denied = _get_protocol(protocol_id)
    if denied:
        return denied
    if not protocol.is_finalized:
        flash(translate('protocols.flash.pdf_only_finalized'), 'warning')
        return redirect(url_for('protocols.view', protocol_id=protocol.id))

    from app.utils.protocol_pdf import generate_protocol_pdf

    buf = generate_protocol_pdf(protocol)
    filename = f"Protokoll_{protocol.meeting_date.strftime('%Y-%m-%d')}_{protocol.id}.pdf"
    return send_file(
        buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )


@protocols_bp.route('/<int:protocol_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_protocols')
def delete(protocol_id):
    protocol, denied = _get_protocol(protocol_id, require_edit=True, allow_finalized_edit=True)
    if denied:
        return denied
    db.session.delete(protocol)
    db.session.commit()
    flash(translate('protocols.flash.deleted'), 'success')
    return redirect(url_for('protocols.index'))
