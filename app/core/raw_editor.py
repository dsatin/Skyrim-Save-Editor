
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import struct
from typing import Any

from app.core.backups import make_backup
from app.core.inventory_lab import read_player_inventory, validate_inventory_amount
from app.core.global_variables import DRAGONS_ABSORBED_FORM_ID, DRAGONS_ABSORBED_NAME, read_skyrim_dragon_souls, read_skyrim_global_variable
from app.core.skyrim_ess import EssDocument, EssParseError, read_ess
from app.core.live_player import read_live_player_fields
from app.core.race_editor import read_skyrim_race_mapping


@dataclass(slots=True)
class RawMappedField:
    field_id: str
    group: str
    field: str
    storage: str
    offset: int
    size: int
    value_type: str
    current_value: str
    editable: bool
    safety: str
    notes: str
    virtual_offset: int | None = None
    raw_value: str | None = None
    sign: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hex_off(value: int | None) -> str:
    if value is None:
        return ""
    return f"0x{int(value):X}"


def _add_field(fields: list[RawMappedField], *, group: str, field: str, storage: str, offset: int, size: int, value_type: str, current_value: object, editable: bool, safety: str, notes: str, virtual_offset: int | None = None, raw_value: object | None = None, sign: int = 1) -> None:
    fid = f"{storage}:{offset}:{value_type}:{group}:{field}".replace(" ", "_")
    fields.append(RawMappedField(
        field_id=fid,
        group=group,
        field=field,
        storage=storage,
        offset=int(offset),
        size=int(size),
        value_type=value_type,
        current_value=str(current_value),
        editable=bool(editable),
        safety=safety,
        notes=notes,
        virtual_offset=virtual_offset,
        raw_value=str(raw_value) if raw_value is not None else None,
        sign=sign,
    ))


def build_mapped_raw_fields(path: str | Path) -> list[RawMappedField]:
    """Build a user-facing map of real offsets in the save.

    The table deliberately separates editable safe fixed-size fields from read-only
    structural fields. Inventory counts are actual player-change-form bytes, not
    header display fields.
    """
    doc = read_ess(path)
    fields: list[RawMappedField] = []
    h = doc.header


    try:
        live = read_live_player_fields(doc.path)
        if live.name is not None and live.name_data_offset is not None and live.name_length is not None:
            _add_field(fields, group="Live Player", field="In-game Player Name", storage="payload", offset=live.local_to_virtual(live.name_data_offset), size=live.name_length, value_type="string_fixed", current_value=live.name, editable=(not live.compressed), safety=("Mapped live ChangeForm" if not live.compressed else "Read-only compressed ChangeForm"), notes=("ChangeForm 400007 length-prefixed player name. The General tab writes this plus the header when possible." if not live.compressed else "Compressed ChangeForm; use the General tab so the record can be decompressed/recompressed safely."))
        if live.level is not None and live.level_offset is not None:
            _add_field(fields, group="Live Player", field="In-game Player Level", storage="payload", offset=live.local_to_virtual(live.level_offset), size=4, value_type="u32", current_value=live.level, editable=(not live.compressed), safety=("Mapped live ChangeForm" if not live.compressed else "Read-only compressed ChangeForm"), notes=("ChangeForm 400007 live player level found from controlled saves. The General tab writes this plus the header." if not live.compressed else "Compressed ChangeForm; use the General tab so the record can be decompressed/recompressed safely."))
    except Exception:
        pass


    # Mapped player race refs. Tested saves store current/original race as a
    # consecutive RefID cluster in Player ChangeForm 400014, with an optional
    # mirror in Live Player ChangeForm 400007. Use General -> Player -> Race for
    # safer named edits; these raw bytes are exposed for research.
    if doc.payload:
        try:
            race_map = read_skyrim_race_mapping(path)
            for hit in (race_map.player_hit, race_map.live_hit):
                if not hit or hit.record_virtual_base is None:
                    continue
                for index, off in enumerate(hit.offsets):
                    label = "Race RefID" if len(hit.offsets) == 1 else f"Race RefID #{index + 1}"
                    payload_offset = int(hit.record_virtual_base) - int(doc.payload.virtual_offset) + int(off)
                    if payload_offset < 0 or payload_offset + 3 > len(doc.payload.data):
                        continue
                    raw_hex = doc.payload.data[payload_offset:payload_offset + 3].hex(" ").upper()
                    _add_field(
                        fields,
                        group="Live Player",
                        field=f"{hit.record_name} {label}",
                        storage="payload",
                        offset=payload_offset,
                        size=3,
                        value_type="bytes",
                        current_value=raw_hex,
                        editable=(not hit.compressed),
                        safety=("Race RefID bytes" if not hit.compressed else "Read-only compressed ChangeForm"),
                        notes=f"{hit.refid_hex} +0x{off:X}; detected {hit.current_race.editor_id}. Named race edits should be done from General -> Player.",
                        virtual_offset=int(hit.record_virtual_base) + int(off),
                    )
        except Exception:
            pass

    # Header fields are mapped for completeness, but the important non-header data
    # below is the player inventory count data inside the decompressed payload.
    _add_field(fields, group="Header", field="Player Name", storage="file", offset=h.player_name_offset + 2, size=h.player_name_capacity, value_type="string_fixed", current_value=h.player_name, editable=True, safety="Fixed slot", notes="Writes inside the existing string slot only; does not resize the header.")
    _add_field(fields, group="Header", field="Level", storage="file", offset=h.player_level_offset, size=4, value_type="u32", current_value=h.player_level, editable=True, safety="Fixed-size", notes="Same physical field used by Header Editor.")
    _add_field(fields, group="Header", field="Sex", storage="file", offset=h.player_sex_offset, size=2, value_type="u16", current_value=h.player_sex, editable=True, safety="Fixed-size", notes="0 = male, 1 = female.")
    _add_field(fields, group="Header", field="Current XP", storage="file", offset=h.player_current_exp_offset, size=4, value_type="f32", current_value=f"{h.player_current_exp:.6g}", editable=True, safety="Fixed-size", notes="Header/display XP value.")
    _add_field(fields, group="Header", field="Needed XP", storage="file", offset=h.player_needed_exp_offset, size=4, value_type="f32", current_value=f"{h.player_needed_exp:.6g}", editable=True, safety="Fixed-size", notes="Header/display XP value.")
    _add_field(fields, group="Header", field="Location Text", storage="file", offset=h.player_location_offset + 2, size=h.player_location_capacity, value_type="string_fixed", current_value=h.player_location, editable=False, safety="Read-only", notes="Header visual text. Mapping shown, but editing location text does not move the player.")
    _add_field(fields, group="Header", field="Race Text", storage="file", offset=h.player_race_offset + 2, size=h.player_race_capacity, value_type="string_fixed", current_value=h.player_race, editable=False, safety="Read-only", notes="Header visual text. Actual race data lives elsewhere.")

    if doc.payload:
        p = doc.payload
        _add_field(fields, group="Payload", field="Form Version", storage="payload", offset=0, size=1, value_type="u8", current_value=p.form_version if p.form_version is not None else "", editable=False, safety="Read-only", notes="Payload structural value.", virtual_offset=p.virtual_offset)
        if p.plugin_info_size is not None:
            _add_field(fields, group="Payload", field="Plugin Info Size", storage="payload", offset=1, size=4, value_type="u32", current_value=p.plugin_info_size, editable=False, safety="Read-only", notes="Changing this without rebuilding plugin data will corrupt the save.", virtual_offset=p.virtual_offset + 1)

    if doc.payload and doc.file_location_table:
        flt = doc.file_location_table
        names = [
            "FormID Array Count Offset", "Unknown Table 3 Offset", "Global Data Table 1 Offset", "Global Data Table 2 Offset",
            "Change Forms Offset", "Global Data Table 3 Offset", "Global Data Table 1 Count", "Global Data Table 2 Count",
            "Global Data Table 3 Count", "Change Form Count",
        ]
        base_rel = flt.offset - doc.payload.virtual_offset
        values = [
            flt.form_id_array_count_offset, flt.unknown_table_3_offset, flt.global_data_table_1_offset,
            flt.global_data_table_2_offset, flt.change_forms_offset, flt.global_data_table_3_offset,
            flt.global_data_table_1_count, flt.global_data_table_2_count, flt.global_data_table_3_count,
            flt.change_form_count,
        ]
        for i, (name, value) in enumerate(zip(names, values)):
            _add_field(fields, group="File Location Table", field=name, storage="payload", offset=base_rel + i * 4, size=4, value_type="u32", current_value=value, editable=False, safety="Read-only", notes="Core save offset/count table. Must be rebuilt by dedicated code, not hand-edited.", virtual_offset=flt.offset + i * 4)

        for entry in doc.global_data_entries[:250]:
            rel = entry.offset - doc.payload.virtual_offset
            label = f"Table {entry.table} Entry {entry.index}"
            _add_field(fields, group="Global Data", field=f"{label} Type", storage="payload", offset=rel, size=4, value_type="u32", current_value=entry.type, editable=False, safety="Read-only", notes=f"Global data entry length {entry.length:,}; sample {entry.sample_hex}", virtual_offset=entry.offset)
            _add_field(fields, group="Global Data", field=f"{label} Length", storage="payload", offset=rel + 4, size=4, value_type="u32", current_value=entry.length, editable=False, safety="Read-only", notes="Length controls the data block that follows this header.", virtual_offset=entry.offset + 4)

    # Mapped Dragon Souls.  The spendable pool is an actor value inside
    # ChangeForm 400014; the DragonsAbsorbed global is separate and stayed 0 in
    # controlled saves with 1 / 100 / 100,000 spendable souls.
    if doc.payload:
        try:
            dragon_souls = read_skyrim_dragon_souls(path)
            if dragon_souls:
                _add_field(
                    fields,
                    group="Live Player",
                    field="Dragon Souls / Spendable Actor Value",
                    storage="payload",
                    offset=dragon_souls.value_payload_offset,
                    size=4,
                    value_type="f32",
                    current_value=f"{dragon_souls.value:.6g}",
                    editable=True,
                    safety="Fixed-size actor-value float",
                    notes=f"Controlled-save mapped current Dragon Souls: ChangeForm {dragon_souls.change_form_refid_hex} +0x{dragon_souls.relative_offset:X}. Edit as a number; stored as float32.",
                    virtual_offset=dragon_souls.value_virtual_offset,
                )
        except Exception as exc:
            _add_field(fields, group="Live Player", field="Dragon Souls mapping warning", storage="none", offset=0, size=0, value_type="message", current_value=str(exc), editable=False, safety="Read-only", notes="Spendable Dragon Souls actor-value field could not be mapped for this save.")

        try:
            dragon_global = read_skyrim_global_variable(path, DRAGONS_ABSORBED_FORM_ID, name=DRAGONS_ABSORBED_NAME)
            if dragon_global:
                _add_field(
                    fields,
                    group="Global Variables",
                    field="DragonsAbsorbed Global / Not Spendable Souls",
                    storage="payload",
                    offset=dragon_global.value_payload_offset,
                    size=4,
                    value_type="f32",
                    current_value=f"{dragon_global.value:.6g}",
                    editable=False,
                    safety="Read-only",
                    notes=f"{DRAGONS_ABSORBED_FORM_ID} encoded as {dragon_global.encoded_refid_hex}; this did not track spendable Dragon Souls in controlled saves.",
                    virtual_offset=dragon_global.value_virtual_offset,
                )
        except Exception:
            pass

    # Actual non-header player data: inventory stack counts inside the player ACHR change form.
    try:
        inv = read_player_inventory(path)
        cf = inv.player_change_form
        if doc.payload:
            cf_rel = cf.offset - doc.payload.virtual_offset
            _add_field(fields, group="Player Change Form", field="Player ACHR RefID", storage="payload", offset=cf_rel, size=3, value_type="bytes", current_value=cf.refid_hex, editable=False, safety="Read-only", notes="Player change form ID.", virtual_offset=cf.offset)
            _add_field(fields, group="Player Change Form", field="Player ACHR Change Flags", storage="payload", offset=cf_rel + 3, size=4, value_type="u32", current_value=cf.change_flags, editable=False, safety="Read-only", notes="Changing flags without mapped fields can break the record.", virtual_offset=cf.offset + 3)
            length_offset = cf_rel + 9
            _add_field(fields, group="Player Change Form", field="Player Data Length", storage="payload", offset=length_offset, size={0:1,1:2,2:4}.get(cf.lengths_size, 0), value_type={0:"u8",1:"u16",2:"u32"}.get(cf.lengths_size, "bytes"), current_value=cf.length1, editable=False, safety="Read-only", notes="Record length field. Dedicated add/remove tools must maintain it.", virtual_offset=cf.offset + 9)
        for entry in inv.entries:
            name = entry.name or entry.form_id
            sign = -1 if entry.raw_count < 0 else 1
            _add_field(
                fields,
                group="Player Inventory",
                field=f"{name} ({entry.form_id}) New Count",
                storage="payload",
                offset=entry.payload_offset + 3,
                size=4,
                value_type="inventory_count",
                current_value=entry.displayed_count,
                editable=entry.editable,
                safety="Mapped count" if entry.editable else "Read-only",
                notes=f"Actual player inventory count at player-data offset 0x{entry.player_data_offset + 3:X}. {entry.note}",
                virtual_offset=entry.virtual_offset + 3,
                raw_value=entry.raw_count,
                sign=sign,
            )
    except Exception as exc:
        _add_field(fields, group="Player Inventory", field="Inventory mapping warning", storage="none", offset=0, size=0, value_type="message", current_value=str(exc), editable=False, safety="Read-only", notes="Inventory block could not be mapped for this save.")

    return fields


def _encode_value(field: RawMappedField, new_value: str) -> bytes:
    value = (new_value or "").strip()
    if field.value_type == "string_fixed":
        raw = value.encode("utf-8")
        if len(raw) > field.size:
            raise ValueError(f"{field.field}: value is {len(raw)} bytes but the fixed slot is {field.size} bytes.")
        return raw.ljust(field.size, b"\x00")
    if field.value_type == "u8":
        n = int(value, 0)
        if not 0 <= n <= 0xFF:
            raise ValueError(f"{field.field}: u8 value out of range")
        return struct.pack("<B", n)
    if field.value_type == "u16":
        n = int(value, 0)
        if not 0 <= n <= 0xFFFF:
            raise ValueError(f"{field.field}: u16 value out of range")
        return struct.pack("<H", n)
    if field.value_type == "u32":
        n = int(value, 0)
        if not 0 <= n <= 0xFFFFFFFF:
            raise ValueError(f"{field.field}: u32 value out of range")
        return struct.pack("<I", n)
    if field.value_type == "i32":
        n = int(value, 0)
        if not -0x80000000 <= n <= 0x7FFFFFFF:
            raise ValueError(f"{field.field}: i32 value out of range")
        return struct.pack("<i", n)
    if field.value_type == "inventory_count":
        n = validate_inventory_amount(int(value.replace(",", "")))
        stored = -n if field.sign < 0 else n
        return struct.pack("<i", stored)
    if field.value_type == "f32":
        return struct.pack("<f", float(value))
    if field.value_type == "bytes":
        clean = value.replace(" ", "").replace("0x", "").replace("0X", "")
        if len(clean) % 2:
            raise ValueError(f"{field.field}: hex bytes must have an even number of digits")
        raw = bytes.fromhex(clean)
        if len(raw) != field.size:
            raise ValueError(f"{field.field}: bytes patch must be exactly {field.size} bytes")
        return raw
    raise ValueError(f"{field.field}: unsupported editable type {field.value_type!r}")


def _rebuild_output(raw: bytearray, doc: EssDocument, payload: bytearray | None) -> bytes:
    if payload is None:
        return bytes(raw)
    if not doc.payload:
        raise EssParseError("No payload is available for this save.")
    prefix = bytes(raw[:doc.payload.physical_offset])
    if doc.payload.compression_type == 2:
        try:
            import lz4.block  # type: ignore
        except Exception as exc:
            raise EssParseError("This save uses LZ4 compression. Install dependency: pip install lz4") from exc
        comp = lz4.block.compress(bytes(payload), store_size=False)
        return prefix + struct.pack("<II", len(payload), len(comp)) + comp
    if doc.payload.compression_type == 1:
        import zlib
        comp = zlib.compress(bytes(payload))
        return prefix + struct.pack("<II", len(payload), len(comp)) + comp
    if doc.payload.compression_type in (None, 0):
        return prefix + bytes(payload)
    raise EssParseError(f"Unsupported payload compression type: {doc.payload.compression_type}")


def apply_mapped_raw_edits(source: str | Path, target: str | Path, edits: dict[str, str]) -> EssDocument:
    """Apply fixed-size mapped raw edits and return a newly parsed document."""
    source = Path(source)
    target = Path(target)
    if not edits:
        raise ValueError("No raw edits were supplied.")
    fields = {field.field_id: field for field in build_mapped_raw_fields(source)}
    raw = bytearray(source.read_bytes())
    doc = read_ess(source)
    payload = bytearray(doc.payload.data) if doc.payload else None
    touched = 0
    for field_id, new_text in edits.items():
        field = fields.get(field_id)
        if not field:
            raise ValueError(f"Mapped field is no longer available: {field_id}")
        if not field.editable:
            raise ValueError(f"Field is read-only: {field.field}")
        patch = _encode_value(field, new_text)
        if len(patch) != field.size:
            raise ValueError(f"{field.field}: patch changed size, refusing to write")
        if field.storage == "file":
            if field.offset < 0 or field.offset + field.size > len(raw):
                raise ValueError(f"{field.field}: file offset is outside the save")
            raw[field.offset:field.offset + field.size] = patch
            touched += 1
        elif field.storage == "payload":
            if payload is None:
                raise ValueError(f"{field.field}: payload is not decoded")
            if field.offset < 0 or field.offset + field.size > len(payload):
                raise ValueError(f"{field.field}: payload offset is outside the decoded payload")
            payload[field.offset:field.offset + field.size] = patch
            touched += 1
        else:
            raise ValueError(f"{field.field}: unsupported storage {field.storage}")
    if touched == 0:
        raise ValueError("No editable raw fields were changed.")
    out = _rebuild_output(raw, doc, payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    return read_ess(target)


def write_mapped_raw_edits_with_backup(source: str | Path, edits: dict[str, str]) -> EssDocument:
    source = Path(source)
    make_backup(source)
    return apply_mapped_raw_edits(source, source, edits)
