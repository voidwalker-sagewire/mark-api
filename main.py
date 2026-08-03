import os
import shutil
import json
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

def update_or_append_sheet(raw_transcript: str, summary: str, x_post: str, newsletter: str, record_id: str = None):
    sheet = get_google_sheet()
    if not sheet:
        return

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
            # Append new row if no ID provided
            sheet.append_row(["", "", "", raw_transcript, summary, x_post, newsletter])
            print("[SHEETS] Appended new row")
    except Exception as e:
        print(f"[SHEETS] Update failed: {e}")

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

        update_or_append_sheet(raw_transcript, summary, x_post, newsletter, record_id)

        return {
            "status": "success",
            "raw_transcript": raw_transcript,
            "content": formatted_content
        }
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
