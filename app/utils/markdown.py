"""
Gemeinsame Markdown-Verarbeitungsfunktionen für Files und Wiki.
"""
import re
from flask import current_app


def process_markdown(content, wiki_mode=False):
    """
    Verarbeitet Markdown-Text zu HTML mit erweiterten Extensions.
    
    Args:
        content: Markdown-Text als String
        wiki_mode: Wenn True, werden Wiki-Links [[Seitenname]] verarbeitet
    
    Returns:
        Verarbeiteter HTML-String
    """
    try:
        import markdown
        
        # Helper-Funktion für custom fences
        def mermaid_formatter(source):
            return f'<div class="mermaid">{source}</div>'
        
        # Basis-Extensions (immer verfügbar)
        extensions = [
            'fenced_code',      # Code-Blöcke mit ```
            'codehilite',       # Syntax-Highlighting
            'nl2br',            # Zeilenumbrüche
            'toc',              # Table of Contents
            'footnotes',        # Fußnoten
            'def_list',         # Definitionslisten
            'attr_list',        # Attribute-Listen
            'abbr',             # Abkürzungen
            'tables',           # Standard Tabellen-Unterstützung
        ]
        
        # Extension-Konfiguration
        extension_configs = {}
        
        # Prüfe und füge pymdownx-Extensions hinzu, falls verfügbar
        try:
            import pymdownx
            # pymdownx ist verfügbar, füge erweiterte Extensions hinzu
            pymdownx_extensions = [
                'pymdownx.caret',   # Superscript: ^text^
                'pymdownx.tilde',   # Subscript: ~text~
                'pymdownx.superfences',  # Erweiterte Code-Blöcke
                'pymdownx.tables',  # Verbesserte Tabellen-Unterstützung
                'pymdownx.arithmatex'  # LaTeX-Formeln: $inline$ und $$block$$
            ]
            
            # Prüfe welche Extensions verfügbar sind
            available_pymdownx = []
            for ext in pymdownx_extensions:
                try:
                    # Versuche Extension zu importieren
                    ext_name = ext.replace('pymdownx.', '')
                    __import__(f'pymdownx.{ext_name}')
                    available_pymdownx.append(ext)
                except ImportError:
                    current_app.logger.debug(f"pymdownx extension {ext} nicht verfügbar")
            
            # Füge verfügbare Extensions hinzu
            extensions.extend(available_pymdownx)
            
            # Konfiguriere verfügbare Extensions
            if 'pymdownx.arithmatex' in available_pymdownx:
                extension_configs['pymdownx.arithmatex'] = {
                    'generic': True  # Nutzt MathJax/KaTeX im Frontend
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
            
            # Entferne fenced_code wenn superfences verfügbar ist (ersetzt es)
            if 'pymdownx.superfences' in available_pymdownx and 'fenced_code' in extensions:
                extensions.remove('fenced_code')
            
            # Entferne tables wenn pymdownx.tables verfügbar ist (ersetzt es)
            if 'pymdownx.tables' in available_pymdownx and 'tables' in extensions:
                extensions.remove('tables')
                
        except ImportError:
            # pymdownx ist nicht verfügbar, nutze Standard-Extensions
            current_app.logger.debug("pymdownx nicht verfügbar, nutze Standard-Markdown-Extensions")
        
        # Erstelle Markdown-Instanz
        md = markdown.Markdown(extensions=extensions, extension_configs=extension_configs)
        
        # Wenn Wiki-Modus, verarbeite Wiki-Links vor der Markdown-Konvertierung
        if wiki_mode:
            content = process_wiki_links(content)
        
        # Konvertiere Markdown zu HTML
        html = md.convert(content)
        
        return html
        
    except Exception as e:
        current_app.logger.error(f"Markdown processing error: {e}")
        # Fallback: Escape HTML und behalte Zeilenumbrüche
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
        
        # Pattern für [[Seitenname]] oder [[Seitenname|Anzeigetext]]
        pattern = r'\[\[([^\]]+)\]\]'
        
        def replace_wiki_link(match):
            link_text = match.group(1)
            
            # Prüfe ob Anzeigetext vorhanden: [[Seite|Text]]
            if '|' in link_text:
                page_name, display_text = link_text.split('|', 1)
                page_name = page_name.strip()
                display_text = display_text.strip()
            else:
                page_name = link_text.strip()
                display_text = page_name
            
            # Erstelle Slug aus Seitenname
            slug = WikiPage.slugify(page_name)
            
            # Suche nach Wiki-Seite (case-insensitive)
            wiki_page = WikiPage.query.filter(
                db.func.lower(WikiPage.slug) == db.func.lower(slug)
            ).first()
            
            if wiki_page:
                # Seite existiert - normaler Link
                return f'[{display_text}](/wiki/view/{wiki_page.slug})'
            else:
                # Seite existiert nicht - Link mit missing-Klasse (wird im Template markiert)
                return f'[{display_text}](/wiki/view/{slug})'
        
        # Ersetze alle Wiki-Links
        content = re.sub(pattern, replace_wiki_link, content)
        
        return content
        
    except Exception as e:
        current_app.logger.error(f"Wiki link processing error: {e}")
        # Bei Fehler: entferne einfach die doppelten Klammern
        return re.sub(r'\[\[([^\]]+)\]\]', r'\1', content)

