"""Guarded single-byte perk-point editing for the observed SE v78 layout.

The field was identified by the user's 0-point / 80-point saves. The surrounding
layout is an observed profile, not a general ACHR parser. Unknown layouts fail
closed. Copy-only writes remain appropriate until in-game reload is confirmed.
"""
from dataclasses import dataclass
import math
from pathlib import Path
import struct

from app.core.inventory_lab import decode_vsval_at, encode_vsval
from app.core.player_payload import load_player_data, rebuild_save_with_player_data
from app.core.skyrim_ess import EssParseError


@dataclass(frozen=True)
class PerkPointsField:
    offset: int
    value: int
    following_count: int


def locate_perk_points(data: bytes) -> PerkPointsField:
    # Observed fixed suffix after the counted 11-byte entries. Its fifth byte
    # differs between early saves and later saves; only the observed 0/1 fit.
    suffix = bytearray(28)
    suffix[21] = 1
    if len(data) < 42 or data[-24] not in (0, 1):
        raise EssParseError("Unsupported player suffix for perk points.")
    suffix[4] = data[-24]
    if data[-28:] != bytes(suffix):
        raise EssParseError("Unsupported player suffix for perk points.")
    candidates = []
    anchor = bytes.fromhex("010000000000")
    start = 0
    while True:
        pos = data.find(anchor, start)
        if pos < 0:
            break
        start = pos + 1
        offset = pos + 12  # anchor + two compact RefIDs
        if offset + 2 > len(data) - 28:
            continue
        if any(data[ref] >> 6 > 1 for ref in (pos + 6, pos + 9)):
            continue
        try:
            count, width = decode_vsval_at(data, offset + 1)
        except ValueError:
            continue
        entries = offset + 1 + width
        if count > 4096 or entries + count * 11 != len(data) - 28:
            continue
        if data[offset + 1:entries] != encode_vsval(count):
            continue
        valid = True
        for entry in range(entries, len(data) - 28, 11):
            ref = data[entry:entry + 3]
            value = struct.unpack_from("<f", data, entry + 7)[0]
            if (ref == b"\0\0\0" or ref[0] >> 6 > 1
                    or data[entry + 3:entry + 7] != bytes.fromhex("112e1900")
                    or not math.isfinite(value) or not 0 <= value <= 1e8):
                valid = False
                break
        if valid:
            candidates.append(PerkPointsField(offset, data[offset], count))
    if len(candidates) != 1:
        raise EssParseError(f"Expected one supported perk-point field; found {len(candidates)}.")
    return candidates[0]


def read_perk_points(source: str | Path) -> PerkPointsField:
    ctx = load_player_data(source)
    if ctx.doc.header.version != 12 or ctx.change_form.version != 78:
        raise EssParseError("Perk-point editing currently supports only the observed SE v78 player layout.")
    return locate_perk_points(ctx.player_data)


def patch_perk_points_copy(source: str | Path, target: str | Path, value: int) -> PerkPointsField:
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("Perk points must be an integer from 0 to 255.")
    source, target = Path(source), Path(target)
    if target.resolve() == source.resolve() or target.exists():
        raise ValueError("Choose a new copy filename; existing saves cannot be overwritten here.")
    field = read_perk_points(source)
    ctx = load_player_data(source)
    if locate_perk_points(ctx.player_data) != field:
        raise EssParseError("Source changed while reading perk points; reload it.")
    data = bytearray(ctx.player_data)
    data[field.offset] = value
    rebuild_save_with_player_data(source, target, bytes(data))
    verified = load_player_data(target)
    if verified.player_data != bytes(data) or read_perk_points(target).value != value:
        raise EssParseError("Edited copy failed verification; do not load it in game.")
    return field
