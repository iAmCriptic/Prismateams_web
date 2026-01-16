from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.music import MusicProviderToken, MusicWish, MusicQueue, MusicSettings
from app.blueprints.sse import emit_music_update
from app.utils.music_oauth import (
    get_spotify_oauth_url, get_youtube_oauth_url,
    handle_spotify_callback, handle_youtube_callback,
    is_provider_connected, disconnect_provider
)
from app.utils.music_api import search_music, get_track, search_music_multi_provider
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from sqlalchemy.orm import joinedload
from sqlalchemy import func, case
from datetime import datetime
import secrets
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

music_bp = Blueprint('music', __name__, url_prefix='/music')


# Cache für SystemSettings (5 Minuten TTL)
@lru_cache(maxsize=128)
def get_cached_system_setting(key):
    """Holt eine System-Einstellung mit LRU-Cache."""
    from app.models.settings import SystemSettings
    setting = SystemSettings.query.filter_by(key=key).first()
    return setting.value if setting else None


def invalidate_system_settings_cache():
    """Invalidiert den SystemSettings-Cache."""
    get_cached_system_setting.cache_clear()


# Öffentliche Route (kein Login erforderlich)
@music_bp.route('/wishlist', methods=['GET', 'POST'])
def public_wishlist():
    """Öffentliche Wunschliste - Suche und Hinzufügen von Liedern."""
    
    # Prüfe ob Provider aktiviert sind
    enabled_providers = MusicSettings.get_enabled_providers()
    has_providers = len(enabled_providers) > 0
    
    if request.method == 'POST':
        # Lied zur Wunschliste hinzufügen
        provider = request.form.get('provider', '').strip()
        track_id = request.form.get('track_id', '').strip()
        title = request.form.get('title', '').strip()
        artist = request.form.get('artist', '').strip()
        track_url = request.form.get('track_url', '').strip()
        image_url = request.form.get('image_url', '').strip()
        duration_ms = request.form.get('duration_ms', '').strip()
        
        if not all([provider, track_id, title]):
            return jsonify({'error': translate('music.flash.missing_data')}), 400
        
        # Prüfe ob Lied bereits existiert (beliebiger Status)
        existing = MusicWish.query.filter_by(
            provider=provider,
            track_id=track_id
        ).first()
        
        if existing:
            # Lied existiert bereits - erhöhe Wunschzähler
            existing.wish_count += 1
            existing.updated_at = datetime.utcnow()
            # Status bleibt unverändert (played bleibt played, pending bleibt pending, etc.)
            db.session.commit()
            
            # SSE-Update senden (funktioniert mit mehreren Gunicorn-Workern)
            emit_music_update('wish_updated', {
                'wish': {
                    'id': existing.id,
                    'title': existing.title,
                    'artist': existing.artist or '',
                    'provider': existing.provider,
                    'image_url': existing.image_url or '',
                    'wish_count': existing.wish_count,
                    'status': existing.status,
                    'created_at': existing.created_at.isoformat() if existing.created_at else None
                }
            })
            
            return jsonify({'success': True, 'message': translate('music.flash.wish_count_increased', count=existing.wish_count)})
        
        # Erstelle neuen Wunsch
        wish = MusicWish(
            title=title,
            artist=artist or '',
            provider=provider,
            track_id=track_id,
            track_url=track_url or '',
            image_url=image_url or '',
            duration_ms=int(duration_ms) if duration_ms and duration_ms.isdigit() else None,
            added_by_name=request.form.get('added_by_name', '').strip() or None,
            status='pending',
            wish_count=1
        )
        
        db.session.add(wish)
        db.session.commit()
        
        # SSE-Update senden (funktioniert mit mehreren Gunicorn-Workern)
        emit_music_update('wish_added', {
            'wish': {
                'id': wish.id,
                'title': wish.title,
                'artist': wish.artist or '',
                'provider': wish.provider,
                'image_url': wish.image_url or '',
                'wish_count': wish.wish_count,
                'status': wish.status,
                'created_at': wish.created_at.isoformat() if wish.created_at else None
            }
        })
        
        return jsonify({'success': True, 'message': translate('music.flash.wish_added')})
    
    # GET: Zeige Suchseite
    # Hole Einstellungen für Template (mit Cache)
    color_gradient = get_cached_system_setting('color_gradient')
    
    portal_logo_filename = get_cached_system_setting('portal_logo') or None
    
    # Hole App-Name
    portal_name = get_cached_system_setting('portal_name')
    if portal_name and portal_name.strip():
        app_name = portal_name
    else:
        org_name = get_cached_system_setting('organization_name')
        if org_name and org_name.strip():
            app_name = org_name
        else:
            app_name = current_app.config.get('APP_NAME', 'Prismateams')
    
    # Hole App-Logo
    app_logo = current_app.config.get('APP_LOGO')
    if portal_logo_filename:
        app_logo = None
    
    # Hole Einstellung für Provider-Badge-Anzeige
    show_provider_badges = MusicSettings.get_show_provider_badges()
    
    return render_template('music/public_wishlist.html', 
                         has_providers=has_providers,
                         enabled_providers=enabled_providers,
                         color_gradient=color_gradient,
                         portal_logo_filename=portal_logo_filename,
                         app_name=app_name,
                         app_logo=app_logo,
                         show_provider_badges=show_provider_badges)


@music_bp.route('/wishlist/search', methods=['POST'])
def public_search():
    """Öffentliche Suche nach Liedern über alle aktivierten Provider."""
    
    query = request.json.get('query', '').strip()
    include_recommendations = request.json.get('recommendations', True)  # Default: True
    
    if not query:
        return jsonify({'error': translate('music.flash.query_required')}), 400
    
    # Prüfe ob Provider aktiviert sind
    enabled_providers = MusicSettings.get_enabled_providers()
    if not enabled_providers:
        return jsonify({
            'error': translate('music.public_wishlist.no_providers'),
            'results': [],
            'recommendations': []
        }), 200  # 200 statt 400, damit Frontend die Nachricht anzeigen kann
    
    try:
        # Verwende Multi-Provider-Suche (automatisch über alle aktivierten Provider)
        # Übergebe user_id wenn Benutzer eingeloggt ist (für Spotify OAuth)
        user_id = current_user.id if current_user.is_authenticated else None
        search_result = search_music_multi_provider(
            query, 
            limit=10, 
            min_results=5, 
            user_id=user_id,
            include_recommendations=include_recommendations
        )
        
        # search_result ist jetzt ein Dictionary mit 'results' und 'recommendations'
        results = search_result.get('results', [])
        recommendations = search_result.get('recommendations', [])
        
        # Logge für Debugging
        logger.info(f"Suche nach '{query}': {len(results)} Ergebnisse, {len(recommendations)} Empfehlungen")
        
        return jsonify({
            'results': results,
            'recommendations': recommendations
        })
    except Exception as e:
        logger.error(f"Fehler bei Multi-Provider-Suche: {e}", exc_info=True)
        # Gebe benutzerfreundliche Fehlermeldung zurück
        error_message = str(e)
        if 'user_id erforderlich' in error_message or 'Token' in error_message:
            error_message = "Spotify-Provider benötigt eine Verbindung. Bitte kontaktieren Sie einen Administrator."
        elif 'API-Key' in error_message:
            error_message = "YouTube-Provider benötigt einen API-Key. Bitte kontaktieren Sie einen Administrator."
        return jsonify({
            'error': translate('music.flash.search_error', error=error_message),
            'results': [],
            'recommendations': []
        }), 500


# Admin-Routen (Login erforderlich)
@music_bp.route('/')
@login_required
@check_module_access('module_music')
def index():
    """Hauptseite für Musikmodul - Warteschlangen-Verwaltung."""
    # Optimiertes Initial-Load: Nur Counts und erste Tab-Daten laden
    # Nur Wunschliste für ersten Tab laden (maximal 50 Einträge)
    wishes = MusicWish.query.filter_by(status='pending').order_by(
        MusicWish.created_at.desc()
    ).limit(50).all()
    
    # Hole Warteschlange mit joinedload für N+1 Optimierung
    queue = MusicQueue.query.options(joinedload(MusicQueue.wish)).filter_by(
        status='pending'
    ).order_by(MusicQueue.position.asc()).all()
    
    # Hole aktuell spielendes Lied mit joinedload
    playing = MusicQueue.query.options(joinedload(MusicQueue.wish)).filter_by(
        status='playing'
    ).first()
    
    # Optimierte Count-Queries: Separate Counts (effizienter bei kleinen Tabellen und mit Indizes)
    wish_count = db.session.query(func.count(MusicWish.id)).filter_by(status='pending').scalar() or 0
    queue_count = db.session.query(func.count(MusicQueue.id)).filter_by(status='pending').scalar() or 0
    played_count = db.session.query(func.count(MusicWish.id)).filter_by(status='played').scalar() or 0
    
    return render_template('music/index.html',
                         wishes=wishes,
                         queue=queue,
                         playing=playing,
                         wish_count=wish_count,
                         queue_count=queue_count,
                         played_count=played_count)


@music_bp.route('/wishlist/add-to-queue', methods=['POST'])
@login_required
@check_module_access('module_music')
def add_to_queue():
    """Fügt ein Lied von der Wunschliste zur Warteschlange hinzu."""
    wish_id = request.json.get('wish_id')
    position = request.json.get('position', 'end')  # 'next', 'last', 'end'
    
    wish = MusicWish.query.get_or_404(wish_id)
    
    if wish.status != 'pending':
        return jsonify({'error': translate('music.flash.already_processed')}), 400
    
    # Prüfe ob bereits in Queue
    existing_queue = MusicQueue.query.filter_by(wish_id=wish_id).first()
    if existing_queue:
        return jsonify({'error': translate('music.flash.already_in_queue')}), 400
    
    # Bestimme Position (optimiert mit func.max)
    if position == 'next':
        # Als nächstes Lied
        new_position = 1
        # Verschiebe alle anderen nach hinten (nur Position-Updates, kein joinedload nötig)
        existing = MusicQueue.query.filter_by(status='pending').order_by(MusicQueue.position.asc()).all()
        for entry in existing:
            entry.position += 1
    elif position == 'last':
        # Als letztes Lied von Wunschliedern
        # Finde die höchste Position (optimiert mit func.max)
        max_pos = db.session.query(func.max(MusicQueue.position)).filter_by(status='pending').scalar() or 0
        new_position = max_pos + 1
    else:  # 'end'
        # Am Ende
        max_pos = db.session.query(func.max(MusicQueue.position)).filter_by(status='pending').scalar() or 0
        new_position = max_pos + 1
    
    # Erstelle Queue-Eintrag
    queue_entry = MusicQueue(
        wish_id=wish.id,
        position=new_position,
        status='pending',
        added_by=current_user.id
    )
    
    wish.status = 'in_queue'
    
    db.session.add(queue_entry)
    db.session.commit()
    
    # Lade vollständige Queue-Daten für SocketIO-Update
    queue = MusicQueue.query.filter_by(status='pending').order_by(MusicQueue.position.asc()).all()
    queue_data = []
    for entry in queue:
        queue_data.append({
            'id': entry.id,
            'position': entry.position,
            'wish': {
                'id': entry.wish.id,
                'title': entry.wish.title,
                'artist': entry.wish.artist or '',
                'provider': entry.wish.provider,
                'image_url': entry.wish.image_url or '',
                'wish_count': entry.wish.wish_count
            }
        })
    
    # SSE-Update senden (funktioniert mit mehreren Gunicorn-Workern)
    emit_music_update('queue_updated', {
        'action': 'added',
        'queue': queue_data
    })
    
    # Sende auch Wish-Update (Status geändert)
    emit_music_update('wish_updated', {
        'wish': {
            'id': wish.id,
            'title': wish.title,
            'artist': wish.artist or '',
            'provider': wish.provider,
            'image_url': wish.image_url or '',
            'wish_count': wish.wish_count,
            'status': wish.status,
            'created_at': wish.created_at.isoformat() if wish.created_at else None
        }
    })
    
    return jsonify({'success': True})


@music_bp.route('/wishlist/mark-as-played', methods=['POST'])
@login_required
@check_module_access('module_music')
def mark_wish_as_played():
    """Markiert einen Wunsch direkt als bereits gespielt, ohne zur Queue hinzuzufügen."""
    wish_id = request.json.get('wish_id')
    
    wish = MusicWish.query.get_or_404(wish_id)
    
    if wish.status == 'played':
        return jsonify({'error': translate('music.flash.already_played')}), 400
    
    # Setze Status auf 'played'
    wish.status = 'played'
    wish.updated_at = datetime.utcnow()
    
    # Entferne aus Queue falls vorhanden
    if wish.queue_entry:
        db.session.delete(wish.queue_entry)
    
    db.session.commit()
    
    # SSE-Update senden (funktioniert mit mehreren Gunicorn-Workern)
    emit_music_update('wish_updated', {
        'wish': {
            'id': wish.id,
            'title': wish.title,
            'artist': wish.artist or '',
            'provider': wish.provider,
            'image_url': wish.image_url or '',
            'wish_count': wish.wish_count,
            'status': wish.status,
            'created_at': wish.created_at.isoformat() if wish.created_at else None,
            'updated_at': wish.updated_at.isoformat() if wish.updated_at else None
        }
    })
    
    # Sende spezielles Event für "Played"-Updates (optimiertes Count)
    played_count = db.session.query(func.count(MusicWish.id)).filter_by(status='played').scalar() or 0
    emit_music_update('played_updated', {
        'wish': {
            'id': wish.id,
            'title': wish.title,
            'artist': wish.artist or '',
            'provider': wish.provider,
            'image_url': wish.image_url or '',
            'wish_count': wish.wish_count,
            'updated_at': wish.updated_at.isoformat() if wish.updated_at else None
        },
        'count': played_count
    })
    
    # Sende auch Queue-Update falls Queue-Eintrag entfernt wurde (mit joinedload)
    queue = MusicQueue.query.options(joinedload(MusicQueue.wish)).filter_by(
        status='pending'
    ).order_by(MusicQueue.position.asc()).all()
    queue_data = []
    for entry in queue:
        queue_data.append({
            'id': entry.id,
            'position': entry.position,
            'wish': {
                'id': entry.wish.id,
                'title': entry.wish.title,
                'artist': entry.wish.artist or '',
                'provider': entry.wish.provider,
                'image_url': entry.wish.image_url or '',
                'wish_count': entry.wish.wish_count
            }
        })
    
    emit_music_update('queue_updated', {
        'action': 'removed',
        'queue': queue_data
    })
    
    return jsonify({'success': True})


@music_bp.route('/queue/move', methods=['POST'])
@login_required
@check_module_access('module_music')
def move_queue_item():
    """Verschiebt ein Element in der Warteschlange."""
    queue_id = request.json.get('queue_id')
    new_position = request.json.get('position')
    
    if not queue_id or new_position is None:
        return jsonify({'error': translate('music.flash.queue_id_required')}), 400
    
    queue_entry = MusicQueue.query.get_or_404(queue_id)
    old_position = queue_entry.position
    
    if new_position == old_position:
        return jsonify({'success': True})
    
    # Verschiebe andere Einträge
    if new_position < old_position:
        # Nach oben verschoben
        entries = MusicQueue.query.filter(
            MusicQueue.position >= new_position,
            MusicQueue.position < old_position,
            MusicQueue.status == 'pending',
            MusicQueue.id != queue_id
        ).all()
        for entry in entries:
            entry.position += 1
    else:
        # Nach unten verschoben
        entries = MusicQueue.query.filter(
            MusicQueue.position > old_position,
            MusicQueue.position <= new_position,
            MusicQueue.status == 'pending',
            MusicQueue.id != queue_id
        ).all()
        for entry in entries:
            entry.position -= 1
    
    queue_entry.position = new_position
    db.session.commit()
    
    # Lade vollständige Queue-Daten für SocketIO-Update (mit joinedload)
    queue = MusicQueue.query.options(joinedload(MusicQueue.wish)).filter_by(
        status='pending'
    ).order_by(MusicQueue.position.asc()).all()
    queue_data = []
    for entry in queue:
        queue_data.append({
            'id': entry.id,
            'position': entry.position,
            'wish': {
                'id': entry.wish.id,
                'title': entry.wish.title,
                'artist': entry.wish.artist or '',
                'provider': entry.wish.provider,
                'image_url': entry.wish.image_url or '',
                'wish_count': entry.wish.wish_count
            }
        })
    
    # WebSocket-Update senden mit vollständigen Queue-Daten (nur an Clients im Musikmodul)
    emit_music_update('queue_updated', {
        'action': 'moved',
        'queue': queue_data
    })
    
    return jsonify({'success': True})


@music_bp.route('/queue/remove', methods=['POST'])
@login_required
@check_module_access('module_music')
def remove_from_queue():
    """Entfernt ein Lied aus der Warteschlange und setzt Status auf 'played'."""
    queue_id = request.json.get('queue_id')
    
    queue_entry = MusicQueue.query.get_or_404(queue_id)
    wish = queue_entry.wish
    
    # Setze Wish-Status auf 'played' (nicht löschen)
    wish.status = 'played'
    wish.updated_at = datetime.utcnow()
    
    # Setze played_at Datum im Queue-Eintrag, falls vorhanden
    if hasattr(queue_entry, 'played_at'):
        queue_entry.played_at = datetime.utcnow()
    
    # Entferne aus Queue
    db.session.delete(queue_entry)
    
    # Aktualisiere Positionen
    entries = MusicQueue.query.filter(
        MusicQueue.position > queue_entry.position,
        MusicQueue.status == 'pending'
    ).all()
    for entry in entries:
        entry.position -= 1
    
    db.session.commit()
    
    # Lade vollständige Queue-Daten für SocketIO-Update (mit joinedload)
    queue = MusicQueue.query.options(joinedload(MusicQueue.wish)).filter_by(
        status='pending'
    ).order_by(MusicQueue.position.asc()).all()
    queue_data = []
    for entry in queue:
        queue_data.append({
            'id': entry.id,
            'position': entry.position,
            'wish': {
                'id': entry.wish.id,
                'title': entry.wish.title,
                'artist': entry.wish.artist or '',
                'provider': entry.wish.provider,
                'image_url': entry.wish.image_url or '',
                'wish_count': entry.wish.wish_count
            }
        })
    
    # WebSocket-Update senden mit vollständigen Queue-Daten (nur an Clients im Musikmodul)
    emit_music_update('queue_updated', {
        'action': 'removed',
        'queue': queue_data
    })
    
    # SSE-Update senden (Status geändert zu 'played')
    emit_music_update('wish_updated', {
        'wish': {
            'id': wish.id,
            'title': wish.title,
            'artist': wish.artist or '',
            'provider': wish.provider,
            'image_url': wish.image_url or '',
            'wish_count': wish.wish_count,
            'status': wish.status,
            'updated_at': wish.updated_at.isoformat() if wish.updated_at else None
        }
    })
    
    # Sende spezielles Event für "Played"-Updates (optimiertes Count)
    played_count = db.session.query(func.count(MusicWish.id)).filter_by(status='played').scalar() or 0
    emit_music_update('played_updated', {
        'wish': {
            'id': wish.id,
            'title': wish.title,
            'artist': wish.artist or '',
            'provider': wish.provider,
            'image_url': wish.image_url or '',
            'wish_count': wish.wish_count,
            'updated_at': wish.updated_at.isoformat() if wish.updated_at else None
        },
        'count': played_count
    })
    
    return jsonify({'success': True})


@music_bp.route('/queue/clear', methods=['POST'])
@login_required
@check_module_access('module_music')
def clear_queue():
    """Löscht die gesamte Warteschlange und setzt Status der Wünsche auf 'played'."""
    queue_entries = MusicQueue.query.filter_by(status='pending').all()
    
    for entry in queue_entries:
        entry.wish.status = 'played'
        entry.wish.updated_at = datetime.utcnow()
        if hasattr(entry, 'played_at'):
            entry.played_at = datetime.utcnow()
        db.session.delete(entry)
    
    db.session.commit()
    
    # WebSocket-Update senden mit leerer Queue (nur an Clients im Musikmodul)
    emit_music_update('queue_updated', {
        'action': 'cleared',
        'queue': []
    })
    
    return jsonify({'success': True})


@music_bp.route('/wishlist/clear', methods=['POST'])
@login_required
@check_module_access('module_music')
def clear_wishlist():
    """Löscht nur Wünsche mit Status 'pending'. Bereits gespielte Lieder bleiben erhalten."""
    wishes = MusicWish.query.filter_by(status='pending').all()
    
    for wish in wishes:
        db.session.delete(wish)
    
    db.session.commit()
    
    # WebSocket-Update senden (nur an Clients im Musikmodul)
    # Sende explizite Anweisung zum Neuladen der Wishlist
    emit_music_update('wishlist_cleared', {
        'force_reload': True,
        'wish_count': 0
    })
    
    return jsonify({'success': True})


@music_bp.route('/reset-all', methods=['POST'])
@login_required
@check_module_access('module_music')
def reset_all():
    """Löscht ALLES: Wunschliste, Warteschlange und bereits gespielte Lieder."""
    # Lösche alle Queue-Einträge
    queue_entries = MusicQueue.query.all()
    for entry in queue_entries:
        db.session.delete(entry)
    
    # Lösche alle Wünsche (unabhängig vom Status)
    wishes = MusicWish.query.all()
    for wish in wishes:
        db.session.delete(wish)
    
    db.session.commit()
    
    # WebSocket-Updates senden (nur an Clients im Musikmodul)
    emit_music_update('queue_updated', {
        'action': 'cleared',
        'queue': []
    })
    emit_music_update('wishlist_cleared', {
        'force_reload': True,
        'wish_count': 0
    })
    
    return jsonify({'success': True})


# OAuth-Routen
@music_bp.route('/connect/spotify')
@login_required
@check_module_access('module_music')
def connect_spotify():
    """Startet Spotify OAuth Flow."""
    try:
        auth_url = get_spotify_oauth_url()
        return redirect(auth_url)
    except Exception as e:
        flash(translate('music.flash.connect_error', provider='Spotify', error=str(e)), 'danger')
        return redirect(url_for('music.index'))


@music_bp.route('/connect/youtube')
@login_required
@check_module_access('module_music')
def connect_youtube():
    """Startet YouTube OAuth Flow."""
    try:
        auth_url = get_youtube_oauth_url()
        return redirect(auth_url)
    except Exception as e:
        flash(translate('music.flash.connect_error', provider='YouTube', error=str(e)), 'danger')
        return redirect(url_for('music.index'))


@music_bp.route('/callback/spotify')
@login_required
def spotify_callback():
    """Spotify OAuth Callback."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        flash(translate('music.flash.oauth_error', provider='Spotify', error=error), 'danger')
        return redirect(url_for('music.index'))
    
    if not code:
        flash(translate('music.flash.no_auth_code'), 'danger')
        return redirect(url_for('music.index'))
    
    try:
        handle_spotify_callback(code, state)
        flash(translate('music.flash.spotify_connected'), 'success')
    except Exception as e:
        flash(translate('music.flash.connect_error', provider='Spotify', error=str(e)), 'danger')
    
    return redirect(url_for('music.index'))


@music_bp.route('/callback/youtube')
@login_required
def youtube_callback():
    """YouTube OAuth Callback."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        flash(translate('music.flash.oauth_error', provider='YouTube', error=error), 'danger')
        return redirect(url_for('music.index'))
    
    if not code:
        flash(translate('music.flash.no_auth_code'), 'danger')
        return redirect(url_for('music.index'))
    
    try:
        handle_youtube_callback(code, state)
        flash(translate('music.flash.youtube_connected'), 'success')
    except Exception as e:
        flash(translate('music.flash.connect_error', provider='YouTube', error=str(e)), 'danger')
    
    return redirect(url_for('music.index'))


@music_bp.route('/disconnect/<provider>')
@login_required
@check_module_access('module_music')
def disconnect(provider):
    """Trennt die Verbindung zu einem Provider."""
    if provider not in ['spotify', 'youtube']:
        return jsonify({'error': translate('music.flash.invalid_provider')}), 400
    
    try:
        disconnect_provider(current_user.id, provider)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@music_bp.route('/public-url')
@login_required
@check_module_access('module_music')
def public_url_page():
    """Zeigt eine Seite mit QR-Code und Link für die öffentliche Wunschliste."""
    # Hole Portallogo (mit Cache)
    portal_logo_filename = get_cached_system_setting('portal_logo') or None
    
    # Generiere Public URL
    public_url = url_for('music.public_wishlist', _external=True)
    
    return render_template('music/public_url.html',
                         portal_logo_filename=portal_logo_filename,
                         public_url=public_url)


@music_bp.route('/api/public-link')
@login_required
@check_module_access('module_music')
def get_public_link():
    """Gibt den öffentlichen Link zur Wunschliste zurück."""
    link = url_for('music.public_wishlist', _external=True)
    return jsonify({'link': link})


@music_bp.route('/api/qr-code')
@login_required
@check_module_access('module_music')
def get_qr_code():
    """Gibt einen QR-Code für die Public URL zurück."""
    from app.utils.qr_code import generate_qr_code_bytes
    from flask import Response
    
    url = request.args.get('url')
    if not url:
        url = url_for('music.public_wishlist', _external=True)
    
    qr_bytes = generate_qr_code_bytes(url, box_size=10, border=4)
    return Response(qr_bytes, mimetype='image/png')


@music_bp.route('/api/public-link/pdf')
@login_required
@check_module_access('module_music')
def download_public_link_pdf():
    """Generiert und gibt eine A5-PDF mit QR-Code für die Public URL zurück."""
    from app.utils.pdf_generator import generate_music_wish_pdf
    from flask import Response
    
    public_url = url_for('music.public_wishlist', _external=True)
    pdf_bytes = generate_music_wish_pdf(public_url)
    
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': 'attachment; filename=musikwuensche.pdf'
        }
    )


@music_bp.route('/api/wishlist/count')
@login_required
@check_module_access('module_music')
def api_wishlist_count():
    """Gibt die Anzahl der Wünsche zurück."""
    count = db.session.query(func.count(MusicWish.id)).filter_by(status='pending').scalar() or 0
    return jsonify({'count': count})


@music_bp.route('/api/queue/count')
@login_required
@check_module_access('module_music')
def api_queue_count():
    """Gibt die Anzahl der Queue-Einträge zurück."""
    count = db.session.query(func.count(MusicQueue.id)).filter_by(status='pending').scalar() or 0
    return jsonify({'count': count})


@music_bp.route('/api/queue/list')
@login_required
@check_module_access('module_music')
def api_queue_list():
    """Gibt die aktuelle Queue als JSON zurück."""
    queue = MusicQueue.query.options(joinedload(MusicQueue.wish)).filter_by(
        status='pending'
    ).order_by(MusicQueue.position.asc()).all()
    
    queue_data = []
    for entry in queue:
        queue_data.append({
            'id': entry.id,
            'position': entry.position,
            'wish': {
                'id': entry.wish.id,
                'title': entry.wish.title,
                'artist': entry.wish.artist,
                'provider': entry.wish.provider,
                'image_url': entry.wish.image_url,
                'wish_count': entry.wish.wish_count
            }
        })
    
    return jsonify({'queue': queue_data})


@music_bp.route('/api/wishlist/list')
@login_required
@check_module_access('module_music')
def api_wishlist_list():
    """Gibt paginierte Wunschliste als JSON zurück."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    # Begrenze per_page auf maximal 50 (Performance-Optimierung)
    per_page = min(per_page, 50)
    
    pagination = MusicWish.query.filter_by(status='pending').order_by(
        MusicWish.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    wishes_data = []
    for wish in pagination.items:
        wishes_data.append({
            'id': wish.id,
            'title': wish.title,
            'artist': wish.artist or '',
            'provider': wish.provider,
            'image_url': wish.image_url or '',
            'wish_count': wish.wish_count,
            'created_at': wish.created_at.isoformat() if wish.created_at else None
        })
    
    return jsonify({
        'wishes': wishes_data,
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })


@music_bp.route('/api/played/count')
@login_required
@check_module_access('module_music')
def api_played_count():
    """Gibt die Anzahl der bereits gespielten Lieder zurück."""
    count = db.session.query(func.count(MusicWish.id)).filter_by(status='played').scalar() or 0
    return jsonify({'count': count})


@music_bp.route('/api/played/list')
@login_required
@check_module_access('module_music')
def api_played_list():
    """Gibt paginierte Liste der bereits gespielten Lieder als JSON zurück."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    # Begrenze per_page auf maximal 50 (Performance-Optimierung)
    per_page = min(per_page, 50)
    
    pagination = MusicWish.query.filter_by(status='played').order_by(
        MusicWish.updated_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    played_data = []
    for wish in pagination.items:
        played_data.append({
            'id': wish.id,
            'title': wish.title,
            'artist': wish.artist or '',
            'provider': wish.provider,
            'image_url': wish.image_url or '',
            'wish_count': wish.wish_count,
            'updated_at': wish.updated_at.isoformat() if wish.updated_at else None
        })
    
    return jsonify({
        'played': played_data,
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })


# SSE-basierte Live-Updates (siehe app/blueprints/sse.py)
# Socket.IO wurde durch Server-Sent Events ersetzt für bessere Multi-Worker-Kompatibilität

