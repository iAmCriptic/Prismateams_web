import html
from collections import OrderedDict
from datetime import datetime

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from app.utils.pdf_generator import (
    PDF_COLORS,
    RoundedBox,
    build_standard_header,
    build_standard_pdf,
    pdf_paragraph_styles,
    standard_table_style,
)


def _esc(val):
    """Sicheres XML/HTML-Escaping für ReportLab-Paragraphs."""
    if val is None:
        return ""
    return html.escape(str(val))


def generate_single_event_pdf(event_obj):
    """
    Vollständiges, professionelles PDF-Layout für eine Veranstaltung.
    Beinhaltet alle Informationen:
    - Stammdaten & Basis-Infos (Name, Zeitraum, Hauptort, Verantwortliche, Status, Beschreibung)
    - Infos zur Veranstaltung (Benutzerdefinierte Felder nach Kategorien)
    - Tage & Termine (Ablauf, Start-/Endzeiten, Locations, Notizen, Zeitplan-Punkte)
    - Personen, Kontakte & Helfer (Ansprechpartner, Personalzuweisungen)
    - Verknüpfte Module & Ressourcen (Booking-Events, Kanban, Ordner & Dateien, Externe Links)
    - ToDo-Listen & Aufgaben (Fortschritt, Aufgabenstatus, Zuständigkeiten, Fälligkeiten)
    - Materialbedarf & Inventar (Artikel, Mengen, zugeordnete Termine)
    """
    styles = getSampleStyleSheet()
    ps = pdf_paragraph_styles()

    title_section_style = ParagraphStyle(
        'EventPdfSection',
        parent=ps['section'],
        fontSize=11,
        leading=14,
        fontName='Helvetica-Bold',
        textColor=PDF_COLORS['text'],
        spaceBefore=0.25 * cm,
        spaceAfter=0.15 * cm,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        'SingleBody',
        parent=ps['body'],
        fontSize=9,
        leading=12,
        textColor=PDF_COLORS['text'],
    )
    bold_label_style = ParagraphStyle(
        'BoldLabel',
        parent=ps['body'],
        fontSize=9,
        leading=12,
        fontName='Helvetica-Bold',
        textColor=PDF_COLORS['text_secondary'],
    )
    muted_style = ParagraphStyle(
        'SingleMuted',
        parent=ps['muted'],
        fontSize=8.5,
        leading=11,
        textColor=PDF_COLORS['text_muted'],
    )

    stand_date = datetime.now().strftime('%d.%m.%Y %H:%M')
    subtitle_type = "Mehrtägige Veranstaltung" if event_obj.is_multiday else "Eintägige Veranstaltung"
    if event_obj.is_archived:
        subtitle_type += " · Archiviert"

    story = [
        build_standard_header(
            event_obj.name,
            subtitle=f"{subtitle_type} | Stand: {stand_date}",
            pagesize=A4,
        ),
        Spacer(1, 0.3 * cm),
    ]

    # ---------------------------------------------------------
    # 1. STAMMDATEN & BASIS-INFORMATIONEN
    # ---------------------------------------------------------
    date_str = "-"
    if event_obj.is_multiday and event_obj.start_date and event_obj.end_date:
        date_str = f"{event_obj.start_date.strftime('%d.%m.%Y')} – {event_obj.end_date.strftime('%d.%m.%Y')}"
    elif event_obj.days:
        first_d = min(d.date for d in event_obj.days)
        last_d = max(d.date for d in event_obj.days)
        date_str = first_d.strftime('%d.%m.%Y') if first_d == last_d else f"{first_d.strftime('%d.%m.%Y')} – {last_d.strftime('%d.%m.%Y')}"
    elif event_obj.appointments:
        first_a = min(a.start_time for a in event_obj.appointments)
        last_a = max(a.end_time for a in event_obj.appointments)
        date_str = f"{first_a.strftime('%d.%m.%Y %H:%M')} – {last_a.strftime('%d.%m.%Y %H:%M')}"

    owner_name = event_obj.owner.full_name if event_obj.owner else (event_obj.creator.full_name if event_obj.creator else '-')

    meta_data = [
        [
            Paragraph("<b>Veranstaltungsname:</b>", bold_label_style),
            Paragraph(_esc(event_obj.name), body_style),
            Paragraph("<b>Hauptverantwortlich:</b>", bold_label_style),
            Paragraph(_esc(owner_name), body_style),
        ],
        [
            Paragraph("<b>Zeitraum / Datum:</b>", bold_label_style),
            Paragraph(_esc(date_str), body_style),
            Paragraph("<b>Hauptort / Location:</b>", bold_label_style),
            Paragraph(_esc(event_obj.default_location or "-"), body_style),
        ],
        [
            Paragraph("<b>Beschreibung:</b>", bold_label_style),
            Paragraph(_esc(event_obj.description or "-"), body_style),
            Paragraph("<b>Status:</b>", bold_label_style),
            Paragraph("Archiviert" if event_obj.is_archived else "Aktiv", body_style),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[3.8 * cm, 4.9 * cm, 3.8 * cm, 4.9 * cm])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, -1), PDF_COLORS['white']),
        ('BOX', (0, 0), (-1, -1), 0.6, PDF_COLORS['line']),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, PDF_COLORS['line_soft']),
    ]))
    story.append(meta_table)

    # ---------------------------------------------------------
    # 2. INFOS ZUR VERANSTALTUNG (BENUTZERDEFINIERTE FELDER)
    # ---------------------------------------------------------
    try:
        from app.models.event import EventCustomField
        from app.models.user import User

        custom_fields = EventCustomField.query.filter_by(is_active=True).order_by(EventCustomField.position, EventCustomField.id).all()
        custom_values = event_obj.custom_values_dict

        users_by_id = {}
        try:
            all_users = User.query.filter_by(is_active=True).all()
            users_by_id = {u.id: u.full_name for u in all_users}
        except Exception:
            pass

        if custom_fields:
            categories_dict = OrderedDict()
            for f in custom_fields:
                cat = f.category or 'Allgemein'
                if cat in ('Sicherheit', 'Allgemein & Vorverkauf') or 'sicherheit' in cat.lower():
                    cat = 'Allgemein'
                if cat not in categories_dict:
                    categories_dict[cat] = []
                categories_dict[cat].append(f)

            for cat, f_list in categories_dict.items():
                cat_rows = []
                # 2 Felder pro Zeile für kompakte, übersichtliche Darstellung
                for i in range(0, len(f_list), 2):
                    f1 = f_list[i]
                    val1 = custom_values.get(f1.id)
                    str1 = _format_custom_field_value(f1, val1, users_by_id)

                    if i + 1 < len(f_list):
                        f2 = f_list[i + 1]
                        val2 = custom_values.get(f2.id)
                        str2 = _format_custom_field_value(f2, val2, users_by_id)
                    else:
                        f2 = None
                        str2 = ""

                    cat_rows.append([
                        Paragraph(f"<b>{_esc(f1.label)}:</b>", bold_label_style),
                        Paragraph(_esc(str1), body_style),
                        Paragraph(f"<b>{_esc(f2.label)}:</b>" if f2 else "", bold_label_style),
                        Paragraph(_esc(str2) if f2 else "", body_style),
                    ])

                if cat_rows:
                    story.append(Spacer(1, 0.25 * cm))
                    story.append(Paragraph(f"Infos zur Veranstaltung · {_esc(cat)}", title_section_style))
                    t_cat = Table(cat_rows, colWidths=[4.0 * cm, 4.7 * cm, 4.0 * cm, 4.7 * cm])
                    t_cat.setStyle(standard_table_style(header=False))
                    story.append(t_cat)
    except Exception:
        pass

    # ---------------------------------------------------------
    # 3. TAGE & TERMINE (ABLAUF & ZEITPLAN)
    # ---------------------------------------------------------
    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph("Tage, Termine & Zeitplan", title_section_style))

    if event_obj.days:
        for day in event_obj.days:
            day_label = day.label or f"Tag {day.day_number}"
            d_date = day.date.strftime('%d.%m.%Y')
            time_parts = []
            if day.start_time:
                time_parts.append(day.start_time.strftime('%H:%M'))
            if day.end_time:
                time_parts.append(day.end_time.strftime('%H:%M'))
            time_str = f" ({' – '.join(time_parts)} Uhr)" if time_parts else ""
            loc_str = f" | Ort: {day.location}" if day.location else (f" | Ort: {event_obj.default_location}" if event_obj.default_location else "")

            day_header_text = f"<b>{_esc(day_label)}</b> · {_esc(d_date)}{_esc(time_str)}{_esc(loc_str)}"
            story.append(Paragraph(day_header_text, bold_label_style))
            if day.notes:
                story.append(Paragraph(f"<i>Notizen:</i> {_esc(day.notes)}", muted_style))

            day_appts = list(day.appointments)
            if day_appts:
                day_table_data = [[
                    Paragraph("<b>Termin / Phase</b>", bold_label_style),
                    Paragraph("<b>Start</b>", bold_label_style),
                    Paragraph("<b>Ende</b>", bold_label_style),
                    Paragraph("<b>Ort</b>", bold_label_style),
                    Paragraph("<b>Details / Notizen</b>", bold_label_style),
                ]]
                for a in day_appts:
                    day_table_data.append([
                        Paragraph(_esc(a.label), body_style),
                        Paragraph(a.start_time.strftime('%H:%M'), body_style),
                        Paragraph(a.end_time.strftime('%H:%M'), body_style),
                        Paragraph(_esc(a.location or day.location or event_obj.default_location or '-'), body_style),
                        Paragraph(_esc(a.description or '-'), body_style),
                    ])
                t_day = Table(day_table_data, colWidths=[4.2 * cm, 2.0 * cm, 2.0 * cm, 4.2 * cm, 5.0 * cm])
                t_day.setStyle(standard_table_style())
                story.append(Spacer(1, 0.1 * cm))
                story.append(t_day)

            story.append(Spacer(1, 0.15 * cm))

        # Nicht-zugeordnete Termine (falls vorhanden)
        standalone_appts = [a for a in event_obj.appointments if not a.day_id]
        if standalone_appts:
            story.append(Paragraph("<b>Weitere Termine:</b>", bold_label_style))
            st_data = [[
                Paragraph("<b>Termin</b>", bold_label_style),
                Paragraph("<b>Start</b>", bold_label_style),
                Paragraph("<b>Ende</b>", bold_label_style),
                Paragraph("<b>Ort</b>", bold_label_style),
                Paragraph("<b>Details</b>", bold_label_style),
            ]]
            for a in standalone_appts:
                st_data.append([
                    Paragraph(_esc(a.label), body_style),
                    Paragraph(a.start_time.strftime('%d.%m.%Y %H:%M'), body_style),
                    Paragraph(a.end_time.strftime('%d.%m.%Y %H:%M'), body_style),
                    Paragraph(_esc(a.location or event_obj.default_location or '-'), body_style),
                    Paragraph(_esc(a.description or '-'), body_style),
                ])
            t_st = Table(st_data, colWidths=[4.2 * cm, 3.0 * cm, 3.0 * cm, 3.6 * cm, 3.6 * cm])
            t_st.setStyle(standard_table_style())
            story.append(Spacer(1, 0.1 * cm))
            story.append(t_st)
            story.append(Spacer(1, 0.15 * cm))
    elif event_obj.appointments:
        appt_data = [[
            Paragraph("<b>Termin</b>", bold_label_style),
            Paragraph("<b>Start</b>", bold_label_style),
            Paragraph("<b>Ende</b>", bold_label_style),
            Paragraph("<b>Ort</b>", bold_label_style),
            Paragraph("<b>Details</b>", bold_label_style),
        ]]
        for a in event_obj.appointments:
            appt_data.append([
                Paragraph(_esc(a.label), body_style),
                Paragraph(a.start_time.strftime('%d.%m.%Y %H:%M'), body_style),
                Paragraph(a.end_time.strftime('%d.%m.%Y %H:%M'), body_style),
                Paragraph(_esc(a.location or event_obj.default_location or '-'), body_style),
                Paragraph(_esc(a.description or '-'), body_style),
            ])
        t_appts = Table(appt_data, colWidths=[4.2 * cm, 3.0 * cm, 3.0 * cm, 3.6 * cm, 3.6 * cm])
        t_appts.setStyle(standard_table_style())
        story.append(t_appts)
        story.append(Spacer(1, 0.15 * cm))
    else:
        story.append(Paragraph("<i>Keine Termine hinterlegt.</i>", muted_style))

    # Zeitplan-Punkte
    if event_obj.timeline_items:
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph("<b>Detaillierter Zeitplan & Ablauf:</b>", bold_label_style))
        tl_data = [[
            Paragraph("<b>Zeitpunkt</b>", bold_label_style),
            Paragraph("<b>Programmpunkt / Titel</b>", bold_label_style),
            Paragraph("<b>Zugehöriger Termin</b>", bold_label_style),
        ]]
        for item in event_obj.timeline_items:
            time_part = item.starts_at.strftime('%d.%m. %H:%M') if item.starts_at else '-'
            if item.ends_at:
                time_part += f" – {item.ends_at.strftime('%H:%M')}"
            appt_lbl = item.appointment.label if item.appointment else '-'
            tl_data.append([
                Paragraph(time_part, body_style),
                Paragraph(_esc(item.title) + (f"<br/><font color='#6c757d'>{_esc(item.description)}</font>" if item.description else ""), body_style),
                Paragraph(_esc(appt_lbl), body_style),
            ])
        t_tl = Table(tl_data, colWidths=[4.0 * cm, 9.4 * cm, 4.0 * cm])
        t_tl.setStyle(standard_table_style())
        story.append(Spacer(1, 0.1 * cm))
        story.append(t_tl)

    # ---------------------------------------------------------
    # 4. PERSONEN, KONTAKTE & PERSONAL
    # ---------------------------------------------------------
    has_contacts = bool(event_obj.contacts)
    has_assignments = bool(event_obj.assignments)
    if has_contacts or has_assignments:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Personen, Kontakte & Personal", title_section_style))

        if has_contacts:
            story.append(Paragraph("<b>Ansprechpartner:</b>", bold_label_style))
            contact_data = [[
                Paragraph("<b>Name</b>", bold_label_style),
                Paragraph("<b>Rolle / Funktion</b>", bold_label_style),
                Paragraph("<b>Telefon</b>", bold_label_style),
                Paragraph("<b>E-Mail</b>", bold_label_style),
            ]]
            for c in event_obj.contacts:
                contact_data.append([
                    Paragraph(_esc(c.name), body_style),
                    Paragraph(_esc(c.role or '-'), body_style),
                    Paragraph(_esc(c.phone or '-'), body_style),
                    Paragraph(_esc(c.email or '-'), body_style),
                ])
            t_contacts = Table(contact_data, colWidths=[4.5 * cm, 4.2 * cm, 4.2 * cm, 4.5 * cm])
            t_contacts.setStyle(standard_table_style())
            story.append(Spacer(1, 0.1 * cm))
            story.append(t_contacts)
            story.append(Spacer(1, 0.15 * cm))

        if has_assignments:
            story.append(Paragraph("<b>Personal- & Helferzuweisungen:</b>", bold_label_style))
            assign_data = [[
                Paragraph("<b>Name / Helfer</b>", bold_label_style),
                Paragraph("<b>Rolle / Bereich</b>", bold_label_style),
            ]]
            for a in event_obj.assignments:
                name = a.user.full_name if a.user else (a.display_name or '-')
                assign_data.append([
                    Paragraph(_esc(name), body_style),
                    Paragraph(_esc(a.role or '-'), body_style),
                ])
            t_assign = Table(assign_data, colWidths=[8.7 * cm, 8.7 * cm])
            t_assign.setStyle(standard_table_style())
            story.append(Spacer(1, 0.1 * cm))
            story.append(t_assign)
            story.append(Spacer(1, 0.15 * cm))

    # ---------------------------------------------------------
    # 5. VERKNÜPFTE MODULE & RESSOURCEN (BOOKING, KANBAN, DATEIEN, LINKS)
    # ---------------------------------------------------------
    files_list = []
    if event_obj.folder_id:
        try:
            from app.models.file import File
            files_list = File.query.filter_by(
                folder_id=event_obj.folder_id,
                deleted_at=None,
                is_current=True,
            ).order_by(File.name).all()
        except Exception:
            files_list = []

    has_links = bool(event_obj.links)
    has_modules = bool(event_obj.kanban_board or event_obj.folder or event_obj.booking_personal_links)
    if has_modules or has_links or files_list:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Verknüpfte Module & Ressourcen", title_section_style))
        mod_data = [[
            Paragraph("<b>Bereich / Modul</b>", bold_label_style),
            Paragraph("<b>Verknüpfte Inhalte & Details</b>", bold_label_style),
        ]]

        if event_obj.booking_personal_links:
            b_names = [l.booking_personal_event.name for l in event_obj.booking_personal_links if l.booking_personal_event]
            mod_data.append([
                Paragraph("<b>Booking-Listen</b>", bold_label_style),
                Paragraph(_esc(", ".join(b_names) if b_names else '-'), body_style),
            ])

        if event_obj.kanban_board:
            k_text = _esc(event_obj.kanban_board.title)
            if event_obj.kanban_card:
                k_text += f" (Karte: {_esc(event_obj.kanban_card.title)})"
            mod_data.append([
                Paragraph("<b>Kanban-Board</b>", bold_label_style),
                Paragraph(k_text, body_style),
            ])

        if event_obj.folder:
            f_text = f"<b>Ordner:</b> {_esc(event_obj.folder.name)}"
            if files_list:
                f_names = [_esc(f.name) for f in files_list[:15]]
                if len(files_list) > 15:
                    f_names.append(f"... (+{len(files_list) - 15} weitere)")
                f_text += "<br/><font color='#6c757d'>" + ", ".join(f_names) + "</font>"
            mod_data.append([
                Paragraph("<b>Dateiordner & Dateien</b>", bold_label_style),
                Paragraph(f_text, body_style),
            ])

        if event_obj.links:
            links_text = "<br/>".join([f"• <b>{_esc(l.title)}:</b> {_esc(l.url)}" for l in event_obj.links])
            mod_data.append([
                Paragraph("<b>Externe Links</b>", bold_label_style),
                Paragraph(links_text, body_style),
            ])

        if len(mod_data) > 1:
            t_mods = Table(mod_data, colWidths=[4.8 * cm, 12.6 * cm])
            t_mods.setStyle(standard_table_style())
            story.append(Spacer(1, 0.1 * cm))
            story.append(t_mods)
            story.append(Spacer(1, 0.15 * cm))

    # ---------------------------------------------------------
    # 6. TODO-LISTEN & AUFGABEN
    # ---------------------------------------------------------
    if event_obj.todo_lists:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("ToDo-Listen & Aufgaben", title_section_style))
        for tl in event_obj.todo_lists:
            day_ref = f" · {tl.day.label or ('Tag ' + str(tl.day.day_number))}" if tl.day else " · Gesamte Veranstaltung"
            prog_text = f"<b>{_esc(tl.title)}</b>{_esc(day_ref)} <font color='#6c757d'>({tl.completed_count}/{tl.total_count} erledigt – {tl.progress_percent}%)</font>"
            story.append(Paragraph(prog_text, bold_label_style))

            if tl.items:
                todo_data = [[
                    Paragraph("<b>Status</b>", bold_label_style),
                    Paragraph("<b>Aufgabe</b>", bold_label_style),
                    Paragraph("<b>Zugewiesen an</b>", bold_label_style),
                    Paragraph("<b>Fälligkeit</b>", bold_label_style),
                ]]
                for item in tl.items:
                    status_str = "[x] Erledigt" if item.is_completed else "[  ] Offen"
                    status_color = "#198754" if item.is_completed else "#6c757d"
                    due_str = "-"
                    if item.due_date and item.due_time:
                        due_str = f"{item.due_date.strftime('%d.%m.')} {item.due_time.strftime('%H:%M')} Uhr"
                    elif item.due_date:
                        due_str = item.due_date.strftime('%d.%m.')
                    assignee_str = item.assigned_to.full_name if item.assigned_to else '-'

                    todo_data.append([
                        Paragraph(f"<font color='{status_color}'><b>{status_str}</b></font>", body_style),
                        Paragraph(_esc(item.title), body_style),
                        Paragraph(_esc(assignee_str), body_style),
                        Paragraph(_esc(due_str), body_style),
                    ])
                t_todo = Table(todo_data, colWidths=[2.8 * cm, 7.6 * cm, 4.0 * cm, 3.0 * cm])
                t_todo.setStyle(standard_table_style())
                story.append(Spacer(1, 0.1 * cm))
                story.append(t_todo)
            else:
                story.append(Paragraph("<i>Keine Aufgaben in dieser Liste.</i>", muted_style))

            story.append(Spacer(1, 0.15 * cm))

    # ---------------------------------------------------------
    # 7. MATERIALBEDARF & INVENTAR
    # ---------------------------------------------------------
    materials_rows = []
    for appointment in event_obj.appointments:
        for need in appointment.inventory_needs:
            p_name = need.product.name if need.product else f'Produkt #{need.product_id}'
            materials_rows.append((p_name, need.quantity, appointment.label))

    if materials_rows:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Materialbedarf & Inventar", title_section_style))
        mat_data = [[
            Paragraph("<b>Artikel / Produkt</b>", bold_label_style),
            Paragraph("<b>Menge</b>", bold_label_style),
            Paragraph("<b>Termin / Bezug</b>", bold_label_style),
        ]]
        for p_name, qty, appt_lbl in materials_rows:
            mat_data.append([
                Paragraph(_esc(p_name), body_style),
                Paragraph(str(qty), body_style),
                Paragraph(_esc(appt_lbl), body_style),
            ])
        t_mat = Table(mat_data, colWidths=[8.0 * cm, 3.0 * cm, 6.4 * cm])
        t_mat.setStyle(standard_table_style())
        story.append(Spacer(1, 0.1 * cm))
        story.append(t_mat)

    return build_standard_pdf(story, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm)


def _format_custom_field_value(f, val, users_by_id):
    """Formatiert benutzerdefinierte Feldwerte für die PDF-Ausgabe."""
    if val is None or val == '':
        return '-'
    if f.field_type == 'checkbox':
        return 'Ja' if str(val).lower() in ('1', 'true', 'yes', 'on') else 'Nein'
    if f.field_type == 'person':
        try:
            uid = int(val)
            return users_by_id.get(uid, f'Benutzer #{uid}')
        except (ValueError, TypeError):
            return str(val)
    return str(val)


def _future_appointments_for_event(event_obj, now):
    return [a for a in event_obj.appointments if a.end_time >= now]


def _collect_people(event_obj):
    names = []
    for assignment in event_obj.assignments:
        if assignment.user:
            names.append(assignment.user.full_name)
        elif assignment.display_name:
            names.append(assignment.display_name)
    return names or ['-']


def _collect_materials_for_event(event_obj):
    materials = []
    seen = set()
    for appointment in event_obj.appointments:
        for need in appointment.inventory_needs:
            name = need.product.name if need.product else f'Produkt {need.product_id}'
            key = (name, need.quantity)
            if key in seen:
                continue
            seen.add(key)
            materials.append(f"{name} x{need.quantity}")
    return materials or ['-']


def _collect_contacts(event_obj):
    contacts = []
    for contact in event_obj.contacts:
        entry = contact.name
        if contact.role:
            entry += f" ({contact.role})"
        contacts.append(entry)
    return contacts or ['-']


def _event_card(event_obj, future_appointments, styles):
    card_title = ParagraphStyle(
        'CardTitle',
        parent=styles['Heading4'],
        fontSize=13,
        textColor=PDF_COLORS['text'],
        fontName='Helvetica-Bold',
        spaceAfter=5,
    )
    body_style = ParagraphStyle(
        'CardBody',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=12.5,
        textColor=PDF_COLORS['text'],
    )

    people = _collect_people(event_obj)
    materials = _collect_materials_for_event(event_obj)
    contacts = _collect_contacts(event_obj)

    term_lines = []
    for appointment in future_appointments:
        term_lines.append(
            f"{appointment.start_time.strftime('%d.%m. %H:%M')} - "
            f"{appointment.end_time.strftime('%H:%M')} | {appointment.label}"
        )

    lines = [Paragraph(f"{event_obj.name}", card_title)]
    sections = [
        ('Ort', [event_obj.default_location or '-']),
        ('Termine', term_lines or ['-']),
        ('Personen', people or ['-']),
        ('Ansprechpartner', contacts or ['-']),
        ('Material', materials or ['-']),
    ]

    for heading, entries in sections:
        section_text = f"<b>{heading}:</b><br/>" + "<br/>".join(entries) + "<br/><br/>"
        lines.append(Paragraph(section_text, body_style))

    inner = Table([[lines]], colWidths=[6.3 * cm])
    inner.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return RoundedBox(
        inner,
        width=6.7 * cm,
        padding=8,
        radius=10,
        fill_color=PDF_COLORS['white'],
        stroke_color=PDF_COLORS['line'],
    )


def generate_event_overview_pdf(events, now=None, title='Veranstaltungsübersicht'):
    """Karten-Übersicht aktiver Events mit zukünftigen Terminen (Querformat)."""
    now = now or datetime.utcnow()
    styles = getSampleStyleSheet()
    page = landscape(A4)
    story = [
        build_standard_header(
            title,
            subtitle=f"Stand: {datetime.now().strftime('%d.%m.%Y')}",
            pagesize=page,
            logo_size=1.6 * cm,
            content_width=page[0] - 1.1 * cm,
        ),
        Spacer(1, 0.35 * cm),
    ]

    event_items = []
    for event_obj in events:
        future_appointments = _future_appointments_for_event(event_obj, now)
        if not future_appointments:
            continue
        first_start = min(appointment.start_time for appointment in future_appointments)
        event_items.append((first_start, _event_card(event_obj, future_appointments, styles)))

    event_items.sort(key=lambda item: item[0])
    cards = [item[1] for item in event_items]

    if not cards:
        story.append(Paragraph("Keine zukünftigen Veranstaltungstermine vorhanden.", styles['Normal']))
    else:
        columns = 4
        rows = []
        for index in range(0, len(cards), columns):
            row_cards = cards[index:index + columns]
            while len(row_cards) < columns:
                row_cards.append('')
            rows.append(row_cards)

        grid = Table(rows, colWidths=[6.95 * cm] * columns, rowHeights=[7.2 * cm] * len(rows))
        grid.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(grid)

    return build_standard_pdf(
        story,
        pagesize=page,
        leftMargin=0.55 * cm,
        rightMargin=0.55 * cm,
        topMargin=0.7 * cm,
        bottomMargin=1.8 * cm,
    )


def generate_appointments_overview_pdf(appointments, title='Standardübersicht'):
    """Tabellen-PDF für Terminlisten (Standard / Meine / Archiv)."""
    styles = getSampleStyleSheet()
    story = [
        build_standard_header(title, subtitle=f"Stand: {datetime.now().strftime('%d.%m.%Y')}", pagesize=A4),
        Spacer(1, 0.35 * cm),
    ]

    table_data = [['Termin', 'Veranstaltung', 'Start', 'Ende', 'Ort']]
    for appointment in appointments:
        event_name = appointment.event.name if appointment.event else '-'
        location = appointment.location or (appointment.event.default_location if appointment.event else None) or '-'
        table_data.append([
            Paragraph(appointment.label, styles['Normal']),
            Paragraph(event_name, styles['Normal']),
            appointment.start_time.strftime('%d.%m.%Y %H:%M'),
            appointment.end_time.strftime('%d.%m.%Y %H:%M'),
            Paragraph(location, styles['Normal']),
        ])

    if len(table_data) == 1:
        story.append(Paragraph("Keine Termine vorhanden.", styles['Normal']))
    else:
        table = Table(table_data, colWidths=[3.4 * cm, 4.2 * cm, 3.2 * cm, 3.2 * cm, 3.2 * cm])
        table.setStyle(standard_table_style())
        story.append(table)

    return build_standard_pdf(story, pagesize=A4)


def generate_people_overview_pdf(rows, title='Personenübersicht'):
    """Tabellen-PDF für die Personenübersicht."""
    styles = getSampleStyleSheet()
    story = [
        build_standard_header(title, subtitle=f"Stand: {datetime.now().strftime('%d.%m.%Y')}", pagesize=A4),
        Spacer(1, 0.35 * cm),
    ]

    table_data = [['Person', 'Anzahl Veranstaltungen']]
    for row in rows:
        table_data.append([row['user'].full_name, str(row['event_count'])])

    if len(table_data) == 1:
        story.append(Paragraph("Noch keine Zuordnungen vorhanden.", styles['Normal']))
    else:
        table = Table(table_data, colWidths=[10 * cm, 7 * cm])
        table.setStyle(standard_table_style())
        story.append(table)

    return build_standard_pdf(story, pagesize=A4)
