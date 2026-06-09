from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class LearnedMagicList:
    """Detected player learned-magic list inside ChangeForm 400014.

    Skyrim stores learned spell-like records as a u32 count followed by compact
    3-byte RefIDs.  The uploaded PC and decrypted PS4 saves all show this list
    beginning with the same two built-in magic entries, which makes the layout
    reliable enough for a guarded patcher.
    """

    count_offset: int
    start_offset: int
    end_offset: int
    count: int
    entries: tuple[str, ...]
    known_matches: int
    first_pattern: bool
    tail_marker: bool
    confidence: str
    score: int

    def contains(self, encoded_refid_hex: str) -> bool:
        return encoded_refid_hex.upper().strip() in set(self.entries)

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset

    def to_text(self) -> str:
        marker = "yes" if self.tail_marker else "no"
        first = "yes" if self.first_pattern else "no"
        return (
            f"Learned magic list: count={self.count}, "
            f"count_offset=0x{self.count_offset:X}, start=0x{self.start_offset:X}, end=0x{self.end_offset:X}, "
            f"known_matches={self.known_matches}, first_pattern={first}, tail_marker={marker}, confidence={self.confidence}"
        )


def detect_learned_magic_list(player_data: bytes, known_encoded_refids: Iterable[str] = ()) -> LearnedMagicList | None:
    """Find the learned magic array in decoded player ChangeForm bytes.

    The detector prefers the stable first-entry signature seen in the user's PC
    and decrypted PS4 saves.  It only falls back to known-reference density when
    that signature is absent, which avoids accidental matches in animation/text
    subrecords that also contain many 3-byte-looking values.
    """

    known = {str(x).upper().strip() for x in known_encoded_refids if str(x).strip()}
    candidates: list[LearnedMagicList] = []
    data = player_data or b""
    for count_offset in range(0, max(0, len(data) - 8)):
        count = int.from_bytes(data[count_offset:count_offset + 4], "little", signed=False)
        if count < 1 or count > 2000:
            continue
        start = count_offset + 4
        end = start + (count * 3)
        if end > len(data):
            continue
        entries = tuple(data[pos:pos + 3].hex().upper() for pos in range(start, end, 3))
        if not entries:
            continue
        known_matches = sum(1 for entry in entries if entry in known)
        first_pattern = len(entries) >= 2 and entries[0] == "41711D" and entries[1] == "41711F"
        # The next block in the observed saves starts with a small u32/flag group.
        tail = data[end:end + 8]
        tail_marker = tail.startswith(b"\x01\x00\x00")
        if not first_pattern and known_matches < 8:
            continue
        ref_like = sum(1 for entry in entries if entry.startswith("00") or 0x40 <= int(entry[:2], 16) <= 0x7F)
        score = (5000 if first_pattern else 0) + known_matches * 12 + min(ref_like, 300) + (120 if tail_marker else 0)
        if count > 500:
            score -= 250
        if first_pattern and tail_marker:
            confidence = "high"
        elif first_pattern or known_matches >= 24:
            confidence = "medium"
        else:
            confidence = "low"
        candidates.append(LearnedMagicList(
            count_offset=count_offset,
            start_offset=start,
            end_offset=end,
            count=count,
            entries=entries,
            known_matches=known_matches,
            first_pattern=first_pattern,
            tail_marker=tail_marker,
            confidence=confidence,
            score=score,
        ))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.first_pattern, item.tail_marker, item.known_matches, item.score), reverse=True)
    return candidates[0]
