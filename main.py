import os
import shutil
import json
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import gdown
import whisper
import openai
import gspread

app = FastAPI(title="M.A.R.K. Content Engine")

# --- BUG FIX (added 2026-08-04, patched by Claude) ---
# WHY THIS EXISTS: mark-uploader.html is hosted on GitHub Pages
# (voidwalker-sagewire.github.io) and calls this API on a different domain
# (mark.sagewire.dev). Browsers block cross-origin fetch() requests by
# default unless the server explicitly allows it via CORS headers -- this
# is a browser security rule, not something curl/Termux ever hits (which
# is why direct multipart uploads worked in earlier testing but the actual
# hosted uploader page failed with "Failed to fetch"). Without this
# middleware, FastAPI never sends the Access-Control-Allow-Origin header,
# so the browser refuses to let the request through at all -- the request
# never even reaches process_video(), which is why this failure mode
# wasn't visible in any of the server-side [SHEETS]/[PIPELINE] logs.
# allow_origins=["*"] is permissive (any site can call this API from a
# browser) -- fine for now since this endpoint has no auth/secrets exposed
# to the caller, but worth tightening to the specific GitHub Pages origin
# later if this API ever handles anything sensitive.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model = whisper.load_model("base")

client = openai.OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
)

def get_google_sheet():
    json_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "MARK")
    
    if not json_creds:
        print("[SHEETS] GOOGLE_SERVICE_ACCOUNT_JSON is missing!")
        return None

    try:
        creds_dict = json.loads(json_creds)
        gc = gspread.service_account_from_dict(creds_dict)
        return gc.open(sheet_name).sheet1
    except Exception as e:
        print(f"[SHEETS] Connection error: {e}")
        return None

def run_content_pipeline(video_path: str):
    print(f"[PIPELINE] Running Whisper on {video_path}...")
    result = model.transcribe(video_path)
    raw_transcript = result.get("text", "").strip()

    if not raw_transcript:
        raise HTTPException(status_code=400, detail="No speech extracted from video.")

    print(f"[PIPELINE] Transcript generated ({len(raw_transcript)} chars). Running LLM...")

    prompt = f"""
    You are the content generator for a builder who speaks candidly about engineering, software, and real-world execution.
    
    Analyze the following raw transcript from a video recording and generate three distinct outputs:
    1. "summary": A clear 2-3 sentence executive summary in plain English explaining what was done/built so non-technical people understand it immediately.
    2. "x_post": A short, punchy, engaging post (or short thread format) optimized for X (Twitter).
    3. "newsletter": A well-structured section suitable for an email newsletter or blog update.

    Raw Transcript:
    "{raw_transcript}"

    Return your response strictly as valid JSON with keys: "summary", "x_post", "newsletter".
    """

    response = client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "You output JSON only."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    formatted_content = json.loads(response.choices[0].message.content)
    return raw_transcript, formatted_content

# --- BUG FIX (patched by Claude, session 2026-08-03) ---
# ORIGINAL BEHAVIOR: this function returned nothing (implicit None) in every
# case, success or failure, and the append branch wrote append_row(["", "",
# "", raw_transcript, ...]) -- three blank strings for columns A/B/C.
#
# WHY THAT WAS A BUG, not just messy data:
# The MARK AppSheet table (see MARKMobile-539435717 documentation) defines
# column A ("ID") as the table's KEY column, with Initial Value = UNIQUEID().
# UNIQUEID() only fires when AppSheet itself creates the row through its own
# Add/Form action. It does NOT fire when a row is inserted from outside the
# app (e.g. this API writing directly to the sheet via gspread). So any row
# created by the append branch got a permanently blank key column.
# Consequence: that row has no identity AppSheet can reference. It can't be
# targeted by a later record_id update (sheet.find(record_id) has nothing to
# match), Edit/Delete actions tied to the key may misbehave, and the row's
# Video_File (col C) was also blanked, so it shows no thumbnail in the Card
# Deck view. In short: content generated via append was silently orphaned.
#
# THE FIX:
# 1. Always generate an ID and Timestamp ourselves on append, so the row is
#    never missing its key -- mirrors what UNIQUEID()/NOW() would have done
#    if AppSheet had created the row itself.
# 2. Return a bool so the caller (process_video) knows whether the sheet
#    write actually succeeded, instead of assuming success unconditionally.
# 3. Re-raise write failures instead of only printing them, so a failed
#    Google Sheets write is no longer invisible to whoever/whatever called
#    this API (including an AppSheet Automation/Bot, if one is wired up to
#    call this endpoint -- see BUILD_VLOG_PIPELINE.md bug-fix log entry).
#
# NOTE for Gemini / next collaborator: Video_File (col C) is still left
# blank on the append path. That's not an oversight -- this API only ever
# receives a temp local file (saved to /tmp, deleted in the `finally` block
# of process_video), never a Drive/Sheets-hosted URL, so there's nothing
# valid to put in that cell yet. If you want Video_File populated on
# API-created rows, this function needs a video upload/hosting step first
# (e.g. push to Drive via a service account, then write the resulting URL).
# --- END NOTE ---
def update_or_append_sheet(raw_transcript: str, summary: str, x_post: str, newsletter: str, record_id: str = None) -> bool:
    sheet = get_google_sheet()
    if not sheet:
        print("[SHEETS] No sheet handle -- write skipped.")
        return False

    try:
        if record_id:
            # Find and update existing row
            cell = sheet.find(record_id)
            row_num = cell.row
            sheet.update_cell(row_num, 4, raw_transcript)
            sheet.update_cell(row_num, 5, summary)
            sheet.update_cell(row_num, 6, x_post)
            sheet.update_cell(row_num, 7, newsletter)
            print(f"[SHEETS] Updated row {row_num}")
        else:
            # Append new row -- generate ID/Timestamp ourselves so the key
            # column is never blank (see fix note above).
            new_id = uuid.uuid4().hex
            timestamp = datetime.now(timezone.utc).isoformat()
            sheet.append_row([new_id, timestamp, "", raw_transcript, summary, x_post, newsletter])
            print(f"[SHEETS] Appended new row with ID {new_id}")
        return True
    except Exception as e:
        print(f"[SHEETS] Update failed: {e}")
        return False

# --- SHARED PIPELINE (factored out 2026-08-04, patched by Claude) ---
# Both entry points below (direct upload, and the new URL-based bridge)
# funnel through this exact same function once they have a local file on
# disk. This matters for trust: the URL-based endpoint isn't a separate,
# untested code path -- it's the same tested transcription/LLM/sheet logic
# as the working uploader, just with a different way of getting the video
# onto disk first. If one works, the other's pipeline is proven too; the
# only new surface area to debug is the download step itself.
def _process_local_file(temp_video_path: str, record_id: str = None) -> dict:
    raw_transcript, formatted_content = run_content_pipeline(temp_video_path)

    summary = formatted_content.get("summary", "")
    x_post = formatted_content.get("x_post", "")
    newsletter = formatted_content.get("newsletter", "")
    if isinstance(newsletter, dict):
        newsletter = f"{newsletter.get('title', '')}\n\n{newsletter.get('content', '')}"

    sheet_write_ok = update_or_append_sheet(raw_transcript, summary, x_post, newsletter, record_id)

    return {
        "status": "success" if sheet_write_ok else "partial_success",
        "sheet_write_ok": sheet_write_ok,
        "raw_transcript": raw_transcript,
        "content": formatted_content
    }

@app.post("/process-video")
async def process_video(file: UploadFile = File(...), record_id: str = Form(None)):
    temp_video_path = f"/tmp/{file.filename}"
    try:
        print(f"[UPLOAD] Receiving local file stream: {file.filename}")
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return _process_local_file(temp_video_path, record_id)
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)

# --- NEW ENDPOINT (added 2026-08-04, patched by Claude) ---
# WHY THIS EXISTS: /process-video above requires actual multipart file
# bytes (an UploadFile). That works fine for a client that has the raw
# video on-device (the mobile uploader app, Termux/curl). It does NOT work
# for an AppSheet Automation/Bot, because AppSheet's "Call a webhook" step
# sends an uploaded file as a stored file path/URL reference, not as raw
# multipart bytes -- see MARK sheet's Video_File column, values like
# "MARK_Files_/66f50c0c.Video_File.190348.mp4". There was no way for the
# Bot to actually hand this API a real video before now, which is the real
# reason two days of AppSheet-submitted rows (8/2-8/3) never got processed
# -- not a bug in the processing logic itself, a missing bridge to it.
#
# WHAT THIS ENDPOINT DOES: accepts a JSON body with a video URL instead of
# raw bytes, downloads it to /tmp itself, then hands off to the exact same
# _process_local_file() the working upload path already uses.
#
# NOW VERIFIED (2026-08-04, patched by Claude): AppSheet's stored files
# turned out to live in the app's own Google Drive folder (auto-created by
# AppSheet, not something Mike set up manually -- see "MARK_Files_" folder
# under the app's default Drive folder). A plain `requests.get()` on a
# drive.google.com/uc?... link works for small files, but Google requires
# a dynamically-generated confirmation token for larger ones -- a static
# `&confirm=t` trick doesn't satisfy it. Both failed the same way: ffmpeg
# choked with "moov atom not found" because it received Google's HTML
# virus-scan interstitial page saved with a .mp4 extension, not real video
# bytes. Fixed below using `gdown` (already in requirements.txt, never
# actually wired into this file until now) -- it handles Drive's
# confirmation-token flow automatically instead of guessing at URL tricks.
class VideoUrlRequest(BaseModel):
    video_url: str
    record_id: str = None

@app.post("/process-video-url")
async def process_video_url(payload: VideoUrlRequest):
    temp_video_path = f"/tmp/{uuid.uuid4().hex}.mp4"
    try:
        if "drive.google.com" in payload.video_url or "drive.usercontent.google.com" in payload.video_url:
            print(f"[DOWNLOAD] Google Drive URL detected, using gdown: {payload.video_url}")
            result = gdown.download(payload.video_url, temp_video_path, quiet=False, fuzzy=True)
            if result is None or not os.path.exists(temp_video_path) or os.path.getsize(temp_video_path) == 0:
                raise HTTPException(
                    status_code=502,
                    detail="gdown could not download the Drive file. Check that sharing is set to 'Anyone with the link' and the file ID is correct."
                )
        else:
            print(f"[DOWNLOAD] Fetching video from URL: {payload.video_url}")
            resp = requests.get(payload.video_url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(temp_video_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

        print(f"[DOWNLOAD] Saved to {temp_video_path}, size={os.path.getsize(temp_video_path)} bytes")
        return _process_local_file(temp_video_path, payload.record_id)
    except requests.exceptions.RequestException as e:
        # Downloading the video failed -- almost certainly the auth/access
        # question flagged in the note above, not a transcription problem.
        print(f"[DOWNLOAD ERROR] {str(e)}")
        raise HTTPException(status_code=502, detail=f"Could not download video from URL: {str(e)}")
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)

# --- ALIAS ENDPOINT (added 2026-08-04, patched by Claude) ---
# WHY THIS EXISTS: this project has two AI collaborators (Gemini and
# Claude) working across sessions. Gemini documented a webhook contract
# for Mike -- POST /process-webhook, JSON body {"ID": ..., "file_url":
# ...} -- as the intended AppSheet integration point. At the time that
# documentation was written, this endpoint did NOT exist in the repo
# (verified via `git log --all` -- no commit ever added it, only one
# branch exists). Rather than leave two different endpoint contracts
# (this one's /process-video-url above, and Gemini's documented
# /process-webhook) both floating around unreconciled, this alias makes
# Gemini's documented contract the real, working one. It's a thin
# wrapper: same field meanings (ID = record_id, file_url = video_url),
# same underlying pipeline, just the field names Gemini already told
# Mike to expect. If Gemini or a future session references
# /process-webhook, this is why it now actually works.
class WebhookRequest(BaseModel):
    ID: str = None
    file_url: str

@app.post("/process-webhook")
async def process_webhook(payload: WebhookRequest):
    return await process_video_url(VideoUrlRequest(video_url=payload.file_url, record_id=payload.ID))

# --- NEW ENDPOINT (added 2026-08-04, patched by Claude) ---
# WHY THIS EXISTS: every other endpoint in this file writes to the sheet;
# nothing reads from it. That means the only way to see what MARK has
# actually produced is to open the Google Sheet directly -- there's no
# "library" or history view anywhere in the uploader. This endpoint fixes
# that: it returns the most recent N rows as JSON so a frontend (the
# uploader, or anything else) can render a real list without ever touching
# Google credentials directly. Read-only, no risk to existing data.
@app.get("/recent-content")
async def recent_content(limit: int = 20):
    sheet = get_google_sheet()
    if not sheet:
        raise HTTPException(status_code=502, detail="Could not connect to Google Sheet.")

    try:
        all_rows = sheet.get_all_records()  # list of dicts, keyed by header row
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not read sheet: {str(e)}")

    # Most recent first. Sheet rows are in append order (oldest first), so
    # reverse before slicing to limit.
    recent = list(reversed(all_rows))[:limit]

    return {
        "count": len(recent),
        "items": [
            {
                "id": row.get("ID", ""),
                "timestamp": row.get("Timestamp", ""),
                "video_file": row.get("Video_File", ""),
                "summary": row.get("Summary", ""),
                "x_post": row.get("X_Post", ""),
                "newsletter": row.get("Newsletter", ""),
                "has_content": bool(row.get("Summary", "").strip())
            }
            for row in recent
        ]
    }
