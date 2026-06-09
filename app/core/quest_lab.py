from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import csv
import io
import struct
from typing import Any

from app.core.skyrim_ess import (
    EssDocument,
    GlobalDataEntry,
    iter_change_forms,
    read_ess,
)

QUEST_CHANGE_FORM_TYPE = 8  # UESP ChangeForm lower 6-bit type: QUST
QUEST_STATIC_GLOBAL_TYPE = 107


@dataclass(slots=True)
class QuestStageProbe:
    offset: int
    count: int
    stages: list[int]
    statuses: list[int]

    def summary(self, limit: int = 16) -> str:
        pairs = [f"{stage}:{status}" for stage, status in zip(self.stages[:limit], self.statuses[:limit])]
        suffix = " …" if len(self.stages) > limit else ""
        return ", ".join(pairs) + suffix


@dataclass(slots=True)
class QuestRecord:
    index: int
    form_id: str
    refid_hex: str
    change_flags: int
    version: int
    lengths_size: int
    length1: int
    length2: int
    data_offset: int
    data_end_offset: int
    payload_offset: int
    sample_hex: str
    first_byte: int | None
    stage_probe_offset: int | None
    stage_probe_count: int
    stage_probe_summary: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["change_flags_hex"] = f"0x{self.change_flags:08X}"
        return d


def _payload_bounds(doc: EssDocument, abs_offset: int, abs_end: int) -> tuple[int, int]:
    if not doc.payload:
        return abs_offset, abs_end
    return abs_offset - doc.payload.virtual_offset, abs_end - doc.payload.virtual_offset


def _slice_changeform_data(doc: EssDocument, data_offset: int, data_end_offset: int) -> bytes:
    if not doc.payload:
        return b""
    start, end = _payload_bounds(doc, data_offset, data_end_offset)
    if start < 0 or end < start or end > len(doc.payload.data):
        return b""
    return doc.payload.data[start:end]


def _best_stage_triplet_probe(data: bytes) -> QuestStageProbe | None:
    """Find the most likely quest-stage triplet run inside a QUST payload.

    Skyrim quest ChangeForms commonly contain compact stage rows.  We do not
    claim these bytes are fully decoded yet; this probe looks for stable
    repeated rows shaped like: uint16 stage + uint8 status, with stage IDs in
    a normal quest-stage range and a small status byte.  It gives us a useful
    readable starting point without making structural edits.
    """
    best: QuestStageProbe | None = None
    max_scan_start = min(len(data), 48)
    for start in range(max_scan_start):
        stages: list[int] = []
        statuses: list[int] = []
        pos = start
        last_stage = -1
        while pos + 3 <= len(data):
            stage = struct.unpack_from("<H", data, pos)[0]
            status = data[pos + 2]
            if stage > 3000 or status > 4:
                break
            # Long useful runs tend to be mostly ascending.  Allow a restart at
            # zero, but stop once an obvious non-stage value appears.
            if stages and stage < last_stage and stage != 0:
                break
            stages.append(stage)
            statuses.append(status)
            last_stage = stage
            pos += 3
        positive_unique = {stage for stage in stages if stage > 0}
        if len(stages) >= 3 and len(positive_unique) >= 3:
            probe = QuestStageProbe(start, len(stages), stages, statuses)
            if best is None or probe.count > best.count:
                best = probe
    return best


def _small_u16s(data: bytes, limit: int = 24) -> list[int]:
    out: list[int] = []
    for pos in range(0, min(len(data) - 1, 160), 2):
        val = struct.unpack_from("<H", data, pos)[0]
        if 0 <= val <= 3000:
            out.append(val)
            if len(out) >= limit:
                break
    return out


def _quest_notes(data: bytes, probe: QuestStageProbe | None) -> str:
    notes: list[str] = []
    if not data:
        return "No quest payload bytes available."
    notes.append(f"first byte 0x{data[0]:02X}")
    if probe:
        notes.append(f"stage-like run at +0x{probe.offset:X}: {probe.count} triplet(s)")
    smalls = _small_u16s(data)
    if smalls:
        notes.append("small u16 candidates: " + ", ".join(str(v) for v in smalls[:12]))
    return "; ".join(notes)


def read_quest_records(path: str | Path, *, limit: int | None = None) -> tuple[EssDocument, list[QuestRecord], GlobalDataEntry | None]:
    doc = read_ess(path, change_form_preview_limit=0)
    if not doc.payload or not doc.file_location_table:
        return doc, [], None

    quest_static = next((g for g in doc.global_data_entries if g.type == QUEST_STATIC_GLOBAL_TYPE), None)
    records: list[QuestRecord] = []
    for entry in iter_change_forms(doc.payload, doc.file_location_table):
        if entry.form_type != QUEST_CHANGE_FORM_TYPE:
            continue
        data = _slice_changeform_data(doc, entry.data_offset, entry.data_end_offset)
        probe = _best_stage_triplet_probe(data)
        payload_offset = entry.data_offset - doc.payload.virtual_offset
        records.append(
            QuestRecord(
                index=entry.index,
                form_id=entry.form_id_guess,
                refid_hex=entry.refid_hex,
                change_flags=entry.change_flags,
                version=entry.version,
                lengths_size=entry.lengths_size,
                length1=entry.length1,
                length2=entry.length2,
                data_offset=entry.data_offset,
                data_end_offset=entry.data_end_offset,
                payload_offset=payload_offset,
                sample_hex=data[:96].hex(" ").upper(),
                first_byte=data[0] if data else None,
                stage_probe_offset=probe.offset if probe else None,
                stage_probe_count=probe.count if probe else 0,
                stage_probe_summary=probe.summary() if probe else "",
                notes=_quest_notes(data, probe),
            )
        )
        if limit is not None and len(records) >= limit:
            break
    return doc, records, quest_static


def quest_records_to_csv(records: list[QuestRecord]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "index", "form_id", "refid_hex", "change_flags", "version", "length1", "length2",
        "data_offset", "payload_offset", "first_byte", "stage_probe_offset", "stage_probe_count",
        "stage_probe_summary", "notes", "sample_hex",
    ])
    for r in records:
        writer.writerow([
            r.index,
            r.form_id,
            r.refid_hex,
            f"0x{r.change_flags:08X}",
            r.version,
            r.length1,
            r.length2,
            f"0x{r.data_offset:X}",
            f"0x{r.payload_offset:X}",
            "" if r.first_byte is None else f"0x{r.first_byte:02X}",
            "" if r.stage_probe_offset is None else f"0x{r.stage_probe_offset:X}",
            r.stage_probe_count,
            r.stage_probe_summary,
            r.notes,
            r.sample_hex,
        ])
    return output.getvalue()


def quest_static_summary(doc: EssDocument, static_entry: GlobalDataEntry | None) -> str:
    if not doc.payload or not static_entry:
        return "Quest Static Data (Global Data type 107) was not found in this save."
    start = static_entry.data_offset - doc.payload.virtual_offset
    end = start + static_entry.length
    data = doc.payload.data[start:end] if 0 <= start <= end <= len(doc.payload.data) else b""
    return (
        "Quest Static Data / Global Data type 107\n"
        f"Table: {static_entry.table}, entry index: {static_entry.index}\n"
        f"Payload offset: 0x{start:X}, virtual/data offset: 0x{static_entry.data_offset:X}\n"
        f"Length: {static_entry.length:,} byte(s)\n"
        f"First 128 bytes:\n{data[:128].hex(' ').upper()}\n\n"
        "Status: read-only research. This table is useful for quest-system state, but it is not safe to edit until each substructure is decoded."
    )
