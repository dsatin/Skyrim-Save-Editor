from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import io

from app.core.form_id_tools import infer_plugin_name, resolve_xx_id
from app.core.id_database import IdRecord
from app.core.learned_magic import LearnedMagicList, detect_learned_magic_list
from app.core.player_payload import load_player_data
from app.core.skyrim_ess import EssDocument, EssParseError, encode_default_refid, iter_change_forms, read_ess

MAGIC_FAVORITES_GLOBAL_TYPE = 109
MAGIC_CATEGORIES = {
    "spells",
    "shouts",
    "powers",
    "lesser powers",
    "greater powers",
    "abilities",
    "active effects",
    "activeeffects",
}

MAGIC_CATEGORY_ALIASES = {
    "spell": "spells",
    "spells": "spells",
    "shout": "shouts",
    "shouts": "shouts",
    "power": "powers",
    "powers": "powers",
    "lesser power": "lesser powers",
    "lesser powers": "lesser powers",
    "greater power": "greater powers",
    "greater powers": "greater powers",
    "ability": "abilities",
    "abilities": "abilities",
    "active effect": "active effects",
    "active effects": "active effects",
    "activeeffects": "active effects",
}


@dataclass(slots=True)
class MagicRecordRef:
    category: str
    editor_id: str
    name: str
    form_id: str
    resolved_form_id: str
    encoded_refid_hex: str
    source: str
    notes: str


@dataclass(slots=True)
class MagicHit:
    source: str
    name: str
    category: str
    form_id: str
    resolved_form_id: str
    encoded_refid_hex: str
    area: str
    offset: int
    local_offset: int | None
    confidence: str
    notes: str




@dataclass(slots=True)
class ShoutWordState:
    source: str
    shout_name: str
    word_name: str
    editor_id: str
    form_id: str
    resolved_form_id: str
    encoded_refid_hex: str
    present: bool
    unlocked: bool
    change_form_index: int | None
    offset: int | None
    data_offset: int | None
    data_hex: str
    notes: str


@dataclass(slots=True)
class MagicFavoriteBlock:
    table: int
    index: int
    data_offset: int
    length: int
    sample_hex: str
    candidate_count: int
    candidate_hex: str


@dataclass(slots=True)
class MagicScanResult:
    hits: list[MagicHit]
    favorite_blocks: list[MagicFavoriteBlock]
    notes: list[str]
    learned_magic: LearnedMagicList | None = None
    shout_words: list[ShoutWordState] | None = None


def _normalize_magic_category(category: str) -> str:
    c = (category or "").strip().casefold()
    return MAGIC_CATEGORY_ALIASES.get(c, c)


def magic_kind(category: str) -> str:
    """Return the UI bucket used by the Magic page.

    Favorites can contain spells, shouts, powers, and abilities in the same raw
    save block, but the editor deliberately keeps shouts separate because they
    use Word-of-Power records instead of the normal player.addspell flow. Powers
    and passive abilities are still SPELL records and use the same learned-magic
    list as ordinary spells, but they are shown in separate tabs for clarity.
    """
    c = _normalize_magic_category(category)
    if c == "shouts":
        return "Shouts"
    if c == "spells":
        return "Spells"
    if c in {"powers", "lesser powers", "greater powers"}:
        return "Powers"
    if c == "abilities":
        return "Abilities"
    if c in {"active effects", "activeeffects"}:
        return "Active Effects"
    return "Other"


def magic_records_from_database(records: list[IdRecord], plugins: list[str] | None = None) -> list[MagicRecordRef]:
    plugins = list(plugins or [])
    out: list[MagicRecordRef] = []
    seen: set[str] = set()
    for rec in records:
        cat = _normalize_magic_category(rec.category)
        if cat not in MAGIC_CATEGORIES:
            continue
        form_id = (rec.form_id or "").upper().strip()
        if not form_id:
            continue
        resolved = form_id
        if form_id.startswith("XX"):
            hint = infer_plugin_name(rec.source, rec.editor_id, rec.name, rec.notes) or rec.source
            resolved = resolve_xx_id(form_id, hint, plugins) or form_id
        if len(resolved) != 8 or resolved.startswith("XX"):
            continue
        try:
            encoded = encode_default_refid(int(resolved, 16)).hex().upper()
        except Exception:
            continue
        key = resolved
        if key in seen:
            continue
        seen.add(key)
        out.append(MagicRecordRef(
            category=rec.category or "Magic",
            editor_id=rec.editor_id,
            name=rec.name or rec.editor_id or resolved,
            form_id=form_id,
            resolved_form_id=resolved,
            encoded_refid_hex=encoded,
            source=rec.source,
            notes=rec.notes,
        ))
    out.sort(key=lambda r: (r.category.casefold(), r.name.casefold(), r.resolved_form_id))
    return out




def detect_shout_word_states_from_doc(doc: EssDocument, records: list[IdRecord]) -> list[ShoutWordState]:
    """Return shout Word-of-Power changeform states.

    Learned spells/powers are stored in the player learned-magic list, but shout
    words are stored as individual Word-of-Power ChangeForms. In the uploaded
    saves the 6-byte word payload is 49 00 XX 00 00 00, where byte 2 is the
    unlocked flag: 00 = known/locked, nonzero = unlocked.
    """
    if not doc.payload or not doc.file_location_table:
        return []
    plugins = doc.plugin_info.plugins if doc.plugin_info else []
    refs = [ref for ref in magic_records_from_database(records, plugins) if magic_kind(ref.category) == "Shouts"]
    if not refs:
        return []
    by_encoded = {entry.refid_hex.upper(): entry for entry in iter_change_forms(doc.payload, doc.file_location_table)}
    states: list[ShoutWordState] = []
    for ref in refs:
        entry = by_encoded.get(ref.encoded_refid_hex.upper())
        present = entry is not None
        unlocked = False
        data_hex = ""
        data_offset: int | None = None
        offset: int | None = None
        index: int | None = None
        note = "No Word-of-Power ChangeForm found."
        if entry is not None:
            index = entry.index
            offset = entry.offset
            data_offset = entry.data_offset
            rel = entry.data_offset - doc.payload.virtual_offset
            raw = doc.payload.data[rel:rel + entry.length1] if 0 <= rel <= len(doc.payload.data) else b""
            data_hex = raw.hex(" " ).upper()
            unlocked = len(raw) >= 3 and raw[2] != 0
            if len(raw) >= 3:
                note = "Unlocked word flag is set." if unlocked else "Word ChangeForm exists but unlock flag is not set."
            else:
                note = "Word ChangeForm exists, but the payload is shorter than the known 6-byte layout."
        shout_name = ref.notes or "Unknown shout"
        states.append(ShoutWordState(
            source=ref.source,
            shout_name=shout_name,
            word_name=ref.name,
            editor_id=ref.editor_id,
            form_id=ref.form_id,
            resolved_form_id=ref.resolved_form_id,
            encoded_refid_hex=ref.encoded_refid_hex,
            present=present,
            unlocked=unlocked,
            change_form_index=index,
            offset=offset,
            data_offset=data_offset,
            data_hex=data_hex,
            notes=note,
        ))
    states.sort(key=lambda s: (s.shout_name.casefold(), s.word_name.casefold(), s.resolved_form_id))
    return states


def detect_shout_word_states(save_path: str | Path, records: list[IdRecord]) -> list[ShoutWordState]:
    return detect_shout_word_states_from_doc(read_ess(save_path, change_form_preview_limit=0), records)

def scan_magic(save_path: str | Path, records: list[IdRecord]) -> MagicScanResult:
    doc = read_ess(save_path, change_form_preview_limit=0)
    plugins = doc.plugin_info.plugins if doc.plugin_info else []
    refs = magic_records_from_database(records, plugins)
    notes: list[str] = []
    if not refs:
        notes.append("No spell/shout/power/ability reference rows are loaded. Load or merge the reference database to improve names.")
    favorite_blocks = _read_magic_favorite_blocks(doc)
    shout_words = detect_shout_word_states_from_doc(doc, records)
    hits: list[MagicHit] = []

    player_data = b""
    player_virtual = 0
    try:
        ctx = load_player_data(save_path)
        player_data = ctx.player_data
        player_virtual = ctx.player_data_virtual_offset
    except Exception as exc:
        notes.append(f"Player ChangeForm scan skipped: {exc}")

    ref_by_encoded = {ref.encoded_refid_hex: ref for ref in refs}
    learned_magic: LearnedMagicList | None = None
    if player_data:
        learned_magic = detect_learned_magic_list(player_data, ref_by_encoded.keys())
        if learned_magic:
            notes.append(
                f"Learned magic list detected: {learned_magic.count:,} entries at player offset "
                f"0x{learned_magic.start_offset:X} ({learned_magic.confidence} confidence)."
            )
            for index, encoded in enumerate(learned_magic.entries):
                ref = ref_by_encoded.get(encoded)
                if not ref:
                    continue
                pos = learned_magic.start_offset + index * 3
                context = player_data[max(0, pos - 8):min(len(player_data), pos + 11)].hex(" ").upper()
                hits.append(MagicHit(
                    source=ref.source,
                    name=ref.name,
                    category=ref.category,
                    form_id=ref.form_id,
                    resolved_form_id=ref.resolved_form_id,
                    encoded_refid_hex=ref.encoded_refid_hex,
                    area="Player learned magic list",
                    offset=player_virtual + pos,
                    local_offset=pos,
                    confidence="confirmed",
                    notes=f"entry #{index + 1}; context {context}",
                ))
        else:
            notes.append("Learned magic list was not detected; falling back to a conservative player-byte scan.")

    # Search favorites and, only if the learned list was not found, the broader
    # player data. The learned list gives cleaner current/unlocked status than a
    # loose full-player scan.
    areas: list[tuple[str, bytes, int, int | None, str]] = []
    if player_data and learned_magic is None:
        areas.append(("Player ChangeForm 400014", player_data, player_virtual, 0, "medium"))
    if doc.payload:
        for block in favorite_blocks:
            start = block.data_offset - doc.payload.virtual_offset
            raw = doc.payload.data[start:start + block.length]
            areas.append((f"GlobalData {MAGIC_FAVORITES_GLOBAL_TYPE} Magic Favorites", raw, block.data_offset, None, "high"))

    seen_hit_keys: set[tuple[str, str, int]] = {(h.encoded_refid_hex, h.area, h.local_offset or h.offset) for h in hits}
    for ref in refs:
        needle = bytes.fromhex(ref.encoded_refid_hex)
        for area_name, data, base_offset, local_base, confidence in areas:
            pos = data.find(needle)
            while pos != -1:
                abs_offset = base_offset + pos
                local = (local_base + pos) if local_base is not None else None
                key = (ref.encoded_refid_hex, area_name, local if local is not None else abs_offset)
                if key not in seen_hit_keys:
                    context = data[max(0, pos - 8):min(len(data), pos + len(needle) + 8)].hex(" ").upper()
                    hits.append(MagicHit(
                        source=ref.source,
                        name=ref.name,
                        category=ref.category,
                        form_id=ref.form_id,
                        resolved_form_id=ref.resolved_form_id,
                        encoded_refid_hex=ref.encoded_refid_hex,
                        area=area_name,
                        offset=abs_offset,
                        local_offset=local,
                        confidence=confidence,
                        notes=f"matched encoded RefID bytes; context {context}",
                    ))
                    seen_hit_keys.add(key)
                pos = data.find(needle, pos + 1)

    # Keep the table manageable while still surfacing repeated matches.
    hits.sort(key=lambda h: (h.area, h.offset, h.category, h.name))
    if len(hits) > 2000:
        notes.append(f"Magic hit list clipped from {len(hits):,} to 2,000 rows to keep the UI responsive.")
        hits = hits[:2000]
    unlocked_words = sum(1 for state in shout_words if state.unlocked)
    known_locked_words = sum(1 for state in shout_words if state.present and not state.unlocked)
    if shout_words:
        notes.append(f"Shout words detected: {unlocked_words:,} unlocked, {known_locked_words:,} known/locked, {len(shout_words) - unlocked_words - known_locked_words:,} missing.")
    if not hits:
        notes.append("No known spell/power/ability FormIDs were found in the currently mapped magic/player regions yet. Shout words are tracked separately from the learned-spell list.")
    return MagicScanResult(hits=hits, favorite_blocks=favorite_blocks, notes=notes, learned_magic=learned_magic, shout_words=shout_words)


def _read_magic_favorite_blocks(doc: EssDocument) -> list[MagicFavoriteBlock]:
    blocks: list[MagicFavoriteBlock] = []
    if not doc.payload:
        return blocks
    for entry in doc.global_data_entries:
        if entry.type != MAGIC_FAVORITES_GLOBAL_TYPE:
            continue
        start = entry.data_offset - doc.payload.virtual_offset
        raw = doc.payload.data[start:start + entry.length]
        candidates = _candidate_refid_hex(raw)
        blocks.append(MagicFavoriteBlock(
            table=entry.table,
            index=entry.index,
            data_offset=entry.data_offset,
            length=entry.length,
            sample_hex=raw[:96].hex(" ").upper(),
            candidate_count=len(candidates),
            candidate_hex=", ".join(candidates[:32]) + (" ..." if len(candidates) > 32 else ""),
        ))
    return blocks


def _candidate_refid_hex(raw: bytes) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for i in range(0, max(0, len(raw) - 2)):
        b0 = raw[i]
        # Default records use type bits 01 -> 0x40-0x7F.  This catches base
        # game/DLC form refs while ignoring most small counters.
        if 0x40 <= b0 <= 0x7F:
            h = raw[i:i + 3].hex().upper()
            if h not in seen:
                seen.add(h)
                out.append(h)
    return out


def magic_hits_to_csv(hits: list[MagicHit]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Category", "FormID", "ResolvedFormID", "EncodedRefID", "Area", "Offset", "LocalOffset", "Confidence", "Source", "Notes"])
    for h in hits:
        writer.writerow([
            h.name,
            h.category,
            h.form_id,
            h.resolved_form_id,
            h.encoded_refid_hex,
            h.area,
            f"0x{h.offset:X}",
            "" if h.local_offset is None else f"0x{h.local_offset:X}",
            h.confidence,
            h.source,
            h.notes,
        ])
    return buf.getvalue()
