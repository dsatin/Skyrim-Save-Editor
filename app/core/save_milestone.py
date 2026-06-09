from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from collections import Counter
from typing import Any

from app.core.skyrim_ess import read_ess
from app.core.inventory_lab import read_player_inventory
from app.core.id_database import IdDatabase
from app.core.resources import resource_path


@dataclass(slots=True)
class MilestoneSummary:
    save_path: str
    player_name: str
    level: int
    location: str
    game_date: str
    save_number: int
    file_size: int
    payload_size: int
    change_forms: int
    inventory_rows: int
    named_inventory_rows: int
    unknown_inventory_rows: int
    editable_inventory_rows: int
    category_counts: dict[str, int]
    key_items: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_save_milestone(path: str | Path, database_csv: str | Path | None = None) -> MilestoneSummary:
    path = Path(path)
    doc = read_ess(path, change_form_preview_limit=0)
    inv = read_player_inventory(path)
    db = IdDatabase()
    db.load_csv(database_csv or resource_path('database/skyrim_ids_sample.csv'))

    category_counts: Counter[str] = Counter()
    key_items: dict[str, int] = {}
    named = 0
    unknown = 0
    editable = 0
    interesting = {
        '0000000F': 'Gold',
        '0000000A': 'Lockpicks',
        '00039647': 'Golden Claw',
        '00039654': "Arvel's Journal",
        '0009E2A8': 'Spell Tome: Oakflesh',
        '000E0CD5': 'Scroll of Guardian Circle',
        '0005BF0F': 'Honed Ancient Nord Sword',
        '00034182': 'Ancient Nord Arrow',
        '000236A5': 'Ancient Nord Greatsword',
    }

    for entry in inv.entries:
        rec = db.by_form_id(entry.form_id)
        if rec and rec.name:
            named += 1
            cat = rec.category or 'Item'
        else:
            unknown += 1
            cat = 'Unknown'
        if entry.editable:
            editable += 1
        category_counts[cat] += 1
        if entry.form_id in interesting:
            key_items[interesting[entry.form_id]] = key_items.get(interesting[entry.form_id], 0) + entry.displayed_count

    return MilestoneSummary(
        save_path=str(path),
        player_name=doc.header.player_name,
        level=doc.header.player_level,
        location=doc.header.player_location,
        game_date=doc.header.game_date,
        save_number=doc.header.save_number,
        file_size=doc.file_size,
        payload_size=doc.payload.uncompressed_size if doc.payload else 0,
        change_forms=doc.file_location_table.change_form_count if doc.file_location_table else 0,
        inventory_rows=len(inv.entries),
        named_inventory_rows=named,
        unknown_inventory_rows=unknown,
        editable_inventory_rows=editable,
        category_counts=dict(sorted(category_counts.items())),
        key_items=dict(sorted(key_items.items())),
    )
