"""Meetings module — MiroTalk SFU rooms managed by the portal."""

from __future__ import annotations

import os

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.models.chat import Chat, ChatMember
from app.models.meetings import (
    MEETING_ACCESS_INVITE,
    MEETING_STATUS_ACTIVE,
    Meeting,
)
from app.models.user import User
from app.utils.access_control import check_module_access, has_module_access
from app.utils.i18n import translate
from app.utils.meetings import (
    create_meeting,
    create_meeting_from_chat,
    end_meeting,
    list_inviteable_users,
    load_avatar_user_id,
    meetings_module_available,
    meetings_runtime_ready,
    purge_ended_meetings,
    sanitize_guest_name,
    sign_avatar_token,
    user_can_end_meeting,
    user_can_join_meeting,
    visible_meetings_query,
)
from app.utils.mirotalk import request_join_url

meetings_bp = Blueprint('meetings', __name__, url_prefix='/meetings')

GUEST_SESSION_KEY = 'meetings_guest_name'


def _module_guard():
    if not meetings_runtime_ready():
        abort(404)


def _sidebar_counts():
    active = visible_meetings_query(current_user, MEETING_STATUS_ACTIVE).count()
    return active


def _create_context(**extra):
    ctx = {
        'section': 'create',
        'form_title': '',
        'form_access_mode': 'public',
        'form_invitee_ids': [],
        'mirotalk_ready': True,
    }
    ctx.update(extra)
    if 'active_count' not in extra:
        ctx['active_count'] = _sidebar_counts()
    if 'invite_users' not in extra:
        ctx['invite_users'] = _invite_users_payload()
    ctx['has_other_invitees'] = any(not person.get('is_host') for person in ctx['invite_users'])
    return ctx


def _invite_users_payload():
    people = [{
        'id': current_user.id,
        'name': current_user.full_name,
        'email': current_user.email,
        'is_host': True,
    }]
    for user in list_inviteable_users(exclude_user_id=current_user.id):
        people.append({
            'id': user.id,
            'name': user.full_name,
            'email': user.email,
            'is_host': False,
        })
    return people


def _parse_invitee_ids():
    raw = request.form.getlist('invitee_ids')
    ids = []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _guest_link(meeting: Meeting) -> str:
    return url_for('meetings.guest_join', token=meeting.guest_join_token, _external=True)


def _avatar_url_for(user: User):
    if not user or not user.profile_picture:
        return None
    return url_for('meetings.avatar', token=sign_avatar_token(user.id), _external=True)


@meetings_bp.route('/')
@login_required
@check_module_access('module_meetings')
def index():
    _module_guard()
    purge_ended_meetings()
    meetings = visible_meetings_query(current_user, MEETING_STATUS_ACTIVE).options(
        joinedload(Meeting.creator),
    ).all()
    return render_template(
        'meetings/index.html',
        meetings=meetings,
        section='active',
        active_count=len(meetings),
        mirotalk_ready=True,
    )


@meetings_bp.route('/new', methods=['GET', 'POST'])
@login_required
@check_module_access('module_meetings')
def create():
    _module_guard()
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        access_mode = (request.form.get('access_mode') or 'public').strip().lower()
        invite_ids = _parse_invitee_ids() if access_mode == MEETING_ACCESS_INVITE else []
        meeting = create_meeting(
            title=title,
            created_by=current_user.id,
            access_mode=access_mode,
            invite_user_ids=invite_ids,
        )
        return redirect(url_for('meetings.join', meeting_id=meeting.id))

    return render_template('meetings/create.html', **_create_context())


@meetings_bp.route('/<int:meeting_id>/join')
@login_required
def join(meeting_id):
    if not meetings_runtime_ready():
        abort(404)
    meeting = Meeting.query.get_or_404(meeting_id)
    guest_token = (request.args.get('g') or '').strip() or None
    if not meeting.is_active:
        flash(translate('meetings.flash.ended'), 'warning')
        if has_module_access(current_user, 'module_meetings'):
            return redirect(url_for('meetings.index'))
        abort(403)
    if not user_can_join_meeting(current_user, meeting, guest_token=guest_token):
        flash(translate('meetings.flash.no_access'), 'danger')
        if has_module_access(current_user, 'module_meetings'):
            return redirect(url_for('meetings.index'))
        abort(403)

    back_url = url_for('meetings.index')
    if meeting.chat_id:
        back_url = url_for('chat.view_chat', chat_id=meeting.chat_id)
    try:
        iframe_src = request_join_url(
            meeting.room_id,
            current_user.full_name,
            avatar=_avatar_url_for(current_user),
            presenter=(meeting.created_by == current_user.id),
        )
    except Exception:
        current_app.logger.exception('MiroTalk join failed')
        flash(translate('meetings.flash.join_failed'), 'danger')
        return redirect(back_url)

    return render_template(
        'meetings/join.html',
        meeting=meeting,
        iframe_src=iframe_src,
        back_url=back_url,
        can_end=user_can_end_meeting(current_user, meeting),
        guest_link=_guest_link(meeting),
        meetings_call_mode=True,
    )


@meetings_bp.route('/<int:meeting_id>/end', methods=['POST'])
@login_required
def end(meeting_id):
    if not meetings_runtime_ready():
        abort(404)
    meeting = Meeting.query.get_or_404(meeting_id)
    if not user_can_end_meeting(current_user, meeting):
        abort(403)
    end_meeting(meeting, current_user.id)
    flash(translate('meetings.flash.ended_ok'), 'success')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'redirect': url_for('meetings.index')})
    return redirect(url_for('meetings.index'))


@meetings_bp.route('/from-chat/<int:chat_id>', methods=['POST'])
@login_required
def from_chat(chat_id):
    if not meetings_module_available(current_user):
        return jsonify({'success': False, 'error': translate('meetings.flash.no_module')}), 403
    if chat_id == 1:
        main = Chat.query.filter_by(is_main_chat=True).first()
        if not main:
            return jsonify({'success': False, 'error': translate('meetings.flash.chat_missing')}), 404
        actual_id = main.id
    else:
        actual_id = chat_id
    chat = Chat.query.get_or_404(actual_id)
    membership = ChatMember.query.filter_by(chat_id=actual_id, user_id=current_user.id).first()
    if not membership:
        return jsonify({'success': False, 'error': translate('meetings.flash.not_chat_member')}), 403
    meeting = create_meeting_from_chat(chat, current_user)
    join_url = url_for('meetings.join', meeting_id=meeting.id)
    return jsonify({
        'success': True,
        'meeting_id': meeting.id,
        'join_url': join_url,
        'title': meeting.title,
    })


@meetings_bp.route('/g/<token>', methods=['GET', 'POST'])
def guest_join(token):
    if not meetings_runtime_ready():
        abort(404)
    meeting = Meeting.query.filter_by(guest_join_token=token).first_or_404()
    if not meeting.is_active:
        return render_template(
            'meetings/guest_join.html',
            meeting=meeting,
            ended=True,
            meetings_call_mode=True,
        ), 410

    if current_user.is_authenticated:
        return redirect(url_for('meetings.join', meeting_id=meeting.id, g=token))

    guest_name = sanitize_guest_name(session.get(GUEST_SESSION_KEY, ''))
    if request.method == 'POST':
        guest_name = sanitize_guest_name(request.form.get('guest_name', ''))
        if not guest_name:
            flash(translate('meetings.guest.name_required'), 'warning')
            return render_template(
                'meetings/guest_join.html',
                meeting=meeting,
                ended=False,
                meetings_call_mode=True,
            )
        session[GUEST_SESSION_KEY] = guest_name

    if not guest_name:
        return render_template(
            'meetings/guest_join.html',
            meeting=meeting,
            ended=False,
            meetings_call_mode=True,
        )

    try:
        iframe_src = request_join_url(meeting.room_id, guest_name, presenter=False)
    except Exception:
        current_app.logger.exception('MiroTalk guest join failed')
        flash(translate('meetings.flash.join_failed'), 'danger')
        return render_template(
            'meetings/guest_join.html',
            meeting=meeting,
            ended=False,
            meetings_call_mode=True,
        )

    return render_template(
        'meetings/join.html',
        meeting=meeting,
        iframe_src=iframe_src,
        back_url=None,
        can_end=False,
        guest_link=_guest_link(meeting),
        meetings_call_mode=True,
        guest_display_name=guest_name,
    )


@meetings_bp.route('/avatar/<token>')
def avatar(token):
    user_id = load_avatar_user_id(token)
    if not user_id:
        abort(404)
    user = User.query.get(user_id)
    if not user or not user.profile_picture:
        abort(404)
    project_root = os.path.dirname(current_app.root_path)
    directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
    path = os.path.join(directory, user.profile_picture)
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(directory, user.profile_picture)
