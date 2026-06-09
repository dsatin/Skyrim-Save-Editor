from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import zlib

from app.core.skyrim_ess import (
    EssDocument,
    EssParseError,
    ChangeFormEntry,
    iter_change_forms,
    read_ess,
)

PLAYER_REFID_HEX = "400014"


@dataclass(slots=True)
class PlayerDataContext:
    source: Path
    doc: EssDocument
    change_form: ChangeFormEntry
    raw_start_rel: int
    raw_end_rel: int
    raw_data: bytes
    player_data: bytes
    compressed: bool
    compression_name: str

    @property
    def player_data_virtual_offset(self) -> int:
        # For uncompressed player records this is the real payload virtual offset.
        # For compressed player records it is a stable pseudo-offset used by the UI
        # and patcher to refer to offsets inside the decompressed player data.
        return self.doc.payload.virtual_offset + self.raw_start_rel  # type: ignore[union-attr]

    def local_to_virtual(self, local_offset: int) -> int:
        return self.player_data_virtual_offset + int(local_offset)

    def virtual_to_local(self, virtual_offset: int) -> int:
        return int(virtual_offset) - self.player_data_virtual_offset


def load_player_data(source: str | Path) -> PlayerDataContext:
    source = Path(source)
    doc = read_ess(source, change_form_preview_limit=0)
    if not doc.payload or not doc.file_location_table:
        raise EssParseError("Save payload/change forms were not decoded.")

    player_cf: ChangeFormEntry | None = None
    for cf in iter_change_forms(doc.payload, doc.file_location_table):
        if cf.refid_hex.casefold() == PLAYER_REFID_HEX:
            player_cf = cf
            break
    if not player_cf:
        raise EssParseError("Player change form 400014 was not found.")

    raw_start = player_cf.data_offset - doc.payload.virtual_offset
    raw_end = player_cf.data_end_offset - doc.payload.virtual_offset
    if raw_start < 0 or raw_end > len(doc.payload.data) or raw_start > raw_end:
        raise EssParseError("Player change-form data range is outside the decoded payload.")
    raw = doc.payload.data[raw_start:raw_end]
    decoded, compressed, name = _decode_player_change_form_data(raw, player_cf)
    return PlayerDataContext(
        source=source,
        doc=doc,
        change_form=player_cf,
        raw_start_rel=raw_start,
        raw_end_rel=raw_end,
        raw_data=raw,
        player_data=decoded,
        compressed=compressed,
        compression_name=name,
    )


def _decode_player_change_form_data(raw: bytes, cf: ChangeFormEntry) -> tuple[bytes, bool, str]:
    # Classic Skyrim can keep individual ChangeForm payloads compressed even when
    # the whole save payload is otherwise uncompressed.  The player ChangeForm in
    # PAWEL.ess is one example: length1 is the zlib size, length2 is the expanded
    # player-data size, and the data starts with 78 9C.
    looks_zlib = len(raw) >= 2 and raw[0] == 0x78
    should_try = bool(cf.length2 and cf.length2 != len(raw)) or looks_zlib
    if should_try:
        try:
            out = zlib.decompress(raw)
            if cf.length2 and len(out) != cf.length2:
                # Keep parsing uncompressed if the length check fails; a false
                # positive zlib-looking sequence should not break normal saves.
                return raw, False, "none"
            return out, True, "zlib"
        except Exception:
            pass
    return raw, False, "none"


def rebuild_save_with_player_data(source: str | Path, target: str | Path, new_player_data: bytes) -> EssDocument:
    """Replace the player ChangeForm data and rebuild the save.

    Supports both normal uncompressed player ChangeForms and zlib-compressed
    player ChangeForms.  If recompression changes the ChangeForm size, downstream
    file-location-table offsets are adjusted before the save payload is rebuilt.
    """
    source = Path(source)
    target = Path(target)
    ctx = load_player_data(source)
    doc = ctx.doc
    if not doc.payload:
        raise EssParseError("Save payload was not decoded; cannot rebuild save.")

    if ctx.compressed:
        new_raw = zlib.compress(bytes(new_player_data))
        new_length1 = len(new_raw)
        new_length2 = len(new_player_data)
    else:
        new_raw = bytes(new_player_data)
        new_length1 = len(new_raw)
        # Skyrim stores length2 as zero for uncompressed records in some saves and
        # as the expanded size in others. Preserve the original convention.
        new_length2 = 0 if ctx.change_form.length2 == 0 else len(new_raw)

    body = bytearray(doc.payload.data)
    old_len = ctx.raw_end_rel - ctx.raw_start_rel
    body[ctx.raw_start_rel:ctx.raw_end_rel] = new_raw
    delta = len(new_raw) - old_len

    _write_change_form_lengths(body, ctx, new_length1, new_length2)
    if delta:
        _shift_file_location_table_offsets(body, ctx, delta)

    return rebuild_save_with_payload_variable(source, target, bytes(body))


def _write_change_form_lengths(body: bytearray, ctx: PlayerDataContext, length1: int, length2: int) -> None:
    cf = ctx.change_form
    cf_start = cf.offset - ctx.doc.payload.virtual_offset  # type: ignore[union-attr]
    length_pos = cf_start + 9
    if cf.lengths_size == 0:
        if length1 > 0xFF or length2 > 0xFF:
            raise EssParseError("Edited player ChangeForm no longer fits 1-byte length fields.")
        body[length_pos] = length1
        body[length_pos + 1] = length2
    elif cf.lengths_size == 1:
        if length1 > 0xFFFF or length2 > 0xFFFF:
            raise EssParseError("Edited player ChangeForm no longer fits 2-byte length fields.")
        struct.pack_into("<H", body, length_pos, length1)
        struct.pack_into("<H", body, length_pos + 2, length2)
    elif cf.lengths_size == 2:
        struct.pack_into("<I", body, length_pos, length1)
        struct.pack_into("<I", body, length_pos + 4, length2)
    else:
        raise EssParseError("Unsupported player ChangeForm length-size value 3.")


def _shift_file_location_table_offsets(body: bytearray, ctx: PlayerDataContext, delta: int) -> None:
    doc = ctx.doc
    flt = doc.file_location_table
    if not flt or not doc.payload:
        return
    table_rel = flt.offset - doc.payload.virtual_offset
    if table_rel < 0 or table_rel + 24 > len(body):
        return
    # First six u32 fields are absolute section offsets.  Any section that starts
    # after the edited player ChangeForm data must move by delta.
    cutoff = ctx.change_form.data_end_offset
    for index in range(6):
        pos = table_rel + index * 4
        value = struct.unpack_from("<I", body, pos)[0]
        if value > cutoff:
            struct.pack_into("<I", body, pos, value + delta)


def rebuild_save_with_payload_variable(source: str | Path, target: str | Path, new_payload: bytes) -> EssDocument:
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
