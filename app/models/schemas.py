"""
Pydantic models for request/response schemas.
"""
from pydantic import BaseModel, HttpUrl


# ============================================================================
# INGESTION MODELS
# ============================================================================

class IngestRequest(BaseModel):
    """Request model for single URL ingestion."""
    url: HttpUrl
    program_id: str | None = None


class IngestResponse(BaseModel):
    """Response model for single URL ingestion."""
    success: bool
    program_id: str | None = None
    confidence: float
    issues: list[str]


class BatchIngestRequest(BaseModel):
    """Request model for batch URL ingestion."""
    urls: list[str]


class BatchItemResult(BaseModel):
    """Result for a single URL in batch processing."""
    url: str
    success: bool
    program_id: str | None = None
    confidence: float = 0.0
    issues: list[str] = []
    error: str | None = None
    processing_time: float = 0.0


class BatchIngestResponse(BaseModel):
    """Response model for batch URL ingestion."""
    total: int
    successful: int
    failed: int
    results: list[BatchItemResult]
    total_time: float


# ============================================================================
# ELIGIBILITY MODELS
# ============================================================================

class UserProfile(BaseModel):
    """User profile for eligibility checking."""
    nationality: str
    age: int | None = None
    degree: str  # Current/highest degree: BSc, BA, MSc, MA, PhD, High School
    target_degree: str | None = None  # What they're looking for: bachelor, masters, phd, postdoc
    gpa: float | None = None  # GPA on 4.0 scale
    field_of_study: str | None = None
    work_experience_years: int = 0
    languages: list[str] = []  # Languages with proficiency
    has_financial_need: bool | None = None
    is_refugee: bool = False
    has_disability: bool = False
    additional_info: str | None = None  # Free text for other relevant info


class EligibilityCheckRequest(BaseModel):
    """Request model for eligibility checking."""
    profile: UserProfile


class ProgramMatch(BaseModel):
    """A program match result with eligibility analysis."""
    program_id: str
    program_name: str
    provider: str
    level: str
    funding_type: str
    match_score: int  # 0-100
    status: str  # "eligible", "likely_eligible", "maybe", "unlikely", "not_eligible"
    explanation: str  # Personalized explanation
    strengths: list[str]  # What makes them a good fit
    concerns: list[str]  # Potential issues or missing requirements
    action_items: list[str]  # What they should do to apply/improve chances


class EligibilityCheckResponse(BaseModel):
    """Response model for eligibility checking."""
    eligible: list[ProgramMatch]
    likely_eligible: list[ProgramMatch]
    maybe: list[ProgramMatch]
    unlikely: list[ProgramMatch]
    not_eligible: list[ProgramMatch]
    total_programs_analyzed: int
    processing_time: float
    ai_summary: str  # Overall personalized summary


# ============================================================================
# ONBOARDING MODELS
# ============================================================================

class OnboardingMessage(BaseModel):
    """A single message in the onboarding conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str


class OnboardingChatRequest(BaseModel):
    """Request model for onboarding chat."""
    messages: list[OnboardingMessage]
    current_step: int
    extracted_data: dict


class OnboardingChatResponse(BaseModel):
    """Response model for onboarding chat."""
    response: str
    extracted_data: dict
    next_step: int
    is_complete: bool


# ============================================================================
# TEXT-TO-SPEECH MODELS
# ============================================================================

class TTSRequest(BaseModel):
    """Request model for text-to-speech conversion."""
    text: str
    voice: str = "Kore"  # Default to Kore (confirmed working female voice)
    style: str | None = None  # Optional style instruction like "warmly and encouragingly"


class TTSResponse(BaseModel):
    """Response model for text-to-speech conversion."""
    audio_base64: str
    format: str = "pcm"
    sample_rate: int = 24000
