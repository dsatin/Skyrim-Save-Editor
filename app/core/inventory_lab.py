from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import csv
import struct

from app.core.skyrim_ess import (
    EssParseError,
    ChangeFormEntry,
    decode_refid,
    encode_default_refid,
    iter_change_forms,
    read_ess,
    rebuild_save_with_payload,
)
from app.core.player_payload import load_player_data, rebuild_save_with_player_data

PLAYER_REFID_HEX = "400014"
MAX_SAFE_INVENTORY_COUNT = 999_999_999


def validate_inventory_amount(amount: int) -> int:
    amount = int(amount)
    if amount < 0:
        raise ValueError("Inventory amount must be zero or positive")
    if amount > MAX_SAFE_INVENTORY_COUNT:
        raise ValueError(f"Inventory amount must be {MAX_SAFE_INVENTORY_COUNT:,} or lower")
    return amount

# Small built-in labels. The real database page can load the user's full Google Sheet CSV.
KNOWN_NAMES = {
    "0000000F": "Gold",
    "0000000A": "Lockpick",
    "0001397D": "Iron Arrow",
    "0001397E": "Iron Dagger",
    "00012EB7": "Iron Sword",
    "00012EB6": "Iron Shield",
    "00013790": "Iron War Axe",
    "0003B562": "Long Bow",
    "00013982": "Iron Mace",
    "00013981": "Iron Warhammer",
    "0003C9FE": "Roughspun Tunic",
    "0003CA00": "Footwraps",
    "0001D4EC": "Food / misc candidate",
    "0003EADD": "Potion of Minor Healing",
    "0003EAE0": "Potion of Minor Magicka",
    "00039B4A": "Potion of Resist Fire",
    "0003EAE5": "Potion of Minor Stamina",
    "0003EB2A": "Potion of the Warrior",
    "0003EB33": "Potion of Light Feet",
    "000F86FE": "Survival/CC candidate",
    "000319E3": "Tankard",
    "00012FDF": "Bucket",
    "0006717F": "Broom",
    "00033761": "Roll of Paper",
    "00031941": "Wooden Plate",
    "00012FE7": "Basket",
    "00012FE8": "Basket",
    "00012FE9": "Basket",
    "00012FEA": "Basket",
    "00012FEB": "Basket",
    "00012FEC": "Basket",
    "0003199A": "Wooden Bowl",
    "00012FE6": "Kettle",
    "000318FB": "Cast Iron Pot",
    "000318FA": "Cast Iron Pot",
    "000319E5": "Wooden Ladle",
    "00064B3F": "Cabbage",
    "00064B40": "Carrot",
    "00064B41": "Potato",
}

def _load_reference_known_names() -> dict[str, str]:
    """Load the packaged reference database so inventory detection can score real Skyrim IDs.

    The older scanner only treated a small hand-written list as "known", which caused
    long inventories to be trimmed when newer saves started with items outside that list.
    This remains optional/fail-soft so the low-level parser can still run during tests.
    """
    out: dict[str, str] = {}
    try:
        csv_path = Path(__file__).resolve().parents[1] / "resources" / "database" / "skyrim_ids_sample.csv"
        if not csv_path.exists():
            return out
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                form_id = (row.get("FormID") or row.get("form_id") or "").strip().upper()
                if not form_id or form_id.startswith("XX") or form_id.startswith("FE"):
                    continue
                if len(form_id) <= 8 and all(ch in "0123456789ABCDEF" for ch in form_id):
                    form_id = form_id.zfill(8)[-8:]
                    name = (row.get("Name") or row.get("name") or "").strip()
                    if name:
                        out[form_id] = name
    except Exception:
        return out
    return out

REFERENCE_KNOWN_NAMES = _load_reference_known_names()
KNOWN_NAMES.update({fid: name for fid, name in REFERENCE_KNOWN_NAMES.items() if fid not in KNOWN_NAMES})
KNOWN_FORM_IDS = set(KNOWN_NAMES) | set(REFERENCE_KNOWN_NAMES)


@dataclass(slots=True)
class InventoryEntry:
    row: int
    player_data_offset: int
    payload_offset: int
    virtual_offset: int
    refid_hex: str
    ref_type: int
    ref_value: int
    form_id: str
    name: str
    raw_count: int
    displayed_count: int
    extra: int
    confidence: str
    editable: bool
    note: str

    def to_dict(self) -> dict:
        d = asdict(self)
        # Keep raw_count in JSON for research, but UI deliberately shows displayed_count only.
        return d


@dataclass(slots=True)
class PlayerInventoryBlock:
    player_change_form: ChangeFormEntry
    data_start_offset: int
    data_end_offset: int
    entries: list[InventoryEntry]
    warning: str = ""
    player_data_compressed: bool = False
    player_data_compression: str = "none"

    def to_dict(self) -> dict:
        return {
            "player_change_form": self.player_change_form.to_dict(),
            "data_start_offset": self.data_start_offset,
            "data_end_offset": self.data_end_offset,
            "entries": [e.to_dict() for e in self.entries],
            "warning": self.warning,
            "player_data_compressed": self.player_data_compressed,
            "player_data_compression": self.player_data_compression,
        }


def _read_form_id_array(doc) -> list[int]:
    """Read the save's FormIDArray table for compact RefID type 0 rows.

    DLC/plugin inventory rows often store a 3-byte RefID of type 0.  The value
    is an index into this table, whose entries are full load-order-resolved
    FormIDs such as 020098A0.  Mapping this table lets inventory offsets and
    names display the actual DLC item instead of ARRAY[n].
    """
    try:
        if not doc or not doc.payload or not doc.file_location_table:
            return []
        pos = int(doc.file_location_table.form_id_array_count_offset) - int(doc.payload.virtual_offset)
        data = doc.payload.data
        if pos < 0 or pos + 4 > len(data):
            return []
        count = struct.unpack_from("<I", data, pos)[0]
        if count < 0 or count > 1_000_000 or pos + 4 + count * 4 > len(data):
            return []
        return [struct.unpack_from("<I", data, pos + 4 + i * 4)[0] for i in range(count)]
    except Exception:
        return []


def _format_form_id(value: int) -> str:
    return f"{int(value) & 0xFFFFFFFF:08X}"


def read_player_inventory(path: str | Path) -> PlayerInventoryBlock:
    ctx = load_player_data(path)
    doc = ctx.doc
    if not doc.payload:
        raise EssParseError("Save payload/change forms were not decoded.")
    player_cf = ctx.change_form
    player_data = ctx.player_data
    rel_start = ctx.raw_start_rel
    form_id_array = _read_form_id_array(doc)

    candidates, warning = _find_inventory_candidates(player_data, form_id_array)
    common_candidates = _find_common_inventory_candidates(player_data)
    if common_candidates:
        # Controlled add/remove saves showed that broad RefID scans can also find
        # stale Gold/Lockpick-looking bytes outside the real inventory list.  Keep
        # a direct-scanned common row only when the main inventory cluster does not
        # already contain that FormID. This avoids duplicate zero-count Lockpick
        # rows and keeps the inventory-list count research sane.
        clustered_common_ids = {c["form_id"] for c in candidates if c["form_id"] in ("0000000F", "0000000A")}
        by_offset = {c["offset"]: c for c in candidates}
        added_direct: list[str] = []
        skipped_direct: list[str] = []
        for c in common_candidates:
            if c["form_id"] in clustered_common_ids:
                skipped_direct.append(c["form_id"])
                continue
            by_offset.setdefault(c["offset"], c)
            added_direct.append(c["form_id"])
        candidates = sorted(by_offset.values(), key=lambda c: c["offset"])
        if added_direct:
            if warning:
                warning += " "
            warning += "Gold/Lockpick rows were direct-scanned from the full player ChangeForm."
        if skipped_direct:
            if warning:
                warning += " "
            warning += "Skipped duplicate direct common RefID hits outside the main inventory cluster."
    tail_candidates = _find_inventory_tail_candidates(player_data, candidates, form_id_array)
    if tail_candidates:
        by_offset = {c["offset"]: c for c in candidates}
        for c in tail_candidates:
            by_offset.setdefault(c["offset"], c)
        candidates = sorted(by_offset.values(), key=lambda c: c["offset"])
        if warning:
            warning += " "
        warning += "Merged simple rows found at the end of the full inventory list."
    if not candidates:
        raise EssParseError("Could not identify a player inventory candidate block in the player change form.")

    entries: list[InventoryEntry] = []
    for row, cand in enumerate(candidates):
        off = cand["offset"]
        ref = player_data[off:off + 3]
        raw_count = struct.unpack_from("<i", player_data, off + 3)[0]
        extra = player_data[off + 7]
        ref_type, ref_value = decode_refid(ref)
        form_id = _form_id_from_ref(ref_type, ref_value, form_id_array)
        displayed = abs(raw_count) if raw_count < 0 else raw_count
        editable = ref_type in (0, 1) and (raw_count != 0 or form_id in KNOWN_FORM_IDS or ref_type == 0)
        if raw_count == 0:
            note = "dormant zero-count row; New Count > 0 re-adds this existing row without inserting bytes"
        elif extra:
            note = "count field found; has extra-data flags, save-copy edits only"
        else:
            note = "count field found; save-copy edits only"
        if ctx.compressed:
            note += "; player ChangeForm is zlib-compressed and will be recompressed on save"
        virtual = ctx.local_to_virtual(off)
        entries.append(InventoryEntry(
            row=row,
            player_data_offset=off,
            payload_offset=virtual - doc.payload.virtual_offset,
            virtual_offset=virtual,
            refid_hex=ref.hex().upper(),
            ref_type=ref_type,
            ref_value=ref_value,
            form_id=form_id,
            name=KNOWN_NAMES.get(form_id, ""),
            raw_count=raw_count,
            displayed_count=displayed,
            extra=extra,
            confidence=cand["confidence"],
            editable=editable,
            note=note,
        ))

    return PlayerInventoryBlock(
        player_change_form=player_cf,
        data_start_offset=ctx.local_to_virtual(candidates[0]["offset"]),
        data_end_offset=ctx.local_to_virtual(candidates[-1]["offset"] + 8),
        entries=entries,
        warning=warning,
        player_data_compressed=ctx.compressed,
        player_data_compression=ctx.compression_name,
    )


def patch_player_inventory_counts(source: str | Path, target: str | Path, updates: dict[str, int]) -> PlayerInventoryBlock:
    """Patch existing player inventory count fields only. This does not insert new rows."""
    cleaned_updates: dict[str, int] = {}
    for fid, amount in updates.items():
        form_id = fid.strip().replace("0x", "").replace("0X", "").upper().zfill(8)[-8:]
        cleaned_updates[form_id] = validate_inventory_amount(amount)

    block = read_player_inventory(source)
    offset_updates: dict[int, int] = {}
    for entry in block.entries:
        if entry.form_id not in cleaned_updates or not entry.editable:
            continue
        offset_updates[int(entry.payload_offset)] = cleaned_updates[entry.form_id]
    if not offset_updates:
        raise ValueError("None of the requested FormIDs were editable existing count rows in the current player inventory block.")
    return patch_player_inventory_entry_counts(source, target, offset_updates)




def patch_player_inventory_entry_counts(source: str | Path, target: str | Path, updates: dict[int, int]) -> PlayerInventoryBlock:
    """Patch exact existing player inventory rows by payload offset.

    This is safer than FormID-only patching because Skyrim can keep multiple stacks
    of the same base item when enchantments, tempering, poison, ownership, or other
    extra data are attached. The UI stores each row's payload offset and sends those
    exact offsets here. This does not insert new rows.
    """
    cleaned_updates: dict[int, int] = {}
    for key, amount in updates.items():
        off = int(key)
        amount = validate_inventory_amount(amount)
        cleaned_updates[off] = amount

    if not cleaned_updates:
        raise ValueError("No inventory count changes were supplied.")

    ctx = load_player_data(source)
    block = read_player_inventory(source)
    by_offset = {int(entry.payload_offset): entry for entry in block.entries}
    player_data = bytearray(ctx.player_data)
    changed = False
    skipped: list[str] = []

    for payload_offset, desired in cleaned_updates.items():
        entry = by_offset.get(int(payload_offset))
        if not entry:
            skipped.append(f"0x{payload_offset:X}: row not found in current inventory parse")
            continue
        if not entry.editable:
            skipped.append(f"{entry.name or entry.form_id}: row is not editable")
            continue
        if desired == 0:
            stored = 0
        elif entry.raw_count < 0:
            stored = -desired
        elif entry.raw_count == 0 and entry.form_id not in ("0000000F", "0000000A"):
            # Controlled PS4 saves showed removal leaves a dormant 0-count row
            # and in-game re-add stores the revived count as negative for that row
            # shape (for example Iron War Axe: 00 00 00 00 -> FF FF FF FF).
            # Use the same sign style when reactivating dormant rows.
            stored = -desired
        else:
            stored = desired
        struct.pack_into("<i", player_data, int(entry.player_data_offset) + 3, stored)
        changed = True

    if not changed:
        details = "; ".join(skipped) if skipped else "No editable rows matched the requested offsets."
        raise ValueError(details)

    rebuild_save_with_player_data(source, target, bytes(player_data))
    return read_player_inventory(target)


def _form_id_from_ref(ref_type: int, ref_value: int, form_id_array: list[int] | None = None) -> str:
    if ref_type == 1:
        return f"{ref_value:08X}"
    if ref_type == 2:
        return f"FF{ref_value:06X}"[-8:]
    if ref_type == 0:
        if form_id_array is not None and 0 <= ref_value < len(form_id_array):
            return _format_form_id(form_id_array[ref_value])
        return f"ARRAY[{ref_value}]"
    return f"UNKNOWN[{ref_value:06X}]"


def _find_inventory_candidates(player_data: bytes, form_id_array: list[int] | None = None) -> tuple[list[dict], str]:
    raw_candidates = []
    max_scan = min(len(player_data) - 8, 0x1400)
    for off in range(0, max_scan):
        c = _candidate_at(player_data, off, form_id_array)
        if c:
            raw_candidates.append(c)
    if not raw_candidates:
        return [], ""

    # Group nearby candidates. Variable extra-data chunks make the stride non-uniform,
    # so this is intentionally cluster-based rather than fixed 8-byte rows only.
    clusters: list[list[dict]] = []
    cur: list[dict] = []
    last_off: int | None = None
    for c in raw_candidates:
        off = c["offset"]
        if last_off is None or off - last_off <= 24:
            cur.append(c)
        else:
            if cur:
                clusters.append(cur)
            cur = [c]
        last_off = off
    if cur:
        clusters.append(cur)

    best: list[dict] = []
    best_score = -1_000_000
    for cl in clusters:
        if not cl:
            continue
        collapsed = _collapse_overlaps(cl)
        known_count = sum(1 for c in collapsed if c["known"])
        anchors = sum(1 for c in collapsed if c["form_id"] in ("0000000F", "0000000A"))
        nonzero = sum(1 for c in collapsed if c["raw_count"] != 0)
        # Prefer the long contiguous inventory run. A full reference DB now makes real
        # gameplay items score as known, so we do not trim off leading equipment/loot.
        score = len(collapsed) * 7 + known_count * 18 + anchors * 45 + nonzero * 2 - collapsed[0]["offset"] // 256
        if score > best_score:
            best_score = score
            best = collapsed

    if not best:
        return [], ""

    warning = ""
    if best[0]["offset"] not in (0x127, 0x137, 0x15D):
        warning = f"Inventory candidates found at player-data offset 0x{best[0]['offset']:X}; verify with controlled save comparisons."
    return best, warning


def _find_common_inventory_candidates(player_data: bytes) -> list[dict]:
    """Direct-scan Gold and Lockpick rows across the full player ChangeForm.

    The broader inventory-cluster picker can select a key/equipment cluster on
    large SSE saves and miss common rows.  These two base-game rows have stable
    default RefIDs, so scan them directly and merge them into the inventory list.
    """
    out: list[dict] = []
    seen: set[int] = set()
    for form_id in ("0000000F", "0000000A"):
        ref = encode_default_refid(int(form_id, 16))
        pos = 0
        while True:
            off = player_data.find(ref, pos)
            if off < 0:
                break
            pos = off + 1
            if off in seen or off + 8 > len(player_data):
                continue
            raw_count = struct.unpack_from("<i", player_data, off + 3)[0]
            extra = player_data[off + 7]
            if abs(raw_count) > MAX_SAFE_INVENTORY_COUNT:
                continue
            # Common rows in real saves can carry non-zero flag/extra bytes
            # such as 0x1C or 0x40.  Because the RefID is exact and the count is
            # in-range, keep the row instead of filtering it out like generic
            # inventory candidates.
            seen.add(off)
            out.append({
                "offset": off,
                "form_id": form_id,
                "raw_count": raw_count,
                "extra": extra,
                "known": True,
                "score": 1000,
                "confidence": "direct-common",
            })
    return sorted(out, key=lambda c: c["offset"])


def _find_inventory_tail_candidates(player_data: bytes, current: list[dict], form_id_array: list[int] | None = None) -> list[dict]:
    """Find simple rows inserted after the complex inventory tail.

    Brand-new PS4 rows from controlled saves appear immediately before the next
    BShkbAnimationGraph player-data field, which can be far enough from the main
    simple-row cluster that the cluster picker drops it.  Scan that tail region
    and merge known simple rows back into the inventory UI.
    """
    if not current:
        return []
    try:
        start = max(c["offset"] + 8 for c in current)
        end = _find_inventory_full_insert_offset(player_data, [
            InventoryEntry(0, c["offset"], 0, c["offset"], "", 1, 0, c.get("form_id", ""), "", int(c.get("raw_count", 0)), abs(int(c.get("raw_count", 0))), int(c.get("extra", 0)), "", True, "")
            for c in current
        ])
    except Exception:
        return []
    out: list[dict] = []
    seen_offsets = {int(c["offset"]) for c in current}
    for off in range(start, max(start, end)):
        if off in seen_offsets:
            continue
        c = _candidate_at(player_data, off, form_id_array)
        if not c:
            continue
        # Only trust known/default rows in this tail. Unknown byte patterns here
        # can belong to the next player-data field, not the inventory list.
        if not c.get("known"):
            continue
        c = dict(c)
        c["confidence"] = "tail-inventory"
        out.append(c)
    return _collapse_overlaps(out)


def _candidate_at(player_data: bytes, off: int, form_id_array: list[int] | None = None) -> dict | None:
    if off + 8 > len(player_data):
        return None
    ref = player_data[off:off + 3]
    ref_type, ref_value = decode_refid(ref)
    # Keep the production inventory scanner on safe simple/default rows only.
    # Type-0 FormIDArray rows need a real list walker because zero-heavy player
    # data can otherwise create false inventory clusters. The database UI still
    # resolves XX placeholders to the loaded save's plugin bytes for add/search.
    if ref_type != 1 or ref_value <= 0 or ref_value > 0x3FFFFF:
        return None
    raw_count = struct.unpack_from("<i", player_data, off + 3)[0]
    extra = player_data[off + 7]
    form_id = _form_id_from_ref(ref_type, ref_value, form_id_array)
    known = form_id in KNOWN_FORM_IDS

    if extra > 0x10:
        return None
    if raw_count == 0 and not known:
        return None
    if known:
        # Gold/lockpicks and other known items can legitimately be edited to high
        # values by this tool. Keep them detectable after a large edit so the
        # General/Common tab and Player Inventory tab stay in sync on reload.
        if abs(raw_count) > MAX_SAFE_INVENTORY_COUNT:
            return None
    else:
        # Unknown high-count byte patterns inside animation strings create many false positives.
        if abs(raw_count) > 500:
            return None

    score = 0
    if known:
        score += 50
    if form_id in ("0000000F", "0000000A"):
        score += 50
    if abs(raw_count) <= 100:
        score += 10
    if extra in (0, 4, 8):
        score += 5
    if raw_count != 0:
        score += 3
    return {
        "offset": off,
        "form_id": form_id,
        "raw_count": raw_count,
        "extra": extra,
        "known": known,
        "score": score,
        "confidence": "mapped" if known else "candidate",
    }

def _collapse_overlaps(candidates: list[dict]) -> list[dict]:
    out: list[dict] = []
    for c in candidates:
        if not out:
            out.append(c)
            continue
        prev = out[-1]
        if c["offset"] < prev["offset"] + 8:
            if c["score"] > prev["score"]:
                out[-1] = c
            continue
        out.append(c)
    return out



def decode_vsval_at(data: bytes, offset: int) -> tuple[int, int]:
    """Decode Skyrim/Bethesda VSVal at offset as (value, encoded_size)."""
    if offset < 0 or offset >= len(data):
        raise ValueError("VSVal offset is outside data")
    first = data[offset]
    tag = first & 0x03
    if tag == 0:
        return first >> 2, 1
    if tag == 1:
        if offset + 2 > len(data):
            raise ValueError("Truncated 2-byte VSVal")
        raw = struct.unpack_from("<H", data, offset)[0]
        return raw >> 2, 2
    if tag == 2:
        if offset + 4 > len(data):
            raise ValueError("Truncated 4-byte VSVal")
        raw = struct.unpack_from("<I", data, offset)[0]
        return raw >> 2, 4
    raise ValueError("Unsupported VSVal tag 3")


def encode_vsval(value: int) -> bytes:
    """Encode a non-negative Skyrim/Bethesda VSVal."""
    value = int(value)
    if value < 0:
        raise ValueError("VSVal cannot be negative")
    if value <= 0x3F:
        return bytes([(value << 2) | 0])
    if value <= 0x3FFF:
        return struct.pack("<H", (value << 2) | 1)
    if value <= 0x3FFFFFFF:
        return struct.pack("<I", (value << 2) | 2)
    raise ValueError("VSVal is too large")


def _find_inventory_full_insert_offset(player_data: bytes, entries: list[InventoryEntry]) -> int:
    """Find the end of the real inventory list, not just the last simple row.

    Controlled PS4 add/remove saves showed that the simple editable rows are
    followed by a few complex/unmapped inventory rows. The next field after the
    inventory list is the Havok animation graph block, which begins with two
    variable bytes then:

        01 02 00 00 00 13 00 "BShkbAnimationGraph"

    Direct insertion must happen before that next field. Inserting after the
    last simple row leaves the new item inside the complex tail and the game can
    load the save without showing the item in the player inventory.
    """
    if not entries:
        raise EssParseError("No inventory rows were detected, so no safe insertion point is available.")
    last_simple_end = max(int(e.player_data_offset) + 8 for e in entries)
    marker = b"BShkbAnimationGraph"
    marker_pos = player_data.find(marker, last_simple_end)
    if marker_pos < 0:
        raise EssParseError("Could not find the post-inventory BShkbAnimationGraph marker; direct insertion is not safe for this save.")
    if marker_pos >= 9 and player_data[marker_pos - 7:marker_pos] == b"\x01\x02\x00\x00\x00\x13\x00":
        insert_at = marker_pos - 9
    elif marker_pos >= 2 and player_data[marker_pos - 2:marker_pos] == b"\x13\x00":
        insert_at = marker_pos - 2
    else:
        raise EssParseError("The post-inventory marker shape did not match the controlled PS4 saves; direct insertion is not safe for this save.")
    if insert_at < last_simple_end:
        raise EssParseError("Computed full-list insertion point is before the end of the simple inventory rows.")
    return insert_at


def _find_inventory_count_vsval(player_data: bytes, first_entry_offset: int, expected_count: int) -> tuple[int, int]:
    """Find the inventory-entry count VSVal immediately before the detected list.

    The table's VSVal count can be larger than the number of simple 8-byte rows
    we expose in the UI. Controlled PS4 saves showed 103 simple editable rows but
    a stored inventory-list count of 106/107 because the list also contains a few
    complex rows with extra data after the simple stack run.

    So this finder prefers an exact match, but also accepts the nearest preceding
    VSVal whose value is >= the simple-row count and within a small complex-row
    allowance. This is what lets direct PS4 insertion work without a console.
    """
    max_extra_rows = 64

    def _acceptable(value: int) -> bool:
        return expected_count <= value <= expected_count + max_extra_rows

    exact_matches: list[tuple[int, int]] = []
    flexible_matches: list[tuple[int, int, int]] = []

    # First check the bytes directly before the first row. This is the normal
    # layout in the controlled PS4 saves: count at 0x158, first row at 0x15A.
    for size in (1, 2, 4):
        off = first_entry_offset - size
        if off < 0:
            continue
        try:
            value, actual_size = decode_vsval_at(player_data, off)
        except Exception:
            continue
        if actual_size != size or off + actual_size > first_entry_offset:
            continue
        if value == expected_count:
            exact_matches.append((off, size))
        elif _acceptable(value):
            flexible_matches.append((off, size, value))

    if exact_matches:
        return max(exact_matches, key=lambda pair: pair[0])
    if flexible_matches:
        return max(flexible_matches, key=lambda pair: pair[0])[:2]

    # Fall back to a small backward window for saves with a few header bytes
    # between the count and first simple row.
    start = max(0, first_entry_offset - 64)
    for off in range(start, first_entry_offset):
        try:
            value, size = decode_vsval_at(player_data, off)
        except Exception:
            continue
        if off + size > first_entry_offset:
            continue
        if value == expected_count:
            exact_matches.append((off, size))
        elif _acceptable(value):
            flexible_matches.append((off, size, value))
    if exact_matches:
        return max(exact_matches, key=lambda pair: pair[0])
    if flexible_matches:
        # Prefer the closest matching count field to the first inventory row.
        return max(flexible_matches, key=lambda pair: pair[0])[:2]
    raise EssParseError(
        f"Could not find the inventory count field before the item list. "
        f"Expected at least {expected_count:,} simple row(s). Direct add is not safe for this save."
    )

def rebuild_save_with_payload_variable(source: str | Path, target: str | Path, new_payload: bytes):
    """Rebuild a save after a payload-size-changing edit.

    This is intentionally separate from the fixed-size helper used for count edits.
    It updates the compressed payload size header and returns a freshly parsed document.
    Callers are responsible for updating any internal save offsets before rebuilding.
    """
    from app.core.skyrim_ess import read_ess
    doc = read_ess(source, change_form_preview_limit=0)
    if not doc.payload:
        raise EssParseError("Save payload was not decoded; cannot rebuild save.")
    raw = Path(source).read_bytes()
    prefix = raw[:doc.payload.physical_offset]
    if doc.payload.compression_type == 2:
        try:
            import lz4.block  # type: ignore
        except Exception as exc:
            raise EssParseError("Install dependency first: pip install lz4") from exc
        comp = lz4.block.compress(bytes(new_payload), store_size=False)
        out = prefix + struct.pack("<II", len(new_payload), len(comp)) + comp
    elif doc.payload.compression_type == 1:
        import zlib
        comp = zlib.compress(bytes(new_payload))
        out = prefix + struct.pack("<II", len(new_payload), len(comp)) + comp
    elif doc.payload.compression_type in (None, 0):
        out = prefix + bytes(new_payload)
    else:
        raise EssParseError(f"Unsupported payload compression type: {doc.payload.compression_type}")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    return read_ess(target, change_form_preview_limit=0)



def build_simple_player_inventory_insert_plan(source: str | Path, form_id: str, amount: int) -> str:
    """Return a human-readable plan for the fake/minimal simple-stack insertion.

    This is the safest research output for PS4 testing: it shows the exact row
    bytes, the inventory count field that must change, and the true insertion
    point before any bytes are written.
    """
    clean = form_id.strip().replace("0x", "").replace("0X", "").upper()
    if clean.startswith("XX") or clean.startswith("FE") or clean.startswith("FF"):
        raise ValueError("This FormID needs plugin/light/temp FormIDArray mapping before fake-row insertion is safe.")
    if len(clean) > 8 or not clean or any(ch not in "0123456789ABCDEF" for ch in clean):
        raise ValueError("FormID must be a hexadecimal base ID such as 000F8318.")
    clean = clean.zfill(8)[-8:]
    form_value = int(clean, 16)
    if form_value <= 0 or form_value > 0x3FFFFF:
        raise ValueError("This FormID cannot use the simple default RefID encoding yet.")
    amount = validate_inventory_amount(amount)
    if amount == 0:
        raise ValueError("A fake inserted row needs an amount above zero.")

    ctx = load_player_data(source)
    if ctx.compressed:
        raise EssParseError("Player ChangeForm is compressed; variable-size direct insertion is still blocked for this save.")
    block = read_player_inventory(source)
    entries = sorted(block.entries, key=lambda e: e.player_data_offset)
    if not entries:
        raise EssParseError("No inventory rows were detected, so no safe insertion point is available.")

    for entry in entries:
        if entry.form_id == clean:
            stored = -amount if entry.raw_count < 0 or (entry.raw_count == 0 and clean not in ("0000000F", "0000000A")) else amount
            row_bytes = bytes(ctx.player_data[entry.player_data_offset:entry.player_data_offset + 8])
            new_row = row_bytes[:3] + struct.pack("<i", stored) + row_bytes[7:8]
            return "\n".join([
                "Existing/dormant inventory row plan",
                f"Item FormID: {clean}",
                f"Existing player-data row offset: 0x{entry.player_data_offset:X}",
                f"Current raw/displayed count: {entry.raw_count} / {entry.displayed_count}",
                f"New stored count: {stored}",
                f"Existing row bytes: {row_bytes.hex(' ').upper()}",
                f"New row bytes:      {new_row.hex(' ').upper()}",
                "No bytes need to be inserted; this is the safest path.",
            ])

    count_player_off, count_size = _find_inventory_count_vsval(ctx.player_data, entries[0].player_data_offset, len(entries))
    old_count, old_count_size = decode_vsval_at(ctx.player_data, count_player_off)
    insert_player_off = _find_inventory_full_insert_offset(ctx.player_data, entries)
    row = encode_default_refid(form_value) + struct.pack("<i", int(amount)) + b"\x00"
    new_count_bytes = encode_vsval(old_count + 1)
    old_count_bytes = ctx.player_data[count_player_off:count_player_off + old_count_size]
    marker_window = ctx.player_data[insert_player_off:insert_player_off + 32]
    lines = [
        "PS4 fake/minimal simple-stack insertion plan",
        f"Item FormID: {clean}",
        f"Amount: {amount:,}",
        "",
        "Generated row bytes:",
        f"  {row.hex(' ').upper()}",
        "  layout = Encoded RefID (3) + int32 count (4) + ExtraDataCount/flag (1)",
        "",
        "Inventory-list count update:",
        f"  player-data offset: 0x{count_player_off:X}",
        f"  old count: {old_count:,}  bytes: {old_count_bytes.hex(' ').upper()}",
        f"  new count: {old_count + 1:,}  bytes: {new_count_bytes.hex(' ').upper()}",
        "",
        "Insertion point:",
        f"  player-data offset: 0x{insert_player_off:X}",
        f"  virtual offset: 0x{ctx.local_to_virtual(insert_player_off):X}",
        "  rule: insert immediately before the post-inventory BShkbAnimationGraph field prefix",
        f"  bytes at insert point now: {marker_window.hex(' ').upper()}",
        "",
        "What must be true for this to show in-game:",
        "  1. RefID must be valid/default-encoded for the base game.",
        "  2. Count must be positive for a brand-new simple row.",
        "  3. ExtraDataCount must be 00 for a clean no-extra stack.",
        "  4. The row must be inside the real inventory list, not just visible to our loose scanner.",
        "  5. The inventory-list count and player ChangeForm length must both be updated.",
        "  6. File-location offsets must shift after a size-changing edit.",
    ]
    return "\n".join(lines)


def preflight_player_inventory_insert_layout(source: str | Path) -> tuple[bool, str]:
    """Return whether this save currently has a layout safe for direct missing-stack insertion.

    This deliberately checks the save structure only.  Individual FormID validation
    still happens in the UI / insert function.  Most saves should fail closed until
    we have enough controlled pairs to prove their inventory count field and end
    marker are safe to move.
    """
    try:
        doc = read_ess(source, change_form_preview_limit=0)
        if not doc.payload or not doc.file_location_table:
            return False, "Save payload/change forms were not decoded."
        ctx = load_player_data(source)
        if ctx.compressed:
            return False, "Player ChangeForm is compressed; size-changing missing-item insertion is disabled for safety until compressed direct-add mapping is proven."
        block = read_player_inventory(source)
        entries = sorted(block.entries, key=lambda e: e.virtual_offset)
        if not entries:
            return False, "No inventory rows were detected, so there is no safe insertion point."
        player_data = ctx.player_data
        count_player_off, count_size = _find_inventory_count_vsval(player_data, entries[0].player_data_offset, len(entries))
        old_count, old_count_size = decode_vsval_at(player_data, count_player_off)
        if old_count < len(entries) or old_count_size != count_size:
            return False, "Inventory list count did not cover the detected simple rows; direct insertion would risk corrupting the player record."
        insert_player_off = _find_inventory_full_insert_offset(player_data, entries)
        # Direct add inserts after the complete inventory list, not after the
        # last simple row. The stored count may include complex rows that our UI
        # does not expose, so the insertion point is the post-inventory marker.
        complex_rows = old_count - len(entries)
        return True, (
            f"Preflight passed: inventory list count is {old_count:,}; "
            f"simple editable rows are {len(entries):,}; "
            f"complex/unmapped rows after the simple run are about {complex_rows:,}; "
            f"count field at player-data 0x{count_player_off:X}; "
            f"full-list insert point at player-data 0x{insert_player_off:X}."
        )
    except Exception as exc:
        return False, str(exc)


def insert_simple_player_inventory_item(source: str | Path, target: str | Path, form_id: str, amount: int) -> PlayerInventoryBlock:
    """Insert a missing simple inventory stack into the player change form.

    Controlled PS4 saves proved two important details:
    - brand-new rows are inserted after the full inventory list tail, immediately
      before the next BShkbAnimationGraph player-data field;
    - brand-new stack counts are stored as positive int32 values, while some
      dormant zero-count rows may reactivate with the older negative-count style.

    Scope is deliberately narrow:
    - base-game/default FormIDs only, not FF/temp, FE light, or XX placeholders
    - simple no-extra-data stacks only
    - if the item already exists, this delegates to exact count editing instead
    """
    clean = form_id.strip().replace("0x", "").replace("0X", "").upper()
    if clean.startswith("XX") or clean.startswith("FE") or clean.startswith("FF"):
        raise ValueError("This item is not direct-save-addable yet (XX/FE/FF/plugin/temp FormID). FormIDArray/plugin mapping is required before PS4 insertion is safe.")
    if len(clean) > 8 or not clean or any(ch not in "0123456789ABCDEF" for ch in clean):
        raise ValueError("FormID must be a hexadecimal base ID such as 00023D77.")
    clean = clean.zfill(8)[-8:]
    form_value = int(clean, 16)
    if form_value <= 0 or form_value > 0x3FFFFF:
        raise ValueError("This FormID needs FormIDArray/plugin insertion mapping before PS4 insertion is safe.")
    amount = validate_inventory_amount(amount)
    if amount == 0:
        raise ValueError("Use New Count = 0 on an existing row to remove a stack. New item insertion needs an amount above zero.")

    ctx = load_player_data(source)
    if ctx.compressed:
        raise EssParseError("Direct missing-item insertion is not enabled for zlib-compressed player ChangeForms yet. Fixed-size existing-row edits are still allowed.")

    block = read_player_inventory(source)
    for entry in block.entries:
        if entry.form_id == clean and entry.editable:
            return patch_player_inventory_entry_counts(source, target, {entry.payload_offset: amount})

    entries = sorted(block.entries, key=lambda e: e.player_data_offset)
    if not entries:
        raise EssParseError("No inventory rows were found, so no safe insertion point is available.")

    player_data = bytearray(ctx.player_data)
    count_player_off, count_size = _find_inventory_count_vsval(player_data, entries[0].player_data_offset, len(entries))
    old_count, old_count_size = decode_vsval_at(player_data, count_player_off)
    if old_count < len(entries) or old_count_size != count_size:
        raise EssParseError("Inventory count field changed while preparing the edit. Reopen the save and try again.")
    insert_player_off = _find_inventory_full_insert_offset(player_data, entries)

    new_count_bytes = encode_vsval(old_count + 1)
    player_data[count_player_off:count_player_off + old_count_size] = new_count_bytes
    count_delta = len(new_count_bytes) - old_count_size
    adjusted_insert = insert_player_off + (count_delta if count_player_off < insert_player_off else 0)

    row = encode_default_refid(form_value) + struct.pack("<i", int(amount)) + b"\x00"
    player_data[adjusted_insert:adjusted_insert] = row

    rebuild_save_with_player_data(source, target, bytes(player_data))
    new_block = read_player_inventory(target)
    inserted = [e for e in new_block.entries if e.form_id == clean and e.displayed_count == amount]
    if not inserted:
        raise EssParseError("The edited save rebuilt, but the inserted item was not found by the inventory parser.")
    return new_block
