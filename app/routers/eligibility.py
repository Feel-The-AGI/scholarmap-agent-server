"""
Eligibility router - /check-eligibility endpoint.
"""
import logging
import time
from google.genai import types

from fastapi import APIRouter

from ..dependencies import get_supabase, gemini_client
from ..models.schemas import (
    EligibilityCheckRequest,
    EligibilityCheckResponse,
)
from ..services.eligibility import analyze_eligibility_batch

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/check-eligibility", response_model=EligibilityCheckResponse)
async def check_eligibility(request: EligibilityCheckRequest):
    """LLM-powered intelligent eligibility checker."""
    start_time = time.time()

    logger.info("=== ELIGIBILITY CHECK START ===")
    logger.info(f"Profile: {request.profile.nationality}, {request.profile.degree}")

    supabase = get_supabase()

    # Fetch all active programs with eligibility rules
    result = supabase.table("programs").select(
        "id, name, provider, level, funding_type, description, "
        "countries_eligible, countries_of_study, fields, who_wins, "
        "age_min, age_max, gpa_min, eligibility_rules(*)"
    ).eq("status", "active").execute()

    programs = result.data or []
    logger.info(f"Found {len(programs)} active programs to analyze")

    if not programs:
        return EligibilityCheckResponse(
            eligible=[],
            likely_eligible=[],
            maybe=[],
            unlikely=[],
            not_eligible=[],
            total_programs_analyzed=0,
            processing_time=time.time() - start_time,
            ai_summary="No active scholarship programs found in our database."
        )

    # Analyze all programs
    matches = await analyze_eligibility_batch(request.profile, programs)

    # Sort by match score
    matches.sort(key=lambda x: x.match_score, reverse=True)

    # Categorize results
    eligible = [m for m in matches if m.status == 'eligible']
    likely_eligible = [m for m in matches if m.status == 'likely_eligible']
    maybe = [m for m in matches if m.status == 'maybe']
    unlikely = [m for m in matches if m.status == 'unlikely']
    not_eligible = [m for m in matches if m.status == 'not_eligible']

    processing_time = time.time() - start_time

    # Generate overall summary
    total_good = len(eligible) + len(likely_eligible)
    summary_prompt = f"""Based on the analysis of {len(programs)} scholarships for a student from {request.profile.nationality} 
with a {request.profile.degree} degree, {total_good} scholarships look promising.

Write a 2-3 sentence encouraging and personalized summary for them. Be specific about their opportunities.
Return ONLY the summary text, no JSON."""

    try:
        summary_response = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=summary_prompt,
            config=types.GenerateContentConfig(max_output_tokens=200)
        )
        ai_summary = summary_response.text.strip()
    except:
        if total_good > 0:
            ai_summary = f"Great news! We found {total_good} scholarship{'s' if total_good != 1 else ''} that match your profile well. Your background and qualifications open up some exciting opportunities."
        else:
            ai_summary = f"While we didn't find perfect matches, there are {len(maybe)} scholarships worth exploring. Don't give up - many successful scholars didn't fit traditional profiles."

    logger.info("=== ELIGIBILITY CHECK COMPLETE ===")
    logger.info(f"Results: {len(eligible)} eligible, {len(likely_eligible)} likely, {len(maybe)} maybe, {len(not_eligible)} not eligible")
    logger.info(f"Processing time: {processing_time:.2f}s")

    return EligibilityCheckResponse(
        eligible=eligible,
        likely_eligible=likely_eligible,
        maybe=maybe,
        unlikely=unlikely,
        not_eligible=not_eligible,
        total_programs_analyzed=len(programs),
        processing_time=processing_time,
        ai_summary=ai_summary
    )
