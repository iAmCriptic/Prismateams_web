"""Auth split-screen branding (login/register)."""



from __future__ import annotations



AUTH_BRAND_LOGO_POSITIONS = (

    'top-left',

    'top-center',

    'top-right',

    'middle-left',

    'middle-center',

    'middle-right',

    'bottom-left',

    'bottom-center',

    'bottom-right',

)



_DEFAULT_POSITION = 'middle-center'

_DEFAULT_ACCENT = '#0d6efd'

_DEFAULT_BRAND_COLOR = '#667eea'

_DEFAULT_FORM_GRADIENT = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'





def _read_setting(key: str) -> str | None:

    try:

        from app.models.settings import SystemSettings



        row = SystemSettings.query.filter_by(key=key).first()

        if row and row.value is not None:

            value = str(row.value).strip()

            return value or None

    except Exception:

        pass

    return None





def _normalize_hex_color(value: str | None, fallback: str) -> str:

    if not value:

        return fallback

    raw = str(value).strip()

    if not raw:

        return fallback

    if not raw.startswith('#'):

        raw = f'#{raw.lstrip("#")}'

    if len(raw) not in (4, 7):

        return fallback

    return raw





def normalize_auth_brand_logo_position(value: str | None) -> str:

    if value and value in AUTH_BRAND_LOGO_POSITIONS:

        return value

    return _DEFAULT_POSITION





def get_auth_branding_context() -> dict:

    accent = _normalize_hex_color(_read_setting('default_accent_color'), _DEFAULT_ACCENT)



    return {

        'default_accent_color': accent,

        'auth_brand_image_filename': _read_setting('auth_brand_image'),

        'auth_brand_color': _normalize_hex_color(

            _read_setting('auth_brand_color'),

            _DEFAULT_BRAND_COLOR,

        ),

        'auth_brand_logo_position': normalize_auth_brand_logo_position(

            _read_setting('auth_brand_logo_position')

        ),

        'auth_brand_text': _read_setting('auth_brand_text') or '',

        'auth_form_gradient': _read_setting('color_gradient') or _DEFAULT_FORM_GRADIENT,

    }

