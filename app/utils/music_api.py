import requests
from requests.exceptions import Timeout, RequestException, ConnectionError
from app import db
from app.models.music import MusicProviderToken
from app.utils.music_oauth import decrypt_token, refresh_token_if_needed
import os
import time
import logging

logger = logging.getLogger(__name__)

# Timeout für alle Musik-API-Aufrufe (5 Sekunden)
MUSIC_API_TIMEOUT = 5

# Anzahl der Retry-Versuche
MAX_RETRIES = 2

# Wartezeit zwischen Retries (in Sekunden)
RETRY_DELAY = 0.5


class SpotifyAPI:
    """Spotify API Client."""
    
    BASE_URL = 'https://api.spotify.com/v1'
    
    def __init__(self, access_token):
        self.access_token = access_token
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
    
    def search(self, query, limit=10):
        """Sucht nach Liedern."""
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{self.BASE_URL}/search',
                    headers=self.headers,
                    params={
                        'q': query,
                        'type': 'track',
                        'limit': limit
                    },
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                results = []
                for track in data.get('tracks', {}).get('items', []):
                    results.append({
                        'id': track['id'],
                        'title': track['name'],
                        'artist': ', '.join([artist['name'] for artist in track['artists']]),
                        'album': track['album']['name'],
                        'image_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                        'url': track['external_urls']['spotify'],
                        'duration_ms': track['duration_ms'],
                        'provider': 'spotify'
                    })
                return results
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Spotify API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Spotify API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"Spotify API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"Spotify API Fehler: {str(e)}")
        
        # Falls alle Retries fehlgeschlagen sind
        raise Exception(f"Spotify API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")
    
    def get_track(self, track_id):
        """Holt Details zu einem Track."""
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{self.BASE_URL}/tracks/{track_id}',
                    headers=self.headers,
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                track = response.json()
                
                return {
                    'id': track['id'],
                    'title': track['name'],
                    'artist': ', '.join([artist['name'] for artist in track['artists']]),
                    'album': track['album']['name'],
                    'image_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                    'url': track['external_urls']['spotify'],
                    'duration_ms': track['duration_ms'],
                    'provider': 'spotify'
                }
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Spotify API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Spotify API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"Spotify API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"Spotify API Fehler: {str(e)}")
        
        raise Exception(f"Spotify API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")


class YouTubeMusicAPI:
    """YouTube Music API Client (verwendet YouTube Data API v3 mit API-Key oder OAuth)."""
    
    BASE_URL = 'https://www.googleapis.com/youtube/v3'
    
    def __init__(self, api_key=None, access_token=None):
        """
        Initialisiert den YouTube API Client.
        
        Args:
            api_key: API-Key für öffentliche Suchen (vereinfacht, kein OAuth)
            access_token: OAuth Access Token (optional, für Benutzer-spezifische Daten)
        """
        self.api_key = api_key
        self.access_token = access_token
        self.headers = {
            'Content-Type': 'application/json'
        }
        if access_token:
            self.headers['Authorization'] = f'Bearer {access_token}'
    
    def search(self, query, limit=10):
        """Sucht nach Liedern."""
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Suche nach Musik-Videos
                params = {
                    'q': f'{query} music song',
                    'type': 'video',
                    'videoCategoryId': '10',  # Music category
                    'maxResults': limit,
                    'part': 'snippet'
                }
                
                # Verwende API-Key wenn verfügbar, sonst OAuth Token
                if self.api_key:
                    params['key'] = self.api_key
                
                response = requests.get(
                    f'{self.BASE_URL}/search',
                    headers=self.headers,
                    params=params,
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                results = []
                for item in data.get('items', []):
                    # Filtere nach "official audio" oder "official music video" für bessere Ergebnisse
                    title = item['snippet']['title']
                    description = item['snippet'].get('description', '').lower()
                    
                    # Priorisiere offizielle Audio/Music Videos
                    if 'official audio' in description.lower() or 'official music video' in description.lower() or 'music' in title.lower():
                        results.append({
                            'id': item['id']['videoId'],
                            'title': title,
                            'artist': item['snippet'].get('channelTitle', 'Unbekannt'),
                            'album': None,
                            'image_url': item['snippet']['thumbnails']['high']['url'] if 'high' in item['snippet']['thumbnails'] else item['snippet']['thumbnails']['default']['url'],
                            'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                            'duration_ms': None,
                            'provider': 'youtube'
                        })
                
                # Falls keine Ergebnisse, nimm alle
                if not results:
                    for item in data.get('items', []):
                        results.append({
                            'id': item['id']['videoId'],
                            'title': item['snippet']['title'],
                            'artist': item['snippet'].get('channelTitle', 'Unbekannt'),
                            'album': None,
                            'image_url': item['snippet']['thumbnails']['high']['url'] if 'high' in item['snippet']['thumbnails'] else item['snippet']['thumbnails']['default']['url'],
                            'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                            'duration_ms': None,
                            'provider': 'youtube'
                        })
                
                return results[:limit]
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"YouTube API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"YouTube API Fehler: {str(e)}")
        
        raise Exception(f"YouTube API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")
    
    def get_track(self, track_id):
        """Holt Details zu einem Track."""
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{self.BASE_URL}/videos',
                    headers=self.headers,
                    params={
                        'id': track_id,
                        'part': 'snippet,contentDetails'
                    },
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                if not data.get('items'):
                    raise Exception("Video nicht gefunden")
                
                item = data['items'][0]
                
                return {
                    'id': item['id'],
                    'title': item['snippet']['title'],
                    'artist': item['snippet'].get('channelTitle', 'Unbekannt'),
                    'album': None,
                    'image_url': item['snippet']['thumbnails']['high']['url'] if 'high' in item['snippet']['thumbnails'] else item['snippet']['thumbnails']['default']['url'],
                    'url': f"https://www.youtube.com/watch?v={item['id']}",
                    'duration_ms': None,
                    'provider': 'youtube'
                }
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"YouTube API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"YouTube API Fehler: {str(e)}")
        
        raise Exception(f"YouTube API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")
    
    def get_playlists(self):
        """Holt Playlists des Benutzers."""
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{self.BASE_URL}/playlists',
                    headers=self.headers,
                    params={
                        'part': 'snippet,contentDetails',
                        'mine': 'true',
                        'maxResults': 50
                    },
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                playlists = []
                for item in data.get('items', []):
                    playlists.append({
                        'id': item['id'],
                        'name': item['snippet']['title'],
                        'description': item['snippet'].get('description', ''),
                        'image_url': item['snippet']['thumbnails']['high']['url'] if 'high' in item['snippet']['thumbnails'] else item['snippet']['thumbnails']['default']['url'],
                        'track_count': item['contentDetails'].get('itemCount', 0)
                    })
                return playlists
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"YouTube API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"YouTube API Fehler: {str(e)}")
        
        raise Exception(f"YouTube API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")


class MusicBrainzAPI:
    """MusicBrainz API Client (öffentliche API, keine Authentifizierung)."""
    
    BASE_URL = 'https://musicbrainz.org/ws/2'
    
    def __init__(self):
        # User-Agent ist erforderlich für MusicBrainz API
        self.headers = {
            'User-Agent': 'Prismateams/1.0 (https://github.com/iAmCriptic/Prismateams_web)',
            'Accept': 'application/json'
        }
        # Rate Limiting: 1 Request/Sekunde
        self._last_request_time = 0
    
    def _rate_limit(self):
        """Stellt sicher, dass nur 1 Request pro Sekunde gemacht wird."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < 1.0:
            time.sleep(1.0 - time_since_last)
        self._last_request_time = time.time()
    
    def search(self, query, limit=10):
        """Sucht nach Liedern. Unterstützt erweiterte Suche (Titel, Künstler, Album)."""
        last_exception = None
        
        # Rate Limiting beachten
        self._rate_limit()
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                # MusicBrainz unterstützt erweiterte Suche
                # Beispiel: "sido straßenjunge" wird als allgemeine Suche interpretiert
                # Wir können auch spezifische Felder verwenden: artist:sido AND recording:straßenjunge
                search_query = query
                
                response = requests.get(
                    f'{self.BASE_URL}/recording',
                    headers=self.headers,
                    params={
                        'query': search_query,
                        'limit': limit,
                        'fmt': 'json'
                    },
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                results = []
                for recording in data.get('recordings', []):
                    # Extrahiere Künstler
                    artists = []
                    if 'artist-credit' in recording:
                        for artist_credit in recording['artist-credit']:
                            if 'artist' in artist_credit:
                                artists.append(artist_credit['artist']['name'])
                    
                    artist_name = ', '.join(artists) if artists else 'Unbekannter Künstler'
                    
                    # Extrahiere Album/Release
                    album_name = None
                    if 'releases' in recording and recording['releases']:
                        album_name = recording['releases'][0].get('title', None)
                    
                    # Extrahiere Cover-Art (MusicBrainz hat keine direkten Cover-URLs)
                    # Wir können Cover Art Archive verwenden, aber das ist optional
                    image_url = None
                    if 'releases' in recording and recording['releases']:
                        release_id = recording['releases'][0].get('id')
                        if release_id:
                            # Versuche Cover Art Archive URL zu generieren
                            image_url = f"https://coverartarchive.org/release/{release_id}/front"
                    
                    # MusicBrainz ID als track_id verwenden
                    track_id = recording.get('id')
                    
                    results.append({
                        'id': track_id,
                        'title': recording.get('title', 'Unbekannt'),
                        'artist': artist_name,
                        'album': album_name,
                        'image_url': image_url,  # Kann None sein, wird beim Laden geprüft
                        'url': f"https://musicbrainz.org/recording/{track_id}",
                        'duration_ms': recording.get('length') if recording.get('length') else None,
                        'provider': 'musicbrainz'
                    })
                
                return results
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"MusicBrainz API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"MusicBrainz API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"MusicBrainz API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"MusicBrainz API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"MusicBrainz API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"MusicBrainz API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"MusicBrainz API Fehler: {str(e)}")
        
        raise Exception(f"MusicBrainz API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")
    
    def get_track(self, track_id):
        """Holt Details zu einem Track."""
        self._rate_limit()
        
        last_exception = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{self.BASE_URL}/recording/{track_id}',
                    headers=self.headers,
                    params={
                        'inc': 'artists+releases',
                        'fmt': 'json'
                    },
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                recording = response.json()
                
                # Extrahiere Künstler
                artists = []
                if 'artist-credit' in recording:
                    for artist_credit in recording['artist-credit']:
                        if 'artist' in artist_credit:
                            artists.append(artist_credit['artist']['name'])
                
                artist_name = ', '.join(artists) if artists else 'Unbekannter Künstler'
                
                # Extrahiere Album
                album_name = None
                if 'releases' in recording and recording['releases']:
                    album_name = recording['releases'][0].get('title', None)
                
                return {
                    'id': recording.get('id'),
                    'title': recording.get('title', 'Unbekannt'),
                    'artist': artist_name,
                    'album': album_name,
                    'image_url': None,  # MusicBrainz hat keine direkten Cover-URLs
                    'url': f"https://musicbrainz.org/recording/{recording.get('id')}",
                    'duration_ms': recording.get('length') if recording.get('length') else None,
                    'provider': 'musicbrainz'
                }
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"MusicBrainz API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"MusicBrainz API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"MusicBrainz API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"MusicBrainz API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"MusicBrainz API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"MusicBrainz API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"MusicBrainz API Fehler: {str(e)}")
        
        raise Exception(f"MusicBrainz API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")


def get_api_client(user_id=None, provider=None, use_client_credentials=False):
    """
    Holt einen API-Client für den angegebenen Provider.
    
    Args:
        user_id: Benutzer-ID (erforderlich für Spotify OAuth, optional für YouTube API-Key)
        provider: Provider-Name ('spotify', 'youtube', 'musicbrainz')
        use_client_credentials: Wenn True, verwendet API-Key für YouTube (Spotify verwendet immer OAuth)
    """
    from app.utils.music_oauth import get_music_setting
    
    if provider == 'spotify':
        # Spotify verwendet immer OAuth (Benutzer-Login)
        if not user_id:
            raise Exception("user_id erforderlich für Spotify-Verbindung. Bitte mit Spotify-Konto anmelden.")
        token_obj = MusicProviderToken.query.filter_by(user_id=user_id, provider=provider).first()
        if not token_obj:
            raise Exception(f"Kein Spotify-Token gefunden. Bitte zuerst mit Spotify-Konto verbinden.")
        refresh_token_if_needed(token_obj)
        access_token = decrypt_token(token_obj.access_token)
        return SpotifyAPI(access_token)
    
    elif provider == 'youtube':
        if use_client_credentials:
            # Verwende API-Key (vereinfacht, kein OAuth)
            api_key = get_music_setting('youtube_api_key')
            if not api_key:
                raise Exception("YouTube API-Key nicht konfiguriert. Bitte in den Einstellungen konfigurieren.")
            return YouTubeMusicAPI(api_key=api_key)
        else:
            # Verwende OAuth Token (für Benutzer-spezifische Daten)
            if not user_id:
                raise Exception("user_id erforderlich für OAuth-basierte YouTube-Verbindung")
            token_obj = MusicProviderToken.query.filter_by(user_id=user_id, provider=provider).first()
            if not token_obj:
                raise Exception(f"Kein Token für {provider} gefunden")
            refresh_token_if_needed(token_obj)
            access_token = decrypt_token(token_obj.access_token)
            return YouTubeMusicAPI(access_token=access_token)
    
    elif provider == 'musicbrainz':
        # MusicBrainz benötigt keine Authentifizierung
        return MusicBrainzAPI()
    
    else:
        raise Exception(f"Unbekannter Provider: {provider}")


def search_music(user_id, provider, query, limit=10):
    """Sucht nach Musik über den angegebenen Provider."""
    client = get_api_client(user_id, provider)
    return client.search(query, limit)


def search_music_multi_provider(query, limit=10, min_results=5, user_id=None):
    """
    Sucht nach Musik über alle aktivierten Provider in konfigurierter Reihenfolge.
    Stoppt, wenn genug Ergebnisse gefunden wurden.
    
    Args:
        query: Suchbegriff (kann Titel, Künstler, Album enthalten, z.B. "sido straßenjunge")
        limit: Maximale Anzahl Ergebnisse pro Provider
        min_results: Minimale Anzahl Ergebnisse bevor Suche stoppt
        user_id: Benutzer-ID für OAuth-basierte Provider (Spotify)
    
    Returns:
        Liste von Suchergebnissen mit Provider-Label
    """
    from app.models.music import MusicSettings
    from app.models.user import User
    
    # Hole aktivierte Provider und Reihenfolge
    enabled_providers = MusicSettings.get_enabled_providers()
    provider_order = MusicSettings.get_provider_order()
    
    # Filtere nur aktivierte Provider
    active_providers = [p for p in provider_order if p in enabled_providers]
    
    if not active_providers:
        return []
    
    # Für Spotify benötigen wir einen Benutzer mit verbundenem Account
    spotify_user_id = user_id
    if 'spotify' in active_providers and not spotify_user_id:
        # Suche nach Admin mit verbundenem Spotify-Account
        from app.utils.music_oauth import is_provider_connected
        admins = User.query.filter_by(is_admin=True).all()
        for admin in admins:
            if is_provider_connected(admin.id, 'spotify'):
                spotify_user_id = admin.id
                break
    
    all_results = []
    seen_tracks = set()  # Verhindere Duplikate (Titel + Künstler)
    
    # Suche nacheinander über Provider
    for provider in active_providers:
        try:
            # Spotify benötigt OAuth (Benutzer-Login)
            if provider == 'spotify':
                if not spotify_user_id:
                    logger.warning("Spotify aktiviert, aber kein verbundener Account gefunden. Überspringe Spotify.")
                    continue
                client = get_api_client(user_id=spotify_user_id, provider=provider, use_client_credentials=False)
            # YouTube kann mit API-Key verwendet werden
            elif provider == 'youtube':
                client = get_api_client(user_id=None, provider=provider, use_client_credentials=True)
            # MusicBrainz benötigt keine Authentifizierung
            else:
                client = get_api_client(user_id=None, provider=provider, use_client_credentials=False)
            
            results = client.search(query, limit=limit)
            
            # Füge Ergebnisse hinzu, entferne Duplikate
            for result in results:
                # Erstelle eindeutigen Key für Duplikat-Prüfung
                track_key = (result.get('title', '').lower().strip(), 
                           result.get('artist', '').lower().strip())
                
                if track_key not in seen_tracks and track_key[0]:  # Titel muss vorhanden sein
                    seen_tracks.add(track_key)
                    all_results.append(result)
            
            # Wenn genug Ergebnisse gefunden, stoppe Suche
            if len(all_results) >= min_results:
                logger.info(f"Genug Ergebnisse gefunden ({len(all_results)}), stoppe Suche nach Provider {provider}")
                break
                
        except Exception as e:
            logger.warning(f"Fehler beim Suchen mit Provider {provider}: {e}")
            # Weiter mit nächstem Provider
            continue
    
    # Sortiere Ergebnisse nach Relevanz (einfache Sortierung)
    # Priorisiere Ergebnisse mit vollständigen Informationen
    all_results.sort(key=lambda x: (
        not x.get('artist'),  # Ergebnisse ohne Künstler nach hinten
        not x.get('image_url'),  # Ergebnisse ohne Bild nach hinten
        x.get('title', '').lower()
    ))
    
    return all_results[:limit * 2]  # Gib mehr Ergebnisse zurück, da aus mehreren Providern


def get_track(user_id, provider, track_id):
    """Holt Details zu einem Track."""
    client = get_api_client(user_id, provider)
    return client.get_track(track_id)


def get_playlists(user_id, provider):
    """Holt Playlists des Benutzers."""
    if provider != 'youtube':
        raise Exception("Playlists werden nur für YouTube unterstützt")
    client = get_api_client(user_id, provider)
    return client.get_playlists()

