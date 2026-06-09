from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import io
import re
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen, Request
from typing import Iterable

from app.core.form_id_tools import infer_plugin_name, normalize_id, resolve_xx_id

PREFERRED_CATEGORY_ORDER = [
    "Arrows", "Blades", "Blunts", "Bows", "Staves",
    "Heavy Armor", "Light Armor", "Armor", "Clothing", "Jewelry", "Books", "Keys",
    "Spells", "Powers", "Abilities", "Active Effects", "Spell Tomes", "Scrolls", "Enchantments", "Perks", "Shouts", "Skills", "ActorValues",
    "Characters", "Factions", "Followers", "Races", "Worldspaces", "Cells", "Locations", "Weather",
    "Currency", "Alchemy", "Poisons", "Food", "Beverages", "Misc", "Crafting", "Ores and Ingots", "Building Materials", "Gems", "Soul Gems", "Ingredients",
    "FormIDInfo", "DetectedCandidate", "CategoryInfo",
]


@dataclass(slots=True)
class IdRecord:
    category: str
    editor_id: str
    form_id: str
    name: str
    value: str
    source: str
    notes: str
    raw: dict[str, str]


_FIELD_ALIASES = {
    "category": {"category", "type", "kind", "group", "tab"},
    "editor_id": {"editorid", "editor_id", "edid", "id", "record", "recordid"},
    "form_id": {"formid", "form_id", "hex", "idhex", "code", "itemid"},
    "name": {"name", "displayname", "display_name", "item", "description"},
    "value": {"value", "amount", "default", "points"},
    "source": {"source", "dlc", "plugin", "file", "esm", "esp"},
    "notes": {"notes", "note", "comment", "comments"},
}


def _clean_key(key: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", key.strip().lower().replace(" ", "_"))


def _pick(row: dict[str, str], canonical: str) -> str:
    aliases = _FIELD_ALIASES[canonical]
    for k, v in row.items():
        if _clean_key(k) in aliases and v is not None:
            return str(v).strip()
    return ""


class IdDatabase:
    def __init__(self) -> None:
        self.records: list[IdRecord] = []
        self.path: Path | None = None

    def load_csv(self, path: str | Path) -> list[IdRecord]:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.records = self._dedupe([self._from_row(row) for row in rows])
        self.path = path
        return self.records

    def load_csv_text(self, text: str, label: str = "downloaded CSV") -> list[IdRecord]:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        rows = list(reader)
        self.records = self._dedupe([self._from_row(row) for row in rows])
        self.path = Path(label)
        return self.records

    def merge_csv(self, path: str | Path) -> list[IdRecord]:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            incoming = [self._from_row(row) for row in reader]
        self.records = self._dedupe([*self.records, *incoming])
        self.path = Path(f"Merged + {path.name}")
        return self.records

    def merge_csv_text(self, text: str, label: str = "downloaded CSV") -> list[IdRecord]:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        incoming = [self._from_row(row) for row in reader]
        self.records = self._dedupe([*self.records, *incoming])
        self.path = Path(f"Merged + {label}")
        return self.records

    def _record_score(self, rec: IdRecord) -> tuple[int, int, int, int]:
        source = (rec.source or "").casefold()
        notes = (rec.notes or "").casefold()
        score = 0
        if rec.source.strip().lower().endswith((".esm", ".esp", ".esl")):
            score += 40
        if infer_plugin_name(rec.source, rec.editor_id, rec.name, rec.notes):
            score += 25
        if rec.editor_id:
            score += 8
        if rec.name and rec.name.casefold() not in {"unknown", "unknown item"}:
            score += 8
        if "curated" in source or "uesp" in source:
            score += 6
        if "fandom" in source:
            score += 2
        if "duplicate" in notes or "conflict" in notes:
            score -= 20
        return (score, len(rec.name or ""), len(rec.editor_id or ""), -len(rec.source or ""))

    def _dedupe(self, records: list[IdRecord]) -> list[IdRecord]:
        # First remove exact same records, then collapse exact same category+ID+name
        # to the best source row. Different names sharing one FormID are left alone
        # here because a few Skyrim rows genuinely alias or conflict; UI tables do a
        # stricter display-level de-dupe after resolving XX load-order placeholders.
        best: dict[tuple[str, str, str], IdRecord] = {}
        order: list[tuple[str, str, str]] = []
        for rec in records:
            key = (rec.category.casefold(), rec.form_id.upper(), (rec.name or rec.editor_id).casefold())
            if key not in best:
                best[key] = rec
                order.append(key)
                continue
            if self._record_score(rec) > self._record_score(best[key]):
                best[key] = rec
        return [best[key] for key in order]

    def load_google_sheet_url(self, url: str, timeout: int = 20) -> list[IdRecord]:
        csv_url = google_sheet_csv_export_url(url)
        request = Request(csv_url, headers={"User-Agent": "SkyrimSaveLab/1.0"})
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
        text = raw.decode("utf-8-sig", errors="replace")
        records = self.load_csv_text(text, label="Google Sheet CSV")
        self.path = Path("Google Sheet CSV")
        return records

    def _from_row(self, row: dict[str, str]) -> IdRecord:
        normalized = {str(k): ("" if v is None else str(v)) for k, v in row.items()}
        return IdRecord(
            category=_pick(normalized, "category"),
            editor_id=_pick(normalized, "editor_id"),
            form_id=_normalize_form_id(_pick(normalized, "form_id")),
            name=_pick(normalized, "name"),
            value=_pick(normalized, "value"),
            source=_pick(normalized, "source"),
            notes=_pick(normalized, "notes"),
            raw=normalized,
        )

    def search(self, text: str = "", category: str = "") -> list[IdRecord]:
        q = text.casefold().strip()
        cat = category.casefold().strip()
        out: list[IdRecord] = []
        for rec in self.records:
            if cat and rec.category.casefold() != cat:
                continue
            haystack = " ".join([
                rec.category, rec.editor_id, rec.form_id, rec.name, rec.value, rec.source, rec.notes,
                " ".join(rec.raw.values()),
            ]).casefold()
            if not q or q in haystack:
                out.append(rec)
        return out

    def categories(self) -> list[str]:
        order = {name.casefold(): i for i, name in enumerate(PREFERRED_CATEGORY_ORDER)}
        cats = {r.category for r in self.records if r.category}
        return sorted(cats, key=lambda c: (order.get(c.casefold(), 10_000), c.casefold()))

    def by_form_id(self, form_id: str, plugins: Iterable[str] = ()) -> IdRecord | None:
        wanted = _normalize_form_id(form_id)
        if not wanted:
            return None
        for rec in self.records:
            if rec.form_id == wanted:
                return rec
        # Prefer true save-specific XX resolution over loose suffix matching.
        plugin_list = list(plugins or [])
        if len(wanted) == 8 and plugin_list:
            for rec in self.records:
                if not rec.form_id.upper().startswith("XX"):
                    continue
                hint = infer_plugin_name(rec.source, rec.editor_id, rec.name, rec.notes) or rec.source
                resolved = resolve_xx_id(rec.form_id, hint, plugin_list)
                if resolved == wanted:
                    return rec
        # Fallback only for display labels when no plugin list was available.
        if len(wanted) == 8 and wanted[:2] not in ("00", "FE"):
            suffix = wanted[2:]
            for rec in self.records:
                if rec.form_id.upper().startswith("XX") and rec.form_id[2:].upper() == suffix:
                    return rec
        return None


def _normalize_form_id(value: str) -> str:
    v = value.strip()
    if not v:
        return ""
    v = v.replace("0x", "").replace("0X", "").replace(" ", "")
    if re.fullmatch(r"(?i)xx[0-9a-f]{1,6}", v):
        return "XX" + v[2:].upper().zfill(6)
    if re.fullmatch(r"[0-9A-Fa-f]{1,8}", v):
        return v.upper().zfill(8)
    return value.strip()


def export_template(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Category", "EditorID", "FormID", "Name", "Value", "Source", "Notes"])
        writer.writerow(["Currency", "Gold001", "0000000F", "Gold", "", "Skyrim.esm", "Base-game item FormID example"])
        writer.writerow(["Ores and Ingots", "DLC2OreStalhrim", "XX02B06B", "Stalhrim", "", "Dragonborn.esm", "XX resolves from plugin load order"])
        writer.writerow(["Skills", "Smithing", "", "Smithing", "100", "", "ActorValue token example"])
    return path


def google_sheet_csv_export_url(url: str) -> str:
    text = url.strip()
    if not text:
        raise ValueError("Paste a Google Sheets URL first.")
    parsed = urlparse(text)
    if "docs.google.com" not in parsed.netloc or "/spreadsheets/d/" not in parsed.path:
        if text.lower().endswith(".csv"):
            return text
        raise ValueError("Expected a Google Sheets URL or direct CSV URL.")
    parts = parsed.path.split("/")
    try:
        sheet_id = parts[parts.index("d") + 1]
    except (ValueError, IndexError):
        raise ValueError("Could not find the spreadsheet ID in that Google Sheets URL.")
    query = parse_qs(parsed.query)
    gid = "0"
    if "gid" in query and query["gid"]:
        gid = query["gid"][0]
    elif parsed.fragment.startswith("gid="):
        gid = parsed.fragment.split("=", 1)[1]
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
