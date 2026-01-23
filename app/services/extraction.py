"""
Data extraction service using Gemini AI.
Includes extraction from web content and data sanitization.
"""
import logging
import json
import re
from datetime import datetime
from google.genai import types

from ..dependencies import gemini_client
from ..prompts import EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

# Valid values for database constraints
VALID_OPERATORS = {'=', '>=', '<=', '>', '<', 'in', 'not_in', 'exists', 'between'}
VALID_RULE_TYPES = {'gpa', 'degree', 'nationality', 'age', 'work_experience', 'language', 'other'}
VALID_REQ_TYPES = {'transcript', 'cv', 'essay', 'references', 'proposal', 'test', 'interview', 'other'}
VALID_STAGES = {'application', 'interview', 'nomination', 'result'}
VALID_CONFIDENCE = {'high', 'medium', 'inferred'}
VALID_LEVELS = {'bachelor', 'masters', 'phd', 'postdoc'}
VALID_FUNDING_TYPES = {'full', 'partial', 'tuition_only', 'stipend_only'}


def extract_with_gemini(content: str) -> dict:
    """Extract scholarship data from web content using Gemini AI."""
    logger.debug("=" * 50)
    logger.debug("STARTING GEMINI EXTRACTION")
    logger.debug("=" * 50)
    logger.debug(f"Content length for extraction: {len(content)} characters")
    logger.debug(f"Content preview (first 200 chars): {content[:200]}...")

    if not gemini_client:
        logger.error("CRITICAL: Gemini client is None - not initialized")
        raise Exception("Gemini client not initialized")

    logger.debug("Gemini client is valid, preparing request...")
    logger.debug(f"Using model: gemini-2.5-pro")
    logger.debug(f"Max output tokens: 32768")

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=f"{EXTRACTION_PROMPT}\n\nWebpage content:\n{content}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=32768  # 32k tokens to prevent cutoff
            )
        )
        logger.debug("Gemini API call successful")
    except Exception as e:
        logger.error(f"Gemini API call failed: {type(e).__name__}: {e}")
        raise

    logger.debug(f"Gemini response received, text length: {len(response.text)}")
    logger.debug(f"Response preview (first 500 chars): {response.text[:500]}...")
    
    try:
        result = json.loads(response.text)
        logger.debug(f"JSON parsed successfully")
        logger.debug(f"Extracted keys: {list(result.keys())}")
        logger.debug(f"Program name: {result.get('name', 'N/A')}")
        logger.debug(f"Confidence score: {result.get('confidence_score', 'N/A')}")
        logger.debug(f"Eligibility rules count: {len(result.get('eligibility_rules', []))}")
        logger.debug(f"Requirements count: {len(result.get('requirements', []))}")
        logger.debug(f"Deadlines count: {len(result.get('deadlines', []))}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed: {e}")
        logger.error(f"Raw response was: {response.text[:1000]}")
        raise
    
    logger.debug("EXTRACTION COMPLETE")
    return result


# ============================================================================
# SANITIZATION FUNCTIONS
# ============================================================================

def sanitize_level(level) -> str:
    """Ensure level is a single valid value."""
    if isinstance(level, list):
        for l in level:
            if isinstance(l, str) and l.lower() in VALID_LEVELS:
                return l.lower()
        return 'masters'

    if isinstance(level, str):
        level_lower = level.lower().strip()
        if level_lower in VALID_LEVELS:
            return level_lower

        mapping = {
            'undergraduate': 'bachelor',
            'bachelors': 'bachelor',
            "bachelor's": 'bachelor',
            'graduate': 'masters',
            "master's": 'masters',
            'master': 'masters',
            'msc': 'masters',
            'mba': 'masters',
            'doctoral': 'phd',
            'doctorate': 'phd',
            'post-doctoral': 'postdoc',
            'post-doc': 'postdoc',
        }
        return mapping.get(level_lower, 'masters')

    return 'masters'


def sanitize_funding_type(funding_type) -> str:
    """Ensure funding_type is a valid value."""
    if isinstance(funding_type, str):
        ft_lower = funding_type.lower().strip()
        if ft_lower in VALID_FUNDING_TYPES:
            return ft_lower
        if 'full' in ft_lower:
            return 'full'
        if 'tuition' in ft_lower:
            return 'tuition_only'
        if 'stipend' in ft_lower:
            return 'stipend_only'
    return 'partial'


def sanitize_int(value) -> int | None:
    """Safely convert value to integer."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            match = re.search(r'\d+', value)
            if match:
                return int(match.group())
        return None
    except:
        return None


def sanitize_float(value) -> float | None:
    """Safely convert value to float."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return round(float(value), 2)
        if isinstance(value, str):
            match = re.search(r'\d+\.?\d*', value)
            if match:
                return round(float(match.group()), 2)
        return None
    except:
        return None


def sanitize_eligibility_rule(rule: dict) -> dict | None:
    """Sanitize eligibility rule to match database constraints."""
    try:
        rule_type = rule.get('rule_type', 'other')
        operator = rule.get('operator', 'exists')
        confidence = rule.get('confidence', 'medium')

        operator_mapping = {
            'has': 'exists',
            'contains': 'in',
            'is': '=',
            'equals': '=',
            'greater': '>',
            'less': '<',
            'minimum': '>=',
            'maximum': '<=',
            'required': 'exists',
            'must': 'exists',
        }

        if operator not in VALID_OPERATORS:
            operator = operator_mapping.get(operator.lower(), 'exists')

        if rule_type not in VALID_RULE_TYPES:
            rule_type = 'other'

        if confidence not in VALID_CONFIDENCE:
            confidence = 'medium'

        return {
            'rule_type': rule_type,
            'operator': operator,
            'value': rule.get('value', {}),
            'confidence': confidence,
            'source_snippet': rule.get('source_snippet')
        }
    except Exception as e:
        logger.warning(f"Failed to sanitize eligibility rule: {e}")
        return None


def sanitize_requirement(req: dict) -> dict | None:
    """Sanitize requirement to match database constraints."""
    try:
        req_type = req.get('type', 'other')
        if req_type not in VALID_REQ_TYPES:
            req_type = 'other'

        return {
            'type': req_type,
            'description': req.get('description', 'Required document'),
            'mandatory': req.get('mandatory', True)
        }
    except Exception as e:
        logger.warning(f"Failed to sanitize requirement: {e}")
        return None


def sanitize_deadline(deadline: dict) -> dict | None:
    """Sanitize deadline to match database constraints."""
    try:
        stage = deadline.get('stage', 'application')
        if stage not in VALID_STAGES:
            stage = 'application'

        return {
            'cycle': deadline.get('cycle', 'Unknown'),
            'deadline_date': deadline.get('deadline_date'),
            'stage': stage
        }
    except Exception as e:
        logger.warning(f"Failed to sanitize deadline: {e}")
        return None


def sanitize_program_data(extracted: dict, url: str) -> dict:
    """Build sanitized program data from extraction result."""
    return {
        "name": extracted.get("name") or "Unknown Program",
        "provider": extracted.get("provider") or "Unknown",
        "level": sanitize_level(extracted.get("level")),
        "funding_type": sanitize_funding_type(extracted.get("funding_type")),
        "countries_eligible": extracted.get("countries_eligible") or [],
        "countries_of_study": extracted.get("countries_of_study") or [],
        "fields": extracted.get("fields") or [],
        "official_url": url,
        "description": extracted.get("description"),
        "who_wins": extracted.get("who_wins"),
        "rejection_reasons": extracted.get("rejection_reasons"),
        "status": "active",
        "last_verified_at": datetime.utcnow().isoformat(),
        "application_url": extracted.get("application_url"),
        "benefits": extracted.get("benefits") or {},
        "contact_email": extracted.get("contact_email"),
        "host_institution": extracted.get("host_institution"),
        "duration": extracted.get("duration"),
        "age_min": sanitize_int(extracted.get("age_min")),
        "age_max": sanitize_int(extracted.get("age_max")),
        "gpa_min": sanitize_float(extracted.get("gpa_min")),
        "language_requirements": extracted.get("language_requirements") or [],
        "award_amount": extracted.get("award_amount"),
        "number_of_awards": sanitize_int(extracted.get("number_of_awards")),
        "is_renewable": bool(extracted.get("is_renewable")) if extracted.get("is_renewable") is not None else None
    }
