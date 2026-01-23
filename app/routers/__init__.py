"""
Routers package initialization.
"""
from .ingestion import router as ingestion_router
from .eligibility import router as eligibility_router
from .onboarding import router as onboarding_router
from .tts import router as tts_router
from .live import router as live_router

__all__ = [
    "ingestion_router",
    "eligibility_router",
    "onboarding_router",
    "tts_router",
    "live_router",
]
