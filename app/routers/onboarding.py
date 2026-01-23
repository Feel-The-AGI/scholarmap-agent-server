"""
Onboarding router - /onboarding/chat endpoint.
"""
import logging
import json
from google.genai import types

from fastapi import APIRouter

from ..dependencies import gemini_client
from ..models.schemas import (
    OnboardingChatRequest,
    OnboardingChatResponse,
)
from ..prompts import ONBOARDING_PROMPT

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/onboarding/chat", response_model=OnboardingChatResponse)
async def onboarding_chat(request: OnboardingChatRequest):
    """AI-powered conversational onboarding to extract user profile."""
    logger.debug("=" * 50)
    logger.debug("ONBOARDING CHAT REQUEST")
    logger.debug("=" * 50)
    logger.debug(f"Current step: {request.current_step}")
    logger.debug(f"Messages count: {len(request.messages)}")
    logger.debug(f"Existing extracted data: {request.extracted_data}")
    
    try:
        # Format messages for prompt
        messages_text = "\n".join([
            f"{m.role.upper()}: {m.content}" for m in request.messages
        ])
        logger.debug(f"Formatted messages: {messages_text[:200]}...")

        # Format extracted data
        extracted_text = json.dumps(request.extracted_data, indent=2) if request.extracted_data else "None yet"

        prompt = ONBOARDING_PROMPT.format(
            messages=messages_text,
            extracted_data=extracted_text,
            step=request.current_step
        )

        logger.debug("Calling Gemini for onboarding response...")
        response = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=1024,
                temperature=0.7
            )
        )

        logger.debug(f"Gemini response received, length: {len(response.text)}")
        result_text = response.text.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        result_text = result_text.strip()

        result = json.loads(result_text)

        logger.debug(f"Parsed result: response={result.get('response', '')[:50]}..., next_step={result.get('next_step')}, is_complete={result.get('is_complete')}")
        
        # Merge new extracted data with existing
        merged_data = {**request.extracted_data}
        if result.get("extracted_data"):
            for key, value in result["extracted_data"].items():
                if value is not None and value != "" and value != []:
                    merged_data[key] = value

        logger.debug(f"Merged extracted data: {merged_data}")
        logger.debug("Onboarding chat completed successfully")

        return OnboardingChatResponse(
            response=result.get("response", "Thanks for sharing! Let me process that..."),
            extracted_data=merged_data,
            next_step=result.get("next_step", request.current_step + 1),
            is_complete=result.get("is_complete", False)
        )

    except Exception as e:
        logger.error(f"Onboarding chat error: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Smart fallback based on step
        step = request.current_step
        fallback_questions = {
            0: "What's your name and where are you from?",
            1: "Great! What are you currently studying or what did you last complete? (e.g., BSc in Computer Science)",
            2: "What degree are you hoping to pursue next - Bachelor's, Master's, or PhD? And which countries interest you?",
            3: "Do you have any work experience? And roughly what's your GPA?",
            4: "Last question - any special circumstances that might help your application? (First-gen student, financial need, etc.)",
        }
        fallback_response = fallback_questions.get(step, "Thanks for sharing! Let me find scholarships for you...")

        return OnboardingChatResponse(
            response=fallback_response,
            extracted_data=request.extracted_data,
            next_step=request.current_step + 1,
            is_complete=step >= 4
        )
