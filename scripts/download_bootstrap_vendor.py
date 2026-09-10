#!/usr/bin/env python3
"""Download Bootstrap 5.3.2 + Icons 1.11.1 into app/static/vendor/ (committed)."""

import os
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(BASE_DIR, 'app', 'static', 'vendor')

ASSETS = [
    (
        'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
        os.path.join(VENDOR_DIR, 'bootstrap', 'bootstrap.min.css'),
    ),
    (
        'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
        os.path.join(VENDOR_DIR, 'bootstrap', 'bootstrap.bundle.min.js'),
    ),
    (
        'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.min.css',
        os.path.join(VENDOR_DIR, 'bootstrap-icons', 'bootstrap-icons.min.css'),
    ),
    (
        'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff2',
        os.path.join(VENDOR_DIR, 'bootstrap-icons', 'fonts', 'bootstrap-icons.woff2'),
    ),
    (
        'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff',
        os.path.join(VENDOR_DIR, 'bootstrap-icons', 'fonts', 'bootstrap-icons.woff'),
    ),
]


def _download(url, target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'PrismateamsVendor/1.0'})
    with urllib.request.urlopen(req, timeout=60) as resp, open(target_path, 'wb') as f:
        data = resp.read()
        f.write(data)
    return len(data)


def main():
    for url, path in ASSETS:
        size = _download(url, path)
        print(f'{size:8d}  {os.path.relpath(path, VENDOR_DIR)}')


if __name__ == '__main__':
    main()
