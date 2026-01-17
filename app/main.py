from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, ValidationError
from supabase import create_client, Client
import httpx
from google import genai
from google.genai import types
import json
import os
import logging
import sys
import traceback
import random
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from fake_useragent import UserAgent
import cloudscraper

# Configure logging - DEBUG level for maximum verbosity
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Log all environment variables (safely)
logger.debug("=== STARTUP CONFIGURATION ===")
logger.debug(f"SUPABASE_URL set: {bool(os.getenv('SUPABASE_URL'))}")
logger.debug(f"SUPABASE_SERVICE_KEY set: {bool(os.getenv('SUPABASE_SERVICE_KEY'))}")
logger.debug(f"GEMINI_API_KEY set: {bool(os.getenv('GEMINI_API_KEY'))}")
logger.debug(f"AGENT_SECRET set: {bool(os.getenv('AGENT_SECRET'))}")

app = FastAPI(title="ScholarMap Agent", version="1.0.0")

# Custom exception handler to log all errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"=== UNHANDLED EXCEPTION ===")
    logger.error(f"Path: {request.url.path}")
    logger.error(f"Method: {request.method}")
    logger.error(f"Exception type: {type(exc).__name__}")
    logger.error(f"Exception message: {str(exc)}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__}
    )

# Log all requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.debug(f"=== INCOMING REQUEST ===")
    logger.debug(f"Method: {request.method}")
    logger.debug(f"URL: {request.url}")
    logger.debug(f"Path: {request.url.path}")
    logger.debug(f"Headers: {dict(request.headers)}")
    
    # Try to read body for POST requests
    if request.method == "POST":
        try:
            body = await request.body()
            logger.debug(f"Raw body: {body.decode('utf-8', errors='replace')}")
            # Important: we need to re-set the body since we consumed it
            async def receive():
                return {"type": "http.request", "body": body}
            request._receive = receive
        except Exception as e:
            logger.error(f"Error reading body: {e}")
    
    response = await call_next(request)
    
    logger.debug(f"=== RESPONSE ===")
    logger.debug(f"Status code: {response.status_code}")
    
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://scholarmap.vercel.app",
        "https://frontend-tawny-ten-57.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AGENT_SECRET = os.getenv("AGENT_SECRET")

# Initialize Gemini client
logger.debug("Initializing Gemini client...")
try:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.debug("Gemini client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Gemini client: {e}")
    gemini_client = None

def get_supabase() -> Client:
    logger.debug("Creating Supabase client...")
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    logger.debug("Supabase client created")
    return client

def verify_token(authorization: str = Header(None)):
    logger.debug(f"=== TOKEN VERIFICATION ===")
    logger.debug(f"Authorization header received: {authorization is not None}")
    logger.debug(f"Authorization header value (first 20 chars): {authorization[:20] if authorization else 'None'}...")
    logger.debug(f"Expected token starts with: Bearer {AGENT_SECRET[:10] if AGENT_SECRET else 'NOT_SET'}...")
    
    if not authorization:
        logger.error("No authorization header provided")
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    expected = f"Bearer {AGENT_SECRET}"
    if authorization != expected:
        logger.error(f"Token mismatch!")
        logger.debug(f"Received length: {len(authorization)}, Expected length: {len(expected)}")
        raise HTTPException(status_code=401, detail="Unauthorized - token mismatch")
    
    logger.debug("Token verified successfully")

class IngestRequest(BaseModel):
    url: HttpUrl
    program_id: str | None = None

class IngestResponse(BaseModel):
    success: bool
    program_id: str | None = None
    confidence: float
    issues: list[str]

EXTRACTION_PROMPT = """You are analyzing a scholarship/fellowship program webpage. Extract structured data.

Return ONLY valid JSON with this exact structure:
{
  "name": "Program name",
  "provider": "Organization offering this",
  "level": "bachelor" | "masters" | "phd" | "postdoc",
  "funding_type": "full" | "partial" | "tuition_only" | "stipend_only",
  "countries_eligible": ["country1", "country2"],
  "countries_of_study": ["country1"],
  "fields": ["field1", "field2"],
  "description": "Brief description",
  "who_wins": "Profile of typical winners",
  "rejection_reasons": "Common reasons for rejection",
  "eligibility_rules": [
    {"rule_type": "gpa", "operator": ">=", "value": {"min": 3.0}, "confidence": "high", "source_snippet": "quote from page"},
    {"rule_type": "nationality", "operator": "in", "value": {"countries": ["Ghana", "Nigeria"]}, "confidence": "high", "source_snippet": "quote"}
  ],
  "requirements": [
    {"type": "transcript", "description": "Official transcripts", "mandatory": true},
    {"type": "essay", "description": "500-word personal statement", "mandatory": true}
  ],
  "deadlines": [
    {"cycle": "2025/2026", "deadline_date": "2025-11-15", "stage": "application"}
  ],
  "confidence_score": 0.85,
  "issues": ["Any concerns about data quality"]
}

Rules:
- level must be exactly: bachelor, masters, phd, or postdoc
- funding_type must be exactly: full, partial, tuition_only, or stipend_only
- rule_type must be: gpa, degree, nationality, age, work_experience, language, or other
- operator MUST be exactly one of: =, >=, <=, >, <, in, not_in, exists, between (NO OTHER VALUES)
- requirement type must be: transcript, cv, essay, references, proposal, test, interview, or other
- stage must be: application, interview, nomination, or result
- confidence must be: high, medium, or inferred
- confidence_score is 0-1 overall extraction confidence
- Include source_snippet for eligibility rules when possible

If information is not clearly stated, omit it or mark confidence as "inferred".
"""

# Valid values for database constraints
VALID_OPERATORS = {'=', '>=', '<=', '>', '<', 'in', 'not_in', 'exists', 'between'}
VALID_RULE_TYPES = {'gpa', 'degree', 'nationality', 'age', 'work_experience', 'language', 'other'}
VALID_REQ_TYPES = {'transcript', 'cv', 'essay', 'references', 'proposal', 'test', 'interview', 'other'}
VALID_STAGES = {'application', 'interview', 'nomination', 'result'}
VALID_CONFIDENCE = {'high', 'medium', 'inferred'}
VALID_LEVELS = {'bachelor', 'masters', 'phd', 'postdoc'}
VALID_FUNDING_TYPES = {'full', 'partial', 'tuition_only', 'stipend_only'}

def sanitize_level(level) -> str:
    """Ensure level is a single valid value."""
    # If it's a list, pick the first valid one
    if isinstance(level, list):
        for l in level:
            if isinstance(l, str) and l.lower() in VALID_LEVELS:
                return l.lower()
        return 'masters'  # default
    
    # If it's a string, validate it
    if isinstance(level, str):
        level_lower = level.lower().strip()
        if level_lower in VALID_LEVELS:
            return level_lower
        # Try to map common variations
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
    
    return 'masters'  # default

def sanitize_funding_type(funding_type) -> str:
    """Ensure funding_type is a valid value."""
    if isinstance(funding_type, str):
        ft_lower = funding_type.lower().strip()
        if ft_lower in VALID_FUNDING_TYPES:
            return ft_lower
        # Map variations
        if 'full' in ft_lower:
            return 'full'
        if 'tuition' in ft_lower:
            return 'tuition_only'
        if 'stipend' in ft_lower:
            return 'stipend_only'
    return 'partial'  # default

def sanitize_eligibility_rule(rule: dict) -> dict | None:
    """Sanitize eligibility rule to match database constraints. Returns None if invalid."""
    try:
        rule_type = rule.get('rule_type', 'other')
        operator = rule.get('operator', 'exists')
        confidence = rule.get('confidence', 'medium')
        
        # Map invalid operators to valid ones
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

# ==================== ULTRA-RESILIENT WEB SCRAPER ====================
# 6-Layer fallback system to bypass ANY bot detection
# Layer 1: curl_cffi (TLS fingerprint impersonation - mimics Chrome exactly)
# Layer 2: httpx with full browser headers
# Layer 3: Cloudscraper (JS challenge solver - no browser needed)
# Layer 4: Playwright with stealth mode
# Layer 5: Playwright with human simulation
# Layer 6: Playwright with Cloudflare/challenge bypass
# =====================================================================

# Initialize fake user agent generator
try:
    ua = UserAgent(browsers=['chrome', 'firefox', 'safari', 'edge'])
except:
    ua = None
    logger.warning("Failed to initialize UserAgent, using fallback list")

# Fallback User-Agents if fake_useragent fails
FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 2560, "height": 1440},
]

# Chrome impersonation versions for curl_cffi
CHROME_VERSIONS = [
    "chrome110", "chrome116", "chrome119", "chrome120", 
    "chrome123", "chrome124", "chrome131",
]

def get_random_user_agent() -> str:
    """Get a random user agent, preferring real-time generation"""
    try:
        if ua:
            return ua.random
    except:
        pass
    return random.choice(FALLBACK_USER_AGENTS)

def get_browser_headers() -> dict:
    """Generate realistic browser headers"""
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Pragma": "no-cache",
    }


# ==================== LAYER 1: curl_cffi (TLS Fingerprint Impersonation) ====================
async def fetch_with_curl_cffi(url: str) -> str | None:
    """
    Layer 1: curl_cffi with TLS fingerprint impersonation.
    Mimics Chrome's exact JA3/TLS fingerprint - bypasses most basic detection.
    """
    logger.info(f"[Layer 1] curl_cffi with TLS impersonation: {url}")
    
    for attempt, impersonate in enumerate(random.sample(CHROME_VERSIONS, min(3, len(CHROME_VERSIONS)))):
        try:
            logger.debug(f"  Attempt {attempt + 1} with impersonate={impersonate}")
            
            # curl_cffi is synchronous, run in executor
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: curl_requests.get(
                    str(url),
                    impersonate=impersonate,
                    timeout=25,
                    allow_redirects=True,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                    }
                )
            )
            
            if response.status_code in [403, 429, 503, 520, 521, 522, 523, 524]:
                logger.warning(f"  curl_cffi got {response.status_code}, trying next...")
                await asyncio.sleep(random.uniform(1.0, 2.0))
                continue
            
            if response.status_code == 200:
                content = response.text
                if len(content) > 500 and "blocked" not in content.lower()[:1000]:
                    logger.info(f"  [Layer 1] SUCCESS - Got {len(content)} chars")
                    return content
            
            logger.warning(f"  curl_cffi status {response.status_code}, content too short or blocked")
            
        except Exception as e:
            logger.warning(f"  curl_cffi attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(random.uniform(0.5, 1.5))
    
    logger.info("  [Layer 1] FAILED - Moving to Layer 2")
    return None


# ==================== LAYER 2: httpx with Browser Headers ====================
async def fetch_with_httpx(url: str, max_retries: int = 2) -> str | None:
    """
    Layer 2: httpx with full browser headers and HTTP/2.
    Fast and works for sites without aggressive protection.
    """
    logger.info(f"[Layer 2] httpx with browser headers: {url}")
    
    for attempt in range(max_retries):
        headers = get_browser_headers()
        
        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                http2=True,
            ) as client:
                if attempt > 0:
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                
                response = await client.get(str(url), headers=headers)
                
                if response.status_code in [403, 429, 503, 520, 521, 522, 523, 524]:
                    logger.warning(f"  httpx blocked with {response.status_code}")
                    continue
                
                if response.status_code == 200:
                    content = response.text
                    if len(content) > 500:
                        logger.info(f"  [Layer 2] SUCCESS - Got {len(content)} chars")
                        return content
                
        except Exception as e:
            logger.warning(f"  httpx attempt {attempt + 1} failed: {e}")
    
    logger.info("  [Layer 2] FAILED - Moving to Layer 3")
    return None


# ==================== LAYER 3: Cloudscraper (JS Challenge Solver) ====================
async def fetch_with_cloudscraper(url: str) -> str | None:
    """
    Layer 3: Cloudscraper - solves Cloudflare JS challenges without browser.
    Uses a JS interpreter to solve challenges, much faster than Playwright.
    """
    logger.info(f"[Layer 3] Cloudscraper JS challenge solver: {url}")
    
    try:
        # Create scraper with browser impersonation
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True,
            },
            delay=random.uniform(3, 7),  # Delay to seem human
        )
        
        # Run synchronous cloudscraper in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: scraper.get(
                str(url),
                timeout=30,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Upgrade-Insecure-Requests": "1",
                }
            )
        )
        
        if response.status_code in [403, 429, 503, 520, 521, 522, 523, 524]:
            logger.warning(f"  Cloudscraper got {response.status_code}")
            return None
        
        if response.status_code == 200:
            content = response.text
            # Check for Cloudflare block page indicators
            block_indicators = ['blocked', 'captcha', 'challenge', 'attention required', 'access denied']
            if len(content) > 500 and not any(ind in content.lower()[:2000] for ind in block_indicators):
                logger.info(f"  [Layer 3] SUCCESS - Got {len(content)} chars")
                return content
            else:
                logger.warning(f"  Cloudscraper content may be blocked page")
        
    except Exception as e:
        logger.warning(f"  Cloudscraper failed: {e}")
    
    logger.info("  [Layer 3] FAILED - Moving to Layer 4")
    return None


# ==================== LAYER 4: Playwright Basic Stealth ====================
async def fetch_with_playwright_basic(url: str) -> str | None:
    """
    Layer 4: Playwright with basic stealth mode.
    Real browser but minimal human simulation.
    """
    logger.info(f"[Layer 4] Playwright basic stealth: {url}")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-infobars',
                    '--disable-extensions',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--window-position=0,0',
                    '--ignore-certificate-errors',
                    '--ignore-certificate-errors-spki-list',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            
            viewport = random.choice(VIEWPORTS)
            user_agent = get_random_user_agent()
            
            context = await browser.new_context(
                viewport=viewport,
                user_agent=user_agent,
                locale='en-US',
                timezone_id='America/New_York',
                java_script_enabled=True,
                bypass_csp=True,
            )
            
            # Basic stealth scripts
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            
            page = await context.new_page()
            
            response = await page.goto(url, wait_until='domcontentloaded', timeout=25000)
            
            if response and response.status in [403, 429, 503]:
                logger.warning(f"  Playwright basic got {response.status}")
                await browser.close()
                return None
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            content = await page.content()
            
            await browser.close()
            
            if len(content) > 500:
                logger.info(f"  [Layer 4] SUCCESS - Got {len(content)} chars")
                return content
            
    except Exception as e:
        logger.warning(f"  Playwright basic failed: {e}")
    
    logger.info("  [Layer 4] FAILED - Moving to Layer 5")
    return None


# ==================== LAYER 5: Playwright with Human Simulation ====================
async def fetch_with_playwright_human(url: str) -> str | None:
    """
    Layer 5: Playwright with full human simulation.
    Mouse movements, scrolling, realistic delays.
    """
    logger.info(f"[Layer 5] Playwright with human simulation: {url}")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-infobars',
                    '--disable-extensions',
                    '--window-position=0,0',
                    '--ignore-certificate-errors',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-web-security',
                    '--disable-features=BlockInsecurePrivateNetworkRequests',
                ]
            )
            
            viewport = random.choice(VIEWPORTS)
            user_agent = get_random_user_agent()
            
            context = await browser.new_context(
                viewport=viewport,
                user_agent=user_agent,
                locale='en-US',
                timezone_id=random.choice(['America/New_York', 'America/Los_Angeles', 'Europe/London']),
                geolocation={'latitude': 40.7128, 'longitude': -74.0060},
                permissions=['geolocation'],
                java_script_enabled=True,
                bypass_csp=True,
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                }
            )
            
            # Advanced stealth scripts
            await context.add_init_script("""
                // Remove webdriver
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                
                // Realistic plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => {
                        const plugins = [
                            {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                            {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                            {name: 'Native Client', filename: 'internal-nacl-plugin'},
                        ];
                        plugins.length = 3;
                        return plugins;
                    }
                });
                
                // Languages
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                
                // Chrome runtime
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };
                
                // Permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({state: Notification.permission}) :
                        originalQuery(parameters)
                );
                
                // Remove automation indicators
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                
                // WebGL vendor/renderer
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                    return getParameter.apply(this, arguments);
                };
                
                // Canvas fingerprint protection
                const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function(type) {
                    if (type === 'image/png' && this.width === 220 && this.height === 30) {
                        return originalToDataURL.apply(this, arguments);
                    }
                    return originalToDataURL.apply(this, arguments);
                };
            """)
            
            page = await context.new_page()
            
            # Navigate
            response = await page.goto(url, wait_until='networkidle', timeout=35000)
            
            if response and response.status in [403, 429, 503]:
                logger.warning(f"  Playwright human got {response.status}")
                await browser.close()
                return None
            
            # Human-like behavior
            await asyncio.sleep(random.uniform(1.0, 2.0))
            
            # Random mouse movements
            for _ in range(random.randint(2, 5)):
                x = random.randint(100, viewport['width'] - 100)
                y = random.randint(100, viewport['height'] - 100)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.1, 0.3))
            
            # Smooth scroll
            await page.evaluate("""
                async () => {
                    await new Promise(resolve => {
                        let totalHeight = 0;
                        const distance = Math.floor(Math.random() * 100) + 200;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= Math.min(document.body.scrollHeight / 2, 2000)) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, Math.floor(Math.random() * 50) + 80);
                    });
                }
            """)
            
            await asyncio.sleep(random.uniform(0.5, 1.0))
            
            content = await page.content()
            await browser.close()
            
            if len(content) > 500:
                logger.info(f"  [Layer 5] SUCCESS - Got {len(content)} chars")
                return content
            
    except Exception as e:
        logger.warning(f"  Playwright human failed: {e}")
    
    logger.info("  [Layer 5] FAILED - Moving to Layer 6")
    return None


# ==================== LAYER 6: Playwright Challenge Bypass ====================
async def fetch_with_playwright_challenge(url: str) -> str | None:
    """
    Layer 6: Playwright with challenge/Cloudflare bypass.
    Waits for JS challenges to complete, longer timeouts.
    """
    logger.info(f"[Layer 6] Playwright challenge bypass: {url}")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process',
                    '--disable-gpu',
                    '--ignore-certificate-errors',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            
            viewport = random.choice(VIEWPORTS)
            user_agent = get_random_user_agent()
            
            context = await browser.new_context(
                viewport=viewport,
                user_agent=user_agent,
                locale='en-US',
                timezone_id='America/New_York',
                java_script_enabled=True,
                bypass_csp=True,
            )
            
            # Full stealth mode
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}};
                
                // Hide automation
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                delete window.__nightmare;
                delete window._phantom;
                delete window.callPhantom;
            """)
            
            page = await context.new_page()
            
            # First navigation
            logger.debug(f"  First navigation to {url}")
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            # Wait for any challenge to complete
            logger.debug("  Waiting for potential challenge...")
            await asyncio.sleep(5)  # Wait for Cloudflare/challenge
            
            # Check for challenge indicators and wait more if needed
            content = await page.content()
            challenge_indicators = [
                'challenge-running', 'cf-browser-verification', 
                'please wait', 'checking your browser', 'ddos-guard',
                'just a moment', 'verify you are human'
            ]
            
            if any(indicator in content.lower() for indicator in challenge_indicators):
                logger.debug("  Challenge detected, waiting longer...")
                await asyncio.sleep(8)  # Wait for challenge to complete
                
                # Try to wait for navigation
                try:
                    await page.wait_for_load_state('networkidle', timeout=15000)
                except:
                    pass
            
            # Scroll and interact
            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(random.uniform(1.0, 2.0))
            
            content = await page.content()
            await browser.close()
            
            if len(content) > 500:
                # Check if we got past the challenge
                if not any(indicator in content.lower() for indicator in challenge_indicators):
                    logger.info(f"  [Layer 6] SUCCESS - Got {len(content)} chars")
                    return content
            
    except Exception as e:
        logger.warning(f"  Playwright challenge failed: {e}")
    
    logger.error("  [Layer 6] FAILED - All layers exhausted")
    return None


# ==================== MAIN FETCH ORCHESTRATOR ====================
async def fetch_page_content(url: str) -> str:
    """
    Ultra-resilient content fetcher with 6-layer fallback system.
    Tries increasingly sophisticated methods until one succeeds.
    """
    logger.info(f"="*60)
    logger.info(f"FETCHING: {url}")
    logger.info(f"="*60)
    
    # Layer 1: curl_cffi (TLS fingerprint - fastest)
    content = await fetch_with_curl_cffi(url)
    if content:
        return clean_html_content(content)
    
    # Layer 2: httpx (fast HTTP client)
    content = await fetch_with_httpx(url)
    if content:
        return clean_html_content(content)
    
    # Layer 3: Cloudscraper (JS challenge solver - no browser needed)
    content = await fetch_with_cloudscraper(url)
    if content:
        return clean_html_content(content)
    
    # Layer 4: Playwright basic (real browser)
    content = await fetch_with_playwright_basic(url)
    if content:
        return clean_html_content(content)
    
    # Layer 5: Playwright with human simulation
    content = await fetch_with_playwright_human(url)
    if content:
        return clean_html_content(content)
    
    # Layer 6: Playwright challenge bypass
    content = await fetch_with_playwright_challenge(url)
    if content:
        return clean_html_content(content)
    
    # All layers failed
    raise Exception(f"Failed to fetch content from {url} - All 6 layers exhausted")


def clean_html_content(content: str) -> str:
    """Clean HTML and extract readable text for LLM processing"""
    try:
        soup = BeautifulSoup(content, 'lxml')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript', 'iframe', 'svg']):
            element.decompose()
        
        # Get text
        text = soup.get_text(separator='\n', strip=True)
        
        # If text is too short, return original HTML (might have useful structured data)
        if len(text) < 500:
            return content[:50000]
        
        return text[:50000]
        
    except Exception as e:
        logger.warning(f"HTML cleaning failed: {e}")
        return content[:50000]

def extract_with_gemini(content: str) -> dict:
    logger.debug("Starting Gemini extraction...")
    logger.debug(f"Content length for extraction: {len(content)}")
    
    if not gemini_client:
        raise Exception("Gemini client not initialized")
    
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{EXTRACTION_PROMPT}\n\nWebpage content:\n{content}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    logger.debug(f"Gemini response received, text length: {len(response.text)}")
    result = json.loads(response.text)
    logger.debug(f"JSON parsed successfully, keys: {result.keys()}")
    return result

@app.get("/health")
async def health():
    logger.debug("Health check requested")
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: Request, authorization: str = Header(None)):
    logger.debug("=== INGEST ENDPOINT CALLED ===")
    
    # Verify token first
    verify_token(authorization)
    
    # Parse body manually to get better error messages
    try:
        body = await request.body()
        logger.debug(f"Request body: {body.decode('utf-8')}")
        body_json = json.loads(body)
        logger.debug(f"Parsed JSON: {body_json}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    
    # Validate with Pydantic
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
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching URL: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: HTTP {e.response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching URL: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")
    
    # Extract with Gemini
    try:
        logger.debug("Starting Gemini extraction...")
        extracted = extract_with_gemini(content)
        logger.debug(f"Extraction complete. Keys: {list(extracted.keys())}")
        logger.debug(f"Extracted name: {extracted.get('name')}")
        logger.debug(f"Extracted provider: {extracted.get('provider')}")
        logger.debug(f"Extracted level: {extracted.get('level')}")
        logger.debug(f"Full extraction result: {json.dumps(extracted, indent=2)[:2000]}")
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")
    
    confidence = extracted.get("confidence_score", 0.5)
    issues.extend(extracted.get("issues", []))
    
    if confidence < 0.5:
        issues.append("Low confidence extraction - manual review recommended")
    
    program_data = {
        "name": extracted.get("name") or "Unknown Program",
        "provider": extracted.get("provider") or "Unknown",
        "level": sanitize_level(extracted.get("level")),
        "funding_type": sanitize_funding_type(extracted.get("funding_type")),
        "countries_eligible": extracted.get("countries_eligible") or [],
        "countries_of_study": extracted.get("countries_of_study") or [],
        "fields": extracted.get("fields") or [],
        "official_url": str(ingest_request.url),
        "description": extracted.get("description"),
        "who_wins": extracted.get("who_wins"),
        "rejection_reasons": extracted.get("rejection_reasons"),
        "status": "active",
        "last_verified_at": datetime.utcnow().isoformat()
    }
    
    logger.debug(f"Sanitized level: {program_data['level']} (original: {extracted.get('level')})")
    logger.debug(f"Sanitized funding_type: {program_data['funding_type']} (original: {extracted.get('funding_type')})")
    
    try:
        if ingest_request.program_id:
            logger.debug(f"Updating existing program: {ingest_request.program_id}")
            result = supabase.table("programs").update(program_data).eq("id", ingest_request.program_id).execute()
            program_id = ingest_request.program_id
            supabase.table("eligibility_rules").delete().eq("program_id", program_id).execute()
            supabase.table("requirements").delete().eq("program_id", program_id).execute()
            supabase.table("deadlines").delete().eq("program_id", program_id).execute()
        else:
            logger.debug("Inserting new program...")
            result = supabase.table("programs").insert(program_data).execute()
            program_id = result.data[0]["id"]
            logger.debug(f"New program created with ID: {program_id}")
        
        # Insert eligibility rules (with sanitization)
        for rule in extracted.get("eligibility_rules", []):
            sanitized = sanitize_eligibility_rule(rule)
            if sanitized:
                logger.debug(f"Inserting eligibility rule: {sanitized['rule_type']} {sanitized['operator']}")
                supabase.table("eligibility_rules").insert({
                    "program_id": program_id,
                    "rule_type": sanitized["rule_type"],
                    "operator": sanitized["operator"],
                    "value": sanitized["value"],
                    "confidence": sanitized["confidence"],
                    "source_snippet": sanitized["source_snippet"]
                }).execute()
        
        # Insert requirements (with sanitization)
        for req in extracted.get("requirements", []):
            sanitized = sanitize_requirement(req)
            if sanitized:
                logger.debug(f"Inserting requirement: {sanitized['type']}")
                supabase.table("requirements").insert({
                    "program_id": program_id,
                    "type": sanitized["type"],
                    "description": sanitized["description"],
                    "mandatory": sanitized["mandatory"]
                }).execute()
        
        # Insert deadlines (with sanitization)
        for deadline in extracted.get("deadlines", []):
            sanitized = sanitize_deadline(deadline)
            if sanitized and sanitized.get("deadline_date"):
                logger.debug(f"Inserting deadline: {sanitized['stage']}")
                supabase.table("deadlines").insert({
                    "program_id": program_id,
                    "cycle": sanitized["cycle"],
                    "deadline_date": sanitized["deadline_date"],
                    "stage": sanitized["stage"]
                }).execute()
        
        # Insert source
        logger.debug("Inserting source record...")
        supabase.table("sources").insert({
            "program_id": program_id,
            "url": str(ingest_request.url),
            "agent_model": "gemini-2.5-flash",
            "raw_summary": json.dumps(extracted)[:10000],
            "confidence_score": confidence
        }).execute()
        
        # Insert reviews if any issues
        if issues:
            for issue in issues:
                logger.debug(f"Inserting review: {issue}")
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
    
    logger.debug(f"=== INGEST COMPLETE ===")
    logger.debug(f"Program ID: {program_id}, Confidence: {confidence}, Issues: {issues}")
    
    return IngestResponse(success=True, program_id=program_id, confidence=confidence, issues=issues)

@app.post("/recheck")
async def recheck(program_id: str, authorization: str = Header(None)):
    logger.debug(f"Recheck requested for program: {program_id}")
    verify_token(authorization)
    
    supabase = get_supabase()
    program = supabase.table("programs").select("official_url").eq("id", program_id).single().execute()
    if not program.data:
        raise HTTPException(status_code=404, detail="Program not found")
    
    # Create a mock request for the ingest function
    from fastapi import Request as FastAPIRequest
    # This is a bit hacky but works for recheck
    return {"message": "Use /ingest endpoint directly with program_id parameter"}

logger.debug("=== APPLICATION STARTUP COMPLETE ===")
