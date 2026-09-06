from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, abort, current_app, send_file, g, after_this_request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.settings import SystemSettings
from app.models.notification import NotificationSettings, ChatNotificationSettings, PushSubscription, NotificationLog
from app.models.chat import Chat, ChatMember
from app.models.whitelist import WhitelistEntry
from app.utils.notifications import get_or_create_notification_settings, sync_user_notification_flags
from app.utils.backup import export_backup, import_backup, SUPPORTED_CATEGORIES, CATEGORY_DEFINITIONS
from werkzeug.utils import secure_filename
from datetime import datetime
from collections import defaultdict
import json
import os
import secrets
import tempfile
from app.utils.i18n import available_languages, translate
from app.utils.totp import (
    generate_totp_secret,
    get_totp_uri,
    get_totp_issuer_name,
    generate_qr_code,
    encrypt_secret,
    verify_totp,
)
from app.utils.webauthn_helper import passkeys_supported_for_request, localhost_passkey_url
from app.utils.session_manager import get_user_sessions, revoke_session, revoke_all_sessions
from app.utils.password_policy import validate_password
from app.utils.common import get_timezone_choices, DEFAULT_TIMEZONE, now_in_portal_timezone, portal_now_naive
from datetime import datetime, timedelta
from sqlalchemy import func, or_

from app.blueprints.settings._bp import (
    LANGUAGE_COMPLETENESS,
    LANGUAGE_FALLBACK_NAMES,
    _guest_account_form_options,
    _language_badge_grade,
    _settings_redirect,
    _settings_save_response,
    _wants_json_response,
    settings_bp,
)

def _team_upload_dir():
    project_root = os.path.dirname(current_app.root_path)
    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'teams')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _delete_team_image_file(filename):
    if not filename:
        return
    try:
        path = os.path.join(_team_upload_dir(), filename)
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _normalize_team_color(raw):
    """Return normalized #RRGGBB or None. Empty is allowed. False if invalid."""
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith('#') and len(value) == 7:
        hex_part = value[1:]
        if all(c in '0123456789abcdefABCDEF' for c in hex_part):
            return f'#{hex_part.lower()}'
    return False


def _team_name_taken(name, exclude_id=None):
    from app.models.team import Team
    query = Team.query.filter(db.func.lower(Team.name) == name.strip().lower())
    if exclude_id is not None:
        query = query.filter(Team.id != exclude_id)
    return query.first() is not None


def _ensure_team_member(team_id, user_id):
    from app.models.team import TeamMember
    existing = TeamMember.query.filter_by(team_id=team_id, user_id=user_id).first()
    if existing:
        return existing
    member = TeamMember(team_id=team_id, user_id=user_id)
    db.session.add(member)
    return member


def _save_team_image(file_storage, team_id=None):
    """Validate and save team image. Returns (filename, error_key_or_None)."""
    if not file_storage or not file_storage.filename:
        return None, None
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    if '.' not in file_storage.filename or file_storage.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return None, 'settings.admin.teams.flash_picture_invalid_type'
    file_storage.seek(0, 2)
    file_size = file_storage.tell()
    file_storage.seek(0)
    if file_size > 5 * 1024 * 1024:
        return None, 'settings.admin.teams.flash_picture_too_large'
    filename = secure_filename(file_storage.filename)
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    prefix = str(team_id) if team_id else 'new'
    filename = f"{prefix}_{timestamp}_{filename}"
    file_storage.save(os.path.join(_team_upload_dir(), filename))
    return filename, None


def _team_leader_choices():
    """Active full users and guests available as team leaders."""
    return User.query.filter(
        User.email != 'anonymous@system.local',
        or_(
            User.is_active == True,
            User.is_guest == True,
        )
    ).order_by(User.last_name, User.first_name).all()


@settings_bp.route('/admin/teams')
@login_required
def admin_teams():
    """List teams (admin: all; team leader: own teams)."""
    from app.models.team import Team
    from app.utils.multi_mailboxes import get_led_teams, user_is_team_leader

    if current_user.is_admin:
        teams = Team.query.order_by(Team.name).all()
    elif user_is_team_leader(current_user):
        teams = get_led_teams(current_user)
    else:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    return render_template('settings/admin_teams.html', teams=teams, is_team_leader_view=not current_user.is_admin)


@settings_bp.route('/team-settings', methods=['GET', 'POST'])
@login_required
def team_settings():
    """Team leaders: enable/disable team sections per team."""
    from app.models.team import Team
    from app.utils.multi_mailboxes import can_manage_team, get_led_teams, user_is_team_leader
    from app.utils.team_module_settings import (
        TEAM_SECTION_MODULES,
        get_team_section_states,
        set_team_section_enabled,
    )

    if current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))
    if not user_is_team_leader(current_user):
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    teams = get_led_teams(current_user)
    if not teams:
        flash(translate('settings.team_settings.flash_no_teams'), 'warning')
        return redirect(url_for('settings.index'))

    team_id = request.args.get('team_id', type=int) or request.form.get('team_id', type=int)
    if team_id:
        team = next((t for t in teams if t.id == team_id), None)
    else:
        team = teams[0]
    if not team or not can_manage_team(current_user, team.id):
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.team_settings'))

    module_labels = {
        'wiki': translate('layout.nav.wiki'),
        'credentials': translate('layout.nav.credentials'),
        'manuals': translate('layout.nav.manuals'),
        'contacts': translate('layout.nav.contacts'),
        'shortlinks': translate('layout.nav.shortlinks'),
        'excalidraw': translate('layout.nav.excalidraw'),
        'kanban': translate('settings.sidebar.kanban'),
        'calendar': translate('settings.admin.cards.calendar_settings.title'),
        'files': translate('settings.admin.cards.file_settings.title'),
        'email': translate('settings.sidebar.email_module'),
        'chat': translate('settings.team_settings.module_chat'),
    }

    if request.method == 'POST':
        for module_key in TEAM_SECTION_MODULES:
            enabled = request.form.get(f'team_module_{module_key}') == 'on'
            set_team_section_enabled(team.id, module_key, enabled)
        db.session.commit()
        return _settings_save_response(
            True,
            translate('settings.autosave.saved'),
            'settings.team_settings',
            redirect_kwargs={'team_id': team.id},
        )

    states = get_team_section_states(team.id)
    modules = []
    for key in TEAM_SECTION_MODULES:
        from app.utils.common import is_module_enabled
        mod = TEAM_SECTION_MODULES[key]
        if not is_module_enabled(mod):
            continue
        modules.append({
            'key': key,
            'label': module_labels.get(key, key),
            'enabled': states.get(key, True),
        })

    return render_template(
        'settings/team_settings.html',
        teams=teams,
        team=team,
        modules=modules,
    )


@settings_bp.route('/admin/teams/create', methods=['GET', 'POST'])
@login_required
def create_team():
    """Create a new team (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.team import Team
    leader_choices = _team_leader_choices()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None
        leader_id_raw = request.form.get('leader_id', '').strip()
        color = _normalize_team_color(request.form.get('color', ''))

        if not name:
            flash(translate('settings.admin.teams.flash_name_required'), 'danger')
            return render_template('settings/admin_team_form.html', team=None, leader_choices=leader_choices)

        if color is False:
            flash(translate('settings.admin.teams.flash_color_invalid'), 'danger')
            return render_template('settings/admin_team_form.html', team=None, leader_choices=leader_choices)

        if _team_name_taken(name):
            flash(translate('settings.admin.teams.flash_name_taken'), 'danger')
            return render_template('settings/admin_team_form.html', team=None, leader_choices=leader_choices)

        leader_id = int(leader_id_raw) if leader_id_raw.isdigit() else None
        if leader_id and not User.query.get(leader_id):
            leader_id = None

        team = Team(name=name, description=description, color=color, leader_id=leader_id)
        db.session.add(team)
        db.session.flush()

        image_file = request.files.get('image')
        filename, err = _save_team_image(image_file, team.id)
        if err:
            db.session.rollback()
            flash(translate(err), 'danger')
            return render_template('settings/admin_team_form.html', team=None, leader_choices=leader_choices)
        if filename:
            team.image = filename

        if leader_id:
            _ensure_team_member(team.id, leader_id)

        from app.utils.team_chat import ensure_team_chat
        ensure_team_chat(team, created_by=current_user.id)

        db.session.commit()
        flash(translate('settings.admin.teams.flash_created', name=team.name), 'success')
        return redirect(url_for('settings.admin_team_detail', team_id=team.id))

    return render_template('settings/admin_team_form.html', team=None, leader_choices=leader_choices)


@settings_bp.route('/admin/teams/<int:team_id>', methods=['GET', 'POST'])
@login_required
def admin_team_detail(team_id):
    """Team detail: members list, bulk add, remove (admin or team leader)."""
    from app.models.team import Team, TeamMember
    from app.utils.multi_mailboxes import can_manage_team, is_email_multi_enabled

    if not can_manage_team(current_user, team_id):
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        from app.utils.multi_mailboxes import user_is_team_leader
        if user_is_team_leader(current_user) or current_user.is_admin:
            return redirect(url_for('settings.admin_teams'))
        return redirect(url_for('settings.index'))

    team = Team.query.get_or_404(team_id)

    if request.method == 'POST':
        action = request.form.get('action', '').strip()

        if action == 'add_members':
            user_ids = request.form.getlist('user_ids')
            added = 0
            for raw_id in user_ids:
                if not raw_id.isdigit():
                    continue
                uid = int(raw_id)
                user = User.query.get(uid)
                if not user or user.email == 'anonymous@system.local':
                    continue
                if TeamMember.query.filter_by(team_id=team.id, user_id=uid).first():
                    continue
                db.session.add(TeamMember(team_id=team.id, user_id=uid))
                added += 1
            from app.utils.team_chat import ensure_team_chat
            ensure_team_chat(team, created_by=current_user.id)
            db.session.commit()
            flash(translate('settings.admin.teams.flash_members_added', count=added), 'success')
            return redirect(url_for('settings.admin_team_detail', team_id=team.id))

        if action == 'remove_member':
            raw_id = request.form.get('user_id', '').strip()
            if raw_id.isdigit():
                uid = int(raw_id)
                if team.leader_id and uid == team.leader_id:
                    flash(translate('settings.admin.teams.flash_cannot_remove_leader'), 'warning')
                    return redirect(url_for('settings.admin_team_detail', team_id=team.id))
                TeamMember.query.filter_by(team_id=team.id, user_id=uid).delete()
                from app.utils.team_chat import sync_team_chat_members
                sync_team_chat_members(team)
                db.session.commit()
                flash(translate('settings.admin.teams.flash_member_removed'), 'success')
            return redirect(url_for('settings.admin_team_detail', team_id=team.id))

    member_user_ids = {m.user_id for m in team.members}
    members = sorted(
        [m for m in team.members if m.user],
        key=lambda m: ((m.user.last_name or '').lower(), (m.user.first_name or '').lower())
    )
    # Alle Portalnutzer außer System-Anonymous und bestehenden Mitgliedern
    # (aktive zuerst), damit Teamleitung andere Mitglieder klar auswählen kann.
    available_q = User.query.filter(User.email != 'anonymous@system.local')
    if member_user_ids:
        available_q = available_q.filter(~User.id.in_(list(member_user_ids)))
    available_users = available_q.order_by(
        User.is_active.desc(),
        User.last_name,
        User.first_name,
    ).all()

    return render_template(
        'settings/admin_team_detail.html',
        team=team,
        members=members,
        available_users=available_users,
        email_multi_enabled=is_email_multi_enabled(),
        can_edit_team_meta=current_user.is_admin,
    )


@settings_bp.route('/admin/teams/<int:team_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_team(team_id):
    """Edit team metadata (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.team import Team
    team = Team.query.get_or_404(team_id)
    leader_choices = _team_leader_choices()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None
        leader_id_raw = request.form.get('leader_id', '').strip()
        color = _normalize_team_color(request.form.get('color', ''))
        remove_image = request.form.get('remove_image') == '1'

        if not name:
            flash(translate('settings.admin.teams.flash_name_required'), 'danger')
            return render_template('settings/admin_team_form.html', team=team, leader_choices=leader_choices)

        if color is False:
            flash(translate('settings.admin.teams.flash_color_invalid'), 'danger')
            return render_template('settings/admin_team_form.html', team=team, leader_choices=leader_choices)

        if _team_name_taken(name, exclude_id=team.id):
            flash(translate('settings.admin.teams.flash_name_taken'), 'danger')
            return render_template('settings/admin_team_form.html', team=team, leader_choices=leader_choices)

        leader_id = int(leader_id_raw) if leader_id_raw.isdigit() else None
        if leader_id and not User.query.get(leader_id):
            leader_id = None

        team.name = name
        team.description = description
        team.color = color
        team.leader_id = leader_id
        from app.utils.private_files import sync_team_root_name
        sync_team_root_name(team)

        if remove_image and team.image:
            _delete_team_image_file(team.image)
            team.image = None

        image_file = request.files.get('image')
        filename, err = _save_team_image(image_file, team.id)
        if err:
            flash(translate(err), 'danger')
            return render_template('settings/admin_team_form.html', team=team, leader_choices=leader_choices)
        if filename:
            if team.image:
                _delete_team_image_file(team.image)
            team.image = filename

        if leader_id:
            _ensure_team_member(team.id, leader_id)

        from app.utils.team_chat import ensure_team_chat, sync_team_chat_name
        from app.models.calendar import Calendar as CalModel
        ensure_team_chat(team, created_by=current_user.id)
        sync_team_chat_name(team)
        for cal in CalModel.query.filter_by(calendar_type='team', team_id=team.id, is_default=True).all():
            if cal.name != team.name:
                cal.name = team.name

        db.session.commit()
        flash(translate('settings.admin.teams.flash_updated', name=team.name), 'success')
        return redirect(url_for('settings.admin_team_detail', team_id=team.id))

    return render_template('settings/admin_team_form.html', team=team, leader_choices=leader_choices)


@settings_bp.route('/admin/teams/<int:team_id>/delete', methods=['POST'])
@login_required
def delete_team(team_id):
    """Delete a team (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.team import Team
    from app.models.calendar import Calendar as CalModel, CalendarEvent
    from app.utils.private_files import soft_delete_team_tree
    from app.utils.team_chat import unlink_team_chat
    from app.utils.multi_calendars import get_public_calendar
    team = Team.query.get_or_404(team_id)
    name = team.name
    if team.image:
        _delete_team_image_file(team.image)
    soft_delete_team_tree(team.id, current_user.id)
    unlink_team_chat(team.id)
    public = get_public_calendar()
    for cal in CalModel.query.filter_by(calendar_type='team', team_id=team.id).all():
        CalendarEvent.query.filter_by(calendar_id=cal.id).update(
            {CalendarEvent.calendar_id: public.id},
            synchronize_session=False,
        )
        db.session.delete(cal)
    db.session.delete(team)
    db.session.commit()
    flash(translate('settings.admin.teams.flash_deleted', name=name), 'success')
    return redirect(url_for('settings.admin_teams'))


@settings_bp.route('/admin/teams/image/<path:filename>')
@login_required
def team_image(filename):
    """Serve team images."""
    try:
        from urllib.parse import unquote
        filename = unquote(filename)
        directory = _team_upload_dir()
        full_path = os.path.join(directory, filename)
        if not os.path.isfile(full_path):
            abort(404)
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        abort(404)


@settings_bp.route('/admin/users/<int:user_id>/teams', methods=['POST'])
@login_required
def set_user_teams(user_id):
    """Set team memberships for a user from the users list (admin only)."""
    if not current_user.is_admin:
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.index'))

    from app.models.team import Team, TeamMember
    user = User.query.get_or_404(user_id)
    if user.email == 'anonymous@system.local':
        flash(translate('settings.admin.flash_unauthorized'), 'danger')
        return redirect(url_for('settings.admin_users'))

    selected_raw = request.form.getlist('team_ids')
    selected_ids = {int(x) for x in selected_raw if x.isdigit()}
    valid_ids = {t.id for t in Team.query.filter(Team.id.in_(selected_ids)).all()} if selected_ids else set()

    existing = TeamMember.query.filter_by(user_id=user.id).all()
    existing_ids = {m.team_id for m in existing}

    for membership in existing:
        if membership.team_id not in valid_ids:
            team = Team.query.get(membership.team_id)
            if team and team.leader_id == user.id:
                team.leader_id = None
            db.session.delete(membership)

    for tid in valid_ids - existing_ids:
        db.session.add(TeamMember(team_id=tid, user_id=user.id))

    from app.utils.team_chat import ensure_team_chat, sync_team_chat_members
    for tid in (existing_ids | valid_ids):
        team = Team.query.get(tid)
        if team:
            ensure_team_chat(team, created_by=current_user.id)
            sync_team_chat_members(team)

    db.session.commit()
    flash(translate('settings.admin.teams.flash_user_teams_updated', name=user.full_name), 'success')
    return redirect(url_for('settings.admin_users'))
