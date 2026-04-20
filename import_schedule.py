import os
import re
from datetime import datetime
from difflib import get_close_matches

import gspread
from google.oauth2.service_account import Credentials
from flask import Blueprint, jsonify, request

from auth import api_scheduler_required
from database import get_db

bp = Blueprint("import_schedule", __name__, url_prefix="/api/import-schedule")

UNAVAIL_CODES = {"u", "unavail", "unavailable", "x", "off", "pto", "req off", "admin", "holiday"}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_gspread_client():
    path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Google credentials file not found: {path}")
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)


def _extract_sheet_id(url_or_id: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def _parse_date(cell: str, year_hint: int = None) -> str | None:
    cell = cell.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cell, fmt).date().isoformat()
        except ValueError:
            continue
    # M/D without year — infer from year_hint
    if year_hint:
        for fmt in ["%m/%d", "%m/%d"]:
            try:
                d = datetime.strptime(cell, fmt).replace(year=year_hint).date()
                return d.isoformat()
            except ValueError:
                continue
    return None


def _extract_skill_code(raw: str) -> str:
    """Strip parenthetical comments and a leading start-time number.

    '7 IR Late (See comment)' → 'IR Late'
    '9 ECU'                   → 'ECU'
    'Call'                    → 'Call'
    'REQ OFF'                 → 'REQ OFF'
    """
    # Normalize unicode whitespace (non-breaking spaces, tabs, etc.)
    code = ' '.join(raw.split())
    # Remove anything in parentheses
    code = re.sub(r'\s*\(.*?\)', '', code).strip()
    # Strip a leading integer (start time, e.g. 7 or 9)
    parts = code.split(None, 1)
    if parts and re.match(r'^\d+$', parts[0]):
        return parts[1].strip() if len(parts) > 1 else ''
    return code


def _parse_sheet(worksheet, block_start: str = None):
    all_values = worksheet.get_all_values()
    if len(all_values) < 2:
        return []

    year_hint = int(block_start[:4]) if block_start else None

    # Row index 1 = date header row
    header_row = all_values[1]
    col_to_date = {}
    for c, cell in enumerate(header_row):
        if c == 0:
            continue
        parsed = _parse_date(cell, year_hint=year_hint)
        if parsed:
            col_to_date[c] = parsed

    entries = []
    for row in all_values[2:]:
        if not row:
            continue
        raw_name = row[0].strip() if row else ""
        if not raw_name:
            continue
        for c, date_str in col_to_date.items():
            if c >= len(row):
                continue
            raw_cell = row[c].strip()
            if not raw_cell:
                continue
            skill_code = _extract_skill_code(raw_cell)
            if not skill_code:
                continue
            entries.append({"raw_name": raw_name, "date": date_str, "raw_code": skill_code})

    return entries


def _name_variants(raw: str) -> list:
    """Return candidate normalized strings for a raw name.

    Handles 'Last, First' → 'first last' rearrangement so the sheet's
    name format can match the DB's 'First Last' format.
    """
    variants = [raw.strip().lower()]
    if ',' in raw:
        parts = [p.strip() for p in raw.split(',', 1)]
        if len(parts) == 2 and parts[1]:
            variants.append(f"{parts[1]} {parts[0]}".lower())
    return variants


def _match_names(raw_names, db_staff):
    normalized_map = {s["name"].strip().lower(): s for s in db_staff}
    all_normalized = list(normalized_map.keys())

    name_map = {}
    unmatched = []

    for raw in raw_names:
        matched = None
        for variant in _name_variants(raw):
            if variant in normalized_map:
                matched = normalized_map[variant]["id"]
                break
            close = get_close_matches(variant, all_normalized, n=1, cutoff=0.80)
            if close:
                matched = normalized_map[close[0]]["id"]
                break
        if matched is not None:
            name_map[raw] = matched
        else:
            # Lower-cutoff fuzzy pass to catch hyphenated / unusual names
            for variant in _name_variants(raw):
                close = get_close_matches(variant, all_normalized, n=1, cutoff=0.70)
                if close:
                    matched = normalized_map[close[0]]["id"]
                    break
            if matched is not None:
                name_map[raw] = matched
            else:
                unmatched.append(raw)

    return name_map, unmatched


def _resolve_skill(norm, full_name, first_word, fw_candidates, all_full_names):
    """Match a single normalised code string to a skill, or return None."""
    words     = norm.split()
    last_word = words[-1] if words else norm

    if norm in full_name:
        return full_name[norm]
    if norm in first_word:
        return first_word[norm]
    if norm in fw_candidates:
        # Collision: compare only against the competing skills so e.g. "IR"
        # never accidentally fuzzy-matches to "IRC".
        candidates = {s["name"].strip().lower(): s for s in fw_candidates[norm]}
        close = get_close_matches(norm, list(candidates.keys()), n=1, cutoff=0.40)
        if close:
            return candidates[close[0]]
        return min(fw_candidates[norm], key=lambda s: len(s["name"]))
    if last_word in full_name:
        return full_name[last_word]
    close = get_close_matches(norm, all_full_names, n=1, cutoff=0.70)
    if close:
        return full_name[close[0]]
    return None


def _match_skills(raw_codes, db_skills):
    """
    Returns:
        skill_map  – {raw_code: [skill, ...]}  (list so compound codes can
                     yield two skills, e.g. "IR Late" → [IR RN, Late])
        unmatched  – list of raw codes that could not be resolved
    """
    full_name     = {}
    fw_candidates = {}

    for skill in db_skills:
        norm = skill["name"].strip().lower()
        full_name[norm] = skill
        parts = norm.split()
        if parts:
            fw_candidates.setdefault(parts[0], []).append(skill)

    first_word     = {fw: skills[0] for fw, skills in fw_candidates.items() if len(skills) == 1}
    all_full_names = list(full_name.keys())

    skill_map = {}   # raw_code -> [skill, ...]
    unmatched = []

    for raw in raw_codes:
        norm = raw.strip().lower()
        if norm in UNAVAIL_CODES:
            continue

        words = norm.split()

        if len(words) >= 2:
            # Try to find two constituent skills in a multi-word code.
            # e.g. "IR Call"  → IR RN  + Call
            #      "IR Late"  → IR RN  + IR Late  (IR Late is an exact skill)
            prefix_skill = _resolve_skill(
                words[0], full_name, first_word, fw_candidates, all_full_names
            )
            if prefix_skill:
                # Check full code as its own skill first (e.g. "IR Late" skill)
                full_match = full_name.get(norm)
                if full_match and full_match != prefix_skill:
                    skill_map[raw] = [prefix_skill, full_match]
                    continue

                # Otherwise try the suffix words as an independent skill
                # e.g. "call" from "IR Call"
                suffix_norm  = " ".join(words[1:])
                suffix_skill = _resolve_skill(
                    suffix_norm, full_name, first_word, fw_candidates, all_full_names
                )
                if suffix_skill and suffix_skill != prefix_skill:
                    skill_map[raw] = [prefix_skill, suffix_skill]
                    continue

        matched = _resolve_skill(norm, full_name, first_word, fw_candidates, all_full_names)
        if matched:
            skill_map[raw] = [matched]
        else:
            unmatched.append(raw)

    return skill_map, unmatched


# ── Endpoints ─────────────────────────────────────────────────────────────────

@bp.route("/preview", methods=["POST"])
@api_scheduler_required
def preview():
    body = request.get_json(silent=True) or {}
    spreadsheet_id_raw = body.get("spreadsheet_id", "").strip()
    sheet_name         = body.get("sheet_name", "").strip()
    block_id           = body.get("block_id")

    if not spreadsheet_id_raw or not sheet_name or not block_id:
        return jsonify({"error": "spreadsheet_id, sheet_name, and block_id are required"}), 400

    spreadsheet_id = _extract_sheet_id(spreadsheet_id_raw)

    with get_db() as conn:
        block = conn.execute("SELECT * FROM schedule_blocks WHERE id = ?", (block_id,)).fetchone()
        if not block:
            return jsonify({"error": "Block not found"}), 404
        db_staff  = [dict(r) for r in conn.execute("SELECT id, name FROM staff").fetchall()]
        db_skills = [dict(r) for r in conn.execute(
            "SELECT id, name, priority FROM skills ORDER BY priority ASC, name ASC"
        ).fetchall()]

    try:
        client = _get_gspread_client()
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        return jsonify({"error": "Spreadsheet not found — check the ID/URL and that the service account has access"}), 404
    except gspread.exceptions.APIError as e:
        return jsonify({"error": f"Google Sheets API error: {e}"}), 500

    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return jsonify({"error": f"Sheet tab '{sheet_name}' not found"}), 404

    entries = _parse_sheet(worksheet, block_start=block["start_date"])

    # Filter to block date range
    block_start = block["start_date"]
    block_end   = block["end_date"]
    entries = [e for e in entries if block_start <= e["date"] <= block_end]

    if not entries:
        return jsonify({
            "matched_requests": [], "matched_unavail": [],
            "unmatched_staff": [], "unmatched_skills": [],
            "block_id": block_id, "block_name": block["name"],
        })

    raw_names = list({e["raw_name"] for e in entries})
    raw_codes = list({e["raw_code"] for e in entries if e["raw_code"].strip().lower() not in UNAVAIL_CODES})

    name_map, unmatched_staff = _match_names(raw_names, db_staff)
    skill_map, unmatched_skills = _match_skills(raw_codes, db_skills)

    # Build a set of staff name tokens so we can silently ignore cells that
    # contain just a person's first name, last name, or nickname instead of a skill.
    staff_name_tokens = set()
    for s in db_staff:
        for token in re.split(r'[\s,]+', s["name"]):
            if len(token) > 2:
                staff_name_tokens.add(token.lower())

    def _looks_like_staff_name(code: str) -> bool:
        norm = code.strip().lower()
        if norm in staff_name_tokens:
            return True
        # catch nicknames that are a prefix of a full name token (e.g. "Aly" → "Alyson")
        if len(norm) >= 3:
            return any(token.startswith(norm) for token in staff_name_tokens)
        return False

    unmatched_skills = [
        code for code in unmatched_skills
        if not _looks_like_staff_name(code)
    ]

    # Build staff id → name lookup for response labels
    staff_id_to_name = {s["id"]: s["name"] for s in db_staff}

    matched_requests = []
    matched_unavail  = []

    seen_requests = set()
    seen_unavail  = set()

    for e in entries:
        raw_name = e["raw_name"]
        raw_code = e["raw_code"]
        date     = e["date"]
        norm_code = raw_code.strip().lower()

        if raw_name not in name_map:
            continue

        staff_id   = name_map[raw_name]
        staff_name = staff_id_to_name.get(staff_id, raw_name)

        if norm_code in UNAVAIL_CODES:
            key = (staff_id, date)
            if key not in seen_unavail:
                seen_unavail.add(key)
                matched_unavail.append({"staff_id": staff_id, "staff_name": staff_name, "date": date})
        elif raw_code in skill_map:
            for skill in skill_map[raw_code]:
                key = (staff_id, date, skill["id"])
                if key not in seen_requests:
                    seen_requests.add(key)
                    matched_requests.append({
                        "staff_id":   staff_id,
                        "staff_name": staff_name,
                        "date":       date,
                        "skill_id":   skill["id"],
                        "skill_name": skill["name"],
                    })

    return jsonify({
        "matched_requests": matched_requests,
        "matched_unavail":  matched_unavail,
        "unmatched_staff":  unmatched_staff,
        "unmatched_skills": unmatched_skills,
        "block_id":   block_id,
        "block_name": block["name"],
    })


@bp.route("/apply", methods=["POST"])
@api_scheduler_required
def apply():
    body = request.get_json(silent=True) or {}
    block_id          = body.get("block_id")
    matched_requests  = body.get("matched_requests", [])
    matched_unavail   = body.get("matched_unavail", [])

    if not block_id:
        return jsonify({"error": "block_id is required"}), 400

    with get_db() as conn:
        block = conn.execute("SELECT id FROM schedule_blocks WHERE id = ?", (block_id,)).fetchone()
        if not block:
            return jsonify({"error": "Block not found"}), 404

        requests_imported = 0
        unavail_imported  = 0

        for r in matched_requests:
            conn.execute(
                "INSERT OR IGNORE INTO staff_requests (block_id, staff_id, date, skill_id) VALUES (?,?,?,?)",
                (block_id, r["staff_id"], r["date"], r["skill_id"]),
            )
            requests_imported += conn.execute("SELECT changes()").fetchone()[0]

        for u in matched_unavail:
            conn.execute(
                "INSERT OR IGNORE INTO staff_unavailability (block_id, staff_id, date) VALUES (?,?,?)",
                (block_id, u["staff_id"], u["date"]),
            )
            unavail_imported += conn.execute("SELECT changes()").fetchone()[0]

        conn.commit()

    return jsonify({"ok": True, "requests_imported": requests_imported, "unavail_imported": unavail_imported})
