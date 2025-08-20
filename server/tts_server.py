import asyncio
import io
import edge_tts
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

app = FastAPI(title="Edge TTS Server", description="Free TTS API using Microsoft Edge TTS")

class TTSRequest(BaseModel):
    model: str = "tts-1"
    input: str
    voice: str = "alloy"
    response_format: str = "mp3"
    speed: float = 1.0

# Voice mapping from OpenAI to Edge TTS
VOICE_MAPPING = {
    "alloy": "en-US-AriaNeural",
    "echo": "en-US-AndrewNeural", 
    "fable": "en-US-EmmaNeural",
    "onyx": "en-US-BrianNeural",
    "nova": "en-US-JennyNeural",
    "shimmer": "en-US-MichelleNeural",
    # Indonesian voices
    "gadis": "id-ID-GadisNeural",
    "ardhi": "id-ID-ArdhiNeural"
}

@app.post("/v1/audio/speech")
async def create_speech(request: TTSRequest):
    try:
        # Map OpenAI voice to Edge TTS voice
        edge_voice = VOICE_MAPPING.get(request.voice, "en-US-AriaNeural")
        
        # Adjust speed
        rate = "+0%"  # Default rate
        if request.speed < 1.0:
            rate = f"-{int((1.0 - request.speed) * 50)}%"
        elif request.speed > 1.0:
            rate = f"+{int((request.speed - 1.0) * 50)}%"
        
        # Create TTS
        communicate = edge_tts.Communicate(request.input, edge_voice, rate=rate)
        
        # Generate audio
        audio_data = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.write(chunk["data"])
        
        audio_data.seek(0)
        
        # Return audio response
        media_type = "audio/mpeg" if request.response_format == "mp3" else "audio/wav"
        
        return StreamingResponse(
            io.BytesIO(audio_data.read()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename=speech.{request.response_format}"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS Error: {str(e)}")

@app.get("/v1/voices")
async def list_voices():
    """List available voices"""
    return {
        "data": [
            {"id": voice_id, "name": voice_name, "object": "voice"}
            for voice_id, voice_name in VOICE_MAPPING.items()
        ]
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Edge TTS Server"}

if __name__ == "__main__":
    # Production configuration
    import os
    debug_mode = os.environ.get("DEBUG", "false").lower() == "true"
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=5050,
        reload=debug_mode,
        access_log=debug_mode
    )