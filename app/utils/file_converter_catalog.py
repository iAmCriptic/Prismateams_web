"""Conversion option catalog: detect category and list available targets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

AUDIO_INPUT = frozenset({'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'opus', 'wma'})
AUDIO_OUTPUT = frozenset({'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'opus'})

IMAGE_INPUT = frozenset({'jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff', 'tif', 'gif'})
IMAGE_OUTPUT = frozenset({'jpeg', 'png', 'webp', 'bmp', 'tiff', 'gif'})

PDF_INPUT = frozenset({'pdf'})

DOC_WORD_INPUT = frozenset({'docx', 'doc', 'odt', 'rtf'})
DOC_WORD_OUTPUT = frozenset({'pdf', 'docx', 'odt', 'txt'})

DOC_SHEET_INPUT = frozenset({'xlsx', 'xls', 'ods', 'csv'})
DOC_SHEET_OUTPUT = frozenset({'pdf', 'xlsx', 'ods', 'csv'})

DOC_PRES_INPUT = frozenset({'pptx', 'ppt', 'odp'})
DOC_PRES_OUTPUT = frozenset({'pdf', 'pptx', 'odp'})

DOCUMENT_INPUT = DOC_WORD_INPUT | DOC_SHEET_INPUT | DOC_PRES_INPUT

PAGE_SIZES = ('A1', 'A2', 'A3', 'A4', 'A5', 'Letter', 'Legal')

# Paper sizes in pixels at 300 DPI (portrait)
PAGE_SIZE_PX_300DPI = {
    'A1': (7016, 9933),
    'A2': (4961, 7016),
    'A3': (3508, 4961),
    'A4': (2480, 3508),
    'A5': (1748, 2480),
    'Letter': (2550, 3300),
    'Legal': (2550, 4200),
}

# Paper sizes in PDF points (1/72 inch), portrait
PAGE_SIZE_POINTS = {
    'A1': (1683.78, 2383.94),
    'A2': (1190.55, 1683.78),
    'A3': (841.89, 1190.55),
    'A4': (595.28, 841.89),
    'A5': (419.53, 595.28),
    'Letter': (612.0, 792.0),
    'Legal': (612.0, 1008.0),
}

CATEGORY_AUDIO = 'audio'
CATEGORY_IMAGE = 'image'
CATEGORY_PDF = 'pdf'
CATEGORY_DOCUMENT = 'document'

MIME_HINTS = {
    'audio/mpeg': 'mp3',
    'audio/mp3': 'mp3',
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
    'audio/ogg': 'ogg',
    'audio/flac': 'flac',
    'audio/aac': 'aac',
    'audio/mp4': 'm4a',
    'audio/x-m4a': 'm4a',
    'audio/opus': 'opus',
    'audio/x-ms-wma': 'wma',
    'image/jpeg': 'jpeg',
    'image/png': 'png',
    'image/webp': 'webp',
    'image/bmp': 'bmp',
    'image/tiff': 'tiff',
    'image/gif': 'gif',
    'application/pdf': 'pdf',
    'application/msword': 'doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.oasis.opendocument.text': 'odt',
    'application/rtf': 'rtf',
    'text/rtf': 'rtf',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.oasis.opendocument.spreadsheet': 'ods',
    'text/csv': 'csv',
    'application/vnd.ms-powerpoint': 'ppt',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'application/vnd.oasis.opendocument.presentation': 'odp',
}


@dataclass
class ConversionOption:
    id: str
    kind: str  # format | resize | page_size | image_to_pdf
    label_key: str
    target_format: str
    params: dict[str, Any] = field(default_factory=dict)
    group: str = 'format'  # format | size


@dataclass
class AnalysisResult:
    category: str
    source_format: str
    source_filename: str
    options: list[ConversionOption]
    engines: dict[str, bool]
    error: str | None = None


def normalize_ext(filename: str, mime: str | None = None) -> str:
    ext = ''
    if filename and '.' in filename:
        ext = filename.rsplit('.', 1)[-1].lower().strip()
    if ext == 'jpg':
        ext = 'jpeg'
    if ext == 'tif':
        ext = 'tif'
    if not ext and mime:
        hinted = MIME_HINTS.get((mime or '').split(';')[0].strip().lower())
        if hinted:
            ext = hinted
    if ext == 'tif':
        ext = 'tiff'
    return ext


def detect_category(ext: str) -> str | None:
    if ext in AUDIO_INPUT:
        return CATEGORY_AUDIO
    if ext in IMAGE_INPUT:
        return CATEGORY_IMAGE
    if ext in PDF_INPUT:
        return CATEGORY_PDF
    if ext in DOCUMENT_INPUT:
        return CATEGORY_DOCUMENT
    return None


def document_outputs_for(ext: str) -> frozenset[str]:
    if ext in DOC_WORD_INPUT:
        return DOC_WORD_OUTPUT
    if ext in DOC_SHEET_INPUT:
        return DOC_SHEET_OUTPUT
    if ext in DOC_PRES_INPUT:
        return DOC_PRES_OUTPUT
    return frozenset()


def get_available_engines() -> dict[str, bool]:
    from app.utils.file_converter import (
        is_ffmpeg_available,
        is_libreoffice_available,
        is_pillow_available,
        is_pypdf_available,
        is_img2pdf_available,
    )

    return {
        'ffmpeg': is_ffmpeg_available(),
        'pillow': is_pillow_available(),
        'pypdf': is_pypdf_available(),
        'img2pdf': is_img2pdf_available(),
        'libreoffice': is_libreoffice_available(),
    }


def build_options(category: str, source_format: str, engines: dict[str, bool]) -> list[ConversionOption]:
    options: list[ConversionOption] = []
    src = source_format.lower()
    if src == 'jpg':
        src = 'jpeg'

    if category == CATEGORY_AUDIO and engines.get('ffmpeg'):
        for fmt in sorted(AUDIO_OUTPUT):
            if fmt == src:
                continue
            options.append(ConversionOption(
                id=f'audio_to_{fmt}',
                kind='format',
                label_key=f'file_converter.format.{fmt}',
                target_format=fmt,
                group='format',
            ))

    elif category == CATEGORY_IMAGE and engines.get('pillow'):
        for fmt in sorted(IMAGE_OUTPUT):
            out = 'jpeg' if fmt == 'jpeg' else fmt
            if out == src or (src == 'jpeg' and out == 'jpeg'):
                continue
            options.append(ConversionOption(
                id=f'image_to_{out}',
                kind='format',
                label_key=f'file_converter.format.{out}',
                target_format=out,
                group='format',
            ))

        if engines.get('img2pdf'):
            options.append(ConversionOption(
                id='image_to_pdf',
                kind='image_to_pdf',
                label_key='file_converter.format.pdf',
                target_format='pdf',
                group='format',
            ))

        for size in PAGE_SIZES:
            if size == 'Legal':
                continue  # keep image paper list focused
            options.append(ConversionOption(
                id=f'image_resize_{size.lower()}',
                kind='resize',
                label_key=f'file_converter.page_size.{size.lower()}',
                target_format=src if src in IMAGE_OUTPUT else 'png',
                params={'page_size': size, 'dpi': 300},
                group='size',
            ))

        options.append(ConversionOption(
            id='image_resize_custom',
            kind='resize',
            label_key='file_converter.resize.custom',
            target_format=src if src in IMAGE_OUTPUT else 'png',
            params={'mode': 'custom'},
            group='size',
        ))
        options.append(ConversionOption(
            id='image_resize_percent',
            kind='resize',
            label_key='file_converter.resize.percent',
            target_format=src if src in IMAGE_OUTPUT else 'png',
            params={'mode': 'percent'},
            group='size',
        ))

    elif category == CATEGORY_PDF and engines.get('pypdf'):
        for size in PAGE_SIZES:
            options.append(ConversionOption(
                id=f'pdf_page_{size.lower()}',
                kind='page_size',
                label_key=f'file_converter.page_size.{size.lower()}',
                target_format='pdf',
                params={'page_size': size},
                group='size',
            ))

    elif category == CATEGORY_DOCUMENT and engines.get('libreoffice'):
        for fmt in sorted(document_outputs_for(src)):
            if fmt == src:
                continue
            options.append(ConversionOption(
                id=f'doc_to_{fmt}',
                kind='format',
                label_key=f'file_converter.format.{fmt}',
                target_format=fmt,
                group='format',
            ))

    return options


def analyze_upload(path: str, filename: str, mime: str | None = None) -> AnalysisResult:
    engines = get_available_engines()
    ext = normalize_ext(filename, mime)
    category = detect_category(ext)

    if not category:
        return AnalysisResult(
            category='',
            source_format=ext or '',
            source_filename=filename or '',
            options=[],
            engines=engines,
            error='unsupported_type',
        )

    if category == CATEGORY_AUDIO and not engines.get('ffmpeg'):
        return AnalysisResult(
            category=category,
            source_format=ext,
            source_filename=filename,
            options=[],
            engines=engines,
            error='ffmpeg_missing',
        )
    if category == CATEGORY_DOCUMENT and not engines.get('libreoffice'):
        return AnalysisResult(
            category=category,
            source_format=ext,
            source_filename=filename,
            options=[],
            engines=engines,
            error='libreoffice_missing',
        )
    if category == CATEGORY_IMAGE and not engines.get('pillow'):
        return AnalysisResult(
            category=category,
            source_format=ext,
            source_filename=filename,
            options=[],
            engines=engines,
            error='pillow_missing',
        )
    if category == CATEGORY_PDF and not engines.get('pypdf'):
        return AnalysisResult(
            category=category,
            source_format=ext,
            source_filename=filename,
            options=[],
            engines=engines,
            error='pypdf_missing',
        )

    if path and not os.path.isfile(path):
        return AnalysisResult(
            category=category,
            source_format=ext,
            source_filename=filename,
            options=[],
            engines=engines,
            error='file_missing',
        )

    options = build_options(category, ext, engines)
    if not options:
        return AnalysisResult(
            category=category,
            source_format=ext,
            source_filename=filename,
            options=[],
            engines=engines,
            error='no_options',
        )

    return AnalysisResult(
        category=category,
        source_format=ext,
        source_filename=filename,
        options=options,
        engines=engines,
    )


def options_to_dict(options: list[ConversionOption]) -> list[dict[str, Any]]:
    return [
        {
            'id': o.id,
            'kind': o.kind,
            'label_key': o.label_key,
            'target_format': o.target_format,
            'params': o.params,
            'group': o.group,
        }
        for o in options
    ]


def find_option(option_id: str, category: str, source_format: str, engines: dict[str, bool] | None = None) -> ConversionOption | None:
    engines = engines or get_available_engines()
    for opt in build_options(category, source_format, engines):
        if opt.id == option_id:
            return opt
    return None
