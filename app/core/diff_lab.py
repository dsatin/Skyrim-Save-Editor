from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
from typing import Any


@dataclass(slots=True)
class DiffHit:
    offset: int
    before_hex: str
    after_hex: str
    length: int
    before_int_le: int | None = None
    after_int_le: int | None = None
    before_int_be: int | None = None
    after_int_be: int | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DiffReport:
    baseline: str
    modified: str
    baseline_size: int
    modified_size: int
    changed_bytes: int
    windows: list[DiffHit]
    size_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "modified": self.modified,
            "baseline_size": self.baseline_size,
            "modified_size": self.modified_size,
            "changed_bytes": self.changed_bytes,
            "size_note": self.size_note,
            "windows": [w.to_dict() for w in self.windows],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def summary(self) -> str:
        return (
            f"Baseline: {self.baseline}\n"
            f"Modified: {self.modified}\n"
            f"Sizes: {self.baseline_size:,} → {self.modified_size:,} bytes\n"
            f"Changed bytes in overlapping range: {self.changed_bytes:,}\n"
            f"Diff windows shown: {len(self.windows):,}\n"
            f"{self.size_note}"
        )


def compare_saves(baseline: str | Path, modified: str | Path, *, context: int = 12, max_windows: int = 500) -> DiffReport:
    base_path = Path(baseline)
    mod_path = Path(modified)
    a = base_path.read_bytes()
    b = mod_path.read_bytes()
    limit = min(len(a), len(b))
    changed = [i for i in range(limit) if a[i] != b[i]]

    windows: list[DiffHit] = []
    if changed:
        start = changed[0]
        last = changed[0]
        for idx in changed[1:]:
            if idx <= last + 1:
                last = idx
            else:
                windows.append(_make_window(a, b, start, last, context))
                if len(windows) >= max_windows:
                    break
                start = last = idx
        if len(windows) < max_windows:
            windows.append(_make_window(a, b, start, last, context))

    size_note = "File sizes match." if len(a) == len(b) else "File size changed; deeper structure remap is required before patching."
    return DiffReport(
        baseline=str(base_path),
        modified=str(mod_path),
        baseline_size=len(a),
        modified_size=len(b),
        changed_bytes=len(changed) + abs(len(a) - len(b)),
        windows=windows,
        size_note=size_note,
    )


def _make_window(a: bytes, b: bytes, start: int, last: int, context: int) -> DiffHit:
    lo = max(0, start - context)
    hi = min(min(len(a), len(b)), last + 1 + context)
    before = a[lo:hi]
    after = b[lo:hi]
    changed_before = a[start:last + 1]
    changed_after = b[start:last + 1]
    before_le, after_le = _int_guess(changed_before, changed_after, "little")
    before_be, after_be = _int_guess(changed_before, changed_after, "big")
    note = _interpret(start, changed_before, changed_after, before_le, after_le)
    return DiffHit(
        offset=start,
        before_hex=before.hex(" ").upper(),
        after_hex=after.hex(" ").upper(),
        length=last - start + 1,
        before_int_le=before_le,
        after_int_le=after_le,
        before_int_be=before_be,
        after_int_be=after_be,
        note=note,
    )


def _int_guess(before: bytes, after: bytes, endian: str) -> tuple[int | None, int | None]:
    if len(before) not in {1, 2, 3, 4, 8} or len(after) != len(before):
        return None, None
    return int.from_bytes(before, endian), int.from_bytes(after, endian)


def _interpret(offset: int, before: bytes, after: bytes, before_le: int | None, after_le: int | None) -> str:
    notes: list[str] = []
    if len(before) == len(after) == 4 and before_le is not None and after_le is not None:
        delta = after_le - before_le
        notes.append(f"LE32 delta {delta:+d}")
        if abs(delta) in {1, 10, 100, 1000, 10000, 9999}:
            notes.append("amount-like change")
    if len(before) == len(after) == 1:
        notes.append(f"byte {before[0]}→{after[0]}")
    if offset < 256:
        notes.append("near save header")
    return "; ".join(notes)


def scan_value_variants(path: str | Path, value: str) -> dict[str, list[int]]:
    raw = Path(path).read_bytes()
    clean = value.strip().replace("0x", "").replace("0X", "").replace(" ", "")
    if not clean:
        raise ValueError("Missing hex value")
    if any(c not in "0123456789ABCDEFabcdef" for c in clean):
        raise ValueError("Value must be hexadecimal")
    clean = clean.upper().zfill(8)[-8:]
    num = int(clean, 16)
    needles: dict[str, bytes] = {
        "u32_be": num.to_bytes(4, "big"),
        "u32_le": num.to_bytes(4, "little"),
        "u24_ref_be": num.to_bytes(4, "big")[1:4],
        "u24_ref_le": num.to_bytes(4, "little")[:3],
    }
    return {name: _find_all(raw, needle) for name, needle in needles.items()}


def _find_all(data: bytes, needle: bytes) -> list[int]:
    hits: list[int] = []
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx < 0:
            return hits
        hits.append(idx)
        start = idx + 1
