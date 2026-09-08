"""Read-only perk-layout diagnostics; no ESS writes are enabled here.

Run: python -m app.core.perk_research before.ess [after.ess]
The ranked/ref-only arrays below are observed candidates, not a complete
documented player-record parser. Do not use these offsets to write saves.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from app.core.id_database import IdDatabase
from app.core.inventory_lab import _read_form_id_array, decode_vsval_at
from app.core.player_payload import load_player_data
from app.core.preset_patcher import build_skyrim_preset_patch_plan
from app.core.perk_points import read_perk_points
from app.core.resources import resource_path
from app.core.skyrim_ess import decode_refid


@dataclass(frozen=True)
class PerkArrayCandidate:
    count_offset: int
    end_offset: int
    ranked_entries: tuple[tuple[str, int], ...]
    companion_refs: tuple[str, ...]


def find_perk_array_candidates(data: bytes, known_refs: set[str]) -> list[PerkArrayCandidate]:
    """Find bounded, unique RefID/rank arrays followed by a RefID subset.

    Require a known perk in both arrays. This deliberately cannot identify an
    empty skill-perk list just from a coincidental binary pattern. Returned
    candidates still require controlled in-game validation.
    """
    candidates = []
    known_refs = {ref.upper() for ref in known_refs}
    for offset in range(max(0, len(data) - 8)):
        try:
            count, size = decode_vsval_at(data, offset)
            if not 1 <= count <= 1024:
                continue
            start = offset + size
            end = start + count * 4
            if end >= len(data):
                continue
            ranked = tuple((data[pos:pos + 3].hex().upper(), data[pos + 3])
                           for pos in range(start, end, 4))
            refs = {ref for ref, _ in ranked}
            if len(refs) != count or not refs.intersection(known_refs):
                continue
            if any(not 1 <= rank <= 5 or int(ref, 16) >> 22 > 1
                   for ref, rank in ranked):
                continue
            other_count, other_size = decode_vsval_at(data, end)
            if not 1 <= other_count <= count:
                continue
            other_start = end + other_size
            other_end = other_start + other_count * 3
            if other_end > len(data):
                continue
            companion = tuple(data[pos:pos + 3].hex().upper()
                              for pos in range(other_start, other_end, 3))
            other_refs = set(companion)
            if (len(other_refs) != other_count or not other_refs <= refs
                    or not other_refs.intersection(known_refs)):
                continue
            candidates.append(PerkArrayCandidate(offset, other_end, ranked, companion))
        except ValueError:
            continue
    return candidates


def inspect_perks(source: str | Path) -> dict:
    ctx = load_player_data(source)
    db = IdDatabase()
    db.load_csv(resource_path("database", "skyrim_ids_sample.csv"))
    names = {r.form_id.upper(): r.name for r in db.records if r.category == "Perks"}
    array = _read_form_id_array(ctx.doc)
    known_refs = {f"{0x400000 | int(fid, 16):06X}" for fid in names
                  if fid.startswith("00") and int(fid, 16) < 0x400000}
    known_refs.update(f"{i:06X}" for i, fid in enumerate(array)
                      if i < 0x400000 and f"{fid:08X}" in names)

    def describe(ref: str, rank: int) -> dict:
        kind, value = decode_refid(bytes.fromhex(ref))
        fid = value if kind == 1 else array[value] if kind == 0 and value < len(array) else None
        form_id = f"{fid:08X}" if fid is not None else None
        return {"refid": ref, "form_id": form_id, "rank": rank,
                "database_name": names.get(form_id)}

    candidates = []
    for candidate in find_perk_array_candidates(ctx.player_data, known_refs):
        entry = asdict(candidate)
        entry["entries"] = [describe(ref, rank) for ref, rank in candidate.ranked_entries]
        candidates.append(entry)
    report = {
        "source": str(Path(source)), "player": ctx.doc.header.player_name,
        "level": ctx.doc.header.player_level, "player_record_size": len(ctx.player_data),
        "change_flags": f"{ctx.change_form.change_flags:08X}",
        "status": "Research only: candidates do not authorize save writes.",
        "perk_points": None,
        "points_status": "Unsupported layout; point count unavailable.",
        "candidates": candidates,
    }
    try:
        field = read_perk_points(source)
        report["perk_points"] = field.value
        report["points_offset"] = field.offset
        report["points_status"] = "Observed SE v78 layout; copy editing available, in-game reload pending."
    except Exception as exc:
        report["points_status"] = str(exc)
    try:
        plan, _ = build_skyrim_preset_patch_plan(source, "perk_points", 10)
        report["guarded_point_preview_only"] = plan.to_text()
    except Exception as exc:
        report["point_preview_error"] = str(exc)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("saves", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([inspect_perks(source) for source in args.saves], indent=2))


if __name__ == "__main__":
    main()
