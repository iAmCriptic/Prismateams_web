#!/usr/bin/env python3
# Downloads local vendor assets for Excalidraw, React, ReactDOM, Socket.IO,
# and all Excalidraw lazy-loaded webpack chunks (required for menus/dialogs to work).

import os
import re
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(BASE_DIR, 'app', 'static', 'vendor')
EXCALIDRAW_VERSION = '0.17.6'
EXCALIDRAW_DIST_URL = f'https://unpkg.com/@excalidraw/excalidraw@{EXCALIDRAW_VERSION}/dist/'

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
        f'{EXCALIDRAW_DIST_URL}excalidraw.production.min.js',
        os.path.join(VENDOR_DIR, 'excalidraw', 'excalidraw.production.min.js'),
    ),
    (
        'https://cdn.socket.io/4.7.5/socket.io.min.js',
        os.path.join(VENDOR_DIR, 'socket.io', 'socket.io.min.js'),
    ),
]


def _download(url, target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as resp, open(target_path, 'wb') as f:
        data = resp.read()
        f.write(data)
    return len(data)


def download_vendor_assets():
    print('Checking Excalidraw vendor assets...')
    for url, target_path in ASSETS:
        if os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
            print(f'  OK (exists): {os.path.relpath(target_path, BASE_DIR)}')
            continue
        print(f'  Downloading: {url}')
        try:
            size = _download(url, target_path)
            print(f'  Downloaded {os.path.relpath(target_path, BASE_DIR)} ({size} bytes)')
        except Exception as err:
            print(f'  Warning: Download failed for {url}: {err}', file=sys.stderr)


def find_chunk_ids(js_path):
    with open(js_path, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = r'\{([0-9]+:\"[a-f0-9]+\"(?:,[0-9]+:\"[a-f0-9]+\")*)\}\[e\]\+\".js\"'
    chunks = {}
    for match in re.findall(pattern, content):
        for chunk_id, hash_val in re.findall(r'([0-9]+):\"([a-f0-9]+)\"', match):
            chunks[chunk_id] = hash_val
    return chunks


def download_excalidraw_chunks():
    excalidraw_dir = os.path.join(VENDOR_DIR, 'excalidraw')
    js_path = os.path.join(excalidraw_dir, 'excalidraw.production.min.js')
    if not os.path.exists(js_path):
        print('  Excalidraw main bundle not found, skipping chunk download.')
        return
    chunks = find_chunk_ids(js_path)
    print(f'Found {len(chunks)} webpack chunks in Excalidraw bundle.')
    downloaded = skipped = failed = 0
    for chunk_id, hash_val in sorted(chunks.items(), key=lambda x: int(x[0])):
        filename = f'{chunk_id}.{hash_val}.chunk.js'
        target = os.path.join(excalidraw_dir, filename)
        if os.path.exists(target) and os.path.getsize(target) > 50:
            skipped += 1
            continue
        url = EXCALIDRAW_DIST_URL + filename
        try:
            size = _download(url, target)
            print(f'  Downloaded chunk: {filename} ({size} bytes)')
            downloaded += 1
        except Exception as e:
            print(f'  Failed chunk {filename}: {e}', file=sys.stderr)
            failed += 1
    print(f'Chunks: {downloaded} new, {skipped} cached, {failed} failed.')


if __name__ == '__main__':
    download_vendor_assets()
    download_excalidraw_chunks()
    print('All assets ready.')
