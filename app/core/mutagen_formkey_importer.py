from __future__ import annotations

from dataclasses import dataclass
from urllib.request import Request, urlopen
import csv
import io
import re
from typing import Iterable

FIELDNAMES = ["Category", "EditorID", "FormID", "Name", "Value", "Source", "Notes"]
REPO_RAW_BASE = "https://raw.githubusercontent.com/Mutagen-Modding/Mutagen.Bethesda.FormKeys/master/Mutagen.Bethesda.FormKeys.SkyrimSE/Skyrim"

SOURCE_FILES = [
    ("Ammo", "Arrows"),
    ("Armor", "Armor"),
    ("Book", "Books"),
    ("Key", "Keys"),
    ("MiscItem", "Misc"),
    ("Weapon", "Weapons"),
    ("Spell", "Spells"),
    ("Enchantment", "Enchantments"),
    ("MagicEffect", "Magic Effects"),
    ("Potion", "Alchemy"),
    ("Ingredient", "Ingredients"),
    ("Perk", "Perks"),
    ("Shout", "Shouts"),
    ("Scroll", "Scrolls"),
    ("SoulGem", "Soul Gems"),
    ("Faction", "Factions"),
    ("Race", "Races"),
    ("Npc", "Characters"),
    ("Weather", "Weather"),
    ("Worldspace", "Worldspaces"),
    ("Location", "Locations"),
    ("Cell", "Cells"),
]

LINE_RE = re.compile(r"public\s+static\s+FormLink<[^>]+>\s+([A-Za-z_][A-Za-z0-9_]*)\s*=>\s*Construct\(0x([0-9A-Fa-f]+)\)")

@dataclass(slots=True)
class MutagenImportResult:
    records: list[dict[str, str]]
    files_ok: int
    files_failed: int
    errors: list[str]


def _norm_form_id(hex_text: str) -> str:
    return hex_text.upper().zfill(8)[-8:]


def _display_name(editor_id: str) -> str:
    text = re.sub(r"(?<!^)([A-Z])", r" \1", editor_id)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or editor_id


def _fetch(url: str, timeout: int = 30) -> str:
    req = Request(url, headers={"User-Agent": "SkyrimSaveLab/1.0 Mutagen FormKey importer"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def parse_formkey_file(text: str, file_name: str, category: str, source_url: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for editor_id, fid in LINE_RE.findall(text or ""):
        form_id = _norm_form_id(fid)
        out.append({
            "Category": category,
            "EditorID": editor_id,
            "FormID": form_id,
            "Name": _display_name(editor_id),
            "Value": "",
            "Source": "Mutagen.Bethesda.FormKeys SkyrimSE",
            "Notes": f"Generated FormKey import from {file_name}. Display name is derived from EditorID; use Fandom/xEdit names when available. {source_url}",
        })
    return out


def dedupe_records(records: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for rec in records:
        cat = (rec.get("Category") or "").strip()
        fid = (rec.get("FormID") or "").strip().upper()
        name = (rec.get("Name") or "").strip()
        if not cat or not fid or not name:
            continue
        key = (cat.casefold(), fid, name.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append({field: rec.get(field, "") for field in FIELDNAMES})
    return out


def records_to_csv_text(records: Iterable[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
    writer.writeheader()
    for rec in records:
        writer.writerow({field: rec.get(field, "") for field in FIELDNAMES})
    return out.getvalue()


def harvest_mutagen_formkeys(timeout: int = 30) -> MutagenImportResult:
    records: list[dict[str, str]] = []
    errors: list[str] = []
    ok = failed = 0
    for file_name, category in SOURCE_FILES:
        url = f"{REPO_RAW_BASE}/{file_name}.cs"
        try:
            text = _fetch(url, timeout=timeout)
            page_records = parse_formkey_file(text, file_name, category, url)
            if not page_records:
                raise ValueError("no FormLink rows parsed")
            records.extend(page_records)
            ok += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{file_name}.cs: {exc}")
    return MutagenImportResult(records=dedupe_records(records), files_ok=ok, files_failed=failed, errors=errors)
