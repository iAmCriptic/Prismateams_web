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
    
    def search(self, query, limit=10, parsed_query=None):
        """
        Sucht nach Liedern.
        
        Args:
            query: Rohe Query-String (für Fallback)
            limit: Maximale Anzahl Ergebnisse
            parsed_query: Optionales Dictionary mit 'title', 'artist', 'album' für erweiterte Suche
        """
        from app.utils.music_search_parser import build_search_query_for_provider
        
        # Wenn geparste Query vorhanden, baue optimierte Query
        if parsed_query:
            search_query = build_search_query_for_provider(parsed_query, 'spotify')
        else:
            search_query = query
        
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{self.BASE_URL}/search',
                    headers=self.headers,
                    params={
                        'q': search_query,
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
    
    def get_recommendations(self, track_id, limit=5):
        """
        Holt Empfehlungen basierend auf einem Track.
        
        Args:
            track_id: Spotify Track-ID als Seed
            limit: Maximale Anzahl Recommendations (max 100, aber wir nutzen typisch 5-10)
            
        Returns:
            Liste von Track-Dictionaries im gleichen Format wie search()
        """
        last_exception = None
        
        # Stelle sicher, dass limit nicht zu hoch ist
        limit = min(limit, 100)
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{self.BASE_URL}/recommendations',
                    headers=self.headers,
                    params={
                        'seed_tracks': track_id,
                        'limit': limit
                    },
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                results = []
                for track in data.get('tracks', []):
                    results.append({
                        'id': track['id'],
                        'title': track['name'],
                        'artist': ', '.join([artist['name'] for artist in track['artists']]),
                        'album': track['album']['name'],
                        'image_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                        'url': track['external_urls']['spotify'],
                        'duration_ms': track['duration_ms'],
                        'provider': 'spotify',
                        'is_recommendation': True  # Flag für Frontend
                    })
                return results
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Spotify Recommendations API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify Recommendations API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Spotify Recommendations API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Spotify Recommendations API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"Spotify Recommendations API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                # Bei 401/403 könnte es ein Berechtigungsproblem sein - logge aber nicht als Fehler
                if e.response and e.response.status_code in [401, 403]:
                    logger.info(f"Spotify Recommendations API: Keine Berechtigung oder Track nicht verfügbar")
                    return []
                raise Exception(f"Spotify Recommendations API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"Spotify Recommendations API Fehler: {str(e)}")
        
        raise Exception(f"Spotify Recommendations API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")


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
    
    def search(self, query, limit=10, parsed_query=None):
        """
        Sucht nach Liedern.
        
        Args:
            query: Rohe Query-String (für Fallback)
            limit: Maximale Anzahl Ergebnisse
            parsed_query: Optionales Dictionary mit 'title', 'artist', 'album' für optimierte Suche
        """
        from app.utils.music_search_parser import build_search_query_for_provider
        
        # Wenn geparste Query vorhanden, baue optimierte Query
        if parsed_query:
            search_query = build_search_query_for_provider(parsed_query, 'youtube')
            # Für YouTube Music fügen wir spezifische Begriffe hinzu, um YouTube Music Inhalte zu priorisieren
            # "official audio" hilft dabei, offizielle Musik-Versionen zu finden
            search_query = f'{search_query} official audio'
        else:
            search_query = f'{query} official audio music'
        
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Suche nach Musik-Videos mit Fokus auf YouTube Music
                params = {
                    'q': search_query,
                    'type': 'video',
                    'videoCategoryId': '10',  # Music category
                    'maxResults': limit * 2,  # Hole mehr, um dann zu filtern
                    'part': 'snippet',
                    'order': 'relevance'  # Relevanz-Sortierung
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
                
                # Priorisiere YouTube Music spezifische Inhalte
                prioritized_results = []
                other_results = []
                
                for item in data.get('items', []):
                    title = item['snippet']['title']
                    description = item['snippet'].get('description', '').lower()
                    channel_title = item['snippet'].get('channelTitle', '').lower()
                    
                    track_data = {
                        'id': item['id']['videoId'],
                        'title': title,
                        'artist': item['snippet'].get('channelTitle', 'Unbekannt'),
                        'album': None,
                        'image_url': item['snippet']['thumbnails']['high']['url'] if 'high' in item['snippet']['thumbnails'] else item['snippet']['thumbnails']['default']['url'],
                        'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                        'duration_ms': None,
                        'provider': 'youtube',
                        '_youtube_music_score': 0  # Score für Priorisierung
                    }
                    
                    # Score basierend auf YouTube Music Indikatoren
                    score = 0
                    
                    # Höchste Priorität: "Official Audio" oder "Official Music Video" im Titel/Description
                    if 'official audio' in title.lower() or 'official audio' in description:
                        score += 100
                    if 'official music video' in title.lower() or 'official music video' in description:
                        score += 90
                    
                    # YouTube Music Topic Channels (offizielle Musik-Channels)
                    if '- topic' in channel_title or 'topic' in channel_title:
                        score += 80
                    
                    # VEVO Channels (offizielle Musik-Videos)
                    if 'vevo' in channel_title:
                        score += 70
                    
                    # "Music" im Titel
                    if 'music' in title.lower():
                        score += 20
                    
                    # Offizielle Künstler-Channels (oft Name des Künstlers = Channel-Name)
                    if parsed_query and parsed_query.get('artist'):
                        artist_name = parsed_query.get('artist', '').lower()
                        if artist_name in channel_title:
                            score += 60
                    
                    track_data['_youtube_music_score'] = score
                    
                    if score >= 50:  # Mindestens 50 Punkte = priorisiert
                        prioritized_results.append(track_data)
                    else:
                        other_results.append(track_data)
                
                # Sortiere priorisierte Ergebnisse nach Score
                prioritized_results.sort(key=lambda x: -x['_youtube_music_score'])
                
                # Kombiniere: Erst priorisierte, dann andere
                all_results = prioritized_results + other_results
                
                # Entferne Score vor Rückgabe
                for result in all_results:
                    result.pop('_youtube_music_score', None)
                
                return all_results[:limit]
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
    
    def get_related_videos(self, video_id, limit=5):
        """
        Holt ähnliche/verwandte Videos basierend auf einem Video-ID (für Recommendations).
        
        Args:
            video_id: YouTube Video-ID als Seed
            limit: Maximale Anzahl Recommendations
            
        Returns:
            Liste von Track-Dictionaries im gleichen Format wie search()
        """
        last_exception = None
        
        # Stelle sicher, dass limit nicht zu hoch ist (YouTube API Limit: 50)
        limit = min(limit, 50)
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Suche nach ähnlichen Videos mit relatedToVideoId
                # Wichtig: Dieser Parameter funktioniert nur in Kombination mit type=video
                params = {
                    'relatedToVideoId': video_id,
                    'type': 'video',
                    'videoCategoryId': '10',  # Nur Musik-Videos
                    'maxResults': limit,
                    'part': 'snippet',
                    'order': 'relevance'
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
                    # Überspringe das ursprüngliche Video selbst
                    if item['id']['videoId'] == video_id:
                        continue
                    
                    title = item['snippet']['title']
                    channel_title = item['snippet'].get('channelTitle', 'Unbekannt')
                    
                    # Priorisiere YouTube Music Inhalte
                    score = 0
                    if '- topic' in channel_title.lower() or 'topic' in channel_title.lower():
                        score += 50
                    if 'vevo' in channel_title.lower():
                        score += 40
                    if 'official audio' in title.lower() or 'official music video' in title.lower():
                        score += 60
                    
                    results.append({
                        'id': item['id']['videoId'],
                        'title': title,
                        'artist': channel_title,
                        'album': None,
                        'image_url': item['snippet']['thumbnails']['high']['url'] if 'high' in item['snippet']['thumbnails'] else item['snippet']['thumbnails']['default']['url'],
                        'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                        'duration_ms': None,
                        'provider': 'youtube',
                        'is_recommendation': True,  # Flag für Frontend
                        '_score': score
                    })
                
                # Sortiere nach Score (höhere Scores = bessere YouTube Music Inhalte)
                results.sort(key=lambda x: -x.get('_score', 0))
                
                # Entferne Score vor Rückgabe
                for result in results:
                    result.pop('_score', None)
                
                return results[:limit]
                
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube Related Videos API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube Related Videos API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"YouTube Related Videos API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"YouTube Related Videos API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"YouTube Related Videos API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                # Bei 400 könnte relatedToVideoId nicht unterstützt werden (limitiert in manchen API-Keys)
                if e.response and e.response.status_code == 400:
                    logger.info(f"YouTube Related Videos API: relatedToVideoId Parameter nicht unterstützt oder ungültig")
                    return []
                raise Exception(f"YouTube Related Videos API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"YouTube Related Videos API Fehler: {str(e)}")
        
        raise Exception(f"YouTube Related Videos API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")
    
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
    
    def search(self, query, limit=10, parsed_query=None):
        """
        Sucht nach Liedern. Unterstützt erweiterte Suche (Titel, Künstler, Album).
        
        Args:
            query: Rohe Query-String (für Fallback)
            limit: Maximale Anzahl Ergebnisse
            parsed_query: Optionales Dictionary mit 'title', 'artist', 'album' für erweiterte Syntax
        """
        from app.utils.music_search_parser import build_search_query_for_provider
        
        # Rate Limiting beachten
        self._rate_limit()
        
        # Wenn geparste Query vorhanden, baue optimierte Query
        if parsed_query:
            search_query = build_search_query_for_provider(parsed_query, 'musicbrainz')
        else:
            search_query = query
        
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                
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


class DeezerAPI:
    """Deezer API Client (öffentliche API, optional App-ID für Rate Limits)."""
    
    BASE_URL = 'https://api.deezer.com'
    
    def __init__(self, app_id=None):
        """
        Initialisiert den Deezer API Client.
        
        Args:
            app_id: Optional App-ID für höhere Rate Limits (empfohlen)
        """
        self.app_id = app_id
        self.headers = {
            'Accept': 'application/json'
        }
    
    def search(self, query, limit=10, parsed_query=None):
        """
        Sucht nach Liedern.
        
        Args:
            query: Rohe Query-String (für Fallback)
            limit: Maximale Anzahl Ergebnisse
            parsed_query: Optionales Dictionary mit 'title', 'artist', 'album' für erweiterte Suche
        """
        from app.utils.music_search_parser import build_search_query_for_provider
        
        # Wenn geparste Query vorhanden, baue optimierte Query
        if parsed_query:
            search_query = build_search_query_for_provider(parsed_query, 'deezer')
        else:
            search_query = query
        
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                params = {
                    'q': search_query,
                    'limit': limit
                }
                
                # Deezer öffentliche API benötigt keine Authentifizierung für Suchen
                # App-ID wird gespeichert für mögliche zukünftige Verwendung
                
                response = requests.get(
                    f'{self.BASE_URL}/search',
                    headers=self.headers,
                    params=params,
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                results = []
                for track in data.get('data', []):
                    # Deezer gibt Dauer in Sekunden zurück, konvertiere zu ms
                    duration_ms = track.get('duration') * 1000 if track.get('duration') else None
                    
                    results.append({
                        'id': str(track['id']),
                        'title': track.get('title', 'Unbekannt'),
                        'artist': track.get('artist', {}).get('name', 'Unbekannter Künstler'),
                        'album': track.get('album', {}).get('title', None),
                        'image_url': track.get('album', {}).get('cover_medium', None),
                        'url': track.get('link', f"https://www.deezer.com/track/{track['id']}"),
                        'duration_ms': duration_ms,
                        'provider': 'deezer'
                    })
                
                return results
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Deezer API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Deezer API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Deezer API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Deezer API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"Deezer API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Deezer API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"Deezer API Fehler: {str(e)}")
        
        raise Exception(f"Deezer API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")
    
    def get_track(self, track_id):
        """Holt Details zu einem Track."""
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                params = {}
                # Deezer öffentliche API benötigt keine Authentifizierung
                
                response = requests.get(
                    f'{self.BASE_URL}/track/{track_id}',
                    headers=self.headers,
                    params=params,
                    timeout=MUSIC_API_TIMEOUT
                )
                response.raise_for_status()
                track = response.json()
                
                # Deezer gibt Dauer in Sekunden zurück, konvertiere zu ms
                duration_ms = track.get('duration') * 1000 if track.get('duration') else None
                
                return {
                    'id': str(track['id']),
                    'title': track.get('title', 'Unbekannt'),
                    'artist': track.get('artist', {}).get('name', 'Unbekannter Künstler'),
                    'album': track.get('album', {}).get('title', None),
                    'image_url': track.get('album', {}).get('cover_medium', None),
                    'url': track.get('link', f"https://www.deezer.com/track/{track['id']}"),
                    'duration_ms': duration_ms,
                    'provider': 'deezer'
                }
            except Timeout as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Deezer API Timeout (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Deezer API Timeout: Die Anfrage dauerte zu lange.")
            except ConnectionError as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    logger.warning(f"Deezer API Verbindungsfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Deezer API Verbindungsfehler: {str(e)}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES and e.response and e.response.status_code >= 500:
                    logger.warning(f"Deezer API Serverfehler (Versuch {attempt + 1}/{MAX_RETRIES + 1}), retry...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise Exception(f"Deezer API Fehler: {str(e)}")
            except Exception as e:
                raise Exception(f"Deezer API Fehler: {str(e)}")
        
        raise Exception(f"Deezer API Fehler nach {MAX_RETRIES + 1} Versuchen: {str(last_exception)}")


def get_api_client(user_id=None, provider=None, use_client_credentials=False):
    """
    Holt einen API-Client für den angegebenen Provider.
    
    Args:
        user_id: Benutzer-ID (erforderlich für Spotify OAuth, optional für YouTube API-Key)
        provider: Provider-Name ('spotify', 'youtube', 'musicbrainz', 'deezer')
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
    
    elif provider == 'deezer':
        # Deezer benötigt keine Authentifizierung, aber App-ID ist optional (empfohlen für Rate Limits)
        app_id = get_music_setting('deezer_app_id')
        return DeezerAPI(app_id=app_id if app_id else None)
    
    else:
        raise Exception(f"Unbekannter Provider: {provider}")


def search_music(user_id, provider, query, limit=10, parsed_query=None):
    """Sucht nach Musik über den angegebenen Provider."""
    client = get_api_client(user_id, provider)
    return client.search(query, limit, parsed_query=parsed_query)


def _calculate_relevance_score(result, parsed_query):
    """
    Berechnet einen Relevanz-Score für ein Suchergebnis basierend auf der geparsten Query.
    
    Args:
        result: Track-Dictionary mit title, artist, album
        parsed_query: Geparste Query mit title, artist, album
        
    Returns:
        Score (höher = relevanter)
    """
    score = 0
    result_title = (result.get('title', '') or '').lower().strip()
    result_artist = (result.get('artist', '') or '').lower().strip()
    result_album = (result.get('album', '') or '').lower().strip()
    
    query_title = (parsed_query.get('title') or '').lower().strip()
    query_artist = (parsed_query.get('artist') or '').lower().strip()
    query_album = (parsed_query.get('album') or '').lower().strip()
    
    # Exakte Titel-Übereinstimmung (höchste Priorität)
    if query_title and result_title == query_title:
        score += 1000
    elif query_title and result_title.startswith(query_title):
        score += 500
    elif query_title and query_title in result_title:
        score += 200
    
    # Exakte Artist-Übereinstimmung
    if query_artist and result_artist:
        # Prüfe ob query_artist in result_artist enthalten ist (wegen mehrerer Artists)
        if query_artist == result_artist:
            score += 800
        elif query_artist in result_artist:
            score += 400
        # Prüfe auch einzelne Wörter (z.B. "Sido" in "Sido, Samy Deluxe")
        artist_words = query_artist.split()
        for word in artist_words:
            if word in result_artist:
                score += 150
    
    # Album-Übereinstimmung
    if query_album and result_album and query_album in result_album:
        score += 300
    
    # Bonus für vollständige Informationen
    if result.get('artist') and result.get('image_url'):
        score += 100
    if result.get('album'):
        score += 50
    
    # Bonus für Spotify (bessere Qualität)
    if result.get('provider') == 'spotify':
        score += 20
    
    # Bonus für Deezer (gute Qualität)
    if result.get('provider') == 'deezer':
        score += 15
    
    return score


def search_music_multi_provider(query, limit=10, min_results=5, user_id=None, include_recommendations=False):
    """
    Sucht nach Musik über alle aktivierten Provider in konfigurierter Reihenfolge.
    Stoppt, wenn genug Ergebnisse gefunden wurden.
    
    Args:
        query: Suchbegriff (kann Titel, Künstler, Album enthalten, z.B. "sido straßenjunge" oder "Straßenjunge" "Sido")
        limit: Maximale Anzahl Ergebnisse pro Provider
        min_results: Minimale Anzahl Ergebnisse bevor Suche stoppt
        user_id: Benutzer-ID für OAuth-basierte Provider (Spotify)
        include_recommendations: Wenn True, füge Spotify Recommendations hinzu wenn verfügbar (YouTube Recommendations wurden entfernt)
    
    Returns:
        Dictionary mit 'results' (Liste von Suchergebnissen) und optional 'recommendations' (Liste)
    """
    from app.models.music import MusicSettings
    from app.models.user import User
    from app.utils.music_search_parser import parse_search_query
    
    # Parse Query
    parsed_query = parse_search_query(query)
    
    # Hole aktivierte Provider und Reihenfolge
    enabled_providers = MusicSettings.get_enabled_providers()
    provider_order = MusicSettings.get_provider_order()
    
    # Filtere nur aktivierte Provider
    active_providers = [p for p in provider_order if p in enabled_providers]
    
    if not active_providers:
        return {'results': [], 'recommendations': []}
    
    # Für Spotify benötigen wir einen Benutzer mit verbundenem Account
    spotify_user_id = user_id
    spotify_client = None
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
    first_spotify_track_id = None  # Für Spotify Recommendations
    
    # Suche nacheinander über Provider
    for provider in active_providers:
        try:
            # Spotify benötigt OAuth (Benutzer-Login)
            if provider == 'spotify':
                if not spotify_user_id:
                    logger.warning("Spotify aktiviert, aber kein verbundener Account gefunden. Überspringe Spotify.")
                    continue
                client = get_api_client(user_id=spotify_user_id, provider=provider, use_client_credentials=False)
                spotify_client = client  # Speichere für später (Recommendations)
            # YouTube kann mit API-Key verwendet werden
            elif provider == 'youtube':
                client = get_api_client(user_id=None, provider=provider, use_client_credentials=True)
            # MusicBrainz benötigt keine Authentifizierung
            else:
                client = get_api_client(user_id=None, provider=provider, use_client_credentials=False)
            
            # Nutze geparste Query für bessere Ergebnisse
            results = client.search(query, limit=limit, parsed_query=parsed_query)
            
            # Füge Ergebnisse hinzu, entferne Duplikate
            for result in results:
                # Erstelle eindeutigen Key für Duplikat-Prüfung
                track_key = (result.get('title', '').lower().strip(), 
                           result.get('artist', '').lower().strip())
                
                if track_key not in seen_tracks and track_key[0]:  # Titel muss vorhanden sein
                    seen_tracks.add(track_key)
                    # Berechne Relevanz-Score
                    result['_relevance_score'] = _calculate_relevance_score(result, parsed_query)
                    all_results.append(result)
                    
                    # Speichere ersten Spotify-Track für Recommendations
                    if provider == 'spotify' and not first_spotify_track_id:
                        first_spotify_track_id = result.get('id')
            
            # Wenn genug Ergebnisse gefunden, stoppe Suche
            if len(all_results) >= min_results:
                logger.info(f"Genug Ergebnisse gefunden ({len(all_results)}), stoppe Suche nach Provider {provider}")
                break
                
        except Exception as e:
            logger.warning(f"Fehler beim Suchen mit Provider {provider}: {e}")
            # Weiter mit nächstem Provider
            continue
    
    # Sortiere Ergebnisse nach Relevanz-Score (höher = besser)
    all_results.sort(key=lambda x: (
        -x.get('_relevance_score', 0),  # Negativ für absteigende Sortierung
        not x.get('artist'),  # Tiebreaker: Ergebnisse ohne Künstler nach hinten
        not x.get('image_url'),  # Tiebreaker: Ergebnisse ohne Bild nach hinten
        x.get('title', '').lower()
    ))
    
    # Entferne internen Score vor Rückgabe
    for result in all_results:
        result.pop('_relevance_score', None)
    
    # Bereite Ergebnis vor
    final_results = all_results[:limit * 2]  # Gib mehr Ergebnisse zurück, da aus mehreren Providern
    recommendations = []
    seen_recommendations = set()  # Verhindere Duplikate in Recommendations
    
    # Hole Spotify Recommendations wenn gewünscht und möglich
    if include_recommendations and spotify_client and first_spotify_track_id:
        try:
            spotify_recs = spotify_client.get_recommendations(first_spotify_track_id, limit=5)
            for rec in spotify_recs:
                track_key = (rec.get('title', '').lower().strip(), 
                           rec.get('artist', '').lower().strip())
                if track_key not in seen_recommendations and track_key[0]:
                    seen_recommendations.add(track_key)
                    recommendations.append(rec)
            logger.info(f"Spotify Recommendations geholt: {len(spotify_recs)} Ergebnisse")
        except Exception as e:
            logger.warning(f"Fehler beim Abrufen von Spotify Recommendations: {e}")
    
    # YouTube Recommendations wurden entfernt, da die API (relatedToVideoId) nicht mehr unterstützt wird
    
    return {
        'results': final_results,
        'recommendations': recommendations
    }


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

