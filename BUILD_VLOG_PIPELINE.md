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

### 2026-08-04 (fourth pass) — Two real Google Cloud API blockers found + fixed (not code)

First real end-to-end test kept returning `sheet_write_ok: false` even after all prior
fixes. Turned out to be two separate, sequential 403 errors from Google Cloud itself, not
`mark-api`:
1. **Google Drive API** was never enabled on the project — gspread needs it to open a
   spreadsheet by name even though the actual writes happen through the Sheets API.
2. Once Drive was enabled, the **Google Sheets API** itself turned out to also be
   disabled — same project, never enabled at all.

Both fixed via Google Cloud Console (Enable API), no code changes. First fully successful
row: `a89de2b5ff9e4474ba88220754e625db` — real transcript, summary, X post, and newsletter
all written back to the sheet. **MARK's core pipeline is now confirmed working
end-to-end**, from a phone, through curl, into the sheet.

Note the ID format on that row is a full 32-char UUID (`uuid.uuid4().hex`) vs. the
8-char IDs AppSheet's own `UNIQUEID()` generates on earlier rows. Cosmetic difference
only — both are valid, unique keys.

### 2026-08-04 (fifth pass) — Read endpoint + Library view added (patched by Claude)

Every existing endpoint in this file writes to the sheet; nothing read from it. The
uploader was write-only — no way to see what MARK had actually produced without opening
the Google Sheet directly.

**Added `GET /recent-content?limit=N`** — read-only, returns the most recent N rows
(newest first) as JSON: id, timestamp, video_file, summary, x_post, newsletter, and a
`has_content` flag so a row that failed to generate content (blank Summary) is visibly
flagged instead of silently missing.

**Added a Library tab to `mark-uploader.html`** — fetches `/recent-content` and renders
real cards (timestamp, summary preview, a warning badge on empty rows). Tapping a card's
ID copies it into the Record ID field on the Upload tab, for re-running/updating a
specific row without retyping the ID by hand.

### 2026-08-04 (sixth pass) — Cards made expandable with Copy/Share per field (patched by Claude)

First real use surfaced the actual gap: the Library showed content existed but gave no
way to get it out and post it anywhere. Fix: tapping a card's summary now expands it to
show all three generated fields (Summary, X Post, Newsletter) in full, each with its own
**Copy** button (clipboard) and, where the browser supports it (`navigator.share` —
most Android browsers), a **Share** button that hands the text straight to the native
Android share sheet (X app, Notes, Messages, whatever's installed) — no
copy-then-switch-apps-then-paste round trip required. Card ID tap-to-reuse (for
re-running/updating a specific row) is unchanged.

### 2026-08-04 (seventh pass) — Library had no loading feedback or timeout (patched by Claude)

`loadLibrary()` showed a static "Loading..." string with no spinner and, critically, no
timeout on the fetch itself -- a slow `/recent-content` response (cold container, large
sheet, gspread being sluggish) or a genuine hang looked identical to "still working,"
with no way to tell them apart. Same root issue as the original upload button before its
debug-logging pass earlier this session. **Fix:** added a real spinner with a live
elapsed-time counter, plus a 20-second `AbortController` ceiling -- a hang now fails
visibly with a clear timeout message instead of spinning forever.

### 2026-08-04 (eighth pass) — Google Drive downloads needed gdown, not plain requests (patched by Claude)

Testing `/process-video-url` against a real AppSheet-stored video (confirmed to live in
Google Drive, in an auto-created `MARK_Files_` folder inside the app's Drive space --
Mike didn't set this up manually, AppSheet does it automatically) failed with ffmpeg
erroring `moov atom not found`. Root cause: `requests.get()` on a `drive.google.com/uc?...`
link returns Google's HTML virus-scan interstitial page for larger files, not the actual
video bytes -- ffmpeg was trying to decode an HTML page saved with a `.mp4` extension.
Neither the static `&confirm=t` trick nor Google's newer `drive.usercontent.google.com`
endpoint solved it; both need a token Google generates per-request, not a static one.

**Fix:** `gdown` — already sitting unused in `requirements.txt` — handles this
confirmation-token flow automatically. `/process-video-url` now detects Drive URLs and
routes them through `gdown.download(..., fuzzy=True)` instead of `requests.get()`;
non-Drive URLs still use the original plain-GET path unchanged.

### 2026-08-04 (ninth pass) — API key authentication added (patched by Claude)

Both `mark-api` and `mark-uploader` are **public GitHub repositories**. Every endpoint
(`/process-video`, `/process-video-url`, `/process-webhook`, `/recent-content`) had zero
authentication until now — anyone who found `mark.sagewire.dev` (a public, indexable
domain, no secret in it) could burn OpenAI quota, spam the sheet, or read every
transcript/summary via `/recent-content`. "Nobody knows this URL exists" stopped being
real security the moment the repo (and therefore the domain referenced in it) went
public.

**How it works:** every protected endpoint now requires a header `X-API-Key: <key>`,
checked against a `MARK_API_KEY` environment variable — same pattern as
`OPENAI_API_KEY`, never hardcoded in the file, never committed. **Fails closed**: if
`MARK_API_KEY` isn't set on the server at all, every request is refused with a 500
instead of silently letting everything through.

**Setup required before this works (not automatic):**
1. In Coolify → `mark-api` → Configuration → Environment Variables, add `MARK_API_KEY`
   set to any long random string you generate.
2. Redeploy so the container picks it up.
3. In `mark-uploader.html`, paste that same value into the new **API Key** field. It is
   NOT hardcoded into the file (that file is public — hardcoding it would defeat the
   whole point), so it needs to be pasted in each time the page loads fresh, same as the
   endpoint URL.
4. If/when the AppSheet Bot route to `/process-webhook` gets wired up, its webhook step
   needs an `X-API-Key` custom header added too, or it will get a 401.

**Not done in this pass, worth knowing:** the key is currently the *only* thing
protecting these endpoints — no rate limiting, no per-user keys, no rotation. Fine for
"nobody else knows about this yet," worth revisiting before any real audience arrives.

### 2026-08-05 — Uploader's own 120s timeout was too short for longer videos (patched by Claude)

First real test with a longer video (2:15) hit "Timed out after 120.0s" in the uploader.
This was **not** a repeat of the earlier proxy/TLS issues from the previous session --
no connection reset, just the uploader's own client-side `AbortController` giving up on
schedule at a number (120s) that was a guess, not a measurement, made when only
short (<1 min) clips had been tested. CPU-based Whisper transcription time scales
roughly with video length on top of upload time for a larger file -- a fixed short
ceiling was always going to eventually be too small once someone uploaded something
longer.

**Fix:** raised the client-side timeout to 10 minutes (also a rough ceiling, not a
measured one) and corrected the timeout error message, which previously pointed
confidently at "a reverse proxy is killing the connection" -- that was speculation
carried over from a different failure mode earlier in the project, not necessarily
true here. The message now tells whoever hits this to check `mark-api`'s Coolify logs
for a `[PIPELINE]` line timestamped after the client gave up, which would confirm the
server was still working the whole time -- that's the fast way to tell "video is just
long" apart from "something's actually broken," instead of guessing.

**Still open, flagged honestly:** if a legitimately long video times out even at the new
10-minute ceiling, the real fix isn't raising the number a third time -- it's adding a
way to see real progress (e.g. a status-polling endpoint) instead of a single blocking
request with a guessed-at deadline.

### 2026-08-04 (same day, third pass) — CORS blocking the hosted uploader (patched by Claude)

First real test of `mark-uploader.html` (hosted on GitHub Pages at
`voidwalker-sagewire.github.io`) against the live API failed with `Request failed:
Failed to fetch` before the request even reached the server — nothing showed up in the
`[SHEETS]`/`[PIPELINE]` logs at all, which was the tell. **Root cause:** the API had no
CORS configuration, so the browser blocked the cross-origin request outright (GitHub
Pages domain calling `mark.sagewire.dev` — a different origin). This is a browser-only
rule; it's why curl and Termux testing never hit this, and it's why the failure was
invisible server-side — the request never arrived.

**Fix:** added `CORSMiddleware` with `allow_origins=["*"]`. Permissive for now since this
endpoint doesn't expose secrets to the caller; worth narrowing to the specific GitHub
Pages origin later if that changes.
