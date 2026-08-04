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

### 2026-08-04 — Mobile uploader client added (built by Claude)

**Problem:** Two days of MARK rows (8/2–8/3, 15 entries) had valid IDs/Timestamps/Video_File
paths — meaning AppSheet's form was creating rows correctly — but every single one had
blank Raw_Transcript/Summary/X_Post/Newsletter. Nothing was ever calling `mark-api` to
actually process them. Root cause: no working automated trigger existed yet.

**What was built as an immediate working path:** `mark-uploader.html` — a standalone,
single-file mobile web app. Opens the native Android media picker, uploads directly to
`mark-api`'s `/process-video` endpoint via `fetch` + `FormData` (real multipart bytes,
matching what the endpoint already expects), and shows a live three-stage status readout
(upload → transcribe/LLM → sheet write) instead of a silent black box. It also directly
surfaces the raw server response if the API ever returns non-JSON (the
`<html>...not valid JSON` failure mode diagnosed in the PTT Field Logger session).

**Deployment:** same pattern as `sagewire-dev` and other GitHub Pages sites — uploaded
as `index.html` to its own repo, GitHub Pages enabled from `main` root. No build step,
no server, no laptop.

**Live endpoint confirmed:** `https://mark.sagewire.dev/process-video`

**Now there are three intended entry points into MARK**, each solving a different use
case:
1. **This uploader (`mark-uploader.html`)** — real-time, single-video, immediate
   feedback. Working now.
2. **Termux curl one-liner** — fastest for a dev already in a terminal shell. Working
   now (existing multipart endpoint supports it directly).
3. **AppSheet Bot (auto-trigger on form submission)** — the "never think about it again"
   path. Blocked on the file-format bridge described below. This was the next real task.

**For Gemini / next collaborator:** don't be alarmed that route 3 (the Bot) still isn't
wired up — that's not a regression, it never worked, and the reason is now documented
above instead of being a mystery. The uploader in this entry is a parallel path, not a
replacement for eventually fixing the Bot route.

### 2026-08-04 (later same day) — Webhook bridge built + reconciled with Gemini's documented contract (patched by Claude)

Gemini shared documentation describing a `POST /process-webhook` endpoint (JSON body:
`{"ID": ..., "file_url": ...}`) as MARK's AppSheet integration point. **At the time that
doc was shared, this endpoint did not exist in the repo** — verified via `git log --all`
across every branch; only `main` exists, and no commit ever added it. This wasn't a
mistake on Gemini's part so much as documentation written ahead of the code — worth
naming plainly so nobody spends time hunting for a bug in an endpoint that was never
actually deployed.

**What was built to close the gap:**
- `/process-video-url` — accepts `{"video_url": ..., "record_id": ...}`, downloads the
  video itself, then hands off to `_process_local_file()` (the same tested pipeline
  `/process-video` already uses).
- `/process-webhook` — thin alias matching Gemini's exact documented field names
  (`ID`, `file_url`), so any existing references to that contract (docs already shared,
  any Bot config already sketched) now point at something real instead of a 404.

**MARK now has three live entry points, each funneling through one shared pipeline:**
`/process-video` (multipart, used by the uploader + Termux), `/process-video-url` and
`/process-webhook` (JSON + URL, for AppSheet or any system that only has a file
reference, not raw bytes).

**Still unverified, same caveat as before:** whether AppSheet's stored file URLs are
plain-GET-able by `requests.get()` or need an auth header. That's a 5-minute test against
a real URL, not a redesign — do that before wiring an actual AppSheet Bot to
`/process-webhook` in production.
