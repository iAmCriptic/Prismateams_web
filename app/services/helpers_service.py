"""Geschäftslogik für das Helferverwaltungs-Modul (Marken, T-Shirts, Soll-Ist, Export)."""

from __future__ import annotations

import csv
import io
from collections import defaultdict

from app import db
from app.models.helpers import (
    Helper,
    HelperArea,
    HelperEvent,
    HelperFieldConfig,
    HelperShift,
    HelperVoucherRule,
)
from app.utils.helpers_seed import seed_event_defaults

DAY_SHORT_MAP = {
    'freitag': 'Fr',
    'fr': 'Fr',
    'samstag': 'Sa',
    'sa': 'Sa',
    'sonntag': 'So',
    'so': 'So',
}


def normalize_day_short(day_label):
    key = (day_label or '').strip().lower()
    if key in DAY_SHORT_MAP:
        return DAY_SHORT_MAP[key]
    for prefix, short in DAY_SHORT_MAP.items():
        if key.startswith(prefix):
            return short
    return (day_label or 'Sonstige').strip() or 'Sonstige'


def create_helper_event(
    name,
    description='',
    start_date=None,
    end_date=None,
    clone_from_event_id=None,
    apply_enabled=True,
    voucher_calc_mode='per_shift',
):
    """Legt eine neue Veranstaltung an und seeded Standard- oder geklonte Konfiguration."""
    event = HelperEvent(
        name=name.strip(),
        description=(description or '').strip() or None,
        start_date=start_date,
        end_date=end_date,
        is_active=True,
        apply_enabled=bool(apply_enabled),
        voucher_calc_mode=voucher_calc_mode if voucher_calc_mode in ('per_shift', 'cumulative_per_person_day') else 'per_shift',
    )
    event.ensure_apply_token()
    db.session.add(event)
    db.session.flush()

    if clone_from_event_id:
        source = db.session.get(HelperEvent, clone_from_event_id)
        if source:
            area_map = {}
            for area in source.areas:
                new_area = HelperArea(
                    event_id=event.id,
                    name=area.name,
                    description=area.description,
                    is_public_selectable=area.is_public_selectable,
                    sort_order=area.sort_order,
                )
                db.session.add(new_area)
                db.session.flush()
                area_map[area.id] = new_area.id

            for fc in source.field_configs:
                db.session.add(
                    HelperFieldConfig(
                        event_id=event.id,
                        field_key=fc.field_key,
                        label=fc.label,
                        field_type=fc.field_type,
                        options=fc.get_options(),
                        is_public=fc.is_public,
                        is_required=fc.is_required,
                        admin_only=fc.admin_only,
                        show_in_overview=fc.show_in_overview,
                        is_active=fc.is_active,
                        is_core=fc.is_core,
                        sort_order=fc.sort_order,
                    )
                )

            for rule in source.voucher_rules:
                db.session.add(
                    HelperVoucherRule(
                        event_id=event.id,
                        name=rule.name,
                        min_hours=rule.min_hours,
                        max_hours=rule.max_hours,
                        food_count=rule.food_count,
                        drinks_count=rule.drinks_count,
                        head_bonus_drinks=rule.head_bonus_drinks,
                        area_id=area_map.get(rule.area_id) if rule.area_id else None,
                    )
                )
            db.session.commit()
            return event

    seed_event_defaults(event.id)
    db.session.commit()
    return event


def _find_matching_rule(rules, hours, area_id=None):
    """Sucht passende Regel: bereichsspezifisch vor global, sonst höchste passende Stufe."""
    area_rules = [r for r in rules if r.area_id == area_id] if area_id else []
    global_rules = [r for r in rules if r.area_id is None]

    for pool in (area_rules, global_rules):
        matches = [r for r in pool if r.matches_hours(hours)]
        if matches:
            matches.sort(key=lambda r: (float(r.min_hours or 0.0), r.id or 0), reverse=True)
            return matches[0]
    return None


def calculate_shift_vouchers(shift, rules):
    """Berechnet (food, drinks) für eine einzelne Schicht inkl. group_count, HEAD-Bonus und Overrides."""
    count = max(int(shift.group_count or 1), 1)
    rule = _find_matching_rule(rules, shift.hours or 0.0, area_id=shift.area_id)

    base_food = (rule.food_count if rule else 0) * count
    base_drinks = (rule.drinks_count if rule else 0) * count
    if rule and shift.is_head_role and (rule.head_bonus_drinks or 0) > 0:
        base_drinks += int(rule.head_bonus_drinks) * count

    food = int(shift.food_override) if shift.food_override is not None else int(base_food)
    drinks = int(shift.drinks_override) if shift.drinks_override is not None else int(base_drinks)
    return max(food, 0), max(drinks, 0)


def calculate_event_vouchers(event):
    """
    Berechnet Marken pro Schicht und pro Helfer unter Berücksichtigung von
    `event.voucher_calc_mode` ('per_shift' vs. 'cumulative_per_person_day').
    """
    rules = list(event.voucher_rules)
    shifts = list(event.shifts)
    mode = (event.voucher_calc_mode or 'per_shift').strip()

    shift_results = {}
    helper_totals = defaultdict(lambda: {'food': 0, 'drinks': 0, 'hours': 0.0, 'by_day': defaultdict(lambda: {'food': 0, 'drinks': 0})})

    if mode != 'cumulative_per_person_day':
        for s in shifts:
            food, drinks = calculate_shift_vouchers(s, rules)
            shift_results[s.id] = {'food': food, 'drinks': drinks}
            if s.helper_id:
                short = normalize_day_short(s.day_label)
                helper_totals[s.helper_id]['food'] += food
                helper_totals[s.helper_id]['drinks'] += drinks
                helper_totals[s.helper_id]['hours'] += float(s.hours or 0.0)
                helper_totals[s.helper_id]['by_day'][short]['food'] += food
                helper_totals[s.helper_id]['by_day'][short]['drinks'] += drinks
        return shift_results, dict(helper_totals)

    # Kumuliert pro Person und Tag
    grouped = defaultdict(list)
    for s in shifts:
        if s.helper_id is None:
            food, drinks = calculate_shift_vouchers(s, rules)
            shift_results[s.id] = {'food': food, 'drinks': drinks}
        else:
            day_key = s.date.isoformat() if s.date else normalize_day_short(s.day_label)
            grouped[(s.helper_id, day_key)].append(s)

    for (helper_id, _day_key), day_shifts in grouped.items():
        total_hours = sum(float(s.hours or 0.0) for s in day_shifts)
        any_head = any(s.is_head_role for s in day_shifts)
        primary_area_id = day_shifts[0].area_id if day_shifts else None
        rule = _find_matching_rule(rules, total_hours, area_id=primary_area_id)

        calc_food = int(rule.food_count) if rule else 0
        calc_drinks = int(rule.drinks_count) if rule else 0
        if rule and any_head and (rule.head_bonus_drinks or 0) > 0:
            calc_drinks += int(rule.head_bonus_drinks)

        # Manuelle Overrides auf Einzelschichten haben Vorrang
        food_overrides = [s.food_override for s in day_shifts if s.food_override is not None]
        drinks_overrides = [s.drinks_override for s in day_shifts if s.drinks_override is not None]

        day_food = sum(int(v) for v in food_overrides) if food_overrides else calc_food
        day_drinks = sum(int(v) for v in drinks_overrides) if drinks_overrides else calc_drinks

        # Erste Schicht trägt die Tageszuordnung für Bereichs-Summen (oder anteilig bei Overrides)
        for idx, s in enumerate(day_shifts):
            if idx == 0:
                shift_results[s.id] = {'food': max(day_food, 0), 'drinks': max(day_drinks, 0)}
            else:
                shift_results[s.id] = {'food': 0, 'drinks': 0}

        short = normalize_day_short(day_shifts[0].day_label)
        helper_totals[helper_id]['food'] += max(day_food, 0)
        helper_totals[helper_id]['drinks'] += max(day_drinks, 0)
        helper_totals[helper_id]['hours'] += total_hours
        helper_totals[helper_id]['by_day'][short]['food'] += max(day_food, 0)
        helper_totals[helper_id]['by_day'][short]['drinks'] += max(day_drinks, 0)

    return shift_results, dict(helper_totals)


def get_helper_overview_data(event, search_query='', area_filter=None, status_filter='', assignment_filter=''):
    """Liefert Helfer-Zeilen inkl. Soll-Ist-Abgleich ('Gemeldet für' vs. 'Eingeteilt in')."""
    overview_fields = [
        fc for fc in event.field_configs
        if fc.is_active and fc.show_in_overview and fc.field_key not in ('first_name', 'last_name', 'email', 'phone', 'tshirt_size', 'allergies')
    ]
    _, helper_vouchers = calculate_event_vouchers(event)

    q = (search_query or '').strip().lower()
    rows = []
    for h in event.helpers:
        custom = h.get_custom_fields()
        wishes = list(h.wishes)
        shifts = list(h.shifts)

        wish_area_ids = {w.area_id for w in wishes}
        assigned_area_ids = {s.area_id for s in shifts}

        if area_filter and area_filter not in wish_area_ids and area_filter not in assigned_area_ids:
            continue
        if status_filter and h.status != status_filter:
            continue
        if assignment_filter == 'unassigned' and shifts:
            continue
        if assignment_filter == 'assigned' and not shifts:
            continue

        if q:
            haystack = ' '.join([
                h.first_name or '',
                h.last_name or '',
                h.email or '',
                h.phone or '',
                h.tshirt_size or '',
                h.allergies or '',
                ' '.join(w.area.name for w in wishes if w.area),
                ' '.join(s.area.name for s in shifts if s.area),
                ' '.join(str(v) for v in custom.values()),
            ]).lower()
            if q not in haystack:
                continue

        assigned_areas = sorted({s.area.name for s in shifts if s.area})
        assigned_days = sorted({normalize_day_short(s.day_label) for s in shifts})
        total_hours = round(sum(float(s.hours or 0.0) for s in shifts), 2)
        v_info = helper_vouchers.get(h.id, {'food': 0, 'drinks': 0})

        rows.append({
            'helper': h,
            'custom': custom,
            'wishes': wishes,
            'shifts': shifts,
            'assigned_areas': assigned_areas,
            'assigned_days': assigned_days,
            'total_hours': total_hours,
            'is_unassigned': len(shifts) == 0,
            'food_vouchers': v_info['food'],
            'drinks_vouchers': v_info['drinks'],
        })

    return rows, overview_fields


def get_area_dashboard_data(event):
    """Aggregiert Kennzahlen je Bereich für die Bereichs-Übersicht."""
    shift_vouchers, _ = calculate_event_vouchers(event)
    cards = []

    for area in event.areas:
        shifts = list(area.shifts)
        total_slots = sum(max(int(s.group_count or 1), 1) for s in shifts)
        filled_slots = sum(
            max(int(s.group_count or 1), 1)
            for s in shifts
            if s.helper_id is not None or s.is_bulk_post
        )
        open_slots = max(total_slots - filled_slots, 0)
        total_hours = round(sum(float(s.hours or 0.0) * max(int(s.group_count or 1), 1) for s in shifts), 2)

        food_by_day = {'Fr': 0, 'Sa': 0, 'So': 0, 'Sonstige': 0}
        drinks_by_day = {'Fr': 0, 'Sa': 0, 'So': 0, 'Sonstige': 0}
        drinks_total = 0
        assigned_helper_ids = set()

        for s in shifts:
            v = shift_vouchers.get(s.id, {'food': 0, 'drinks': 0})
            short = normalize_day_short(s.day_label)
            if short not in food_by_day:
                short = 'Sonstige'
            food_by_day[short] += v['food']
            drinks_by_day[short] += v['drinks']
            drinks_total += v['drinks']
            if s.helper_id:
                assigned_helper_ids.add(s.helper_id)

        wish_count = len(area.wishes)
        cards.append({
            'area': area,
            'shift_count': len(shifts),
            'total_slots': total_slots,
            'filled_slots': filled_slots,
            'open_slots': open_slots,
            'total_hours': total_hours,
            'food_by_day': food_by_day,
            'food_total': sum(food_by_day.values()),
            'drinks_by_day': drinks_by_day,
            'drinks_total': drinks_total,
            'helper_count': len(assigned_helper_ids),
            'wish_count': wish_count,
        })

    return cards


def get_prioritized_helpers_for_area(event, area_id):
    """Listet Helfer für das Zuweisungs-Dropdown; Wunsch-Helfer für diesen Bereich stehen oben."""
    preferred = []
    others = []

    for h in event.helpers:
        wish = next((w for w in h.wishes if w.area_id == area_id), None)
        if wish is not None:
            preferred.append((wish.priority, h, wish))
        else:
            others.append((h, None))

    preferred.sort(key=lambda item: (item[0], (item[1].last_name or '').lower(), (item[1].first_name or '').lower()))
    result = [(h, True, wish) for _, h, wish in preferred]
    result.extend((h, False, None) for h, _ in others)
    return result


def get_area_detail_data(event, area):
    """Liefert alle Daten für die Detailansicht eines Bereichs inkl. Team-Liste & Kennzahlen."""
    shift_vouchers, _ = calculate_event_vouchers(event)
    shift_rows = []
    team_map = {}

    food_by_day = {'Fr': 0, 'Sa': 0, 'So': 0, 'Sonstige': 0}
    drinks_by_day = {'Fr': 0, 'Sa': 0, 'So': 0, 'Sonstige': 0}
    drinks_total = 0
    total_hours = 0.0
    filled_slots = 0
    total_slots = 0

    for s in area.shifts:
        v = shift_vouchers.get(s.id, {'food': 0, 'drinks': 0})
        count = max(int(s.group_count or 1), 1)
        total_slots += count
        if s.helper_id is not None or s.is_bulk_post:
            filled_slots += count
        total_hours += float(s.hours or 0.0) * count

        short = normalize_day_short(s.day_label)
        if short not in food_by_day:
            short = 'Sonstige'
        food_by_day[short] += v['food']
        drinks_by_day[short] += v['drinks']
        drinks_total += v['drinks']

        shift_rows.append({
            'shift': s,
            'food': v['food'],
            'drinks': v['drinks'],
        })

        if s.helper is not None:
            entry = team_map.setdefault(
                s.helper.id,
                {'helper': s.helper, 'shifts': 0, 'hours': 0.0, 'food': 0, 'drinks': 0, 'roles': set()},
            )
            entry['shifts'] += 1
            entry['hours'] += float(s.hours or 0.0)
            entry['food'] += v['food']
            entry['drinks'] += v['drinks']
            if s.role_label:
                entry['roles'].add(s.role_label)

    team_list = sorted(
        team_map.values(),
        key=lambda item: ((item['helper'].last_name or '').lower(), (item['helper'].first_name or '').lower()),
    )
    for item in team_list:
        item['roles'] = sorted(item['roles'])
        item['hours'] = round(item['hours'], 2)

    prioritized_helpers = get_prioritized_helpers_for_area(event, area.id)
    return {
        'shift_rows': shift_rows,
        'team_list': team_list,
        'prioritized_helpers': prioritized_helpers,
        'kpis': {
            'total_slots': total_slots,
            'filled_slots': filled_slots,
            'open_slots': max(total_slots - filled_slots, 0),
            'total_hours': round(total_hours, 2),
            'food_by_day': food_by_day,
            'food_total': sum(food_by_day.values()),
            'drinks_by_day': drinks_by_day,
            'drinks_total': drinks_total,
        },
    }


def get_tshirt_summary(event, only_assigned=False):
    """Summiert T-Shirt-Größen gesamt und aufgeschlüsselt nach Bereichen."""
    size_order = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']
    size_totals = defaultdict(int)
    area_matrix = defaultdict(lambda: defaultdict(int))
    seen_helper_ids = set()

    for h in event.helpers:
        is_assigned_or_confirmed = bool(h.shifts) or h.status in ('confirmed', 'assigned')
        if only_assigned and not is_assigned_or_confirmed:
            continue

        size = (h.tshirt_size or '').strip() or 'Keine Angabe'
        if h.id not in seen_helper_ids:
            size_totals[size] += 1
            seen_helper_ids.add(h.id)

        assigned_areas = {s.area.name for s in h.shifts if s.area}
        if not assigned_areas:
            assigned_areas = {w.area.name for w in h.wishes if w.area} or {'Ohne Bereich'}
        for area_name in assigned_areas:
            area_matrix[area_name][size] += 1

    all_sizes = sorted(
        size_totals.keys(),
        key=lambda s: (size_order.index(s) if s in size_order else 999, s),
    )
    return {
        'sizes': all_sizes,
        'totals': dict(size_totals),
        'total_count': sum(size_totals.values()),
        'area_matrix': {k: dict(v) for k, v in sorted(area_matrix.items())},
    }


def get_voucher_summary(event):
    """Aggregiert Essens- und Getränkemarken nach Tag, Bereich und pro Helfer."""
    shift_vouchers, helper_vouchers = calculate_event_vouchers(event)

    by_day = {
        'Fr': {'food': 0, 'drinks': 0},
        'Sa': {'food': 0, 'drinks': 0},
        'So': {'food': 0, 'drinks': 0},
        'Sonstige': {'food': 0, 'drinks': 0},
    }
    by_area = []

    for area in event.areas:
        area_row = {
            'area': area,
            'food_fr': 0,
            'food_sa': 0,
            'food_so': 0,
            'food_other': 0,
            'food_total': 0,
            'drinks_total': 0,
        }
        for s in area.shifts:
            v = shift_vouchers.get(s.id, {'food': 0, 'drinks': 0})
            short = normalize_day_short(s.day_label)
            if short not in by_day:
                short = 'Sonstige'
            by_day[short]['food'] += v['food']
            by_day[short]['drinks'] += v['drinks']

            if short == 'Fr':
                area_row['food_fr'] += v['food']
            elif short == 'Sa':
                area_row['food_sa'] += v['food']
            elif short == 'So':
                area_row['food_so'] += v['food']
            else:
                area_row['food_other'] += v['food']
            area_row['food_total'] += v['food']
            area_row['drinks_total'] += v['drinks']

        by_area.append(area_row)

    checklist = []
    for h in event.helpers:
        v = helper_vouchers.get(h.id, {'food': 0, 'drinks': 0, 'hours': 0.0, 'by_day': {}})
        if not h.shifts and v['food'] == 0 and v['drinks'] == 0:
            continue
        days_present = sorted({normalize_day_short(s.day_label) for s in h.shifts})
        checklist.append({
            'helper': h,
            'hours': round(v.get('hours', 0.0), 2),
            'food': v['food'],
            'drinks': v['drinks'],
            'days': days_present,
            'by_day': v.get('by_day', {}),
        })

    totals = {
        'food': sum(d['food'] for d in by_day.values()),
        'drinks': sum(d['drinks'] for d in by_day.values()),
    }
    return {
        'by_day': by_day,
        'by_area': by_area,
        'checklist': checklist,
        'totals': totals,
    }


def export_area_team_csv(event, area):
    """Erstellt UTF-8-BOM-CSV mit allen im Bereich eingeteilten Helfern inkl. Kontakt & Allergien."""
    detail = get_area_detail_data(event, area)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Vorname',
        'Nachname',
        'E-Mail',
        'Telefon',
        'T-Shirt-Größe',
        'Unverträglichkeiten',
        'Rollen',
        'Schichten',
        'Stunden',
        'Essensmarken',
        'Getränkemarken',
    ])
    for item in detail['team_list']:
        h = item['helper']
        writer.writerow([
            h.first_name or '',
            h.last_name or '',
            h.email or '',
            h.phone or '',
            h.tshirt_size or '',
            h.allergies or '',
            ', '.join(item['roles']),
            item['shifts'],
            item['hours'],
            item['food'],
            item['drinks'],
        ])
    return ('\ufeff' + output.getvalue()).encode('utf-8')
