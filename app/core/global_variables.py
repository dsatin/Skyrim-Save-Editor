from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Mapping

from app.core.skyrim_ess import EssDocument, EssParseError, iter_change_forms, read_ess


DRAGONS_ABSORBED_FORM_ID = "0001C0F2"
DRAGONS_ABSORBED_NAME = "DragonsAbsorbed"
# The spendable in-game Dragon Souls pool is not the DragonsAbsorbed
# global variable. Controlled saves with 1 / 100 / 100,000 souls map it
# to a float32 inside ChangeForm RefID 400014 at this relative offset.
DRAGON_SOULS_PLAYER_REFID_HEX = "400014"
DRAGON_SOULS_PLAYER_RELATIVE_OFFSET = 0x49A5
DRAGON_SOULS_NAME = "Dragon Souls"


@dataclass(slots=True)
class DragonSoulsValue:
    name: str
    value: float
    change_form_refid_hex: str
    change_form_form_id_guess: str
    change_form_index: int
    change_form_type: int
    change_form_flags: int
    change_form_payload_offset: int
    value_payload_offset: int
    value_virtual_offset: int | None
    relative_offset: int


@dataclass(slots=True)
class GlobalVariableValue:
    name: str
    form_id: str
    encoded_refid_hex: str
    value: float
    table: int
    entry_index: int
    global_entry_type: int
    global_data_payload_offset: int
    refid_payload_offset: int
    value_payload_offset: int
    refid_virtual_offset: int | None
    value_virtual_offset: int | None
    global_count: int | None


def read_skyrim_dragon_souls(path: str | Path) -> DragonSoulsValue | None:
    """Read the spendable Dragon Souls actor-value pool from the player data.

    UESP's DragonsAbsorbed global (0001C0F2 / 41 C0 F2) tracks a separate
    global/stat style value and stayed 0 in controlled saves. The value that
    actually followed 1 -> 100 -> 100,000 lives in ChangeForm 400014 as f32.
    """
    doc = read_ess(path)
    if not doc.payload or not doc.file_location_table:
        return None
    target = DRAGON_SOULS_PLAYER_REFID_HEX.upper()
    for entry in iter_change_forms(doc.payload, doc.file_location_table):
        if entry.refid_hex.upper() != target:
            continue
        data_start = int(entry.data_offset) - int(doc.payload.virtual_offset)
        value_payload_offset = data_start + DRAGON_SOULS_PLAYER_RELATIVE_OFFSET
        if value_payload_offset < data_start or value_payload_offset + 4 > int(entry.data_end_offset) - int(doc.payload.virtual_offset):
            return None
        value = struct.unpack_from("<f", doc.payload.data, value_payload_offset)[0]
        return DragonSoulsValue(
            name=DRAGON_SOULS_NAME,
            value=float(value),
            change_form_refid_hex=entry.refid_hex,
            change_form_form_id_guess=entry.form_id_guess,
            change_form_index=int(entry.index),
            change_form_type=int(entry.form_type),
            change_form_flags=int(entry.change_flags),
            change_form_payload_offset=data_start,
            value_payload_offset=value_payload_offset,
            value_virtual_offset=int(doc.payload.virtual_offset) + value_payload_offset,
            relative_offset=DRAGON_SOULS_PLAYER_RELATIVE_OFFSET,
        )
    return None


def patch_skyrim_dragon_souls(source: str | Path, target: str | Path, value: int | float) -> DragonSoulsValue:
    """Patch the spendable Dragon Souls pool and return the original mapping."""
    source = Path(source)
    target = Path(target)
    raw = bytearray(source.read_bytes())
    doc = read_ess(source)
    if not doc.payload:
        raise EssParseError("No decoded save payload was available.")
    hit = read_skyrim_dragon_souls(source)
    if not hit:
        raise ValueError("Dragon Souls actor-value field was not found in ChangeForm 400014.")
    payload = bytearray(doc.payload.data)
    if hit.value_payload_offset < 0 or hit.value_payload_offset + 4 > len(payload):
        raise ValueError("Dragon Souls value offset is outside the decoded payload.")
    payload[hit.value_payload_offset:hit.value_payload_offset + 4] = struct.pack("<f", float(value))
    out = _rebuild_output(raw, doc, payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    return hit


def normalize_form_id(form_id: str | int) -> str:
    if isinstance(form_id, int):
        value = form_id
    else:
        text = str(form_id).strip().replace("0x", "").replace("0X", "")
        value = int(text, 16)
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("FormID out of range")
    return f"{value:08X}"


def encode_save_refid(form_id: str | int) -> bytes:
    """Encode a base-game FormID into Skyrim save RefID bytes.

    UESP's example: DragonsAbsorbed 0x0001C0F2 -> 41 C0 F2.
    The same compact format is used elsewhere in this editor, e.g. 0000000F
    -> 40 00 0F and 000F8318 -> 4F 83 18.
    """
    fid = int(normalize_form_id(form_id), 16)
    high = (fid >> 16) & 0x3F
    return bytes((0x40 | high, (fid >> 8) & 0xFF, fid & 0xFF))


def _global_variable_blocks(doc: EssDocument):
    if not doc.payload:
        return
    for entry in doc.global_data_entries:
        if int(entry.type) != 3:
            continue
        data_payload_offset = int(entry.data_offset) - int(doc.payload.virtual_offset)
        if data_payload_offset < 0 or data_payload_offset + int(entry.length) > len(doc.payload.data):
            continue
        yield entry, data_payload_offset, doc.payload.data[data_payload_offset:data_payload_offset + int(entry.length)]


def read_skyrim_global_variable(path: str | Path, form_id: str | int, *, name: str | None = None) -> GlobalVariableValue | None:
    doc = read_ess(path)
    if not doc.payload:
        return None
    target_form_id = normalize_form_id(form_id)
    target_refid = encode_save_refid(target_form_id)
    for entry, data_payload_offset, data in _global_variable_blocks(doc) or []:
        count: int | None = None
        start = 0
        if len(data) >= 2:
            possible_count = struct.unpack_from("<H", data, 0)[0]
            if 2 + possible_count * 7 <= len(data):
                count = possible_count
                start = 2
        # Global-variable records are 3-byte RefID + 4-byte float. Use the count
        # when it is sane, otherwise fall back to a bounded 7-byte walk.
        max_end = start + count * 7 if count is not None else len(data) - ((len(data) - start) % 7)
        for rel in range(start, max_end, 7):
            if rel + 7 > len(data):
                break
            if data[rel:rel + 3] != target_refid:
                continue
            value = struct.unpack_from("<f", data, rel + 3)[0]
            ref_payload_offset = data_payload_offset + rel
            value_payload_offset = ref_payload_offset + 3
            virt_base = int(doc.payload.virtual_offset)
            return GlobalVariableValue(
                name=name or target_form_id,
                form_id=target_form_id,
                encoded_refid_hex=target_refid.hex(" ").upper(),
                value=float(value),
                table=int(entry.table),
                entry_index=int(entry.index),
                global_entry_type=int(entry.type),
                global_data_payload_offset=int(data_payload_offset),
                refid_payload_offset=int(ref_payload_offset),
                value_payload_offset=int(value_payload_offset),
                refid_virtual_offset=virt_base + int(ref_payload_offset),
                value_virtual_offset=virt_base + int(value_payload_offset),
                global_count=count,
            )
        # Fallback raw search inside this type-3 block in case a variant has a
        # small header we do not fully understand yet.
        hit = data.find(target_refid)
        while hit >= 0:
            if hit + 7 <= len(data):
                value = struct.unpack_from("<f", data, hit + 3)[0]
                ref_payload_offset = data_payload_offset + hit
                value_payload_offset = ref_payload_offset + 3
                virt_base = int(doc.payload.virtual_offset)
                return GlobalVariableValue(
                    name=name or target_form_id,
                    form_id=target_form_id,
                    encoded_refid_hex=target_refid.hex(" ").upper(),
                    value=float(value),
                    table=int(entry.table),
                    entry_index=int(entry.index),
                    global_entry_type=int(entry.type),
                    global_data_payload_offset=int(data_payload_offset),
                    refid_payload_offset=int(ref_payload_offset),
                    value_payload_offset=int(value_payload_offset),
                    refid_virtual_offset=virt_base + int(ref_payload_offset),
                    value_virtual_offset=virt_base + int(value_payload_offset),
                    global_count=count,
                )
            hit = data.find(target_refid, hit + 1)
    return None


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


def patch_skyrim_global_variables(source: str | Path, target: str | Path, values: Mapping[str, int | float]) -> list[GlobalVariableValue]:
    """Patch mapped global variables by FormID and return the original hits."""
    source = Path(source)
    target = Path(target)
    if not values:
        raise ValueError("No global variable edits were supplied.")
    raw = bytearray(source.read_bytes())
    doc = read_ess(source)
    if not doc.payload:
        raise EssParseError("No decoded save payload was available.")
    payload = bytearray(doc.payload.data)
    hits: list[GlobalVariableValue] = []
    for form_id, value in values.items():
        hit = read_skyrim_global_variable(source, form_id, name="DragonsAbsorbed" if normalize_form_id(form_id) == DRAGONS_ABSORBED_FORM_ID else None)
        if not hit:
            raise ValueError(f"Global variable {normalize_form_id(form_id)} was not found in global data type 3.")
        if hit.value_payload_offset < 0 or hit.value_payload_offset + 4 > len(payload):
            raise ValueError(f"Global variable {hit.form_id} value offset is outside the decoded payload.")
        payload[hit.value_payload_offset:hit.value_payload_offset + 4] = struct.pack("<f", float(value))
        hits.append(hit)
    out = _rebuild_output(raw, doc, payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    return hits
