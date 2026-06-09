from __future__ import annotations

FRESH_SAVE_STUDY_PLAN = """Fresh-save study plan

Goal: isolate one save structure at a time so the editor can patch records without corrupting saves.

Minimum saves to send next:
1. baseline.ess — fresh save, no commands after loading.
2. gold_1000.ess — same baseline, run: player.additem 0000000F 1000, then save.
3. lockpick_10.ess — same baseline, run: player.additem 0000000A 10, then save.
4. carryweight_9999.ess — same baseline, run: player.forceav carryweight 9999, then save.
5. smithing_100.ess — same baseline, run: player.setav smithing 100, then save.

Good optional saves:
- one_perk_added.ess after adding exactly one known perk.
- one_spell_added.ess after adding exactly one known spell.
- item_removed.ess after removing a known count from a stack.

Rules for clean comparisons:
- Start each changed save from the same baseline.
- Run only one command per changed save.
- Save in the same location if possible.
- Do not wait in-game longer than needed; time/date changes add noise.
- Avoid autosaves between tests when possible.
"""

EDITOR_ROADMAP = """Module roadmap

Current safe modules:
- Header editor: fixed-width header fields only.
- Plugin reader: save dependency/load-order awareness.
- ID database: spreadsheet-backed FormID and actor-value search.
- Console IDs: command builder for controlled save tests.
- Scanner: raw FormID and RefID discovery.
- Diff Lab: baseline-vs-changed save comparison.

Next modules after fresh saves:
- Global Variables module: parse global data type 3 values.
- Player Actor module: locate Player / PlayerBase change forms.
- Inventory module: map item FormIDs, counts, equipped flags.
- Actor Values module: map health/magicka/stamina/carryweight/skills.
- Perks/Spells/Shouts module: discover single-add records.
- Patch Queue module: stage edits, validate offsets, write edited copy only.
"""
