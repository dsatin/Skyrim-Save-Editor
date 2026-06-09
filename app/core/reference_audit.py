from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import json
import re
from collections import Counter, defaultdict
from typing import Iterable

FANDOM_SOURCE_PAGES = [
    ("Alchemy", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Alchemy"),
    ("Arrows", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Arrows"),
    ("Blades", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Blade_Weapons"),
    ("Blunts", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Blunt_Weapons"),
    ("Books", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Books"),
    ("Bows", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Bows"),
    ("Clothing", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Clothing"),
    ("Enchantments", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Enchantments"),
    ("Heavy Armor", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Heavy_Armor"),
    ("Ingredients", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Ingredients"),
    ("Jewelry", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Jewelry"),
    ("Keys", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Keys"),
    ("Light Armor", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Light_Armor"),
    ("Misc", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Miscellaneous_Items"),
    ("Shouts", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Shouts"),
    ("Skills", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Skills"),
    ("Soul Gems", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Soul_Gems"),
    ("Spells", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Spells"),
    ("Staves", "https://elderscrolls.fandom.com/wiki/Console_Commands_(Skyrim)/Staves"),
]

EXPECTED_CATEGORY_ALIASES = {
    "Alchemy": {"Alchemy", "Poisons", "Food", "Beverages"},
    "Arrows": {"Arrows"},
    "Blades": {"Blades", "Weapons"},
    "Blunts": {"Blunts", "Weapons"},
    "Books": {"Books", "Spell Tomes"},
    "Bows": {"Bows", "Weapons"},
    "Clothing": {"Clothing"},
    "Enchantments": {"Enchantments", "Magic Effects"},
    "Heavy Armor": {"Heavy Armor", "Armor"},
    "Ingredients": {"Ingredients"},
    "Jewelry": {"Jewelry"},
    "Keys": {"Keys"},
    "Light Armor": {"Light Armor", "Armor"},
    "Misc": {"Misc", "Crafting", "Ores and Ingots", "Building Materials", "Gems"},
    "Shouts": {"Shouts"},
    "Skills": {"Skills", "ActorValues"},
    "Soul Gems": {"Soul Gems"},
    "Spells": {"Spells"},
    "Staves": {"Staves", "Weapons"},
}

ID_RE = re.compile(r"^(?:XX[0-9A-F]{6}|[0-9A-F]{8}|FE[0-9A-F]{6})$")


def _rec_attr(rec, name: str) -> str:
    return str(getattr(rec, name, "") or "")


def _quality_label(count: int) -> str:
    if count <= 0:
        return "missing"
    if count < 25:
        return "thin"
    if count < 100:
        return "partial"
    if count < 250:
        return "strong"
    return "very strong"


def audit_records(records) -> dict:
    rows = list(records or [])
    cats = Counter(_rec_attr(r, "category") for r in rows if _rec_attr(r, "category"))
    form_ids = [_rec_attr(r, "form_id").upper() for r in rows if _rec_attr(r, "form_id")]
    fid_counts = Counter(form_ids)
    malformed = []
    missing = []
    xx = []
    for i, rec in enumerate(rows, start=1):
        category = _rec_attr(rec, "category")
        name = _rec_attr(rec, "name")
        fid = _rec_attr(rec, "form_id").upper()
        if not category or not name:
            missing.append({"row": i, "category": category, "form_id": fid, "name": name})
        if fid and not ID_RE.match(fid):
            malformed.append({"row": i, "category": category, "form_id": fid, "name": name})
        if fid.startswith("XX"):
            xx.append({"row": i, "category": category, "form_id": fid, "name": name})
    page_rows = []
    for page, url in FANDOM_SOURCE_PAGES:
        aliases = EXPECTED_CATEGORY_ALIASES.get(page, {page})
        count = sum(cats.get(alias, 0) for alias in aliases)
        page_rows.append({
            "page": page,
            "expected_categories": sorted(aliases),
            "local_rows_in_related_categories": count,
            "status": _quality_label(count),
            "url": url,
        })
    return {
        "total_rows": len(rows),
        "unique_form_ids": len(set(form_ids)),
        "category_count": len(cats),
        "category_counts": dict(sorted(cats.items())),
        "duplicate_form_ids": {fid: n for fid, n in sorted(fid_counts.items()) if n > 1},
        "malformed_form_id_rows": malformed[:200],
        "missing_required_rows": missing[:200],
        "xx_placeholder_rows": len(xx),
        "source_page_checklist": page_rows,
        "notes": [
            "The audit checks the local reference pack and source-page category coverage; it cannot prove that a live Fandom page has not changed unless you use Fetch Linked Fandom Pages on the same machine.",
            "Duplicate FormIDs can be legitimate when one record appears in multiple source groups, but they should be reviewed if names conflict.",
            "XX rows are DLC/mod load-order placeholders and are expected for Dawnguard, Hearthfire, Dragonborn, and mod/plugin records.",
        ],
    }


def audit_to_summary_rows(audit: dict) -> list[tuple[str, str]]:
    return [
        ("Reference rows", f"{audit.get('total_rows', 0):,}"),
        ("Unique FormIDs / tokens", f"{audit.get('unique_form_ids', 0):,}"),
        ("Categories", f"{audit.get('category_count', 0):,}"),
        ("Duplicate FormIDs", f"{len(audit.get('duplicate_form_ids', {})):,}"),
        ("Malformed FormID rows", f"{len(audit.get('malformed_form_id_rows', [])):,}"),
        ("Missing required rows", f"{len(audit.get('missing_required_rows', [])):,}"),
        ("XX placeholder rows", f"{audit.get('xx_placeholder_rows', 0):,}"),
    ]


def write_audit_json(path: str | Path, audit: dict) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return p
