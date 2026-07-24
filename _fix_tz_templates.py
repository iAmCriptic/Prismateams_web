"""One-shot: replace UTC .strftime() in templates with localdatetime/localtime filters."""
import re
from pathlib import Path

root = Path("app/templates")
utc_attrs = [
    "created_at",
    "updated_at",
    "uploaded_at",
    "last_login",
    "last_seen",
    "last_activity",
    "last_used",
    "last_synced",
    "last_synced_at",
    "sent_at",
    "received_at",
    "started_at",
    "completed_at",
    "deleted_at",
    "responded_at",
    "expires_at",
    "guest_expires_at",
    "confirmation_code_expires",
    "share_expires_at",
    "password_reset_code_expires",
    "archived_at",
    "borrow_date",
    "expected_return_date",
    "actual_return_date",
    "notification_sent_at",
    "played_at",
    "inspection_timestamp",
    "timestamp",
]

wall_clock = re.compile(
    r"(start_time|end_time|recurrence_end_date|event_date|appointment_start|appointment_end)"
)

pattern = re.compile(
    r"((?:\([^)]+\)|[A-Za-z_][\w\.]*(?:\[[^\]]+\])?))\.strftime\('([^']+)'\)"
)


def repl_strftime(m):
    expr = m.group(1)
    fmt = m.group(2)
    if wall_clock.search(expr):
        return m.group(0)
    if not any(a in expr for a in utc_attrs):
        return m.group(0)
    if fmt in ("%H:%M", "%H:%M:%S"):
        return f"{expr}|localtime('{fmt}')"
    return f"{expr}|localdatetime('{fmt}')"


count = 0
files_changed = []
for path in root.rglob("*.html"):
    text = path.read_text(encoding="utf-8")
    text2, n = pattern.subn(repl_strftime, text)
    if n:
        path.write_text(text2, encoding="utf-8")
        files_changed.append((str(path), n))
        count += n

print(f"Replaced {count} occurrences in {len(files_changed)} files")
for f, n in files_changed:
    print(f"  {n:3d} {f}")
