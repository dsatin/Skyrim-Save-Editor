from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import re

from app.core.form_id_tools import normalize_id
from app.core.id_database import IdRecord
from app.core.player_payload import rebuild_save_with_payload_variable
from app.core.skyrim_ess import EssParseError, encode_default_refid, iter_change_forms, read_ess

_HEX8 = re.compile(r"^[0-9A-F]{8}$")
SHOUT_WORD_FORM_TYPE = 34
SHOUT_WORD_CHANGE_FLAGS = 1
SHOUT_WORD_VERSION = 0x4E
SHOUT_WORD_DATA_PREFIX = b"\x49\x00"
SHOUT_WORD_DATA_SUFFIX = b"\x00\x00\x00"


@dataclass(slots=True)
class ShoutWordPatchPlan:
    source: Path
    target: Path | None
    unlocked: list[str]
    locked: list[str]
    inserted: list[str]
    already_unlocked: list[str]
    already_locked: list[str]
    not_present: list[str]
    invalid: list[str]
    count_before: int
    count_after: int
    warnings: list[str]

    def has_changes(self) -> bool:
        return bool(self.unlocked or self.locked or self.inserted)

    def to_text(self) -> str:
        lines = [
            "Direct shout-word patch plan",
            f"Source: {self.source}",
        ]
        if self.target is not None:
            lines.append(f"Target: {self.target}")
        lines.append(f"ChangeForm count: {self.count_before:,} -> {self.count_after:,}")
        if self.unlocked:
            lines.append("Set existing word(s) unlocked:")
            lines.extend(f"- {x}" for x in self.unlocked)
        if self.inserted:
            lines.append("Insert new unlocked word ChangeForm(s):")
            lines.extend(f"- {x}" for x in self.inserted)
        if self.locked:
            lines.append("Set existing word(s) locked:")
            lines.extend(f"- {x}" for x in self.locked)
        if self.already_unlocked:
            lines.append("Already unlocked / skipped:")
            lines.extend(f"- {x}" for x in self.already_unlocked)
        if self.already_locked:
            lines.append("Already locked / skipped:")
            lines.extend(f"- {x}" for x in self.already_locked)
        if self.not_present:
            lines.append("Not present / skipped direct write:")
            lines.extend(f"- {x}" for x in self.not_present)
        if self.invalid:
            lines.append("Invalid or unsupported shout IDs:")
            lines.extend(f"- {x}" for x in self.invalid)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {x}" for x in self.warnings)
        if not self.has_changes():
            lines.append("No direct shout-word changes are needed.")
        return "\n".join(lines)


def encoded_refid_for_shout_word(form_id: str) -> str:
    norm = normalize_id(form_id)
    if norm.startswith("XX"):
        raise ValueError(f"{form_id} still has an unresolved XX load-order prefix.")
    if norm.startswith("FE"):
        raise ValueError(f"{form_id} is an FE/light-plugin FormID; shout-word writes are not enabled for light plugins yet.")
    if not _HEX8.fullmatch(norm):
        raise ValueError(f"{form_id} is not an 8-hex FormID.")
    return encode_default_refid(int(norm, 16)).hex().upper()



def _missing_shout_insert_rel(entries, payload_virtual_offset: int, default_insert_rel: int) -> int:
    """Return the safest payload-relative insertion point for missing Word records.

    Real PC saves with full shout progress place Word-of-Power ChangeForms in the
    static/default-ref ChangeForm region, immediately after any already-known
    Word records and before the first high 0x80xxxx temporary/dynamic reference.
    The earlier experimental build appended synthetic Word records at the end of
    the ChangeForm section; our parser could see them, but Skyrim did not treat
    them like normally learned wall words.  Insert beside the existing static word
    records so the on-disk order matches observed working PC saves.
    """
    word_entries = [
        entry for entry in entries
        if entry.form_type == SHOUT_WORD_FORM_TYPE and entry.change_flags == SHOUT_WORD_CHANGE_FLAGS
    ]
    if word_entries:
        last_word = max(word_entries, key=lambda entry: entry.data_end_offset)
        return last_word.data_end_offset - payload_virtual_offset

    # Fallback for extremely early saves with no known shout words yet.  Put new
    # static default-ref records before the first 0x80xxxx temporary reference.
    # If that boundary is unavailable, fall back to the old end-of-changeforms
    # location rather than guessing inside unrelated data.
    for entry in entries:
        if entry.refid_hex.upper().startswith("80"):
            return entry.offset - payload_virtual_offset
    return default_insert_rel

def _word_label(form_id: str, encoded: str) -> str:
    return f"{normalize_id(form_id)} ({encoded})"


def _word_changeform_bytes(encoded_hex: str, unlocked: bool = True) -> bytes:
    data = bytearray(SHOUT_WORD_DATA_PREFIX + (b"\x01" if unlocked else b"\x00") + SHOUT_WORD_DATA_SUFFIX)
    return (
        bytes.fromhex(encoded_hex)
        + struct.pack("<I", SHOUT_WORD_CHANGE_FLAGS)
        + bytes([SHOUT_WORD_FORM_TYPE, SHOUT_WORD_VERSION, len(data), 0])
        + bytes(data)
    )


def _build_shout_word_patch(
    source: str | Path,
    unlock_word_ids: list[str],
    lock_word_ids: list[str],
    *,
    allow_insert_missing: bool = False,
    allow_lock: bool = False,
) -> tuple[ShoutWordPatchPlan, bytes]:
    source_path = Path(source)
    doc = read_ess(source_path, change_form_preview_limit=0)
    if not doc.payload or not doc.file_location_table:
        raise EssParseError("Save payload/change forms were not decoded.")

    body = bytearray(doc.payload.data)
    flt = doc.file_location_table
    payload = doc.payload
    table_rel = flt.offset - payload.virtual_offset
    default_insert_rel = flt.global_data_table_3_offset - payload.virtual_offset
    if table_rel < 0 or table_rel + 40 > len(body):
        raise EssParseError("File location table is outside the decoded payload.")
    if default_insert_rel < 0 or default_insert_rel > len(body):
        raise EssParseError("Global data table 3 offset is outside the decoded payload; cannot insert shout word records.")

    entries = list(iter_change_forms(payload, flt))
    by_ref = {entry.refid_hex.upper(): entry for entry in entries}
    unlocked: list[str] = []
    locked: list[str] = []
    inserted: list[str] = []
    already_unlocked: list[str] = []
    already_locked: list[str] = []
    not_present: list[str] = []
    invalid: list[str] = []
    warnings: list[str] = []
    insert_chunks: list[bytes] = []
    touched: set[str] = set()

    def data_for(entry) -> tuple[int, bytearray] | None:
        data_rel = entry.data_offset - payload.virtual_offset
        if data_rel < 0 or data_rel + entry.length1 > len(body):
            return None
        return data_rel, bytearray(body[data_rel:data_rel + entry.length1])

    if lock_word_ids and not allow_lock:
        warnings.append("Direct shout locking is disabled in experimental copy mode; unchecked shout boxes are skipped. Use the console script if you need lock/removal testing.")
    for raw_id in (lock_word_ids if allow_lock else []):
        try:
            encoded = encoded_refid_for_shout_word(raw_id)
        except Exception as exc:
            invalid.append(f"{raw_id}: {exc}")
            continue
        entry = by_ref.get(encoded)
        label = _word_label(raw_id, encoded)
        if entry is None:
            not_present.append(label)
            continue
        blob = data_for(entry)
        if blob is None or entry.length1 < 3:
            invalid.append(f"{label}: existing word ChangeForm has an unsupported data layout.")
            continue
        data_rel, data = blob
        if data[2] == 0:
            already_locked.append(label)
            continue
        body[data_rel + 2] = 0
        locked.append(label)
        touched.add(encoded)

    for raw_id in unlock_word_ids:
        try:
            encoded = encoded_refid_for_shout_word(raw_id)
        except Exception as exc:
            invalid.append(f"{raw_id}: {exc}")
            continue
        label = _word_label(raw_id, encoded)
        if encoded in touched:
            # The latest desired state wins; this avoids duplicate work when a row
            # is toggled repeatedly before Direct Apply.
            continue
        entry = by_ref.get(encoded)
        if entry is None:
            if allow_insert_missing:
                insert_chunks.append(_word_changeform_bytes(encoded, unlocked=True))
                inserted.append(label)
                by_ref[encoded] = None  # reserve against duplicate inserted rows
                touched.add(encoded)
                continue
            not_present.append(label)
            if not any("Missing shout words" in w for w in warnings):
                warnings.append("Missing shout words are not inserted by experimental direct copy because synthetic Word-of-Power ChangeForms corrupted saves. Use the generated console script for missing shouts.")
            continue
        blob = data_for(entry)
        if blob is None or entry.length1 < 3:
            invalid.append(f"{label}: existing word ChangeForm has an unsupported data layout.")
            continue
        data_rel, data = blob
        if data[2] != 0:
            already_unlocked.append(label)
            continue
        body[data_rel + 2] = 1
        unlocked.append(label)
        touched.add(encoded)

    count_before = flt.change_form_count
    count_after = count_before + len(insert_chunks)
    if insert_chunks:
        insert_chunks.sort()
        insertion = b"".join(insert_chunks)
        insert_rel = _missing_shout_insert_rel(entries, payload.virtual_offset, default_insert_rel)
        body[insert_rel:insert_rel] = insertion
        delta = len(insertion)
        insert_abs = payload.virtual_offset + insert_rel

        # FileLocationTable offsets are absolute offsets into the uncompressed
        # ESS/SAVEDATA payload. Move every known FileLocationTable offset that
        # lives after the insertion point.
        offset_fields = (
            (0, flt.form_id_array_count_offset),
            (1, flt.unknown_table_3_offset),
            (2, flt.global_data_table_1_offset),
            (3, flt.global_data_table_2_offset),
            (4, flt.change_forms_offset),
            (5, flt.global_data_table_3_offset),
        )
        moved_names = []
        field_names = {
            0: "form_id_array_count_offset",
            1: "unknown_table_3_offset",
            2: "global_data_table_1_offset",
            3: "global_data_table_2_offset",
            4: "change_forms_offset",
            5: "global_data_table_3_offset",
        }
        for field_index, old_offset in offset_fields:
            if old_offset and old_offset > insert_abs:
                struct.pack_into("<I", body, table_rel + field_index * 4, old_offset + delta)
                moved_names.append(field_names[field_index])

        struct.pack_into("<I", body, table_rel + 9 * 4, count_after)
        if moved_names:
            warnings.append("Updated downstream FileLocationTable offsets after shout insertion: " + ", ".join(moved_names) + ".")
        warnings.append("Inserted missing shout-word ChangeForms into the static shout-word area instead of appending them at the end. Keep the automatic backup until the save is confirmed in-game.")
    else:
        count_after = count_before

    plan = ShoutWordPatchPlan(
        source=source_path,
        target=None,
        unlocked=unlocked,
        locked=locked,
        inserted=inserted,
        already_unlocked=already_unlocked,
        already_locked=already_locked,
        not_present=not_present,
        invalid=invalid,
        count_before=count_before,
        count_after=count_after,
        warnings=warnings,
    )
    return plan, bytes(body)


def build_shout_word_patch_plan(
    source: str | Path,
    records: list[IdRecord],
    unlock_word_ids: list[str],
    lock_word_ids: list[str],
    *,
    allow_insert_missing: bool = False,
    allow_lock: bool = False,
) -> ShoutWordPatchPlan:
    # records is accepted to keep parity with the magic patcher and future name-rich plans.
    plan, _body = _build_shout_word_patch(
        source,
        unlock_word_ids,
        lock_word_ids,
        allow_insert_missing=allow_insert_missing,
        allow_lock=allow_lock,
    )
    return plan


def apply_shout_word_patch(
    source: str | Path,
    target: str | Path,
    records: list[IdRecord],
    unlock_word_ids: list[str],
    lock_word_ids: list[str],
    *,
    allow_insert_missing: bool = False,
    allow_lock: bool = False,
) -> ShoutWordPatchPlan:
    plan, body = _build_shout_word_patch(
        source,
        unlock_word_ids,
        lock_word_ids,
        allow_insert_missing=allow_insert_missing,
        allow_lock=allow_lock,
    )
    target_path = Path(target)
    rebuild_save_with_payload_variable(source, target_path, body)
    return ShoutWordPatchPlan(
        source=plan.source,
        target=target_path,
        unlocked=plan.unlocked,
        locked=plan.locked,
        inserted=plan.inserted,
        already_unlocked=plan.already_unlocked,
        already_locked=plan.already_locked,
        not_present=plan.not_present,
        invalid=plan.invalid,
        count_before=plan.count_before,
        count_after=plan.count_after,
        warnings=plan.warnings,
    )
