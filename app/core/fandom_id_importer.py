from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
import csv
import io
import json
import re
from typing import Iterable

from app.core.resources import resource_path

FIELDNAMES = ["Category", "EditorID", "FormID", "Name", "Value", "Source", "Notes"]


def normalize_form_id(value: str) -> str:
    v = value.strip().replace("0x", "").replace("0X", "").replace(" ", "")
    v = v.replace("xx", "XX").replace("Xx", "XX")
    if not v:
        return ""
    if re.fullmatch(r"(?i)xx[0-9a-f]{1,6}", v):
        return "XX" + v[2:].upper().zfill(6)
    if re.fullmatch(r"(?i)[0-9a-f]{1,8}", v):
        return v.upper().zfill(8)
    return v.upper()


def editor_id_from_name(name: str) -> str:
    s = "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", name) if part)
    if not s:
        s = "SkyrimId"
    if s[0].isdigit():
        s = "ID" + s
    return s[:64]


@dataclass(slots=True)
class HarvestResult:
    records: list[dict[str, str]]
    pages_ok: int
    pages_failed: int
    errors: list[str]


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag == "table":
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = []
        elif self.in_cell and tag == "br":
            self.current_cell.append(" | ")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in ("td", "th") and self.in_cell:
            text = clean_text("".join(self.current_cell))
            self.current_row.append(text)
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if any(c for c in self.current_row):
                self.rows.append(self.current_row)
            self.in_row = False
        elif tag == "table" and self.in_table:
            self.in_table = False

    def handle_data(self, data: str):
        if self.in_cell:
            self.current_cell.append(data)


def clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_source_pages() -> list[dict[str, str]]:
    path = resource_path("database", "fandom_source_pages.json")
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item) for item in data]


def fetch_page(url: str, timeout: int = 25) -> str:
    request = Request(url, headers={"User-Agent": "SkyrimSaveLab/1.0 (+local reference importer)"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def records_to_csv_text(records: Iterable[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
    writer.writeheader()
    for rec in records:
        writer.writerow({field: rec.get(field, "") for field in FIELDNAMES})
    return out.getvalue()


def harvest_all_source_pages(timeout: int = 25) -> HarvestResult:
    records: list[dict[str, str]] = []
    errors: list[str] = []
    pages_ok = 0
    pages_failed = 0
    for page in load_source_pages():
        try:
            html = fetch_page(page["url"], timeout=timeout)
            page_records = parse_fandom_page(html, page["category"], page["url"], page.get("notes", ""))
            records.extend(page_records)
            pages_ok += 1
        except Exception as exc:  # network/pages are user-local and can fail independently
            pages_failed += 1
            errors.append(f"{page.get('category', page.get('url', 'Unknown'))}: {exc}")
    return HarvestResult(records=dedupe_records(records), pages_ok=pages_ok, pages_failed=pages_failed, errors=errors)


def parse_fandom_page(html: str, category: str, source_url: str, note: str = "") -> list[dict[str, str]]:
    parser = _TableParser()
    parser.feed(html)
    records: list[dict[str, str]] = []
    for row in parser.rows:
        records.extend(parse_table_row(row, category, source_url, note))
    # Fallback for Fandom's mobile/simple layouts where tables flatten into text.
    if not records:
        text = clean_text(re.sub(r"<[^>]+>", " ", html))
        records.extend(parse_flat_text(text, category, source_url, note))
    return dedupe_records(records)


def parse_table_row(cells: list[str], category: str, source_url: str, note: str = "") -> list[dict[str, str]]:
    cells = [clean_text(c) for c in cells if clean_text(c)]
    if len(cells) < 2:
        return []
    out: list[dict[str, str]] = []
    # Common Fandom shape: Name | ID | Name | ID
    for i in range(0, len(cells) - 1, 2):
        name_cell, id_cell = cells[i], cells[i + 1]
        out.extend(records_from_name_id_cell(name_cell, id_cell, category, source_url, note))
    # Some rows are Name | Type | ID or Name | ID | Weight | Value. Try the last ID-looking cell too.
    if not out:
        id_candidates = [c for c in cells if find_ids(c)]
        name_candidates = [c for c in cells if not find_ids(c) and c.lower() not in {"name", "id", "editor id", "type", "value", "weight"}]
        if name_candidates and id_candidates:
            out.extend(records_from_name_id_cell(name_candidates[0], id_candidates[-1], category, source_url, note))
    return out


def records_from_name_id_cell(name_cell: str, id_cell: str, category: str, source_url: str, note: str) -> list[dict[str, str]]:
    name = clean_name(name_cell)
    if not name or name.lower() in {"name", "id", "item id", "editor id"}:
        return []
    ids = find_ids(id_cell)
    if not ids:
        # Leveled entries sometimes come as "1-11: 000AB702 | 12-18: 000F5D1A".
        ids = find_ids(name_cell)
        name = clean_name(re.sub(r"(?i)(xx\s*)?[0-9a-f]{5,8}|\d+\s*[+–-]?\s*\d*\s*:", " ", name_cell))
    records = []
    for raw_id, label in ids:
        fid = normalize_form_id(raw_id)
        label_suffix = f" ({label})" if label else ""
        records.append({
            "Category": category,
            "EditorID": editor_id_from_name(name + label_suffix),
            "FormID": fid,
            "Name": name + label_suffix,
            "Value": "",
            "Source": source_url,
            "Notes": f"Harvested from linked Fandom table. {note}".strip(),
        })
    return records


def parse_flat_text(text: str, category: str, source_url: str, note: str) -> list[dict[str, str]]:
    # Conservative fallback: capture a title-like phrase immediately before an ID.
    out: list[dict[str, str]] = []
    pattern = re.compile(r"([A-Z][A-Za-z0-9'’\- ]{2,80})\s+((?:(?:xx|XX)\s*)?[0-9A-Fa-f]{5,8})")
    for match in pattern.finditer(text):
        name = clean_name(match.group(1))
        if not name or name.lower() in {"name", "id", "the following"}:
            continue
        fid = normalize_form_id(match.group(2))
        out.append({
            "Category": category,
            "EditorID": editor_id_from_name(name),
            "FormID": fid,
            "Name": name,
            "Value": "",
            "Source": source_url,
            "Notes": f"Harvested from linked Fandom page text. {note}".strip(),
        })
    return out


def clean_name(value: str) -> str:
    v = clean_text(value)
    v = re.sub(r"(?i)^name$", "", v).strip()
    v = re.sub(r"(?i)\b(DG|DR|HF)\b", "", v).strip()
    v = re.sub(r"\s+", " ", v).strip(" -:|")
    return v


def find_ids(value: str) -> list[tuple[str, str]]:
    text = clean_text(value)
    matches: list[tuple[str, str]] = []
    # Labelled ranges: "1-11: 000AB702" or "46+: 000F71D0".
    for label, fid in re.findall(r"(\d+\s*(?:[–-]\s*\d+|\+)?)\s*:\s*((?:(?:xx|XX)\s*)?[0-9A-Fa-f]{5,8})", text):
        matches.append((fid, f"Lv {re.sub(r'\\s+', '', label).replace('-', '–')}"))
    # Plain IDs including split "xx 014fce".
    for fid in re.findall(r"(?i)(?:xx\s*)?[0-9a-f]{5,8}", text):
        normalized = normalize_form_id(fid)
        if not any(normalize_form_id(existing) == normalized for existing, _ in matches):
            matches.append((fid, ""))
    return matches


def dedupe_records(records: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for rec in records:
        fid = normalize_form_id(rec.get("FormID", ""))
        name = clean_name(rec.get("Name", ""))
        cat = rec.get("Category", "").strip()
        if not fid or not name or not cat:
            continue
        key = (cat.casefold(), fid, name.casefold())
        if key in seen:
            continue
        seen.add(key)
        r = dict(rec)
        r["FormID"] = fid
        r["Name"] = name
        r["EditorID"] = r.get("EditorID") or editor_id_from_name(name)
        out.append(r)
    return out


# --- Deep Fandom importer helpers added by the deep ID pass ---

def records_from_plain_seed_text(text: str, category: str, source_url: str, note: str = "") -> list[dict[str, str]]:
    """Parse simple `Name FORMID` / `Name XXFORMID` lines into reference rows.

    This is used by the bundled seed packs and is also useful when copying a rendered
    Fandom table into a local text file for import.
    """
    rows: list[dict[str, str]] = []
    last_name = ""
    for line in (text or "").splitlines():
        line = clean_text(line)
        if not line:
            continue
        line = re.sub(r"^L\d+:\s*", "", line)
        ids = find_ids(line)
        if not ids:
            # A continuation line can still be a name carrier for the next numeric-only rows.
            if re.search(r"[A-Za-z]", line):
                last_name = clean_name(line)
            continue
        name_part = line
        first = re.search(r"(?i)(?:xx\s*)?[0-9a-f]{5,8}", line)
        if first:
            name_part = line[:first.start()]
        name = clean_name(name_part) or last_name
        # Trim common generated-table type columns that sometimes land between name and ID.
        name = re.split(r"\b(?:Miscellaneous Item|Quest Item|Housebuilding Item|Precious gem|Crafting Material|Ingot|Ore|Soul Gem|Potion|Unique item|Unobtainable item)\b", name, flags=re.I)[0].strip()
        if not name:
            name = last_name
        if not name:
            continue
        last_name = name
        for raw_id, label in ids:
            fid = normalize_form_id(raw_id)
            suffix = f" ({label})" if label else ""
            rows.append({
                "Category": category,
                "EditorID": editor_id_from_name(name + suffix),
                "FormID": fid,
                "Name": name + suffix,
                "Value": "",
                "Source": source_url,
                "Notes": f"Bundled/rendered Fandom table import. {note}".strip(),
            })
    return dedupe_records(rows)



# --- ID-first parser added by the magic/apparel pass ---

def records_from_id_first_seed_text(text: str, category: str, source_url: str, note: str = "") -> list[dict[str, str]]:
    """Parse rendered lines such as `000AA155 Absorb Health EnchAbsorbHealthFFContact y y`.

    Fandom's enchantment page is mostly ID-first rather than Name-first, so this helper
    keeps the first human-readable phrase after the FormID and discards common editor/flag tail data.
    """
    rows: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        line = clean_text(line)
        line = re.sub(r"^L\d+:\s*", "", line)
        m = re.match(r"^((?:(?:xx|XX)\s*)?[0-9A-Fa-f]{5,8})\s+(.+)$", line)
        if not m:
            continue
        fid = normalize_form_id(m.group(1))
        rest = m.group(2)
        rest = re.split(r"\s+[A-Za-z0-9_]*[A-Z][A-Za-z0-9_]*\s+(?:y|n)\b", rest, maxsplit=1)[0]
        rest = re.split(r"\s+\b(?:y|n)\b", rest, maxsplit=1)[0]
        name = clean_name(rest)
        if not name or name.lower() in {"name", "id", "ench id", "enchantment"}:
            continue
        rows.append({
            "Category": category,
            "EditorID": editor_id_from_name(name),
            "FormID": fid,
            "Name": name,
            "Value": "",
            "Source": source_url,
            "Notes": f"Parsed from ID-first Fandom table text. {note}".strip(),
        })
    return dedupe_records(rows)
