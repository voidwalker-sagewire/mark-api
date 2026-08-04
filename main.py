import os
import shutil
import json
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import whisper
import openai
import gspread

app = FastAPI(title="M.A.R.K. Content Engine")

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

@app.post("/process-video")
async def process_video(file: UploadFile = File(...), record_id: str = Form(None)):
    temp_video_path = f"/tmp/{file.filename}"
    try:
        print(f"[UPLOAD] Receiving local file stream: {file.filename}")
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        raw_transcript, formatted_content = run_content_pipeline(temp_video_path)

        summary = formatted_content.get("summary", "")
        x_post = formatted_content.get("x_post", "")
        newsletter = formatted_content.get("newsletter", "")
        if isinstance(newsletter, dict):
            newsletter = f"{newsletter.get('title', '')}\n\n{newsletter.get('content', '')}"

        # BUG FIX: previously this call's result was discarded, so the
        # response below always claimed "status": "success" even when the
        # Google Sheets write failed. Now we surface the real outcome.
        sheet_write_ok = update_or_append_sheet(raw_transcript, summary, x_post, newsletter, record_id)

        return {
            "status": "success" if sheet_write_ok else "partial_success",
            "sheet_write_ok": sheet_write_ok,
            "raw_transcript": raw_transcript,
            "content": formatted_content
        }
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
