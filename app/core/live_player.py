from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

from app.core.skyrim_ess import ChangeFormEntry, EssDocument, EssParseError, iter_change_forms, read_ess
from app.core.player_payload import rebuild_save_with_payload_variable

LIVE_PLAYER_REFID_HEX = "400007"


@dataclass(slots=True)
class LivePlayerFields:
    source: Path
    doc: EssDocument
    change_form: ChangeFormEntry
    raw_start_rel: int
    raw_end_rel: int
    raw_data: bytes
    record_data: bytes
    compressed: bool
    compression_name: str
    name: str | None
    name_length_offset: int | None
    name_data_offset: int | None
    name_length: int | None
    level: int | None
    level_offset: int | None

    @property
    def record_virtual_offset(self) -> int:
        return self.doc.payload.virtual_offset + self.raw_start_rel  # type: ignore[union-attr]

    def local_to_virtual(self, local_offset: int) -> int:
        return self.record_virtual_offset + int(local_offset)


def read_live_player_fields(source: str | Path) -> LivePlayerFields:
    source = Path(source)
    doc = read_ess(source, change_form_preview_limit=0)
    if not doc.payload or not doc.file_location_table:
        raise EssParseError("Save payload/change forms were not decoded.")

    live_cf: ChangeFormEntry | None = None
    for cf in iter_change_forms(doc.payload, doc.file_location_table):
        if cf.refid_hex.casefold() == LIVE_PLAYER_REFID_HEX.casefold():
            live_cf = cf
            break
    if not live_cf:
        raise EssParseError("Live player ChangeForm 400007 was not found.")

    raw_start = live_cf.data_offset - doc.payload.virtual_offset
    raw_end = live_cf.data_end_offset - doc.payload.virtual_offset
    if raw_start < 0 or raw_end > len(doc.payload.data) or raw_start > raw_end:
        raise EssParseError("Live player ChangeForm data range is outside the decoded payload.")

    raw = doc.payload.data[raw_start:raw_end]
    decoded, compressed, name = _decode_change_form_data(raw, live_cf)
    name_info = _find_live_name(decoded, doc.header.player_name)
    level_info = _find_live_level(decoded)

    return LivePlayerFields(
        source=source,
        doc=doc,
        change_form=live_cf,
        raw_start_rel=raw_start,
        raw_end_rel=raw_end,
        raw_data=raw,
        record_data=decoded,
        compressed=compressed,
        compression_name=name,
        name=name_info[2] if name_info else None,
        name_length_offset=name_info[0] if name_info else None,
        name_data_offset=(name_info[0] + 2) if name_info else None,
        name_length=name_info[1] if name_info else None,
        level=level_info[1] if level_info else None,
        level_offset=level_info[0] if level_info else None,
    )


def patch_live_player_values(
    source: str | Path,
    target: str | Path,
    *,
    player_name: str | None = None,
    player_level: int | None = None,
) -> EssDocument:
    ctx = read_live_player_fields(source)
    data = bytearray(ctx.record_data)

    if player_name is not None:
        if ctx.name_length_offset is None or ctx.name_data_offset is None or ctx.name_length is None:
            raise EssParseError("Live player name field was not located in ChangeForm 400007.")
        encoded = player_name.encode("utf-8")
        if not encoded:
            raise ValueError("Player name cannot be empty.")
        if len(encoded) > 255:
            raise ValueError("Player name is too long for the live player name slot.")
        old_total = 2 + int(ctx.name_length)
        new_total = 2 + len(encoded)
        replacement = struct.pack("<H", len(encoded)) + encoded
        start = int(ctx.name_length_offset)
        data[start:start + old_total] = replacement

    if player_level is not None:
        if not 1 <= int(player_level) <= 65535:
            raise ValueError("Player level must be between 1 and 65535.")
        if ctx.level_offset is not None:
            struct.pack_into("<I", data, int(ctx.level_offset), int(player_level))
        # Some early-game saves do not store the tested live-level field inside
        # ChangeForm 400007 yet.  Do not fail the whole Player save path in that
        # case: header level can still be synced, while Name/Race/XP/Common edits
        # remain writable.

    return _rebuild_save_with_live_record(ctx, target, bytes(data))


def _decode_change_form_data(raw: bytes, cf: ChangeFormEntry) -> tuple[bytes, bool, str]:
    looks_zlib = len(raw) >= 2 and raw[0] == 0x78
    should_try = bool(cf.length2 and cf.length2 != len(raw)) or looks_zlib
    if should_try:
        try:
            out = zlib.decompress(raw)
            if cf.length2 and len(out) != cf.length2:
                return raw, False, "none"
            return out, True, "zlib"
        except Exception:
            pass
    return raw, False, "none"


def _find_live_name(data: bytes, header_name: str | None = None) -> tuple[int, int, str] | None:
    candidates: list[tuple[int, int, str]] = []
    for off in range(0, max(0, len(data) - 2)):
        length = struct.unpack_from("<H", data, off)[0]
        if not (1 <= length <= 96):
            continue
        end = off + 2 + length
        if end > len(data):
            continue
        raw = data[off + 2:end]
        # Player names in tested Skyrim saves are plain UTF-8/ASCII length-prefixed strings.
        if any(b == 0 for b in raw):
            continue
        if not all(32 <= b < 127 for b in raw):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not any(ch.isalpha() for ch in text):
            continue
        candidates.append((off, length, text))
    if not candidates:
        return None
    if header_name:
        for cand in candidates:
            if cand[2] == header_name:
                return cand
    # In all tested saves the real player name is the only printable length-prefixed
    # string in ChangeForm 400007. If the header was edited only, prefer the longest
    # printable candidate so the UI shows the real in-game name instead of the header.
    return sorted(candidates, key=lambda c: (len(c[2]), c[0]), reverse=True)[0]


def _find_live_level(data: bytes) -> tuple[int, int] | None:
    # Later PS4/SE saves and tested PC saves store the live player level at offset 8
    # in ChangeForm 400007, directly after 30 00 00 00 32 00 32 00.
    if len(data) >= 12 and data[:8] == bytes.fromhex("30 00 00 00 32 00 32 00"):
        value = struct.unpack_from("<I", data, 8)[0]
        if 1 <= value <= 65535:
            return 8, value
    return None


def _rebuild_save_with_live_record(ctx: LivePlayerFields, target: str | Path, new_record_data: bytes) -> EssDocument:
    doc = ctx.doc
    if not doc.payload:
        raise EssParseError("Save payload was not decoded; cannot rebuild save.")

    if ctx.compressed:
        new_raw = zlib.compress(bytes(new_record_data))
        new_length1 = len(new_raw)
        new_length2 = len(new_record_data)
    else:
        new_raw = bytes(new_record_data)
        new_length1 = len(new_raw)
        new_length2 = 0 if ctx.change_form.length2 == 0 else len(new_record_data)

    body = bytearray(doc.payload.data)
    old_len = ctx.raw_end_rel - ctx.raw_start_rel
    body[ctx.raw_start_rel:ctx.raw_end_rel] = new_raw
    delta = len(new_raw) - old_len

    _write_change_form_lengths(body, ctx, new_length1, new_length2)
    if delta:
        _shift_file_location_table_offsets(body, ctx, delta)

    return rebuild_save_with_payload_variable(ctx.source, target, bytes(body))


def _write_change_form_lengths(body: bytearray, ctx: LivePlayerFields, length1: int, length2: int) -> None:
    cf = ctx.change_form
    cf_start = cf.offset - ctx.doc.payload.virtual_offset  # type: ignore[union-attr]
    length_pos = cf_start + 9
    if cf.lengths_size == 0:
        if length1 > 0xFF or length2 > 0xFF:
            raise EssParseError("Edited live player ChangeForm no longer fits 1-byte length fields.")
        body[length_pos] = length1
        body[length_pos + 1] = length2
    elif cf.lengths_size == 1:
        if length1 > 0xFFFF or length2 > 0xFFFF:
            raise EssParseError("Edited live player ChangeForm no longer fits 2-byte length fields.")
        struct.pack_into("<H", body, length_pos, length1)
        struct.pack_into("<H", body, length_pos + 2, length2)
    elif cf.lengths_size == 2:
        struct.pack_into("<I", body, length_pos, length1)
        struct.pack_into("<I", body, length_pos + 4, length2)
    else:
        raise EssParseError("Unsupported ChangeForm length-size value 3.")


def _shift_file_location_table_offsets(body: bytearray, ctx: LivePlayerFields, delta: int) -> None:
    doc = ctx.doc
    flt = doc.file_location_table
    if not flt or not doc.payload:
        return
    table_rel = flt.offset - doc.payload.virtual_offset
    if table_rel < 0 or table_rel + 24 > len(body):
        return
    cutoff = ctx.change_form.data_end_offset
    for index in range(6):
        pos = table_rel + index * 4
        value = struct.unpack_from("<I", body, pos)[0]
        if value > cutoff:
            struct.pack_into("<I", body, pos, value + delta)
