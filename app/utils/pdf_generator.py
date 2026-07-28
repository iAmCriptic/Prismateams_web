from reportlab.lib.pagesizes import A4, A5, letter
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, Flowable, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas
from flask import current_app
from io import BytesIO
from datetime import datetime
import os
from PIL import Image as PILImage
from app.utils.qr_code import (
    generate_qr_code_bytes,
    generate_qr_code_inverted_bytes,
    generate_qr_code_with_logo_bytes,
    generate_product_qr_code,
    generate_borrow_qr_code,
    generate_set_qr_code,
)
from app.utils.lengths import format_length_from_meters, parse_length_to_meters
from app.utils.color_mapping import get_color_for_length, initialize_color_mappings


# ---------------------------------------------------------------------------
# Design tokens — einheitliches Portal-PDF-System
# ---------------------------------------------------------------------------

PDF_COLORS = {
    'text': colors.HexColor('#1a1d21'),
    'text_muted': colors.HexColor('#6c757d'),
    'text_secondary': colors.HexColor('#495057'),
    'header_bg': colors.HexColor('#f0f2f5'),
    'zebra': colors.HexColor('#f8f9fa'),
    'line': colors.HexColor('#dee2e6'),
    'line_soft': colors.HexColor('#e9ecef'),
    'footer': colors.HexColor('#868e96'),
    'white': colors.white,
    'card_bg': colors.white,
    'default_accent': colors.HexColor('#0d6efd'),
}


def get_pdf_accent_color():
    """Portal-Akzentfarbe aus SystemSettings (dezent nutzen, nie als Tabellen-Vollfläche)."""
    try:
        from app.models.settings import SystemSettings
        setting = SystemSettings.query.filter_by(key='default_accent_color').first()
        if setting and setting.value and setting.value.strip():
            return colors.HexColor(setting.value.strip())
    except Exception:
        pass
    return PDF_COLORS['default_accent']


def pdf_paragraph_styles():
    """Gemeinsame Paragraph-Styles für alle Portal-PDFs."""
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'PdfSysTitle',
            parent=base['Heading1'],
            fontSize=17,
            leading=21,
            textColor=PDF_COLORS['text'],
            fontName='Helvetica-Bold',
            spaceAfter=2,
        ),
        'subtitle': ParagraphStyle(
            'PdfSysSubtitle',
            parent=base['Normal'],
            fontSize=10,
            leading=12,
            textColor=PDF_COLORS['text_muted'],
        ),
        'section': ParagraphStyle(
            'PdfSysSection',
            parent=base['Normal'],
            fontSize=11,
            leading=14,
            fontName='Helvetica-Bold',
            textColor=PDF_COLORS['text'],
            spaceBefore=0.15 * cm,
            spaceAfter=0.2 * cm,
        ),
        'body': ParagraphStyle(
            'PdfSysBody',
            parent=base['Normal'],
            fontSize=10,
            leading=13,
            textColor=PDF_COLORS['text'],
        ),
        'muted': ParagraphStyle(
            'PdfSysMuted',
            parent=base['Normal'],
            fontSize=9,
            leading=12,
            textColor=PDF_COLORS['text_muted'],
        ),
        'caption': ParagraphStyle(
            'PdfSysCaption',
            parent=base['Normal'],
            fontSize=8,
            leading=10,
            textColor=PDF_COLORS['text_muted'],
            alignment=TA_CENTER,
        ),
    }


class AccentLine(Flowable):
    """Dünne Akzentlinie unter dem Dokumentkopf."""

    def __init__(self, width, height=1.5, color=None):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color or get_pdf_accent_color()

    def wrap(self, availWidth, availHeight):
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self):
        self.canv.saveState()
        self.canv.setStrokeColor(self.color)
        self.canv.setFillColor(self.color)
        self.canv.setLineWidth(0)
        self.canv.roundRect(0, 0, self.width, self.height, min(self.height / 2, 1), fill=1, stroke=0)
        self.canv.restoreState()


class RoundedBox(Flowable):
    """Inhalt in weich abgerundeter Karte (Portal-Pill-Look)."""

    def __init__(
        self,
        inner,
        width,
        padding=7,
        radius=8,
        fill_color=None,
        stroke_color=None,
        stroke_width=0.6,
    ):
        Flowable.__init__(self)
        self.inner = inner
        self.box_width = width
        self.padding = padding
        self.radius = radius
        self.fill_color = fill_color if fill_color is not None else PDF_COLORS['card_bg']
        self.stroke_color = stroke_color if stroke_color is not None else PDF_COLORS['line']
        self.stroke_width = stroke_width

    def wrap(self, availWidth, availHeight):
        w = min(self.box_width, availWidth)
        inner_w = max(w - 2 * self.padding, 1)
        iw, ih = self.inner.wrap(inner_w, availHeight - 2 * self.padding)
        self._inner_w = iw
        self._inner_h = ih
        self.width = w
        self.height = ih + 2 * self.padding
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.fill_color)
        c.setStrokeColor(self.stroke_color)
        c.setLineWidth(self.stroke_width)
        c.roundRect(0, 0, self.width, self.height, self.radius, fill=1, stroke=1)
        c.restoreState()
        self.inner.drawOn(c, self.padding, self.padding)


class DashedLine(Flowable):
    """Custom Flowable für gestrichelte Linien."""
    def __init__(self, width, height, color, dash_array=[3, 2], horizontal=True):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color
        self.dash_array = dash_array
        self.horizontal = horizontal
    
    def draw(self):
        """Zeichnet eine gestrichelte Linie."""
        self.canv.saveState()
        self.canv.setStrokeColor(self.color)
        self.canv.setDash(self.dash_array)
        self.canv.setLineWidth(0.5)
        
        if self.horizontal:
            # Horizontale Linie
            self.canv.line(0, self.height / 2, self.width, self.height / 2)
        else:
            # Vertikale Linie
            self.canv.line(self.width / 2, 0, self.width / 2, self.height)
        
        self.canv.restoreState()


class CableLabelFlowable(Flowable):
    """
    Kabel-Wickeletikett: [FARBSTREIFEN][QR weiß/schwarz][TEXT weiß/schwarz][FARBSTREIFEN]
    Kann um ein Kabel gewickelt werden – eine Seite QR, andere Seite Text.
    """
    def __init__(self, product, qr_bytes, stripe_color_hex, label_width, label_height):
        Flowable.__init__(self)
        self.product = product
        self.qr_bytes = qr_bytes
        try:
            self.stripe_color = colors.HexColor(stripe_color_hex)
        except Exception:
            self.stripe_color = colors.HexColor('#888888')
        self.width = label_width
        self.height = label_height

    def draw(self):
        c = self.canv
        lw = self.width
        lh = self.height
        sw = 1.2 * cm  # Streifenbreite

        # Linker Farbstreifen
        c.setFillColor(self.stripe_color)
        c.rect(0, 0, sw, lh, fill=1, stroke=0)

        # Rechter Farbstreifen
        c.setFillColor(self.stripe_color)
        c.rect(lw - sw, 0, sw, lh, fill=1, stroke=0)

        # Schwarzer Mittelteil
        c.setFillColor(colors.black)
        c.rect(sw, 0, lw - 2 * sw, lh, fill=1, stroke=0)

        # QR-Code (weiß auf schwarz) – quadratisch, füllt fast die volle Höhe
        qr_margin = 3
        qr_size = lh - 2 * qr_margin
        qr_x = sw + qr_margin
        qr_y = qr_margin
        c.drawImage(ImageReader(BytesIO(self.qr_bytes)), qr_x, qr_y, qr_size, qr_size)

        # Textbereich (weiß auf schwarz)
        c.setFillColor(colors.white)
        text_x = sw + qr_size + qr_margin * 2 + 4

        # Produktname (fett)
        name = self.product.name or f'ID {self.product.id}'
        if len(name) > 16:
            name = name[:15] + u'…'
        c.setFont('Helvetica-Bold', 8)
        c.drawString(text_x, lh * 0.70, name)

        # Produkt-ID
        c.setFont('Helvetica', 6.5)
        c.drawString(text_x, lh * 0.46, f'ID: {self.product.id}')

        # Länge mit farbigem Punkt
        if self.product.length:
            length_str = _format_length(self.product.length)
            dot_r = 3
            dot_x = text_x + dot_r
            dot_y = lh * 0.20 + dot_r
            c.setFillColor(self.stripe_color)
            c.circle(dot_x, dot_y, dot_r, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont('Helvetica-Bold', 8)
            c.drawString(text_x + dot_r * 2 + 4, lh * 0.17, length_str)

        # Gestrichelter Schnittrahmen
        c.setStrokeColor(colors.HexColor('#aaaaaa'))
        c.setDash([2, 2])
        c.setLineWidth(0.4)
        c.rect(0, 0, lw, lh, fill=0, stroke=1)
        c.setDash([])


def _format_length(value):
    """Gibt eine konsistente Meter-Darstellung zurück."""
    meters = parse_length_to_meters(value)
    if meters is None:
        return value or '-'
    formatted = format_length_from_meters(meters)
    return formatted or (value or '-')


def get_logo_path():
    """Holt den Pfad zum Portal-Logo aus SystemSettings oder Konfiguration."""
    # Try to get portal logo from SystemSettings first
    try:
        from app.models.settings import SystemSettings
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            # Portal logo is stored in uploads/system/
            project_root = os.path.dirname(current_app.root_path)
            logo_path = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system', portal_logo_setting.value)
            if os.path.exists(logo_path):
                return logo_path
    except:
        pass
    
    # Fallback to config
    logo_path = current_app.config.get('APP_LOGO', 'static/img/logo.png')
    
    # Wenn der Pfad mit 'static/' beginnt, entferne es (Flask fügt es automatisch hinzu)
    if logo_path.startswith('static/'):
        logo_path = logo_path[7:]
    
    # Konvertiere zu absolutem Pfad
    static_folder = current_app.static_folder
    full_path = os.path.join(static_folder, logo_path)
    
    # Prüfe ob Logo existiert
    if os.path.exists(full_path):
        return full_path
    return None


def get_portal_name():
    """Portalname aus SystemSettings, sonst APP_NAME."""
    try:
        from app.models.settings import SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
            return portal_name_setting.value.strip()
    except Exception:
        pass
    return current_app.config.get('APP_NAME', 'Prismateams')


def build_standard_header(title, subtitle=None, pagesize=A4, logo_size=2.0 * cm,
                          content_width=None, show_logo=True, show_accent=True):
    """
    Einheitlicher PDF-Kopf: Portal-Logo links, Titel (und optional Untertitel) daneben,
    darunter dezente Akzentlinie. show_logo=False für QR-Bögen.
    """
    ps = pdf_paragraph_styles()
    usable_width = content_width if content_width is not None else (pagesize[0] - 4 * cm)

    text_block = [Paragraph(title, ps['title'])]
    if subtitle:
        text_block.append(Paragraph(subtitle, ps['subtitle']))

    logo_cell = ''
    if show_logo:
        logo_path = get_logo_path()
        if logo_path:
            try:
                logo_cell = Image(logo_path, width=logo_size, height=logo_size, kind='proportional')
            except Exception:
                logo_cell = ''

    if show_logo and logo_cell != '':
        logo_col = logo_size + 0.6 * cm
        text_col = max(usable_width - logo_col, 8 * cm)
        header = Table([[logo_cell, text_block]], colWidths=[logo_col, text_col])
    else:
        header = Table([[text_block]], colWidths=[usable_width])

    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    if not show_accent:
        return header

    parts = [header, Spacer(1, 0.22 * cm), AccentLine(usable_width)]
    return KeepTogether(parts)


def standard_table_style(header=True):
    """
    Moderner Portal-Tabellenstil: weicher Header, LINEBELOW statt hartem Grid,
    pill-ähnliches Padding — kein vollflächiges Blau.
    """
    style = [
        ('BOX', (0, 0), (-1, -1), 0.6, PDF_COLORS['line']),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, PDF_COLORS['line_soft']),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('LEADING', (0, 0), (-1, -1), 12),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('TEXTCOLOR', (0, 0), (-1, -1), PDF_COLORS['text']),
        ('BACKGROUND', (0, 1), (-1, -1), PDF_COLORS['white']),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [PDF_COLORS['white'], PDF_COLORS['zebra']]),
    ]
    if header:
        style.extend([
            ('BACKGROUND', (0, 0), (-1, 0), PDF_COLORS['header_bg']),
            ('TEXTCOLOR', (0, 0), (-1, 0), PDF_COLORS['text']),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('LINEBELOW', (0, 0), (-1, 0), 1.0, PDF_COLORS['line']),
        ])
    return TableStyle(style)


def inventory_table_style(header=True):
    """Alias für Abwärtskompatibilität — nutzt standard_table_style."""
    return standard_table_style(header=header)


def meta_kv_table_style():
    """Key/Value-Metadaten (Ausleihe, Rückgabe, Inventur)."""
    return TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), PDF_COLORS['text_secondary']),
        ('TEXTCOLOR', (1, 0), (1, -1), PDF_COLORS['text']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, 0), (-1, -2), 0.3, PDF_COLORS['line_soft']),
    ])


def _qr_block(qr_payload, label='QR-Code', size=4.0 * cm):
    """Zentrierter QR in weicher Karte für Inventar-Belege."""
    ps = pdf_paragraph_styles()
    label_style = ParagraphStyle(
        'InvQrLabel',
        parent=ps['section'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=0.15 * cm,
        spaceBefore=0,
    )
    caption_style = ParagraphStyle(
        'InvQrCaption',
        parent=ps['caption'],
        fontSize=7,
        leading=9,
    )
    qr_bytes = generate_qr_code_bytes(qr_payload, box_size=8, border=2)
    qr_image = Image(BytesIO(qr_bytes), width=size, height=size)
    inner = Table(
        [[Paragraph(label, label_style)], [qr_image], [Paragraph(str(qr_payload), caption_style)]],
        colWidths=[size + 0.6 * cm],
    )
    inner.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))
    return RoundedBox(
        inner,
        width=size + 1.4 * cm,
        padding=8,
        radius=10,
        fill_color=PDF_COLORS['zebra'],
        stroke_color=PDF_COLORS['line'],
    )


class StandardFooterCanvas(pdf_canvas.Canvas):
    """Canvas mit Fußzeile und Seitenzahl im Format X/Y."""

    def __init__(self, *args, **kwargs):
        pdf_canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []
        self.pdf_created_at = datetime.now().strftime('%d.%m.%Y %H:%M')
        self.pdf_portal_name = 'Prismateams'
        self.pdf_left_margin = 2 * cm
        self.pdf_right_margin = 2 * cm

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(page_count)
            pdf_canvas.Canvas.showPage(self)
        pdf_canvas.Canvas.save(self)

    def _draw_footer(self, page_count):
        page_width, _ = self._pagesize
        left = self.pdf_left_margin
        right = page_width - self.pdf_right_margin
        y = 1.15 * cm
        line_y = y + 0.4 * cm

        self.saveState()
        self.setStrokeColor(PDF_COLORS['line'])
        self.setLineWidth(0.5)
        self.line(left, line_y, right, line_y)

        self.setFillColor(PDF_COLORS['footer'])
        self.setFont('Helvetica', 8)
        self.drawString(left, y, f"Erstellt am {self.pdf_created_at}")
        self.drawCentredString(page_width / 2.0, y, f"© {self.pdf_portal_name}")
        self.drawRightString(right, y, f"{self._pageNumber}/{page_count}")
        self.restoreState()


def draw_standard_footer(canvas, doc):
    """
    Einheitlicher PDF-Fuß (Fallback ohne Gesamtseitenzahl).
    Bevorzugt StandardFooterCanvas über build_standard_pdf nutzen.
    """
    canvas.saveState()
    page_width, _ = doc.pagesize
    left = doc.leftMargin
    right = page_width - doc.rightMargin
    y = 1.15 * cm
    line_y = y + 0.4 * cm

    canvas.setStrokeColor(PDF_COLORS['line'])
    canvas.setLineWidth(0.5)
    canvas.line(left, line_y, right, line_y)

    canvas.setFillColor(PDF_COLORS['footer'])
    canvas.setFont('Helvetica', 8)

    created_at = getattr(doc, 'pdf_created_at', None) or datetime.now().strftime('%d.%m.%Y %H:%M')
    portal_name = getattr(doc, 'pdf_portal_name', None) or 'Prismateams'
    page_count = getattr(doc, 'pdf_page_count', None)

    canvas.drawString(left, y, f"Erstellt am {created_at}")
    canvas.drawCentredString(page_width / 2.0, y, f"© {portal_name}")
    page_label = (
        f"{canvas.getPageNumber()}/{page_count}"
        if page_count
        else str(canvas.getPageNumber())
    )
    canvas.drawRightString(right, y, page_label)
    canvas.restoreState()


def build_standard_pdf(story, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                       topMargin=1.5 * cm, bottomMargin=2 * cm, output=None):
    """Baut PDF mit Standard-Footer und Seitenzahl X/Y auf jeder Seite."""
    if output is None:
        output = BytesIO()

    doc = SimpleDocTemplate(
        output,
        pagesize=pagesize,
        leftMargin=leftMargin,
        rightMargin=rightMargin,
        topMargin=topMargin,
        bottomMargin=bottomMargin,
    )
    created_at = datetime.now().strftime('%d.%m.%Y %H:%M')
    try:
        portal_name = get_portal_name()
    except Exception:
        portal_name = 'Prismateams'

    doc.pdf_created_at = created_at
    doc.pdf_portal_name = portal_name

    def _canvas_maker(filename, **kwargs):
        canvas_obj = StandardFooterCanvas(filename, **kwargs)
        canvas_obj.pdf_created_at = created_at
        canvas_obj.pdf_portal_name = portal_name
        canvas_obj.pdf_left_margin = leftMargin
        canvas_obj.pdf_right_margin = rightMargin
        return canvas_obj

    doc.build(story, canvasmaker=_canvas_maker)

    if isinstance(output, BytesIO):
        output.seek(0)
    return output


def generate_music_wish_pdf(public_url, output=None):
    """
    Generiert eine A5-PDF für Musikwünsche mit QR-Code und Link.
    Einheitliches Layout: Standard-Kopf, Footer, Portal-Look.
    """
    if output is None:
        output = BytesIO()

    usable = A5[0] - 3 * cm
    ps = pdf_paragraph_styles()
    story = [
        build_standard_header(
            "Musikwünsche?",
            subtitle="Hier scannen und suchen",
            pagesize=A5,
            logo_size=2.0 * cm,
            content_width=usable,
        ),
        Spacer(1, 0.7 * cm),
    ]

    qr_bytes = generate_qr_code_bytes(public_url, box_size=8, border=3)
    qr_size = 5.5 * cm
    qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
    qr_inner = Table([[qr_image]], colWidths=[qr_size])
    qr_inner.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(RoundedBox(
        qr_inner,
        width=usable,
        padding=14,
        radius=12,
        fill_color=PDF_COLORS['zebra'],
        stroke_color=PDF_COLORS['line'],
    ))
    story.append(Spacer(1, 0.55 * cm))

    link_style = ParagraphStyle(
        'MusicWishLink',
        parent=ps['muted'],
        fontSize=9,
        alignment=TA_CENTER,
        leading=12,
        wordWrap='CJK',
    )
    story.append(Paragraph(public_url, link_style))

    return build_standard_pdf(
        story,
        pagesize=A5,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.3 * cm,
        bottomMargin=1.8 * cm,
        output=output,
    )


def generate_guest_credentials_pdf(full_name, username, password, login_url, output=None):
    """
    A5-PDF mit Gast-Zugangsdaten: Portal-Kopf, Credentials-Karte, QR + Login-Link.
    """
    if output is None:
        output = BytesIO()

    usable = A5[0] - 3 * cm
    ps = pdf_paragraph_styles()
    portal = get_portal_name()
    display_name = (full_name or '').strip() or 'Gast'

    story = [
        build_standard_header(
            "Gast-Zugang",
            subtitle=portal,
            pagesize=A5,
            logo_size=2.0 * cm,
            content_width=usable,
        ),
        Spacer(1, 0.45 * cm),
        Paragraph(
            f"Zugangsdaten für <b>{display_name}</b>",
            ParagraphStyle(
                'GuestCredIntro',
                parent=ps['body'],
                fontSize=11,
                leading=14,
                alignment=TA_CENTER,
            ),
        ),
        Spacer(1, 0.4 * cm),
    ]

    label_style = ParagraphStyle(
        'GuestCredLabel',
        parent=ps['caption'],
        fontSize=8,
        textColor=PDF_COLORS['text_muted'],
        spaceAfter=1,
    )
    value_style = ParagraphStyle(
        'GuestCredValue',
        parent=ps['body'],
        fontName='Courier',
        fontSize=11,
        leading=14,
        spaceAfter=8,
    )
    password_style = ParagraphStyle(
        'GuestCredPassword',
        parent=value_style,
        fontName='Courier-Bold',
        fontSize=14,
        leading=17,
        spaceAfter=0,
    )

    cred_inner = Table(
        [
            [Paragraph('Benutzername / E-Mail', label_style)],
            [Paragraph(str(username or ''), value_style)],
            [Paragraph('Passwort', label_style)],
            [Paragraph(str(password or ''), password_style)],
        ],
        colWidths=[usable - 1.2 * cm],
    )
    cred_inner.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(RoundedBox(
        cred_inner,
        width=usable,
        padding=14,
        radius=12,
        fill_color=PDF_COLORS['zebra'],
        stroke_color=PDF_COLORS['line'],
    ))
    story.append(Spacer(1, 0.45 * cm))

    qr_bytes = generate_qr_code_bytes(login_url, box_size=8, border=2)
    qr_size = 4.2 * cm
    qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
    qr_label = ParagraphStyle(
        'GuestQrLabel',
        parent=ps['section'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=0.15 * cm,
    )
    qr_caption = ParagraphStyle(
        'GuestQrCaption',
        parent=ps['caption'],
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
        wordWrap='CJK',
    )
    qr_inner = Table(
        [
            [Paragraph('Zur Website / Login', qr_label)],
            [qr_image],
            [Paragraph(str(login_url or ''), qr_caption)],
        ],
        colWidths=[usable - 1.2 * cm],
    )
    qr_inner.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(RoundedBox(
        qr_inner,
        width=usable,
        padding=12,
        radius=12,
        fill_color=PDF_COLORS['card_bg'],
        stroke_color=PDF_COLORS['line'],
    ))
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph(
        'Zugangsdaten sicher aufbewahren und nicht weitergeben.',
        ParagraphStyle(
            'GuestCredNote',
            parent=ps['muted'],
            fontSize=8,
            alignment=TA_CENTER,
            leading=10,
        ),
    ))

    return build_standard_pdf(
        story,
        pagesize=A5,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.3 * cm,
        bottomMargin=1.8 * cm,
        output=output,
    )


def generate_borrow_receipt_pdf(borrow_transactions, output=None):
    """
    Generiert einen Ausleihschein-PDF für Checkout oder Legacy-BorrowTransactions.
    Einheitliches Layout: Logo, Titel, Tabelle, QR, Standard-Footer.
    """
    from app.models.inventory import Checkout

    styles = getSampleStyleSheet()
    ps = pdf_paragraph_styles()
    stand = datetime.now().strftime('%d.%m.%Y')

    # --- Checkout path ---
    if isinstance(borrow_transactions, Checkout):
        checkout = borrow_transactions
        story = [
            build_standard_header(
                "Ausleihschein / Packliste",
                subtitle=f"Stand: {stand}",
                pagesize=A4,
                logo_size=2.0 * cm,
            ),
            Spacer(1, 0.4 * cm),
        ]

        details_data = [
            ['Ausleihdatum', checkout.start_date.strftime('%d.%m.%Y %H:%M') if checkout.start_date else '—'],
            ['Vorgangsnummer', checkout.checkout_number],
            ['Projekt / Veranstaltung', checkout.event_name or '—'],
            ['Verantwortlicher', checkout.borrower_name or '—'],
            ['Kontakt-E-Mail', checkout.contact_email or '—'],
            ['Rückgabe bis', checkout.end_date.strftime('%d.%m.%Y %H:%M') if checkout.end_date else '—'],
            ['Status', checkout.status or '—'],
        ]
        details_table = Table(details_data, colWidths=[5.2 * cm, 6.3 * cm])
        details_table.setStyle(meta_kv_table_style())

        qr_payload = checkout.qr_code_data or generate_borrow_qr_code(checkout.checkout_number)
        top = Table([[details_table, _qr_block(qr_payload, 'Rückgabe-QR')]], colWidths=[11.8 * cm, 5.4 * cm])
        top.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(top)
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph("Ausgeliehene Artikel", ps['section']))

        items_data = [['Nr.', 'Produktname', 'ID', 'Länge', 'Zurück']]
        for idx, item in enumerate(checkout.items, 1):
            product = item.product
            length_str = _format_length(product.length) if product and product.length else '—'
            items_data.append([
                str(idx),
                Paragraph(product.name if product else '—', styles['Normal']),
                str(product.id) if product else '—',
                length_str,
                item.returned_at.strftime('%d.%m.%Y') if item.returned_at else 'unterwegs',
            ])
        items_table = Table(items_data, colWidths=[1.1 * cm, 7.2 * cm, 2.2 * cm, 2.5 * cm, 3.2 * cm], repeatRows=1)
        items_table.setStyle(standard_table_style())
        story.append(items_table)
        story.append(Spacer(1, 0.35 * cm))
        end_txt = checkout.end_date.strftime('%d.%m.%Y %H:%M') if checkout.end_date else '—'
        story.append(Paragraph(
            f"Bitte beachten Sie das Rückgabedatum: <b>{end_txt}</b>. "
            f"Der QR-Code dient zur schnellen Rückgabe am Scanner.",
            ps['muted'],
        ))
        return build_standard_pdf(story, pagesize=A4, output=output)

    # --- Legacy BorrowTransaction list ---
    if not isinstance(borrow_transactions, list):
        borrow_transactions = [borrow_transactions]
    if not borrow_transactions:
        raise ValueError("Keine Ausleihvorgänge zum Generieren des PDFs vorhanden.")

    first_transaction = borrow_transactions[0]
    borrower = first_transaction.borrower
    display_ref = first_transaction.borrow_group_id or first_transaction.transaction_number

    story = [
        build_standard_header("Ausleihschein", subtitle=f"Stand: {stand}", pagesize=A4, logo_size=2.0 * cm),
        Spacer(1, 0.4 * cm),
    ]

    details_data = [
        ['Ausleihdatum', first_transaction.borrow_date.strftime('%d.%m.%Y %H:%M')],
        ['Vorgangsnummer', display_ref],
        ['Voraussichtliche Rückgabe', first_transaction.expected_return_date.strftime('%d.%m.%Y')],
        ['Ausleiher', f"{borrower.first_name} {borrower.last_name}" if borrower else '—'],
    ]
    if borrower and borrower.email:
        details_data.append(['E-Mail', borrower.email])

    details_table = Table(details_data, colWidths=[5.2 * cm, 6.3 * cm])
    details_table.setStyle(meta_kv_table_style())

    qr_data = generate_borrow_qr_code(first_transaction.transaction_number)
    top = Table([[details_table, _qr_block(qr_data, 'Rückgabe-QR')]], colWidths=[11.8 * cm, 5.4 * cm])
    top.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(top)
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Ausgeliehene Artikel", ps['section']))

    items_data = [['Nr.', 'Produktname', 'Produkt-ID', 'Länge']]
    for idx, transaction in enumerate(borrow_transactions, 1):
        product = transaction.product
        length_str = _format_length(product.length) if product and product.length else '—'
        items_data.append([
            str(idx),
            Paragraph(product.name if product else '—', styles['Normal']),
            str(product.id) if product else '—',
            length_str,
        ])
    items_table = Table(items_data, colWidths=[1.5 * cm, 8.5 * cm, 3 * cm, 3.2 * cm], repeatRows=1)
    items_table.setStyle(standard_table_style())
    story.append(items_table)
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph(
        f"Bitte beachten Sie das voraussichtliche Rückgabedatum: "
        f"<b>{first_transaction.expected_return_date.strftime('%d.%m.%Y')}</b>.",
        ps['muted'],
    ))
    return build_standard_pdf(story, pagesize=A4, output=output)


def _append_device_style_qr_grid(story, items, *, stand, styles, get_qr_payload, get_name, continuation_title):
    """Geräte-Raster: kompakt, Logo im QR, nur Name darunter, Outline-Karten."""
    from reportlab.platypus import PageBreak

    # 4×5 = 20 Badges/Seite (vorher 3×4 = 12)
    qr_size = 2.35 * cm
    items_per_row = 4
    items_per_col = 5
    items_per_page = items_per_row * items_per_col
    col_w = 4.55 * cm
    cell_w = 4.3 * cm
    name_style = ParagraphStyle(
        'DeviceQrName', parent=styles['Normal'], fontSize=7, leading=8.5,
        alignment=TA_CENTER, fontName='Helvetica-Bold', textColor=PDF_COLORS['text'],
    )

    logo_path = get_logo_path()

    for page_start in range(0, len(items), items_per_page):
        if page_start > 0:
            story.append(PageBreak())
            story.append(build_standard_header(
                continuation_title,
                subtitle=f"Stand: {stand} · Fortsetzung",
                pagesize=A4,
                show_logo=False,
                content_width=A4[0] - 2.4 * cm,
            ))
            story.append(Spacer(1, 0.2 * cm))

        page_items = items[page_start:page_start + items_per_page]
        qr_data = []
        for row in range(items_per_col):
            row_cells = []
            for col in range(items_per_row):
                idx = row * items_per_row + col
                if idx < len(page_items):
                    item = page_items[idx]
                    qr_payload = get_qr_payload(item)
                    if logo_path:
                        qr_bytes = generate_qr_code_with_logo_bytes(
                            qr_payload, logo_path, box_size=8, border=1, logo_ratio=0.22
                        )
                    else:
                        qr_bytes = generate_qr_code_bytes(qr_payload, box_size=8, border=1)
                    qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
                    item_name = (get_name(item) or '—')[:32]
                    name_para = Paragraph(item_name, name_style)
                    cell_inner = Table(
                        [[qr_image], [Spacer(1, 0.06 * cm)], [name_para]],
                        colWidths=[cell_w - 0.3 * cm],
                    )
                    cell_inner.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 0),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                    ]))
                    row_cells.append(RoundedBox(
                        cell_inner,
                        width=cell_w,
                        padding=4,
                        radius=7,
                        fill_color=PDF_COLORS['white'],
                        stroke_color=PDF_COLORS['line'],
                    ))
                else:
                    row_cells.append('')
            qr_data.append(row_cells)

        qr_table = Table(
            qr_data,
            colWidths=[col_w] * items_per_row,
            rowHeights=[3.55 * cm] * items_per_col,
        )
        qr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(qr_table)


def generate_qr_code_sheet_pdf(products=None, output=None, label_type='cable', sets=None):
    """
    Generiert einen QR-Code-Druckbogen für Produkte und/oder Sets.
    Footer Pflicht; Seitenkopf ohne Logo; Etiketten darunter.
    """
    products = list(products or [])
    sets = list(sets or [])
    if not products and not sets:
        raise ValueError("Keine Produkte oder Sets zum Generieren des QR-Code-Druckbogens vorhanden.")

    styles = getSampleStyleSheet()
    stand = datetime.now().strftime('%d.%m.%Y')
    parts = []
    if products:
        parts.append(f"{len(products)} Artikel")
    if sets:
        parts.append(f"{len(sets)} Sets")
    if label_type == 'cable' and products:
        title = "QR-Codes (Kabel)"
    elif products and not sets:
        title = "QR-Codes (Geräte)"
    elif sets and not products:
        title = "QR-Codes (Sets)"
    else:
        title = "QR-Codes"
    content_w = A4[0] - 2.4 * cm
    story = [
        build_standard_header(
            title,
            subtitle=f"Stand: {stand} · {' · '.join(parts)}",
            pagesize=A4,
            show_logo=False,
            content_width=content_w,
        ),
        Spacer(1, 0.3 * cm),
    ]

    if products and label_type == 'cable':
        try:
            initialize_color_mappings()
        except Exception:
            pass

        LABEL_W = 8.6 * cm
        LABEL_H = 3.0 * cm
        LABELS_PER_ROW = 2
        GAP = 0.3 * cm

        rows = []
        row_data = []

        for product in products:
            stripe_hex = '#888888'
            if product.length:
                try:
                    color = get_color_for_length(product.length)
                    if color:
                        stripe_hex = color
                except Exception:
                    pass

            qr_url = generate_product_qr_code(product.id)
            qr_bytes = generate_qr_code_inverted_bytes(qr_url, box_size=6, border=2)
            label = CableLabelFlowable(product, qr_bytes, stripe_hex, LABEL_W, LABEL_H)
            row_data.append(label)

            if len(row_data) == LABELS_PER_ROW:
                rows.append(list(row_data))
                row_data = []

        if row_data:
            while len(row_data) < LABELS_PER_ROW:
                row_data.append('')
            rows.append(row_data)

        col_widths = [LABEL_W + GAP] * LABELS_PER_ROW
        row_heights = [LABEL_H + GAP] * len(rows)
        table = Table(rows, colWidths=col_widths, rowHeights=row_heights)
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(table)
    elif products:
        _append_device_style_qr_grid(
            story,
            products,
            stand=stand,
            styles=styles,
            get_qr_payload=lambda p: generate_product_qr_code(p.id),
            get_name=lambda p: p.name or f"ID {p.id}",
            continuation_title=title,
        )

    if sets:
        if products:
            from reportlab.platypus import PageBreak
            story.append(PageBreak())
            story.append(build_standard_header(
                "QR-Codes (Sets)",
                subtitle=f"Stand: {stand} · {len(sets)} Sets",
                pagesize=A4,
                show_logo=False,
                content_width=content_w,
            ))
            story.append(Spacer(1, 0.25 * cm))
        _append_device_style_qr_grid(
            story,
            sets,
            stand=stand,
            styles=styles,
            get_qr_payload=lambda s: generate_set_qr_code(s.id),
            get_name=lambda s: s.name or f"Set {s.id}",
            continuation_title="QR-Codes (Sets)",
        )

    return build_standard_pdf(
        story,
        pagesize=A4,
        leftMargin=0.7 * cm,
        rightMargin=0.7 * cm,
        topMargin=1.2 * cm,
        bottomMargin=2.0 * cm,
        output=output,
    )


def generate_inventory_list_pdf(products, output=None):
    """Inventurliste als PDF im Standard-Layout."""
    styles = getSampleStyleSheet()
    products = products or []
    stand = datetime.now().strftime('%d.%m.%Y')
    story = [
        build_standard_header(
            "Inventurliste",
            subtitle=f"Stand: {stand} · {len(products)} Produkte",
            pagesize=A4,
            logo_size=2.0 * cm,
        ),
        Spacer(1, 0.35 * cm),
    ]

    if not products:
        story.append(Paragraph("Keine Produkte vorhanden.", styles['Normal']))
        return build_standard_pdf(story, pagesize=A4, output=output)

    table_data = [["#", "Name", "ID", "Kategorie", "Standort", "Status"]]
    for idx, product in enumerate(products, 1):
        table_data.append([
            str(idx),
            Paragraph(getattr(product, "name", None) or "—", styles['Normal']),
            str(getattr(product, "id", "—")),
            getattr(product, "category", None) or "—",
            Paragraph(getattr(product, "location", None) or "—", styles['Normal']),
            getattr(product, "status", None) or "—",
        ])

    table = Table(table_data, colWidths=[1 * cm, 5.5 * cm, 1.8 * cm, 3.2 * cm, 3.5 * cm, 2.2 * cm], repeatRows=1)
    table.setStyle(standard_table_style())
    story.append(table)
    return build_standard_pdf(story, pagesize=A4, output=output)


def generate_inventory_tool_pdf(inventory, items, output=None):
    """Inventur-Export als PDF im Standard-Layout."""
    styles = getSampleStyleSheet()
    items = items or []
    stand = datetime.now().strftime('%d.%m.%Y')
    title = f"Inventur: {getattr(inventory, 'name', 'Unbenannt')}"
    story = [
        build_standard_header(title, subtitle=f"Stand: {stand}", pagesize=A4, logo_size=2.0 * cm),
        Spacer(1, 0.3 * cm),
    ]

    started = getattr(inventory, "started_at", None)
    completed = getattr(inventory, "completed_at", None)
    meta_rows = [
        ["Status", getattr(inventory, "status", None) or "—"],
        ["Gestartet", started.strftime("%d.%m.%Y %H:%M") if started else "—"],
        ["Abgeschlossen", completed.strftime("%d.%m.%Y %H:%M") if completed else "—"],
        ["Positionen", str(len(items))],
    ]
    meta = Table(meta_rows, colWidths=[4 * cm, 12 * cm])
    meta.setStyle(meta_kv_table_style())
    story.extend([meta, Spacer(1, 0.35 * cm)])

    table_data = [["Produkt", "Geprüft", "Neuer Standort", "Neuer Zustand", "Geprüft von"]]
    for item in items:
        product = getattr(item, "product", None)
        checker = getattr(item, "checker", None)
        checker_name = "—"
        if checker:
            checker_name = getattr(checker, "full_name", None) or getattr(checker, "username", "—")
        checked = getattr(item, "checked", None)
        if checked is None:
            checked = getattr(item, "is_counted", False)
        table_data.append([
            Paragraph(getattr(product, "name", None) or "—", styles['Normal']),
            "Ja" if checked else "Nein",
            Paragraph(
                getattr(item, "new_location", None)
                or (getattr(product, "location", None) if product else None)
                or "—",
                styles['Normal'],
            ),
            getattr(item, "new_condition", None)
            or (getattr(product, "condition", None) if product else None)
            or "—",
            checker_name,
        ])

    table = Table(table_data, colWidths=[4.5 * cm, 1.8 * cm, 3.8 * cm, 3 * cm, 3.1 * cm], repeatRows=1)
    table.setStyle(standard_table_style())
    story.append(table)
    return build_standard_pdf(story, pagesize=A4, output=output)


def generate_return_confirmation_pdf(borrow_transaction, output=None, returned_items=None):
    """Kompakte Rückgabe-Bestätigung im Standard-Layout (optional mit QR + Artikelliste)."""
    from app.utils.common import portal_now_naive

    styles = getSampleStyleSheet()
    ps = pdf_paragraph_styles()
    stand = datetime.now().strftime('%d.%m.%Y')
    story = [
        build_standard_header("Rückgabeschein", subtitle=f"Stand: {stand}", pagesize=A4, logo_size=2.0 * cm),
        Spacer(1, 0.35 * cm),
    ]

    # CheckoutItem / Checkout compat
    from app.models.inventory import Checkout, CheckoutItem
    items_for_table = None
    if isinstance(borrow_transaction, Checkout):
        checkout = borrow_transaction
        items_for_table = (
            list(returned_items) if returned_items is not None else list(checkout.returned_items or [])
        )
        return_date = portal_now_naive()
        if items_for_table:
            first_returned = getattr(items_for_table[0], 'returned_at', None)
            if first_returned:
                return_date = first_returned
        rows = [
            ["Vorgangsnummer", checkout.checkout_number],
            ["Projekt", checkout.event_name or "—"],
            ["Verantwortlicher", checkout.borrower_name or "—"],
            ["Status", checkout.status or "—"],
            ["Bestätigt am", return_date.strftime("%d.%m.%Y %H:%M")],
            ["Artikel", str(len(items_for_table))],
        ]
        qr_payload = checkout.qr_code_data or generate_borrow_qr_code(checkout.checkout_number)
    elif isinstance(borrow_transaction, CheckoutItem):
        item = borrow_transaction
        checkout = item.checkout
        product = item.product
        return_date = item.returned_at or portal_now_naive()
        items_for_table = list(returned_items) if returned_items is not None else [item]
        rows = [
            ["Vorgangsnummer", checkout.checkout_number if checkout else "—"],
            ["Produkt", getattr(product, "name", None) or "—"],
            ["Verantwortlicher", checkout.borrower_name if checkout else "—"],
            ["Rückgabedatum", return_date.strftime("%d.%m.%Y %H:%M")],
        ]
        qr_payload = (checkout.qr_code_data if checkout else None) or (
            generate_product_qr_code(product.id) if product else None
        )
    else:
        borrower = getattr(borrow_transaction, "borrower", None)
        product = getattr(borrow_transaction, "product", None)
        borrower_name = getattr(borrower, "full_name", "—") if borrower else "—"
        product_name = getattr(product, "name", "—") if product else "—"
        return_date = getattr(borrow_transaction, "actual_return_date", None) or portal_now_naive()
        txn = getattr(borrow_transaction, "transaction_number", "—")
        rows = [
            ["Vorgangsnummer", txn],
            ["Ausleiher", borrower_name],
            ["Produkt", product_name],
            ["Rückgabedatum", return_date.strftime("%d.%m.%Y %H:%M")],
        ]
        qr_payload = generate_borrow_qr_code(txn) if txn and txn != "—" else None
        if returned_items is not None:
            items_for_table = list(returned_items)

    details = Table(rows, colWidths=[5 * cm, 6.5 * cm])
    details.setStyle(meta_kv_table_style())

    if qr_payload:
        layout = Table([[details, _qr_block(qr_payload, 'Beleg-QR', size=3.6 * cm)]], colWidths=[11.8 * cm, 5.4 * cm])
        layout.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(layout)
    else:
        story.append(details)

    if items_for_table:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph("Zurückgegebene Artikel", ps['section']))
        items_data = [['Nr.', 'Produktname', 'ID', 'Länge', 'Rückgabe']]
        for idx, item in enumerate(items_for_table, 1):
            product = getattr(item, 'product', None)
            length_str = (
                _format_length(product.length)
                if product and getattr(product, 'length', None)
                else '—'
            )
            returned_at = getattr(item, 'returned_at', None)
            items_data.append([
                str(idx),
                Paragraph(getattr(product, 'name', None) or '—', styles['Normal']),
                str(getattr(product, 'id', None) or getattr(item, 'product_id', '—')),
                length_str,
                returned_at.strftime('%d.%m.%Y %H:%M') if returned_at else '—',
            ])
        items_table = Table(
            items_data,
            colWidths=[1.1 * cm, 7.2 * cm, 2.2 * cm, 2.5 * cm, 3.2 * cm],
            repeatRows=1,
        )
        items_table.setStyle(standard_table_style())
        story.append(items_table)
        story.append(Spacer(1, 0.35 * cm))
        story.append(Paragraph(
            "Diese Liste enthält die bei diesem Vorgang zurückgegebenen Artikel "
            "(auch bei Teilerückgabe).",
            ps['muted'],
        ))

    return build_standard_pdf(story, pagesize=A4, output=output)
