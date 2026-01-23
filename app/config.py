"""
Application configuration and environment variables.
"""
import os
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AGENT_SECRET = os.getenv("AGENT_SECRET")

# CORS allowed origins
ALLOWED_ORIGINS = [
    "https://scholarmap.vercel.app",
    "https://frontend-tawny-ten-57.vercel.app",
    "http://localhost:3000",
    "http://localhost:3001",
]

# Log startup configuration
logger.debug("=== STARTUP CONFIGURATION ===")
logger.debug(f"SUPABASE_URL set: {bool(SUPABASE_URL)}")
logger.debug(f"SUPABASE_SERVICE_KEY set: {bool(SUPABASE_SERVICE_KEY)}")
logger.debug(f"GEMINI_API_KEY set: {bool(GEMINI_API_KEY)}")
logger.debug(f"AGENT_SECRET set: {bool(AGENT_SECRET)}")
