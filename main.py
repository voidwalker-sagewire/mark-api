import os
import shutil
import json
import requests
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
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
        print(f"[SHEETS] Failed to connect to Google Sheets: {e}")
        return None

def run_content_pipeline(video_path: str):
    print(f"[PIPELINE] Running Whisper on {video_path}...")
    result = model.transcribe(video_path)
    raw_transcript = result.get("text", "").strip()

    if not raw_transcript:
        raise HTTPException(status_code=400, detail="No speech could be extracted from the video.")

    print(f"[PIPELINE] Transcript extracted ({len(raw_transcript)} chars). Running LLM...")

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
        return

    try:
        print(f"[SHEETS] Searching for row with ID: {record_id}...")
        cell = sheet.find(record_id)
        row_num = cell.row

        sheet.update_cell(row_num, 4, raw_transcript)
        sheet.update_cell(row_num, 5, summary)
        sheet.update_cell(row_num, 6, x_post)
        sheet.update_cell(row_num, 7, newsletter)
        print(f"[SHEETS] Successfully updated row {row_num}!")
    except Exception as e:
        print(f"[SHEETS] Failed to update row: {e}")

@app.post("/process-webhook")
async def process_webhook(request: Request):
    temp_video_path = "/tmp/appsheet_video.mp4"
    try:
        body = await request.json()
        print(f"[WEBHOOK] Payload received: {body}")
        
        file_url = body.get("file_url", "")
        record_id = body.get("ID", "")

        if not file_url:
            raise HTTPException(status_code=400, detail="No file_url provided in payload.")

        print(f"[DOWNLOAD] Streaming video from: {file_url}")
        
        # Stream the download using standard requests with redirect handling
        with requests.get(file_url, stream=True, allow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            with open(temp_video_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        file_size = os.path.getsize(temp_video_path)
        print(f"[DOWNLOAD] Download complete. File size: {file_size} bytes")

        if file_size < 5000:  # If under 5KB, it's an HTML error page, not a video
            with open(temp_video_path, 'r', errors='ignore') as f:
                snippet = f.read(500)
            print(f"[ERROR] Downloaded file is too small ({file_size} bytes). Snippet:\n{snippet}")
            raise HTTPException(status_code=400, detail=f"Downloaded invalid file. Content snippet: {snippet[:200]}")

        raw_transcript, formatted_content = run_content_pipeline(temp_video_path)

        summary = formatted_content.get("summary", "")
        x_post = formatted_content.get("x_post", "")
        newsletter = formatted_content.get("newsletter", "")
        if isinstance(newsletter, dict):
            newsletter = f"{newsletter.get('title', '')}\n\n{newsletter.get('content', '')}"

        if record_id:
            update_sheet_row(record_id, raw_transcript, summary, x_post, newsletter)

        return {
            "status": "success",
            "raw_transcript": raw_transcript,
            "content": formatted_content
        }
    except Exception as e:
        print(f"[WEBHOOK ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
