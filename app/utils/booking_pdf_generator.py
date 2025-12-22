from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from flask import current_app
from io import BytesIO
from datetime import datetime
import os
import re
from app.utils.pdf_generator import get_logo_path


def generate_booking_request_pdf(booking_request, output=None):
    """
    Generiert ein PDF für eine Buchungsanfrage mit benutzerdefiniertem Text.
    
    Args:
        booking_request: BookingRequest Objekt
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Header mit Logos
    logo_path = get_logo_path()
    secondary_logo_path = booking_request.form.secondary_logo_path
    
    # Erstelle Logo-Tabelle (zwei Spalten wenn beide Logos vorhanden)
    if logo_path and secondary_logo_path:
        # Beide Logos nebeneinander
        logo_table_data = []
        logo_row = []
        
        try:
            logo1 = Image(logo_path, width=3*cm, height=3*cm, kind='proportional')
            logo_row.append(logo1)
        except Exception as e:
            current_app.logger.warning(f"Konnte primäres Logo nicht laden: {e}")
            logo_row.append(Paragraph("", styles['Normal']))
        
        try:
            logo2 = Image(secondary_logo_path, width=3*cm, height=3*cm, kind='proportional')
            logo_row.append(logo2)
        except Exception as e:
            current_app.logger.warning(f"Konnte optionales 2. Logo nicht laden: {e}")
            logo_row.append(Paragraph("", styles['Normal']))
        
        logo_table_data.append(logo_row)
        logo_table = Table(logo_table_data, colWidths=[9*cm, 9*cm])
        logo_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(logo_table)
    elif logo_path:
        # Nur primäres Logo
        try:
            logo = Image(logo_path, width=3*cm, height=3*cm, kind='proportional')
            story.append(logo)
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    elif secondary_logo_path:
        # Nur sekundäres Logo
        try:
            logo = Image(secondary_logo_path, width=3*cm, height=3*cm, kind='proportional')
            story.append(logo)
        except Exception as e:
            current_app.logger.warning(f"Konnte optionales 2. Logo nicht laden: {e}")
    
    story.append(Spacer(1, 0.5*cm))
    
    # Titel (wird immer übernommen)
    title_style = ParagraphStyle(
        'BookingTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=10
    )
    story.append(Paragraph(booking_request.form.title, title_style))
    story.append(Spacer(1, 0.8*cm))
    
    # Benutzerdefinierter PDF-Text mit Platzhaltern
    form = booking_request.form
    if form.pdf_application_text:
        # Bereite Platzhalter vor
        replacements = {}
        
        # Antragsteller - Name aus dem Formular
        applicant_name = booking_request.applicant_name if booking_request.applicant_name else booking_request.email.split('@')[0] if '@' in booking_request.email else booking_request.email
        replacements['{applicant}'] = applicant_name
        
        # Zeitraum
        time_range = ""
        if booking_request.event_date:
            date_str = booking_request.event_date.strftime('%d.%m.%Y')
            if booking_request.event_start_time and booking_request.event_end_time:
                time_range = f"{date_str} von {booking_request.event_start_time.strftime('%H:%M')} Uhr bis {booking_request.event_end_time.strftime('%H:%M')} Uhr"
            elif booking_request.event_start_time:
                time_range = f"{date_str} ab {booking_request.event_start_time.strftime('%H:%M')} Uhr"
            else:
                time_range = date_str
        replacements['{time_range}'] = time_range
        
        # Zustimmungsrollen (durchnummeriert ab 1) - zeigt nur den Namen der Person
        roles = sorted(form.roles, key=lambda r: r.role_order)
        for idx, role in enumerate(roles, start=1):
            approval = None
            for appr in booking_request.approvals:
                if appr.role_id == role.id:
                    approval = appr
                    break
            
            role_text = ""  # Leer wenn noch keine Zustimmung
            if approval:
                if approval.status == 'approved' and approval.approver:
                    role_text = approval.approver.full_name
                elif approval.status == 'rejected' and approval.approver:
                    role_text = approval.approver.full_name
            
            # Unterstütze verschiedene Schreibweisen des Platzhalters
            replacements[f'{{role_{idx}}}'] = role_text
            replacements[f'{{Role_{idx}}}'] = role_text
            replacements[f'{{ROLE_{idx}}}'] = role_text
            replacements[f'{{role {idx}}}'] = role_text
            replacements[f'{{Role {idx}}}'] = role_text
            replacements[f'{{ROLE {idx}}}'] = role_text
            replacements[f'{{role{idx}}}'] = role_text
            replacements[f'{{Role{idx}}}'] = role_text
            replacements[f'{{ROLE{idx}}}'] = role_text
        
        # Status - zeigt ob der Antrag angenommen oder abgelehnt wurde
        status_text = "Ausstehend"
        
        # Prüfe ob jemand abgelehnt hat (wenn ja, ist der Antrag abgelehnt)
        is_rejected = False
        for role in roles:
            approval = None
            for appr in booking_request.approvals:
                if appr.role_id == role.id:
                    approval = appr
                    break
            
            if approval and approval.status == 'rejected':
                is_rejected = True
                break  # Sobald einer ablehnt, ist der Antrag abgelehnt
        
        if is_rejected:
            status_text = "Abgelehnt"
        elif booking_request.status == 'accepted':
            status_text = "Angenommen"
        
        # Setze Platzhalter
        replacements['{status}'] = status_text
        # Alte Platzhalter für Rückwärtskompatibilität (falls noch verwendet)
        replacements['{approved}'] = "Angenommen" if booking_request.status == 'accepted' else "Nicht angenommen"
        replacements['{rejected}'] = "Abgelehnt" if is_rejected else "Nicht abgelehnt"
        
        # Ersetze alle Platzhalter im Text
        pdf_text = form.pdf_application_text
        
        # Ersetze alle definierten Platzhalter
        for placeholder, value in replacements.items():
            pdf_text = pdf_text.replace(placeholder, str(value))
        
        # Zusätzlich: Ersetze Rollen-Platzhalter in verschiedenen Schreibweisen (case-insensitive)
        # Unterstützt: {role_1}, {Role_1}, {ROLE_1}, {role 1}, {Role 1}, {role1}, {Role1}, etc.
        roles = sorted(form.roles, key=lambda r: r.role_order)
        for idx, role in enumerate(roles, start=1):
            approval = None
            for appr in booking_request.approvals:
                if appr.role_id == role.id:
                    approval = appr
                    break
            
            role_text = ""
            if approval:
                if approval.status == 'approved' and approval.approver:
                    role_text = approval.approver.full_name
                elif approval.status == 'rejected' and approval.approver:
                    role_text = approval.approver.full_name
            
            # Ersetze alle Varianten des Platzhalters (case-insensitive, mit/ohne Leerzeichen, mit/ohne Unterstrich)
            # Pattern: {role_1}, {role 1}, {role1}, {Role_1}, {Role 1}, {Role1}, etc.
            pattern = rf'\{{[Rr][Oo][Ll][Ee][_\s]*{idx}\}}'
            pdf_text = re.sub(pattern, role_text, pdf_text)
        
        # Konvertiere Zeilenumbrüche zu HTML <br/> Tags für Paragraph
        # Paragraph unterstützt HTML-ähnliche Tags, aber nicht \n
        pdf_text = pdf_text.replace('\n', '<br/>')
        
        # Rendere den Text als Paragraph (Paragraph unterstützt HTML-ähnliche Tags)
        text_style = ParagraphStyle(
            'PDFText',
            parent=styles['Normal'],
            fontSize=11,
            alignment=TA_LEFT,
            spaceAfter=15,
            leading=16
        )
        story.append(Paragraph(pdf_text, text_style))
    
    # Footer mit Erstellungsdatum
    story.append(Spacer(1, 1*cm))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    footer_text = f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    story.append(Paragraph(footer_text, footer_style))
    
    # PDF bauen
    doc.build(story)
    
    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    
    return output
