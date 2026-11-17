"""Tests for Excalidraw CSP headers and integration."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

import pytest


def test_csp_headers_allow_excalidraw_and_web_tools(client):
    """Test that Content-Security-Policy allows esm.sh, unpkg, and web tool embeds."""
    resp = client.get('/login', follow_redirects=True)
    assert resp.status_code == 200
    csp = resp.headers.get('Content-Security-Policy', '')
    assert csp, "Content-Security-Policy header must be present"

    # script-src allows esm.sh and unpkg.com
    assert 'https://esm.sh' in csp
    assert 'https://unpkg.com' in csp

    # style-src allows unpkg and esm.sh
    assert 'style-src' in csp
    assert 'https://unpkg.com' in csp

    # font-src allows unpkg and esm.sh
    assert 'font-src' in csp

    # frame-src allows http: and https: for web embed tool
    assert 'frame-src' in csp
    assert 'https:' in csp
    assert 'http:' in csp
