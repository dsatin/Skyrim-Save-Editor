from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import math

from app.core.quick_codes import generate_skyrim_quick_code_preset, get_skyrim_quick_code_preset
from app.core.skyrim_ess import EssParseError, read_ess, rebuild_save_with_payload
from app.core.player_payload import load_player_data, rebuild_save_with_player_data




SKYRIM_SKILL_NAMES: tuple[str, ...] = (
    "One-Handed",
    "Two-Handed",
    "Archery",
    "Block",
    "Smithing",
    "Heavy Armor",
    "Light Armor",
    "Pickpocket",
    "Lockpicking",
    "Sneak",
    "Alchemy",
    "Speech",
    "Alteration",
    "Conjuration",
    "Destruction",
    "Illusion",
    "Restoration",
    "Enchanting",
)

# Skyrim actor value IDs exposed by the safe Stats tab. Rate actor values were
# removed from the UI because they were commonly disabled/not resolved on user
# saves. Carry Weight is exposed as an intended total: base ActorValue 32 plus
# the Save Wizard modifier target when that modifier exists. Early saves without
# the modifier fall back to ActorValue 32.

# The normal in-game skill cap is 100. Direct skill writes are capped at
# 999,999 for this experimental test pass. The prior 999,999,999 test path
# was too unstable, but 1,000 was confirmed working by the user.
SKYRIM_SKILL_TEST_MAX = 999_999.0
SKYRIM_SKILL_VANILLA_SAFE_MAX = 300.0

SKYRIM_ACTOR_VALUE_FIELDS: tuple[tuple[int, str], ...] = (
    (24, "Health"),
    (25, "Magicka"),
    (26, "Stamina"),
    (320, "Carry Weight"),
)
SKYRIM_ACTOR_VALUE_NAMES: dict[int, str] = dict(SKYRIM_ACTOR_VALUE_FIELDS)


@dataclass(slots=True)
class PresetSearchHit:
    label: str
    offset: int
    pattern_hex: str
    occurrence: int


@dataclass(slots=True)
class PresetWrite:
    offset: int
    size: int
    before_hex: str
    after_hex: str
    note: str




@dataclass(slots=True)
class SkillValueSlot:
    index: int
    name: str
    offset: int
    value: float
    raw_hex: str


@dataclass(slots=True)
class ActorValueSlot:
    actor_id: int
    name: str
    id_offset: int
    value_offset: int
    value: float
    id_raw_hex: str
    value_raw_hex: str


@dataclass(slots=True)
class ActorValuePatchPlan:
    requested_values: dict[int, float]
    searches: list[PresetSearchHit]
    actor_values: list[ActorValueSlot]
    writes: list[PresetWrite]
    payload_size: int

    def to_text(self) -> str:
        lines = [
            "Preset: Player Actor Values",
            "",
            "Direct save patch preview:",
        ]
        if self.searches:
            lines.append("Search anchors found:")
            for hit in self.searches:
                lines.append(f"- {hit.label}: payload 0x{hit.offset:X}, occurrence {hit.occurrence}, pattern {hit.pattern_hex}")
        lines.append("")
        if self.writes:
            lines.append("Actor values that will be written:")
            for write in self.writes:
                lines.append(
                    f"- payload 0x{write.offset:X}, {write.size} byte(s): "
                    f"{write.before_hex} -> {write.after_hex}  {write.note}"
                )
        else:
            lines.append("No actor value changes are different from the loaded save.")
        lines.append("")
        lines.append("Detected actor value slots:")
        for slot in self.actor_values:
            lines.append(
                f"- ActorValue {slot.actor_id:02d} {slot.name}: {slot.value:g} "
                f"at payload 0x{slot.value_offset:X} ({slot.value_raw_hex}); "
                f"ID at 0x{slot.id_offset:X} ({slot.id_raw_hex})"
            )
        lines.append("")
        lines.append("Carry Weight is shown as the intended total. When a modifier slot exists, the editor writes total - base to the Save Wizard carry slot; otherwise it falls back to ActorValue 32.")
        lines.append("This uses the same validated actor-value block that made individual skills work. It does not call Save Wizard.")
        return "\n".join(lines)


@dataclass(slots=True)
class AddExpPatchPlan:
    requested_exp: float
    searches: list[PresetSearchHit]
    writes: list[PresetWrite]
    payload_size: int

    def to_text(self) -> str:
        lines = [
            "Preset: XP Pool",
            "",
            f"Requested XP pool value: {self.requested_exp:g}",
            "",
            "Direct save patch preview:",
        ]
        if self.searches:
            lines.append("Search anchors found:")
            for hit in self.searches:
                lines.append(f"- {hit.label}: payload 0x{hit.offset:X}, occurrence {hit.occurrence}, pattern {hit.pattern_hex}")
        lines.append("")
        if self.writes:
            lines.append("XP pool values that will be written:")
            for write in self.writes:
                lines.append(
                    f"- payload 0x{write.offset:X}, {write.size} byte(s): "
                    f"{write.before_hex} -> {write.after_hex}  {write.note}"
                )
        else:
            lines.append("No XP pool byte changes are needed; this save already has the requested XP pool value.")
        lines.append("")
        lines.append("This edits the XP pool / pending-EXP structure used by the +EXP preset and rebuilds the ESS payload. It does not call Save Wizard.")
        return "\n".join(lines)


@dataclass(slots=True)
class SkillPatchPlan:
    requested_values: dict[int, float]
    searches: list[PresetSearchHit]
    skills: list[SkillValueSlot]
    writes: list[PresetWrite]
    payload_size: int

    def to_text(self) -> str:
        lines = [
            "Preset: Individual Skills",
            "",
            "Direct save patch preview:",
        ]
        if self.searches:
            lines.append("Search anchors found:")
            for hit in self.searches:
                lines.append(f"- {hit.label}: payload 0x{hit.offset:X}, occurrence {hit.occurrence}, pattern {hit.pattern_hex}")
        lines.append("")
        if self.writes:
            lines.append("Skill values that will be written:")
            for write in self.writes:
                lines.append(
                    f"- payload 0x{write.offset:X}, {write.size} byte(s): "
                    f"{write.before_hex} -> {write.after_hex}  {write.note}"
                )
        else:
            lines.append("No skill changes are different from the loaded save.")
        lines.append("")
        lines.append("Detected skill slots:")
        for slot in self.skills:
            lines.append(f"- {slot.index + 1:02d}. {slot.name}: {slot.value:g} at payload 0x{slot.offset:X} ({slot.raw_hex})")
        lines.append("")
        lines.append("This patches the decompressed Skyrim ESS payload and rebuilds the save. It does not call Save Wizard.")
        return "\n".join(lines)


@dataclass(slots=True)
class PresetPatchPlan:
    preset_id: str
    preset_name: str
    value_label: str
    requested_value: float | int
    code_text: str
    searches: list[PresetSearchHit]
    writes: list[PresetWrite]
    payload_size: int

    def to_text(self) -> str:
        lines = [
            f"Preset: {self.preset_name}",
            f"{self.value_label}: {self.requested_value:g}" if isinstance(self.requested_value, float) else f"{self.value_label}: {self.requested_value}",
            "",
            "Direct save patch preview:",
        ]
        if self.searches:
            lines.append("Search anchors found:")
            for hit in self.searches:
                lines.append(f"- {hit.label}: payload 0x{hit.offset:X}, occurrence {hit.occurrence}, pattern {hit.pattern_hex}")
        if self.writes:
            lines.append("")
            lines.append("Values that will be written:")
            for write in self.writes:
                lines.append(
                    f"- payload 0x{write.offset:X}, {write.size} byte(s): "
                    f"{write.before_hex} -> {write.after_hex}  {write.note}"
                )
        else:
            lines.append("No byte changes are needed; this save already has the requested value at the resolved location(s).")
        lines.append("")
        lines.append("This patches the decompressed Skyrim ESS payload and rebuilds the save. It does not call Save Wizard.")
        return "\n".join(lines)


class PresetPatchError(ValueError):
    pass


EXPERIMENTAL_SW_PRESET_IDS = {
    "all_skills_level",
    "carry_weight",
    "health_magicka_stamina",
    "add_exp",
    "perk_points",
}


def _find_all_bytes(data: bytes | bytearray, needle: bytes) -> list[int]:
    if not needle:
        return []
    hay = bytes(data)
    hits: list[int] = []
    pos = 0
    while True:
        idx = hay.find(needle, pos)
        if idx < 0:
            return hits
        hits.append(idx)
        pos = idx + 1


def _skill_candidate_score(data: bytes | bytearray, anchor: int) -> tuple[int, list[float]] | None:
    values: list[float] = []
    try:
        for index in range(len(SKYRIM_SKILL_NAMES)):
            value = _float32_le_from_payload(data, anchor + 0x0C + index * 0x08)
            if not math.isfinite(value):
                return None
            values.append(value)
    except Exception:
        return None
    # The direct editor is only safe when the detected block already looks like
    # a real Skyrim skill array. This prevents a generic 05/04...06 byte pattern
    # elsewhere in the payload from being treated as skills.
    finite_test_range = sum(1 for value in values if 0.0 <= value <= SKYRIM_SKILL_TEST_MAX)
    normalish = sum(1 for value in values if 0.0 <= value <= SKYRIM_SKILL_VANILLA_SAFE_MAX)
    vanillaish = sum(1 for value in values if 1.0 <= value <= 100.0)
    roundish = sum(1 for value in values if abs(value - round(value)) < 0.001)

    # Prefer natural/vanilla-looking arrays, but keep accepting a previously
    # edited test save whose skills were raised past 300. Values above 999,999 are
    # intentionally not accepted as a safe editable skill block.
    if normalish < 14 or vanillaish < 8:
        if finite_test_range < len(SKYRIM_SKILL_NAMES) or roundish < 8:
            return None
    score = normalish * 100 + vanillaish * 10 + roundish + finite_test_range
    return score, values


def _hex_words(text: str) -> list[str]:
    words: list[str] = []
    for raw in (text or "").splitlines():
        parts = raw.strip().split()
        for part in parts:
            clean = part.strip().upper()
            if len(clean) == 8 and all(ch in "0123456789ABCDEF" for ch in clean):
                words.append(clean)
    if len(words) % 2:
        raise PresetPatchError("Generated preset code has an incomplete 8-hex word pair.")
    return words


def _find_nth(data: bytes | bytearray, needle: bytes, start: int, occurrence: int, *, forward: bool = True) -> int:
    if not needle:
        raise PresetPatchError("Search pattern is empty.")
    occurrence = max(1, int(occurrence))
    if forward:
        pos = max(0, min(len(data), start))
        hits: list[int] = []
        while True:
            idx = bytes(data).find(needle, pos)
            if idx < 0:
                break
            hits.append(idx)
            if len(hits) >= occurrence:
                return idx
            pos = idx + 1
    else:
        end = max(0, min(len(data), start if start else len(data)))
        hay = bytes(data)[:end]
        hits = []
        pos = 0
        while True:
            idx = hay.find(needle, pos)
            if idx < 0:
                break
            hits.append(idx)
            pos = idx + 1
        if len(hits) >= occurrence:
            return hits[-occurrence]
    raise PresetPatchError(
        f"Could not find occurrence {occurrence} of search pattern {needle.hex(' ').upper()} "
        f"from payload 0x{start:X}."
    )


def _width_from_standard(code_type: str) -> int:
    try:
        return {"0": 1, "1": 2, "2": 4}[code_type.upper()]
    except KeyError as exc:
        raise PresetPatchError(f"Unsupported standard write type {code_type!r}.") from exc


def _width_from_type4_mode(mode: str) -> int:
    # Save Wizard Type 4 mode digit carries width and pointer-relative state.
    # Skyrim presets use A, which is the 4-byte pointer-relative variant.
    table = {
        "0": 1, "1": 2, "2": 4,
        "8": 1, "9": 2, "A": 4,
    }
    try:
        return table[mode.upper()]
    except KeyError as exc:
        raise PresetPatchError(f"Unsupported Type 4 mode {mode!r}; only fixed-width writes are implemented.") from exc


def _is_pointer_relative(mode: str) -> bool:
    return mode.upper() in {"8", "9", "A", "B", "C", "D", "E", "F"}


def _write_bytes_for_numeric_word(word: str, width: int) -> bytes:
    raw = bytes.fromhex(word[-width * 2:])
    # The posted Skyrim Save Wizard presets use big-endian text values, while the
    # ESS payload stores these numeric values little-endian. Search data is not
    # swapped; only numeric writes are converted for direct save editing.
    return raw[::-1] if width > 1 else raw


def _record_write(data: bytearray, offset: int, patch: bytes, note: str, writes: list[PresetWrite]) -> None:
    if offset < 0 or offset + len(patch) > len(data):
        raise PresetPatchError(f"Write at payload 0x{offset:X} is outside the decompressed payload.")
    before = bytes(data[offset:offset + len(patch)])
    if before != patch:
        writes.append(PresetWrite(offset, len(patch), before.hex(" ").upper(), patch.hex(" ").upper(), note))
    data[offset:offset + len(patch)] = patch




def _float32_le_from_payload(data: bytes | bytearray, offset: int) -> float:
    if offset < 0 or offset + 4 > len(data):
        raise PresetPatchError(f"Float read at payload 0x{offset:X} is outside the decompressed payload.")
    return float(struct.unpack("<f", bytes(data[offset:offset + 4]))[0])


def _float32_le_bytes(value: float) -> bytes:
    return struct.pack("<f", float(value))


def _u32_le_from_payload(data: bytes | bytearray, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise PresetPatchError(f"Actor value ID read at payload 0x{offset:X} is outside the decompressed payload.")
    return int(struct.unpack("<I", bytes(data[offset:offset + 4]))[0])


def _resolve_carry_weight_marker(data: bytes | bytearray, anchor: int, occurrence: int) -> tuple[int, int, int]:
    """Resolve a carry-weight-looking ActorValue 32 marker after the skill anchor.

    The base carry weight is the first `20 00 00 00` marker after the validated
    actor/skill block.  The posted Save Wizard carry code uses `88020004`, so
    its target is the second occurrence after the same pointer.
    """
    marker = bytes.fromhex("20 00 00 00")
    hay = bytes(data)
    start = max(0, min(len(data), anchor))
    hits: list[int] = []
    pos = start
    while True:
        found = hay.find(marker, pos)
        if found < 0:
            break
        if found + 8 <= len(data):
            hits.append(found)
        pos = found + 1
    if len(hits) < occurrence:
        raise PresetPatchError(
            f"Could not resolve Carry Weight marker occurrence {occurrence}. "
            f"Found {len(hits)} occurrence(s) of 20 00 00 00 after the validated skill anchor. "
            "No bytes were changed."
        )
    id_offset = hits[occurrence - 1]
    return id_offset, id_offset + 4, len(hits)


def _resolve_carry_weight_sw_pointer(data: bytes | bytearray, anchor: int) -> tuple[int, int, int]:
    """Resolve the exact Save Wizard carry-weight pointer chain.

    Posted code:
        8001000C 05000000
        00000000 06000000
        88020004 20000000
        28000004 <float>

    After the skill anchor is found, `88020004` searches pointer-relative for
    the 2nd occurrence of the 4-byte marker `20 00 00 00` and writes the float
    at pointer+4. Save Wizard byte-searches raw bytes, so alignment is not
    required here.
    """
    return _resolve_carry_weight_marker(data, anchor, 2)


def _resolve_carry_weight_total_targets(data: bytes | bytearray, anchor: int) -> dict[str, tuple[int, int, float]]:
    """Resolve carry-weight storage used by the Stats tab.

    Skyrim commonly stores ActorValue 32 as the 300-ish base carry weight, while
    the posted Save Wizard code targets a nearby modifier/bonus slot.  In game,
    the displayed carry limit behaves like base + modifier.  Some early saves do
    not contain the modifier slot yet, so we fall back to the base slot instead
    of disabling carry weight entirely.
    """
    targets: dict[str, tuple[int, int, float]] = {}
    base_id, base_value, _base_hits = _resolve_carry_weight_marker(data, anchor, 1)
    targets["base"] = (base_id, base_value, _float32_le_from_payload(data, base_value))
    try:
        mod_id, mod_value, _mod_hits = _resolve_carry_weight_sw_pointer(data, anchor)
    except PresetPatchError:
        mod_id = mod_value = -1
    if mod_id >= 0 and mod_value >= 0:
        targets["modifier"] = (mod_id, mod_value, _float32_le_from_payload(data, mod_value))
    return targets


def _read_carry_weight_total(data: bytes | bytearray, anchor: int) -> tuple[float, int, int, str, str]:
    targets = _resolve_carry_weight_total_targets(data, anchor)
    base_id, base_value, base_float = targets["base"]
    modifier = targets.get("modifier")
    if modifier is None:
        return base_float, base_id, base_value, "base-only", f"base {base_float:g}; no modifier slot found"
    mod_id, mod_value, mod_float = modifier
    total = base_float + mod_float
    return total, mod_id, mod_value, "base+modifier", f"base {base_float:g} + modifier {mod_float:g}"


def _actor_value_offsets_from_block(data: bytes | bytearray, anchor: int, actor_id: int) -> tuple[int, int]:
    actor_id = int(actor_id)
    if actor_id < 0:
        raise PresetPatchError(f"Invalid ActorValue {actor_id}.")

    actor_bytes = struct.pack("<I", actor_id)

    def plausible_value_at(value_at: int) -> bool:
        if value_at + 4 > len(data):
            return False
        try:
            value = _float32_le_from_payload(data, value_at)
        except Exception:
            return False
        return math.isfinite(value) and -1_000_000_000.0 <= value <= 1_000_000_000.0

    # Carry Weight is split into two explicit targets. The base value is the
    # first ActorValue-32 marker after the validated actor/skill block; the
    # Save-Wizard target is the second marker from the posted pointer chain.
    if actor_id == 32:
        id_offset, value_offset, _hit_count = _resolve_carry_weight_marker(data, anchor, 1)
        return id_offset, value_offset
    if actor_id == 320:
        id_offset, value_offset, _hit_count = _resolve_carry_weight_sw_pointer(data, anchor)
        return id_offset, value_offset

    # Fast path for the normal contiguous player actor-value list.  The validated
    # skill block anchors ActorValue 6 at anchor+0x08 and the value at anchor+0x0C.
    if actor_id >= 6:
        expected_index = actor_id - 6
        id_offset = anchor + 0x08 + expected_index * 0x08
        value_offset = id_offset + 4
        if value_offset + 4 <= len(data) and _u32_le_from_payload(data, id_offset) == actor_id:
            return id_offset, value_offset

    def scan_range(start: int, end: int, *, require_stride: bool) -> list[tuple[int, int]]:
        hits: list[tuple[int, int]] = []
        pos = max(0, start)
        hay = bytes(data)
        end = max(pos, min(len(data), end))
        while True:
            found = hay.find(actor_bytes, pos, end)
            if found < 0:
                break
            value_at = found + 4
            if value_at + 4 <= len(data):
                aligned = (found % 4) == 0
                stride_ok = actor_id < 6 or (found - (anchor + 0x08)) % 0x08 == 0
                if aligned and plausible_value_at(value_at):
                    if not require_stride or stride_ok:
                        hits.append((found, value_at))
            pos = found + 1
        return hits

    # First prefer the exact 8-byte actor-value stride around the validated skill
    # block.  Then allow a wider aligned scan near the block for saves where the
    # list is sparse or shifted.  Only a unique candidate is accepted.
    windows = (
        (max(0, anchor - 0x40), min(len(data), anchor + 0x800), True),
        (max(0, anchor - 0x100), min(len(data), anchor + 0x2000), False),
    )
    for start, end, require_stride in windows:
        hits = scan_range(start, end, require_stride=require_stride)
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            choices = ", ".join(f"0x{id_off:X}" for id_off, _value_off in hits[:8])
            raise PresetPatchError(
                f"Multiple candidate ActorValue {actor_id} records were found near the player block: {choices}. "
                "No bytes were changed because the editor cannot prove which one is the player value."
            )

    raise PresetPatchError(
        f"Could not safely locate ActorValue {actor_id} ({SKYRIM_ACTOR_VALUE_NAMES.get(actor_id, 'unknown')}) "
        "near the validated player actor-value block. No bytes were changed."
    )


def _resolve_skyrim_skill_block(data: bytes | bytearray) -> tuple[int, bytes, str]:
    # The posted all-skills code searches 05 00 00 00 / 00 00 00 00 / 06 00 00 00,
    # then writes 18 float values at pointer+0x0C, stepping by 0x08. That anchor is
    # generic enough to appear in the wrong place, so we now scan every match and
    # only accept a candidate whose 18 float slots already look like a Skyrim skill
    # array. This is the crash-safety guard that prevents blind Save Wizard pattern
    # writes from landing on unrelated payload bytes.
    candidates = (
        ("primary skill block anchor", bytes.fromhex("05 00 00 00 00 00 00 00 06 00 00 00")),
        ("alternate skill block anchor", bytes.fromhex("04 00 00 00 00 00 00 00 06 00 00 00")),
    )
    required_end_extra = 0x0C + (len(SKYRIM_SKILL_NAMES) - 1) * 0x08 + 4
    valid: list[tuple[int, str, int, bytes, list[float]]] = []
    raw_hit_count = 0
    for label, pattern in candidates:
        hits = _find_all_bytes(data, pattern)
        raw_hit_count += len(hits)
        for found in hits:
            if found + required_end_extra > len(data):
                continue
            scored = _skill_candidate_score(data, found)
            if not scored:
                continue
            score, values = scored
            valid.append((score, label, found, pattern, values))

    if not valid:
        raise PresetPatchError(
            "Could not safely locate the Skyrim skill block. The 05...06/04...06 anchors were scanned, "
            f"but none of the {raw_hit_count} raw matches contained 18 plausible skill floats. "
            "No bytes were changed."
        )

    valid.sort(key=lambda item: item[0], reverse=True)
    best_score, best_label, best_offset, best_pattern, best_values = valid[0]
    tied = [item for item in valid if item[0] == best_score]
    if len(tied) > 1:
        choices = ", ".join(f"0x{item[2]:X}" for item in tied[:8])
        raise PresetPatchError(
            "More than one plausible skill block was found with the same confidence score: "
            f"{choices}. No bytes were changed because the editor cannot prove which block is the player."
        )
    detail = f"{best_label} (validated skill floats, {len(valid)} plausible candidate(s), {raw_hit_count} raw anchor hit(s))"
    return best_offset, best_pattern, detail

def read_skyrim_skill_values(source: str | Path) -> tuple[list[SkillValueSlot], list[PresetSearchHit], int]:
    source = Path(source)
    ctx = load_player_data(source)
    data = ctx.player_data
    anchor, pattern, label = _resolve_skyrim_skill_block(data)
    if ctx.compressed:
        label += " inside zlib-compressed player ChangeForm"
    searches = [PresetSearchHit(label, anchor, pattern.hex(" ").upper(), 1)]
    slots: list[SkillValueSlot] = []
    for index, name in enumerate(SKYRIM_SKILL_NAMES):
        offset = anchor + 0x0C + index * 0x08
        raw = bytes(data[offset:offset + 4])
        slots.append(SkillValueSlot(index, name, offset, _float32_le_from_payload(data, offset), raw.hex(" ").upper()))
    return slots, searches, len(data)


def build_skyrim_skill_patch_plan(source: str | Path, skill_values: dict[int, float]) -> tuple[SkillPatchPlan, bytes]:
    source = Path(source)
    ctx = load_player_data(source)
    data = bytearray(ctx.player_data)
    anchor, pattern, label = _resolve_skyrim_skill_block(data)
    if ctx.compressed:
        label += " inside zlib-compressed player ChangeForm"
    searches = [PresetSearchHit(label, anchor, pattern.hex(" ").upper(), 1)]
    skills: list[SkillValueSlot] = []
    for index, name in enumerate(SKYRIM_SKILL_NAMES):
        offset = anchor + 0x0C + index * 0x08
        raw = bytes(data[offset:offset + 4])
        skills.append(SkillValueSlot(index, name, offset, _float32_le_from_payload(data, offset), raw.hex(" ").upper()))

    writes: list[PresetWrite] = []
    clean_values: dict[int, float] = {}
    for raw_index, raw_value in (skill_values or {}).items():
        index = int(raw_index)
        if index < 0 or index >= len(SKYRIM_SKILL_NAMES):
            raise PresetPatchError(f"Invalid skill slot {index + 1}; expected 1-{len(SKYRIM_SKILL_NAMES)}.")
        value = float(raw_value)
        if value < 0 or value > SKYRIM_SKILL_TEST_MAX:
            raise PresetPatchError(f"Skill value is outside the test editor range (0-{SKYRIM_SKILL_TEST_MAX:,.0f}). Use 100 for normal max skills or 999,999 for this test build.")
        offset = anchor + 0x0C + index * 0x08
        _record_write(data, offset, _float32_le_bytes(value), f"{SKYRIM_SKILL_NAMES[index]} skill value", writes)
        clean_values[index] = value

    plan = SkillPatchPlan(
        requested_values=clean_values,
        searches=searches,
        skills=skills,
        writes=writes,
        payload_size=len(data),
    )
    return plan, bytes(data)


def apply_skyrim_skill_patch(source: str | Path, target: str | Path, skill_values: dict[int, float]) -> SkillPatchPlan:
    source = Path(source)
    target = Path(target)
    plan, patched_payload = build_skyrim_skill_patch_plan(source, skill_values)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        temp = target.with_suffix(target.suffix + ".tmp-skills-save-lab")
        try:
            rebuild_save_with_player_data(source, temp, patched_payload)
            shutil.move(str(temp), str(target))
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
    else:
        rebuild_save_with_player_data(source, target, patched_payload)
    return plan


def read_skyrim_actor_values(source: str | Path, actor_ids: tuple[int, ...] | None = None) -> tuple[list[ActorValueSlot], list[PresetSearchHit], int]:
    source = Path(source)
    ctx = load_player_data(source)
    data = ctx.player_data
    anchor, pattern, label = _resolve_skyrim_skill_block(data)
    if ctx.compressed:
        label += " inside zlib-compressed player ChangeForm"
    searches = [PresetSearchHit(label, anchor, pattern.hex(" ").upper(), 1)]
    ids = actor_ids or tuple(actor_id for actor_id, _name in SKYRIM_ACTOR_VALUE_FIELDS)
    slots: list[ActorValueSlot] = []
    missing: list[str] = []
    for actor_id in ids:
        actor_id = int(actor_id)
        name = SKYRIM_ACTOR_VALUE_NAMES.get(actor_id, f"ActorValue {actor_id}")
        try:
            if actor_id == 320:
                total_value, id_offset, value_offset, mode, detail = _read_carry_weight_total(data, anchor)
                occurrence = 2 if mode == "base+modifier" else 1
                searches.append(PresetSearchHit(
                    f"Carry Weight total resolver ({detail})",
                    id_offset,
                    "20 00 00 00",
                    occurrence,
                ))
                slot_value = total_value
            else:
                id_offset, value_offset = _actor_value_offsets_from_block(data, anchor, actor_id)
                slot_value = _float32_le_from_payload(data, value_offset)
        except PresetPatchError:
            missing.append(name)
            continue
        id_raw = bytes(data[id_offset:id_offset + 4])
        value_raw = bytes(data[value_offset:value_offset + 4])
        slots.append(ActorValueSlot(
            actor_id,
            name,
            id_offset,
            value_offset,
            slot_value,
            id_raw.hex(" ").upper(),
            value_raw.hex(" ").upper(),
        ))
    if not slots:
        details = ", ".join(missing) if missing else "none of the enabled actor values"
        raise PresetPatchError(f"Could not locate any enabled player actor values near the validated skill block ({details}).")
    return slots, searches, len(data)


def build_skyrim_actor_value_patch_plan(source: str | Path, actor_values: dict[int, float]) -> tuple[ActorValuePatchPlan, bytes]:
    source = Path(source)
    ctx = load_player_data(source)
    data = bytearray(ctx.player_data)
    anchor, pattern, label = _resolve_skyrim_skill_block(data)
    if ctx.compressed:
        label += " inside zlib-compressed player ChangeForm"
    searches = [PresetSearchHit(label, anchor, pattern.hex(" ").upper(), 1)]
    actor_ids = tuple(actor_id for actor_id, _name in SKYRIM_ACTOR_VALUE_FIELDS)
    slots: list[ActorValueSlot] = []
    located_offsets: dict[int, tuple[int, int]] = {}
    missing_names: list[str] = []
    carry_target_modes: dict[int, str] = {}
    for actor_id in actor_ids:
        name = SKYRIM_ACTOR_VALUE_NAMES.get(actor_id, f"ActorValue {actor_id}")
        try:
            if actor_id == 320:
                total_value, id_offset, value_offset, mode, detail = _read_carry_weight_total(data, anchor)
                occurrence = 2 if mode == "base+modifier" else 1
                searches.append(PresetSearchHit(
                    f"Carry Weight total resolver ({detail})",
                    id_offset,
                    "20 00 00 00",
                    occurrence,
                ))
                slot_value = total_value
                carry_target_modes[actor_id] = mode
            else:
                id_offset, value_offset = _actor_value_offsets_from_block(data, anchor, actor_id)
                slot_value = _float32_le_from_payload(data, value_offset)
        except PresetPatchError:
            missing_names.append(name)
            continue
        located_offsets[actor_id] = (id_offset, value_offset)
        slots.append(ActorValueSlot(
            actor_id,
            name,
            id_offset,
            value_offset,
            slot_value,
            bytes(data[id_offset:id_offset + 4]).hex(" ").upper(),
            bytes(data[value_offset:value_offset + 4]).hex(" ").upper(),
        ))
    if not slots:
        details = ", ".join(missing_names) if missing_names else "none of the enabled actor values"
        raise PresetPatchError(f"Could not locate any enabled player actor values near the validated skill block ({details}).")

    writes: list[PresetWrite] = []
    clean_values: dict[int, float] = {}
    allowed = set(actor_ids)
    for raw_actor_id, raw_value in (actor_values or {}).items():
        actor_id = int(raw_actor_id)
        if actor_id not in allowed:
            raise PresetPatchError(
                f"ActorValue {actor_id} is not enabled for this safe editor pass. "
                f"Enabled values: {', '.join(str(x) for x in sorted(allowed))}."
            )
        value = float(raw_value)
        max_value = 2_000_000_000.0 if actor_id == 320 else 1_000_000_000.0
        if not math.isfinite(value) or value < 0.0 or value > max_value:
            raise PresetPatchError(f"Actor value must be a finite number from 0 to {max_value:,.0f}.")
        if actor_id not in located_offsets:
            name = SKYRIM_ACTOR_VALUE_NAMES.get(actor_id, f"ActorValue {actor_id}")
            raise PresetPatchError(f"{name} was not found in this save's detected player actor-value block, so it cannot be edited safely yet.")
        _id_offset, value_offset = located_offsets[actor_id]
        if actor_id == 320:
            targets = _resolve_carry_weight_total_targets(data, anchor)
            base_float = targets["base"][2]
            modifier = targets.get("modifier")
            if modifier is not None:
                _mod_id, mod_value_offset, _mod_float = modifier
                patch_value = value - base_float
                _record_write(
                    data,
                    mod_value_offset,
                    _float32_le_bytes(patch_value),
                    f"Carry Weight total {value:g} (writes modifier {patch_value:g}; base {base_float:g})",
                    writes,
                )
            else:
                _base_id, base_value_offset, _base_float = targets["base"]
                _record_write(
                    data,
                    base_value_offset,
                    _float32_le_bytes(value),
                    f"Carry Weight total {value:g} (no modifier slot; writes base ActorValue 32)",
                    writes,
                )
        else:
            _record_write(data, value_offset, _float32_le_bytes(value), f"{SKYRIM_ACTOR_VALUE_NAMES.get(actor_id, f'ActorValue {actor_id}')} value", writes)
        clean_values[actor_id] = value

    plan = ActorValuePatchPlan(
        requested_values=clean_values,
        searches=searches,
        actor_values=slots,
        writes=writes,
        payload_size=len(data),
    )
    return plan, bytes(data)


def apply_skyrim_actor_value_patch(source: str | Path, target: str | Path, actor_values: dict[int, float]) -> ActorValuePatchPlan:
    source = Path(source)
    target = Path(target)
    plan, patched_payload = build_skyrim_actor_value_patch_plan(source, actor_values)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        temp = target.with_suffix(target.suffix + ".tmp-actor-values-save-lab")
        try:
            rebuild_save_with_player_data(source, temp, patched_payload)
            shutil.move(str(temp), str(target))
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
    else:
        rebuild_save_with_player_data(source, target, patched_payload)
    return plan


def _resolve_add_exp_anchor(data: bytes | bytearray) -> tuple[int, bytes, str, int]:
    # Original Save Wizard preset:
    # 8001000A 80BF0000
    # 00000000 80BF0000
    # 28000034 <float>
    # 28000038 00000000
    #
    # Important: 8001000A means the search payload length is 0x0A bytes.
    # The second 8-hex word in the posted code is padded, so the actual search
    # bytes are only:
    #   80 BF 00 00 00 00 00 00 80 BF
    primary_pattern = bytes.fromhex("80 BF 00 00 00 00 00 00 80 BF")
    padded_pattern = bytes.fromhex("80 BF 00 00 00 00 00 00 80 BF 00 00")

    hits = _find_all_bytes(data, primary_pattern)
    pattern = primary_pattern
    pattern_label = "10-byte XP pool anchor from Type 8 length 0x000A"
    if not hits:
        hits = _find_all_bytes(data, padded_pattern)
        pattern = padded_pattern
        pattern_label = "12-byte padded XP pool anchor fallback"
    if not hits:
        raise PresetPatchError(
            "Could not locate the XP pool / Add EXP command anchor. Tried the real 10-byte Save Wizard search "
            "(80 BF 00 00 00 00 00 00 80 BF) and the older padded 12-byte fallback "
            "(80 BF 00 00 00 00 00 00 80 BF 00 00). No bytes were changed."
        )
    return hits[0], pattern, pattern_label, len(hits)


def read_skyrim_xp_pool(source: str | Path) -> tuple[float, list[PresetSearchHit], int]:
    source = Path(source)
    ctx = load_player_data(source)
    data = bytearray(ctx.player_data)
    anchor, pattern, pattern_label, hit_count = _resolve_add_exp_anchor(data)
    if ctx.compressed:
        pattern_label += " inside zlib-compressed player ChangeForm"
    searches = [PresetSearchHit(
        f"{pattern_label} ({hit_count} raw hit(s); using first like the original preset)",
        anchor,
        pattern.hex(" ").upper(),
        1,
    )]
    return _float32_le_from_payload(data, anchor + 0x34), searches, len(data)


def build_skyrim_add_exp_patch_plan(source: str | Path, exp_amount: float) -> tuple[AddExpPatchPlan, bytes]:
    source = Path(source)
    value = float(exp_amount)
    if not math.isfinite(value) or value < 0.0 or value > 100_000_000.0:
        raise PresetPatchError("XP pool value must be a finite number from 0 to 100,000,000.")

    ctx = load_player_data(source)
    data = bytearray(ctx.player_data)

    anchor, pattern, pattern_label, hit_count = _resolve_add_exp_anchor(data)
    if ctx.compressed:
        pattern_label += " inside zlib-compressed player ChangeForm"
    searches = [PresetSearchHit(
        f"{pattern_label} ({hit_count} raw hit(s); using first like the original preset)",
        anchor,
        pattern.hex(" ").upper(),
        1,
    )]

    writes: list[PresetWrite] = []
    _record_write(data, anchor + 0x34, _float32_le_bytes(value), "XP pool / pending EXP amount", writes)
    _record_write(data, anchor + 0x38, bytes.fromhex("00 00 00 00"), "XP pool follow-up word cleared", writes)

    plan = AddExpPatchPlan(
        requested_exp=value,
        searches=searches,
        writes=writes,
        payload_size=len(data),
    )
    return plan, bytes(data)


def apply_skyrim_add_exp_patch(source: str | Path, target: str | Path, exp_amount: float) -> AddExpPatchPlan:
    source = Path(source)
    target = Path(target)
    plan, patched_payload = build_skyrim_add_exp_patch_plan(source, exp_amount)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        temp = target.with_suffix(target.suffix + ".tmp-add-exp-save-lab")
        try:
            rebuild_save_with_player_data(source, temp, patched_payload)
            shutil.move(str(temp), str(target))
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
    else:
        rebuild_save_with_player_data(source, target, patched_payload)
    return plan


def build_skyrim_preset_patch_plan(source: str | Path, preset_id: str, value: float | int | None = None) -> tuple[PresetPatchPlan, bytes]:
    """Resolve a Skyrim preset against a save and return (preview plan, patched payload bytes).

    This deliberately implements only the Search + Pointer + Write subset used by
    the bundled Skyrim presets. It is not a general-purpose Save Wizard runtime.
    """
    source = Path(source)
    preset = get_skyrim_quick_code_preset(preset_id)
    requested = preset.default_value if value is None else value
    if preset.value_kind == "int":
        requested = int(round(float(requested)))
    else:
        requested = float(requested)
    code_text = generate_skyrim_quick_code_preset(preset_id, requested)

    doc = read_ess(source, change_form_preview_limit=0)
    if not doc.payload:
        raise EssParseError("Save payload was not decoded; preset patching needs the decompressed ESS payload.")
    data = bytearray(doc.payload.data)
    words = _hex_words(code_text)
    pointer = 0
    searches: list[PresetSearchHit] = []
    writes: list[PresetWrite] = []

    i = 0
    while i < len(words):
        word1 = words[i]
        word2 = words[i + 1]
        code_type = word1[0].upper()
        mode = word1[1].upper()

        if code_type in {"8", "B"}:
            occurrence = int(word1[2:4], 16)
            count = int(word1[4:], 16)
            pattern_hex = word2
            consumed_pairs = 1
            while len(pattern_hex) < count * 2:
                next_pair_index = i + consumed_pairs * 2
                if next_pair_index + 1 >= len(words):
                    raise PresetPatchError("Search pattern data is truncated.")
                pattern_hex += words[next_pair_index] + words[next_pair_index + 1]
                consumed_pairs += 1
            pattern_hex = pattern_hex[:count * 2]
            pattern = bytes.fromhex(pattern_hex)
            start = pointer if _is_pointer_relative(mode) else 0
            found = _find_nth(data, pattern, start, occurrence, forward=(code_type == "8"))
            pointer = found
            searches.append(PresetSearchHit(f"Type {code_type} byte search", found, pattern.hex(" ").upper(), max(1, occurrence)))
            i += consumed_pairs * 2
            continue

        if code_type in {"0", "1", "2"}:
            width = _width_from_standard(code_type)
            address = int(word1[2:], 16)
            offset = (pointer if _is_pointer_relative(mode) else 0) + address
            patch = _write_bytes_for_numeric_word(word2, width)
            _record_write(data, offset, patch, f"{width * 8}-bit numeric preset write", writes)
            i += 2
            continue

        if code_type == "4":
            if i + 3 >= len(words):
                raise PresetPatchError("Type 4 preset is missing its repeater line.")
            width = _width_from_type4_mode(mode)
            address = int(word1[2:], 16)
            base_offset = (pointer if _is_pointer_relative(mode) else 0) + address
            patch = _write_bytes_for_numeric_word(word2, width)
            repeat_word = words[i + 2]
            inc_word = words[i + 3]
            if repeat_word[0].upper() != "4":
                raise PresetPatchError("Type 4 preset has an invalid repeater line.")
            repeat_count = int(repeat_word[1:4], 16)
            address_step = int(repeat_word[4:], 16)
            value_increment = int(inc_word, 16)
            if value_increment != 0:
                raise PresetPatchError("Type 4 value increments are not implemented for direct Skyrim presets.")
            # Save Wizard's Skyrim skill/stat presets use the repeat count as the
            # total number of fixed-width writes in the series.
            for n in range(repeat_count):
                _record_write(data, base_offset + n * address_step, patch, f"series write {n + 1}/{repeat_count}", writes)
            i += 4
            continue

        raise PresetPatchError(f"Preset contains unsupported quick-code type {code_type}.")

    plan = PresetPatchPlan(
        preset_id=preset_id,
        preset_name=preset.name,
        value_label=preset.value_label,
        requested_value=requested,
        code_text=code_text,
        searches=searches,
        writes=writes,
        payload_size=len(data),
    )
    return plan, bytes(data)


def apply_skyrim_preset_patch(source: str | Path, target: str | Path, preset_id: str, value: float | int | None = None, *, allow_experimental: bool = False) -> PresetPatchPlan:
    source = Path(source)
    target = Path(target)
    if preset_id in EXPERIMENTAL_SW_PRESET_IDS and source.resolve() == target.resolve():
        raise PresetPatchError(
            "In-place Save Wizard-pattern preset writes are disabled after crash reports. "
            "Use the separated Skills tab for validated skill edits, or save an experimental preset copy only."
        )
    if preset_id in EXPERIMENTAL_SW_PRESET_IDS and not allow_experimental:
        raise PresetPatchError(
            "This is an experimental Save Wizard-pattern preset. Enable the experimental copy checkbox in the UI before writing a copy."
        )
    plan, patched_payload = build_skyrim_preset_patch_plan(source, preset_id, value)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        temp = target.with_suffix(target.suffix + ".tmp-preset-save-lab")
        try:
            rebuild_save_with_payload(source, temp, patched_payload)
            shutil.move(str(temp), str(target))
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
    else:
        rebuild_save_with_payload(source, target, patched_payload)
    return plan
