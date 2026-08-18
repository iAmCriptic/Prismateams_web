#!/usr/bin/env python3
"""Downloads local vendor assets for Excalidraw, React, ReactDOM, and Socket.IO."""

import os
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(BASE_DIR, 'app', 'static', 'vendor')

ASSETS = [
    (
        'https://unpkg.com/react@18.3.1/umd/react.production.min.js',
        os.path.join(VENDOR_DIR, 'react', 'react.production.min.js'),
    ),
    (
        'https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js',
        os.path.join(VENDOR_DIR, 'react', 'react-dom.production.min.js'),
    ),
    (
        'https://unpkg.com/@excalidraw/excalidraw@0.17.6/dist/excalidraw.production.min.js',
        os.path.join(VENDOR_DIR, 'excalidraw', 'excalidraw.production.min.js'),
    ),
    (
        'https://cdn.socket.io/4.7.5/socket.io.min.js',
        os.path.join(VENDOR_DIR, 'socket.io', 'socket.io.min.js'),
    ),
]


def download_vendor_assets():
    print('Checking Excalidraw vendor assets...')
    for url, target_path in ASSETS:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
            print(f'Asset exists: {os.path.relpath(target_path, BASE_DIR)}')
            continue
        print(f'Downloading {url} -> {os.path.relpath(target_path, BASE_DIR)}...')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as resp, open(target_path, 'wb') as f:
                f.write(resp.read())
            print(f'Downloaded {os.path.relpath(target_path, BASE_DIR)}')
        except Exception as err:
            print(f'Warning: Download failed for {url}: {err}', file=sys.stderr)


if __name__ == '__main__':
    download_vendor_assets()
