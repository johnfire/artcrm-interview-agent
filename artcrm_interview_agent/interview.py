"""
ArtCRM — Post-Visit Debrief Interview

Interviews you after a recon trip and saves answers directly to the database.

Usage:
    uv run artcrm-interview
    # or:
    uv run python -m artcrm_interview_agent.interview

Voice input tip (Ubuntu/Wayland):
    Install nerd-dictation: https://github.com/ideasman42/nerd-dictation
    Works system-wide — speak and it types into any terminal.
"""
import sys
from datetime import date

from artcrm_interview_agent.db import db


# ── UI helpers ────────────────────────────────────────────────────────────────

def hr():
    print("\n" + "─" * 50)


def ask(prompt, default=None):
    """Free-text input. Enter to skip."""
    suffix = f" [{default}]" if default else " (Enter to skip)"
    val = input(f"  {prompt}{suffix}: ").strip()
    return val if val else default


def menu(prompt, options, allow_skip=True):
    """Numbered menu. Returns chosen value or None if skipped."""
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    if allow_skip:
        print("    0. skip")
    while True:
        raw = input("  Choice: ").strip()
        if allow_skip and raw in ("", "0"):
            return None
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        print("  Invalid — try again.")


def multi_menu(prompt, options):
    """Multi-select numbered menu. Comma-separate choices."""
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    print("    0. skip / none")
    while True:
        raw = input("  Choices (e.g. 1,3): ").strip()
        if not raw or raw == "0":
            return []
        try:
            idxs = [int(x.strip()) - 1 for x in raw.split(",")]
            if all(0 <= i < len(options) for i in idxs):
                return [options[i] for i in idxs]
        except ValueError:
            pass
        print("  Invalid — try again.")


# ── database ──────────────────────────────────────────────────────────────────

def search_contacts(query: str) -> list[dict]:
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, city, country, status, type, first_impression
            FROM contacts
            WHERE deleted_at IS NULL
              AND (lower(name) LIKE %s OR lower(city) LIKE %s)
            ORDER BY lower(name)
            LIMIT 15
            """,
            (f"%{query.lower()}%", f"%{query.lower()}%"),
        )
        return [dict(r) for r in cur.fetchall()]


def save_updates(contact_id: int, updates: dict):
    if not updates:
        return
    fields = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [contact_id]
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE contacts SET {fields}, updated_at = NOW() WHERE id = %s",
            values,
        )


def append_notes(contact_id: int, new_text: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT notes FROM contacts WHERE id = %s", (contact_id,))
        row = cur.fetchone()
        existing = (row["notes"] or "").strip()
        today = date.today().isoformat()
        combined = f"{existing}\n\n[{today}] {new_text}".strip() if existing else f"[{today}] {new_text}"
        cur.execute(
            "UPDATE contacts SET notes = %s, updated_at = NOW() WHERE id = %s",
            (combined, contact_id),
        )


# ── contact picker ────────────────────────────────────────────────────────────

def pick_contact() -> dict | None:
    while True:
        query = input("\n  Search venue name or city (or Enter to finish): ").strip()
        if not query:
            return None

        results = search_contacts(query)
        if not results:
            print("  No matches found. Try again.")
            continue

        print(f"\n  Found {len(results)} match(es):")
        for i, c in enumerate(results, 1):
            loc = f"{c['city']}, {c['country']}" if c.get("country") else c.get("city", "")
            print(f"    {i}. {c['name']}  [{loc}]  {c['status']}")
        print("    0. search again")

        raw = input("  Select: ").strip()
        if raw == "0" or not raw:
            continue
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(results):
                return results[idx]
        except ValueError:
            pass
        print("  Invalid — try again.")


# ── interview ─────────────────────────────────────────────────────────────────

VALID_STATUSES = [
    "candidate", "cold", "contacted", "networking_visit",
    "meeting", "accepted", "on_hold", "dropped", "do_not_contact",
]

def interview_contact(contact: dict) -> None:
    hr()
    loc = contact.get("city", "")
    print(f"\n  Venue : {contact['name']}  {loc}  [{contact['status']}]")
    if contact.get("first_impression"):
        print(f"  First impression on record: {contact['first_impression']}")

    updates = {}
    today_str = date.today().isoformat()

    # Date of visit
    visited = ask("Date of visit", default=today_str)
    if visited:
        updates["last_visited_at"] = visited

    # Status
    current = contact.get("status", "")
    new_status = menu(
        f"Update status? (current: {current})",
        VALID_STATUSES,
    )
    if new_status:
        updates["status"] = new_status

    # Who did you speak to
    dm = ask("Who did you speak to? (name / role)")
    if dm:
        updates["decision_maker"] = dm

    # Impression
    impression = menu(
        "How did it go?",
        ["warm", "neutral", "cold", "skeptical"],
    )
    if impression:
        updates["last_impression"] = impression
        if not contact.get("first_impression"):
            updates["first_impression"] = impression

    # Materials left
    materials = multi_menu(
        "What did you leave behind?",
        ["prints", "postcards", "portfolio", "business card", "price list", "nothing"],
    )
    if materials:
        updates["materials_left"] = ", ".join(materials)

    # Follow-up promised
    followup = ask("Did you promise anything? (e.g. 'send price list', 'visit in May')")
    if followup:
        updates["followup_promised"] = followup

    # Preferred contact method
    pref = menu(
        "Best way to reach them?",
        ["email", "phone", "drop in", "Instagram DM", "contact form"],
    )
    if pref:
        updates["preferred_contact_method"] = pref

    # Email / phone (if you got one in person)
    got_email = ask("Did you get an email address?")
    if got_email:
        updates["email"] = got_email

    got_phone = ask("Did you get a phone number?")
    if got_phone:
        updates["phone"] = got_phone

    # Access notes
    access = ask("Access / logistics notes? (train, parking, hilly…)")
    if access:
        updates["access_notes"] = access

    # Space notes
    space = ask("Space notes? (wall size, lighting, vibe…)")
    if space:
        updates["space_notes"] = space

    # Price / commercial
    price = ask("Price / commercial notes?")
    if price:
        updates["price_sensitivity"] = price

    # Best time to visit
    best_time = ask("Best time to visit?")
    if best_time:
        updates["best_visit_time"] = best_time

    # Free notes — appended, not overwritten
    free_notes = ask("Anything else to note?")

    # Persist
    save_updates(contact["id"], updates)
    if free_notes:
        append_notes(contact["id"], free_notes)

    saved_fields = list(updates.keys()) + (["notes"] if free_notes else [])
    print(f"\n  Saved: {', '.join(saved_fields)}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n  ArtCRM — Post-Visit Debrief")
    print("  Search for each venue you visited today. Empty search = done.\n")

    count = 0
    while True:
        contact = pick_contact()
        if contact is None:
            break
        interview_contact(contact)
        count += 1

    hr()
    if count == 0:
        print("\n  No venues logged. Goodbye.\n")
    else:
        print(f"\n  Done — {count} venue(s) updated. Goodbye.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Any saves already made are kept.\n")
        sys.exit(0)
