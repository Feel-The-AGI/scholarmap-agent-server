"""
Ingestion router - /ingest, /batch-ingest, /recheck, /health endpoints.
"""
import logging
import json
import asyncio
import time
import traceback
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import ValidationError

from ..dependencies import get_supabase, verify_token
from ..models.schemas import (
    IngestRequest,
    IngestResponse,
    BatchIngestRequest,
    BatchItemResult,
    BatchIngestResponse,
)
from ..services.scraper import fetch_page_content
from ..services.extraction import (
    extract_with_gemini,
    sanitize_program_data,
    sanitize_eligibility_rule,
    sanitize_requirement,
    sanitize_deadline,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health():
    """Health check endpoint."""
    logger.debug("Health check requested")
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: Request, authorization: str = Header(None)):
    """Ingest a single scholarship URL."""
    logger.debug("=== INGEST ENDPOINT CALLED ===")

    verify_token(authorization)

    # Parse body manually for better error messages
    try:
        body = await request.body()
        logger.debug(f"Request body: {body.decode('utf-8')}")
        body_json = json.loads(body)
        logger.debug(f"Parsed JSON: {body_json}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    try:
        ingest_request = IngestRequest(**body_json)
        logger.debug(f"Pydantic validation passed. URL: {ingest_request.url}")
    except ValidationError as e:
        logger.error(f"Pydantic validation error: {e}")
        raise HTTPException(status_code=400, detail=f"Validation error: {e.errors()}")

    supabase = get_supabase()
    issues = []

    # Fetch page
    try:
        logger.debug(f"Fetching URL: {ingest_request.url}")
        content = await fetch_page_content(str(ingest_request.url))
        logger.debug(f"Page fetched, content length: {len(content)}")
    except Exception as e:
        logger.error(f"Error fetching URL: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")

    # Extract with Gemini
    try:
        logger.debug("Starting Gemini extraction...")
        extracted = extract_with_gemini(content)
        logger.debug(f"Extraction complete. Keys: {list(extracted.keys())}")
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    confidence = extracted.get("confidence_score", 0.5)
    issues.extend(extracted.get("issues", []))

    if confidence < 0.5:
        issues.append("Low confidence extraction - manual review recommended")

    program_data = sanitize_program_data(extracted, str(ingest_request.url))

    try:
        if ingest_request.program_id:
            logger.debug(f"Updating existing program: {ingest_request.program_id}")
            supabase.table("programs").update(program_data).eq("id", ingest_request.program_id).execute()
            program_id = ingest_request.program_id
            supabase.table("eligibility_rules").delete().eq("program_id", program_id).execute()
            supabase.table("requirements").delete().eq("program_id", program_id).execute()
            supabase.table("deadlines").delete().eq("program_id", program_id).execute()
        else:
            logger.debug("Inserting new program...")
            result = supabase.table("programs").insert(program_data).execute()
            program_id = result.data[0]["id"]
            logger.debug(f"New program created with ID: {program_id}")

        # Insert eligibility rules
        for rule in extracted.get("eligibility_rules", []):
            sanitized = sanitize_eligibility_rule(rule)
            if sanitized:
                supabase.table("eligibility_rules").insert({
                    "program_id": program_id,
                    "rule_type": sanitized["rule_type"],
                    "operator": sanitized["operator"],
                    "value": sanitized["value"],
                    "confidence": sanitized["confidence"],
                    "source_snippet": sanitized["source_snippet"]
                }).execute()

        # Insert requirements
        for req in extracted.get("requirements", []):
            sanitized = sanitize_requirement(req)
            if sanitized:
                supabase.table("requirements").insert({
                    "program_id": program_id,
                    "type": sanitized["type"],
                    "description": sanitized["description"],
                    "mandatory": sanitized["mandatory"]
                }).execute()

        # Insert deadlines
        for deadline in extracted.get("deadlines", []):
            sanitized = sanitize_deadline(deadline)
            if sanitized and sanitized.get("deadline_date"):
                supabase.table("deadlines").insert({
                    "program_id": program_id,
                    "cycle": sanitized["cycle"],
                    "deadline_date": sanitized["deadline_date"],
                    "stage": sanitized["stage"]
                }).execute()

        # Insert source
        supabase.table("sources").insert({
            "program_id": program_id,
            "url": str(ingest_request.url),
            "agent_model": "gemini-2.5-pro",
            "raw_summary": json.dumps(extracted)[:10000],
            "confidence_score": confidence
        }).execute()

        # Insert reviews if issues
        for issue in issues:
            supabase.table("agent_reviews").insert({
                "program_id": program_id,
                "issue_type": "suspicious" if confidence < 0.5 else "missing_data",
                "note": issue,
                "severity": "high" if confidence < 0.5 else "low"
            }).execute()

    except Exception as e:
        logger.error(f"Database error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    logger.debug("=== INGEST COMPLETE ===")
    return IngestResponse(success=True, program_id=program_id, confidence=confidence, issues=issues)


@router.post("/recheck")
async def recheck(program_id: str, authorization: str = Header(None)):
    """Recheck an existing program."""
    logger.debug(f"Recheck requested for program: {program_id}")
    verify_token(authorization)

    supabase = get_supabase()
    program = supabase.table("programs").select("official_url").eq("id", program_id).single().execute()
    if not program.data:
        raise HTTPException(status_code=404, detail="Program not found")

    return {"message": "Use /ingest endpoint directly with program_id parameter"}


async def process_single_url(url: str, supabase) -> BatchItemResult:
    """Process a single URL for batch ingestion."""
    start_time = time.time()

    try:
        logger.debug(f"[BATCH] Processing: {url}")

        if not url.startswith(('http://', 'https://')):
            return BatchItemResult(
                url=url,
                success=False,
                error="Invalid URL format",
                processing_time=time.time() - start_time
            )

        issues = []

        # Fetch content
        try:
            content = await fetch_page_content(url)
            if not content or len(content) < 100:
                return BatchItemResult(
                    url=url,
                    success=False,
                    error="Failed to fetch page content or page too short",
                    processing_time=time.time() - start_time
                )
        except Exception as e:
            return BatchItemResult(
                url=url,
                success=False,
                error=f"Scraping failed: {str(e)}",
                processing_time=time.time() - start_time
            )

        # Extract with Gemini
        try:
            extracted = extract_with_gemini(content)
        except Exception as e:
            return BatchItemResult(
                url=url,
                success=False,
                error=f"AI extraction failed: {str(e)}",
                processing_time=time.time() - start_time
            )

        confidence = extracted.get("confidence_score", 0.5)
        issues.extend(extracted.get("issues", []))

        if confidence < 0.5:
            issues.append("Low confidence extraction - manual review recommended")

        program_data = sanitize_program_data(extracted, url)

        # Insert into database
        try:
            result = supabase.table("programs").insert(program_data).execute()
            program_id = result.data[0]["id"]

            for rule in extracted.get("eligibility_rules", []):
                sanitized = sanitize_eligibility_rule(rule)
                if sanitized:
                    supabase.table("eligibility_rules").insert({
                        "program_id": program_id,
                        "rule_type": sanitized["rule_type"],
                        "operator": sanitized["operator"],
                        "value": sanitized["value"],
                        "confidence": sanitized["confidence"],
                        "source_snippet": sanitized["source_snippet"]
                    }).execute()

            for req in extracted.get("requirements", []):
                sanitized = sanitize_requirement(req)
                if sanitized:
                    supabase.table("requirements").insert({
                        "program_id": program_id,
                        "type": sanitized["type"],
                        "description": sanitized["description"],
                        "mandatory": sanitized["mandatory"]
                    }).execute()

            for deadline in extracted.get("deadlines", []):
                sanitized = sanitize_deadline(deadline)
                if sanitized and sanitized.get("deadline_date"):
                    supabase.table("deadlines").insert({
                        "program_id": program_id,
                        "cycle": sanitized["cycle"],
                        "deadline_date": sanitized["deadline_date"],
                        "stage": sanitized["stage"]
                    }).execute()

            supabase.table("sources").insert({
                "program_id": program_id,
                "url": url,
                "agent_model": "gemini-2.5-pro",
                "raw_summary": json.dumps(extracted)[:10000],
                "confidence_score": confidence
            }).execute()

            for issue in issues:
                supabase.table("agent_reviews").insert({
                    "program_id": program_id,
                    "issue_type": "suspicious" if confidence < 0.5 else "missing_data",
                    "note": issue,
                    "severity": "high" if confidence < 0.5 else "low"
                }).execute()

            logger.debug(f"[BATCH] Success: {url} -> {program_id}")
            return BatchItemResult(
                url=url,
                success=True,
                program_id=program_id,
                confidence=confidence,
                issues=issues,
                processing_time=time.time() - start_time
            )

        except Exception as e:
            return BatchItemResult(
                url=url,
                success=False,
                error=f"Database error: {str(e)}",
                processing_time=time.time() - start_time
            )

    except Exception as e:
        logger.error(f"[BATCH] Unexpected error for {url}: {e}")
        return BatchItemResult(
            url=url,
            success=False,
            error=f"Unexpected error: {str(e)}",
            processing_time=time.time() - start_time
        )


@router.post("/batch-ingest", response_model=BatchIngestResponse)
async def batch_ingest(request: BatchIngestRequest, authorization: str = Header(None)):
    """Batch ingest multiple scholarship URLs concurrently."""
    start_time = time.time()

    logger.debug("=== BATCH INGEST START ===")
    logger.debug(f"URLs to process: {len(request.urls)}")

    verify_token(authorization)

    urls = [url.strip() for url in request.urls if url.strip()]

    if not urls:
        raise HTTPException(status_code=400, detail="No valid URLs provided")

    if len(urls) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 URLs per batch")

    supabase = get_supabase()

    semaphore = asyncio.Semaphore(5)

    async def process_with_semaphore(url: str) -> BatchItemResult:
        async with semaphore:
            return await process_single_url(url, supabase)

    results = await asyncio.gather(
        *[process_with_semaphore(url) for url in urls],
        return_exceptions=False
    )

    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful
    total_time = time.time() - start_time

    logger.debug("=== BATCH INGEST COMPLETE ===")
    logger.debug(f"Total: {len(results)}, Success: {successful}, Failed: {failed}, Time: {total_time:.2f}s")

    return BatchIngestResponse(
        total=len(results),
        successful=successful,
        failed=failed,
        results=results,
        total_time=total_time
    )
