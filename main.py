import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
import whisper
import openai

app = FastAPI(title="M.A.R.K. Content Engine")

# Load Whisper model once on startup
model = whisper.load_model("base")

# OpenRouter / OpenAI client configuration
# (Ensures your API key is pulled from environment variables)
client = openai.OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
)

@app.post("/process-video")
async def process_video(file: UploadFile = File(...)):
    temp_video_path = f"/tmp/{file.filename}"
    
    try:
        # 1. Save uploaded video to temporary storage
        with open(temp_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Transcribe audio track via Whisper
        result = model.transcribe(temp_video_path)
        raw_transcript = result.get("text", "").strip()

        if not raw_transcript:
            raise HTTPException(status_code=400, detail="No speech could be extracted from the video.")

        # 3. Pass raw transcript to LLM to generate all content formats
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

        formatted_content = response.parse()

        return {
            "status": "success",
            "filename": file.filename,
            "raw_transcript": raw_transcript,
            "content": formatted_content
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # Clean up temporary video file
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
