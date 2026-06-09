from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Iterable

from app.core.global_variables import encode_save_refid
from app.core.live_player import read_live_player_fields, _rebuild_save_with_live_record  # type: ignore
from app.core.player_payload import load_player_data, rebuild_save_with_player_data
from app.core.skyrim_ess import EssDocument, EssParseError, read_ess


@dataclass(frozen=True, slots=True)
class SkyrimRaceOption:
    display: str
    editor_id: str
    form_id: str

    @property
    def encoded(self) -> bytes:
        return encode_save_refid(self.form_id)

    @property
    def encoded_hex(self) -> str:
        return self.encoded.hex(" ").upper()


# Vanilla playable race editor IDs use the Creation Kit convention: <RaceName>Race.
# FormIDs are base-game FormIDs, encoded in saves as 3-byte RefIDs such as
# 00013746 NordRace -> 41 37 46.
SKYRIM_RACES: tuple[SkyrimRaceOption, ...] = (
    SkyrimRaceOption("Argonian", "ArgonianRace", "00013740"),
    SkyrimRaceOption("Breton", "BretonRace", "00013741"),
    SkyrimRaceOption("Dark Elf / Dunmer", "DarkElfRace", "00013742"),
    SkyrimRaceOption("High Elf / Altmer", "HighElfRace", "00013743"),
    SkyrimRaceOption("Imperial", "ImperialRace", "00013744"),
    SkyrimRaceOption("Khajiit", "KhajiitRace", "00013745"),
    SkyrimRaceOption("Nord", "NordRace", "00013746"),
    SkyrimRaceOption("Orc / Orsimer", "OrcRace", "00013747"),
    SkyrimRaceOption("Redguard", "RedguardRace", "00013748"),
    SkyrimRaceOption("Wood Elf / Bosmer", "WoodElfRace", "00013749"),
)

RACE_BY_EDITOR_ID: dict[str, SkyrimRaceOption] = {r.editor_id.casefold(): r for r in SKYRIM_RACES}
RACE_BY_FORM_ID: dict[str, SkyrimRaceOption] = {r.form_id.upper(): r for r in SKYRIM_RACES}
RACE_BY_ENCODED: dict[bytes, SkyrimRaceOption] = {r.encoded: r for r in SKYRIM_RACES}


@dataclass(slots=True)
class RacePairHit:
    record_name: str
    refid_hex: str
    offsets: tuple[int, ...]
    current_race: SkyrimRaceOption
    original_race: SkyrimRaceOption | None
    compressed: bool
    record_virtual_base: int | None

    @property
    def offset_text(self) -> str:
        return ", ".join(f"0x{o:X}" for o in self.offsets)


@dataclass(slots=True)
class RaceMapping:
    source: Path
    header_race_text: str
    header_race_option: SkyrimRaceOption | None
    active_race: SkyrimRaceOption | None
    player_hit: RacePairHit | None
    live_hit: RacePairHit | None

    @property
    def can_patch_live_race(self) -> bool:
        return self.player_hit is not None or self.live_hit is not None

    def summary(self) -> str:
        lines = [f"Header Race: {self.header_race_text or '(blank)'}"]
        if self.active_race:
            lines.append(f"Detected Race: {self.active_race.display} ({self.active_race.editor_id}, {self.active_race.form_id}, {self.active_race.encoded_hex})")
        if self.player_hit:
            lines.append(
                f"Player ChangeForm {self.player_hit.refid_hex}: {self.player_hit.current_race.editor_id} at {self.player_hit.offset_text}"
            )
        else:
            lines.append("Player ChangeForm 400014: race RefID pair not found")
        if self.live_hit:
            lines.append(
                f"Live ChangeForm {self.live_hit.refid_hex}: {self.live_hit.current_race.editor_id} at {self.live_hit.offset_text}"
            )
        return "\n".join(lines)


def race_from_editor_id(editor_id: str) -> SkyrimRaceOption:
    key = str(editor_id).strip().casefold()
    if key in RACE_BY_EDITOR_ID:
        return RACE_BY_EDITOR_ID[key]
    # Also accept display names for UI safety.
    display_key = key.replace(" ", "")
    for race in SKYRIM_RACES:
        if race.display.casefold().replace(" ", "") == display_key:
            return race
    raise ValueError(f"Unsupported Skyrim race: {editor_id!r}")


def _race_from_header(text: str | None) -> SkyrimRaceOption | None:
    if not text:
        return None
    return RACE_BY_EDITOR_ID.get(str(text).strip().casefold())


def _find_known_race_offsets(data: bytes) -> list[tuple[int, SkyrimRaceOption]]:
    hits: list[tuple[int, SkyrimRaceOption]] = []
    for encoded, race in RACE_BY_ENCODED.items():
        start = 0
        while True:
            off = data.find(encoded, start)
            if off < 0:
                break
            hits.append((off, race))
            start = off + 1
    hits.sort(key=lambda item: item[0])
    return hits


def _find_race_pair(data: bytes, *, record_name: str, refid_hex: str, compressed: bool, virtual_base: int | None, preferred: SkyrimRaceOption | None = None) -> RacePairHit | None:
    hits = _find_known_race_offsets(data)
    if not hits:
        return None
    by_offset = {off: race for off, race in hits}

    def cluster_for(pair_start: int) -> tuple[int, ...]:
        start = pair_start
        while (start - 3) in by_offset:
            start -= 3
        end = pair_start + 3
        while (end + 3) in by_offset:
            end += 3
        return tuple(range(start, end + 1, 3))

    pairs: list[RacePairHit] = []
    for off, race in hits:
        second = by_offset.get(off + 3)
        if second:
            offsets = cluster_for(off)
            pairs.append(RacePairHit(record_name, refid_hex, offsets, race, second, compressed, virtual_base))
    if pairs:
        if preferred:
            for pair in pairs:
                if pair.current_race.editor_id == preferred.editor_id:
                    return pair
        return pairs[0]
    # Fallback for early/short records with only one race RefID.
    if preferred:
        for off, race in hits:
            if race.editor_id == preferred.editor_id:
                return RacePairHit(record_name, refid_hex, (off,), race, None, compressed, virtual_base)
    off, race = hits[0]
    return RacePairHit(record_name, refid_hex, (off,), race, None, compressed, virtual_base)


def read_skyrim_race_mapping(source: str | Path) -> RaceMapping:
    source = Path(source)
    doc = read_ess(source, change_form_preview_limit=0)
    header_option = _race_from_header(doc.header.player_race)
    player_hit: RacePairHit | None = None
    live_hit: RacePairHit | None = None

    try:
        player_ctx = load_player_data(source)
        player_hit = _find_race_pair(
            player_ctx.player_data,
            record_name="Player Actor",
            refid_hex=player_ctx.change_form.refid_hex,
            compressed=player_ctx.compressed,
            virtual_base=player_ctx.player_data_virtual_offset,
            preferred=header_option,
        )
    except Exception:
        player_hit = None

    try:
        live_ctx = read_live_player_fields(source)
        live_hit = _find_race_pair(
            live_ctx.record_data,
            record_name="Live Player",
            refid_hex=live_ctx.change_form.refid_hex,
            compressed=live_ctx.compressed,
            virtual_base=live_ctx.record_virtual_offset,
            preferred=header_option,
        )
    except Exception:
        live_hit = None

    active = player_hit.current_race if player_hit else (live_hit.current_race if live_hit else header_option)
    return RaceMapping(
        source=source,
        header_race_text=doc.header.player_race,
        header_race_option=header_option,
        active_race=active,
        player_hit=player_hit,
        live_hit=live_hit,
    )


def patch_header_race_text(source: str | Path, target: str | Path, race: SkyrimRaceOption) -> EssDocument:
    source = Path(source)
    target = Path(target)
    doc = read_ess(source)
    raw = bytearray(source.read_bytes())
    h = doc.header
    encoded = race.editor_id.encode("utf-8")
    if len(encoded) > h.player_race_capacity:
        raise ValueError(
            f"Race text {race.editor_id!r} is {len(encoded)} bytes but this save header has only {h.player_race_capacity} bytes."
        )
    struct.pack_into("<H", raw, h.player_race_offset, h.player_race_capacity)
    raw[h.player_race_offset + 2:h.player_race_offset + 2 + h.player_race_capacity] = encoded.ljust(h.player_race_capacity, b"\x00")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return read_ess(target)


def _patch_offsets(data: bytearray, offsets: Iterable[int], race: SkyrimRaceOption) -> None:
    encoded = race.encoded
    for off in offsets:
        if off < 0 or off + 3 > len(data):
            raise EssParseError(f"Race offset 0x{off:X} is outside the record.")
        data[off:off + 3] = encoded


def patch_skyrim_player_race(source: str | Path, target: str | Path, race_id: str, *, patch_header: bool = True) -> RaceMapping:
    """Patch the mapped player race references.

    The tested saves store the current/original race as a consecutive 3-byte
    RefID pair in Player ChangeForm 400014, and some saves also mirror it in
    Live Player ChangeForm 400007.  This writes both entries when found, then
    optionally syncs the header race text.
    """
    source = Path(source)
    target = Path(target)
    race = race_from_editor_id(race_id)

    # Work on target in-place/copy style to match other patchers.
    if source.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    work = target

    mapping = read_skyrim_race_mapping(work)
    wrote_any_record = False

    if mapping.player_hit:
        ctx = load_player_data(work)
        data = bytearray(ctx.player_data)
        _patch_offsets(data, mapping.player_hit.offsets, race)
        rebuild_save_with_player_data(work, work, bytes(data))
        wrote_any_record = True

    # Re-read after the player ChangeForm rebuild, then patch the optional 400007 mirror.
    try:
        live_ctx = read_live_player_fields(work)
        header_option = _race_from_header(read_ess(work, change_form_preview_limit=0).header.player_race)
        live_hit = _find_race_pair(
            live_ctx.record_data,
            record_name="Live Player",
            refid_hex=live_ctx.change_form.refid_hex,
            compressed=live_ctx.compressed,
            virtual_base=live_ctx.record_virtual_offset,
            preferred=header_option,
        )
        if live_hit:
            data = bytearray(live_ctx.record_data)
            _patch_offsets(data, live_hit.offsets, race)
            _rebuild_save_with_live_record(live_ctx, work, bytes(data))
            wrote_any_record = True
    except Exception:
        # 400007 race refs are not present in some early saves; 400014 is the main target.
        pass

    if patch_header:
        try:
            patch_header_race_text(work, work, race)
        except ValueError:
            # Header race text is a fixed string slot.  Example: a NordRace save
            # may have only an 8-byte header slot, so BretonRace/ArgonianRace
            # cannot fit without rebuilding the header.  Keep the live race edit.
            pass

    if not wrote_any_record:
        raise EssParseError("No live player race RefID pair was found; only the header race text could be changed, so the race edit was refused.")

    return read_skyrim_race_mapping(work)
