"""
Eligibility checking service using Gemini AI.
"""
import logging
import json
from google.genai import types

from ..dependencies import gemini_client
from ..prompts import ELIGIBILITY_PROMPT
from ..models.schemas import UserProfile, ProgramMatch

logger = logging.getLogger(__name__)


async def analyze_eligibility_batch(profile: UserProfile, programs: list[dict]) -> list[ProgramMatch]:
    """Analyze eligibility for multiple programs using LLM."""
    logger.debug("=" * 50)
    logger.debug("STARTING ELIGIBILITY BATCH ANALYSIS")
    logger.debug("=" * 50)
    logger.debug(f"Total programs to analyze: {len(programs)}")
    logger.debug(f"Profile nationality: {profile.nationality}")
    logger.debug(f"Profile degree: {profile.degree}")
    logger.debug(f"Target degree: {profile.target_degree}")
    logger.debug(f"Profile GPA: {profile.gpa}")
    logger.debug(f"Profile age: {profile.age}")
    logger.debug(f"Profile field: {profile.field_of_study}")
    
    results = []

    target_degree_label = {
        'bachelor': "Bachelor's degree",
        'masters': "Master's degree",
        'phd': "PhD/Doctorate",
        'postdoc': "Postdoctoral fellowship"
    }.get(profile.target_degree, profile.target_degree or 'Not specified')

    profile_text = f"""
- Nationality: {profile.nationality}
- Age: {profile.age or 'Not specified'}
- Current Education: {profile.degree}
- LOOKING FOR: {target_degree_label} scholarship
- GPA: {profile.gpa or 'Not specified'}
- Field of Study: {profile.field_of_study or 'Not specified'}
- Work Experience: {profile.work_experience_years} years
- Languages: {', '.join(profile.languages) if profile.languages else 'Not specified'}
- Financial Need: {'Yes' if profile.has_financial_need else 'Not specified' if profile.has_financial_need is None else 'No'}
- Refugee/Displaced: {'Yes' if profile.is_refugee else 'No'}
- Disability: {'Yes' if profile.has_disability else 'No'}
- Additional Info: {profile.additional_info or 'None'}
"""

    for idx, program in enumerate(programs):
        try:
            logger.debug(f"[{idx+1}/{len(programs)}] Analyzing program: {program.get('name', 'Unknown')} (ID: {program.get('id')})")
            # Build eligibility rules text
            rules_text = "None specified"
            if program.get('eligibility_rules'):
                rules = program['eligibility_rules']
                if isinstance(rules, list) and rules:
                    rules_text = "\n".join([
                        f"- {r.get('rule_type', 'other')}: {r.get('value', {})} (confidence: {r.get('confidence', 'unknown')})"
                        for r in rules
                    ])

            # Format age requirements
            age_req = "Not specified"
            if program.get('age_min') or program.get('age_max'):
                if program.get('age_min') and program.get('age_max'):
                    age_req = f"{program['age_min']}-{program['age_max']} years"
                elif program.get('age_max'):
                    age_req = f"Up to {program['age_max']} years"
                else:
                    age_req = f"{program['age_min']}+ years"

            # Format GPA requirements
            gpa_req = "Not specified"
            if program.get('gpa_min'):
                gpa_req = f"Minimum {program['gpa_min']} GPA"

            prompt = ELIGIBILITY_PROMPT.format(
                profile=profile_text,
                name=program.get('name', 'Unknown'),
                provider=program.get('provider', 'Unknown'),
                level=program.get('level', 'Unknown'),
                funding_type=program.get('funding_type', 'Unknown'),
                description=program.get('description') or 'No description available',
                countries_eligible=', '.join(program.get('countries_eligible', [])) or 'Not specified',
                countries_of_study=', '.join(program.get('countries_of_study', [])) or 'Not specified',
                fields=', '.join(program.get('fields', [])) or 'All fields',
                who_wins=program.get('who_wins') or 'Not specified',
                age_requirements=age_req,
                gpa_requirements=gpa_req,
                eligibility_rules=rules_text,
                target_degree_upper=target_degree_label.upper()
            )

            logger.debug(f"[{idx+1}] Sending to Gemini for analysis...")
            response = gemini_client.models.generate_content(
                model="gemini-2.5-pro",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=1024,
                    temperature=0.3
                )
            )

            logger.debug(f"[{idx+1}] Gemini response received, parsing...")
            result_text = response.text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result_text = result_text.strip()

            analysis = json.loads(result_text)
            logger.debug(f"[{idx+1}] Analysis result: status={analysis.get('status')}, score={analysis.get('match_score')}")

            results.append(ProgramMatch(
                program_id=program['id'],
                program_name=program.get('name', 'Unknown'),
                provider=program.get('provider', 'Unknown'),
                level=program.get('level', 'unknown'),
                funding_type=program.get('funding_type', 'unknown'),
                match_score=min(100, max(0, int(analysis.get('match_score', 50)))),
                status=analysis.get('status', 'maybe'),
                explanation=analysis.get('explanation', 'Unable to analyze this program.'),
                strengths=analysis.get('strengths', []),
                concerns=analysis.get('concerns', []),
                action_items=analysis.get('action_items', [])
            ))

        except Exception as e:
            logger.error(f"[{idx+1}] Error analyzing program {program.get('id')}: {type(e).__name__}: {e}")
            results.append(ProgramMatch(
                program_id=program['id'],
                program_name=program.get('name', 'Unknown'),
                provider=program.get('provider', 'Unknown'),
                level=program.get('level', 'unknown'),
                funding_type=program.get('funding_type', 'unknown'),
                match_score=50,
                status='maybe',
                explanation='We couldn\'t fully analyze this program. Please review the details manually.',
                strengths=[],
                concerns=['Automated analysis unavailable'],
                action_items=['Review program requirements directly on their website']
            ))

    logger.debug(f"ELIGIBILITY ANALYSIS COMPLETE: {len(results)} results")
    logger.debug(f"Results breakdown: eligible={sum(1 for r in results if r.status=='eligible')}, likely={sum(1 for r in results if r.status=='likely_eligible')}, maybe={sum(1 for r in results if r.status=='maybe')}, not_eligible={sum(1 for r in results if r.status=='not_eligible')}")
    return results
