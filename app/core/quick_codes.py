from __future__ import annotations

from dataclasses import dataclass
import re
import struct


@dataclass(frozen=True, slots=True)
class QuickCodeFormat:
    code_type: str
    name: str
    layout: str
    meaning: str
    notes: str
    example: str


@dataclass(frozen=True, slots=True)
class SkyrimQuickCodePreset:
    preset_id: str
    name: str
    value_label: str
    value_kind: str
    default_value: float
    minimum: float
    maximum: float
    decimals: int
    description: str
    warning: str


QUICK_CODE_FORMATS: tuple[QuickCodeFormat, ...] = (
    QuickCodeFormat("0", "Standard 1-byte write", "0BYYYYYY 000000XX", "Writes one byte to an address.", "B is 0 for normal address or 8 for pointer-relative address.", "00000456 00000063"),
    QuickCodeFormat("1", "Standard 2-byte write", "1BYYYYYY 0000XXXX", "Writes two bytes to an address.", "Most Save Wizard standard writes are entered big-endian; some games/tools swap in the final save.", "10001E24 000003E7"),
    QuickCodeFormat("2", "Standard 4-byte write", "2BYYYYYY XXXXXXXX", "Writes four bytes to an address.", "B is 0 for normal address or 8 for pointer-relative address.", "20000250 3B9AC9FF"),
    QuickCodeFormat("3", "Increase / decrease", "3BYYYYYY XXXXXXXX", "Adds or subtracts an integer-sized value at an address.", "B selects width, add/subtract, and pointer-relative variants.", "31003E3D 0000112A"),
    QuickCodeFormat("4", "Multi-write repeater", "4BYYYYYY XXXXXXXX / 4CCCDDDD ZZZZZZZZ", "Writes a value repeatedly while stepping the address and optionally the value.", "C is repeat count, D is address step, Z is value increment.", "41004500 00000100\n4004000C 00000002"),
    QuickCodeFormat("5", "Copy and paste", "5BYYYYYY XXXXXXXX / 5BZZZZZZ 00000000", "Copies bytes from one address and writes them to another.", "X is byte count; Y is source; Z is destination.", "500000A2 00000004\n500000B4 00000000"),
    QuickCodeFormat("7", "No less / no more than", "7BYYYYYY XXXXXXXX", "Clamps a value only if it is under or over the requested threshold.", "B selects no-less/no-more, width, and pointer-relative variants.", "72001234 000F423F"),
    QuickCodeFormat("8", "Forward byte search / set pointer", "8BCCYYYY XXXXXXXX", "Searches forward for bytes and stores the hit address as the pointer offset.", "CC is occurrence index; YYYY is byte-count searched from following data words.", "80010004 01B00117"),
    QuickCodeFormat("9", "Pointer manipulator", "9Y000000 XXXXXXXX", "Sets, moves, adds to, subtracts from, or EOF-bases the current pointer offset.", "Y selects operator: BE pointer read, LE pointer read, add, subtract, EOF-minus, or direct set.", "92000000 00000010"),
    QuickCodeFormat("A", "Mass write", "ABYYYYYY XXXXXXXX / data...", "Writes an arbitrary byte sequence beginning at an address.", "X is byte count; following lines hold data bytes.", "A0004510 00000010\n11223344 55667788\n99AABBCC DDEEFF00"),
    QuickCodeFormat("B", "Backward byte search / set pointer", "BBCCYYYY XXXXXXXX", "Searches backward for bytes and stores the hit address as the pointer offset.", "Same shape as Type 8 but searches from the end/current pointer backwards.", "B0010004 01B00117"),
    QuickCodeFormat("C", "Address byte search / set pointer", "CBFFYYYY XXXXXXXX", "Uses bytes from an address as the search value and stores the found address as pointer.", "Mode 0/4/8/C controls direction/range and pointer-relative addressing.", "C0010004 00004510"),
    QuickCodeFormat("D", "2-byte test / code skipper", "DBYYYYYY CCDDXXXX", "Tests a 2-byte value and skips following code lines when the test fails.", "C is lines to skip; D is compare operation: equal, not equal, greater, less.", "D0001234 010003E7"),
)


SKYRIM_QUICK_CODE_PRESETS: tuple[SkyrimQuickCodePreset, ...] = (
    SkyrimQuickCodePreset(
        "all_skills_level",
        "All Skills Level",
        "Skill level",
        "float",
        100.0,
        1.0,
        100.0,
        1,
        "Searches the player skill block and writes the same float value across the skill entries.",
        "Backup first. If this breaks a save, the original note says to change the first search value from 05000000 to 04000000 and retest.",
    ),
    SkyrimQuickCodePreset(
        "carry_weight",
        "Carry Weight",
        "Carry weight",
        "float",
        999_999_680.0,
        0.0,
        1_000_000_000.0,
        0,
        "Searches the actor-value area and writes a float carry-weight value.",
        "This is still a Save Wizard search/pointer preset, not a direct mapped ESS field.",
    ),
    SkyrimQuickCodePreset(
        "health_magicka_stamina",
        "Health / Magicka / Stamina",
        "Stat value",
        "float",
        1_000_000_000.0,
        0.0,
        1_000_000_000.0,
        0,
        "Searches the actor-value area and writes the same float value across six stat-related fields.",
        "Very large stat values can still destabilize saves. Use a copy first.",
    ),
    SkyrimQuickCodePreset(
        "add_exp",
        "Add EXP",
        "EXP amount",
        "float",
        100_000.0,
        0.0,
        100_000_000.0,
        0,
        "Searches the real XP structure and writes the requested float EXP amount, then clears the following word.",
        "Can be reused multiple times. The header XP editor is separate from this real XP structure.",
    ),
    SkyrimQuickCodePreset(
        "perk_points",
        "Perk Points",
        "Perk points",
        "int",
        255.0,
        0.0,
        255.0,
        0,
        "Searches the perk-points structure and writes one unsigned byte.",
        "Default max is 255 because the pasted code uses 000000FF.",
    ),
)


class QuickCodeDecodeError(ValueError):
    """Raised when pasted quick-code text cannot be decoded enough to describe it."""


_HEX_RE = re.compile(r"[0-9A-Fa-f]+")
_HEX8_TOKEN_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{8})(?![0-9A-Fa-f])")


def clean_hex(text: str) -> str:
    """Return only hex characters from a user field."""
    return "".join(_HEX_RE.findall(text or "")).upper()


def _line_hex_groups(raw: str) -> list[str]:
    """Extract 8-hex groups from a pasted line while ignoring labels/notes.

    Save Wizard tables often include credits, warnings, and labels in the same pasted
    block as the code. The decoder should ignore those text lines instead of trying
    to treat words such as "READ" or "Dynamite" as hexadecimal.
    """
    raw = raw.split("//", 1)[0].split("#", 1)[0].strip()
    if not raw:
        return []
    groups = [m.group(1).upper() for m in _HEX8_TOKEN_RE.finditer(raw)]
    if groups:
        return groups
    compact = re.sub(r"[\s_]+", "", raw).upper()
    if compact and len(compact) % 8 == 0 and re.fullmatch(r"[0-9A-F]+", compact):
        return [compact[i:i + 8] for i in range(0, len(compact), 8)]
    return []


def _code_lines(text: str) -> list[str]:
    lines: list[str] = []
    skipped_hexish: list[str] = []
    for raw in (text or "").splitlines():
        groups = _line_hex_groups(raw)
        if not groups:
            stripped = raw.strip()
            if stripped and any(ch in "0123456789ABCDEFabcdef" for ch in stripped) and not any(ch.isalpha() and ch.upper() not in "ABCDEF" for ch in stripped):
                skipped_hexish.append(stripped)
            continue
        i = 0
        while i < len(groups):
            if i + 1 < len(groups):
                lines.append(f"{groups[i]} {groups[i + 1]}")
                i += 2
            else:
                lines.append(groups[i])
                i += 1
    if not lines and skipped_hexish:
        raise QuickCodeDecodeError("No complete 8-hex code groups were found. Check spacing and line breaks.")
    return lines


def _split_line(line: str) -> tuple[str, str]:
    parts = line.split()
    if len(parts) != 2:
        raise QuickCodeDecodeError(f"Expected a code line with two 8-hex words, got: {line}")
    return parts[0].upper(), parts[1].upper()


def _offset_text(nibble: str) -> str:
    return "pointer-relative" if nibble.upper() in {"8", "9", "A", "B", "C", "D", "E", "F"} else "normal"


def _width_from_standard_type(code_type: str) -> int | None:
    return {"0": 1, "1": 2, "2": 4}.get(code_type.upper())


def _width_text(width: int | None) -> str:
    return {1: "1 byte", 2: "2 bytes", 4: "4 bytes", 8: "8 bytes"}.get(width, "unknown width")


def _describe_type3_mode(mode: str) -> str:
    table = {
        "0": ("add", 1), "1": ("add", 2), "2": ("add", 4), "3": ("add", 8),
        "4": ("subtract", 1), "5": ("subtract", 2), "6": ("subtract", 4), "7": ("subtract", 8),
        "8": ("add", 1), "9": ("add", 2), "A": ("add", 4), "B": ("add", 8),
        "C": ("subtract", 1), "D": ("subtract", 2), "E": ("subtract", 4), "F": ("subtract", 8),
    }
    op, width = table.get(mode.upper(), ("adjust", None))
    return f"{op} {_width_text(width)} ({_offset_text(mode)} offset)"


def _describe_type7_mode(mode: str) -> str:
    table = {
        "0": ("no less than", 1), "1": ("no less than", 2), "2": ("no less than", 4),
        "4": ("no more than", 1), "5": ("no more than", 2), "6": ("no more than", 4),
        "8": ("pointer no less than", 1), "9": ("pointer no less than", 2), "A": ("pointer no less than", 4),
        "C": ("pointer no more than", 1), "D": ("pointer no more than", 2), "E": ("pointer no more than", 4),
    }
    op, width = table.get(mode.upper(), ("clamp", None))
    return f"{op}, {_width_text(width)}"


def _pointer_operator(op: str) -> str:
    return {
        "0": "set pointer to big-endian value read at X",
        "1": "set pointer to little-endian value read at X",
        "2": "add X to pointer",
        "3": "subtract X from pointer",
        "4": "set pointer to EOF then subtract X",
        "5": "set pointer directly to X",
    }.get(op.upper(), "unknown pointer operation")


def _data_words_after(lines: list[str], index: int, byte_count: int) -> tuple[list[str], int]:
    data_words: list[str] = []
    consumed = 0
    j = index + 1
    while j < len(lines) and consumed < byte_count:
        compact = clean_hex(lines[j])
        if not compact:
            break
        # Stop if the next item looks like a real code line. Search payload data can
        # also be two words, so only stop once we already have the declared bytes.
        data_words.append(compact)
        consumed += len(compact) // 2
        j += 1
    return data_words, consumed


def decode_quick_code_text(text: str) -> str:
    """Decode pasted Save Wizard/Game Genie style quick-code lines into readable notes."""
    lines = _code_lines(text)
    if not lines:
        return "Paste one or more quick-code lines to decode. Text labels and notes are ignored automatically."

    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if " " not in line:
            out.append(f"Data word {i + 1}: {line}")
            i += 1
            continue
        word1, word2 = _split_line(line)
        code_type = word1[0].upper()
        mode = word1[1].upper()
        address = word1[2:].upper()

        if code_type in {"0", "1", "2"}:
            width = _width_from_standard_type(code_type)
            value_hex = word2[-(width or 4) * 2:]
            out.append(
                f"Line {i + 1}: Type {code_type} standard {_width_text(width)} write | "
                f"address 0x{address} ({_offset_text(mode)}) | value 0x{value_hex} ({int(value_hex, 16)})"
            )
            i += 1
        elif code_type == "3":
            out.append(
                f"Line {i + 1}: Type 3 increase/decrease | { _describe_type3_mode(mode) } | "
                f"address 0x{address} | amount 0x{word2} ({int(word2, 16)})"
            )
            i += 1
        elif code_type == "4":
            detail = "missing repeater line"
            if i + 1 < len(lines) and " " in lines[i + 1]:
                r1, r2 = _split_line(lines[i + 1])
                if r1[0].upper() == "4":
                    repeat = int(r1[1:4], 16)
                    step = int(r1[4:], 16)
                    inc = int(r2, 16)
                    detail = f"repeat {repeat} time(s), address step 0x{step:X}, value increment 0x{inc:X}"
                    i += 1
            out.append(
                f"Line {i}: Type 4 multi-write | address 0x{address} ({_offset_text(mode)}) | "
                f"base value 0x{word2} | {detail}"
            )
            i += 1
        elif code_type == "5":
            detail = "missing paste line"
            if i + 1 < len(lines) and " " in lines[i + 1]:
                p1, _p2 = _split_line(lines[i + 1])
                if p1[0].upper() == "5":
                    detail = f"paste to 0x{p1[2:]} ({_offset_text(p1[1])})"
                    i += 1
            out.append(
                f"Line {i}: Type 5 copy/paste | copy 0x{word2} byte(s) from 0x{address} ({_offset_text(mode)}) | {detail}"
            )
            i += 1
        elif code_type == "7":
            out.append(
                f"Line {i + 1}: Type 7 no-less/no-more clamp | {_describe_type7_mode(mode)} | "
                f"address 0x{address} | threshold/value 0x{word2} ({int(word2, 16)})"
            )
            i += 1
        elif code_type in {"8", "B"}:
            direction = "forward" if code_type == "8" else "backward"
            occurrence = int(word1[2:4], 16)
            byte_count = int(word1[4:], 16)
            remaining = max(byte_count - 4, 0)
            extra_words, extra_bytes = _data_words_after(lines, i, remaining) if remaining else ([], 0)
            extra_note = f", extra search data {' '.join(extra_words)}" if extra_words else ""
            out.append(
                f"Line {i + 1}: Type {code_type} {direction} byte search / set pointer | "
                f"occurrence {occurrence}, search length {byte_count} byte(s), first data word 0x{word2} ({_offset_text(mode)})"
                f"{extra_note}"
            )
            i += 1 + len(extra_words)
        elif code_type == "9":
            out.append(
                f"Line {i + 1}: Type 9 pointer manipulator | {_pointer_operator(mode)} | value/address 0x{word2} ({int(word2, 16)})"
            )
            i += 1
        elif code_type == "A":
            count = int(word2, 16)
            data_words: list[str] = []
            j = i + 1
            bytes_seen = 0
            while j < len(lines) and bytes_seen < count:
                data_hex = clean_hex(lines[j])
                if not data_hex:
                    break
                data_words.append(data_hex)
                bytes_seen += len(data_hex) // 2
                j += 1
            out.append(
                f"Line {i + 1}: Type A mass write | address 0x{address} ({_offset_text(mode)}) | "
                f"declared {count} byte(s), pasted data {bytes_seen} byte(s) | data {' '.join(data_words) or '(none)'}"
            )
            i = max(j, i + 1)
        elif code_type == "C":
            occurrence = int(word1[2:4], 16)
            byte_count = int(word1[4:], 16)
            out.append(
                f"Line {i + 1}: Type C address byte search / set pointer | mode {mode}, occurrence {occurrence}, "
                f"length {byte_count} byte(s), source address 0x{word2}"
            )
            i += 1
        elif code_type == "D":
            skip = int(word2[0:2], 16)
            op = {"00": "equal", "01": "not equal", "02": "greater than", "03": "less than"}.get(word2[2:4], "unknown compare")
            value = word2[4:]
            out.append(
                f"Line {i + 1}: Type D 2-byte test / skipper | address 0x{address} ({_offset_text(mode)}) | "
                f"skip {skip} line(s) if test fails | compare {op} 0x{value} ({int(value, 16)})"
            )
            i += 1
        else:
            out.append(f"Line {i + 1}: Unknown or unsupported Type {code_type} | raw {word1} {word2}")
            i += 1

    out.append("")
    out.append("Pasted-table note: labels, credits, and warning text were ignored; only complete 8-hex groups were decoded.")
    out.append("Endian note: Save Wizard custom codes are normally written in big-endian text form, but many PS4 saves store little-endian values and Save Wizard may swap standard write codes for specific games. Treat decoded addresses/values as mapping clues until verified against a before/after save pair.")
    return "\n".join(out)


def _parse_int_field(text: str, *, name: str, max_value: int | None = None, base: int | None = None) -> int:
    raw = (text or "").strip()
    if not raw:
        raise ValueError(f"{name} is required.")
    if base is None:
        if raw.lower().startswith("0x"):
            base = 16
        elif re.fullmatch(r"[0-9]+", raw):
            base = 10
        else:
            base = 16
    value = int(raw.replace("_", ""), base)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} cannot exceed 0x{max_value:X}.")
    return value


def _float32_hex(value: float) -> str:
    return struct.pack(">f", float(value)).hex().upper()


def _u32_hex(value: int) -> str:
    value = int(value)
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("Integer preset value must fit in unsigned 32-bit range.")
    return f"{value:08X}"


def get_skyrim_quick_code_preset(preset_id: str) -> SkyrimQuickCodePreset:
    for preset in SKYRIM_QUICK_CODE_PRESETS:
        if preset.preset_id == preset_id:
            return preset
    raise KeyError(f"Unknown Skyrim quick-code preset: {preset_id}")


def generate_skyrim_quick_code_preset(preset_id: str, value: float | int | None = None) -> str:
    preset = get_skyrim_quick_code_preset(preset_id)
    v = preset.default_value if value is None else value
    if v < preset.minimum or v > preset.maximum:
        raise ValueError(f"{preset.value_label} must be between {preset.minimum:g} and {preset.maximum:g}.")

    if preset.preset_id == "all_skills_level":
        hx = _float32_hex(float(v))
        return f"8001000C 05000000\n00000000 06000000\n4A00000C {hx}\n40120008 00000000"
    if preset.preset_id == "carry_weight":
        hx = _float32_hex(float(v))
        return f"8001000C 05000000\n00000000 06000000\n88020004 20000000\n28000004 {hx}"
    if preset.preset_id == "health_magicka_stamina":
        hx = _float32_hex(float(v))
        return f"8001000C 05000000\n00000000 06000000\n4A00009C {hx}\n40060008 00000000"
    if preset.preset_id == "add_exp":
        hx = _float32_hex(float(v))
        return f"8001000A 80BF0000\n00000000 80BF0000\n28000034 {hx}\n28000038 00000000"
    if preset.preset_id == "perk_points":
        hx = _u32_hex(round(float(v)))
        return f"80010008 00000041\n37464137 00000000\n8801000C 01000000\n00000000 00000000\n0800000C {hx}"
    raise KeyError(f"Unknown Skyrim quick-code preset: {preset_id}")


def generate_standard_write_code(address: str, value: str, width: int, offset_mode: str = "0", *, value_is_decimal: bool = False) -> str:
    """Build a Type 0/1/2 standard write code line."""
    if width not in {1, 2, 4}:
        raise ValueError("Standard write width must be 1, 2, or 4 bytes.")
    address_int = _parse_int_field(address, name="Address", max_value=0xFFFFFF, base=16)
    value_int = _parse_int_field(value, name="Value", max_value=(1 << (width * 8)) - 1, base=10 if value_is_decimal else 16)
    type_digit = {1: "0", 2: "1", 4: "2"}[width]
    mode = clean_hex(offset_mode or "0")[:1] or "0"
    if mode.upper() not in {"0", "8"}:
        raise ValueError("Standard write offset mode must be 0 normal or 8 pointer-relative.")
    return f"{type_digit}{mode.upper()}{address_int:06X} {value_int:0{width * 2}X}".replace(" ", f" {'0' * (8 - width * 2)}", 1) if width < 4 else f"{type_digit}{mode.upper()}{address_int:06X} {value_int:08X}"


def generate_mass_write_code(address: str, data_hex: str, offset_mode: str = "0") -> str:
    """Build a Type A mass-write code from raw hex bytes."""
    address_int = _parse_int_field(address, name="Address", max_value=0xFFFFFF, base=16)
    data = clean_hex(data_hex)
    if not data:
        raise ValueError("Data bytes are required.")
    if len(data) % 2:
        raise ValueError("Data bytes must contain an even number of hex digits.")
    mode = clean_hex(offset_mode or "0")[:1] or "0"
    if mode.upper() not in {"0", "8"}:
        raise ValueError("Mass-write offset mode must be 0 normal or 8 pointer-relative.")
    lines = [f"A{mode.upper()}{address_int:06X} {len(data) // 2:08X}"]
    words = [data[i:i + 8].ljust(8, "0") for i in range(0, len(data), 8)]
    for i in range(0, len(words), 2):
        pair = words[i:i + 2]
        lines.append(" ".join(pair))
    return "\n".join(lines)
