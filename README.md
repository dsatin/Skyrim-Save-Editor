# Skyrim Save Lab - ProtoBuffers header and app icon

A modern PyQt6 Skyrim save editor/research build focused on safe parsing first.

## Run

```bat
python -m pip install -r requirements.txt
python run.py
```

## Build

```bat
build.bat
```

## Current features

- Opens `.ess` and `SAVEDATA.DAT` style Skyrim saves.
- Parses the ESS header, screenshot metadata, compression type, plugin list, file-location table, and change-form counts.
- Decodes LZ4 save payloads when `lz4` is installed.
- Header editor for fixed-width fields:
  - player name, inside the existing name slot
  - level
  - sex
  - XP Pool payload value
  - needed XP display value
- Player Inventory page:
  - shows item names first instead of FormIDs
  - lets you double-click the Count column and edit existing item counts inline
  - supports multiple queued count edits before saving
  - keeps internal FormIDs and exact payload offsets hidden in row metadata for safer patching
  - writes to a new save copy and creates a backup
- Plugins page:
  - shows full plugin index and hex load-order slot
  - shows light plugin slots as `FE###`
  - expands to use the available page height and includes a plugin filter/search box
- Reference IDs page:
  - spreadsheet/CSV driven
  - can load a local CSV or paste a public Google Sheets link and pull its CSV export
  - supports `XX123456` load-order placeholder IDs
  - shows a resolved active FormID when the owning plugin exists in the loaded save
- Form ID Tools page:
  - explains base IDs vs reference IDs
  - decodes full FormIDs into load-order byte and object ID
  - resolves `XX` placeholders against the current save plugin list
  - identifies `FE` light-plugin compact IDs
- Scanner page searches raw and decompressed save data for selected FormIDs.

## Important safety rule

Inventory editing currently changes only existing rows. It does **not** insert brand-new inventory rows yet. That keeps offsets and compressed payload rebuilds much safer while we finish mapping the player inventory structure.

## CSV columns

```csv
Category,EditorID,FormID,Name,Value,Source,Notes
```

Use `FormID` for normal eight-digit records, `XX` placeholders for DLC/mod tables, and `Value` for non-hex tokens like ActorValues or COC cell names.


## Expanded built-in reference database

This build ships with an expanded `app/resources/database/skyrim_ids_sample.csv` containing 981 rows across the main editor groups: alchemy/potions, arrows/bolts, blade weapons, blunt weapons, books, bows, clothing, heavy armor, light armor, jewelry, keys, misc items, food, staves, spells, enchantments, perks, shouts, skills, actor values, followers, factions, locations, weather, crafting materials, ores/ingots, gems, soul gems, building materials, and ingredients.

The database is still intentionally CSV-backed so we can keep adding and correcting IDs without touching the parser. `XX` DLC IDs are stored as placeholders and the Form ID Tools page resolves the first byte from the currently loaded save's plugin list when possible.


## ID database expansion pass

This build expands the built-in CSV reference database with additional rows from the Skyrim console-command item pages. New/expanded groups include Alchemy potions, poisons, Books, Keys, Clothing, Jewelry, Soul Gems, and common Spell Tomes. The database remains CSV-backed at `app/resources/database/skyrim_ids_sample.csv`, so future web/sheet imports can continue to replace or extend it without touching save parsing.


## Continued work pass

This pass adds ID coverage/export tooling and a larger curated reference set. Player Inventory now has export buttons for the full inventory and unknown-only inventory rows. Reference IDs now shows coverage stats, including total reference rows, mapped inventory rows, unknown inventory rows, editable rows, and queued count edits.

New module: `app/core/id_coverage.py`.


## Full reference-ID setup pass

This build expands the bundled Skyrim reference database to **2,150 rows** across **37 categories**. The current pass added **523 rows** for armor sets, unique armor, Dragon Priest masks, ingredients, food/beverages, misc crafting/clutter, spell tomes, perks, followers, factions, locations, weather, and more weapon/ammo records.

Reference IDs are still CSV-backed at `app/resources/database/skyrim_ids_sample.csv`. Use **Load CSV** to replace the active database, or **Merge CSV** to append/de-dupe your Google Sheet exports or extra ID packs without losing the built-in rows.

The count editor still edits existing inventory rows only. Adding brand-new inventory entries is intentionally held until the player inventory record insertion/repack logic is mapped safely.

## Fandom ID source-page importer

This build includes a linked-page importer for the Skyrim console-command pages requested in the project notes. The built-in CSV still loads offline, but the Reference IDs page now has **Fetch Linked Fandom Pages**.

That button downloads and parses the registered Fandom pages, then merges and de-dupes the rows into the active Reference IDs table. It is useful when you want the newest copy of the linked tables without waiting for another packaged CSV pass.

Registered pages:

- Alchemy / Food / Beverages / Potions / Poisons
- Arrows and bolts
- Blade Weapons
- Blunt Weapons
- Books
- Bows
- Clothing
- Enchantments
- Heavy Armor
- Ingredients
- Jewelry
- Keys
- Light Armor
- Miscellaneous Items
- Shouts
- Skills
- Soul Gems
- Spells
- Staves

The importer is conservative: it reads table rows, extracts name/FormID pairs, normalizes `XX` load-order placeholders, and skips empty/bad rows. You can export the merged reference CSV after importing.

## Deep Fandom ID pass

This build expands the bundled offline reference database to **3,453 rows**. The new seed pack focuses on the linked Fandom pages that were still thin in the previous build: Books, Keys, and Miscellaneous Items. It also keeps the live **Fetch Linked Fandom Pages** button so the app can pull current tables directly when internet is available.

Bundled transparency file:

```text
app/resources/database/fandom_deep_seed_rows.csv
```

Manifest:

```text
app/resources/database/reference_manifest.json
```


## Reference ID audit pass

This build adds verification tools for the Reference IDs database:

- **Run Reference Audit** checks row counts, malformed FormIDs, duplicate FormIDs, missing required fields, XX placeholder rows, and coverage for the 19 linked Fandom pages.
- **Export Audit JSON** writes the audit to a JSON file for comparison between builds.
- **Fetch Linked Fandom Pages** still harvests the current Fandom console-command tables.
- **Fetch Mutagen FormKeys** can import generated SkyrimSE FormKeys from Mutagen.Bethesda.FormKeys for broader base-record coverage. Display names from this source are derived from EditorIDs, so Fandom/xEdit names remain preferred when both exist.

This does not mean every live page row is guaranteed baked into the offline CSV; it gives the app a repeatable way to audit and import the remaining rows on your machine.


## Bleak Falls Barrow save pass

This build includes the new `SAVEDATA(2).DAT` study pass. The reference database now includes newly observed inventory IDs from the Bleak Falls Barrow milestone, including Golden Claw, Arvel's Journal, Bread, Stormcloak Armor, Imperial Studded Armor, Silver Ring, Scroll of Guardian Circle, Necklace of Minor Lockpicking, and Honed Ancient Nord Sword.

A generated report is included at:

`app/resources/database/bleak_falls_save_report.json`

The current safe inventory editor still edits existing item count rows only; it does not insert new item rows yet.

## Player Inventory readability / safety pass

This build cleans up the Player Inventory page:

- The table now shows only the useful columns: Item, Count, Category, Status, and Note.
- Single-clicking a Count cell only selects the row; it no longer opens the editor and hides the value.
- Inline count editing now uses a bounded spinbox delegate.
- The selected item editor at the top shows item name, FormID, current count, and new count separately.
- Counts are validated and clamped through one shared safe limit: 0 to 999,999,999.
- Oversized values are rejected with a warning instead of reaching the save patcher or crashing the UI.
- Added an inventory filter box for quick searching by item, FormID, category, or note.


## Inventory tabs + Save Changes build

Player Inventory now has category tabs with row counts, so weapons, armor, books, food, misc, and other groups can be filtered without cluttering the main table. Search works together with the active tab.

Use **Save Changes** to back up and write queued count edits into the currently loaded save. Use **Save Changes As…** when you want a separate edited copy instead. Count editing remains limited to existing inventory rows only.

## End-user feature pass

This build adds more end-user workflow tools without adding new side-rail research tabs:

- Save / Load now includes a Backups / Restore panel for editor-created `.bak` files.
- Player Inventory now includes quick selected-item count buttons, a queued edit preview table, remove-selected queued edit, and Copy AddItem.
- Save Changes now shows a preview of old → new inventory count edits before writing.
- Reference IDs now includes Copy FormID, Copy `player.additem`, command count, and Find In Inventory helpers.

Inventory writing is still intentionally limited to existing inventory rows.


## Header save workflow fix

- Header Editor now has **Save Header Edits** for in-place header writes with a backup.
- Header Editor still has **Save Copy…** for writing a separate edited save.
- File menu **Save Edits** / Ctrl+S is page-aware: Header Editor saves header edits; Player Inventory saves inventory count edits.
- Header saves validate the fixed player-name byte slot before writing and refresh the loaded summary after saving.

### Notification readability + direct inventory add retry

This build updates the theme stylesheet for QMessageBox/QDialog popups so Windows dialogs use readable foreground/background colors under each theme.

It also re-enables direct missing-item adds for simple base-game FormIDs only. The direct-adder now updates the inventory VSVal row count before rebuilding the player change form. The earlier disabled build only inserted item rows; Skyrim can reject that because the explicit inventory-row count still says the old value.

Direct add scope remains intentionally narrow:
- base-game/default FormIDs only
- no XX/FE/FF/plugin/temp FormIDs
- no enchanted, tempered, poisoned, owned, equipped, or custom-extra-data stacks
- backup before in-place writes
- use Save Copy for first tests


## Mapped Raw Editor pass

This build adds a Raw Editor page with mapped fixed-size fields from the save bytes.

- Mapped Fields tab: searchable table of header fields, payload structure, player change-form metadata, and actual player inventory count fields.
- Editable fields are fixed-size only. Inventory count edits write the actual player ACHR inventory count bytes, not just visual header data.
- Read-only structural fields are shown for mapping and research without letting users hand-corrupt offsets/counts.
- Save Raw Edits writes in-place with a backup; Save Raw Copy writes a separate edited copy.
- Ctrl+S/File > Save Edits is page-aware for Header Editor, Player Inventory, and Raw Editor.

Use Save Raw Copy first when testing newly mapped fields in-game.

## UESP Raw Format Reference Pass

The Raw Editor now includes a searchable **Format Reference** tab based on the UESP Skyrim save-file format notes. This is a documentation/map tab inside the editor; actual writable bytes remain on **Mapped Fields** and are still limited to fixed-size, safety-checked fields.

## UI cleanup / raw-code research pass

- Removed the standalone **Header Editor** side-rail page. Header display values are still parsed in Save / Load, and fixed-size header bytes remain visible in Raw Editor for reference, but the main editing workflow now focuses on Player Inventory and Raw Editor.
- File menu **Save Edits** / Ctrl+S is now page-aware for:
  - Player Inventory
  - Raw Editor
- Added **Raw Editor → Code Research** with the old Save Wizard-style patterns for:
  - All Skills Level 100
  - Carry Weight
  - Health/Magicka/Stamina
  - +100,000 EXP
  - Max Perk Points
  - Iron Arrow item-swap marker
- Added a **Scan Loaded Save** button in Code Research. It searches the loaded raw file and decoded payload for each old code's byte pattern and reports hit counts/offsets. This is a mapping aid only; it does not patch values by itself.
- The goal is to turn these code patterns into safe named raw editors only after controlled before/after saves confirm the exact field layout.

## Save Wizard Quick Code format pass

This build adds a fuller **Raw Editor → Quick Code Formats** tab based on the PlayerSquared Save Wizard custom quick-code format notes.

New workflow:

- searchable reference table for Types `0`, `1`, `2`, `3`, `4`, `5`, `7`, `8`, `9`, `A`, `B`, `C`, and `D`
- paste/decode area that turns quick-code lines into readable address/value/search/pointer operations
- simple copy-ready generator for standard Type `0`/`1`/`2` writes
- Type `A` mass-write generator for arbitrary byte payloads
- explicit endian/mapping warning so these codes remain research hints until a field is verified against known-good before/after saves

New module:

```text
app/core/quick_codes.py
```

## General tab + Quick Code cleanup pass

This build adds a new **General** side-rail tab for real editable values that are already safely mapped:

- Player Name
- Level
- Sex
- Current XP
- Needed XP
- Gold, when the loaded save already has an editable Gold inventory row
- Lockpicks, when the loaded save already has an editable Lockpick inventory row

The General tab writes through the same fixed-size header patcher and exact inventory payload-offset patcher used elsewhere in the editor. Missing common values stay disabled instead of being guessed or inserted blindly.

The Raw Editor quick-code area was also cleaned up:

- **Raw Editor → Quick Codes** is now split into small internal tabs: Builder, Decoder, and Reference.
- The builder/decoder are no longer stacked under the full format-reference table.
- The format table is still available, but it is tucked into the Reference subtab so the main workflow is easier to read.

File menu **Save Edits** / Ctrl+S is now page-aware for:

- General
- Player Inventory
- Raw Editor

## General tab + Skyrim quick-code preset pass

This build adds the pasted Dynamite / Almighty Skyrim Save Wizard codes as clean editable presets on the **General** page.

Preset generator values:

- All Skills Level
- Carry Weight
- Health / Magicka / Stamina
- Add EXP
- Perk Points

The General page now has two different edit styles:

- **Real save edits**: player name, level, sex, XP Pool, needed XP, existing Gold/Lockpick inventory rows, skills, and validated actor values are written through mapped save offsets with backups.
- **Quick Codes** remain available in the Raw Editor as a decoder/reference tool, but General no longer exposes experimental preset save-edit tabs.

The Quick Codes decoder now accepts a whole pasted table with credits, labels, and warnings. It ignores non-code text and decodes only complete 8-hex quick-code groups.

## General UI cleanup pass

The **General** page was simplified so the editable values are no longer stacked into one tall, compressed screen.

Changed layout:

- Added a compact action bar at the top: Reload, Preview, Save Copy, Save Edits.
- Split General into focused internal tabs:
  - **Player** for name, level, sex, XP Pool, needed XP, and read-only header context.
  - **Common** for detected editable Gold / Lockpick rows.
  - **Skills** for individual skill values.
  - **Stats** for Health, Magicka, Stamina, and effective Carry Weight.
- Added scrollable tab contents so controls do not collapse or hide when the window is shorter.
- Reduced repeated text and moved long notes away from the main edit view.

## Individual Skills pass

The **General → Skills** tab separates the old **All Skills Level** preset into individual editable skill slots.

Notes:

- The pasted Save Wizard line `40120008` means `0x12` skill entries, so this editor exposes **18 Skyrim skills**, not 12 decimal.
- The skill block is resolved with the same search anchor as the pasted All Skills preset, with the documented `05...06` → `04...06` fallback.
- Each skill shows its detected value and can be edited independently.
- **Preview Skill Edits** shows the exact payload offsets and before/after bytes before writing.
- **Apply To Save** creates a backup first; **Save Copy…** writes a separate edited save.
- File → Save Edits / Ctrl+S follows the active General subtab, so it applies skill edits when the **Skills** subtab is active.
UI theme update: added Nightingale, Daedric, Frostfall, and Whiterun themes in addition to Obsidian, Nord, and Dwemer.

## Inventory / Actor Values pass

This build adds a focused `General > Stats` tab. It edits Carry Weight, Health, Magicka, and Stamina from the same validated player actor-value block used by the working Skills tab. Recovery-rate fields were removed because they were not resolving consistently on test saves. Preview shows the exact payload offsets before any write.

`General > Common` has `Sync From Inventory` so Gold and Lockpicks are pulled directly from the current Player Inventory parse. Common inventory writes are verified after saving by reading the edited save back and checking the expected counts.

## XP Pool Player Tab Pass

- The Player tab no longer treats the editable XP field as the save-header `Current XP` display value.
- `XP Pool` now resolves the same payload slot used by the +EXP command and writes that value directly.
- Player header saves now include XP Pool when the field is changed, with readback verification.
- The separate Add-To-XP controls were removed because XP Pool can now be edited directly.

## Clean General Tabs pass

The General page now keeps only the working focused tabs:

- **Player**
- **Common**
- **Skills**
- **Stats**

Removed from General:

- dedicated Save Player / XP Pool card
- Add To XP Pool card
- Preset Save Edits tab
- Review tab

Use the top General **Save Edits** / **Save Copy** buttons for Player/Common changes. Skills and Stats still keep their own focused preview/apply buttons.

## Carry Weight pointer-chain fix

Carry Weight now follows the pasted Save Wizard chain literally:

```text
8001000C 05000000
00000000 06000000
88020004 20000000
28000004 <float>
```

After the validated skill anchor is found, the editor searches from that pointer for the second raw `20 00 00 00` marker, then reads/writes the float at `marker + 4`. The locator no longer rejects unaligned `20 00 00 00` hits, because Save Wizard searches raw bytes rather than aligned 32-bit words.


## Player-data sync pass

This build moves the major player edits onto the actual Player ChangeForm data instead of guessing from the full ESS payload.

Added/fixed:

- Gold and Lockpicks are direct-scanned from the full player ChangeForm using their base-game RefIDs, then merged back into the Player Inventory/Common views.
- Existing Gold/Lockpick edits now work on saves where the older inventory-cluster picker chose the wrong block.
- zlib-compressed player ChangeForms are supported for fixed-size player edits. The editor decompresses the player data, patches it, recompresses it, updates the ChangeForm length fields, and shifts downstream file-location offsets when the recompressed size changes.
- Skills, XP Pool/Add EXP, Health, Magicka, Stamina, and Carry Weight now operate on the player ChangeForm data, so Classic PC saves with compressed player records are handled.
- Carry Weight is split into two explicit fields:
  - **Carry Weight Base**: first `20 00 00 00` marker after the validated actor/skill block.
  - **Carry Weight SW Target**: second `20 00 00 00` marker, matching the posted Save Wizard pointer chain.
- **Set Carry 1B** in `General > Stats` sets both carry targets when both are found.

Window title for this build: `Skyrim Save Lab - cleaned general tabs`.


## Effective Carry Weight UI pass

Carry Weight Base / ActorValue 32 is no longer exposed as a normal editable field. In tested saves it stayed at the vanilla 300 baseline while the Save Wizard pointer target matched the effective carry-capacity value. The Stats tab now shows a single Carry Weight field for that effective/SW target.


## Player Inventory storage-info / add safety pass

This build keeps existing inventory-row count edits as the safe path and makes missing-item insertion fail closed unless the opened save passes a strict direct-insert preflight. Missing items normally use the console workflow: copy `player.additem`, add the item in-game, save, reopen the save, then edit the existing row count inside the editor.

Player Inventory now includes a **Selected Row Storage Info** panel. Selecting a row shows the exact encoded RefID bytes, player-data offset, payload offset, virtual offset, raw signed count, displayed count, extra/flag byte, confidence, editability, and whether the player ChangeForm is compressed.

The Item Database/AddItem table now shows **Preflight direct add** only when the current save layout proves a safe inventory count field and insertion marker. The PC saves tested so far fail that preflight or use compressed player ChangeForms, so they remain console-command only for missing items.

## Inventory research/pass update

The Player Inventory tab now has a **Research / Preflight** subtab. It explains the currently loaded save's inventory storage, whether direct missing-item insertion is enabled or fail-closed, and why. Existing inventory rows remain the safe direct-edit path. Missing items default to `player.additem`, then save/reopen and edit the newly existing stack.

The selected-row storage panel can now be copied or exported to CSV. It includes encoded RefID bytes, player-data offset, payload offset, raw signed count, displayed count, extra flag, compression state, confidence, and editability.


## Inventory add/remove workflow update

The Player Inventory editor now treats two different cases separately:

- **Existing row edits** remain the safe path. The editor patches only the signed 32-bit count at the detected row's count field.
- **Dormant zero-count rows** can now be re-added safely by setting New Count above 0. Controlled saves showed that removing an item can leave its row in the player inventory list with a count of `0`; re-adding that item changed the same row to a negative raw count such as `FF FF FF FF` for displayed count `1`. The editor now mirrors that sign style for dormant non-currency rows instead of inserting new bytes.
- **Truly missing rows** still stay console-command only unless the save passes strict insertion preflight. Direct row insertion remains disabled for the tested layouts because the inventory count field does not match the currently detected simple-row count.

Controlled save comparison used for this pass:

- Iron War Axe `00013790` stayed at the same player-data offset `0x32D`.
- Removed/dormant state: `41 37 90 00 00 00 00 00`.
- Re-added state: `41 37 90 FF FF FF FF 00`.
- Gold/Lockpick duplicate direct-scan false positives outside the main inventory cluster are now filtered out when the main cluster already contains those FormIDs.

## Inventory tooltip layout update

The large **Selected Row Storage Info** panel has been removed from the visible Current Inventory layout so the inventory table has more room. Storage details now live on the compact **Storage Info** button as a tooltip. Click the button to open the full storage details in a small dialog, or use **Copy Info** / **Export Storage CSV** from the same row.

Window title for this build: `Skyrim Save Lab - inventory tooltip layout`.


## PS4 direct missing-item add update

Controlled PS4 saves showed the inventory-list count is not always equal to the number of simple 8-byte rows shown in the UI. In the uploaded test saves, the editor detected 103 simple editable rows, while the real inventory-list count stored immediately before the list was 106 or 107. The extra rows are complex/unmapped inventory entries after the simple stack run.

Direct base-game item insertion now works for saves that pass this layout preflight:

- find the inventory-list VSVal count before the first simple row, accepting counts greater than the simple-row count;
- insert the new simple stack after the last simple 8-byte row and before the following complex rows;
- increment the real inventory-list count;
- expand the Player ChangeForm and shift downstream offsets.

Newly inserted plain stacks use the controlled save's signed-count style: `RefID + negative int32 count + 00`. This is intended for base-game/default FormIDs such as `000F8318`. Plugin/light/temp FormIDs still require more FormIDArray mapping before they are safe.

Window title for this build: `Skyrim Save Lab - PS4 direct item add`.


## Inventory direct-add correction

Controlled PS4 saves showed that brand-new item rows are not inserted directly after the last simple 8-byte row. The real inventory list can contain several complex/unmapped rows after the visible simple stack run. Brand-new simple rows must be inserted at the end of the full inventory list, immediately before the next `BShkbAnimationGraph` player-data field.

The direct-add patcher now:

- updates the inventory VSVal count;
- inserts the new simple row at the full-list boundary, not after the last visible row;
- stores brand-new counts as positive `int32` values, matching the controlled added-item save;
- merges known tail-inserted rows back into the inventory parser so the editor can verify the add.

Dormant zero-count rows still use the existing-row edit path. Plugin/light/temp FormIDs remain blocked until FormIDArray mapping is implemented.


### PS4 fake/minimal inventory row test pass

This build keeps missing-item adds staged until Save Edits, but now exposes a **Preview Fake Row** button on Player Inventory -> Item Database / AddItem. It shows the exact generated row bytes, inventory count VSVal change, and player-data insertion offset before writing.

For a simple base-game item with no extra data, the generated row is:

```text
Encoded RefID (3 bytes) + signed int32 count (4 bytes) + ExtraDataCount/flag 00
```

For example, Chillrend Lv 46+ / `000F8318` at count 1 generates:

```text
4F 83 18 01 00 00 00 00
```

The save must also increment the inventory-list count, grow the player ChangeForm, shift downstream offsets, and rebuild the compressed payload. If the row appears in the editor after reload but not in-game, the next research target is extra-data/template requirements for that item type rather than the simple count field.

## Raw JSON editor pass

The Raw Editor's Parsed JSON tab now has a cleaner JSON workspace:

- Search parsed JSON text with Find Next / Find Previous.
- Validate JSON syntax with line/column error reporting.
- Format or compact JSON for easier review.
- Use Undo or Reload Parsed while experimenting.
- Export the edited JSON text to a `.json` file.

Note: the parsed JSON tab is still a research/export view. It does not round-trip arbitrary JSON edits back into Skyrim save bytes. Use Mapped Fields or the dedicated editor pages for actual save-byte writes.


## Mapped fields cleanup pass

- Removed the main-window **Form ID Tools** and **Scanner** pages from the side rail to reduce clutter. Reference IDs remains the database/search page.
- Removed **Raw Editor → Code Research**; quick-code format helpers remain under **Quick Codes**.
- Removed **Player Inventory → Research / Preflight**; direct-add safety is now shown inline in the AddItem workflow instead of a separate research page.
- Improved **Raw Editor → Mapped Fields** so edits can be staged from a selected-field edit bar or by editing the New column directly. Use **Save Raw Copy** first when testing new mapped offsets.


## QSS warning fix

Removed the unsupported Qt stylesheet rule `selection-behavior: select-rows;` from the shared theme stylesheet. Qt selection behavior is now handled only through `QTableWidget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)`, which avoids the repeated startup warning:

```text
Unknown property selection-behavior
```

Window title for this build: `Skyrim Save Lab - qss warning fix`.

## About page update

Updated the About page credits and links:

- Skyrim PS4 save editor created by ProtoBuffers.
- Based on the UESP Skyrim save file format reference: https://en.uesp.net/wiki/Skyrim_Mod:Save_File_Format
- Originally intended to fix Save Wizard saves using the research spreadsheet: https://docs.google.com/spreadsheets/d/1pln64WRA8QhhrW1QBDEn97HEbp4gdvBNd3GnrC4Bg5c/edit?gid=1795290740#gid=1795290740
- Free PS4 save decryption community: https://discord.gg/protobuffers

Window title for this build: `Skyrim Save Lab - about update`.

## Raw Value Overwrite Cleanup

This build changes **Raw Editor → Mapped Fields** so edits happen directly in the **Value** column instead of using a confusing separate **New** column. Editable fixed-size rows show their current value in-place; changing that cell stages the replacement value. Reverting the cell to its original value clears the pending edit.

The About page was also updated for public testing with the current feature list, PS4 focus, backup warning, UESP/Save Wizard references, and ProtoBuffers Discord link.

## Raw value readability pass

- Raw Editor -> Mapped Fields now opens a larger readable value editor when the Value cell is double-clicked.
- Added a Big Edit button for the selected mapped field.
- The inline Value editor now uses a high-contrast editor style so text stays visible on selected dark rows.
- Widened the Value column and increased mapped-field row height.


## Cleaned IDs and DLC XX resolve pass

- Item Database rows now de-duplicate by the active/resolved FormID, so repeated source rows no longer clutter AddItem search results.
- `XX######` DLC placeholders are resolved from the currently loaded save's plugin list whenever the source/editor ID/name/notes identify Dawnguard, HearthFires, or Dragonborn.
- Added stronger official-DLC inference for rows imported from mixed sources, including common Dragonborn/Dawnguard keywords such as Stalhrim, Bonemold, Chitin, Crossbow, Bolt, and Auriel.
- Inventory display name lookup now prefers save-specific resolved DLC IDs before loose suffix fallback, reducing wrong labels when multiple DLC/mods share object-ID suffixes.
- The low-level inventory scanner remains conservative: existing simple rows stay editable, while full FormIDArray insertion for plugin/light IDs remains a future mapped-list walker task.

Window title for this build: `Skyrim Save Lab - cleaned IDs and DLC XX resolve`.

## Dragon Souls / DragonsAbsorbed common edit

- Added **General → Common → Dragon Souls**.
- The value is mapped from the global variable `DragonsAbsorbed` (`0001C0F2`). In Skyrim save RefID bytes this resolves to `41 C0 F2`.
- The editor patches the fixed 32-bit float value attached to that global variable inside Global Data type 3.
- The same value also appears in **Raw Editor → Mapped Fields → Global Variables** as `Dragon Souls / DragonsAbsorbed` for low-level inspection.

Window title for this build: `Skyrim Save Lab - dragon souls common tab`.


## General Dragon Souls Save Fix

- General > Save Edits / Save Copy now include Common global edits such as Dragon Souls / DragonsAbsorbed.
- General preview now lists Dragon Souls changes instead of reporting "No General changes" when only the Common global changed.
- Dragon Souls writes are verified after saving by reading the DragonsAbsorbed global back from the rebuilt save.

Window title for this build: `Skyrim Save Lab - general dragon souls save fix`.


## Live player name/level mapper

This build maps the real in-game player name and level from ChangeForm `400007` when available. Header name/level are still written for save-menu consistency, but General -> Player now loads and writes the live ChangeForm values first.

Findings from uploaded saves:
- Live player name is a length-prefixed UTF-8 string inside ChangeForm `400007`.
- Modern PS4/SSE saves and tested PC saves store live level as a u32 at decoded ChangeForm `400007` offset `0x08`.
- Saves where only the header was edited can show a different header value than the real live value.

Window title for this build: `Skyrim Save Lab - live player name level mapper`.


## Skill Max Test Build

- Skills tab now allows values from 0 to 999 for testing.
- Added quick buttons: Set All 1, Set All 100, and Set All 999; removed the unstable 1000+/999,999,999 test paths.
- Normal Skyrim skill max is still 100; extreme values are experimental and may be clamped, ignored, or behave strangely in-game.
- The skill block detector now still recognizes saves after high-value skill edits so the editor can reopen them.

Window title for this build: `Skyrim Save Lab - skill max test`.

## Quests Removed Cleanup

- Removed the Quests side-rail page because the current quest decode view was not readable/useful enough for normal editing.
- Quest research code may remain in the project for future controlled-save comparisons, but it is no longer exposed in the main editor UI.
- The side rail is now back to: Save / Load, General, Player Inventory, Plugins, Reference IDs, Raw Editor, About.

Window title for this build: `Skyrim Save Lab - skill cap 999`.



## Skill cap 999 cleanup

- Skills are capped at 999 for safer testing.
- Removed the 999,999,999 quick button and validation range.
- Skill-block detection no longer treats values above 999 as a safe editable skill block.


## Skill cap 999 cleanup

- Skills now use 999 as the test maximum.
- Quick buttons are now exactly: Set All 1, Set All 100, Set All 999.
- Values above 999 are rejected by the skill editor and detector.

Window title for this build: `Skyrim Save Lab - skill cap 999`.


## Skill max 999,999 test

- Skills now allow values from 0 to 999,999 for testing.
- Quick buttons are: Set All 1, Set All 100, Set All 999, and Set All 999,999.
- This is an experimental test path because 1,000 worked but 999,999,999 did not.
- Make a backup before trying 999,999.

Window title for this build: `Skyrim Save Lab - skill max 999999 test`.


## ProtoBuffers header and app icon update

- Window title now uses `Skyrim Save Lab - created by ProtoBuffers`.
- About page header now reads `Skyrim Save Lab created by ProtoBuffers`.
- Added the Skyrim icon to `app/resources/icons/skyrim.png` and generated `skyrim.ico`.
- PyInstaller spec now applies the ICO through the `icon=` field so the built EXE uses the same icon.

Window title for this build: `Skyrim Save Lab - created by ProtoBuffers`.


## Plugin page layout update

- Expanded the Plugins page table so it uses the available page height instead of only showing a few plugins at once.
- Added a plugin filter box and full/light/showing count summary.
- Window title for this build: `Skyrim Save Lab - expanded plugins view`.


## Real Dragon Souls mapper

- Controlled saves with spendable Dragon Souls at 1, 100, and 100,000 proved that the old DragonsAbsorbed global (0001C0F2 / 41 C0 F2) is not the spendable Dragon Souls pool.
- General > Common > Dragon Souls now reads/writes the live actor-value float in ChangeForm 400014 at relative offset 0x49A5.
- Raw Editor > Mapped Fields now exposes this as `Dragon Souls / Spendable Actor Value`; the old DragonsAbsorbed global is shown read-only when found.


## Race changer test

General → Player now includes an experimental Race dropdown for the 10 vanilla Skyrim races.
The editor writes the mapped race RefID pair in Player ChangeForm `400014`, the optional Live Player mirror `400007` when present, and the save header race text.
Known vanilla Race FormIDs use the `RaceNameRace` convention, for example `NordRace` = `00013746` = save RefID bytes `41 37 46`.

Use Save Copy and test on a backup first. Race edits can affect appearance, powers, and actor data in ways that may need more mapping.


## Optional live level fix

Some early-game saves do not contain the mapped live level slot in ChangeForm `400007` yet. The Player save path now treats that live level field as optional, so name/race/XP/common edits are not blocked when the field is absent. Header level still syncs where available; live level verification is only enforced when the live slot exists.


## Carry weight total fix

Carry Weight in General > Stats now displays the intended total instead of only the Save Wizard modifier slot. When the modifier slot exists, the editor writes `desired total - base ActorValue 32`; when it does not exist, it falls back to writing ActorValue 32 directly. This fixes saves where the previous modifier-only path did not affect the in-game carry limit or disabled the field.

Window title for this build: `Skyrim Save Lab - carry weight total fix`.

## Magic research tab

- Added a new main **Magic** tab.
- This pass is read-only and focuses on making magic data understandable before any writes are enabled.
- Scans loaded reference rows for spells/shouts/powers, resolves DLC `XX` IDs against the save plugin list, and searches mapped player/magic data for the encoded RefID bytes.
- Shows the likely **Magic Favorites** global data block (`Global Data` type `109`) with raw samples and RefID-like candidates.
- Adds CSV export for magic hits so controlled saves can be compared: spell unknown, spell learned, spell favorited, spell removed.
- Magic add/remove/favorite writes are still disabled until controlled saves prove the exact safe structures.

Window title for this build: `Skyrim Save Lab - magic research tab`.

## Magic / Shouts split pass

The Magic page now separates discovered/known magic records into dedicated tabs:

- **Spells** uses normal `player.addspell` / `player.removespell` command helpers.
- **Shouts** is its own tab because shout entries are Word-of-Power records and use `player.teachword` / `player.unlockword` helpers.
- **Powers / Abilities** is ready for power/ability reference rows when the active database includes them.
- **Favorites / Hotkeys Data** keeps the raw Global Data 109 Magic Favorites block visible for controlled-save comparison.

Direct save-writing for spell learning, shout learning, and favorites is still disabled. The current build intentionally stays read-only for magic save structures and provides console-command helpers until controlled PC save comparisons prove the exact learned/unlocked/favorite byte layout.

## Magic checkbox workflow

The Magic page now supports a simple checkbox workflow for known magic records:

- **Spells**: check to queue `player.addspell`; uncheck a detected spell to queue `player.removespell`.
- **Powers / Abilities**: same add/remove flow as spells.
- **Shouts**: check to queue both `player.teachword` and `player.unlockword` for the selected word ID.
- **Checkbox Script**: shows the generated Skyrim console script from all queued checkbox changes.

Direct ESS writing for learned spells/shouts is intentionally still disabled because the save stores learned magic in variable-length actor data that must be mapped before inserting/removing entries safely. The checkbox workflow produces a safe `bat` script: run the commands in Skyrim, then make a new save.

Unchecking a learned shout is marked unsupported because Skyrim does not expose a reliable `unteachword` / re-lock command equivalent.

## Magic direct learned-list patch

Uploaded PC and decrypted PS4 saves exposed the learned-magic list inside Player ChangeForm `400014`:

- Layout: `u32 count` followed by `count` compact 3-byte RefIDs.
- PC samples detected high-confidence lists with 167, 178, and 228 learned entries.
- Decrypted PS4 samples detected the same structure with early-game counts of 5 or 6 entries.

The Magic checkbox workflow now has two paths:

- **Checkbox Script** still generates safe in-game console commands.
- **Preview Direct Patch / Apply To Save / Save Edited Copy** patches the learned-magic list directly, with backup support when writing the loaded save.

Direct patching updates learned-list membership for spells, powers/abilities, and shout word IDs. For shouts, the direct save patch teaches/removes learned word-list membership; the command script still provides `teachword` + `unlockword` for true in-game dragon-soul unlock behavior. Magic Favorites / hotkey writes remain read-only until their exact structure is separately verified.

## Shout direct patch fix

The previous direct Magic patch used the player learned-magic array for every magic checkbox row. That works for normal spells and powers, but it does **not** work for shouts. The uploaded saves show shouts are stored as individual Word-of-Power ChangeForms instead:

- ChangeForm ref = the 3-byte Word-of-Power RefID.
- Observed Word-of-Power form type = `34`.
- Observed payload = `49 00 XX 00 00 00`.
- `XX = 00` means the word record exists but is still locked.
- `XX = 01` means the word is unlocked.

The Magic > Shouts tab now reads those Word-of-Power ChangeForms directly. Direct Apply now routes shout rows through the shout-word patcher instead of the learned-spell list:

- Checking an existing locked shout word flips the word unlock flag from `00` to `01`.
- Unchecking an existing unlocked shout word flips the word unlock flag from `01` to `00`.
- Checking a missing shout word inserts a new unlocked Word-of-Power ChangeForm at the end of the changeform section and updates the changeform count / table offsets.
- The console script path still emits `player.teachword` and `player.unlockword` as a safe fallback.

Spells and powers still use the learned-magic list in Player ChangeForm `400014`. Magic Favorites / hotkeys remain read-only.

## Direct magic/shout confirmation dialog fix

The Apply Direct Patch and Save Edited Copy confirmations now use a resizable dialog with a scrollable patch-plan preview. This prevents long add/remove lists from pushing the Apply/Cancel buttons off screen when many spells, powers, or shout words are queued.

Window title for this build: `Skyrim Save Lab - magic dialog scroll fix`.

## Magic Powers / Abilities update

Powers and abilities are now split into their own Magic subtabs instead of being grouped together.

- `Magic > Powers` covers active power-style SPELL records such as racial powers, Nightingale powers, standing-stone powers, vampire powers, and Beast Form.
- `Magic > Abilities` covers passive or active-effect-style SPELL records such as blessings, standing-stone effects, Imperial Luck, Ancient Knowledge, and similar effects.
- Checkboxes for both tabs use the same direct learned-magic list patcher as normal spells.
- Shouts still use the separate Word-of-Power patcher and are not written through the learned-magic list.
- A bundled `skyrim_powers_abilities_seed_rows.csv` reference file is merged into the default ID database at startup so the tabs are populated without a manual CSV import.

Safety note: some ability-like effects are normally temporary, quest-controlled, race-controlled, vampire/werewolf-controlled, or standing-stone-controlled. The editor can add/remove their SPELL records, but Skyrim's normal scripts may later reapply or remove them depending on game state.


## Emergency magic/shout recovery note

Direct magic/shout save-writing is disabled in this build after real-save corruption was reported. The Magic checkboxes now generate a safe Skyrim console `bat` script only.

Recovery if you used an older Direct Apply build:

1. Open the corrupted save in the editor.
2. Go to **Magic** and click **Restore Latest Backup**.
3. The editor looks beside the save for files named like `SAVEDATA.DAT.YYYYMMDD_HHMMSS.bak` or `SaveName.ess.YYYYMMDD_HHMMSS.bak`.
4. It backs up the corrupted file again, then copies the newest automatic backup over the loaded save.

Manual recovery is the same: rename the corrupted save out of the way, copy the newest `.bak` beside it, and rename that backup back to the original save filename.

Safe magic workflow:

1. Check the spells, powers, abilities, or shouts you want.
2. Click **Save Checkbox Script**.
3. Run the generated script in Skyrim with `bat <scriptname>`.
4. Save in-game normally.


## Build single EXE

This build uses a PyInstaller **one-file** spec. Run:

```bat
build.bat
```

The output will be:

```text
dist\SkyrimSaveLab.exe
```

You no longer need to ship the full `dist\SkyrimSaveLab\` folder for the normal build. Keep in mind the one-file EXE starts a little slower because PyInstaller unpacks bundled resources at launch.


## Magic safe-script workflow pass

The Magic tab now defaults to a **Safe Add/Unlock Only** workflow. This is the recommended way to add spells, powers, abilities, and shout words without corrupting saves.

- Direct magic/shout save-writing remains disabled.
- Checkbox changes generate a Skyrim console batch script instead of editing the ESS/DAT bytes.
- Default script name is `skyrim_magic_changes.txt`.
- In-game command is:

```text
bat skyrim_magic_changes
```

Script modes:

- **Safe Add/Unlock Only**: emits only `player.addspell`, `player.teachword`, and `player.unlockword`. Removal requests are written as skipped comments. This is the safest mode and the default.
- **Match Checkboxes**: can also emit `player.removespell` for normal spells, powers, and abilities. Shout removals are still skipped because Skyrim has no safe `unteachword` equivalent.

Recommended flow:

1. Open the save and go to Magic.
2. Check the spells/powers/abilities/shout words you want.
3. Keep Script Mode on **Safe Add/Unlock Only**.
4. Click **Save Safe Script** and save it as `skyrim_magic_changes.txt`.
5. Put the file where Skyrim's console `bat` command can read it.
6. In-game, open the console and run `bat skyrim_magic_changes`.
7. Wait a few seconds, open the Magic menu to let Skyrim refresh, then make a new in-game save.

This avoids raw learned-magic list edits entirely and lets Skyrim update its own actor/magic structures.

## Magic experimental save-copy pass

The Magic tab now has two workflows:

- **Save Safe Script**: the recommended route. It writes `player.addspell`, `player.teachword`, and `player.unlockword` commands to a text file that Skyrim applies in-game.
- **Save Experimental Copy**: writes add/unlock-only changes to a new save file for testing. It never overwrites the loaded/original save.

Experimental direct-copy safety limits:

- Spell, power, and ability checkboxes only add IDs to the detected player learned-magic list.
- Shout checkboxes only flip existing Word-of-Power unlock flags from locked to unlocked.
- Missing shout Word-of-Power records are skipped instead of inserted, because synthetic shout-record insertion corrupted saves.
- Unchecked/removal changes are skipped by the direct-copy path; use the safe script workflow if you need `player.removespell` commands.
- The edited copy is re-opened by the parser after writing and the Magic preview shows a validation summary.

Use the test copy in-game first. Keep the original save until the copy loads and behaves correctly.

## Magic edited-save copy button fix

The Magic page now makes the two output paths explicit:

- **Save Console Script (.txt)** writes a Skyrim console batch script only.
- **Save Edited Save Copy (.ess/.DAT)** writes a binary Skyrim save copy for in-game testing.

The edited-save button now forces the output extension to `.ess` or `.DAT` based on the loaded save. If a `.txt` name is selected by mistake, the editor changes it back to the source save extension and refuses to overwrite the loaded/original save.

Window title for this build: `Skyrim Save Lab - magic save copy extension fix`.

## Synced working-save workflow

This build adds a shared in-memory working copy for Magic edits:

1. Open a save. The editor copies the save bytes into memory.
2. In Magic, check spells/shouts/powers/abilities.
3. Click **Stage Checked Magic Changes**. This patches the in-memory working save only and re-scans it.
4. Use **File > Save Working Save** to overwrite the loaded save with a backup, or **File > Save Working Save As…** to write a separate .ess/.DAT.

The old per-tab Magic edited-copy save button has been replaced by working-copy staging so the Magic tab stays synced with the same loaded save state.

## Magic quick unlock buttons

The Magic page now includes two bulk checkbox helpers:

- **Unlock Visible Tab** checks every visible row in the currently selected Magic subtab.
- **Unlock All Magic** checks every loaded Spell, Shout, Power, and Ability row.

These buttons only queue checkbox changes. They do not overwrite the original save. Use **Stage Checked Magic Changes** to update the synced in-memory working copy, then use **File > Save Working Save** or **File > Save Working Save As…** after the working copy re-scans cleanly.

## Magic tab cleanup pass

The Magic page has been simplified around the synced working-save workflow.

Main tabs now focus on the actual unlock targets:

- **Spells**
- **Shouts**
- **Powers**
- **Abilities**

The old preview/script/debug controls were removed from the normal toolbar. Raw scan data, Magic Favorites data, and reference IDs are now grouped under **Magic > Advanced** for troubleshooting only.

New normal workflow:

1. Open a save.
2. Go to **Magic**.
3. Search/filter if needed.
4. Check individual rows or use **Unlock Visible Tab**, **Unlock All Spells**, **Unlock All Shouts**, **Unlock All Powers**, **Unlock All Abilities**, or **Unlock All Magic**.
5. Click **Apply To Working Save**.
6. Use **File > Save Working Save** or **File > Save Working Save As…**.

The Magic tab no longer has its own save-copy button. Saving stays centralized through the File menu so every editor tab remains synced to the same in-memory working save.


## Working-save auto-sync update

The Magic tab no longer requires an Apply/Stage step before saving. Magic checkbox changes remain pending while you edit, then **File > Save Working Save** automatically syncs those pending Magic changes into the in-memory working save, validates the edited bytes by re-opening them, creates a backup, and writes the loaded save.

Recommended workflow:

1. Open a save.
2. Check/uncheck Magic rows or use Unlock All buttons.
3. Use **File > Save Working Save** to overwrite the loaded save with a backup, or **File > Save Working Save As…** to create a copy.

The **Sync Now** button is optional and only exists for manual testing/re-scanning. It is not required for normal saving.

### Shout direct-save limitation

The Magic tab now disables direct-save checkboxes for shout words that are completely missing from the save. Direct save can only flip an existing Word-of-Power record from locked to unlocked. Missing shout words still require Skyrim's own console commands (`player.teachword` and `player.unlockword`) because synthetic insertion of new Word-of-Power ChangeForms was the path that corrupted saves during testing.

## Shout direct-save honesty fix

The Magic page now separates directly saveable shout words from script-only shout words more clearly.

- **Unlock Saveable Shouts** checks only shout Word-of-Power records that already exist in the loaded save.
- **Unlock All Magic** also skips missing shout Word-of-Power records for direct save safety.
- Missing shout words remain script-only because synthesizing brand-new Word-of-Power ChangeForms previously caused corrupted saves.
- If a queued Magic save contains only script-only missing shout words, File > Save Working Save now reports that there are no directly saveable Magic changes instead of silently appearing to save nothing.
- Script-only shout requests are preserved in the queue after directly saveable Magic changes are synced, so they can still be exported as console commands.

Direct saving currently supports:

- Adding spells, powers, and abilities to the learned-magic list.
- Unlocking shout words that already have Word-of-Power records in the save.

Direct saving intentionally skips:

- Missing shout Word-of-Power records.
- Removing spells/powers/abilities.
- Locking/removing shouts.

## Active Effects tab update

The Magic page now has a separate **Active Effects** tab for effect-style magic entries that were previously mixed into Abilities.  The bundled powers/abilities seed database now classifies blessings, standing-stone effects, rested effects, food effects, and waterbreathing-style effects under Active Effects so they are easier to find.

The traceback from **Unlock Saveable Shouts** was also fixed. The helper now accepts the `direct_saveable_only` argument used by the shout button.

## Magic UI cleanup update
- Magic save/sync success messages now use the status bar instead of pop-up dialogs.
- File > Save Working Save writes the current working save directly after creating a backup.
- Magic tables use a cleaner Unlock/Unlocked checkbox column.
- The optional Sync Now button was removed from the normal Magic toolbar; saving automatically syncs pending Magic changes.

## Shout insertion order fix

This build updates the experimental missing-shout save path after comparing the uploaded PC saves with the early PS4 save sequence.

Observed working PC saves store real Word-of-Power ChangeForms in the static/default-ref ChangeForm area, right after existing static records such as FUS and before the first high `80xxxx` temporary/dynamic ChangeForm. The older experimental writer appended synthetic missing shout records at the end of the ChangeForm section. The local parser could re-open those records, but Skyrim may ignore them for shout-menu discovery.

The writer now inserts missing Word-of-Power records beside the existing static shout-word records and updates the downstream FileLocationTable offsets.

### 2026-06-09 Dragon Souls open-save crash fix
- Fixed an `OverflowError` when opening early/fresh saves whose mapped Dragon Souls candidate contains a sentinel float such as `-FLT_MAX`.
- The UI now disables Dragon Souls editing for that save instead of crashing, and reports that the actor-value slot appears uninitialized.
