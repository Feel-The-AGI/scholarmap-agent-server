#!/bin/bash
# Build script for Render deployment - Ultra-resilient scraper setup

set -e

echo "======================================"
echo "ScholarMap Backend Build Script"
echo "======================================"

echo ""
echo "[1/4] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "[2/4] Installing Playwright browsers..."
playwright install chromium
playwright install-deps chromium || echo "Warning: Some system deps may not install (expected on some systems)"

echo ""
echo "[3/4] Verifying curl_cffi installation..."
python -c "from curl_cffi import requests; print('curl_cffi OK')" || echo "Warning: curl_cffi may need system deps"

echo ""
echo "[4/4] Verifying all imports..."
python -c "
import httpx
import playwright
from bs4 import BeautifulSoup
from curl_cffi import requests
from fake_useragent import UserAgent
print('All imports OK!')
"

echo ""
echo "======================================"
echo "Build complete!"
echo "6-Layer Scraper Ready:"
echo "  Layer 1: curl_cffi (TLS impersonation)"
echo "  Layer 2: httpx (HTTP/2)"
echo "  Layer 3: cloudscraper (JS solver)"
echo "  Layer 4: Playwright basic stealth"
echo "  Layer 5: Playwright human simulation"
echo "  Layer 6: Playwright challenge bypass"
echo "======================================"
