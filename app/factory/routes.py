"""Top-level app routes."""


import json
import os

from flask import Response, jsonify, make_response, request, url_for
from flask_login import current_user

from app.factory._util import asset_version as _asset_version

def register_app_routes(app):
    """App-level routes (manifest, service worker, robots, sitemap)."""
    @app.route('/manifest.json')
    def manifest():
        import json
        from flask import url_for
        from app.models.settings import SystemSettings
        
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else app.config.get('APP_NAME', 'Prismateams')
        
        # Standard Logo-URL
        logo_url = url_for('static', filename='img/logo.png')
        
        # Portal-Logo prüfen
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            logo_url = url_for('settings.portal_logo', filename=portal_logo_setting.value)
        
        manifest_path = os.path.join(app.static_folder, 'manifest.json')
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            manifest_data['name'] = portal_name
            manifest_data['short_name'] = portal_name[:12]  # short_name sollte max 12 Zeichen haben

            # Statusleisten-/PWA-Farbe an Dark/OLED anpassen
            theme_color = '#f0f2f5'
            from flask_login import current_user
            if getattr(current_user, 'is_authenticated', False):
                if getattr(current_user, 'oled_mode', False) and getattr(current_user, 'dark_mode', False):
                    theme_color = '#000000'
                elif getattr(current_user, 'dark_mode', False):
                    theme_color = '#1a1a1a'
            manifest_data['theme_color'] = theme_color
            manifest_data['background_color'] = theme_color
            
            # Logo in allen Icon-Einträgen aktualisieren
            for icon in manifest_data.get('icons', []):
                icon['src'] = logo_url
            
            # Logo auch in Screenshots aktualisieren (falls vorhanden)
            for screenshot in manifest_data.get('screenshots', []):
                screenshot['src'] = logo_url
            
            return jsonify(manifest_data)
        except:
            # Fallback: Statische Datei senden, aber trotzdem Portalnamen verwenden
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest_data = json.load(f)
                manifest_data['name'] = portal_name
                manifest_data['short_name'] = portal_name[:12]
                for icon in manifest_data.get('icons', []):
                    icon['src'] = logo_url
                return jsonify(manifest_data)
            except:
                return app.send_static_file('manifest.json')
    
    @app.route('/api/portal-info')
    def portal_info():
        """API-Endpoint für Portal-Informationen (für Service Worker)."""
        from flask import url_for
        from app.models.settings import SystemSettings
        
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        portal_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else app.config.get('APP_NAME', 'Prismateams')
        
        # Standard Logo-URL
        logo_url = url_for('static', filename='img/logo.png', _external=False)
        
        # Portal-Logo prüfen
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            logo_url = url_for('settings.portal_logo', filename=portal_logo_setting.value, _external=False)
        
        return jsonify({
            'name': portal_name,
            'logo': logo_url
        })
    
    @app.route('/sw.js')
    def service_worker():
        """Serve SW with release-bound cache name and no-cache headers."""
        from flask import Response, make_response

        sw_path = os.path.join(app.static_folder, 'sw.js')
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()

        release = str(app.config.get('ABOUT_RELEASE_VERSION') or 'v0.0.0').strip().lstrip('vV') or '0.0.0'
        build = str(app.config.get('ABOUT_BUILD_NUMBER') or '').strip()
        cache_name = f"team-portal-v{release}"
        if build:
            cache_name = f"{cache_name}-{build}"

        content = content.replace('__SW_CACHE_NAME__', cache_name)
        content = content.replace('__SW_ASSET_VERSION__', _asset_version(app))

        response = make_response(Response(content, mimetype='application/javascript'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.route('/assets/core.css')
    def core_css():
        """One stylesheet for always-on chrome CSS (P04)."""
        from flask import Response, make_response, request
        from app.utils.static_packs import build_core_css

        body, etag = build_core_css(app.static_folder)
        response = make_response(Response(body, mimetype='text/css; charset=utf-8'))
        response.set_etag(etag)
        if app.debug:
            response.headers['Cache-Control'] = 'no-cache'
        else:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response.make_conditional(request)

    @app.route('/robots.txt')
    def robots_txt():
        from flask import Response
        from app.utils.search_indexing import build_robots_txt
        response = Response(build_robots_txt(), mimetype='text/plain; charset=utf-8')
        response.headers['Cache-Control'] = 'public, max-age=300'
        return response

    @app.route('/sitemap.xml')
    def sitemap_xml():
        from flask import Response
        from app.utils.search_indexing import build_sitemap_xml
        response = Response(build_sitemap_xml(), mimetype='application/xml; charset=utf-8')
        response.headers['Cache-Control'] = 'public, max-age=300'
        return response
