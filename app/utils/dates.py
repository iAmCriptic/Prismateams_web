"""Datums-Helfer für Inventar / DGUV."""

from calendar import monthrange
from datetime import date


def add_months(start: date, months: int) -> date:
    """Addiert Monate zu einem Datum (Monatsende wird geklemmt)."""
    month_index = start.month - 1 + int(months)
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def compute_dguv_next(last_check, interval_months):
    """Nächste DGUV-Prüfung = letzte Prüfung + Intervall (Monate)."""
    if not last_check or not interval_months:
        return None
    try:
        months = int(interval_months)
    except (TypeError, ValueError):
        return None
    if months < 1:
        return None
    return add_months(last_check, months)
