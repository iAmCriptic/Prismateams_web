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
    if os.path.isfile(TARGET) and os.path.getsize(TARGET) > 100_000:
        print(f'youtubei.js bundle already present ({os.path.getsize(TARGET)} bytes) -> {TARGET}')
        return
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    with open(TARGET, 'wb') as f:
        f.write(data)
    print(f'Downloaded youtubei.js {VERSION} browser bundle ({len(data)} bytes) -> {TARGET}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Failed: {exc}', file=sys.stderr)
        sys.exit(1)
