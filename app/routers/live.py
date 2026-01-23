"""
Live API router - /live/ada WebSocket endpoint.

This is the PRIMARY speech-to-speech interface for Ada.
Uses Gemini Live API for real-time bidirectional audio streaming.
"""
import logging
import base64
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types as genai_types

from ..dependencies import gemini_client
from ..prompts import LIVE_API_SYSTEM_INSTRUCTION

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/live/ada")
async def websocket_ada_live(websocket: WebSocket):
    """
    WebSocket endpoint for real-time speech-to-speech with Ada.

    Protocol:
    - Client sends: {"type": "audio", "data": "<base64 PCM 16kHz>"}
    - Client sends: {"type": "text", "data": "<text message>"}
    - Server sends: {"type": "audio", "data": "<base64 PCM 24kHz>"}
    - Server sends: {"type": "transcript", "data": "<text>"}
    - Server sends: {"type": "turn_complete"}
    """
    logger.debug("=" * 60)
    logger.debug("WEBSOCKET CONNECTION ATTEMPT - /live/ada")
    logger.debug("=" * 60)
    
    await websocket.accept()
    session_id = str(id(websocket))
    logger.info(f"WebSocket ACCEPTED: session_id={session_id}")
    logger.debug(f"WebSocket client info: {websocket.client}")

    receive_task = None

    try:
        logger.debug("Building LiveConnectConfig...")
        logger.debug(f"Model: gemini-2.5-flash-preview-native-audio")
        logger.debug(f"Voice: Kore")
        logger.debug(f"Modalities: AUDIO")
        
        # Build Live API config
        config = genai_types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=genai_types.Content(
                parts=[genai_types.Part(text=LIVE_API_SYSTEM_INSTRUCTION)]
            ),
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name="Kore"  # Female voice for Ada
                    )
                )
            )
        )

        logger.debug("LiveConnectConfig built successfully")
        logger.debug(f"Checking gemini_client: {gemini_client is not None}")
        
        if not gemini_client:
            logger.error("CRITICAL: gemini_client is None!")
            await websocket.send_json({"type": "error", "data": "Gemini client not initialized"})
            return

        logger.debug("Initiating Live API connection...")
        # Use async context manager properly
        async with gemini_client.aio.live.connect(
            model="gemini-2.5-flash-preview-native-audio",
            config=config
        ) as live_session:
            logger.info(f"Live session CREATED: {session_id}")
            logger.debug(f"Live session object: {type(live_session)}")

            # Task to receive from Gemini and forward to client
            async def receive_from_gemini():
                logger.debug(f"[{session_id}] Starting Gemini receive task...")
                try:
                    async for response in live_session.receive():
                        logger.debug(f"[{session_id}] Received response from Gemini: {type(response)}")
                        if response.server_content:
                            logger.debug(f"[{session_id}] Server content received")
                            # Handle model turn (audio response)
                            if response.server_content.model_turn:
                                logger.debug(f"[{session_id}] Model turn - processing audio parts")
                                for part in response.server_content.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        audio_b64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                                        logger.debug(f"[{session_id}] Sending audio chunk: {len(audio_b64)} chars")
                                        await websocket.send_json({
                                            "type": "audio",
                                            "data": audio_b64
                                        })

                            # Handle output transcription
                            if response.server_content.output_transcription:
                                logger.debug(f"[{session_id}] Transcript: {response.server_content.output_transcription.text[:50]}...")
                                await websocket.send_json({
                                    "type": "transcript",
                                    "data": response.server_content.output_transcription.text
                                })

                            # Handle turn complete
                            if response.server_content.turn_complete:
                                logger.debug(f"[{session_id}] Turn complete")
                                await websocket.send_json({"type": "turn_complete"})

                            # Handle interruption
                            if response.server_content.interrupted:
                                logger.debug(f"[{session_id}] Interrupted")
                                await websocket.send_json({"type": "interrupted"})

                except asyncio.CancelledError:
                    logger.info(f"Receive task cancelled: {session_id}")
                except Exception as e:
                    logger.error(f"Error receiving from Gemini: {e}")

            # Start receive task
            receive_task = asyncio.create_task(receive_from_gemini())
            logger.debug(f"[{session_id}] Receive task started")

            # Send initial greeting
            logger.debug(f"[{session_id}] Sending initial greeting prompt...")
            await live_session.send(input="Start the conversation by greeting me warmly.", end_of_turn=True)
            logger.debug(f"[{session_id}] Initial greeting sent")

            # Main loop: receive from client and forward to Gemini
            logger.debug(f"[{session_id}] Entering main client message loop...")
            while True:
                try:
                    data = await websocket.receive_json()
                    msg_type = data.get("type")
                    logger.debug(f"[{session_id}] Received from client: type={msg_type}")

                    if msg_type == "audio":
                        audio_data = base64.b64decode(data.get("data", ""))
                        logger.debug(f"[{session_id}] Sending audio to Gemini: {len(audio_data)} bytes")
                        await live_session.send(input=genai_types.Blob(
                            data=audio_data,
                            mime_type="audio/pcm;rate=16000"
                        ))

                    elif msg_type == "text":
                        text = data.get("data", "")
                        logger.debug(f"[{session_id}] Sending text to Gemini: {text[:50]}...")
                        await live_session.send(input=text, end_of_turn=True)

                    elif msg_type == "end_turn":
                        logger.debug(f"[{session_id}] End turn signal")
                        await live_session.send(input="", end_of_turn=True)

                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected: {session_id}")
                    break
                except Exception as e:
                    logger.error(f"Error processing client message: {e}")
                    await websocket.send_json({"type": "error", "data": str(e)})

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except:
            pass

    finally:
        if receive_task:
            receive_task.cancel()
        logger.info(f"WebSocket cleanup complete: {session_id}")
