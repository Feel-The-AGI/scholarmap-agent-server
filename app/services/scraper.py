"""
Ultra-resilient web scraper with 6-layer fallback system.

Layers:
1. curl_cffi - TLS fingerprint impersonation (fastest)
2. httpx - HTTP/2 with browser headers
3. Cloudscraper - JS challenge solver (no browser)
4. Playwright basic - Real browser, minimal simulation
5. Playwright human - Full human simulation
6. Playwright challenge - Cloudflare/challenge bypass
"""
import logging
import random
import asyncio
from bs4 import BeautifulSoup
import httpx
from curl_cffi import requests as curl_requests
from fake_useragent import UserAgent
import cloudscraper
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Initialize fake user agent generator
try:
    ua = UserAgent(browsers=['chrome', 'firefox', 'safari', 'edge'])
except:
    ua = None
    logger.warning("Failed to initialize UserAgent, using fallback list")

# Fallback User-Agents
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
    """Get a random user agent, preferring real-time generation."""
    try:
        if ua:
            return ua.random
    except:
        pass
    return random.choice(FALLBACK_USER_AGENTS)


def get_browser_headers() -> dict:
    """Generate realistic browser headers."""
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


# ============================================================================
# LAYER 1: curl_cffi (TLS Fingerprint Impersonation)
# ============================================================================

async def fetch_with_curl_cffi(url: str) -> str | None:
    """
    Layer 1: curl_cffi with TLS fingerprint impersonation.
    Mimics Chrome's exact JA3/TLS fingerprint - bypasses most basic detection.
    """
    logger.info(f"[Layer 1] curl_cffi with TLS impersonation: {url}")

    for attempt, impersonate in enumerate(random.sample(CHROME_VERSIONS, min(3, len(CHROME_VERSIONS)))):
        try:
            logger.debug(f"  Attempt {attempt + 1} with impersonate={impersonate}")

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


# ============================================================================
# LAYER 2: httpx with Browser Headers
# ============================================================================

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


# ============================================================================
# LAYER 3: Cloudscraper (JS Challenge Solver)
# ============================================================================

async def fetch_with_cloudscraper(url: str) -> str | None:
    """
    Layer 3: Cloudscraper - solves Cloudflare JS challenges without browser.
    Uses a JS interpreter to solve challenges, much faster than Playwright.
    """
    logger.info(f"[Layer 3] Cloudscraper JS challenge solver: {url}")

    try:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True,
            },
            delay=random.uniform(3, 7),
        )

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
            block_indicators = ['blocked', 'captcha', 'challenge', 'attention required', 'access denied']
            if len(content) > 500 and not any(ind in content.lower()[:2000] for ind in block_indicators):
                logger.info(f"  [Layer 3] SUCCESS - Got {len(content)} chars")
                return content
            else:
                logger.warning("  Cloudscraper content may be blocked page")

    except Exception as e:
        logger.warning(f"  Cloudscraper failed: {e}")

    logger.info("  [Layer 3] FAILED - Moving to Layer 4")
    return None


# ============================================================================
# LAYER 4: Playwright Basic Stealth
# ============================================================================

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


# ============================================================================
# LAYER 5: Playwright with Human Simulation
# ============================================================================

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

            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
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
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}, loadTimes: function() {}, csi: function() {}, app: {}};
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({state: Notification.permission}) :
                        originalQuery(parameters)
                );
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                    return getParameter.apply(this, arguments);
                };
            """)

            page = await context.new_page()
            response = await page.goto(url, wait_until='networkidle', timeout=35000)

            if response and response.status in [403, 429, 503]:
                logger.warning(f"  Playwright human got {response.status}")
                await browser.close()
                return None

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


# ============================================================================
# LAYER 6: Playwright Challenge Bypass
# ============================================================================

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

            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}};
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                delete window.__nightmare;
                delete window._phantom;
                delete window.callPhantom;
            """)

            page = await context.new_page()
            logger.debug(f"  First navigation to {url}")
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)

            logger.debug("  Waiting for potential challenge...")
            await asyncio.sleep(5)

            content = await page.content()
            challenge_indicators = [
                'challenge-running', 'cf-browser-verification',
                'please wait', 'checking your browser', 'ddos-guard',
                'just a moment', 'verify you are human'
            ]

            if any(indicator in content.lower() for indicator in challenge_indicators):
                logger.debug("  Challenge detected, waiting longer...")
                await asyncio.sleep(8)
                try:
                    await page.wait_for_load_state('networkidle', timeout=15000)
                except:
                    pass

            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(random.uniform(1.0, 2.0))

            content = await page.content()
            await browser.close()

            if len(content) > 500:
                if not any(indicator in content.lower() for indicator in challenge_indicators):
                    logger.info(f"  [Layer 6] SUCCESS - Got {len(content)} chars")
                    return content

    except Exception as e:
        logger.warning(f"  Playwright challenge failed: {e}")

    logger.error("  [Layer 6] FAILED - All layers exhausted")
    return None


# ============================================================================
# HTML CONTENT CLEANER
# ============================================================================

def clean_html_content(content: str) -> str:
    """Clean HTML and extract readable text for LLM processing."""
    try:
        soup = BeautifulSoup(content, 'lxml')

        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript', 'iframe', 'svg']):
            element.decompose()

        text = soup.get_text(separator='\n', strip=True)

        if len(text) < 500:
            return content[:50000]

        return text[:50000]

    except Exception as e:
        logger.warning(f"HTML cleaning failed: {e}")
        return content[:50000]


# ============================================================================
# MAIN FETCH ORCHESTRATOR
# ============================================================================

async def fetch_page_content(url: str) -> str:
    """
    Ultra-resilient content fetcher with 6-layer fallback system.
    Tries increasingly sophisticated methods until one succeeds.
    """
    logger.info("=" * 60)
    logger.info(f"FETCHING: {url}")
    logger.info("=" * 60)

    # Layer 1: curl_cffi (TLS fingerprint - fastest)
    content = await fetch_with_curl_cffi(url)
    if content:
        return clean_html_content(content)

    # Layer 2: httpx (fast HTTP client)
    content = await fetch_with_httpx(url)
    if content:
        return clean_html_content(content)

    # Layer 3: Cloudscraper (JS challenge solver)
    content = await fetch_with_cloudscraper(url)
    if content:
        return clean_html_content(content)

    # Layer 4: Playwright basic
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

    raise Exception(f"Failed to fetch content from {url} - All 6 layers exhausted")
