from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from app.core.form_id_tools import normalize_id
from app.core.id_database import IdRecord
from app.core.learned_magic import LearnedMagicList, detect_learned_magic_list
from app.core.player_payload import load_player_data, rebuild_save_with_player_data
from app.core.skyrim_ess import EssParseError, encode_default_refid


_HEX8 = re.compile(r"^[0-9A-F]{8}$")


@dataclass(slots=True)
class MagicLearnedPatchPlan:
    source: Path
    target: Path | None
    learned_list: LearnedMagicList
    added: list[str]
    removed: list[str]
    already_present: list[str]
    not_present: list[str]
    invalid: list[str]
    count_before: int
    count_after: int
    warnings: list[str]

    def has_changes(self) -> bool:
        return bool(self.added or self.removed)

    def to_text(self) -> str:
        lines = [
            "Direct learned-magic patch plan",
            f"Source: {self.source}",
        ]
        if self.target is not None:
            lines.append(f"Target: {self.target}")
        lines.extend([
            self.learned_list.to_text(),
            f"Count: {self.count_before} -> {self.count_after}",
        ])
        if self.added:
            lines.append("Add/unlock in learned list:")
            lines.extend(f"- {x}" for x in self.added)
        if self.removed:
            lines.append("Remove/lock from learned list:")
            lines.extend(f"- {x}" for x in self.removed)
        if self.already_present:
            lines.append("Already present / skipped add:")
            lines.extend(f"- {x}" for x in self.already_present)
        if self.not_present:
            lines.append("Not present / skipped remove:")
            lines.extend(f"- {x}" for x in self.not_present)
        if self.invalid:
            lines.append("Invalid or unsupported direct IDs:")
            lines.extend(f"- {x}" for x in self.invalid)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {x}" for x in self.warnings)
        if not self.has_changes():
            lines.append("No direct learned-list changes are needed.")
        return "\n".join(lines)


def encoded_refid_for_form_id(form_id: str) -> str:
    norm = normalize_id(form_id)
    if norm.startswith("XX"):
        raise ValueError(f"{form_id} still has an unresolved XX load-order prefix.")
    if norm.startswith("FE"):
        raise ValueError(f"{form_id} is an FE/light-plugin FormID; compact light-plugin magic writes are not enabled yet.")
    if not _HEX8.fullmatch(norm):
        raise ValueError(f"{form_id} is not an 8-hex FormID.")
    return encode_default_refid(int(norm, 16)).hex().upper()


def _known_encoded_refs(records: list[IdRecord], plugins: list[str]) -> set[str]:
    try:
        from app.core.magic_lab import magic_records_from_database
        return {rec.encoded_refid_hex for rec in magic_records_from_database(records, plugins)}
    except Exception:
        return set()


def _build_magic_learned_patch(
    source: str | Path,
    records: list[IdRecord],
    unlock_form_ids: list[str],
    lock_form_ids: list[str],
    *,
    allow_lock: bool = False,
) -> tuple[MagicLearnedPatchPlan, bytes]:
    source_path = Path(source)
    ctx = load_player_data(source_path)
    plugins = ctx.doc.plugin_info.plugins if ctx.doc.plugin_info else []
    learned = detect_learned_magic_list(ctx.player_data, _known_encoded_refs(records, plugins))
    if learned is None:
        raise EssParseError("Could not locate the player learned-magic list in ChangeForm 400014.")
    if learned.confidence == "low":
        raise EssParseError("Learned-magic list confidence is low; direct write refused.")

    warnings: list[str] = []
    entries = [bytes.fromhex(entry) for entry in learned.entries]
    entry_set = {entry.hex().upper() for entry in entries}
    added: list[str] = []
    removed: list[str] = []
    already_present: list[str] = []
    not_present: list[str] = []
    invalid: list[str] = []

    # Normalize removals first, then additions, so a user can flip a row back and
    # forth without creating duplicates. Experimental direct copy is intentionally
    # add/unlock-only by default; removals are better tested through the in-game
    # console script because Skyrim can reapply race/quest/stone abilities.
    if lock_form_ids and not allow_lock:
        warnings.append("Direct magic removal is disabled in experimental copy mode; unchecked spell/power/ability boxes are skipped. Use the console script if you need removal testing.")
    for raw_id in (lock_form_ids if allow_lock else []):
        try:
            encoded = encoded_refid_for_form_id(raw_id)
        except Exception as exc:
            invalid.append(f"{raw_id}: {exc}")
            continue
        if encoded in entry_set:
            entries = [entry for entry in entries if entry.hex().upper() != encoded]
            entry_set.discard(encoded)
            removed.append(f"{normalize_id(raw_id)} ({encoded})")
        else:
            not_present.append(f"{normalize_id(raw_id)} ({encoded})")

    for raw_id in unlock_form_ids:
        try:
            encoded = encoded_refid_for_form_id(raw_id)
        except Exception as exc:
            invalid.append(f"{raw_id}: {exc}")
            continue
        if encoded in entry_set:
            already_present.append(f"{normalize_id(raw_id)} ({encoded})")
            continue
        entries.append(bytes.fromhex(encoded))
        entry_set.add(encoded)
        added.append(f"{normalize_id(raw_id)} ({encoded})")

    new_count = len(entries)
    new_list = b"".join(entries)
    new_player = bytearray(ctx.player_data)
    new_player[learned.count_offset:learned.count_offset + 4] = new_count.to_bytes(4, "little", signed=False)
    new_player[learned.start_offset:learned.end_offset] = new_list

    if learned.count != len(learned.entries):
        warnings.append("Detected list count did not match parsed entry count; patch rebuilt the list from parsed entries.")
    if any("FE/light-plugin" in item for item in invalid):
        warnings.append("Light-plugin/ESL magic IDs are intentionally skipped until compact FE RefID writes are mapped.")
    if any("XX" in item for item in invalid):
        warnings.append("Resolve XX IDs by loading a save with the correct plugin list before direct writing.")

    plan = MagicLearnedPatchPlan(
        source=source_path,
        target=None,
        learned_list=learned,
        added=added,
        removed=removed,
        already_present=already_present,
        not_present=not_present,
        invalid=invalid,
        count_before=learned.count,
        count_after=new_count,
        warnings=warnings,
    )
    return plan, bytes(new_player)


def build_magic_learned_patch_plan(
    source: str | Path,
    records: list[IdRecord],
    unlock_form_ids: list[str],
    lock_form_ids: list[str],
    *,
    allow_lock: bool = False,
) -> MagicLearnedPatchPlan:
    plan, _new_player = _build_magic_learned_patch(source, records, unlock_form_ids, lock_form_ids, allow_lock=allow_lock)
    return plan


def apply_magic_learned_patch(
    source: str | Path,
    target: str | Path,
    records: list[IdRecord],
    unlock_form_ids: list[str],
    lock_form_ids: list[str],
    *,
    allow_lock: bool = False,
) -> MagicLearnedPatchPlan:
    plan, new_player = _build_magic_learned_patch(source, records, unlock_form_ids, lock_form_ids, allow_lock=allow_lock)
    target_path = Path(target)
    rebuild_save_with_player_data(source, target_path, new_player)
    return MagicLearnedPatchPlan(
        source=plan.source,
        target=target_path,
        learned_list=plan.learned_list,
        added=plan.added,
        removed=plan.removed,
        already_present=plan.already_present,
        not_present=plan.not_present,
        invalid=plan.invalid,
        count_before=plan.count_before,
        count_after=plan.count_after,
        warnings=plan.warnings,
    )
