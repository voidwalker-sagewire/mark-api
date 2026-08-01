import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="M.A.R.K. - Mobile Automated Record Keeper", version="1.0.0")

@app.get("/health")
def health_check():
    """Internal and external health check endpoint."""
    return {"status": "healthy", "service": "mark-api"}

@app.post("/process-video")
async def process_video(file: UploadFile = File(...)):
    """
    Receives raw video file, handles transcription, 
    metadata extraction, and formatting pipeline.
    """
    if not file.filename.endswith((".mp4", ".mov", ".avi", ".mkv")):
        raise HTTPException(status_code=400, detail="Invalid video file format.")
    
    # Save incoming file temporarily
    temp_file_path = f"/tmp/{file.filename}"
    try:
        contents = await file.read()
        with open(temp_file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    return JSONResponse(content={
        "filename": file.filename,
        "status": "received",
        "message": "M.A.R.K. has successfully staged video for processing."
    })
