import os
import shutil
import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
import whisper
import openai
import gdown
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
        return None

    creds_dict = json.loads(json_creds)
    gc = gspread.service_account_from_dict(creds_dict)
    return gc.open(sheet_name).sheet1

def run_content_pipeline(video_path: str):
    # 1. Transcribe audio track via Whisper
    result = model.transcribe(video_path)
    raw_transcript = result.get("text", "").strip()

    if not raw_transcript:
        raise HTTPException(status_code=400, detail="No speech could be extracted from the video.")

    # 2. Generate content formats via LLM
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

    raw_json_str = response.choices[0].message.content
    formatted_content = json.loads(raw_json_str)

    return raw_transcript, formatted_content

def update_sheet_row(record_id: str, raw_transcript: str, summary: str, x_post: str, newsletter: str):
    sheet = get_google_sheet()
    if not sheet:
        print("Google Sheets credentials not set. Skipping sheet write-back.")
        return

    # Find the row matching the AppSheet record ID (Column A)
    try:
        cell = sheet.find(record_id)
        row_num = cell.row

        # Update Raw_Transcript (Col D), Summary (Col E), X_Post (Col F), Newsletter (Col G)
        sheet.update_cell(row_num, 4, raw_transcript)
        sheet.update_cell(row_num, 5, summary)
        sheet.update_cell(row_num, 6, x_post)
        sheet.update_cell(row_num, 7, newsletter)
        print(f"Successfully updated row {row_num} in Google Sheets!")
    except Exception as e:
        print(f"Failed to update Google Sheet row: {e}")

# Direct File Upload Endpoint
@app.post("/process-video")
async def process_video(file: UploadFile = File(...)):
    temp_video_path = f"/tmp/{file.filename}"
    try:
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        raw_transcript, formatted_content = run_content_pipeline(temp_video_path)

        return {
            "status": "success",
            "filename": file.filename,
            "raw_transcript": raw_transcript,
            "content": formatted_content
        }
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)

# AppSheet Webhook Endpoint
@app.post("/process-webhook")
async def process_webhook(request: Request):
    try:
        body = await request.json()
        file_url = body.get("file_url", "")
        record_id = body.get("ID", "")

        if not file_url:
            raise HTTPException(status_code=400, detail="No file_url provided in webhook payload.")

        temp_video_path = "/tmp/appsheet_video.mp4"

        # Download file cleanly
        gdown.download(url=file_url, output=temp_video_path, quiet=False)

        raw_transcript, formatted_content = run_content_pipeline(temp_video_path)

        summary = formatted_content.get("summary", "")
        x_post = formatted_content.get("x_post", "")
        newsletter = formatted_content.get("newsletter", "")
        if isinstance(newsletter, dict):
            newsletter = f"{newsletter.get('title', '')}\n\n{newsletter.get('content', '')}"

        # Write directly back to Google Sheets if an ID was passed
        if record_id:
            update_sheet_row(record_id, raw_transcript, summary, x_post, newsletter)

        return {
            "status": "success",
            "raw_transcript": raw_transcript,
            "content": formatted_content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists("/tmp/appsheet_video.mp4"):
            os.remove("/tmp/appsheet_video.mp4")
