from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import csv
import re
from typing import Iterable, Protocol


class _IdRecordLike(Protocol):
    category: str
    editor_id: str
    form_id: str
    name: str
    value: str
    source: str
    notes: str


@dataclass(slots=True)
class CoverageSummary:
    total_rows: int
    total_categories: int
    inventory_rows: int
    mapped_inventory_rows: int
    unknown_inventory_rows: int
    editable_inventory_rows: int
    queued_edits: int = 0

    @property
    def mapped_percent(self) -> float:
        if self.inventory_rows <= 0:
            return 0.0
        return round((self.mapped_inventory_rows / self.inventory_rows) * 100.0, 1)

    def to_rows(self) -> list[tuple[str, str]]:
        return [
            ("Reference rows", f"{self.total_rows:,}"),
            ("Reference categories", f"{self.total_categories:,}"),
            ("Inventory rows", f"{self.inventory_rows:,}"),
            ("Named inventory rows", f"{self.mapped_inventory_rows:,} / {self.inventory_rows:,} ({self.mapped_percent:.1f}%)"),
            ("Unknown inventory rows", f"{self.unknown_inventory_rows:,}"),
            ("Editable inventory rows", f"{self.editable_inventory_rows:,}"),
            ("Queued count edits", f"{self.queued_edits:,}"),
        ]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["mapped_percent"] = self.mapped_percent
        return data


def build_coverage_summary(db, inventory_block=None, queued_edits: int = 0) -> CoverageSummary:
    records = getattr(db, "records", []) or []
    categories = {getattr(r, "category", "") for r in records if getattr(r, "category", "")}
    entries = getattr(inventory_block, "entries", []) if inventory_block else []
    mapped = 0
    unknown = 0
    editable = 0
    for entry in entries:
        name = _display_name_for_entry(db, entry)
        if name and name.casefold() != "unknown item":
            mapped += 1
        else:
            unknown += 1
        if getattr(entry, "editable", False):
            editable += 1
    return CoverageSummary(
        total_rows=len(records),
        total_categories=len(categories),
        inventory_rows=len(entries),
        mapped_inventory_rows=mapped,
        unknown_inventory_rows=unknown,
        editable_inventory_rows=editable,
        queued_edits=max(0, int(queued_edits)),
    )


def export_reference_csv(path: str | Path, records: Iterable[_IdRecordLike]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Category", "EditorID", "FormID", "Name", "Value", "Source", "Notes"])
        for rec in records:
            writer.writerow([
                getattr(rec, "category", ""),
                getattr(rec, "editor_id", ""),
                getattr(rec, "form_id", ""),
                getattr(rec, "name", ""),
                getattr(rec, "value", ""),
                getattr(rec, "source", ""),
                getattr(rec, "notes", ""),
            ])
    return path


def export_inventory_csv(path: str | Path, inventory_block, db=None, only_unknown: bool = False) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Category", "EditorID", "FormID", "Name", "Count", "Confidence",
            "Editable", "PayloadOffset", "VirtualOffset", "RefID", "Notes"
        ])
        for entry in getattr(inventory_block, "entries", []) or []:
            name = _display_name_for_entry(db, entry) if db is not None else (getattr(entry, "name", "") or "")
            if only_unknown and name and name.casefold() != "unknown item":
                continue
            category = "DetectedCandidate"
            if db is not None:
                rec = getattr(db, "by_form_id", lambda _x: None)(getattr(entry, "form_id", ""))
                if rec and getattr(rec, "category", ""):
                    category = rec.category
            writer.writerow([
                category,
                _editor_id_from_name(name or getattr(entry, "form_id", "")),
                getattr(entry, "form_id", ""),
                name or "Unknown item",
                getattr(entry, "displayed_count", ""),
                getattr(entry, "confidence", ""),
                "yes" if getattr(entry, "editable", False) else "no",
                f"0x{getattr(entry, 'payload_offset', 0):X}",
                f"0x{getattr(entry, 'virtual_offset', 0):X}",
                getattr(entry, "refid_hex", ""),
                getattr(entry, "note", ""),
            ])
    return path


def _display_name_for_entry(db, entry) -> str:
    form_id = getattr(entry, "form_id", "")
    rec = getattr(db, "by_form_id", lambda _x: None)(form_id) if db is not None else None
    if rec and getattr(rec, "name", ""):
        return rec.name
    return getattr(entry, "name", "") or "Unknown item"


def _editor_id_from_name(name: str) -> str:
    out = "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", name) if part)
    if not out:
        return "DetectedItem"
    if out[0].isdigit():
        out = "ID" + out
    return out[:64]
