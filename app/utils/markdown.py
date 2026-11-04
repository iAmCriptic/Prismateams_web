"""
Gemeinsame Markdown-Verarbeitungsfunktionen für Files und Wiki.
"""
import re
from flask import current_app


VIDEO_EXTENSIONS = ('.mp4', '.webm', '.ogg', '.mov', '.m4v')
AUDIO_EXTENSIONS = ('.mp3', '.wav', '.oga', '.m4a', '.aac', '.flac')

SAFE_IFRAME_PREFIXES = (
    'https://www.youtube.com/embed/',
    'https://www.youtube-nocookie.com/embed/',
    'https://player.vimeo.com/video/',
    'https://www.dailymotion.com/embed/video/',
    'https://www.loom.com/embed/',
    '/wiki/media/',
    '/files/',
)


def extract_youtube_id(url_or_id):
    """Extrahiert die YouTube-Video-ID aus URLs oder Strings."""
    if not url_or_id:
        return None
    val = url_or_id.strip()
    if re.match(r'^[a-zA-Z0-9_-]{11}$', val):
        return val
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?(?:.*?&)?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube-nocookie\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, val)
        if m:
            return m.group(1)
    return None


def extract_vimeo_id(url_or_id):
    """Extrahiert die Vimeo-Video-ID aus URLs oder Strings."""
    if not url_or_id:
        return None
    val = url_or_id.strip()
    if val.isdigit():
        return val
    m = re.search(r'vimeo\.com\/(?:channels\/(?:\w+\/)?|groups\/[^\/]*\/videos\/|album\/\d+\/video\/|)(\d+)', val)
    if m:
        return m.group(1)
    m = re.search(r'player\.vimeo\.com\/video\/(\d+)', val)
    if m:
        return m.group(1)
    return None


def _iframe_attribute_filter(tag, name, value):
    """Erlaubt nur sichere iframe-Attribute und geprüfte Video-Host-Quellen."""
    if name == 'src':
        val = (value or '').strip().lower()
        return any(val.startswith(p) for p in SAFE_IFRAME_PREFIXES)
    return name in (
        'width', 'height', 'frameborder', 'allow', 'allowfullscreen',
        'title', 'class', 'loading', 'referrerpolicy'
    )


def _sanitize_markdown_html(html):
    """Sanitize rendered markdown HTML to prevent XSS."""
    try:
        import bleach

        allowed_tags = {
            'a', 'abbr', 'acronym', 'b', 'blockquote', 'br', 'code', 'dd', 'del', 'div',
            'dl', 'dt', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'kbd',
            'li', 'mark', 'ol', 'p', 'pre', 's', 'span', 'strong', 'sub', 'sup', 'table',
            'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul', 'col', 'colgroup',
            # Erweiterte Tags für Videos, Audio & Medien
            'video', 'source', 'audio', 'track', 'iframe', 'figure', 'figcaption', 'picture'
        }
        allowed_attributes = {
            '*': ['class', 'id'],
            'a': ['href', 'title', 'target', 'rel'],
            'img': ['src', 'alt', 'title', 'width', 'height', 'loading'],
            'video': [
                'src', 'controls', 'poster', 'preload', 'width', 'height',
                'loop', 'muted', 'playsinline', 'autoplay', 'title'
            ],
            'source': ['src', 'type', 'media'],
            'audio': ['src', 'controls', 'preload', 'loop', 'muted'],
            'track': ['src', 'kind', 'srclang', 'label', 'default'],
            'iframe': _iframe_attribute_filter,
            'figure': ['class', 'id'],
            'figcaption': ['class'],
            'table': ['width'],
            'col': ['width', 'span'],
            'colgroup': ['span'],
            'th': ['colspan', 'rowspan', 'width', 'align'],
            'td': ['colspan', 'rowspan', 'width', 'align'],
        }
        allowed_protocols = ['http', 'https', 'mailto']

        cleaned = bleach.clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attributes,
            protocols=allowed_protocols,
            strip=True,
            strip_comments=True,
        )
        return bleach.linkify(cleaned)
    except Exception as exc:
        current_app.logger.error(f"Markdown sanitization error: {exc}")
        import html as html_module
        return html_module.escape(html)


def process_video_embeds(content):
    """
    Erkennt Video-Direktiven (@[youtube], @[vimeo], @[video]),
    Markdown-Bilder mit Video-URLs/YouTube-Links sowie freistehende
    Video-Links und wandelt sie in responsive HTML-Video-Container um.
    """
    if not content:
        return content

    # 1. Spezifische Direktiven: @[youtube](...), @[vimeo](...), @[video](...)
    def replace_directive(m):
        kind = m.group(1).lower()
        target = m.group(2).strip()
        if kind == 'youtube':
            yt_id = extract_youtube_id(target) or target
            return (
                f'\n\n<div class="wiki-media-embed wiki-video-wrapper wiki-video-responsive">'
                f'<iframe src="https://www.youtube-nocookie.com/embed/{yt_id}" '
                f'title="YouTube video player" frameborder="0" '
                f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
                f'allowfullscreen></iframe></div>\n\n'
            )
        elif kind == 'vimeo':
            vim_id = extract_vimeo_id(target) or target
            return (
                f'\n\n<div class="wiki-media-embed wiki-video-wrapper wiki-video-responsive">'
                f'<iframe src="https://player.vimeo.com/video/{vim_id}" '
                f'title="Vimeo video player" frameborder="0" '
                f'allow="autoplay; fullscreen; picture-in-picture" '
                f'allowfullscreen></iframe></div>\n\n'
            )
        elif kind == 'video':
            return (
                f'\n\n<figure class="wiki-media-embed wiki-video-wrapper">'
                f'<video controls preload="metadata" playsinline class="wiki-video-player" src="{target}">'
                f'<source src="{target}">'
                f'Ihr Browser unterstützt dieses Video nicht.'
                f'</video></figure>\n\n'
            )
        return m.group(0)

    content = re.sub(r'@\[(youtube|vimeo|video)\]\(([^)]+)\)', replace_directive, content, flags=re.IGNORECASE)

    # 2. Markdown Image-Syntax mit Video- oder YouTube/Vimeo-URLs: ![Alt](url)
    def replace_image_syntax(m):
        alt = m.group(1).strip()
        url = m.group(2).strip()

        # YouTube
        yt_id = extract_youtube_id(url)
        if yt_id:
            title = alt or "YouTube video"
            return (
                f'\n\n<div class="wiki-media-embed wiki-video-wrapper wiki-video-responsive">'
                f'<iframe src="https://www.youtube-nocookie.com/embed/{yt_id}" '
                f'title="{title}" frameborder="0" '
                f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
                f'allowfullscreen></iframe></div>\n\n'
            )

        # Vimeo
        vim_id = extract_vimeo_id(url)
        if vim_id:
            title = alt or "Vimeo video"
            return (
                f'\n\n<div class="wiki-media-embed wiki-video-wrapper wiki-video-responsive">'
                f'<iframe src="https://player.vimeo.com/video/{vim_id}" '
                f'title="{title}" frameborder="0" '
                f'allow="autoplay; fullscreen; picture-in-picture" '
                f'allowfullscreen></iframe></div>\n\n'
            )

        # Video-Dateien (.mp4, .webm, etc. oder Wiki-Media-Video)
        url_lower = url.split('?')[0].lower()
        if any(url_lower.endswith(ext) for ext in VIDEO_EXTENSIONS):
            caption = f'<figcaption class="wiki-video-caption">{alt}</figcaption>' if alt else ''
            title_attr = f' title="{alt}"' if alt else ''
            return (
                f'\n\n<figure class="wiki-media-embed wiki-video-wrapper">'
                f'<video controls preload="metadata" playsinline class="wiki-video-player"{title_attr} src="{url}">'
                f'<source src="{url}">'
                f'Ihr Browser unterstützt dieses Video nicht.'
                f'</video>{caption}</figure>\n\n'
            )

        # Audio-Dateien (.mp3, .wav, etc.)
        if any(url_lower.endswith(ext) for ext in AUDIO_EXTENSIONS):
            caption = f'<figcaption class="wiki-audio-caption">{alt}</figcaption>' if alt else ''
            return (
                f'\n\n<figure class="wiki-media-embed wiki-audio-wrapper">'
                f'<audio controls preload="metadata" class="wiki-audio-player" src="{url}">'
                f'<source src="{url}">'
                f'Ihr Browser unterstützt diese Audiodatei nicht.'
                f'</audio>{caption}</figure>\n\n'
            )

        return m.group(0)

    content = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_image_syntax, content)

    # 3. Freistehende YouTube- oder Vimeo-Links auf einer eigenen Zeile
    def replace_standalone_url(m):
        url = m.group(1).strip()
        yt_id = extract_youtube_id(url)
        if yt_id:
            return (
                f'\n\n<div class="wiki-media-embed wiki-video-wrapper wiki-video-responsive">'
                f'<iframe src="https://www.youtube-nocookie.com/embed/{yt_id}" '
                f'title="YouTube video player" frameborder="0" '
                f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
                f'allowfullscreen></iframe></div>\n\n'
            )
        vim_id = extract_vimeo_id(url)
        if vim_id:
            return (
                f'\n\n<div class="wiki-media-embed wiki-video-wrapper wiki-video-responsive">'
                f'<iframe src="https://player.vimeo.com/video/{vim_id}" '
                f'title="Vimeo video player" frameborder="0" '
                f'allow="autoplay; fullscreen; picture-in-picture" '
                f'allowfullscreen></iframe></div>\n\n'
            )
        return m.group(0)

    content = re.sub(
        r'(?m)^[ \t]*(https?:\/\/(?:www\.)?(?:youtube\.com\/watch\?[^\s]+|youtu\.be\/[^\s]+|youtube\.com\/shorts\/[^\s]+|vimeo\.com\/\d+))[ \t]*$',
        replace_standalone_url,
        content
    )

    return content


def process_markdown(content, wiki_mode=False):
    """
    Verarbeitet Markdown-Text zu HTML mit erweiterten Extensions und Video/Medien-Support.
    
    Args:
        content: Markdown-Text als String
        wiki_mode: Wenn True, werden Wiki-Links [[Seitenname]] verarbeitet
    
    Returns:
        Verarbeiteter HTML-String
    """
    try:
        import markdown
        
        def mermaid_formatter(source):
            return f'<div class="mermaid">{source}</div>'
        
        extensions = [
            'fenced_code',      # Code-Blöcke mit ```
            'codehilite',       # Syntax-Highlighting
            'nl2br',            # Zeilenumbrüche
            'toc',              # Table of Contents
            'footnotes',        # Fußnoten
            'def_list',         # Definitionslisten
            'attr_list',        # Attribute-Listen
            'abbr',             # Abkürzungen
            'tables',
        ]
        
        extension_configs = {}
        
        try:
            import pymdownx
            pymdownx_extensions = [
                'pymdownx.caret',   # Superscript: ^text^
                'pymdownx.tilde',   # Subscript: ~text~
                'pymdownx.superfences',  # Erweiterte Code-Blöcke
                'pymdownx.tables',  # Verbesserte Tabellen-Unterstützung
                'pymdownx.arithmatex'
            ]
            
            available_pymdownx = []
            for ext in pymdownx_extensions:
                try:
                    ext_name = ext.replace('pymdownx.', '')
                    __import__(f'pymdownx.{ext_name}')
                    available_pymdownx.append(ext)
                except ImportError:
                    current_app.logger.debug(f"pymdownx extension {ext} nicht verfügbar")
            
            extensions.extend(available_pymdownx)
            
            if 'pymdownx.arithmatex' in available_pymdownx:
                extension_configs['pymdownx.arithmatex'] = {
                    'generic': True
                }
            
            if 'pymdownx.superfences' in available_pymdownx:
                extension_configs['pymdownx.superfences'] = {
                    'custom_fences': [
                        {
                            'name': 'mermaid',
                            'class': 'mermaid',
                            'format': mermaid_formatter
                        }
                    ]
                }
            
            if 'pymdownx.superfences' in available_pymdownx and 'fenced_code' in extensions:
                extensions.remove('fenced_code')
            
            if 'pymdownx.tables' in available_pymdownx and 'tables' in extensions:
                extensions.remove('tables')
                
        except ImportError:
            current_app.logger.debug("pymdownx nicht verfügbar, nutze Standard-Markdown-Extensions")
        
        md = markdown.Markdown(extensions=extensions, extension_configs=extension_configs)
        
        # 1. Video- und Medien-Einbettungen verarbeiten
        content = process_video_embeds(content)

        # 2. Wiki-Links [[Seitenname]] verarbeiten
        if wiki_mode:
            content = process_wiki_links(content)
        
        html = md.convert(content)
        return _sanitize_markdown_html(html)
        
    except Exception as e:
        current_app.logger.error(f"Markdown processing error: {e}")
        import html as html_module
        return html_module.escape(content).replace('\n', '<br>\n')


def process_wiki_links(content):
    """
    Konvertiert Wiki-Link Syntax [[Seitenname]] zu Markdown-Links.
    
    Args:
        content: Markdown-Text mit Wiki-Links
    
    Returns:
        Markdown-Text mit konvertierten Links
    """
    try:
        from app.models.wiki import WikiPage
        from app import db
        
        pattern = r'\[\[([^\]]+)\]\]'
        
        def replace_wiki_link(match):
            link_text = match.group(1)
            
            if '|' in link_text:
                page_name, display_text = link_text.split('|', 1)
                page_name = page_name.strip()
                display_text = display_text.strip()
            else:
                page_name = link_text.strip()
                display_text = page_name
            
            slug = WikiPage.slugify(page_name)
            
            wiki_page = WikiPage.query.filter(
                db.func.lower(WikiPage.slug) == db.func.lower(slug)
            ).first()
            
            if wiki_page:
                return f'[{display_text}](/wiki/view/{wiki_page.slug})'
            else:
                return f'[{display_text}](/wiki/view/{slug})'
        
        content = re.sub(pattern, replace_wiki_link, content)
        
        return content
        
    except Exception as e:
        current_app.logger.error(f"Wiki link processing error: {e}")
        return re.sub(r'\[\[([^\]]+)\]\]', r'\1', content)
