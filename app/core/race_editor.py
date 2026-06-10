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
    # Vampire race variants are separate RACE records.  They matter for research
    # because player.setrace <race>racevampire can make the in-game race differ
    # from the save header race text.  FormIDs are vanilla Skyrim race records.
    SkyrimRaceOption("Nord Vampire", "NordRaceVampire", "00088794"),
    SkyrimRaceOption("Argonian Vampire", "ArgonianRaceVampire", "0008883A"),
    SkyrimRaceOption("Breton Vampire", "BretonRaceVampire", "0008883C"),
    SkyrimRaceOption("Dark Elf Vampire", "DarkElfRaceVampire", "0008883D"),
    SkyrimRaceOption("High Elf Vampire", "HighElfRaceVampire", "00088840"),
    SkyrimRaceOption("Imperial Vampire", "ImperialRaceVampire", "00088844"),
    SkyrimRaceOption("Khajiit Vampire", "KhajiitRaceVampire", "00088845"),
    SkyrimRaceOption("Redguard Vampire", "RedguardRaceVampire", "00088846"),
    SkyrimRaceOption("Wood Elf Vampire", "WoodElfRaceVampire", "00088884"),
    SkyrimRaceOption("Orc Vampire", "OrcRaceVampire", "000A82B9"),
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
            lines.append(f"Mapped Race Ref: {self.active_race.display} ({self.active_race.editor_id}, {self.active_race.form_id}, {self.active_race.encoded_hex})")
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
            cluster_races = [by_offset[o] for o in offsets if o in by_offset]
            display_current = race
            display_original = second
            # showracemenu can leave the previous race in the same cluster.
            # In known tests, a Nord conversion may look like:
            #   Player 400014: BretonRace / NordRace / NordRace
            #   Live   400007: NordRace / BretonRace
            # The old detector returned the first player race (Breton), which made
            # a real Nord save look stale/incorrect.  If the save header names a
            # playable race and that race appears anywhere in the mapped cluster,
            # prefer it as the active display race while preserving all offsets
            # for research output.
            if preferred and any(r.editor_id == preferred.editor_id for r in cluster_races):
                display_current = preferred
                for r in cluster_races:
                    if r.editor_id != preferred.editor_id:
                        display_original = r
                        break
            pairs.append(RacePairHit(record_name, refid_hex, offsets, display_current, display_original, compressed, virtual_base))
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
    """Patch the save-menu/header race text when it fits the existing slot.

    The ESS payload uses internal location tables, so resizing the header string
    would shift the compressed payload and invalidate those offsets.  Keep this
    fixed-width and let the caller still patch the actual player race records.
    """
    source = Path(source)
    target = Path(target)
    doc = read_ess(source)
    raw = bytearray(source.read_bytes())
    h = doc.header
    encoded = race.editor_id.encode("utf-8")
    if len(encoded) > h.player_race_capacity:
        raise ValueError(
            f"Race text {race.editor_id!r} is {len(encoded)} bytes but this save header has only {h.player_race_capacity} bytes. "
            "The actual player race records can still be synced, but this fixed header label cannot be expanded safely."
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


def _patch_all_known_race_refs(data: bytearray, race: SkyrimRaceOption) -> int:
    """Replace every vanilla playable/vampire race RefID in a player record.

    showracemenu saves can keep a mixed race cluster such as Breton/Nord/Nord.
    Patching only the first pair can leave stale body/appearance race refs behind
    and produces hybrid results (for example a Nord body with a Khajiit tail).
    This intentionally operates only on the player-owned records that callers
    pass in, not on the entire save file.
    """
    target = race.encoded
    offsets = sorted({off for off, _r in _find_known_race_offsets(bytes(data))})
    for off in offsets:
        if 0 <= off <= len(data) - 3:
            data[off:off + 3] = target
    return len(offsets)


def patch_skyrim_player_race(source: str | Path, target: str | Path, race_id: str, *, patch_header: bool = True, full_sync: bool = True) -> RaceMapping:
    """Patch the mapped player race references.

    The tested saves store race refs in Player ChangeForm 400014 and usually in
    Live Player ChangeForm 400007. showracemenu can leave stale old-race refs in
    those same records, so full_sync updates every known playable/vampire race
    RefID found inside those player records.  Header race text is also synced
    when its fixed slot can hold the new editor ID.
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
        if full_sync:
            changed_count = _patch_all_known_race_refs(data, race)
            wrote_any_record = changed_count > 0
        else:
            _patch_offsets(data, mapping.player_hit.offsets, race)
            wrote_any_record = True
        rebuild_save_with_player_data(work, work, bytes(data))

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
            if full_sync:
                changed_count = _patch_all_known_race_refs(data, race)
                wrote_any_record = wrote_any_record or changed_count > 0
            else:
                _patch_offsets(data, live_hit.offsets, race)
                wrote_any_record = True
            _rebuild_save_with_live_record(live_ctx, work, bytes(data))
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
