"""
TTS router - /tts endpoint.

NOTE: This is a one-off text-to-speech conversion endpoint.
For real-time speech-to-speech, use the Live API WebSocket at /live/ada.
"""
import logging
import base64
import asyncio
import traceback
from fastapi import APIRouter, HTTPException
from google.genai import types

from ..dependencies import gemini_client
from ..models.schemas import TTSRequest, TTSResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Available voices (from Gemini TTS docs):
# Female: Kore, Aoede, Leda, Zephyr, Charon, Fenrir
# Male: Puck, Orus, etc.


@router.post("/tts", response_model=TTSResponse)
async def text_to_speech(request: TTSRequest):
    """Convert text to speech using Gemini 2.5 Flash TTS."""
    logger.info(f"TTS request: {len(request.text)} chars, voice={request.voice}")

    if not gemini_client:
        logger.error("Gemini client not initialized")
        raise HTTPException(status_code=500, detail="TTS service unavailable")

    max_retries = 3
    retry_delay = 1.0
    last_error = None

    # Voices to try in order (fallback if first fails)
    voices_to_try = [request.voice, "Kore", "Puck"]

    for attempt in range(max_retries):
        for voice_name in voices_to_try:
            try:
                # Build the TTS prompt
                if request.style:
                    tts_prompt = f"Say {request.style}: {request.text}"
                else:
                    tts_prompt = f"Say cheerfully and warmly: {request.text}"

                logger.debug(f"TTS attempt {attempt + 1}, voice={voice_name}: {tts_prompt[:50]}...")

                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash-preview-tts",
                    contents=tts_prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice_name,
                                )
                            )
                        ),
                    )
                )

                if response.candidates and response.candidates[0].content.parts:
                    audio_data = response.candidates[0].content.parts[0].inline_data.data

                    if isinstance(audio_data, bytes):
                        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                    else:
                        audio_base64 = audio_data

                    logger.info(f"TTS generated: {len(audio_base64)} chars, voice={voice_name}")

                    return TTSResponse(
                        audio_base64=audio_base64,
                        format="pcm",
                        sample_rate=24000
                    )
                else:
                    logger.warning(f"No audio data in response for voice {voice_name}")
                    continue

            except Exception as e:
                error_str = str(e)
                logger.warning(f"TTS attempt {attempt + 1} with voice {voice_name} failed: {error_str}")
                last_error = e

                # If 500 error from Google, try next voice
                if "500" in error_str or "INTERNAL" in error_str:
                    continue

                break

        # Wait before next retry
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= 2

    logger.error(f"TTS failed after {max_retries} attempts: {last_error}")
    logger.error(traceback.format_exc())
    raise HTTPException(status_code=500, detail=f"TTS failed after retries: {str(last_error)}")
