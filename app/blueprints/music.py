from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db, socketio
from app.models.music import MusicProviderToken, MusicWish, MusicQueue, MusicSettings
from app.utils.music_oauth import (
    get_spotify_oauth_url, get_youtube_oauth_url,
    handle_spotify_callback, handle_youtube_callback,
    is_provider_connected, disconnect_provider
)
from app.utils.music_api import search_music, get_track
from app.utils.access_control import check_module_access
import secrets

music_bp = Blueprint('music', __name__, url_prefix='/music')


# Öffentliche Route (kein Login erforderlich)
@music_bp.route('/wishlist', methods=['GET', 'POST'])
def public_wishlist():
    """Öffentliche Wunschliste - Suche und Hinzufügen von Liedern."""
    
    # Für die Suche benötigen wir einen verbundenen Account
    # Wir verwenden den ersten verfügbaren Admin-Account
    admin_user = None
    spotify_connected = False
    youtube_connected = False
    
    if current_user.is_authenticated:
        admin_user = current_user
        spotify_connected = is_provider_connected(current_user.id, 'spotify')
        youtube_connected = is_provider_connected(current_user.id, 'youtube')
    else:
        # Suche nach einem Admin mit verbundenem Account
        from app.models.user import User
        admins = User.query.filter_by(is_admin=True).all()
        for admin in admins:
            if is_provider_connected(admin.id, 'spotify') or is_provider_connected(admin.id, 'youtube'):
                admin_user = admin
                spotify_connected = is_provider_connected(admin.id, 'spotify')
                youtube_connected = is_provider_connected(admin.id, 'youtube')
                break
    
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
                         admin_user=admin_user,
                         spotify_connected=spotify_connected,
                         youtube_connected=youtube_connected)


@music_bp.route('/wishlist/search', methods=['POST'])
def public_search():
    """Öffentliche Suche nach Liedern."""
    
    provider = request.json.get('provider', '').strip()
    query = request.json.get('query', '').strip()
    
    if not provider or not query:
        return jsonify({'error': 'Provider und Suchbegriff erforderlich'}), 400
    
    # Suche nach Admin mit verbundenem Account
    admin_user = None
    if current_user.is_authenticated and (is_provider_connected(current_user.id, provider) or current_user.is_admin):
        admin_user = current_user
    else:
        from app.models.user import User
        admins = User.query.filter_by(is_admin=True).all()
        for admin in admins:
            if is_provider_connected(admin.id, provider):
                admin_user = admin
                break
    
    if not admin_user:
        return jsonify({'error': 'Kein verbundener Account für diesen Provider gefunden'}), 400
    
    try:
        results = search_music(admin_user.id, provider, query, limit=10)
        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


@music_bp.route('/api/public-link')
@login_required
@check_module_access('module_music')
def get_public_link():
    """Gibt den öffentlichen Link zur Wunschliste zurück."""
    link = url_for('music.public_wishlist', _external=True)
    return jsonify({'link': link})

