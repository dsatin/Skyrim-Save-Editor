# Perk editing research

Status: spendable points are now identified in the observed SE v78 profile and
copy editing is enabled. Binary round-trip tests pass; in-game reload remains
unverified. Acquired-perk writing is not yet enabled.
Database FormIDs identify records; they do not establish the byte
layout or side effects of changing a player's acquired perks in an ESS file.

## Original implementation (before the SE point-count fix)

- `app/core/quick_codes.py`: `perk_points` accepts 0–255 and generates a
  Search + Pointer + Write sequence. Its final instruction writes **four bytes**.
  This width and the searched location need independent validation; the preset's
  range alone does not prove the underlying field width.
- `app/core/preset_patcher.py`: classifies this preset as experimental, requires
  explicit experimental mode, and rejects writing back to the source path.
- `app/ui/main_window.py`: describes the perk pattern as research only. Legacy
  preset handlers remain, but no active preset selector is constructed.
- The database contains perk IDs, and the console helper supports
  `player.addperk` and `player.removeperk`. The learned-magic array parser is
  specific to spell-like entries and is not evidence for a perk-list layout.

## Sources inspected

Accessed 2026-09-07:

- [xEdit ESS definitions](https://github.com/TES5Edit/TES5Edit/blob/dev-4.1.6/Core/wbDefinitionsTES5Saves.pas):
  the player-specific ACHR branches do not supply a perk-point or acquired-perk
  layout. This source does not validate the existing search-pattern preset.
- [FallrimTools NPC parser](https://github.com/mdfairch/FallrimTools/blob/master/src/main/java/resaver/ess/ChangeFormNPC.java)
  and [ACHR parser](https://github.com/mdfairch/FallrimTools/blob/master/src/main/java/resaver/ess/ChangeFormACHR.java):
  these are references for change-form parsing, not validation of the current
  perk pattern. NPC spell arrays must not be treated as acquired-perk arrays.
- [Skyrim Perk Utility](https://github.com/aaronmaynard/Skyrim-Perk-Utility):
  offers activation/reset through generated in-game scripts, not direct ESS
  byte edits.
- [Console Commands Extender](https://github.com/clayne/CCExtender): documents
  `SetPerkPoints` / `spp` and an SKSE64 dependency. This must not be advertised
  as an available vanilla console command or a console-platform save editor.

UESP save-format pages could not be retrieved (403/access errors); their contents
were not used to validate a writer. No database-wide ID audit or in-game test has
been completed.

## Required validation before enabling direct save writes

1. Establish target edition, platform, and a readable save path. Work on copies.
2. Collect controlled saves from the same character: baseline with known points;
   one additional available point with no perk acquired; and one known perk
   acquired with the before/after point counts recorded. Also obtain a multi-rank
   perk example. Keep the plugin list constant.
3. Compare decoded records, separating the point counter from the acquired-perk
   list. Determine field width, record flags, count encoding, RefID resolution,
   and any associated state. Reject ambiguous or unsupported layouts.
4. Add structural parsing and writing, preserving unrelated records and handling
   compression, counts, lengths, and downstream offsets. Resolve perk IDs against
   the save's actual plugin order; do not assume every listed perk is vanilla.
5. Test no-op byte preservation, bounds, malformed/truncated inputs, duplicate
   activation, rank ordering, compressed/uncompressed round trips, and preservation
   of unrelated bytes. Reopen each generated save with the parser.
6. Load edited copies in the target game and verify points, acquired perks,
   effects, and persistence after saving/reloading. Only then label that tested
   layout as validated and integrate it with the central Save / Save As workflow.

Do not enable the legacy four-byte search-pattern writer merely because the perk
IDs or an in-memory game API are documented online.

## Local Skyrim SE samples

The supplied Proton save directory contains three readable ESS saves (header
version 12, player ChangeForm version 78). Inspection was read-only:

| Save | Level | Candidate ranked-list offset in decoded player record | Known skill perk |
| --- | --- | --- | --- |
| Autosave2 | 2 | `0x6DA3` | `000BE124`, Light Fingers rank 1 |
| Autosave3 | 500 | No candidate accepted by the known-perk guard | None identified |
| Save7 | 500 | `0x7105` | `000BE128`, Haggling rank 1 |

Autosave2 and Save7 each have 14 candidate RefID/rank entries followed by 13
RefIDs that are a subset of the first list. Both lists contain the named skill
perk. Other entries resolve through the FormID array to DLC/light-plugin IDs;
their semantics have not been validated. Autosave3 has a similar 13/12 layout,
but no recognized skill perk to support accepting it automatically.

In all three samples the legacy point preset would replace `00 00 00 01` with
`0A 00 00 00` when asked for 10. Its targets are near the end of the player
record, at local offsets `0x6FFA`, `0x7548`, and `0x7395`, respectively. These
bytes must not be presented as a verified point value.

`python -m app.core.perk_research before.ess after.ess` now reports candidate
arrays, resolved IDs, and the legacy patch preview without writing any file.
Five unit tests cover bounds/truncation, companion-list membership, variable
counts, ambiguous candidates, and non-mutation. Tests and inspection of all
three real saves pass; this does not constitute in-game validation.

Next required evidence: confirm the displayed unspent point count and owned
perks for Save7, then compare against a new manual save made immediately after
spending exactly one point on a named perk. The existing saves differ in level,
magic, inventory and player flags, so they are not a controlled point-count pair.

## Confirmed 80-point sample and implementation

The user subsequently supplied a new character's Save2 (level 1) and Save3
(level 81), reporting 80 available points. In these files the field is one byte:

| Save | Offset inside decoded player record | Value | Following array count |
| --- | --- | --- | --- |
| Save2 | `0x702F` | `00` = 0 | 5 |
| Save3 | `0x7634` | `50` = 80 | 6 |

The next byte is a VSVal count, followed by 11-byte entries and an observed
28-byte suffix. A four-byte write would destroy that count and part of the first
entry. This establishes a concrete defect in the original preset.

`app/core/perk_points.py` recognizes the bounded observed layout, requires a
unique candidate, checks the surrounding entries/suffix and supported save and
record versions, and changes only one byte. It supports nonzero references in
the prefix where the old all-zero search could fail. Unrecognized layouts are
rejected; the early Prisoner Save1 in the current folder is not supported.

General > Perk Points displays the current total and writes only a new test
copy. It does not auto-save pending edits from other tabs. The old preset path
also uses the guarded locator and a one-byte write; compressed player records
use the new copy workflow.

Validation: ten unit tests pass, the panel reads 80 in a headless UI check, and
a temporary copy of the real Save3 successfully round-tripped 80 → 95 → 80.
Only one byte in the complete decompressed ESS payload changed on the forward
patch; the entire original payload was restored on the reverse patch. The
original file's SHA-256 stayed unchanged. Temporary test copies were cleaned up.
No gameplay validation or acquired-perk activation has been performed.
