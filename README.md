# Skyrim Save Lab

Created by ProtoBuffers

Modern Skyrim save editor created by ProtoBuffers.

## Current workflow

1. Open a save.
2. Make edits across the normal tabs.
3. Use **File > Save** once to overwrite the loaded save with a backup.
4. Use **File > Save As...** to create a new edited copy.

The editor keeps one shared working copy in memory. Normal tabs do not need their own save buttons.

## Main features

- Save / Load page with central Save and Save As actions.
- General player fields, stats, skills, XP, gold, lockpicks, and mapped actor values where detected safely.
- Player Inventory editor with category filtering, unknown item research, CSV tools, right-click copy/duplicate/paste actions, and plugin-aware FormID display.
- Magic tabs for Spells, Shouts, Powers, Abilities, and Active Effects.
- Plugin viewer for save plugin order and DLC/FormID resolution.
- Raw Editor with mapped fields, change forms, format reference, quick-code helpers, Parsed Tree, and Parsed JSON.
- Automatic backups before overwrite.
- Single-file PyInstaller build support.

## Notes on experimental areas

- Spendable Dragon Souls is still under research. `DragonsAbsorbed` is a lifetime/absorbed counter, not the spendable shout-menu count.
- Shout word unlock records can be edited/researched, but base shout discovery is still not fully mapped. Console `teachword` / `unlockword` is still the safest route for undiscovered shouts.
- Race/Gender changes may require FaceGen/head-part/player-base data beyond the race references currently detected.
- Creation Club and modded inventory IDs may still need more database rows from user saves.

## Raw Editor improvements

The Raw Editor now includes a **Parsed Tree** tab. It displays the parsed save model in a compact searchable tree with grouped large arrays, making it faster to browse than full JSON text.

The **Parsed JSON** tab remains available for export/research, validation, formatting, and compacting. Parsed JSON is not a direct save writer.

## Safety

Always keep a clean backup before testing. The editor creates `.bak` files before overwriting, but experimental edits should still be tested with Save As first.

## UI readability update

- Parsed Tree now uses theme-aware tree colors instead of native white rows in dark themes.
- Parsed Tree rows are taller, clearer, and show compact object/list summaries.
- Tree nodes include hover highlighting and tooltips for long values.


## Current Dragon Souls Status

Dragon Souls was removed from General > Common because the spendable shout-menu value is not mapped yet. `DragonsAbsorbed` is still known to be a lifetime/absorbed counter, not the spendable value.

## Save Folder Browser

The Save / Load page can store one base folder and scan every subfolder for Skyrim saves. This is intended for PS4/decrypted save folders where every save file is named `SAVEDATA.DAT` and the folder name is the only useful label.

Workflow:

1. Open **Save / Load**.
2. By default, the browser starts at `C:\Users\pc\Documents\My Games\Skyrim Special Edition\Saves`.
3. Click **Choose Base Folder** only if your saves are somewhere else, such as a PS4/decrypted save folder collection.
4. Click **Scan Subfolders**.
5. Double-click a row or select it and click **Open Selected**.

The table displays folder name, save filename, player, location, size, modified date, and full path.

### Save / Load Browser Focus Update

The Save / Load page is now centered around the recursive save folder browser. The old separate Current Save card is hidden from the normal UI. The loaded save is marked directly in the browser with a loaded indicator, and the safety notes/backups are kept at the bottom so the save list remains the main focus.

## Race / Sex research note

Race detection now reports **mapped race references** instead of claiming they are the guaranteed active in-game race. Some saves keep `BretonRace` in the header/player/live records even when the player looks like another race in-game after `showracemenu`, vampire race changes, or appearance edits. Use **General > Player > Race / Sex Research > Copy Snapshot** to see all known race RefID hits and where they live.

### Race Editing Update

Race changes now use a fuller sync pass: the editor updates all known vanilla playable/vampire race RefIDs found in the Player ChangeForm `400014` and Live Player ChangeForm `400007`, instead of only changing the first race pair. This is intended to reduce hybrid race results where an old race reference remains beside the new one.

Header race text is updated only when the new race editor ID fits the existing fixed save-header slot. The editor does not resize the header string because moving the compressed payload can invalidate internal save offsets. If the header label cannot fit, the actual player race records are still synced.

Race editing remains experimental because Skyrim can keep separate appearance/head-part/FaceGen data. Use backups and test Race changes with Save As first.

## Inventory Count Editing

Inventory Count cells now commit live while you edit them. Double-click a Count cell or use the selected-item Count box; the pending edit label updates immediately. Use File > Save once to write all pending changes after a backup is created.

### Inventory live count fix
- Count quick buttons and the Count spinbox now update the selected editable inventory row immediately.
- Read-only/research rows now disable Count editing and show a status-bar message instead of silently ignoring the change.

### Inventory count editability update

The inventory table now keeps conservative full-scan rows visible while allowing
nonzero rows with a mapped fixed-size count field to be edited live. Truly
unmapped zero-count research candidates remain locked until their row layout is
verified.

## Inventory stability rollback pass

This build keeps the updated bundled database, but rolls the editable inventory grid back to stable inventory rows only. Loose full-player scan rows are no longer merged into the editable inventory table because they can be stale, extra-data-adjacent, or research-only candidates that do not reliably save.

Inventory save verification is now a soft warning instead of a hard failure when rebuilt payload offsets move. Save output is still written, then the editor refreshes from the saved file.

## Inventory database collection pass

The inventory editor now keeps stable editable rows separate from research rows. Unknown inventory research remains available, but it no longer changes the main save-writing path.

New research helpers:

- **Player Inventory > Unknown Research > Copy Unknown IDs** copies unresolved FormIDs with counts and category guesses.
- **Copy AddItem Commands** creates `player.additem` commands for unresolved IDs so testers can identify items in-game.
- **Scan Save Folder Unknowns** scans every save in the Save / Load base folder and exports one aggregate CSV. This is the preferred way to collect missing IDs from PS4 folders where every save is named `SAVEDATA.DAT`.

Database policy:

- Do not guess IDs when a FormID conflict exists.
- Keep conflicting duplicate names combined until end users verify the exact record.
- Prefer expanding the bundled database over changing inventory save-writing logic.
- Keep the item/gold cap at `99,999,999` to avoid signed 32-bit display overflow in-game.


## Tools / Diagnostics

The **Tools** page is the preferred place for maintenance work that should not change save bytes. It now includes:

- **Build Diagnostics Report**: copies the current save summary, database health, pending edits, unknown inventory preview, and safety notes into one report for bug reports.
- **Database Audit**: shows duplicate FormIDs, malformed rows, unresolved `XX######` placeholders, weak source categories, and current unknown inventory counts.

Use this page before changing parser code. It helps separate database problems from save-writing problems.