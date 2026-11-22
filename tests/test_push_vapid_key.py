import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import db
from app.blueprints.api_modules.push import _normalize_vapid_public_key
from app.models.user import User
from scripts.generate_vapid_keys import generate_vapid_keys


def _decode_b64url(value: str) -> bytes:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded)


def test_generate_vapid_keys_produces_uncompressed_point():
    keys = generate_vapid_keys()
    raw = _decode_b64url(keys["public_key_b64"])
    assert len(raw) == 65
    assert raw[0] == 0x04


def test_normalize_vapid_public_key_all_formats():
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()

    raw_bytes = pub.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    expected_b64url = base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")

    der_spki = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    der_spki_b64url = base64.urlsafe_b64encode(der_spki).decode("ascii").rstrip("=")

    pem_str = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    pem_escaped = pem_str.replace("\n", "\\n")

    assert _normalize_vapid_public_key(expected_b64url) == expected_b64url
    assert _normalize_vapid_public_key(f'"{expected_b64url}"') == expected_b64url
    assert _normalize_vapid_public_key(der_spki_b64url) == expected_b64url
    assert _normalize_vapid_public_key(pem_str) == expected_b64url
    assert _normalize_vapid_public_key(pem_escaped) == expected_b64url


def test_api_push_vapid_key_endpoint_normalizes_der_spki(app, client):
    user = User(
        email="vapid_test@example.com",
        first_name="Vapid",
        last_name="Tester",
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user.set_password("Password123!@#")
    db.session.add(user)
    db.session.commit()

    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()
    der_spki = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    der_spki_b64url = base64.urlsafe_b64encode(der_spki).decode("ascii").rstrip("=")
    raw_expected = base64.urlsafe_b64encode(
        pub.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
    ).decode("ascii").rstrip("=")

    app.config["VAPID_PUBLIC_KEY"] = der_spki_b64url

    login_resp = client.post(
        "/login",
        data={"email": "vapid_test@example.com", "password": "Password123!@#"},
        follow_redirects=False,
    )
    assert login_resp.status_code in (200, 302)

    resp = client.get("/api/push/vapid-key")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["public_key"] == raw_expected
    assert len(_decode_b64url(data["public_key"])) == 65
