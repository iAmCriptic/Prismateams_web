"""Server-PDFs für das Bewertungstool — Portal-Standardlayout wie Inventar."""

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table

from app.utils.pdf_generator import (
    build_standard_header,
    build_standard_pdf,
    pdf_paragraph_styles,
    standard_table_style,
)


def _safe(value, fallback="—"):
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _build_table(headers, rows, col_widths=None):
    data = [headers] + (rows or [["—"] * len(headers)])
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(standard_table_style(header=True))
    return table


def generate_blank_evaluation_pdf(evaluation_list, targets, criteria, output=None):
    """Leeres Bewertungsformular (Ziele × Kriterien)."""
    if output is None:
        output = BytesIO()

    list_name = _safe(getattr(evaluation_list, "name", None), "Bewertung")
    ps = pdf_paragraph_styles()
    story = [
        build_standard_header(
            "Bewertungsformular",
            subtitle=list_name,
            pagesize=A4,
        ),
        Spacer(1, 0.35 * cm),
        Paragraph("Bitte Punkte eintragen und unterschreiben.", ps["body"]),
        Spacer(1, 0.4 * cm),
    ]

    crit_names = [_safe(c.name) for c in (criteria or [])]
    headers = ["Ziel"] + crit_names + ["Summe", "Notiz"]
    rows = []
    for target in targets or []:
        name = _safe(getattr(target, "name", target))
        rows.append([name] + [""] * len(crit_names) + ["", ""])
    if not rows:
        rows.append(["—"] + [""] * len(crit_names) + ["", ""])

    usable = A4[0] - 4 * cm
    first_w = 4.2 * cm
    last_w = 2.8 * cm
    mid_count = max(len(headers) - 2, 1)
    mid_w = max((usable - first_w - last_w) / mid_count, 1.2 * cm)
    col_widths = [first_w] + [mid_w] * (len(headers) - 2) + [last_w]
    story.append(_build_table(headers, rows, col_widths=col_widths))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("Unterschrift Bewerter: ____________________________", ps["body"]))
    return build_standard_pdf(story, output=output)


def generate_evaluation_detail_pdf(evaluation, target_name, score_rows, list_name=None, output=None):
    """Ausgefüllte Einzelbewertung."""
    if output is None:
        output = BytesIO()

    ps = pdf_paragraph_styles()
    subtitle_parts = [p for p in [list_name, target_name] if p]
    story = [
        build_standard_header(
            "Bewertung",
            subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
            pagesize=A4,
        ),
        Spacer(1, 0.35 * cm),
    ]
    if evaluation and evaluation.timestamp:
        story.append(
            Paragraph(
                f"Datum: {evaluation.timestamp.strftime('%d.%m.%Y %H:%M')}",
                ps["body"],
            )
        )
        story.append(Spacer(1, 0.3 * cm))

    rows = [[_safe(name), str(score)] for name, score in (score_rows or [])]
    total = sum(int(score or 0) for _, score in (score_rows or []))
    if rows:
        rows.append(["Gesamt", str(total)])
    story.append(_build_table(["Kriterium", "Punkte"], rows, col_widths=[12 * cm, 4 * cm]))
    return build_standard_pdf(story, output=output)


def generate_ranking_pdf(evaluation_list, rows, sort_label, output=None):
    """Rangliste mit aktueller Sortierung."""
    if output is None:
        output = BytesIO()

    list_name = _safe(getattr(evaluation_list, "name", None), "Rangliste")
    story = [
        build_standard_header(
            "Rangliste",
            subtitle=f"{list_name} · Sortierung: {_safe(sort_label)}",
            pagesize=A4,
        ),
        Spacer(1, 0.4 * cm),
    ]
    table_rows = []
    for idx, row in enumerate(rows or [], start=1):
        table_rows.append(
            [
                str(idx),
                _safe(row.get("target_name") or row.get("stand_name")),
                _safe(row.get("room_name") or row.get("stand_type_name")),
                str(row.get("displayed_total", 0)),
                f"{float(row.get('displayed_avg') or 0):.2f}",
                str(row.get("displayed_votes", 0)),
            ]
        )
    story.append(
        _build_table(
            ["Rang", "Name", "Raum / Typ", "Punkte", "Ø", "Anz."],
            table_rows,
            col_widths=[1.4 * cm, 6.5 * cm, 3.5 * cm, 2 * cm, 1.8 * cm, 1.6 * cm],
        )
    )
    return build_standard_pdf(story, output=output)


def generate_inspections_pdf(rooms_payload, output=None):
    """Rauminspektionen-Übersicht."""
    if output is None:
        output = BytesIO()

    story = [
        build_standard_header("Rauminspektionen", subtitle="Aktueller Stand", pagesize=A4),
        Spacer(1, 0.4 * cm),
    ]
    rows = []
    for room in rooms_payload or []:
        insp = room.get("inspection") or {}
        status = "Sauber" if insp.get("is_clean") else ("Geprüft" if insp else "Offen")
        if insp and not insp.get("is_clean") and insp.get("comment"):
            status = "Nicht sauber"
        rows.append(
            [
                _safe(room.get("name")),
                status,
                _safe(insp.get("comment")),
                _safe((insp.get("inspection_timestamp") or "")[:16].replace("T", " ")),
            ]
        )
    story.append(
        _build_table(
            ["Raum", "Status", "Kommentar", "Zeitpunkt"],
            rows,
            col_widths=[4.5 * cm, 3 * cm, 6 * cm, 3.5 * cm],
        )
    )
    return build_standard_pdf(story, output=output)


def generate_warnings_pdf(warnings, output=None):
    """Verwarnungsliste."""
    if output is None:
        output = BytesIO()

    story = [
        build_standard_header("Verwarnungen", subtitle="Übersicht", pagesize=A4),
        Spacer(1, 0.4 * cm),
    ]
    rows = []
    for w in warnings or []:
        rows.append(
            [
                _safe(w.get("target_name")),
                _safe(w.get("comment")),
                "Invalidiert" if w.get("is_invalidated") else "Aktiv",
                _safe((w.get("timestamp") or "")[:16].replace("T", " ")),
            ]
        )
    story.append(
        _build_table(
            ["Stand", "Kommentar", "Status", "Zeitpunkt"],
            rows,
            col_widths=[4 * cm, 7.5 * cm, 2.5 * cm, 3 * cm],
        )
    )
    return build_standard_pdf(story, output=output)
