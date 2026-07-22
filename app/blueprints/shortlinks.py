import random
import re
import string
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, case, or_
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models.shortlink import ShortLink
from app.utils.access_control import check_module_access

shortlinks_bp = Blueprint('shortlinks', __name__)

SLUG_PATTERN = re.compile(r'^[A-Za-z0-9_-]{3,64}$')
SLUG_ALPHABET = string.ascii_letters + string.digits

SORT_FIELDS = {'created', 'clicks', 'expires', 'slug', 'last_click'}
SORT_DIRS = {'asc', 'desc'}
STATUS_FILTERS = {'', 'active', 'inactive', 'disabled'}
EXPIRY_FILTERS = {'', 'with', 'without', 'soon'}
PASSWORD_FILTERS = {'', 'yes', 'no'}
CLICKS_FILTERS = {'', 'with_limit', 'limit_reached'}
EXPIRING_SOON_DAYS = 7


def _normalize_target_url(raw_url):
    target_url = (raw_url or '').strip()
    if not target_url:
        return ''
    if not (target_url.startswith('http://') or target_url.startswith('https://')):
        target_url = f'https://{target_url}'
    return target_url


def _generate_random_slug(length=7):
    return ''.join(random.choice(SLUG_ALPHABET) for _ in range(length))


def _build_unique_slug(custom_slug=None):
    if custom_slug:
        candidate = custom_slug.strip()
        if not SLUG_PATTERN.match(candidate):
            return None, 'Das Kürzel darf nur Buchstaben, Zahlen, - und _ enthalten (3-64 Zeichen).'
        if ShortLink.query.filter_by(slug=candidate).first():
            return None, 'Dieses Kürzel ist bereits vergeben.'
        return candidate, None

    for _ in range(20):
        candidate = _generate_random_slug()
        if not ShortLink.query.filter_by(slug=candidate).first():
            return candidate, None
    return None, 'Konnte kein freies Zufalls-Kürzel erstellen. Bitte erneut versuchen.'


def _parse_expires_at(value):
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%dT%H:%M')
    except ValueError:
        return 'invalid'


def _parse_max_clicks(value):
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
        return parsed if parsed > 0 else 'invalid'
    except ValueError:
        return 'invalid'


def _whitelist(value, allowed, default=''):
    raw = (value or '').strip()
    return raw if raw in allowed else default


def _not_expired_clause(now):
    return or_(ShortLink.expires_at.is_(None), ShortLink.expires_at > now)


def _not_max_clicks_clause():
    return or_(ShortLink.max_clicks.is_(None), ShortLink.click_count < ShortLink.max_clicks)


@shortlinks_bp.route('/shortlinks')
@login_required
@check_module_access('module_shortlinks')
def index():
    search_query = (request.args.get('q') or '').strip()
    sort_by = _whitelist(request.args.get('sort'), SORT_FIELDS, 'created')
    sort_dir = _whitelist(request.args.get('dir'), SORT_DIRS, 'desc')
    status_filter = _whitelist(request.args.get('status'), STATUS_FILTERS)
    expiry_filter = _whitelist(request.args.get('expiry'), EXPIRY_FILTERS)
    password_filter = _whitelist(request.args.get('password'), PASSWORD_FILTERS)
    clicks_filter = _whitelist(request.args.get('clicks'), CLICKS_FILTERS)

    now = datetime.utcnow()
    soon = now + timedelta(days=EXPIRING_SOON_DAYS)

    query = ShortLink.query.filter_by(created_by=current_user.id)

    if search_query:
        like = f'%{search_query}%'
        query = query.filter(or_(
            ShortLink.slug.ilike(like),
            ShortLink.target_url.ilike(like),
        ))

    if status_filter == 'active':
        query = query.filter(
            ShortLink.is_active.is_(True),
            _not_expired_clause(now),
            _not_max_clicks_clause(),
        )
    elif status_filter == 'inactive':
        query = query.filter(or_(
            ShortLink.is_active.is_(False),
            and_(ShortLink.expires_at.isnot(None), ShortLink.expires_at <= now),
            and_(ShortLink.max_clicks.isnot(None), ShortLink.click_count >= ShortLink.max_clicks),
        ))
    elif status_filter == 'disabled':
        query = query.filter(ShortLink.is_active.is_(False))

    if expiry_filter == 'with':
        query = query.filter(ShortLink.expires_at.isnot(None))
    elif expiry_filter == 'without':
        query = query.filter(ShortLink.expires_at.is_(None))
    elif expiry_filter == 'soon':
        query = query.filter(
            ShortLink.expires_at.isnot(None),
            ShortLink.expires_at > now,
            ShortLink.expires_at <= soon,
        )

    if password_filter == 'yes':
        query = query.filter(ShortLink.password_hash.isnot(None))
    elif password_filter == 'no':
        query = query.filter(ShortLink.password_hash.is_(None))

    if clicks_filter == 'with_limit':
        query = query.filter(ShortLink.max_clicks.isnot(None))
    elif clicks_filter == 'limit_reached':
        query = query.filter(
            ShortLink.max_clicks.isnot(None),
            ShortLink.click_count >= ShortLink.max_clicks,
        )

    sort_column_map = {
        'created': ShortLink.created_at,
        'clicks': ShortLink.click_count,
        'slug': ShortLink.slug,
        'last_click': ShortLink.last_clicked_at,
    }

    if sort_by == 'expires':
        # Links without expiry go to the end regardless of direction
        nulls_last = case((ShortLink.expires_at.is_(None), 1), else_=0)
        col = ShortLink.expires_at.asc() if sort_dir == 'asc' else ShortLink.expires_at.desc()
        query = query.order_by(nulls_last.asc(), col)
    else:
        col = sort_column_map[sort_by]
        query = query.order_by(col.asc() if sort_dir == 'asc' else col.desc())

    links = query.all()
    return render_template(
        'shortlinks/index.html',
        links=links,
        search_query=search_query,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status_filter=status_filter,
        expiry_filter=expiry_filter,
        password_filter=password_filter,
        clicks_filter=clicks_filter,
    )


@shortlinks_bp.route('/shortlinks/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_shortlinks')
def create():
    if request.method == 'POST':
        target_url = _normalize_target_url(request.form.get('target_url'))
        custom_slug = (request.form.get('slug') or '').strip()
        password = request.form.get('password') or ''
        expires_at = _parse_expires_at(request.form.get('expires_at'))
        max_clicks = _parse_max_clicks(request.form.get('max_clicks'))

        if not target_url:
            flash('Bitte eine Ziel-URL angeben.', 'danger')
            return render_template('shortlinks/form.html', link=None)
        if expires_at == 'invalid':
            flash('Ungültiges Ablaufdatum.', 'danger')
            return render_template('shortlinks/form.html', link=None)
        if max_clicks == 'invalid':
            flash('Maximale Aufrufe müssen eine positive Zahl sein.', 'danger')
            return render_template('shortlinks/form.html', link=None)

        slug, error = _build_unique_slug(custom_slug if custom_slug else None)
        if error:
            flash(error, 'danger')
            return render_template('shortlinks/form.html', link=None)

        link = ShortLink(
            created_by=current_user.id,
            target_url=target_url,
            slug=slug,
            password_hash=generate_password_hash(password) if password else None,
            expires_at=expires_at,
            max_clicks=max_clicks,
        )
        db.session.add(link)
        db.session.commit()
        flash('Kurzlink wurde erstellt.', 'success')
        return redirect(url_for('shortlinks.index'))

    return render_template('shortlinks/form.html', link=None)


@shortlinks_bp.route('/shortlinks/<int:link_id>/edit', methods=['GET', 'POST'])
@login_required
@check_module_access('module_shortlinks')
def edit(link_id):
    link = ShortLink.query.filter_by(id=link_id, created_by=current_user.id).first_or_404()
    if request.method == 'POST':
        target_url = _normalize_target_url(request.form.get('target_url'))
        custom_slug = (request.form.get('slug') or '').strip()
        password = request.form.get('password') or ''
        expires_at = _parse_expires_at(request.form.get('expires_at'))
        max_clicks = _parse_max_clicks(request.form.get('max_clicks'))
        is_active = request.form.get('is_active') == 'on'

        if not target_url:
            flash('Bitte eine Ziel-URL angeben.', 'danger')
            return render_template('shortlinks/form.html', link=link)
        if expires_at == 'invalid':
            flash('Ungültiges Ablaufdatum.', 'danger')
            return render_template('shortlinks/form.html', link=link)
        if max_clicks == 'invalid':
            flash('Maximale Aufrufe müssen eine positive Zahl sein.', 'danger')
            return render_template('shortlinks/form.html', link=link)

        if custom_slug != link.slug:
            slug, error = _build_unique_slug(custom_slug if custom_slug else None)
            if error:
                flash(error, 'danger')
                return render_template('shortlinks/form.html', link=link)
            link.slug = slug

        link.target_url = target_url
        link.expires_at = expires_at
        link.max_clicks = max_clicks
        link.is_active = is_active
        if password.strip():
            link.password_hash = generate_password_hash(password)
        elif request.form.get('clear_password') == 'on':
            link.password_hash = None

        db.session.commit()
        flash('Kurzlink wurde aktualisiert.', 'success')
        return redirect(url_for('shortlinks.index'))

    return render_template('shortlinks/form.html', link=link)


@shortlinks_bp.route('/shortlinks/<int:link_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_shortlinks')
def delete(link_id):
    link = ShortLink.query.filter_by(id=link_id, created_by=current_user.id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    flash('Kurzlink wurde gelöscht.', 'success')
    return redirect(url_for('shortlinks.index'))


@shortlinks_bp.route('/fw-<slug>', methods=['GET', 'POST'])
def resolve(slug):
    link = ShortLink.query.filter_by(slug=slug).first()
    if not link or not link.is_accessible():
        return render_template('shortlinks/unavailable.html'), 404

    if link.password_hash:
        password = request.form.get('password') if request.method == 'POST' else None
        if not password or not check_password_hash(link.password_hash, password):
            if request.method == 'POST':
                flash('Passwort ist falsch.', 'danger')
            return render_template('shortlinks/password.html', shortlink=link), 401

    link.click_count += 1
    link.last_clicked_at = datetime.utcnow()
    db.session.commit()
    return redirect(link.target_url, code=302)
