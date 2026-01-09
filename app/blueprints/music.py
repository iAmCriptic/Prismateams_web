from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db, socketio
from app.models.music import MusicProviderToken, MusicWish, MusicQueue, MusicSettings
from app.utils.music_oauth import (
    get_spotify_oauth_url, get_youtube_oauth_url,
    handle_spotify_callback, handle_youtube_callback,
    is_provider_connected, disconnect_provider
)
from app.utils.music_api import search_music, get_track, search_music_multi_provider
from app.utils.access_control import check_module_access
from datetime import datetime
import secrets
import logging

logger = logging.getLogger(__name__)

music_bp = Blueprint('music', __name__, url_prefix='/music')


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
            return jsonify({'error': 'Fehlende Daten'}), 400
        
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
            
            # WebSocket-Update senden
            socketio.emit('music:wish_added', {
                'wish_id': existing.id,
                'title': existing.title,
                'artist': existing.artist,
                'provider': existing.provider,
                'wish_count': existing.wish_count
            }, namespace='/')
            
            return jsonify({'success': True, 'message': f'Wunschzähler erhöht ({existing.wish_count}x gewünscht)'})
        
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
        
        # WebSocket-Update senden
        socketio.emit('music:wish_added', {
            'wish_id': wish.id,
            'title': wish.title,
            'artist': wish.artist,
            'provider': wish.provider,
            'wish_count': wish.wish_count
        }, namespace='/')
        
        return jsonify({'success': True, 'message': 'Lied zur Wunschliste hinzugefügt'})
    
    # GET: Zeige Suchseite
    return render_template('music/public_wishlist.html', 
                         has_providers=has_providers,
                         enabled_providers=enabled_providers)


@music_bp.route('/wishlist/search', methods=['POST'])
def public_search():
    """Öffentliche Suche nach Liedern über alle aktivierten Provider."""
    
    query = request.json.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'Suchbegriff erforderlich'}), 400
    
    try:
        # Verwende Multi-Provider-Suche (automatisch über alle aktivierten Provider)
        # Übergebe user_id wenn Benutzer eingeloggt ist (für Spotify OAuth)
        user_id = current_user.id if current_user.is_authenticated else None
        results = search_music_multi_provider(query, limit=10, min_results=5, user_id=user_id)
        return jsonify({'results': results})
    except Exception as e:
        logger.error(f"Fehler bei Multi-Provider-Suche: {e}", exc_info=True)
        return jsonify({'error': f'Fehler bei der Suche: {str(e)}'}), 500


# Admin-Routen (Login erforderlich)
@music_bp.route('/')
@login_required
@check_module_access('module_music')
def index():
    """Hauptseite für Musikmodul - Warteschlangen-Verwaltung."""
    # Hole Wunschliste
    wishes = MusicWish.query.filter_by(status='pending').order_by(MusicWish.created_at.desc()).all()
    
    # Hole Warteschlange
    queue = MusicQueue.query.filter_by(status='pending').order_by(MusicQueue.position.asc()).all()
    
    # Hole aktuell spielendes Lied
    playing = MusicQueue.query.filter_by(status='playing').first()
    
    # Hole bereits gespielte Lieder
    played_wishes = MusicWish.query.filter_by(status='played').order_by(MusicWish.updated_at.desc()).all()
    
    return render_template('music/index.html',
                         wishes=wishes,
                         queue=queue,
                         playing=playing,
                         played_wishes=played_wishes)


@music_bp.route('/wishlist/add-to-queue', methods=['POST'])
@login_required
@check_module_access('module_music')
def add_to_queue():
    """Fügt ein Lied von der Wunschliste zur Warteschlange hinzu."""
    wish_id = request.json.get('wish_id')
    position = request.json.get('position', 'end')  # 'next', 'last', 'end'
    
    wish = MusicWish.query.get_or_404(wish_id)
    
    if wish.status != 'pending':
        return jsonify({'error': 'Lied ist bereits verarbeitet'}), 400
    
    # Prüfe ob bereits in Queue
    existing_queue = MusicQueue.query.filter_by(wish_id=wish_id).first()
    if existing_queue:
        return jsonify({'error': 'Lied ist bereits in der Warteschlange'}), 400
    
    # Bestimme Position
    if position == 'next':
        # Als nächstes Lied
        new_position = 1
        # Verschiebe alle anderen nach hinten
        existing = MusicQueue.query.filter_by(status='pending').order_by(MusicQueue.position.asc()).all()
        for entry in existing:
            entry.position += 1
    elif position == 'last':
        # Als letztes Lied von Wunschliedern
        # Finde die höchste Position
        max_pos = db.session.query(db.func.max(MusicQueue.position)).filter_by(status='pending').scalar() or 0
        new_position = max_pos + 1
    else:  # 'end'
        # Am Ende
        max_pos = db.session.query(db.func.max(MusicQueue.position)).filter_by(status='pending').scalar() or 0
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
    
    # WebSocket-Update senden
    socketio.emit('music:queue_updated', {
        'action': 'added',
        'queue_id': queue_entry.id,
        'wish_id': wish_id
    }, namespace='/')
    
    return jsonify({'success': True})


@music_bp.route('/queue/move', methods=['POST'])
@login_required
@check_module_access('module_music')
def move_queue_item():
    """Verschiebt ein Element in der Warteschlange."""
    queue_id = request.json.get('queue_id')
    new_position = request.json.get('position')
    
    if not queue_id or new_position is None:
        return jsonify({'error': 'queue_id und position erforderlich'}), 400
    
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
    
    # WebSocket-Update senden
    socketio.emit('music:queue_updated', {
        'action': 'moved',
        'queue_id': queue_id,
        'new_position': new_position
    }, namespace='/')
    
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
    
    # WebSocket-Update senden
    socketio.emit('music:queue_updated', {
        'action': 'removed',
        'queue_id': queue_id
    }, namespace='/')
    
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
    
    # WebSocket-Update senden
    socketio.emit('music:queue_updated', {
        'action': 'cleared'
    }, namespace='/')
    
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
    
    # WebSocket-Update senden
    socketio.emit('music:wishlist_cleared', {}, namespace='/')
    
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
    
    # WebSocket-Updates senden
    socketio.emit('music:queue_updated', {
        'action': 'cleared'
    }, namespace='/')
    socketio.emit('music:wishlist_cleared', {}, namespace='/')
    
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
        flash(f'Fehler beim Verbinden mit Spotify: {str(e)}', 'danger')
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
        flash(f'Fehler beim Verbinden mit YouTube: {str(e)}', 'danger')
        return redirect(url_for('music.index'))


@music_bp.route('/callback/spotify')
@login_required
def spotify_callback():
    """Spotify OAuth Callback."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        flash(f'Spotify OAuth Fehler: {error}', 'danger')
        return redirect(url_for('music.index'))
    
    if not code:
        flash('Kein Auth-Code erhalten', 'danger')
        return redirect(url_for('music.index'))
    
    try:
        handle_spotify_callback(code, state)
        flash('Spotify erfolgreich verbunden!', 'success')
    except Exception as e:
        flash(f'Fehler beim Verbinden: {str(e)}', 'danger')
    
    return redirect(url_for('music.index'))


@music_bp.route('/callback/youtube')
@login_required
def youtube_callback():
    """YouTube OAuth Callback."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        flash(f'YouTube OAuth Fehler: {error}', 'danger')
        return redirect(url_for('music.index'))
    
    if not code:
        flash('Kein Auth-Code erhalten', 'danger')
        return redirect(url_for('music.index'))
    
    try:
        handle_youtube_callback(code, state)
        flash('YouTube Music erfolgreich verbunden!', 'success')
    except Exception as e:
        flash(f'Fehler beim Verbinden: {str(e)}', 'danger')
    
    return redirect(url_for('music.index'))


@music_bp.route('/disconnect/<provider>')
@login_required
@check_module_access('module_music')
def disconnect(provider):
    """Trennt die Verbindung zu einem Provider."""
    if provider not in ['spotify', 'youtube']:
        return jsonify({'error': 'Ungültiger Provider'}), 400
    
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
    from app.models.settings import SystemSettings
    
    # Hole Portallogo
    portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
    portal_logo_filename = portal_logo_setting.value if portal_logo_setting and portal_logo_setting.value else None
    
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
    count = MusicWish.query.filter_by(status='pending').count()
    return jsonify({'count': count})


@music_bp.route('/api/queue/count')
@login_required
@check_module_access('module_music')
def api_queue_count():
    """Gibt die Anzahl der Queue-Einträge zurück."""
    count = MusicQueue.query.filter_by(status='pending').count()
    return jsonify({'count': count})


@music_bp.route('/api/queue/list')
@login_required
@check_module_access('module_music')
def api_queue_list():
    """Gibt die aktuelle Queue als JSON zurück."""
    queue = MusicQueue.query.filter_by(status='pending').order_by(MusicQueue.position.asc()).all()
    
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

