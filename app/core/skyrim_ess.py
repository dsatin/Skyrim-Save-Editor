from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import struct
from typing import Any, Iterable

MAGIC = b"TESV_SAVEGAME"


class EssParseError(ValueError):
    pass


@dataclass(slots=True)
class SaveHeader:
    magic: str
    header_size: int
    version: int
    save_number: int
    player_name: str
    player_name_offset: int
    player_name_capacity: int
    player_level: int
    player_location: str
    player_location_offset: int
    player_location_capacity: int
    game_date: str
    game_date_offset: int
    game_date_capacity: int
    player_race: str
    player_race_offset: int
    player_race_capacity: int
    player_sex: int
    player_current_exp: float
    player_needed_exp: float
    filetime_raw_hex: str
    screenshot_width: int
    screenshot_height: int
    compression_type: int | None
    header_start: int
    header_end: int
    player_level_offset: int
    player_sex_offset: int
    player_current_exp_offset: int
    player_needed_exp_offset: int
    screenshot_offset: int
    screenshot_size: int
    screenshot_bpp: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sex_text(self) -> str:
        return {0: "Male", 1: "Female"}.get(self.player_sex, f"Unknown ({self.player_sex})")

    @property
    def compression_text(self) -> str:
        if self.compression_type is None:
            return "Not present in header"
        return {0: "None", 1: "zlib", 2: "LZ4"}.get(self.compression_type, f"Unknown ({self.compression_type})")


@dataclass(slots=True)
class SavePayload:
    physical_offset: int
    virtual_offset: int
    compression_type: int | None
    screenshot_bpp: int
    uncompressed_size: int
    compressed_size: int | None
    data: bytes
    form_version: int | None
    plugin_info_size: int | None

    @property
    def is_compressed(self) -> bool:
        return self.compression_type in (1, 2) and self.compressed_size is not None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("data", None)
        d["data_length"] = len(self.data)
        d["compression_name"] = {0: "None", 1: "zlib", 2: "LZ4"}.get(self.compression_type, str(self.compression_type))
        return d


@dataclass(slots=True)
class PluginInfo:
    offset: int
    size: int | None
    plugins: list[str]
    light_plugins: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FileLocationTable:
    offset: int
    form_id_array_count_offset: int
    unknown_table_3_offset: int
    global_data_table_1_offset: int
    global_data_table_2_offset: int
    change_forms_offset: int
    global_data_table_3_offset: int
    global_data_table_1_count: int
    global_data_table_2_count: int
    global_data_table_3_count: int
    change_form_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GlobalDataEntry:
    table: int
    index: int
    offset: int
    data_offset: int
    type: int
    length: int
    sample_hex: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChangeFormEntry:
    index: int
    offset: int
    refid_hex: str
    ref_type: int
    ref_value: int
    form_id_guess: str
    change_flags: int
    form_type: int
    lengths_size: int
    version: int
    length1: int
    length2: int
    data_offset: int
    data_end_offset: int
    sample_hex: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanHit:
    area: str
    offset: int
    virtual_offset: int | None
    pattern: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EssDocument:
    path: Path
    header: SaveHeader
    payload: SavePayload | None
    plugin_info: PluginInfo | None
    file_location_table: FileLocationTable | None
    global_data_entries: list[GlobalDataEntry]
    change_forms_preview: list[ChangeFormEntry]
    file_size: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "file_size": self.file_size,
            "header": self.header.to_dict(),
            "payload": self.payload.to_dict() if self.payload else None,
            "plugin_info": self.plugin_info.to_dict() if self.plugin_info else None,
            "file_location_table": self.file_location_table.to_dict() if self.file_location_table else None,
            "global_data_entries": [e.to_dict() for e in self.global_data_entries],
            "change_forms_preview": [e.to_dict() for e in self.change_forms_preview],
            "warnings": self.warnings,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class ByteReader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def ensure(self, count: int) -> None:
        if self.pos + count > len(self.data):
            raise EssParseError(f"Unexpected end of file at 0x{self.pos:X}; needed {count} bytes")

    def tell(self) -> int:
        return self.pos

    def seek(self, pos: int) -> None:
        if pos < 0 or pos > len(self.data):
            raise EssParseError(f"Seek outside file: 0x{pos:X}")
        self.pos = pos

    def read(self, count: int) -> bytes:
        self.ensure(count)
        out = self.data[self.pos:self.pos + count]
        self.pos += count
        return out

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack_from("<H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack_from("<I", self.read(4))[0]

    def i32(self) -> int:
        return struct.unpack_from("<i", self.read(4))[0]

    def f32(self) -> float:
        return struct.unpack_from("<f", self.read(4))[0]

    def wstring(self) -> str:
        _offset, _capacity, value = self.wstring_with_metadata()
        return value

    def wstring_with_metadata(self) -> tuple[int, int, str]:
        offset = self.tell()
        length = self.u16()
        raw = self.read(length)
        value = raw.decode("utf-8", errors="replace").rstrip("\x00")
        return offset, length, value


def read_ess(path: str | Path, *, change_form_preview_limit: int = 500) -> EssDocument:
    path = Path(path)
    data = path.read_bytes()
    reader = ByteReader(data)
    warnings: list[str] = []

    magic = reader.read(len(MAGIC))
    if magic != MAGIC:
        raise EssParseError("Not a Skyrim ESS/SAVEDATA save: missing TESV_SAVEGAME magic")
    header_size = reader.u32()
    header_start = reader.tell()
    header_end = header_start + header_size
    if header_end > len(data):
        raise EssParseError("Header size points past end of file")

    version = reader.u32()
    save_number = reader.u32()
    player_name_offset, player_name_capacity, player_name = reader.wstring_with_metadata()
    player_level_offset = reader.tell()
    player_level = reader.u32()
    player_location_offset, player_location_capacity, player_location = reader.wstring_with_metadata()
    game_date_offset, game_date_capacity, game_date = reader.wstring_with_metadata()
    player_race_offset, player_race_capacity, player_race = reader.wstring_with_metadata()
    player_sex_offset = reader.tell()
    player_sex = reader.u16()
    player_current_exp_offset = reader.tell()
    player_current_exp = reader.f32()
    player_needed_exp_offset = reader.tell()
    player_needed_exp = reader.f32()
    filetime_raw = reader.read(8)
    screenshot_width = reader.u32()
    screenshot_height = reader.u32()

    compression_type: int | None = None
    if reader.tell() + 2 <= header_end:
        compression_type = reader.u16()
    if reader.tell() != header_end:
        warnings.append(
            f"Header parser stopped at 0x{reader.tell():X}, header ends at 0x{header_end:X}; seeking to header end."
        )
        reader.seek(header_end)

    payload, screenshot_bpp, screenshot_size = _read_payload(data, header_end, screenshot_width, screenshot_height, compression_type, warnings)

    plugin_info: PluginInfo | None = None
    flt: FileLocationTable | None = None
    global_entries: list[GlobalDataEntry] = []
    change_forms_preview: list[ChangeFormEntry] = []

    if payload:
        plugin_info, next_idx = _try_read_plugin_info(payload, warnings)
        flt = _try_read_file_location_table(payload, next_idx, warnings)
        if flt:
            global_entries = _try_read_global_data_entries(payload, flt, warnings)
            change_forms_preview = _try_read_change_forms(payload, flt, warnings, preview_limit=change_form_preview_limit)

    header = SaveHeader(
        magic=magic.decode("ascii"),
        header_size=header_size,
        version=version,
        save_number=save_number,
        player_name=player_name,
        player_name_offset=player_name_offset,
        player_name_capacity=player_name_capacity,
        player_level=player_level,
        player_location=player_location,
        player_location_offset=player_location_offset,
        player_location_capacity=player_location_capacity,
        game_date=game_date,
        game_date_offset=game_date_offset,
        game_date_capacity=game_date_capacity,
        player_race=player_race,
        player_race_offset=player_race_offset,
        player_race_capacity=player_race_capacity,
        player_sex=player_sex,
        player_current_exp=player_current_exp,
        player_needed_exp=player_needed_exp,
        filetime_raw_hex=filetime_raw.hex().upper(),
        screenshot_width=screenshot_width,
        screenshot_height=screenshot_height,
        compression_type=compression_type,
        header_start=header_start,
        header_end=header_end,
        player_level_offset=player_level_offset,
        player_sex_offset=player_sex_offset,
        player_current_exp_offset=player_current_exp_offset,
        player_needed_exp_offset=player_needed_exp_offset,
        screenshot_offset=header_end,
        screenshot_size=screenshot_size,
        screenshot_bpp=screenshot_bpp,
    )
    return EssDocument(
        path=path,
        header=header,
        payload=payload,
        plugin_info=plugin_info,
        file_location_table=flt,
        global_data_entries=global_entries,
        change_forms_preview=change_forms_preview,
        file_size=len(data),
        warnings=warnings,
    )


def _read_payload(data: bytes, screenshot_offset: int, width: int, height: int, compression_type: int | None, warnings: list[str]) -> tuple[SavePayload | None, int, int]:
    # Classic Skyrim screenshots are often RGB; SSE/AE saves with compression commonly use BGRA/RGBA.
    candidates = [4, 3] if compression_type in (1, 2) else [3, 4]
    last_error: Exception | None = None
    for bpp in candidates:
        screenshot_size = width * height * bpp
        payload_offset = screenshot_offset + screenshot_size
        if payload_offset >= len(data):
            continue
        try:
            payload = _decode_payload_at(data, payload_offset, compression_type, bpp)
            return payload, bpp, screenshot_size
        except Exception as exc:
            last_error = exc
            continue
    screenshot_size = width * height * (4 if compression_type in (1, 2) else 3)
    if last_error:
        warnings.append(f"Payload decode failed after screenshot: {last_error}")
    return None, (4 if compression_type in (1, 2) else 3), screenshot_size


def _decode_payload_at(data: bytes, payload_offset: int, compression_type: int | None, bpp: int) -> SavePayload:
    if compression_type == 2:
        if payload_offset + 8 > len(data):
            raise EssParseError("LZ4 payload header is truncated")
        uncompressed_size = struct.unpack_from("<I", data, payload_offset)[0]
        compressed_size = struct.unpack_from("<I", data, payload_offset + 4)[0]
        comp = data[payload_offset + 8:payload_offset + 8 + compressed_size]
        if len(comp) != compressed_size:
            raise EssParseError("LZ4 compressed block size points past end of file")
        try:
            import lz4.block  # type: ignore
        except Exception as exc:
            raise EssParseError("This save uses LZ4 compression. Install dependency: pip install lz4") from exc
        body = lz4.block.decompress(comp, uncompressed_size=uncompressed_size)
        if len(body) != uncompressed_size:
            raise EssParseError("LZ4 block decompressed to an unexpected size")
        return _payload_from_body(payload_offset, compression_type, bpp, body, compressed_size)
    if compression_type == 1:
        if payload_offset + 8 > len(data):
            raise EssParseError("zlib payload header is truncated")
        uncompressed_size = struct.unpack_from("<I", data, payload_offset)[0]
        compressed_size = struct.unpack_from("<I", data, payload_offset + 4)[0]
        comp = data[payload_offset + 8:payload_offset + 8 + compressed_size]
        import zlib
        body = zlib.decompress(comp)
        if uncompressed_size and len(body) != uncompressed_size:
            raise EssParseError("zlib block decompressed to an unexpected size")
        return _payload_from_body(payload_offset, compression_type, bpp, body, compressed_size)
    # Uncompressed payload starts with formVersion, then pluginInfoSize.
    body = data[payload_offset:]
    return _payload_from_body(payload_offset, compression_type or 0, bpp, body, None)


def _payload_from_body(virtual_offset: int, compression_type: int | None, bpp: int, body: bytes, compressed_size: int | None) -> SavePayload:
    form_version = body[0] if len(body) >= 1 else None
    plugin_info_size = struct.unpack_from("<I", body, 1)[0] if len(body) >= 5 else None
    return SavePayload(
        physical_offset=virtual_offset,
        virtual_offset=virtual_offset,
        compression_type=compression_type,
        screenshot_bpp=bpp,
        uncompressed_size=len(body),
        compressed_size=compressed_size,
        data=body,
        form_version=form_version,
        plugin_info_size=plugin_info_size,
    )


def _try_read_plugin_info(payload: SavePayload, warnings: list[str]) -> tuple[PluginInfo | None, int]:
    data = payload.data
    if len(data) < 5:
        warnings.append("Payload too short for plugin info.")
        return None, 0
    r = ByteReader(data, 0)
    try:
        _form_version = r.u8()
        plugin_info_size = r.u32()
        table_start = r.tell()
        table_end = table_start + plugin_info_size
        if table_end > len(data):
            raise EssParseError("PluginInfoSize points past uncompressed payload")
        count = r.u8()
        plugins = [r.wstring() for _ in range(count)]
        light_plugins: list[str] = []
        local_warnings: list[str] = []
        # SSE/AE pluginInfoSize may include a light-plugin block directly after main plugins.
        if r.tell() + 2 <= table_end:
            saved = r.tell()
            try:
                light_count = r.u16()
                lights = [r.wstring() for _ in range(light_count)]
                if r.tell() <= table_end:
                    light_plugins = lights
                else:
                    r.seek(saved)
            except Exception:
                r.seek(saved)
        if r.tell() != table_end:
            # Leave the table position at the official end; unknown plugin-info padding/data is preserved.
            local_warnings.append(f"Plugin info parser consumed 0x{r.tell():X}; official end is 0x{table_end:X}.")
        return PluginInfo(payload.virtual_offset + 1, plugin_info_size, plugins, light_plugins, local_warnings), table_end
    except Exception as exc:
        warnings.append(f"Plugin table parse skipped: {exc}")
        return None, 0


def _try_read_file_location_table(payload: SavePayload, body_index: int, warnings: list[str]) -> FileLocationTable | None:
    if body_index + (25 * 4) > len(payload.data):
        warnings.append("File location table is outside the uncompressed payload range.")
        return None
    r = ByteReader(payload.data, body_index)
    try:
        values = [r.u32() for _ in range(10)]
        _unused = [r.u32() for _ in range(15)]
        return FileLocationTable(
            offset=payload.virtual_offset + body_index,
            form_id_array_count_offset=values[0],
            unknown_table_3_offset=values[1],
            global_data_table_1_offset=values[2],
            global_data_table_2_offset=values[3],
            change_forms_offset=values[4],
            global_data_table_3_offset=values[5],
            global_data_table_1_count=values[6],
            global_data_table_2_count=values[7],
            global_data_table_3_count=values[8],
            change_form_count=values[9],
        )
    except Exception as exc:
        warnings.append(f"File location table parse skipped at body index 0x{body_index:X}: {exc}")
        return None


def _abs_to_body(payload: SavePayload, offset: int) -> int:
    return offset - payload.virtual_offset


def _try_read_global_data_entries(payload: SavePayload, flt: FileLocationTable, warnings: list[str]) -> list[GlobalDataEntry]:
    entries: list[GlobalDataEntry] = []
    tables = [
        (1, flt.global_data_table_1_offset, flt.global_data_table_1_count),
        (2, flt.global_data_table_2_offset, flt.global_data_table_2_count),
        (3, flt.global_data_table_3_offset, flt.global_data_table_3_count),
    ]
    for table_no, abs_offset, count in tables:
        pos = _abs_to_body(payload, abs_offset)
        if pos < 0 or pos >= len(payload.data):
            warnings.append(f"Global data table {table_no} offset 0x{abs_offset:X} is outside payload.")
            continue
        for i in range(count):
            if pos + 8 > len(payload.data):
                warnings.append(f"Global data table {table_no} entry {i} is truncated.")
                break
            typ = struct.unpack_from("<I", payload.data, pos)[0]
            length = struct.unpack_from("<I", payload.data, pos + 4)[0]
            data_start = pos + 8
            data_end = data_start + length
            if data_end > len(payload.data):
                warnings.append(f"Global data table {table_no} entry {i} length points past payload.")
                break
            sample = payload.data[data_start:data_start + 24].hex().upper()
            entries.append(GlobalDataEntry(table_no, i, payload.virtual_offset + pos, payload.virtual_offset + data_start, typ, length, sample))
            pos = data_end
    return entries


def _try_read_change_forms(payload: SavePayload, flt: FileLocationTable, warnings: list[str], *, preview_limit: int = 500) -> list[ChangeFormEntry]:
    entries: list[ChangeFormEntry] = []
    pos = _abs_to_body(payload, flt.change_forms_offset)
    if pos < 0 or pos >= len(payload.data):
        warnings.append("Change forms offset is outside payload.")
        return entries
    count = min(flt.change_form_count, preview_limit)
    for i in range(count):
        try:
            entry, pos = _read_change_form_at(payload, pos, i)
        except Exception as exc:
            warnings.append(f"Change form preview stopped at index {i}: {exc}")
            break
        entries.append(entry)
    if flt.change_form_count > preview_limit:
        warnings.append(f"Change form preview limited to {preview_limit:,} of {flt.change_form_count:,} records.")
    return entries


def iter_change_forms(payload: SavePayload, flt: FileLocationTable) -> Iterable[ChangeFormEntry]:
    pos = _abs_to_body(payload, flt.change_forms_offset)
    for i in range(flt.change_form_count):
        entry, pos = _read_change_form_at(payload, pos, i)
        yield entry


def _read_change_form_at(payload: SavePayload, pos: int, index: int) -> tuple[ChangeFormEntry, int]:
    data = payload.data
    if pos + 11 > len(data):
        raise EssParseError("truncated change form header")
    start = pos
    ref = data[pos:pos + 3]
    pos += 3
    change_flags = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    type_byte = data[pos]
    pos += 1
    lengths_size = (type_byte >> 6) & 0x03
    form_type = type_byte & 0x3F
    version = data[pos]
    pos += 1
    if lengths_size == 0:
        length1 = data[pos]
        length2 = data[pos + 1]
        pos += 2
    elif lengths_size == 1:
        length1 = struct.unpack_from("<H", data, pos)[0]
        length2 = struct.unpack_from("<H", data, pos + 2)[0]
        pos += 4
    elif lengths_size == 2:
        length1 = struct.unpack_from("<I", data, pos)[0]
        length2 = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
    else:
        raise EssParseError("unsupported change-form length-size value 3")
    data_start = pos
    data_end = pos + length1
    if data_end > len(data):
        raise EssParseError("change-form data length points past payload")
    ref_type, ref_value = decode_refid(ref)
    sample = data[data_start:data_start + 24].hex().upper()
    entry = ChangeFormEntry(
        index=index,
        offset=payload.virtual_offset + start,
        refid_hex=ref.hex().upper(),
        ref_type=ref_type,
        ref_value=ref_value,
        form_id_guess=refid_to_form_id_guess(ref),
        change_flags=change_flags,
        form_type=form_type,
        lengths_size=lengths_size,
        version=version,
        length1=length1,
        length2=length2,
        data_offset=payload.virtual_offset + data_start,
        data_end_offset=payload.virtual_offset + data_end,
        sample_hex=sample,
    )
    return entry, data_end


def decode_refid(ref: bytes) -> tuple[int, int]:
    if len(ref) != 3:
        raise ValueError("RefID must be 3 bytes")
    b0, b1, b2 = ref
    ref_type = (b0 >> 6) & 0x03
    value = ((b0 & 0x3F) << 16) | (b1 << 8) | b2
    return ref_type, value


def encode_default_refid(form_id: int) -> bytes:
    value = form_id & 0x3FFFFF
    return bytes([0x40 | ((value >> 16) & 0x3F), (value >> 8) & 0xFF, value & 0xFF])


def refid_to_form_id_guess(ref: bytes) -> str:
    ref_type, value = decode_refid(ref)
    if ref_type == 1:
        return f"{value:08X}"
    if ref_type == 2:
        return f"FF{value:06X}"[-8:]
    if ref_type == 0:
        return f"formIDArray[{value}]"
    return f"unknown:{value:06X}"


def patch_header_values(
    source: str | Path,
    target: str | Path,
    *,
    player_name: str | None = None,
    player_level: int | None = None,
    player_sex: int | None = None,
    player_race: str | None = None,
    current_exp: float | None = None,
    needed_exp: float | None = None,
) -> EssDocument:
    """Patch fixed-width header values only. Strings are written inside their existing byte slots."""
    doc = read_ess(source)
    data = bytearray(Path(source).read_bytes())
    h = doc.header
    if player_name is not None:
        encoded = player_name.encode("utf-8")
        if len(encoded) > h.player_name_capacity:
            raise ValueError(
                f"Player name is {len(encoded)} UTF-8 bytes, but this save has a fixed {h.player_name_capacity}-byte name slot."
            )
        # Skyrim header strings are length-prefixed and changing the length would move every
        # downstream header field. Keep the original length/capacity stable, but overwrite
        # the fixed byte slot and NUL-pad shorter names. read_ess strips those trailing NULs.
        struct.pack_into("<H", data, h.player_name_offset, h.player_name_capacity)
        data[h.player_name_offset + 2:h.player_name_offset + 2 + h.player_name_capacity] = encoded.ljust(h.player_name_capacity, b"\x00")
    if player_level is not None:
        if not 1 <= player_level <= 65535:
            raise ValueError("Player level must be between 1 and 65535")
        struct.pack_into("<I", data, h.player_level_offset, int(player_level))
    if player_sex is not None:
        if player_sex not in (0, 1):
            raise ValueError("Player sex must be 0 male or 1 female")
        struct.pack_into("<H", data, h.player_sex_offset, int(player_sex))
    if player_race is not None:
        race_text = str(player_race).strip()
        encoded = race_text.encode("utf-8")
        if len(encoded) > h.player_race_capacity:
            raise ValueError(
                f"Player race text is {len(encoded)} UTF-8 bytes, but this save has a fixed {h.player_race_capacity}-byte race slot."
            )
        struct.pack_into("<H", data, h.player_race_offset, h.player_race_capacity)
        data[h.player_race_offset + 2:h.player_race_offset + 2 + h.player_race_capacity] = encoded.ljust(h.player_race_capacity, b"\x00")
    if current_exp is not None:
        struct.pack_into("<f", data, h.player_current_exp_offset, float(current_exp))
    if needed_exp is not None:
        struct.pack_into("<f", data, h.player_needed_exp_offset, float(needed_exp))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return read_ess(target)


def rebuild_save_with_payload(source: str | Path, target: str | Path, new_payload: bytes) -> EssDocument:
    doc = read_ess(source)
    if not doc.payload:
        raise EssParseError("Save payload was not decoded; cannot rebuild save.")
    raw = Path(source).read_bytes()
    p = doc.payload
    if len(new_payload) != p.uncompressed_size:
        raise ValueError("This rebuild helper currently preserves payload size only.")
    prefix = raw[:p.physical_offset]
    if p.compression_type == 2:
        try:
            import lz4.block  # type: ignore
        except Exception as exc:
            raise EssParseError("Install dependency first: pip install lz4") from exc
        comp = lz4.block.compress(bytes(new_payload), store_size=False)
        out = prefix + struct.pack("<II", len(new_payload), len(comp)) + comp
    elif p.compression_type == 1:
        import zlib
        comp = zlib.compress(bytes(new_payload))
        out = prefix + struct.pack("<II", len(new_payload), len(comp)) + comp
    elif p.compression_type in (None, 0):
        out = prefix + bytes(new_payload)
    else:
        raise EssParseError(f"Unsupported payload compression type: {p.compression_type}")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    return read_ess(target)


def scan_form_id(path: str | Path, form_id: str) -> list[int]:
    """Backward-compatible raw scan: returns physical offsets for 32-bit endian patterns."""
    raw = Path(path).read_bytes()
    clean = _clean_hex(form_id)
    value = int(clean, 16)
    be = value.to_bytes(4, "big")
    le = value.to_bytes(4, "little")
    hits = set(_find_all(raw, be) + _find_all(raw, le))
    return sorted(hits)


def scan_form_id_detailed(path: str | Path, form_id: str) -> list[ScanHit]:
    raw = Path(path).read_bytes()
    doc = read_ess(path, change_form_preview_limit=0)
    clean = _clean_hex(form_id)
    value = int(clean, 16)
    patterns: list[tuple[str, bytes]] = [
        ("u32 big-endian", value.to_bytes(4, "big")),
        ("u32 little-endian", value.to_bytes(4, "little")),
        ("default RefID u24", encode_default_refid(value)),
    ]
    hits: list[ScanHit] = []
    for name, needle in patterns:
        for off in _find_all(raw, needle):
            hits.append(ScanHit("raw file", off, None, name))
    if doc.payload:
        for name, needle in patterns:
            for idx in _find_all(doc.payload.data, needle):
                hits.append(ScanHit("decompressed payload", idx, doc.payload.virtual_offset + idx, name))
    hits.sort(key=lambda h: (h.area, h.virtual_offset if h.virtual_offset is not None else h.offset, h.pattern))
    return hits


def _clean_hex(form_id: str) -> str:
    clean = form_id.strip().replace("0x", "").replace("0X", "").replace(" ", "")
    if len(clean) > 8:
        clean = clean[-8:]
    if not clean:
        raise ValueError("Form ID cannot be blank")
    int(clean, 16)
    return clean.zfill(8)


def _find_all(data: bytes, needle: bytes) -> list[int]:
    hits: list[int] = []
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx < 0:
            return hits
        hits.append(idx)
        start = idx + 1
