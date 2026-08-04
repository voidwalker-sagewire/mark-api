# M.A.R.K. (Mobile Automated Record Keeper) — Build Log

*Automated video transcription, story extraction, subtitle burning, and social formatting.*

## Service Blueprint
- **Name:** mark-api (Mobile Automated Record Keeper)
- **Port:** 5009
- **Stack:** FastAPI (Python), OpenAI Whisper (STT), FFmpeg (Video processing), LLM API (Metadata & Caption extraction)
- **Deployment:** DigitalOcean Droplet via Coolify / Docker container with persistent storage.

## Initial Setup & Architecture Rules
1. **Decoupled Service:** Operates independently via a clean API contract. Can be called by a mobile shortcut, a Telegram bot, or a frontend web form.
2. **Mobile-First Workflow:** Code written via chat-driven development, deployed via GitHub web editor and Coolify.

## Bug Fix Log

### 2026-08-03 — Blank key column on Sheets append + silent write failures (patched by Claude)
**Found while cross-referencing `main.py` against the MARKMobile-539435717 AppSheet documentation.**

- **Bug 1 — orphaned rows on append:** `update_or_append_sheet()`'s append
  branch wrote `["", "", "", raw_transcript, ...]`, leaving columns A (ID)
  and B (Timestamp) blank. Column A is the MARK table's AppSheet **key**
  column (Initial Value `UNIQUEID()`), which only auto-fills when AppSheet
  itself creates the row — never when a row is inserted externally via
  gspread. Any row created by this API's append path therefore had no valid
  key: unreferenceable by a later `record_id` update, and invisible/broken
  in the app's Card Deck view (also missing Video_File thumbnail, col C).
  **Fix:** the API now generates its own `uuid4` ID and UTC timestamp on
  append, so every row it creates has a valid key from the start.

- **Bug 2 — failures were invisible:** `update_or_append_sheet()` caught all
  exceptions and only `print()`-ed them, returning nothing either way.
  `process_video()` then always returned `{"status": "success"}` regardless
  of whether the sheet write actually worked. **Fix:** the function now
  returns `True`/`False`, and the endpoint reports `"status":
  "partial_success"` with `"sheet_write_ok": false` when the transcript/LLM
  step succeeded but the Sheets write didn't — instead of masking it.

- **Known limitation, not fixed (flagging for whoever picks this up next):**
  Video_File (col C) is still left blank on append. This API only ever has
  a local temp file (written to `/tmp`, deleted in `process_video`'s
  `finally` block) — never a hosted URL — so there's nothing valid to put
  there yet. Populating it would require adding a video hosting/upload step
  (e.g. push to Drive via the service account already used for Sheets, then
  write the resulting share URL) before this function runs.

- **Open question, not verified in this session:** if an AppSheet
  Automation/Bot calls this endpoint automatically (the app's schema shows
  a configured Bot — see "Process for Trigger" / "New step Output" process
  tables), confirm it's actually sending `record_id` as a form field and
  the video as real multipart file bytes. AppSheet's webhook step often
  sends a file as a Drive link/reference rather than raw binary data, which
  this endpoint (`UploadFile`) would not accept as-is.
  
