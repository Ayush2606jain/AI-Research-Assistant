import httpx
import trafilatura
from bs4 import BeautifulSoup

# A generic "AIResearchAssistant/1.0" UA advertises itself as a bot to any
# server doing basic UA sniffing — use a realistic desktop-browser UA and
# accompanying headers instead, since some sites serve a stripped-down page
# (or block outright) when they detect a non-browser client.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Below this length, either trafilatura over-pruned a non-article page, or
# the plain HTTP fetch got a bot-gated/JS-only page with little real content
# — trigger the headless-browser fallback.
MIN_USEFUL_CHARS = 500


class WebScrapeError(Exception):
    pass


def scrape_url(url: str) -> dict:
    """Fetch a URL and return {"title": str, "text": str}.

    Tries a plain HTTP fetch first (fast, no browser needed). If that
    returns too little usable text — common on JS-rendered pages, or sites
    that serve a stripped-down response to non-browser clients — falls back
    to rendering the page with a real headless browser (Playwright) and
    re-extracting from that instead.
    """
    text, title = "", url
    try:
        response = httpx.get(url, headers=REQUEST_HEADERS, timeout=20.0, follow_redirects=True)
        response.raise_for_status()
        text, title = _extract(response.text, url)
    except httpx.HTTPError:
        pass

    if len(text.strip()) < MIN_USEFUL_CHARS:
        try:
            rendered_html = _render_with_browser(url)
            rendered_text, rendered_title = _extract(rendered_html, url)
            if len(rendered_text.strip()) > len(text.strip()):
                text, title = rendered_text, rendered_title
        except Exception:
            pass  # keep whatever the plain fetch already found, if anything

    if not text.strip():
        raise WebScrapeError(f"No extractable text content found at {url}")

    return {"title": title, "text": text}


def _extract(html: str, url: str) -> tuple[str, str]:
    text = trafilatura.extract(html, include_tables=True, include_links=False) or ""
    title = _extract_title(html) or url
    if len(text.strip()) < MIN_USEFUL_CHARS:
        fallback_text = _full_text(html)
        if len(fallback_text.strip()) > len(text.strip()):
            text = fallback_text
    return text, title


def _render_with_browser(url: str) -> str:
    """Render a page with real headless Chromium and return its HTML —
    covers both JS-rendered content and simple bot-detection that serves a
    stripped-down page to non-browser clients. Requires `playwright install
    chromium` to have been run once; imported lazily so the rest of the app
    still works if that setup step was skipped."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=REQUEST_HEADERS["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
        finally:
            browser.close()
    return html


def _full_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None
