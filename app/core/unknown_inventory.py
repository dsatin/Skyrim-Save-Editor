from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import csv
from typing import Iterable

from app.core.id_database import IdDatabase
from app.core.inventory_lab import PlayerInventoryBlock
from app.core.form_id_tools import FormIdInfo, describe_form_id


@dataclass(slots=True)
class UnknownInventoryRow:
    form_id: str
    count: int
    category_guess: str
    plugin_hint: str
    refid_hex: str
    payload_offset: int
    player_data_offset: int
    reason: str
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def format_form_id_hint(info: object) -> str:
    """Return user-facing plugin/FormID hint text for unknown inventory tables/CSV.

    Older code accidentally passed a FormIdInfo object straight into Qt table
    items, which crashes on open.  Keep this formatter permissive so future
    helper objects are rendered safely too.
    """
    if info is None:
        return ""
    if isinstance(info, str):
        return info
    if isinstance(info, FormIdInfo):
        parts: list[str] = []
        if info.plugin_name:
            parts.append(info.plugin_name)
        if info.resolved_id:
            parts.append(info.resolved_id)
        elif info.normalized:
            parts.append(info.normalized)
        if info.kind and info.kind not in parts:
            parts.append(info.kind)
        if info.warning:
            parts.append(info.warning)
        return " | ".join(part for part in parts if part)
    return str(info)


def classify_unknown_form_id(form_id: str) -> tuple[str, str]:
    fid = (form_id or '').strip().upper()
    if not fid:
        return 'Unknown', 'empty FormID'
    if fid.startswith('FF'):
        return 'Temporary / runtime', 'temporary FormID; likely save-created or runtime object'
    if fid.startswith('FE'):
        return 'Light plugin / ESL', 'FE compact FormID; needs light plugin mapping'
    if fid.startswith('ARRAY['):
        return 'Plugin FormIDArray', 'compact RefID points into save FormIDArray'
    if fid.startswith('XX'):
        return 'Plugin / DLC placeholder', 'XX placeholder needs loaded plugin slot resolution'
    try:
        value = int(fid, 16)
    except ValueError:
        return 'Unknown', 'not a standard hexadecimal FormID'
    if value >= 0x01000000:
        return 'Plugin / DLC', 'non-zero load-order byte; likely DLC or modded item'
    # Vanilla ranges that commonly show up as unknowns in our inventory parser.
    if 0x0002E4E2 <= value <= 0x0002E504:
        return 'Soul Gems', 'vanilla soul gem range'
    if 0x00089000 <= value <= 0x000CFFFF:
        return 'Enchanted Weapons/Apparel', 'vanilla enchanted/leveled item range'
    if 0x000F0000 <= value <= 0x0010FFFF:
        return 'Enchanted Weapons/Apparel', 'late vanilla enchanted apparel/robe range'
    return 'Unknown', 'not present in packaged reference database'


def collect_unknown_inventory(block: PlayerInventoryBlock | None, db: IdDatabase, plugins: Iterable[str] = ()) -> list[UnknownInventoryRow]:
    if not block:
        return []
    out: list[UnknownInventoryRow] = []
    plugin_list = list(plugins or [])
    for entry in block.entries:
        rec = db.by_form_id(entry.form_id, plugin_list) if db else None
        # Treat real named DB hits as resolved.  Do not hide a row merely because
        # the low-level inventory scanner gave it a fallback/built-in name; that
        # path can label FormIDArray/plugin rows while the packaged database still
        # has no authoritative record for them.
        if rec and (rec.name or rec.editor_id) and (rec.name or '').strip().casefold() != 'unknown item':
            continue
        category, reason = classify_unknown_form_id(entry.form_id)
        plugin_hint = format_form_id_hint(describe_form_id(entry.form_id, plugins=plugin_list)) if plugin_list else ''
        out.append(UnknownInventoryRow(
            form_id=entry.form_id,
            count=int(entry.displayed_count),
            category_guess=category,
            plugin_hint=plugin_hint,
            refid_hex=entry.refid_hex,
            payload_offset=int(entry.payload_offset),
            player_data_offset=int(entry.player_data_offset),
            reason=reason,
            note=entry.note,
        ))
    return out


def write_unknown_inventory_csv(path: str | Path, rows: list[UnknownInventoryRow]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['form_id','count','category_guess','plugin_hint','refid_hex','payload_offset','player_data_offset','reason','note']
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            d = row.to_dict()
            d['payload_offset'] = f"0x{int(row.payload_offset):X}"
            d['player_data_offset'] = f"0x{int(row.player_data_offset):X}"
            writer.writerow(d)
    return path
