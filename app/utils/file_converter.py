"""File converter engine: FFmpeg, Pillow, pypdf, LibreOffice."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import timedelta

from flask import current_app

from app.utils.file_converter_catalog import (
    PAGE_SIZE_POINTS,
    PAGE_SIZE_PX_300DPI,
    CATEGORY_AUDIO,
    CATEGORY_DOCUMENT,
    CATEGORY_IMAGE,
    CATEGORY_PDF,
)

logger = logging.getLogger(__name__)

LIBREOFFICE_FALLBACK_PATHS = (
    '/usr/bin/soffice',
    '/usr/bin/libreoffice',
    '/usr/local/bin/soffice',
    '/usr/lib/libreoffice/program/soffice',
    r'C:\Program Files\LibreOffice\program\soffice.exe',
    r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
)

CONVERT_TIMEOUT_SECONDS = 300

PILLOW_FORMAT_MAP = {
    'jpeg': 'JPEG',
    'jpg': 'JPEG',
    'png': 'PNG',
    'webp': 'WEBP',
    'bmp': 'BMP',
    'tiff': 'TIFF',
    'gif': 'GIF',
}


class ConversionError(Exception):
    def __init__(self, error_key='err_convert_failed', message=None):
        super().__init__(message or error_key)
        self.error_key = error_key


def is_pillow_available():
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def is_pypdf_available():
    try:
        from pypdf import PdfReader  # noqa: F401
        return True
    except ImportError:
        return False


def is_img2pdf_available():
    try:
        import img2pdf  # noqa: F401
        return True
    except ImportError:
        return False


def is_ffmpeg_available():
    try:
        from app.utils.media_downloader import get_ffmpeg_path
        return bool(get_ffmpeg_path())
    except Exception:
        return False


def get_libreoffice_path():
    configured = current_app.config.get('LIBREOFFICE_PATH', '')
    if configured and os.path.isfile(configured):
        return configured

    for name in ('soffice', 'libreoffice'):
        found = shutil.which(name)
        if found:
            return found

    for candidate in LIBREOFFICE_FALLBACK_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


def is_libreoffice_available():
    return bool(get_libreoffice_path())


def get_libreoffice_version():
    path = get_libreoffice_path()
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, '--version'],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        text = (result.stdout or result.stderr or '').strip()
        match = re.search(r'LibreOffice\s+(\S+)', text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return text.splitlines()[0][:80] if text else None
    except Exception:
        logger.debug('Could not determine LibreOffice version', exc_info=True)
        return None


def get_upload_dir():
    base = current_app.config['UPLOAD_FOLDER']
    if not os.path.isabs(base):
        project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
        base = os.path.join(project_root, base)
    target = os.path.abspath(os.path.join(base, 'file_converter'))
    os.makedirs(target, exist_ok=True)
    return target


def get_job_dir(job_id):
    target = os.path.abspath(os.path.join(get_upload_dir(), str(job_id)))
    os.makedirs(target, exist_ok=True)
    return target


def get_retention_timedelta():
    hours = current_app.config.get('FILE_CONVERTER_RETENTION_HOURS', 24)
    return timedelta(hours=max(1, int(hours)))


def _slugify(name, fallback='file'):
    text = (name or fallback).strip() or fallback
    text = re.sub(r'[^\w\s.-]', '', text, flags=re.UNICODE)
    text = re.sub(r'\s+', '_', text).strip('._')
    return (text[:180] or fallback)


def _base_name(filename):
    name = os.path.basename(filename or 'file')
    if '.' in name:
        name = name.rsplit('.', 1)[0]
    return _slugify(name)


def parse_options_json(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def delete_job_files(job):
    """Remove source/output files and job directory."""
    paths = []
    for attr in ('source_path', 'output_path'):
        path = getattr(job, attr, None)
        if path:
            paths.append(path)

    job_id = getattr(job, 'id', None)
    if job_id:
        job_dir = os.path.abspath(os.path.join(get_upload_dir(), str(job_id)))
        if os.path.isdir(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
            return

    for path in paths:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.debug('Could not delete converter file %s', path, exc_info=True)


def _run_ffmpeg_audio(src, dest, target_format):
    from app.utils.media_downloader import get_ffmpeg_path

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise ConversionError('ffmpeg_missing')

    codec_args = {
        'mp3': ['-acodec', 'libmp3lame', '-q:a', '2'],
        'wav': ['-acodec', 'pcm_s16le'],
        'ogg': ['-acodec', 'libvorbis', '-q:a', '5'],
        'flac': ['-acodec', 'flac'],
        'aac': ['-acodec', 'aac', '-b:a', '192k'],
        'm4a': ['-acodec', 'aac', '-b:a', '192k'],
        'opus': ['-acodec', 'libopus', '-b:a', '128k'],
    }.get(target_format, [])

    args = [
        ffmpeg, '-y', '-i', src,
        '-vn',
        *codec_args,
        dest,
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=CONVERT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0 or not os.path.isfile(dest):
        logger.warning('FFmpeg audio convert failed: %s', (result.stderr or '')[-500:])
        raise ConversionError('err_convert_failed')


def _convert_image(src, dest, target_format, options):
    from PIL import Image

    with Image.open(src) as img:
        work = img.copy()

    page_size = (options.get('page_size') or '').strip()
    mode = (options.get('mode') or '').strip()
    dpi = int(options.get('dpi') or 300)

    if page_size and page_size in PAGE_SIZE_PX_300DPI:
        tw, th = PAGE_SIZE_PX_300DPI[page_size]
        if dpi != 300:
            scale = dpi / 300.0
            tw, th = int(tw * scale), int(th * scale)
        work = _fit_image(work, tw, th)
    elif mode == 'custom':
        width = int(options.get('width') or 0)
        height = int(options.get('height') or 0)
        keep = bool(options.get('keep_aspect', True))
        if width <= 0 and height <= 0:
            raise ConversionError('invalid_resize')
        if keep:
            work = _resize_keep_aspect(work, width, height)
        else:
            if width <= 0 or height <= 0:
                raise ConversionError('invalid_resize')
            work = work.resize((width, height), Image.Resampling.LANCZOS)
    elif mode == 'percent':
        try:
            percent = float(options.get('percent') or 100)
        except (TypeError, ValueError):
            percent = 100
        if percent < 25 or percent > 400:
            raise ConversionError('invalid_resize')
        nw = max(1, int(work.width * percent / 100.0))
        nh = max(1, int(work.height * percent / 100.0))
        work = work.resize((nw, nh), Image.Resampling.LANCZOS)

    fmt = PILLOW_FORMAT_MAP.get(target_format.lower())
    if not fmt:
        raise ConversionError('invalid_format')

    save_kwargs = {}
    if fmt == 'JPEG':
        if work.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', work.size, (255, 255, 255))
            if work.mode == 'P':
                work = work.convert('RGBA')
            background.paste(work, mask=work.split()[-1] if work.mode in ('RGBA', 'LA') else None)
            work = background
        elif work.mode != 'RGB':
            work = work.convert('RGB')
        save_kwargs['quality'] = 90
        save_kwargs['optimize'] = True
    elif fmt == 'GIF' and work.mode not in ('P', 'L'):
        work = work.convert('P', palette=Image.Palette.ADAPTIVE)

    work.save(dest, format=fmt, **save_kwargs)
    if not os.path.isfile(dest):
        raise ConversionError('err_convert_failed')


def _fit_image(img, target_w, target_h):
    """Scale image to fit inside target box, then pad to exact size."""
    from PIL import Image

    ratio = min(target_w / img.width, target_h / img.height)
    nw = max(1, int(img.width * ratio))
    nh = max(1, int(img.height * ratio))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)

    mode = 'RGBA' if resized.mode in ('RGBA', 'LA', 'P') else 'RGB'
    canvas = Image.new(mode, (target_w, target_h), (255, 255, 255) if mode == 'RGB' else (255, 255, 255, 0))
    if resized.mode == 'P':
        resized = resized.convert(mode)
    elif resized.mode != mode:
        resized = resized.convert(mode)
    ox = (target_w - nw) // 2
    oy = (target_h - nh) // 2
    canvas.paste(resized, (ox, oy), resized if mode == 'RGBA' and resized.mode == 'RGBA' else None)
    return canvas


def _resize_keep_aspect(img, width, height):
    from PIL import Image

    if width > 0 and height > 0:
        ratio = min(width / img.width, height / img.height)
    elif width > 0:
        ratio = width / img.width
    else:
        ratio = height / img.height
    nw = max(1, int(img.width * ratio))
    nh = max(1, int(img.height * ratio))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _image_to_pdf(src, dest, options):
    import img2pdf
    from PIL import Image

    page_size = (options.get('page_size') or '').strip()
    tmp_path = None
    try:
        input_path = src
        if page_size and page_size in PAGE_SIZE_PX_300DPI:
            fd, tmp_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            _convert_image(src, tmp_path, 'png', {'page_size': page_size, 'dpi': 300})
            input_path = tmp_path

        with open(input_path, 'rb') as f:
            data = f.read()

        # Validate with Pillow first
        with Image.open(input_path) as _:
            pass

        layout = None
        if page_size and page_size in PAGE_SIZE_POINTS:
            w, h = PAGE_SIZE_POINTS[page_size]
            layout = img2pdf.get_layout_fun((w, h))

        with open(dest, 'wb') as out:
            if layout:
                out.write(img2pdf.convert(data, layout_fun=layout))
            else:
                out.write(img2pdf.convert(data))
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if not os.path.isfile(dest):
        raise ConversionError('err_convert_failed')


def _convert_pdf_page_size(src, dest, page_size):
    from pypdf import PageObject, PdfReader, PdfWriter, Transformation

    if page_size not in PAGE_SIZE_POINTS:
        raise ConversionError('invalid_page_size')

    tw, th = PAGE_SIZE_POINTS[page_size]
    reader = PdfReader(src)
    writer = PdfWriter()

    for page in reader.pages:
        mediabox = page.mediabox
        sw = float(mediabox.width)
        sh = float(mediabox.height)
        if sw <= 0 or sh <= 0:
            continue

        scale = min(tw / sw, th / sh)
        ox = (tw - sw * scale) / 2.0
        oy = (th - sh * scale) / 2.0

        blank = PageObject.create_blank_page(width=tw, height=th)
        blank.merge_transformed_page(
            page,
            Transformation().scale(scale, scale).translate(ox, oy),
        )
        writer.add_page(blank)

    with open(dest, 'wb') as f:
        writer.write(f)

    if not os.path.isfile(dest):
        raise ConversionError('err_convert_failed')


def _convert_document(src, dest_dir, target_format):
    soffice = get_libreoffice_path()
    if not soffice:
        raise ConversionError('libreoffice_missing')

    os.makedirs(dest_dir, exist_ok=True)
    # LibreOffice writes into outdir with original basename + new ext
    env = os.environ.copy()
    # Isolate user profile to avoid lock conflicts under concurrent conversions
    profile_dir = tempfile.mkdtemp(prefix='lo_profile_')
    try:
        profile_uri = 'file:///' + profile_dir.replace('\\', '/').lstrip('/')
        if os.name == 'nt':
            profile_uri = 'file:///' + profile_dir.replace('\\', '/')

        args = [
            soffice,
            f'-env:UserInstallation={profile_uri}',
            '--headless',
            '--nologo',
            '--nofirststartwizard',
            '--norestore',
            '--convert-to', target_format,
            '--outdir', dest_dir,
            src,
        ]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=CONVERT_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            logger.warning('LibreOffice convert failed: %s', (result.stderr or result.stdout or '')[-800:])
            raise ConversionError('err_convert_failed')

        base = os.path.splitext(os.path.basename(src))[0]
        expected = os.path.join(dest_dir, f'{base}.{target_format}')
        if os.path.isfile(expected):
            return expected

        # Fallback: pick newest matching extension
        candidates = [
            os.path.join(dest_dir, name)
            for name in os.listdir(dest_dir)
            if name.lower().endswith('.' + target_format.lower())
        ]
        if not candidates:
            raise ConversionError('output_not_found')
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


def run_conversion(job):
    """
    Convert a ConversionJob. Mutates job fields (paths, status fields left to caller).
    Returns (success: bool, error_key_or_message: str|None).
    """
    options = parse_options_json(job.options_json)
    kind = (options.get('kind') or 'format').strip()
    target_format = (job.target_format or '').strip().lower()
    category = (job.source_category or '').strip().lower()
    src = job.source_path

    if not src or not os.path.isfile(src):
        return False, 'file_missing'

    job_dir = get_job_dir(job.id)
    out_base = _base_name(job.source_filename)

    try:
        if category == CATEGORY_AUDIO:
            dest = os.path.join(job_dir, f'{out_base}.{target_format}')
            _run_ffmpeg_audio(src, dest, target_format)
            job.output_path = dest
            job.output_filename = os.path.basename(dest)
            job.file_size = os.path.getsize(dest)
            return True, None

        if category == CATEGORY_IMAGE:
            if kind == 'image_to_pdf' or target_format == 'pdf':
                dest = os.path.join(job_dir, f'{out_base}.pdf')
                _image_to_pdf(src, dest, options)
            else:
                dest_ext = target_format if target_format != 'jpg' else 'jpeg'
                if dest_ext == 'jpeg':
                    dest_name = f'{out_base}.jpg'
                else:
                    dest_name = f'{out_base}.{dest_ext}'
                dest = os.path.join(job_dir, dest_name)
                _convert_image(src, dest, dest_ext, options)
            job.output_path = dest
            job.output_filename = os.path.basename(dest)
            job.file_size = os.path.getsize(dest)
            return True, None

        if category == CATEGORY_PDF:
            page_size = (options.get('page_size') or '').strip()
            dest = os.path.join(job_dir, f'{out_base}_{page_size or "out"}.pdf')
            _convert_pdf_page_size(src, dest, page_size)
            job.output_path = dest
            job.output_filename = os.path.basename(dest)
            job.file_size = os.path.getsize(dest)
            return True, None

        if category == CATEGORY_DOCUMENT:
            produced = _convert_document(src, job_dir, target_format)
            final_name = f'{out_base}.{target_format}'
            final_path = os.path.join(job_dir, final_name)
            if os.path.abspath(produced) != os.path.abspath(final_path):
                if os.path.isfile(final_path):
                    os.remove(final_path)
                shutil.move(produced, final_path)
            else:
                final_path = produced
            job.output_path = final_path
            job.output_filename = os.path.basename(final_path)
            job.file_size = os.path.getsize(final_path)
            return True, None

        return False, 'unsupported_type'
    except ConversionError as exc:
        return False, exc.error_key
    except subprocess.TimeoutExpired:
        return False, 'timeout'
    except Exception:
        logger.exception('Conversion failed for job %s', getattr(job, 'id', None))
        return False, 'err_convert_failed'
