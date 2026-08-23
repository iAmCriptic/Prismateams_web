#!/usr/bin/env python3
# Downloads local vendor assets for Excalidraw 0.18.1 (ESM dist/prod),
# React, ReactDOM, Socket.IO, lazy-loaded chunks, fonts, locales, and data files.

import os
import re
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(BASE_DIR, 'app', 'static', 'vendor')
EXCALIDRAW_VERSION = '0.18.1'
EXCALIDRAW_DIST_URL = f'https://unpkg.com/@excalidraw/excalidraw@{EXCALIDRAW_VERSION}/dist/prod/'
EXCALIDRAW_PROD_DIR = os.path.join(VENDOR_DIR, 'excalidraw', 'prod')
LEGACY_UMD = os.path.join(VENDOR_DIR, 'excalidraw', 'excalidraw.production.min.js')

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
        'https://cdn.socket.io/4.7.5/socket.io.min.js',
        os.path.join(VENDOR_DIR, 'socket.io', 'socket.io.min.js'),
    ),
]

CORE_FILES = ('index.js', 'index.css')


def _download(url, target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=120) as resp, open(target_path, 'wb') as f:
        data = resp.read()
        f.write(data)
    return len(data)


def _fetch_text(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode('utf-8', errors='replace')


def _ensure_file(relative_path, force=False):
    target = os.path.join(EXCALIDRAW_PROD_DIR, relative_path.replace('/', os.sep))
    if not force and os.path.exists(target) and os.path.getsize(target) > 0:
        return 'skipped', target
    url = EXCALIDRAW_DIST_URL + relative_path
    try:
        size = _download(url, target)
        print(f'  Downloaded: {relative_path} ({size} bytes)')
        return 'downloaded', target
    except Exception as err:
        print(f'  Failed: {relative_path} — {err}', file=sys.stderr)
        return 'failed', target


def _parse_unpkg_links(html_text, base_url):
    links = set()
    for match in re.findall(r'href="([^"]+)"', html_text):
        if match in ('../', './') or match.endswith('/'):
            continue
        if match.startswith('http'):
            links.add(match)
        else:
            links.add(base_url.rstrip('/') + '/' + match.lstrip('/'))
    return links


def _extract_files_from_listing(html_text, extensions=('.woff2', '.woff', '.json', '.js', '.bin')):
    files = set()
    for ext in extensions:
        pattern = r'([\w\-.]+' + re.escape(ext) + r')'
        for match in re.findall(pattern, html_text, re.I):
            if 'favicon' not in match.lower():
                files.add(match)
    return sorted(files)


def _list_unpkg_directory(relative_dir):
    url = EXCALIDRAW_DIST_URL + relative_dir.strip('/') + '/'
    try:
        listing = _fetch_text(url)
    except Exception as err:
        print(f'  Warning: Could not list {url}: {err}', file=sys.stderr)
        return [], []
    subdirs = []
    files = _extract_files_from_listing(listing)
    for match in re.findall(r'href="([^"]+/)"', listing):
        name = match.rstrip('/').split('/')[-1]
        if name and name not in ('..', '.') and 'favicon' not in name.lower():
            subdirs.append(name + '/')
    return subdirs, files


def download_excalidraw_fonts():
    font_subdirs = [
        'Assistant/', 'Cascadia/', 'ComicShanns/', 'Excalifont/',
        'Liberation/', 'Lilita/', 'Nunito/', 'Virgil/', 'Xiaolai/',
    ]
    print('Downloading fonts/...')
    failed = 0
    for subdir in font_subdirs:
        _, files = _list_unpkg_directory('fonts/' + subdir)
        for filename in files:
            status, _ = _ensure_file('fonts/' + subdir + filename)
            if status == 'failed':
                failed += 1
        nested_subdirs, _ = _list_unpkg_directory('fonts/' + subdir)
        for nested in nested_subdirs:
            _, nested_files = _list_unpkg_directory('fonts/' + subdir + nested)
            for filename in nested_files:
                status, _ = _ensure_file('fonts/' + subdir + nested + filename)
                if status == 'failed':
                    failed += 1
    if failed:
        print(f'  Fonts: {failed} failed (CDN fallback via EXCALIDRAW_ASSET_PATH remains available).')


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


def find_esm_imports(js_path):
    with open(js_path, 'r', encoding='utf-8') as f:
        content = f.read()
    imports = set()
    for match in re.findall(r'import\s*\(\s*["\'](\./[^"\']+)["\']\s*\)', content):
        imports.add(match.lstrip('./'))
    for match in re.findall(r'from\s*["\'](\./[^"\']+)["\']', content):
        imports.add(match.lstrip('./'))
    return sorted(imports)


def download_excalidraw_prod():
    print(f'Downloading Excalidraw {EXCALIDRAW_VERSION} dist/prod assets...')
    os.makedirs(EXCALIDRAW_PROD_DIR, exist_ok=True)

    for filename in CORE_FILES:
        _ensure_file(filename)

    index_js = os.path.join(EXCALIDRAW_PROD_DIR, 'index.js')
    if not os.path.exists(index_js):
        print('  index.js missing, skipping chunk discovery.')
        return

    chunks = find_esm_imports(index_js)
    print(f'Found {len(chunks)} ESM chunk imports in index.js.')
    downloaded = skipped = failed = 0
    for chunk in chunks:
        status, _ = _ensure_file(chunk)
        if status == 'downloaded':
            downloaded += 1
        elif status == 'skipped':
            skipped += 1
        else:
            failed += 1
    print(f'Chunks: {downloaded} new, {skipped} cached, {failed} failed.')

    for subdir in ('locales/', 'data/'):
        print(f'Downloading {subdir}...')
        _, files = _list_unpkg_directory(subdir)
        for filename in files:
            status, _ = _ensure_file(subdir + filename)
            if status == 'failed':
                failed += 1

    download_excalidraw_fonts()


def remove_legacy_umd():
    if os.path.exists(LEGACY_UMD):
        os.remove(LEGACY_UMD)
        print(f'Removed legacy UMD bundle: {os.path.relpath(LEGACY_UMD, BASE_DIR)}')


if __name__ == '__main__':
    download_vendor_assets()
    download_excalidraw_prod()
    remove_legacy_umd()
    print('All assets ready.')
