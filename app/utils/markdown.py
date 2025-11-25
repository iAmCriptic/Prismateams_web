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
        
        if wiki_mode:
            content = process_wiki_links(content)
        
        html = md.convert(content)
        
        return html
        
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

