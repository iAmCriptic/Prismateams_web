from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.utils.i18n import _
from app import db
from app.models.wiki import WikiPage, WikiPageVersion, WikiCategory, WikiTag, WikiFavorite
from app.models.user import User
from app.utils.markdown import process_markdown
from app.utils.common import is_module_enabled, format_datetime
from app.utils.access_control import check_module_access
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
from datetime import datetime
from sqlalchemy.orm import defer, joinedload, selectinload
import os
import re

wiki_bp = Blueprint('wiki', __name__, url_prefix='/wiki')

MAX_WIKI_VERSIONS = 3
WIKI_LIST_PER_PAGE = 24


def _wiki_index_page_url(
    page,
    *,
    search_query='',
    category_id=None,
    tag_id=None,
    sort_by='updated',
    sort_dir='desc',
    favorites_only=False,
    section=None,
    filter_team_id=None,
):
    """Build wiki index URL preserving filters and pagination."""
    kwargs = {'page': page, 'sort': sort_by, 'dir': sort_dir}
    if search_query:
        kwargs['q'] = search_query
    if category_id:
        kwargs['category'] = category_id
    if tag_id:
        kwargs['tag'] = tag_id
    if favorites_only:
        kwargs['view'] = 'favorites'
    elif section in ('private', 'team', 'public'):
        kwargs['view'] = section
        if section == 'team' and filter_team_id:
            kwargs['team_id'] = filter_team_id
    return url_for('wiki.index', **kwargs)


def check_wiki_module():
    """Prüft ob das Wiki-Modul aktiviert ist."""
    if not is_module_enabled('module_wiki'):
        flash(_('wiki.api.module_disabled'), 'warning')
        return False
    return True


def _wiki_sidebar_context():
    """Gemeinsame Sidebar-Daten für Index und View."""
    favorites = WikiFavorite.query.filter_by(user_id=current_user.id).all()
    my_wiki_favorites = [fav.wiki_page for fav in favorites if fav.wiki_page]
    favorite_ids = [fav.wiki_page_id for fav in favorites]
    section, filter_team_id = parse_section_args('wiki', current_user)
    ctx = {
        'categories': WikiCategory.query.order_by(WikiCategory.name).all(),
        'tags': WikiTag.query.order_by(WikiTag.name).all(),
        'my_wiki_favorites': my_wiki_favorites,
        'favorite_ids': favorite_ids,
        'show_favorites_nav': bool(favorite_ids),
        'search_query': '',
        'selected_category': None,
        'selected_tag': None,
        'sort_by': 'updated',
        'sort_dir': 'desc',
        'favorites_only': False,
        'active_favorites': False,
        'current_wiki_page_id': None,
    }
    ctx.update(visibility_nav_context('wiki', current_user, section, filter_team_id))
    return ctx


def _wiki_form_kwargs(page=None):
    section, filter_team_id = parse_section_args('wiki', current_user)
    pre_section = section if section in ('private', 'public', 'team') else None
    return visibility_form_context(
        'wiki',
        current_user,
        item=page,
        preselect_section=pre_section,
        preselect_team_id=filter_team_id,
    )


def _wiki_denied():
    flash(_('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('wiki.index'))


def _prune_wiki_versions(wiki_page_id):
    """Behält nur die letzten MAX_WIKI_VERSIONS Snapshots."""
    versions = WikiPageVersion.query.filter_by(wiki_page_id=wiki_page_id).order_by(
        WikiPageVersion.version_number.desc()
    ).all()
    for old in versions[MAX_WIKI_VERSIONS:]:
        if old.file_path and os.path.exists(old.file_path):
            try:
                os.remove(old.file_path)
            except OSError:
                pass
        db.session.delete(old)


@wiki_bp.route('/')
@login_required
@check_module_access('module_wiki')
def index():
    """Wiki Übersichtsseite mit Suche und Filter."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    # Suchparameter
    search_query = request.args.get('q', '').strip()
    category_id = request.args.get('category', type=int)
    tag_id = request.args.get('tag', type=int)
    view = (request.args.get('view') or '').strip().lower()
    section, filter_team_id = parse_section_args('wiki', current_user)
    favorites_only = request.args.get('favorites', type=int) == 1 or section == 'favorites'
    sort_by = request.args.get('sort', 'updated')  # updated, created, title
    sort_dir = request.args.get('dir', 'desc')
    list_page = max(1, request.args.get('page', 1, type=int) or 1)
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'
    if sort_by not in ('updated', 'created', 'title'):
        sort_by = 'updated'
    
    # Basis-Query (ohne Markdown-Content in der Liste)
    query = accessible_query(current_user, WikiPage, 'wiki').options(
        defer(WikiPage.content),
        joinedload(WikiPage.category),
        joinedload(WikiPage.creator),
        selectinload(WikiPage.tags),
    )
    favorite_rows = WikiFavorite.query.filter_by(user_id=current_user.id).all()
    favorite_ids = [fav.wiki_page_id for fav in favorite_rows]
    show_favorites_nav = bool(favorite_ids)
    
    # Filter nach Favoriten
    if favorites_only:
        if favorite_ids:
            query = query.filter(WikiPage.id.in_(favorite_ids))
        else:
            query = query.filter(WikiPage.id == -1)
    elif section in ('private', 'team', 'public'):
        query = apply_section_filter(query, WikiPage, section, filter_team_id)
    
    # Suche: Titel/Slug immer; Content nur als Filter (Spalte bleibt deferred)
    if search_query:
        search_filter = f'%{search_query}%'
        query = query.filter(
            db.or_(
                WikiPage.title.ilike(search_filter),
                WikiPage.slug.ilike(search_filter),
                WikiPage.content.ilike(search_filter),
            )
        )
    
    # Filter nach Kategorie
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    # Filter nach Tag
    if tag_id:
        query = query.join(WikiPage.tags).filter(WikiTag.id == tag_id)
    
    # Sortierung
    if sort_by == 'created':
        sort_col = WikiPage.created_at
    elif sort_by == 'title':
        sort_col = WikiPage.title
    else:  # updated (default)
        sort_col = WikiPage.updated_at

    if sort_dir == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())
    
    pagination = query.paginate(page=list_page, per_page=WIKI_LIST_PER_PAGE, error_out=False)
    pages = pagination.items
    sidebar = _wiki_sidebar_context()
    nav = visibility_nav_context('wiki', current_user, section, filter_team_id)
    url_kwargs = dict(
        search_query=search_query,
        category_id=category_id,
        tag_id=tag_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        favorites_only=favorites_only,
        section=section,
        filter_team_id=filter_team_id,
    )
    
    return render_template('wiki/index.html',
                         pages=pages,
                         pagination=pagination,
                         wiki_prev_url=(
                             _wiki_index_page_url(pagination.prev_num, **url_kwargs)
                             if pagination.has_prev else None
                         ),
                         wiki_next_url=(
                             _wiki_index_page_url(pagination.next_num, **url_kwargs)
                             if pagination.has_next else None
                         ),
                         categories=sidebar['categories'],
                         tags=sidebar['tags'],
                         search_query=search_query,
                         selected_category=category_id,
                         selected_tag=tag_id,
                         sort_by=sort_by,
                         sort_dir=sort_dir,
                         favorites_only=favorites_only,
                         active_favorites=favorites_only,
                         favorite_ids=favorite_ids,
                         show_favorites_nav=show_favorites_nav,
                         my_wiki_favorites=sidebar['my_wiki_favorites'],
                         current_wiki_page_id=None,
                         **nav)


@wiki_bp.route('/view/<slug>')
@login_required
@check_module_access('module_wiki')
def view(slug):
    """Wiki-Seite anzeigen."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    if not can_view_item(current_user, page, 'wiki'):
        return _wiki_denied()

    # Markdown verarbeiten
    processed_content = process_markdown(page.content, wiki_mode=True)
    sidebar = _wiki_sidebar_context()
    sidebar['current_wiki_page_id'] = page.id
    versions = WikiPageVersion.query.filter_by(wiki_page_id=page.id).order_by(
        WikiPageVersion.version_number.desc()
    ).all()

    return render_template('wiki/view.html',
                         page=page,
                         processed_content=processed_content,
                         versions=versions,
                         historical_version=None,
                         **sidebar)


@wiki_bp.route('/view/<slug>/version/<int:version_number>')
@login_required
@check_module_access('module_wiki')
def view_version(slug, version_number):
    """Alte Wiki-Version nur lesen (nicht bearbeiten)."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))

    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    if not can_view_item(current_user, page, 'wiki'):
        return _wiki_denied()
    version = WikiPageVersion.query.filter_by(
        wiki_page_id=page.id,
        version_number=version_number
    ).first_or_404()

    processed_content = process_markdown(version.content, wiki_mode=True)
    sidebar = _wiki_sidebar_context()
    sidebar['current_wiki_page_id'] = page.id
    versions = WikiPageVersion.query.filter_by(wiki_page_id=page.id).order_by(
        WikiPageVersion.version_number.desc()
    ).all()

    return render_template(
        'wiki/view.html',
        page=page,
        processed_content=processed_content,
        versions=versions,
        historical_version=version,
        **sidebar
    )


@wiki_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_wiki')
def create():
    """Neue Wiki-Seite erstellen."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        new_category_name = request.form.get('new_category_name', '').strip()
        tags_input = request.form.get('tags', '').strip()
        
        if not title:
            flash(_('wiki.create.alerts.title_required'), 'danger')
            categories = WikiCategory.query.order_by(WikiCategory.name).all()
            return render_template('wiki/create.html', categories=categories, content=content, **_wiki_form_kwargs())
        
        # Wenn eine neue Kategorie erstellt werden soll
        if new_category_name:
            # Prüfe ob Kategorie bereits existiert
            existing_category = WikiCategory.query.filter_by(name=new_category_name).first()
            if existing_category:
                category_id = existing_category.id
                flash(_('wiki.flash.category_exists', name=new_category_name), 'info')
            else:
                # Erstelle neue Kategorie
                new_category = WikiCategory(name=new_category_name)
                db.session.add(new_category)
                db.session.flush()  # Flush um die ID zu erhalten
                category_id = new_category.id
                flash(_('wiki.flash.category_created', name=new_category_name), 'success')
        
        # Erstelle Slug
        slug = WikiPage.slugify(title)
        
        # Prüfe ob Slug bereits existiert
        existing_page = WikiPage.query.filter_by(slug=slug).first()
        if existing_page:
            flash(_('wiki.flash.duplicate_title'), 'danger')
            categories = WikiCategory.query.order_by(WikiCategory.name).all()
            return render_template('wiki/create.html', categories=categories, title=title, content=content, **_wiki_form_kwargs())
        
        # Erstelle Datei
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{slug}.md"
        upload_dir = os.path.join('uploads', 'wiki')
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, filename)
        absolute_filepath = os.path.abspath(filepath)
        
        # Speichere Markdown-Datei
        # Kein Newline-Transform auf Windows, sonst entstehen doppelte Leerzeilen.
        with open(absolute_filepath, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        
        # Erstelle Wiki-Seite
        page = WikiPage(
            title=title,
            slug=slug,
            content=content,
            file_path=absolute_filepath,
            category_id=category_id,
            created_by=current_user.id
        )
        apply_visibility_from_form(page, 'wiki', current_user)
        
        db.session.add(page)
        
        # Verarbeite Tags
        if tags_input:
            tag_names = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
            for tag_name in tag_names:
                tag = WikiTag.query.filter_by(name=tag_name.lower()).first()
                if not tag:
                    tag = WikiTag(name=tag_name.lower())
                    db.session.add(tag)
                page.tags.append(tag)
        
        db.session.commit()
        
        flash(_('wiki.flash.created', title=title), 'success')
        return redirect(url_for('wiki.view', slug=slug))
    
    categories = WikiCategory.query.order_by(WikiCategory.name).all()
    return render_template('wiki/create.html', categories=categories, **_wiki_form_kwargs())


@wiki_bp.route('/edit/<slug>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_wiki')
def edit(slug):
    """Wiki-Seite bearbeiten."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    if not can_edit_item(current_user, page, 'wiki'):
        return _wiki_denied()
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        new_category_name = request.form.get('new_category_name', '').strip()
        tags_input = request.form.get('tags', '').strip()
        
        if not title:
            flash(_('wiki.edit.alerts.title_required'), 'danger')
            categories = WikiCategory.query.order_by(WikiCategory.name).all()
            tags = [tag.name for tag in page.tags]
            return render_template('wiki/edit.html', page=page, categories=categories, tags=', '.join(tags), **_wiki_form_kwargs(page))
        
        # Wenn eine neue Kategorie erstellt werden soll
        if new_category_name:
            # Prüfe ob Kategorie bereits existiert
            existing_category = WikiCategory.query.filter_by(name=new_category_name).first()
            if existing_category:
                category_id = existing_category.id
                flash(_('wiki.flash.category_exists', name=new_category_name), 'info')
            else:
                # Erstelle neue Kategorie
                new_category = WikiCategory(name=new_category_name)
                db.session.add(new_category)
                db.session.flush()  # Flush um die ID zu erhalten
                category_id = new_category.id
                flash(_('wiki.flash.category_created', name=new_category_name), 'success')
        
        # Speichere aktuelle Version als Snapshot (vor dem Überschreiben)
        version = WikiPageVersion(
            wiki_page_id=page.id,
            version_number=page.version_number,
            content=page.content,
            file_path=page.file_path,
            created_by=current_user.id
        )
        db.session.add(version)
        db.session.flush()
        _prune_wiki_versions(page.id)
        
        # Aktualisiere Seite
        new_slug = WikiPage.slugify(title)
        
        # Wenn Titel geändert wurde, prüfe ob neuer Slug existiert
        if new_slug != page.slug:
            existing_page = WikiPage.query.filter_by(slug=new_slug).first()
            if existing_page and existing_page.id != page.id:
                flash(_('wiki.flash.duplicate_title'), 'danger')
                categories = WikiCategory.query.order_by(WikiCategory.name).all()
                tags = [tag.name for tag in page.tags]
                return render_template('wiki/edit.html', page=page, categories=categories, tags=', '.join(tags), **_wiki_form_kwargs(page))
            page.slug = new_slug
        
        page.title = title
        page.content = content
        page.category_id = category_id
        page.version_number += 1
        page.updated_at = datetime.utcnow()
        apply_visibility_from_form(page, 'wiki', current_user)
        
        # Aktualisiere Datei
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{page.slug}.md"
        upload_dir = os.path.join('uploads', 'wiki')
        filepath = os.path.join(upload_dir, filename)
        absolute_filepath = os.path.abspath(filepath)
        
        # Kein Newline-Transform auf Windows, sonst entstehen doppelte Leerzeilen.
        with open(absolute_filepath, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        
        page.file_path = absolute_filepath
        
        # Aktualisiere Tags
        page.tags.clear()
        if tags_input:
            tag_names = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
            for tag_name in tag_names:
                tag = WikiTag.query.filter_by(name=tag_name.lower()).first()
                if not tag:
                    tag = WikiTag(name=tag_name.lower())
                    db.session.add(tag)
                page.tags.append(tag)
        
        db.session.commit()
        
        flash(_('wiki.flash.updated', title=title), 'success')
        return redirect(url_for('wiki.view', slug=page.slug))
    
    categories = WikiCategory.query.order_by(WikiCategory.name).all()
    tags = [tag.name for tag in page.tags]
    return render_template('wiki/edit.html', page=page, categories=categories, tags=', '.join(tags), **_wiki_form_kwargs(page))


@wiki_bp.route('/delete/<slug>', methods=['POST'])
@login_required
@check_module_access('module_wiki')
def delete(slug):
    """Wiki-Seite löschen."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    if not can_edit_item(current_user, page, 'wiki'):
        return _wiki_denied()
    
    # Lösche Datei
    if os.path.exists(page.file_path):
        os.remove(page.file_path)
    
    # Lösche alle Versionen
    for version in page.versions:
        if os.path.exists(version.file_path):
            os.remove(version.file_path)
    
    db.session.delete(page)
    db.session.commit()
    
    flash(_('wiki.flash.deleted', title=page.title), 'success')
    return redirect(url_for('wiki.index'))


@wiki_bp.route('/history/<slug>')
@login_required
@check_module_access('module_wiki')
def history(slug):
    """Versionshistorie öffnet als Side-Panel auf der View-Seite (wie Dateien)."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))

    # Alte Bookmarks / Links → Viewer mit geöffnetem History-Panel
    return redirect(url_for('wiki.view', slug=slug, history=1))


@wiki_bp.route('/api/history/<slug>', methods=['GET'])
@login_required
@check_module_access('module_wiki')
def api_history(slug):
    """JSON-Versionshistorie für das Side-Panel."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403

    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    if not can_view_item(current_user, page, 'wiki'):
        return jsonify({'error': _('visibility.flash.access_denied')}), 403
    versions = WikiPageVersion.query.filter_by(wiki_page_id=page.id).order_by(
        WikiPageVersion.version_number.desc()
    ).all()

    return jsonify({
        'success': True,
        'page': {
            'id': page.id,
            'title': page.title,
            'slug': page.slug,
            'version_number': page.version_number,
            'updated_at': format_datetime(page.updated_at) if page.updated_at else '',
            'creator': page.creator.full_name if page.creator else '—',
            'view_url': url_for('wiki.view', slug=page.slug),
        },
        'versions': [{
            'version_number': v.version_number,
            'created_at': format_datetime(v.created_at) if v.created_at else '',
            'creator': v.creator.full_name if v.creator else '—',
            'is_current': False,
            'view_url': url_for('wiki.view_version', slug=page.slug, version_number=v.version_number),
        } for v in versions]
    })


@wiki_bp.route('/search')
@login_required
@check_module_access('module_wiki')
def search():
    """Volltextsuche API."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403
    
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': []})
    
    search_filter = f'%{query}%'
    pages = accessible_query(current_user, WikiPage, 'wiki').filter(
        db.or_(
            WikiPage.title.ilike(search_filter),
            WikiPage.content.ilike(search_filter),
            WikiPage.slug.ilike(search_filter)
        )
    ).limit(10).all()
    
    results = [{
        'id': page.id,
        'title': page.title,
        'slug': page.slug,
        'excerpt': page.content[:200] + '...' if len(page.content) > 200 else page.content
    } for page in pages]
    
    return jsonify({'results': results})


@wiki_bp.route('/api/favorite/<int:page_id>', methods=['POST', 'DELETE'])
@login_required
@check_module_access('module_wiki')
def toggle_favorite(page_id):
    """Wiki-Seite zu Favoriten hinzufügen oder entfernen."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403
    
    page = WikiPage.query.get_or_404(page_id)
    if not can_view_item(current_user, page, 'wiki'):
        return jsonify({'error': _('visibility.flash.access_denied')}), 403
    
    if request.method == 'POST':
        # Prüfe ob bereits favorisiert
        existing_favorite = WikiFavorite.query.filter_by(
            user_id=current_user.id,
            wiki_page_id=page_id
        ).first()
        
        if existing_favorite:
            return jsonify({'error': _('wiki.api.favorite.already'), 'is_favorite': True}), 400
        
        # Prüfe ob bereits 5 Favoriten vorhanden
        favorite_count = WikiFavorite.query.filter_by(user_id=current_user.id).count()
        if favorite_count >= 5:
            return jsonify({'error': _('wiki.api.favorite.limit'), 'is_favorite': False}), 400
        
        # Füge zu Favoriten hinzu
        favorite = WikiFavorite(
            user_id=current_user.id,
            wiki_page_id=page_id
        )
        db.session.add(favorite)
        db.session.commit()
        favorites_count = WikiFavorite.query.filter_by(user_id=current_user.id).count()
        
        return jsonify({
            'success': True,
            'is_favorite': True,
            'favorites_count': favorites_count,
            'message': _('wiki.api.favorite.added')
        })
    
    elif request.method == 'DELETE':
        # Entferne aus Favoriten
        favorite = WikiFavorite.query.filter_by(
            user_id=current_user.id,
            wiki_page_id=page_id
        ).first()
        
        if favorite:
            db.session.delete(favorite)
            db.session.commit()
            favorites_count = WikiFavorite.query.filter_by(user_id=current_user.id).count()
            return jsonify({
                'success': True,
                'is_favorite': False,
                'favorites_count': favorites_count,
                'message': _('wiki.api.favorite.removed')
            })
        else:
            return jsonify({'error': _('wiki.api.favorite.missing'), 'is_favorite': False}), 404


@wiki_bp.route('/api/favorite/check/<int:page_id>', methods=['GET'])
@login_required
@check_module_access('module_wiki')
def check_favorite(page_id):
    """Prüfe ob Wiki-Seite favorisiert ist."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403
    
    favorite = WikiFavorite.query.filter_by(
        user_id=current_user.id,
        wiki_page_id=page_id
    ).first()
    
    return jsonify({'is_favorite': favorite is not None})


