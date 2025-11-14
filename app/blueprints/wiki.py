from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.models.wiki import WikiPage, WikiPageVersion, WikiCategory, WikiTag, WikiFavorite
from app.models.user import User
from app.utils.markdown import process_markdown
from app.utils.common import is_module_enabled
from datetime import datetime
import os
import re

wiki_bp = Blueprint('wiki', __name__, url_prefix='/wiki')

MAX_WIKI_VERSIONS = 10


def check_wiki_module():
    """Prüft ob das Wiki-Modul aktiviert ist."""
    if not is_module_enabled('module_wiki'):
        flash(_('wiki.api.module_disabled'), 'warning')
        return False
    return True


@wiki_bp.route('/')
@login_required
def index():
    """Wiki Übersichtsseite mit Suche und Filter."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    # Suchparameter
    search_query = request.args.get('q', '').strip()
    category_id = request.args.get('category', type=int)
    tag_id = request.args.get('tag', type=int)
    favorites_only = request.args.get('favorites', type=int) == 1
    sort_by = request.args.get('sort', 'updated')  # updated, created, title
    
    # Basis-Query
    query = WikiPage.query
    
    # Filter nach Favoriten
    if favorites_only:
        favorite_ids = [fav.wiki_page_id for fav in WikiFavorite.query.filter_by(user_id=current_user.id).all()]
        if favorite_ids:
            query = query.filter(WikiPage.id.in_(favorite_ids))
        else:
            # Wenn keine Favoriten vorhanden, leere Liste zurückgeben
            query = query.filter(WikiPage.id == -1)  # Immer leer
    
    # Suche
    if search_query:
        search_filter = f'%{search_query}%'
        query = query.filter(
            db.or_(
                WikiPage.title.ilike(search_filter),
                WikiPage.content.ilike(search_filter),
                WikiPage.slug.ilike(search_filter)
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
        query = query.order_by(WikiPage.created_at.desc())
    elif sort_by == 'title':
        query = query.order_by(WikiPage.title.asc())
    else:  # updated (default)
        query = query.order_by(WikiPage.updated_at.desc())
    
    pages = query.all()
    
    # Alle Kategorien und Tags für Filter
    categories = WikiCategory.query.order_by(WikiCategory.name).all()
    tags = WikiTag.query.order_by(WikiTag.name).all()
    
    # Favoriten-Anzahl für Button-Badge
    favorites = WikiFavorite.query.filter_by(
        user_id=current_user.id
    ).all()
    my_wiki_favorites = [fav.wiki_page for fav in favorites]
    
    return render_template('wiki/index.html',
                         pages=pages,
                         categories=categories,
                         tags=tags,
                         search_query=search_query,
                         selected_category=category_id,
                         selected_tag=tag_id,
                         sort_by=sort_by,
                         favorites_only=favorites_only,
                         my_wiki_favorites=my_wiki_favorites)


@wiki_bp.route('/view/<slug>')
@login_required
def view(slug):
    """Wiki-Seite anzeigen."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    
    # Markdown verarbeiten
    processed_content = process_markdown(page.content, wiki_mode=True)
    
    return render_template('wiki/view.html', page=page, processed_content=processed_content)


@wiki_bp.route('/create', methods=['GET', 'POST'])
@login_required
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
            return render_template('wiki/create.html', categories=categories, content=content)
        
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
            return render_template('wiki/create.html', categories=categories, title=title, content=content)
        
        # Erstelle Datei
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{slug}.md"
        upload_dir = os.path.join('uploads', 'wiki')
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, filename)
        absolute_filepath = os.path.abspath(filepath)
        
        # Speichere Markdown-Datei
        with open(absolute_filepath, 'w', encoding='utf-8') as f:
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
    return render_template('wiki/create.html', categories=categories)


@wiki_bp.route('/edit/<slug>', methods=['GET', 'POST'])
@login_required
def edit(slug):
    """Wiki-Seite bearbeiten."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    
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
            return render_template('wiki/edit.html', page=page, categories=categories, tags=', '.join(tags))
        
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
        
        # Speichere aktuelle Version
        version = WikiPageVersion(
            wiki_page_id=page.id,
            version_number=page.version_number,
            content=page.content,
            file_path=page.file_path,
            created_by=current_user.id
        )
        db.session.add(version)
        
        # Lösche älteste Versionen wenn nötig
        versions = WikiPageVersion.query.filter_by(wiki_page_id=page.id).order_by(
            WikiPageVersion.version_number.desc()
        ).all()
        
        if len(versions) >= MAX_WIKI_VERSIONS:
            oldest = versions[-1]
            if os.path.exists(oldest.file_path):
                os.remove(oldest.file_path)
            db.session.delete(oldest)
        
        # Aktualisiere Seite
        new_slug = WikiPage.slugify(title)
        
        # Wenn Titel geändert wurde, prüfe ob neuer Slug existiert
        if new_slug != page.slug:
            existing_page = WikiPage.query.filter_by(slug=new_slug).first()
            if existing_page and existing_page.id != page.id:
                flash(_('wiki.flash.duplicate_title'), 'danger')
                categories = WikiCategory.query.order_by(WikiCategory.name).all()
                tags = [tag.name for tag in page.tags]
                return render_template('wiki/edit.html', page=page, categories=categories, tags=', '.join(tags))
            page.slug = new_slug
        
        page.title = title
        page.content = content
        page.category_id = category_id
        page.version_number += 1
        page.updated_at = datetime.utcnow()
        
        # Aktualisiere Datei
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{page.slug}.md"
        upload_dir = os.path.join('uploads', 'wiki')
        filepath = os.path.join(upload_dir, filename)
        absolute_filepath = os.path.abspath(filepath)
        
        with open(absolute_filepath, 'w', encoding='utf-8') as f:
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
    return render_template('wiki/edit.html', page=page, categories=categories, tags=', '.join(tags))


@wiki_bp.route('/delete/<slug>', methods=['POST'])
@login_required
def delete(slug):
    """Wiki-Seite löschen."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    
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
def history(slug):
    """Versionshistorie einer Wiki-Seite anzeigen."""
    if not check_wiki_module():
        return redirect(url_for('dashboard.index'))
    
    page = WikiPage.query.filter_by(slug=slug).first_or_404()
    versions = WikiPageVersion.query.filter_by(wiki_page_id=page.id).order_by(
        WikiPageVersion.version_number.desc()
    ).all()
    
    return render_template('wiki/history.html', page=page, versions=versions)


@wiki_bp.route('/preview', methods=['POST'])
@login_required
def preview():
    """Vorschau-Endpoint für Editor (nutzt gleiche Logik wie /view/)."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403
    
    content = request.form.get('content', '')
    processed_content = process_markdown(content, wiki_mode=True)
    
    return jsonify({'html': processed_content})


@wiki_bp.route('/search')
@login_required
def search():
    """Volltextsuche API."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403
    
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': []})
    
    search_filter = f'%{query}%'
    pages = WikiPage.query.filter(
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
def toggle_favorite(page_id):
    """Wiki-Seite zu Favoriten hinzufügen oder entfernen."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403
    
    page = WikiPage.query.get_or_404(page_id)
    
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
        
        return jsonify({'success': True, 'is_favorite': True, 'message': _('wiki.api.favorite.added')})
    
    elif request.method == 'DELETE':
        # Entferne aus Favoriten
        favorite = WikiFavorite.query.filter_by(
            user_id=current_user.id,
            wiki_page_id=page_id
        ).first()
        
        if favorite:
            db.session.delete(favorite)
            db.session.commit()
            return jsonify({'success': True, 'is_favorite': False, 'message': _('wiki.api.favorite.removed')})
        else:
            return jsonify({'error': _('wiki.api.favorite.missing'), 'is_favorite': False}), 404


@wiki_bp.route('/api/favorite/check/<int:page_id>', methods=['GET'])
@login_required
def check_favorite(page_id):
    """Prüfe ob Wiki-Seite favorisiert ist."""
    if not check_wiki_module():
        return jsonify({'error': _('wiki.api.module_disabled')}), 403
    
    favorite = WikiFavorite.query.filter_by(
        user_id=current_user.id,
        wiki_page_id=page_id
    ).first()
    
    return jsonify({'is_favorite': favorite is not None})


