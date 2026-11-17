"""DGUV V3 examination submodule: scan, measure, OTP, signed PDF."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

from flask import jsonify, render_template, request, send_file, session
from flask_login import current_user, login_required

from app import db
from app.blueprints.inventory._bp import DEFAULT_DGUV_INTERVAL_MONTHS, inventory_bp
from app.blueprints.inventory.helpers import (
    _create_product_document,
    _lookup_product_or_set_by_scan,
    _normalize_scanner_code,
    _serialize_product_api,
    inventory_number_display,
    product_owner_display,
)
from app.models.inventory import DguvExamination, Product, ProductDocument
from app.utils.access_control import check_module_access
from app.utils.common import portal_now_naive
from app.utils.dates import compute_dguv_next
from app.utils.dguv_pdf import generate_dguv_exam_pdf
from app.utils.dguv_signing import (
    DEFAULT_R_ISO_LIMIT,
    DEFAULT_R_PE_LIMIT,
    OTP_VALIDITY_DAYS,
    certificate_status,
    has_signing_certificate,
    sign_pdf_bytes,
)
from app.utils.email_sender import (
    generate_confirmation_code,
    render_and_send_portal_email,
    _mail_configured,
    _portal_name,
)
from app.utils.i18n import translate

logger = logging.getLogger(__name__)

SESSION_OTP_KEY = 'dguv_exam_otp'
OTP_TTL_MINUTES = 10
OVERALL_RESULTS = frozenset({'passed', 'deficient', 'failed'})


def _otp_window_active(user) -> bool:
    until = getattr(user, 'dguv_signature_confirmed_until', None)
    if not until:
        return False
    return portal_now_naive() < until


def _extend_otp_window(user) -> None:
    user.dguv_signature_confirmed_until = portal_now_naive() + timedelta(days=OTP_VALIDITY_DAYS)


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_float(value) -> Optional[float]:
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(',', '.')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on', 'passed', 'bestanden'):
        return True
    if text in ('0', 'false', 'no', 'off', 'failed', 'nicht bestanden'):
        return False
    return None


def _validate_exam_payload(data: dict) -> tuple[Optional[dict], Optional[str]]:
    product_id = data.get('product_id')
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return None, translate('inventory.dguv_exam.errors.product_required')

    product = Product.query.get(product_id)
    if not product:
        return None, translate('inventory.dguv_exam.errors.product_not_found')

    device_name = (data.get('device_name') or '').strip()
    if not device_name:
        return None, translate('inventory.dguv_exam.errors.device_required')

    visual_ok = _parse_bool(data.get('visual_ok'))
    function_ok = _parse_bool(data.get('function_ok'))
    if visual_ok is None:
        return None, translate('inventory.dguv_exam.errors.visual_required')
    if function_ok is None:
        return None, translate('inventory.dguv_exam.errors.function_required')

    overall = (data.get('overall_result') or '').strip().lower()
    if overall not in OVERALL_RESULTS:
        return None, translate('inventory.dguv_exam.errors.result_required')

    try:
        interval = int(data.get('interval_months') or DEFAULT_DGUV_INTERVAL_MONTHS)
    except (TypeError, ValueError):
        return None, translate('inventory.dguv_exam.errors.interval_invalid')
    if interval < 1 or interval > 120:
        return None, translate('inventory.dguv_exam.errors.interval_invalid')

    exam_date = _parse_date(data.get('exam_date')) or portal_now_naive().date()
    next_exam = compute_dguv_next(exam_date, interval)
    if not next_exam:
        return None, translate('inventory.dguv_exam.errors.interval_invalid')

    r_pe_limit = _parse_float(data.get('r_pe_limit'))
    if r_pe_limit is None:
        r_pe_limit = DEFAULT_R_PE_LIMIT
    r_iso_limit = _parse_float(data.get('r_iso_limit'))
    if r_iso_limit is None:
        r_iso_limit = DEFAULT_R_ISO_LIMIT

    r_pe = _parse_float(data.get('r_pe_ohm'))
    r_iso = _parse_float(data.get('r_iso_mohm'))
    r_pe_pass = None if r_pe is None else (r_pe <= r_pe_limit)
    r_iso_pass = None if r_iso is None else (r_iso >= r_iso_limit)

    examiner_name = (getattr(current_user, 'full_name', None) or '').strip()
    if not examiner_name:
        examiner_name = (getattr(current_user, 'email', None) or 'Prüfer').strip()
    examiner_email = (data.get('examiner_email') or getattr(current_user, 'email', None) or '').strip()
    if not examiner_email:
        return None, translate('inventory.dguv_exam.errors.email_required')

    payload = {
        'product_id': product.id,
        'examiner_user_id': current_user.id,
        'examiner_name': examiner_name,
        'examiner_email': examiner_email,
        'device_name': device_name,
        'device_serial': (data.get('device_serial') or '').strip() or None,
        'device_calibration_date': _parse_date(data.get('device_calibration_date')),
        'visual_ok': visual_ok,
        'r_pe_ohm': r_pe,
        'r_iso_mohm': r_iso,
        'i_pe_ma': _parse_float(data.get('i_pe_ma')),
        'i_touch_ma': _parse_float(data.get('i_touch_ma')),
        'function_ok': function_ok,
        'r_pe_limit': r_pe_limit,
        'r_iso_limit': r_iso_limit,
        'r_pe_pass': r_pe_pass,
        'r_iso_pass': r_iso_pass,
        'overall_result': overall,
        'interval_months': interval,
        'exam_date': exam_date,
        'next_exam_date': next_exam,
    }
    return payload, None


def _payload_for_session(payload: dict) -> dict:
    """JSON-serialisable copy for Flask session."""
    out = dict(payload)
    for key in ('exam_date', 'next_exam_date', 'device_calibration_date'):
        val = out.get(key)
        if isinstance(val, date):
            out[key] = val.isoformat()
    return out


def _payload_from_session(raw: dict) -> dict:
    out = dict(raw)
    for key in ('exam_date', 'next_exam_date', 'device_calibration_date'):
        if out.get(key):
            out[key] = _parse_date(out[key])
    return out


def _send_exam_otp(email: str, code: str) -> bool:
    portal = _portal_name()
    subject = translate('inventory.dguv_exam.otp.email_subject', portal=portal)
    plain = translate('inventory.dguv_exam.otp.email_body', code=code, minutes=OTP_TTL_MINUTES)
    if not _mail_configured():
        logger.warning('DGUV OTP mail not configured; code generated for %s', email)
        return False
    return bool(render_and_send_portal_email(
        subject=subject,
        recipients=[email],
        template_name='emails/dguv_exam_otp.html',
        body_text=plain,
        confirmation_code=code,
        minutes=OTP_TTL_MINUTES,
        subject_title=translate('inventory.dguv_exam.otp.email_title'),
        intro=translate('inventory.dguv_exam.otp.email_intro'),
    ))


def _pdf_data_from_payload(payload: dict, product: Product, *, signed_at: datetime) -> dict[str, Any]:
    from app.utils.dguv_signing import _portal_org_name

    return {
        'product_name': product.name,
        'inventory_number': inventory_number_display(product),
        'serial_number': product.serial_number,
        'owner_display': product_owner_display(product),
        'location': product.location,
        'length': product.length,
        'folder_name': product.folder.name if product.folder else None,
        'examiner_name': payload['examiner_name'],
        'examiner_email': payload['examiner_email'],
        'device_name': payload['device_name'],
        'device_serial': payload.get('device_serial'),
        'device_calibration_date': payload.get('device_calibration_date'),
        'visual_ok': payload['visual_ok'],
        'r_pe_ohm': payload.get('r_pe_ohm'),
        'r_iso_mohm': payload.get('r_iso_mohm'),
        'i_pe_ma': payload.get('i_pe_ma'),
        'i_touch_ma': payload.get('i_touch_ma'),
        'function_ok': payload['function_ok'],
        'r_pe_limit': payload['r_pe_limit'],
        'r_iso_limit': payload['r_iso_limit'],
        'r_pe_pass': payload.get('r_pe_pass'),
        'r_iso_pass': payload.get('r_iso_pass'),
        'overall_result': payload['overall_result'],
        'interval_months': payload['interval_months'],
        'exam_date': payload['exam_date'],
        'next_exam_date': payload['next_exam_date'],
        'signed_at': signed_at,
        'stamp_org': _portal_org_name(),
    }


def _store_signed_pdf(product: Product, pdf_bytes: bytes, examiner_user_id: int) -> ProductDocument:
    from flask import current_app

    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_documents')
    os.makedirs(upload_dir, exist_ok=True)
    stamp = portal_now_naive().strftime('%Y%m%d_%H%M%S')
    inv = inventory_number_display(product).replace('/', '-').replace('\\', '-')
    filename = f'DGUV_V3_{inv}_{stamp}.pdf'
    abs_path = os.path.abspath(os.path.join(upload_dir, filename))
    with open(abs_path, 'wb') as fh:
        fh.write(pdf_bytes)
    return _create_product_document(
        product_id=product.id,
        file_type='dguv',
        uploaded_by=examiner_user_id,
        file_path=abs_path,
        file_name=filename,
        file_size=len(pdf_bytes),
    )


@inventory_bp.route('/dguv-exam')
@login_required
@check_module_access('module_inventory')
def dguv_exam():
    """DGUV V3 Prüfung: Scan + Messwerte + FES."""
    recent_devices = (
        db.session.query(
            DguvExamination.device_name,
            DguvExamination.device_serial,
            DguvExamination.device_calibration_date,
        )
        .order_by(DguvExamination.id.desc())
        .limit(40)
        .all()
    )
    seen = set()
    devices = []
    for name, serial, cal in recent_devices:
        key = (name or '', serial or '')
        if key in seen:
            continue
        seen.add(key)
        devices.append({
            'name': name,
            'serial': serial or '',
            'calibration_date': cal.isoformat() if cal else '',
        })
        if len(devices) >= 10:
            break

    return render_template(
        'inventory/dguv_exam.html',
        examiner_name=getattr(current_user, 'full_name', None) or '',
        examiner_email=getattr(current_user, 'email', None) or '',
        signing_ready=has_signing_certificate(),
        otp_window_active=_otp_window_active(current_user),
        otp_window_days=OTP_VALIDITY_DAYS,
        recent_devices=devices,
        default_interval=DEFAULT_DGUV_INTERVAL_MONTHS,
        r_pe_limit=DEFAULT_R_PE_LIMIT,
        r_iso_limit=DEFAULT_R_ISO_LIMIT,
    )


@inventory_bp.route('/api/dguv-exam/product', methods=['GET', 'POST'])
@login_required
@check_module_access('module_inventory')
def api_dguv_exam_product():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        code = _normalize_scanner_code(
            data.get('code') or data.get('qr_code') or request.form.get('code') or ''
        )
    else:
        code = _normalize_scanner_code(request.args.get('code') or '')

    if not code:
        return jsonify({'ok': False, 'error': translate('inventory.errors.qr_data_required')}), 400

    product, product_set = _lookup_product_or_set_by_scan(code)
    if product_set and not product:
        return jsonify({
            'ok': False,
            'type': 'set',
            'error': translate('inventory.dguv_exam.errors.scan_set'),
        }), 400
    if not product:
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.product_not_found')}), 404

    return jsonify({'ok': True, 'product': _serialize_product_api(product)})


@inventory_bp.route('/api/dguv-exam/prepare', methods=['POST'])
@login_required
@check_module_access('module_inventory')
def api_dguv_exam_prepare():
    if not has_signing_certificate():
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.no_certificate')}), 400

    data = request.get_json(silent=True) or {}
    payload, err = _validate_exam_payload(data)
    if err:
        logger.info(
            'DGUV prepare validation failed: %s keys=%s',
            err,
            sorted(str(k) for k in data.keys()),
        )
        return jsonify({'ok': False, 'error': err}), 400

    session_payload = _payload_for_session(payload)
    skip_otp = _otp_window_active(current_user)

    if skip_otp:
        # Keep a short-lived draft; complete will skip OTP check
        expires = portal_now_naive() + timedelta(minutes=OTP_TTL_MINUTES)
        session[SESSION_OTP_KEY] = {
            'code': None,
            'otp_required': False,
            'expires': expires.isoformat(),
            'payload': session_payload,
            'payload_hash': hashlib.sha256(json.dumps(session_payload, sort_keys=True).encode()).hexdigest(),
        }
        session.modified = True
        return jsonify({
            'ok': True,
            'otp_required': False,
            'mail_sent': False,
            'examiner_email': payload['examiner_email'],
            'hint': translate('inventory.dguv_exam.otp.window_active'),
        })

    code = generate_confirmation_code()
    expires = portal_now_naive() + timedelta(minutes=OTP_TTL_MINUTES)
    session[SESSION_OTP_KEY] = {
        'code': code,
        'otp_required': True,
        'expires': expires.isoformat(),
        'payload': session_payload,
        'payload_hash': hashlib.sha256(json.dumps(session_payload, sort_keys=True).encode()).hexdigest(),
    }
    session.modified = True

    mailed = _send_exam_otp(payload['examiner_email'], code)
    resp = {
        'ok': True,
        'otp_required': True,
        'mail_sent': mailed,
        'expires_in_minutes': OTP_TTL_MINUTES,
        'examiner_email': payload['examiner_email'],
        'hint': None if mailed else translate('inventory.dguv_exam.otp.mail_not_configured'),
    }
    try:
        from flask import current_app
        if not mailed and current_app.debug:
            resp['dev_otp'] = code
    except Exception:
        pass
    return jsonify(resp)


@inventory_bp.route('/api/dguv-exam/complete', methods=['POST'])
@login_required
@check_module_access('module_inventory')
def api_dguv_exam_complete():
    if not has_signing_certificate():
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.no_certificate')}), 400

    data = request.get_json(silent=True) or {}
    otp = str(data.get('otp') or data.get('code') or '').strip()
    pending = session.get(SESSION_OTP_KEY) or {}
    if not pending or not pending.get('payload'):
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.otp_missing')}), 400

    try:
        expires = datetime.fromisoformat(pending['expires'])
    except (TypeError, ValueError):
        expires = None
    if not expires or portal_now_naive() > expires:
        session.pop(SESSION_OTP_KEY, None)
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.otp_expired')}), 400

    otp_required = pending.get('otp_required', True)
    if otp_required:
        if not pending.get('code'):
            return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.otp_missing')}), 400
        if otp != str(pending['code']):
            return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.otp_invalid')}), 400
    elif not _otp_window_active(current_user):
        # Window expired between prepare and complete
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.otp_expired')}), 400

    payload = _payload_from_session(pending['payload'])
    if payload.get('examiner_user_id') != current_user.id:
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.otp_invalid')}), 403

    product = Product.query.get(payload['product_id'])
    if not product:
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.product_not_found')}), 404

    now = portal_now_naive()
    pdf_data = _pdf_data_from_payload(payload, product, signed_at=now)
    try:
        unsigned = generate_dguv_exam_pdf(pdf_data)
        signed_pdf, sig_serial = sign_pdf_bytes(
            unsigned,
            reason=f"DGUV V3 Prüfung {inventory_number_display(product)}",
            location=_portal_name(),
            contact_info=payload['examiner_email'],
            examiner_name=payload['examiner_name'],
            examiner_email=payload['examiner_email'],
        )
    except Exception as exc:
        logger.exception('DGUV PDF/sign failed: %s', exc)
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.sign_failed')}), 500

    sha = hashlib.sha256(signed_pdf).hexdigest()
    try:
        doc = _store_signed_pdf(product, signed_pdf, current_user.id)
        db.session.flush()

        exam = DguvExamination(
            product_id=product.id,
            examiner_user_id=payload['examiner_user_id'],
            examiner_name=payload['examiner_name'],
            examiner_email=payload['examiner_email'],
            device_name=payload['device_name'],
            device_serial=payload.get('device_serial'),
            device_calibration_date=payload.get('device_calibration_date'),
            visual_ok=payload['visual_ok'],
            r_pe_ohm=payload.get('r_pe_ohm'),
            r_iso_mohm=payload.get('r_iso_mohm'),
            i_pe_ma=payload.get('i_pe_ma'),
            i_touch_ma=payload.get('i_touch_ma'),
            function_ok=payload['function_ok'],
            r_pe_limit=payload['r_pe_limit'],
            r_iso_limit=payload['r_iso_limit'],
            r_pe_pass=payload.get('r_pe_pass'),
            r_iso_pass=payload.get('r_iso_pass'),
            overall_result=payload['overall_result'],
            interval_months=payload['interval_months'],
            exam_date=payload['exam_date'],
            next_exam_date=payload['next_exam_date'],
            pdf_sha256=sha,
            pdf_document_id=doc.id,
            signature_serial=sig_serial,
            signed_at=now,
            otp_verified_at=now,
        )
        db.session.add(exam)

        product.dguv_last_check = payload['exam_date']
        product.dguv_interval_months = payload['interval_months']
        product.dguv_next_check = payload['next_exam_date']

        if otp_required:
            _extend_otp_window(current_user)

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception('DGUV persist failed: %s', exc)
        return jsonify({'ok': False, 'error': translate('inventory.dguv_exam.errors.save_failed')}), 500

    session.pop(SESSION_OTP_KEY, None)
    return jsonify({
        'ok': True,
        'examination_id': exam.id,
        'document_id': doc.id,
        'pdf_url': f"/inventory/dguv-exam/{exam.id}/pdf",
        'next_exam_date': payload['next_exam_date'].isoformat(),
        'sha256': sha,
        'otp_window_days': OTP_VALIDITY_DAYS,
    })


@inventory_bp.route('/dguv-exam/<int:exam_id>/pdf')
@login_required
@check_module_access('module_inventory')
def dguv_exam_pdf(exam_id: int):
    exam = DguvExamination.query.get_or_404(exam_id)
    doc = exam.pdf_document or (
        ProductDocument.query.get(exam.pdf_document_id) if exam.pdf_document_id else None
    )
    if not doc or not doc.file_path or not os.path.isfile(doc.file_path):
        return jsonify({'error': translate('inventory.dguv_exam.errors.pdf_missing')}), 404
    return send_file(
        doc.file_path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=doc.file_name or f'dguv_exam_{exam.id}.pdf',
    )


@inventory_bp.route('/api/dguv-exam/signing-status')
@login_required
@check_module_access('module_inventory')
def api_dguv_exam_signing_status():
    return jsonify({'ok': True, **certificate_status()})
