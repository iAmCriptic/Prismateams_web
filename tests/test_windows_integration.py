"""Tests for Windows native integration API endpoints."""

import pytest
from app import db
from app.models.user import User
from app.models.api_token import ApiToken
from app.models.app_password import AppPassword
from app.models.settings import SystemSettings


@pytest.fixture
def auth_user(client):
    user = User(
        email="windows_test@example.com",
        first_name="Windows",
        last_name="Tester",
        is_active=True,
        is_admin=True,
    )
    user.set_password("Secret1234!")
    db.session.add(user)
    db.session.commit()

    token_obj, raw_token = ApiToken.create_token(user.id, name="Test Token")
    return user, raw_token


def test_windows_webdav_credentials_token_auth(client, auth_user):
    user, raw_token = auth_user

    # Enable module_files and webdav
    s_files = SystemSettings(key="module_files_enabled", value="true")
    s_webdav = SystemSettings(key="files_webdav_enabled", value="true")
    db.session.add_all([s_files, s_webdav])
    db.session.commit()

    # Call POST /api/windows/webdav-credentials with Bearer token
    headers = {"Authorization": f"Bearer {raw_token}"}
    resp = client.post("/api/windows/webdav-credentials", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "username" in data
    assert "password" in data
    assert len(data["password"]) >= 8

    # Verify that the generated credentials verify in AppPassword
    assert AppPassword.verify_for_user(user.id, data["password"]) is not None


def test_windows_resolve_path(client, auth_user):
    user, raw_token = auth_user

    headers = {"Authorization": f"Bearer {raw_token}"}
    resp = client.get("/api/windows/resolve-path?path=P:\\Private\\TestDoc.docx", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["filename"] == "TestDoc.docx"
    assert data["extension"] == ".docx"
