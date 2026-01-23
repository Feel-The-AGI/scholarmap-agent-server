"""
Shared dependencies: Supabase client, Gemini client, authentication.
"""
import logging
from fastapi import Header, HTTPException
from supabase import create_client, Client
from google import genai

from .config import (
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    GEMINI_API_KEY,
    AGENT_SECRET
)

logger = logging.getLogger(__name__)

# Initialize Gemini client
logger.debug("Initializing Gemini client...")
try:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.debug("Gemini client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Gemini client: {e}")
    gemini_client = None


def get_supabase() -> Client:
    """Create and return a Supabase client instance."""
    logger.debug("Creating Supabase client...")
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    logger.debug("Supabase client created")
    return client


def verify_token(authorization: str = Header(None)):
    """Verify the bearer token in the Authorization header."""
    logger.debug("=== TOKEN VERIFICATION ===")
    logger.debug(f"Authorization header received: {authorization is not None}")
    
    if authorization:
        logger.debug(f"Authorization header value (first 20 chars): {authorization[:20]}...")
    if AGENT_SECRET:
        logger.debug(f"Expected token starts with: Bearer {AGENT_SECRET[:10]}...")
    
    if not authorization:
        logger.error("No authorization header provided")
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    expected = f"Bearer {AGENT_SECRET}"
    if authorization != expected:
        logger.error("Token mismatch!")
        logger.debug(f"Received length: {len(authorization)}, Expected length: {len(expected)}")
        raise HTTPException(status_code=401, detail="Unauthorized - token mismatch")
    
    logger.debug("Token verified successfully")
