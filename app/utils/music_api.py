import requests
from app import db
from app.models.music import MusicProviderToken
from app.utils.music_oauth import decrypt_token, refresh_token_if_needed
import os


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
        try:
            response = requests.get(
                f'{self.BASE_URL}/search',
                headers=self.headers,
                params={
                    'q': query,
                    'type': 'track',
                    'limit': limit
                },
                timeout=10
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
        except Exception as e:
            raise Exception(f"Spotify API Fehler: {str(e)}")
    
    def get_track(self, track_id):
        """Holt Details zu einem Track."""
        try:
            response = requests.get(
                f'{self.BASE_URL}/tracks/{track_id}',
                headers=self.headers,
                timeout=10
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
        except Exception as e:
            raise Exception(f"Spotify API Fehler: {str(e)}")


class YouTubeMusicAPI:
    """YouTube Music API Client (verwendet YouTube Data API v3)."""
    
    BASE_URL = 'https://www.googleapis.com/youtube/v3'
    
    def __init__(self, access_token):
        self.access_token = access_token
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
    
    def search(self, query, limit=10):
        """Sucht nach Liedern."""
        try:
            # Suche nach Musik-Videos
            response = requests.get(
                f'{self.BASE_URL}/search',
                headers=self.headers,
                params={
                    'q': f'{query} music song',
                    'type': 'video',
                    'videoCategoryId': '10',  # Music category
                    'maxResults': limit,
                    'part': 'snippet'
                },
                timeout=10
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
        except Exception as e:
            raise Exception(f"YouTube API Fehler: {str(e)}")
    
    def get_track(self, track_id):
        """Holt Details zu einem Track."""
        try:
            response = requests.get(
                f'{self.BASE_URL}/videos',
                headers=self.headers,
                params={
                    'id': track_id,
                    'part': 'snippet,contentDetails'
                },
                timeout=10
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
        except Exception as e:
            raise Exception(f"YouTube API Fehler: {str(e)}")
    
    def get_playlists(self):
        """Holt Playlists des Benutzers."""
        try:
            response = requests.get(
                f'{self.BASE_URL}/playlists',
                headers=self.headers,
                params={
                    'part': 'snippet,contentDetails',
                    'mine': 'true',
                    'maxResults': 50
                },
                timeout=10
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
        except Exception as e:
            raise Exception(f"YouTube API Fehler: {str(e)}")


def get_api_client(user_id, provider):
    """Holt einen API-Client für den angegebenen Provider."""
    token_obj = MusicProviderToken.query.filter_by(user_id=user_id, provider=provider).first()
    if not token_obj:
        raise Exception(f"Kein Token für {provider} gefunden")
    
    # Token aktualisieren falls nötig
    refresh_token_if_needed(token_obj)
    
    access_token = decrypt_token(token_obj.access_token)
    
    if provider == 'spotify':
        return SpotifyAPI(access_token)
    elif provider == 'youtube':
        return YouTubeMusicAPI(access_token)
    else:
        raise Exception(f"Unbekannter Provider: {provider}")


def search_music(user_id, provider, query, limit=10):
    """Sucht nach Musik über den angegebenen Provider."""
    client = get_api_client(user_id, provider)
    return client.search(query, limit)


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

