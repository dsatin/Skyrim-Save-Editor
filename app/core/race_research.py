from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import json
from typing import Any

from app.core.live_player import read_live_player_fields
from app.core.player_payload import load_player_data
from app.core.race_editor import SKYRIM_RACES, read_skyrim_race_mapping
from app.core.skyrim_ess import read_ess, iter_change_forms


def _safe_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _race_hits(data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for race in SKYRIM_RACES:
        encoded = race.encoded
        start = 0
        while True:
            off = data.find(encoded, start)
            if off < 0:
                break
            rows.append({
                "offset": off,
                "offset_hex": f"0x{off:X}",
                "race": race.display,
                "editor_id": race.editor_id,
                "form_id": race.form_id,
                "encoded": race.encoded_hex,
            })
            start = off + 1
    rows.sort(key=lambda row: int(row["offset"]))
    return rows



def _all_race_hits_with_context(doc, data: bytes) -> list[dict[str, Any]]:
    """Return every known race RefID hit in the decompressed payload with rough ownership.

    Some saves keep stale race text/refs in the header and Player/Live records while
    the in-game body/appearance comes from another structure.  This full scan is a
    research view: it does not claim every hit is the active player race.
    """
    rows: list[dict[str, Any]] = []
    payload = doc.payload
    flt = doc.file_location_table
    owners = []
    if payload and flt:
        try:
            owners = list(iter_change_forms(payload, flt))
        except Exception:
            owners = []
    for race in SKYRIM_RACES:
        start = 0
        while True:
            off = data.find(race.encoded, start)
            if off < 0:
                break
            virt = payload.virtual_offset + off if payload else off
            owner_text = "payload / non-changeform"
            owner_ref = ""
            owner_type = ""
            owner_rel = ""
            for cf in owners:
                if cf.data_offset <= virt < cf.data_end_offset:
                    owner_text = f"changeform #{cf.index}"
                    owner_ref = cf.refid_hex
                    owner_type = str(cf.form_type)
                    owner_rel = f"0x{virt - cf.data_offset:X}"
                    break
            rows.append({
                "offset": off,
                "offset_hex": f"0x{off:X}",
                "virtual_offset": virt,
                "virtual_offset_hex": f"0x{virt:X}",
                "race": race.display,
                "editor_id": race.editor_id,
                "form_id": race.form_id,
                "encoded": race.encoded_hex,
                "owner": owner_text,
                "owner_refid": owner_ref,
                "owner_form_type": owner_type,
                "owner_relative_offset": owner_rel,
            })
            start = off + 1
    rows.sort(key=lambda row: int(row["virtual_offset"]))
    return rows


def _pack_dataclass(obj: object) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    return obj


def build_race_sex_snapshot(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    doc = read_ess(path, change_form_preview_limit=0)
    h = doc.header
    snapshot: dict[str, Any] = {
        "source": str(path),
        "header": {
            "player_name": h.player_name,
            "race_text": h.player_race,
            "sex_value": h.player_sex,
            "sex_text": h.sex_text,
            "race_offset": h.player_race_offset,
            "race_offset_hex": f"0x{h.player_race_offset:X}",
            "race_capacity": h.player_race_capacity,
            "sex_offset": h.player_sex_offset,
            "sex_offset_hex": f"0x{h.player_sex_offset:X}",
            "note": "Header sex/race affects save metadata. It has not been proven to fully change in-game body/appearance.",
        },
        "race_mapping": None,
        "live_player": None,
        "player_actor": None,
        "all_race_refs": [],
        "notes": [
            "Race has at least two mapped areas in many saves: Player ChangeForm 400014 and Live Player 400007.",
            "These mapped refs can be stale after showracemenu, vampire race changes, or appearance changes.",
            "Gender/sex is not fully mapped yet. The current UI header sex is only the save-header value.",
            "A true gender/race change likely needs Player/NPC/FaceGen/head-part data beyond the header value.",
        ],
    }
    if doc.payload:
        snapshot["all_race_refs"] = _all_race_hits_with_context(doc, doc.payload.data)
    try:
        mapping = read_skyrim_race_mapping(path)
        snapshot["race_mapping"] = {
            "summary": mapping.summary(),
            "header_race": mapping.header_race_text,
            "mapped_race_ref": mapping.active_race.editor_id if mapping.active_race else None,
            "player_hit": _pack_dataclass(mapping.player_hit),
            "live_hit": _pack_dataclass(mapping.live_hit),
        }
    except Exception as exc:
        snapshot["race_mapping"] = {"error": str(exc)}
    try:
        live = read_live_player_fields(path)
        snapshot["live_player"] = {
            "refid": live.change_form.refid_hex,
            "name": live.name,
            "level": live.level,
            "record_size": len(live.record_data),
            "race_refs": _race_hits(live.record_data),
        }
    except Exception as exc:
        snapshot["live_player"] = {"error": str(exc)}
    try:
        player = load_player_data(path)
        snapshot["player_actor"] = {
            "refid": player.change_form.refid_hex,
            "compressed": player.compressed,
            "payload_size": len(player.player_data),
            "virtual_offset": player.player_data_virtual_offset,
            "virtual_offset_hex": f"0x{player.player_data_virtual_offset:X}" if player.player_data_virtual_offset is not None else None,
            "race_refs": _race_hits(player.player_data),
        }
    except Exception as exc:
        snapshot["player_actor"] = {"error": str(exc)}
    return snapshot


def race_sex_snapshot_to_text(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    header = snapshot.get("header", {}) or {}
    lines.append("Race / Sex Research Snapshot")
    lines.append(f"Source: {snapshot.get('source', '')}")
    lines.append("")
    lines.append("Header")
    lines.append(f"- Race text: {header.get('race_text', '')}")
    lines.append(f"- Header sex: {header.get('sex_text', '')} ({header.get('sex_value', '')})")
    lines.append(f"- Race text offset: {header.get('race_offset_hex', '')}, capacity {header.get('race_capacity', '')}")
    lines.append(f"- Sex offset: {header.get('sex_offset_hex', '')}")
    lines.append("")
    mapping = snapshot.get("race_mapping", {}) or {}
    lines.append("Mapped Race References")
    if mapping.get("summary"):
        lines.extend(f"- {line}" for line in str(mapping["summary"]).splitlines())
    elif mapping.get("error"):
        lines.append(f"- Error: {mapping['error']}")
    else:
        lines.append("- Not available")
    lines.append("")
    for key, title in (("player_actor", "Player Actor 400014"), ("live_player", "Live Player 400007")):
        block = snapshot.get(key, {}) or {}
        lines.append(title)
        if block.get("error"):
            lines.append(f"- Error: {block['error']}")
        else:
            refs = block.get("race_refs") or []
            lines.append(f"- Race refs found: {len(refs)}")
            for row in refs[:16]:
                lines.append(f"  - {row.get('offset_hex')}: {row.get('editor_id')} ({row.get('encoded')})")
            if len(refs) > 16:
                lines.append(f"  - ... {len(refs) - 16} more")
        lines.append("")
    all_refs = snapshot.get("all_race_refs") or []
    lines.append("All Race RefID Hits in Payload")
    lines.append(f"- Total hits: {len(all_refs)}")
    for row in all_refs[:40]:
        owner = row.get("owner", "")
        refid = row.get("owner_refid", "")
        rel = row.get("owner_relative_offset", "")
        suffix = f" {owner}" + (f" ref {refid}" if refid else "") + (f" rel {rel}" if rel else "")
        lines.append(f"  - {row.get('virtual_offset_hex')}: {row.get('editor_id')} ({row.get('encoded')}){suffix}")
    if len(all_refs) > 40:
        lines.append(f"  - ... {len(all_refs) - 40} more")
    lines.append("")
    lines.append("Current conclusion")
    lines.append("- Header + mapped race clusters are now reported together instead of blindly using the first race RefID hit.")
    lines.append("- showracemenu can leave an old/original race beside the new/current race in Player/Live records.")
    lines.append("- If the header race appears inside the player/live race cluster, the snapshot treats that as the likely active mapped race.")
    lines.append("- Full in-game race/gender/body changes may still need additional FaceGen/head-part/player-base data.")
    return "\n".join(lines)


def write_race_sex_snapshot_json(path: str | Path, snapshot: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
