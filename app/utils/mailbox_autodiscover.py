"""Automatic IMAP/SMTP server discovery and verification for 'Other' mailboxes."""

from __future__ import annotations

import imaplib
import re
import smtplib
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, Optional

import dns.resolver
import requests

_DOMAIN_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$')

# Known consumer and business mail provider presets keyed by email domain.
_KNOWN_DOMAIN_SETTINGS: dict[str, dict] = {
    'gmail.com': {
        'imap': ('imap.gmail.com', 993, True),
        'smtp': ('smtp.gmail.com', 587, True, False),
    },
    'googlemail.com': {
        'imap': ('imap.gmail.com', 993, True),
        'smtp': ('smtp.gmail.com', 587, True, False),
    },
    'outlook.com': {
        'imap': ('outlook.office365.com', 993, True),
        'smtp': ('smtp.office365.com', 587, True, False),
    },
    'hotmail.com': {
        'imap': ('outlook.office365.com', 993, True),
        'smtp': ('smtp.office365.com', 587, True, False),
    },
    'hotmail.de': {
        'imap': ('outlook.office365.com', 993, True),
        'smtp': ('smtp.office365.com', 587, True, False),
    },
    'live.com': {
        'imap': ('outlook.office365.com', 993, True),
        'smtp': ('smtp.office365.com', 587, True, False),
    },
    'live.de': {
        'imap': ('outlook.office365.com', 993, True),
        'smtp': ('smtp.office365.com', 587, True, False),
    },
    'msn.com': {
        'imap': ('outlook.office365.com', 993, True),
        'smtp': ('smtp.office365.com', 587, True, False),
    },
    'infomaniak.com': {
        'imap': ('mail.infomaniak.com', 993, True),
        'smtp': ('mail.infomaniak.com', 587, True, False),
    },
    'ik.me': {
        'imap': ('mail.infomaniak.com', 993, True),
        'smtp': ('mail.infomaniak.com', 587, True, False),
    },
    'etik.com': {
        'imap': ('mail.infomaniak.com', 993, True),
        'smtp': ('mail.infomaniak.com', 587, True, False),
    },
    'ionos.de': {
        'imap': ('imap.ionos.de', 993, True),
        'smtp': ('smtp.ionos.de', 587, True, False),
    },
    '1und1.de': {
        'imap': ('imap.1und1.de', 993, True),
        'smtp': ('smtp.1und1.de', 587, True, False),
    },
    '1and1.com': {
        'imap': ('imap.1and1.com', 993, True),
        'smtp': ('smtp.1and1.com', 587, True, False),
    },
    'gmx.de': {
        'imap': ('imap.gmx.net', 993, True),
        'smtp': ('mail.gmx.net', 587, True, False),
    },
    'gmx.net': {
        'imap': ('imap.gmx.net', 993, True),
        'smtp': ('mail.gmx.net', 587, True, False),
    },
    'gmx.at': {
        'imap': ('imap.gmx.net', 993, True),
        'smtp': ('mail.gmx.net', 587, True, False),
    },
    'gmx.ch': {
        'imap': ('imap.gmx.net', 993, True),
        'smtp': ('mail.gmx.net', 587, True, False),
    },
    'web.de': {
        'imap': ('imap.web.de', 993, True),
        'smtp': ('smtp.web.de', 587, True, False),
    },
    't-online.de': {
        'imap': ('secureimap.t-online.de', 993, True),
        'smtp': ('securesmtp.t-online.de', 587, True, False),
    },
    'yahoo.com': {
        'imap': ('imap.mail.yahoo.com', 993, True),
        'smtp': ('smtp.mail.yahoo.com', 587, True, False),
    },
    'yahoo.de': {
        'imap': ('imap.mail.yahoo.com', 993, True),
        'smtp': ('smtp.mail.yahoo.com', 587, True, False),
    },
    'ymail.com': {
        'imap': ('imap.mail.yahoo.com', 993, True),
        'smtp': ('smtp.mail.yahoo.com', 587, True, False),
    },
    'icloud.com': {
        'imap': ('imap.mail.me.com', 993, True),
        'smtp': ('smtp.mail.me.com', 587, True, False),
    },
    'me.com': {
        'imap': ('imap.mail.me.com', 993, True),
        'smtp': ('smtp.mail.me.com', 587, True, False),
    },
    'mac.com': {
        'imap': ('imap.mail.me.com', 993, True),
        'smtp': ('smtp.mail.me.com', 587, True, False),
    },
    'posteo.de': {
        'imap': ('posteo.de', 993, True),
        'smtp': ('posteo.de', 587, True, False),
    },
    'posteo.net': {
        'imap': ('posteo.de', 993, True),
        'smtp': ('posteo.de', 587, True, False),
    },
    'mailbox.org': {
        'imap': ('imap.mailbox.org', 993, True),
        'smtp': ('smtp.mailbox.org', 587, True, False),
    },
    'strato.de': {
        'imap': ('imap.strato.de', 993, True),
        'smtp': ('smtp.strato.de', 465, False, True),
    },
    'fastmail.com': {
        'imap': ('imap.fastmail.com', 993, True),
        'smtp': ('smtp.fastmail.com', 465, False, True),
    },
    'fastmail.fm': {
        'imap': ('imap.fastmail.com', 993, True),
        'smtp': ('smtp.fastmail.com', 465, False, True),
    },
    'zoho.com': {
        'imap': ('imap.zoho.com', 993, True),
        'smtp': ('smtp.zoho.com', 465, False, True),
    },
    'zoho.eu': {
        'imap': ('imap.zoho.eu', 993, True),
        'smtp': ('smtp.zoho.eu', 465, False, True),
    },
    'hetzner.de': {
        'imap': ('mail.your-server.de', 993, True),
        'smtp': ('mail.your-server.de', 587, True, False),
    },
    'your-server.de': {
        'imap': ('mail.your-server.de', 993, True),
        'smtp': ('mail.your-server.de', 587, True, False),
    },
}

# MX hostname substring -> (imap_host, imap_port, imap_ssl, smtp_host, smtp_port, smtp_tls, smtp_ssl)
_MX_PROVIDER_PATTERNS: list[tuple[str, tuple[str, int, bool], tuple[str, int, bool, bool]]] = [
    ('.mail.protection.outlook.com', ('outlook.office365.com', 993, True), ('smtp.office365.com', 587, True, False)),
    ('.google.com', ('imap.gmail.com', 993, True), ('smtp.gmail.com', 587, True, False)),
    ('.googlemail.com', ('imap.gmail.com', 993, True), ('smtp.gmail.com', 587, True, False)),
    ('infomaniak.ch', ('mail.infomaniak.com', 993, True), ('mail.infomaniak.com', 587, True, False)),
    ('kundenserver.de', ('imap.ionos.de', 993, True), ('smtp.ionos.de', 587, True, False)),
    ('.ionos.', ('imap.ionos.de', 993, True), ('smtp.ionos.de', 587, True, False)),
    ('your-server.de', ('mail.your-server.de', 993, True), ('mail.your-server.de', 587, True, False)),
    ('rzone.de', ('imap.strato.de', 993, True), ('smtp.strato.de', 465, False, True)),
    ('.ovh.net', ('ssl0.ovh.net', 993, True), ('ssl0.ovh.net', 587, True, False)),
    ('.migadu.com', ('imap.migadu.com', 993, True), ('smtp.migadu.com', 465, False, True)),
    ('.zoho.eu', ('imap.zoho.eu', 993, True), ('smtp.zoho.eu', 465, False, True)),
    ('.zoho.com', ('imap.zoho.com', 993, True), ('smtp.zoho.com', 465, False, True)),
    ('.hostinger.', ('imap.hostinger.com', 993, True), ('smtp.hostinger.com', 465, False, True)),
]


@dataclass(frozen=True)
class ImapCandidate:
    server: str
    port: int
    use_ssl: bool
    username: str
    source: str


@dataclass(frozen=True)
class SmtpCandidate:
    server: str
    port: int
    use_tls: bool
    use_ssl: bool
    username: str
    source: str


def _parse_email(email: str) -> tuple[str, str]:
    email = (email or '').strip()
    if '@' not in email or email.count('@') != 1:
        return '', ''
    local, domain = email.split('@', 1)
    local = local.strip()
    domain = domain.strip().lower().rstrip('.')
    if not local or not domain or not _DOMAIN_RE.match(domain):
        return '', ''
    return local, domain


def _resolve_username(pattern: Optional[str], email: str, local_part: str) -> str:
    raw = (pattern or '').strip()
    if not raw or raw == '%EMAILADDRESS%':
        return email
    if raw == '%EMAILLOCALPART%':
        return local_part
    return raw.replace('%EMAILADDRESS%', email).replace('%EMAILLOCALPART%', local_part)


def _fetch_autoconfig_candidates(
    email: str, local_part: str, domain: str, http_timeout: float = 3.0
) -> tuple[list[ImapCandidate], list[SmtpCandidate]]:
    """Query Thunderbird-compatible autoconfig endpoints and ISPDB."""
    urls = [
        f'https://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress={email}',
        f'https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml',
        f'https://autoconfig.thunderbird.net/v1.1/{domain}',
    ]
    imap_list: list[ImapCandidate] = []
    smtp_list: list[SmtpCandidate] = []

    for url in urls:
        try:
            resp = requests.get(url, timeout=http_timeout, headers={'Accept': 'application/xml,text/xml'})
            if resp.status_code != 200 or not resp.text:
                continue
            root = ET.fromstring(resp.text)
        except Exception:
            continue

        for inc in root.findall('.//incomingServer'):
            if (inc.attrib.get('type') or '').lower() != 'imap':
                continue
            host = (inc.findtext('hostname') or '').strip()
            port_raw = (inc.findtext('port') or '').strip()
            sock = (inc.findtext('socketType') or 'SSL').strip().upper()
            user = _resolve_username(inc.findtext('username'), email, local_part)
            if not host:
                continue
            try:
                port = int(port_raw) if port_raw else (993 if sock == 'SSL' else 143)
            except ValueError:
                port = 993
            imap_list.append(ImapCandidate(host, port, sock == 'SSL', user, 'autoconfig'))

        for out in root.findall('.//outgoingServer'):
            if (out.attrib.get('type') or '').lower() != 'smtp':
                continue
            host = (out.findtext('hostname') or '').strip()
            port_raw = (out.findtext('port') or '').strip()
            sock = (out.findtext('socketType') or 'STARTTLS').strip().upper()
            user = _resolve_username(out.findtext('username'), email, local_part)
            if not host:
                continue
            try:
                port = int(port_raw) if port_raw else (465 if sock == 'SSL' else 587)
            except ValueError:
                port = 587
            use_ssl = sock == 'SSL'
            use_tls = sock == 'STARTTLS'
            smtp_list.append(SmtpCandidate(host, port, use_tls, use_ssl, user, 'autoconfig'))

        if imap_list or smtp_list:
            break

    return imap_list, smtp_list


_TWO_LEVEL_TLDS = {'co.uk', 'org.uk', 'ac.uk', 'co.at', 'or.at', 'com.au', 'net.au', 'co.nz', 'com.br'}


def _extract_base_domain(host: str) -> str:
    """Return the registrable base domain for a hostname (e.g. mx1.mellowpark.de -> mellowpark.de)."""
    host = (host or '').strip().lower().rstrip('.')
    parts = [p for p in host.split('.') if p]
    if len(parts) <= 2:
        return host
    if '.'.join(parts[-2:]) in _TWO_LEVEL_TLDS and len(parts) >= 3:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def _dns_resolver(timeout: float = 2.5) -> dns.resolver.Resolver:
    res = dns.resolver.Resolver()
    res.timeout = timeout
    res.lifetime = timeout
    return res


def _doh_query(name: str, rtype: str, timeout: float = 2.5) -> list[str]:
    """Fallback DNS-over-HTTPS query when local UDP DNS is unavailable."""
    try:
        resp = requests.get(
            'https://dns.google/resolve',
            params={'name': name, 'type': rtype},
            timeout=timeout,
            headers={'Accept': 'application/dns-json'},
        )
        if resp.status_code != 200:
            return []
        payload = resp.json() or {}
        return [str(ans.get('data') or '').strip() for ans in (payload.get('Answer') or []) if ans.get('data')]
    except Exception:
        return []


def _resolve_mx_hosts(domain: str) -> list[str]:
    """Resolve MX hostnames for domain sorted by preference, with DoH fallback."""
    res = _dns_resolver()
    try:
        mx_records = sorted(res.resolve(domain, 'MX'), key=lambda r: r.preference)
        hosts = [str(mx.exchange).rstrip('.').lower() for mx in mx_records]
        return [h for h in hosts if h and h != '.']
    except Exception:
        pass

    parsed: list[tuple[int, str]] = []
    for raw in _doh_query(domain, 'MX'):
        parts = raw.split()
        if len(parts) == 2:
            try:
                pref = int(parts[0])
                host = parts[1].rstrip('.').lower()
                if host and host != '.':
                    parsed.append((pref, host))
            except ValueError:
                continue
    parsed.sort(key=lambda x: x[0])
    return [h for _, h in parsed]


def _resolve_srv_records(label: str) -> list[tuple[str, int]]:
    """Resolve SRV (target, port) pairs sorted by priority/weight, with DoH fallback."""
    res = _dns_resolver()
    try:
        answers = sorted(res.resolve(label, 'SRV'), key=lambda r: (r.priority, -r.weight))
        out: list[tuple[str, int]] = []
        for r in answers:
            target = str(r.target).rstrip('.').lower()
            if target and target != '.':
                out.append((target, int(r.port or 0)))
        return out
    except Exception:
        pass

    parsed: list[tuple[int, int, int, str]] = []
    for raw in _doh_query(label, 'SRV'):
        parts = raw.split()
        if len(parts) == 4:
            try:
                prio, weight, port = int(parts[0]), int(parts[1]), int(parts[2])
                target = parts[3].rstrip('.').lower()
                if target and target != '.':
                    parsed.append((prio, -weight, port, target))
            except ValueError:
                continue
    parsed.sort(key=lambda x: (x[0], x[1]))
    return [(target, port) for _, _, port, target in parsed]


def _fetch_srv_candidates(email: str, domain: str) -> tuple[list[ImapCandidate], list[SmtpCandidate]]:
    """Query RFC 6186 SRV records for IMAP and SMTP submission."""
    imap_list: list[ImapCandidate] = []
    smtp_list: list[SmtpCandidate] = []

    for label, use_ssl, default_port in [
        (f'_imaps._tcp.{domain}', True, 993),
        (f'_imap._tcp.{domain}', False, 143),
    ]:
        for target, port in _resolve_srv_records(label):
            imap_list.append(ImapCandidate(target, port or default_port, use_ssl, email, 'srv'))

    for label, use_tls, use_ssl, default_port in [
        (f'_submissions._tcp.{domain}', False, True, 465),
        (f'_submission._tcp.{domain}', True, False, 587),
    ]:
        for target, port in _resolve_srv_records(label):
            smtp_list.append(
                SmtpCandidate(target, port or default_port, use_tls, use_ssl, email, 'srv')
            )

    return imap_list, smtp_list


def _fetch_mx_candidates(
    email: str, local_part: str, domain: str
) -> tuple[list[ImapCandidate], list[SmtpCandidate]]:
    """Infer IMAP/SMTP hosts from MX records, including third-party hosting domains."""
    imap_list: list[ImapCandidate] = []
    smtp_list: list[SmtpCandidate] = []

    mx_hosts = _resolve_mx_hosts(domain)
    seen_mx_domains: set[str] = set()

    for mx_host in mx_hosts:
        matched = False
        for pattern, imap_cfg, smtp_cfg in _MX_PROVIDER_PATTERNS:
            if pattern in mx_host:
                imap_list.append(ImapCandidate(imap_cfg[0], imap_cfg[1], imap_cfg[2], email, 'mx'))
                smtp_list.append(
                    SmtpCandidate(smtp_cfg[0], smtp_cfg[1], smtp_cfg[2], smtp_cfg[3], email, 'mx')
                )
                matched = True
                break
        if matched:
            continue

        # Direct MX host (often the mail server itself on Plesk/Mailcow/Postfix/Dovecot setups)
        imap_list.append(ImapCandidate(mx_host, 993, True, email, 'mx'))
        smtp_list.append(SmtpCandidate(mx_host, 587, True, False, email, 'mx'))
        smtp_list.append(SmtpCandidate(mx_host, 465, False, True, email, 'mx'))

        # If MX points to a different hosting domain (e.g. alleins.de -> mx.mellowpark.de),
        # also inspect that hosting domain's presets, autoconfig, SRV, and standard mail subdomains.
        mx_domain = _extract_base_domain(mx_host)
        if mx_domain and mx_domain != domain and mx_domain not in seen_mx_domains:
            seen_mx_domains.add(mx_domain)

            preset = _KNOWN_DOMAIN_SETTINGS.get(mx_domain)
            if preset:
                ih, ip, issl = preset['imap']
                sh, sp, stls, sssl = preset['smtp']
                imap_list.append(ImapCandidate(ih, ip, issl, email, 'mx'))
                smtp_list.append(SmtpCandidate(sh, sp, stls, sssl, email, 'mx'))

            ac_imap, ac_smtp = _fetch_autoconfig_candidates(email, local_part, mx_domain)
            imap_list.extend(ac_imap)
            smtp_list.extend(ac_smtp)

            srv_imap, srv_smtp = _fetch_srv_candidates(email, mx_domain)
            imap_list.extend(srv_imap)
            smtp_list.extend(srv_smtp)

            for host_cand in (f'imap.{mx_domain}', f'mail.{mx_domain}', mx_domain):
                imap_list.append(ImapCandidate(host_cand, 993, True, email, 'mx'))
            for host_cand in (f'smtp.{mx_domain}', f'mail.{mx_domain}', mx_domain):
                smtp_list.append(SmtpCandidate(host_cand, 587, True, False, email, 'mx'))
                smtp_list.append(SmtpCandidate(host_cand, 465, False, True, email, 'mx'))

    return imap_list, smtp_list


def _dedup_imap(items: Iterable[ImapCandidate]) -> list[ImapCandidate]:
    seen: set[tuple[str, int, bool, str]] = set()
    out: list[ImapCandidate] = []
    for item in items:
        key = (item.server.lower(), item.port, item.use_ssl, item.username)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _dedup_smtp(items: Iterable[SmtpCandidate]) -> list[SmtpCandidate]:
    seen: set[tuple[str, int, bool, bool, str]] = set()
    out: list[SmtpCandidate] = []
    for item in items:
        key = (item.server.lower(), item.port, item.use_tls, item.use_ssl, item.username)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def discover_mail_candidates(email: str) -> tuple[list[ImapCandidate], list[SmtpCandidate]]:
    """Collect ordered, deduplicated IMAP and SMTP server candidates for an email address."""
    local_part, domain = _parse_email(email)
    if not domain:
        return [], []

    imap_all: list[ImapCandidate] = []
    smtp_all: list[SmtpCandidate] = []

    preset = _KNOWN_DOMAIN_SETTINGS.get(domain)
    if preset:
        ih, ip, issl = preset['imap']
        sh, sp, stls, sssl = preset['smtp']
        imap_all.append(ImapCandidate(ih, ip, issl, email, 'preset'))
        smtp_all.append(SmtpCandidate(sh, sp, stls, sssl, email, 'preset'))

    ac_imap, ac_smtp = _fetch_autoconfig_candidates(email, local_part, domain)
    imap_all.extend(ac_imap)
    smtp_all.extend(ac_smtp)

    srv_imap, srv_smtp = _fetch_srv_candidates(email, domain)
    imap_all.extend(srv_imap)
    smtp_all.extend(srv_smtp)

    mx_imap, mx_smtp = _fetch_mx_candidates(email, local_part, domain)
    imap_all.extend(mx_imap)
    smtp_all.extend(mx_smtp)

    # Common subdomain fallbacks
    imap_all.extend([
        ImapCandidate(f'imap.{domain}', 993, True, email, 'guess'),
        ImapCandidate(f'mail.{domain}', 993, True, email, 'guess'),
    ])
    smtp_all.extend([
        SmtpCandidate(f'smtp.{domain}', 587, True, False, email, 'guess'),
        SmtpCandidate(f'smtp.{domain}', 465, False, True, email, 'guess'),
        SmtpCandidate(f'mail.{domain}', 587, True, False, email, 'guess'),
        SmtpCandidate(f'mail.{domain}', 465, False, True, email, 'guess'),
    ])

    return _dedup_imap(imap_all)[:12], _dedup_smtp(smtp_all)[:12]


def test_imap_connection(
    server: str, port: int, use_ssl: bool, username: str, password: str, timeout: float = 6.0
) -> tuple[bool, bool, str]:
    """Test IMAP connection and login. Returns (ok, is_auth_error, error_message)."""
    try:
        if use_ssl:
            context = ssl.create_default_context()
            try:
                imap = imaplib.IMAP4_SSL(server, port, ssl_context=context, timeout=timeout)
            except TypeError:
                imap = imaplib.IMAP4_SSL(server, port, ssl_context=context)
                imap.sock.settimeout(timeout)
        else:
            try:
                imap = imaplib.IMAP4(server, port, timeout=timeout)
            except TypeError:
                imap = imaplib.IMAP4(server, port)
                imap.sock.settimeout(timeout)
        try:
            typ, _ = imap.login(username, password)
            if typ != 'OK':
                return False, True, f'Login failed: {typ}'
            imap.select('INBOX', readonly=True)
            return True, False, ''
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as e:
        return False, True, str(e)
    except Exception as e:
        return False, False, str(e)


def test_smtp_connection(
    server: str, port: int, use_tls: bool, use_ssl: bool, username: str, password: str, timeout: float = 6.0
) -> tuple[bool, bool, str]:
    """Test SMTP connection and login. Returns (ok, is_auth_error, error_message)."""
    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(server, port, timeout=timeout, context=context) as smtp:
                smtp.login(username, password)
        else:
            with smtplib.SMTP(server, port, timeout=timeout) as smtp:
                smtp.ehlo()
                if use_tls:
                    context = ssl.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(username, password)
        return True, False, ''
    except smtplib.SMTPAuthenticationError as e:
        return False, True, str(e)
    except Exception as e:
        return False, False, str(e)


def autodiscover_and_verify(email: str, password: str, timeout: float = 4.0) -> dict:
    """Discover IMAP/SMTP settings for an email address and verify login credentials."""
    local_part, domain = _parse_email(email)
    if not domain or not password:
        return {
            'success': False,
            'imap_ok': False,
            'smtp_ok': False,
            'auth_error': False,
            'imap': None,
            'smtp': None,
            'error': 'invalid_input',
        }

    imap_candidates, smtp_candidates = discover_mail_candidates(email)

    matched_imap: Optional[ImapCandidate] = None
    auth_imap_candidate: Optional[ImapCandidate] = None
    last_imap_err = ''
    for cand in imap_candidates:
        ok, is_auth, err = test_imap_connection(
            cand.server, cand.port, cand.use_ssl, cand.username, password, timeout=timeout
        )
        if ok:
            matched_imap = cand
            break
        if is_auth and auth_imap_candidate is None:
            auth_imap_candidate = cand
        last_imap_err = err

    matched_smtp: Optional[SmtpCandidate] = None
    auth_smtp_candidate: Optional[SmtpCandidate] = None
    last_smtp_err = ''
    for cand in smtp_candidates:
        ok, is_auth, err = test_smtp_connection(
            cand.server, cand.port, cand.use_tls, cand.use_ssl, cand.username, password, timeout=timeout
        )
        if ok:
            matched_smtp = cand
            break
        if is_auth and auth_smtp_candidate is None:
            auth_smtp_candidate = cand
        last_smtp_err = err

    best_imap = matched_imap or auth_imap_candidate
    best_smtp = matched_smtp or auth_smtp_candidate
    auth_error = bool((auth_imap_candidate and not matched_imap) or (auth_smtp_candidate and not matched_smtp))

    return {
        'success': bool(matched_imap and matched_smtp),
        'imap_ok': bool(matched_imap),
        'smtp_ok': bool(matched_smtp),
        'auth_error': auth_error,
        'imap': {
            'server': best_imap.server,
            'port': best_imap.port,
            'use_ssl': best_imap.use_ssl,
            'username': best_imap.username,
            'source': best_imap.source,
        } if best_imap else None,
        'smtp': {
            'server': best_smtp.server,
            'port': best_smtp.port,
            'use_tls': best_smtp.use_tls,
            'use_ssl': best_smtp.use_ssl,
            'username': best_smtp.username,
            'source': best_smtp.source,
        } if best_smtp else None,
        'error': last_imap_err or last_smtp_err,
    }
