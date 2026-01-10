"""
Parser für Musik-Suchanfragen.
Erkennt intelligente Formate wie "Titel" "Artist" oder versucht automatisch
Titel und Artist aus freiem Text zu extrahieren.
"""
import re
from typing import Dict, Optional


def parse_search_query(query: str) -> Dict[str, Optional[str]]:
    """
    Parst eine Suchanfrage und extrahiert Titel, Artist und Album.
    
    Unterstützte Formate:
    - "Titel" "Artist" - Explizite Anführungszeichen
    - "Titel" "Artist" "Album" - Mit Album
    - "Titel" - Nur Titel
    - Freier Text - Automatische Erkennung (letztes Wort = Artist, Rest = Titel)
    
    Args:
        query: Die rohe Suchanfrage vom Benutzer
        
    Returns:
        Dictionary mit keys: 'title', 'artist', 'album', 'raw'
        Ungenutzte Felder sind None, 'raw' enthält immer die Original-Query
    """
    if not query or not query.strip():
        return {'title': None, 'artist': None, 'album': None, 'raw': query}
    
    query = query.strip()
    result = {'title': None, 'artist': None, 'album': None, 'raw': query}
    
    # Prüfe auf Anführungszeichen-Format
    # Muster: "..." "..." oder "..." "..." "..."
    quoted_pattern = r'"([^"]+)"'
    quoted_matches = re.findall(quoted_pattern, query)
    
    if quoted_matches:
        # Anführungszeichen-Format gefunden
        if len(quoted_matches) >= 1:
            result['title'] = quoted_matches[0].strip()
        if len(quoted_matches) >= 2:
            result['artist'] = quoted_matches[1].strip()
        if len(quoted_matches) >= 3:
            result['album'] = quoted_matches[2].strip()
        
        # Wenn nach Anführungszeichen noch Text kommt, könnte das ein Album sein
        # (wenn nur 2 Anführungszeichen gefunden wurden)
        if len(quoted_matches) == 2:
            remaining = re.sub(quoted_pattern, '', query).strip()
            if remaining:
                result['album'] = remaining
        
        return result
    
    # Keine Anführungszeichen - versuche automatische Erkennung
    # Heuristik: Wenn 2+ Wörter, nehme letztes Wort als Artist, Rest als Titel
    words = query.split()
    
    if len(words) == 0:
        return result
    
    if len(words) == 1:
        # Nur ein Wort - könnte Titel oder Artist sein
        # Versuche als Titel zu behandeln (häufigerer Fall)
        result['title'] = words[0]
        return result
    
    # Mehrere Wörter: intelligente Trennung
    # Strategie 1: Wenn "von" oder "by" vorhanden, trenne dort
    # Beispiel: "Straßenjunge von Sido" oder "Song by Artist"
    separator_pattern = r'\s+(von|by|vom|von der|von dem)\s+'
    separator_match = re.search(separator_pattern, query, re.IGNORECASE)
    
    if separator_match:
        parts = re.split(separator_pattern, query, flags=re.IGNORECASE)
        if len(parts) >= 3:
            result['title'] = parts[0].strip()
            result['artist'] = parts[-1].strip()
            return result
    
    # Strategie 2: Letztes Wort als Artist, Rest als Titel
    # Dies funktioniert gut für "Straßenjunge Sido" → Titel="Straßenjunge", Artist="Sido"
    if len(words) >= 2:
        result['title'] = ' '.join(words[:-1]).strip()
        result['artist'] = words[-1].strip()
        return result
    
    return result


def build_search_query_for_provider(parsed: Dict[str, Optional[str]], provider: str) -> str:
    """
    Baut eine optimierte Suchanfrage für einen spezifischen Provider basierend auf
    geparsten Komponenten.
    
    Args:
        parsed: Ergebnis von parse_search_query()
        provider: 'spotify', 'youtube', 'musicbrainz', oder 'deezer'
        
    Returns:
        Optimierte Query-String für den Provider
    """
    title = parsed.get('title')
    artist = parsed.get('artist')
    album = parsed.get('album')
    raw = parsed.get('raw', '')
    
    if provider == 'spotify':
        # Spotify unterstützt erweiterte Syntax: artist:"name" track:"title" album:"album"
        parts = []
        if artist:
            parts.append(f'artist:"{artist}"')
        if title:
            parts.append(f'track:"{title}"')
        elif not artist:  # Wenn kein Artist, aber Titel vorhanden
            parts.append(f'track:"{title}"')
        if album:
            parts.append(f'album:"{album}"')
        
        if parts:
            return ' '.join(parts)
        return raw
    
    elif provider == 'youtube':
        # YouTube: Konstruiere natürliche Query
        parts = []
        if title:
            parts.append(title)
        if artist:
            parts.append(artist)
        if album:
            parts.append(album)
        
        if parts:
            return ' '.join(parts)
        return raw
    
    elif provider == 'musicbrainz':
        # MusicBrainz unterstützt: artist:"name" AND recording:"title"
        parts = []
        conditions = []
        
        if artist:
            conditions.append(f'artist:"{artist}"')
        if title:
            conditions.append(f'recording:"{title}"')
        if album:
            conditions.append(f'release:"{album}"')
        
        if conditions:
            query = ' AND '.join(conditions)
            return query
        return raw
    
    elif provider == 'deezer':
        # Deezer: Konstruiere natürliche Query (ähnlich YouTube)
        parts = []
        if title:
            parts.append(title)
        if artist:
            parts.append(artist)
        if album:
            parts.append(album)
        
        if parts:
            return ' '.join(parts)
        return raw
    
    # Fallback: verwende raw query
    return raw
