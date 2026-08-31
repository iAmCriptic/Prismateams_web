#!/usr/bin/env python3
"""Download youtubei.js browser bundle for the Media Downloader client module."""

import os
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(BASE_DIR, 'app', 'static', 'vendor', 'youtubei.js', 'browser.js')
VERSION = '18.0.0'
URL = f'https://unpkg.com/youtubei.js@{VERSION}/bundle/browser.js'


def main():
    from app.utils.media_downloader import ensure_youtubei_vendor

    try:
        from app import create_app
        app = create_app(os.environ.get('FLASK_ENV', 'production'))
        with app.app_context():
            path = ensure_youtubei_vendor(app)
    except Exception:
        target = os.path.join(BASE_DIR, 'app', 'static', 'vendor', 'youtubei.js', 'browser.js')
        if os.path.isfile(target) and os.path.getsize(target) > 100_000:
            print(f'youtubei.js bundle already present ({os.path.getsize(target)} bytes) -> {target}')
            return
        os.makedirs(os.path.dirname(target), exist_ok=True)
        req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        with open(target, 'wb') as f:
            f.write(data)
        path = target
    print(f'youtubei.js {VERSION} ready ({os.path.getsize(path)} bytes) -> {path}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Failed: {exc}', file=sys.stderr)
        sys.exit(1)
