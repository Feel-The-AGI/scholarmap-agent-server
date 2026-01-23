"""
ScholarMap Agent - FastAPI Application Entry Point

A microservice for scholarship data ingestion, eligibility checking,
and conversational onboarding powered by Gemini AI.

Structure:
- /health           - Health check
- /ingest           - Single URL ingestion
- /batch-ingest     - Batch URL ingestion (up to 50)
- /recheck          - Re-check existing program
- /check-eligibility - LLM-powered eligibility analysis
- /onboarding/chat  - Conversational profile extraction
- /tts              - Text-to-speech (one-off conversion)
- /live/ada         - WebSocket speech-to-speech (real-time)
"""
import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import ALLOWED_ORIGINS, logger
from .routers import (
    ingestion_router,
    eligibility_router,
    onboarding_router,
    tts_router,
    live_router,
)

# Create FastAPI app
app = FastAPI(
    title="ScholarMap Agent",
    version="2.0.0",
    description="AI-powered scholarship discovery microservice"
)


# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to log all unhandled errors."""
    logger.error("=== UNHANDLED EXCEPTION ===")
    logger.error(f"Path: {request.url.path}")
    logger.error(f"Method: {request.method}")
    logger.error(f"Exception type: {type(exc).__name__}")
    logger.error(f"Exception message: {str(exc)}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__}
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests (debug level)."""
    logger.debug("=== INCOMING REQUEST ===")
    logger.debug(f"Method: {request.method}")
    logger.debug(f"URL: {request.url}")
    logger.debug(f"Path: {request.url.path}")
    
    # Read body for POST requests
    if request.method == "POST":
        try:
            body = await request.body()
            logger.debug(f"Raw body: {body.decode('utf-8', errors='replace')[:500]}...")
            # Re-set body since we consumed it
            async def receive():
                return {"type": "http.request", "body": body}
            request._receive = receive
        except Exception as e:
            logger.error(f"Error reading body: {e}")
    
    response = await call_next(request)
    
    logger.debug(f"=== RESPONSE: {response.status_code} ===")
    return response


# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# ROUTERS
# ============================================================================

# Ingestion routes: /health, /ingest, /batch-ingest, /recheck
app.include_router(ingestion_router)

# Eligibility routes: /check-eligibility
app.include_router(eligibility_router)

# Onboarding routes: /onboarding/chat
app.include_router(onboarding_router)

# TTS routes: /tts (one-off text-to-speech)
app.include_router(tts_router)

# Live API routes: /live/ada (WebSocket speech-to-speech)
app.include_router(live_router)


# ============================================================================
# STARTUP
# ============================================================================

logger.info("=== APPLICATION STARTUP COMPLETE ===")
logger.info("Endpoints registered:")
logger.info("  - GET  /health")
logger.info("  - POST /ingest")
logger.info("  - POST /batch-ingest")
logger.info("  - POST /recheck")
logger.info("  - POST /check-eligibility")
logger.info("  - POST /onboarding/chat")
logger.info("  - POST /tts")
logger.info("  - WS   /live/ada")
