"""
Fetch a job-offer URL and turn the HTML into clean plain text suitable
for the analyzer.

Uses urllib (built-in) for the HTTP fetch and BeautifulSoup for parsing.
Falls back to a regex-only stripper if BeautifulSoup is unavailable.
"""

from __future__ import annotations

import html as html_mod
import re
import urllib.request
from urllib.parse import urlparse


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.0 Safari/605.1.15  cvo/0.2"
)
_BLOCK_TAGS = {"script", "style", "nav", "header", "footer", "aside",
               "iframe", "noscript", "form", "svg"}


def is_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def fetch_offer_text(url: str, timeout: int = 30) -> str:
    """
    Download `url` and return cleaned plain text. Raises RuntimeError
    on network / decoding errors with a friendly message.
    """
    if not is_url(url):
        raise ValueError(f"Not a valid http(s) URL: {url!r}")

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read()
    except Exception as e:
        raise RuntimeError(f"Could not fetch {url}: {e}") from e

    try:
        html = raw.decode(charset, errors="replace")
    except LookupError:
        html = raw.decode("utf-8", errors="replace")

    text = html_to_text(html)
    if not text.strip():
        raise RuntimeError(
            f"Fetched {url} but couldn't extract any text. The page may "
            "require JavaScript to render — copy the offer text into a "
            "local .txt file instead."
        )
    return text


def html_to_text(html: str) -> str:
    """Strip HTML to plain text. Prefers BeautifulSoup, regex fallback."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(_BLOCK_TAGS):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    except ImportError:
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>",  "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html_mod.unescape(text)

    # Normalize whitespace.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
