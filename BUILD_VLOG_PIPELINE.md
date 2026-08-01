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
