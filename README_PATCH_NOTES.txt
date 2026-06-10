Skyrim Save Lab - Tools / Diagnostics Stability Pass

Added:
- New visible Tools page.
- Build Diagnostics Report button.
- Copy Report and Export Report actions.
- Database Audit table showing duplicate FormIDs, malformed rows, XX placeholders, weak categories, loaded save info, unknown rows, and pending edits.

Kept safe:
- No new inventory parser changes.
- No new direct Dragon Souls writes.
- No new shout discovery writes.
- Inventory editing remains limited to stable rows.

Validation:
- python -m compileall app run.py
