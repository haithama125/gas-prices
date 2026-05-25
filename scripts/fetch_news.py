"""
fetch_news.py
=============

Fetches recent gas/oil news from GNews and writes data/news.json for
the frontend to load.

Why this exists: the news page used to call GNews directly from the
browser, but GNews's free tier is 100 requests/day per API key — shared
across every visitor. A handful of page loads exhausted it, and the
live site started showing "Failed to fetch" while localhost still
worked off remaining quota. Pre-baking the JSON once per refresh
moves all that traffic off the per-visitor path: now the browser just
fetches a static file, same pattern as data/eu-prices.json.

Run from the project root:

    python3 scripts/fetch_news.py

No pip install — stdlib only. Reads the GNews API key from the
GNEWS_API_KEY env var if set, otherwise uses the same default that
ships in news/index.html (already public, so not a secret).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Already public in news/index.html — no point pretending it's a secret.
DEFAULT_GNEWS_KEY = "ed524fdc4a4a4c6deaf6e3733a8ad284"
GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY", DEFAULT_GNEWS_KEY)

# Same boolean-OR query the frontend used to send directly. GNews's `q`
# supports basic OR/AND in quotes.
QUERY = '"gas prices" OR "gasoline prices" OR "oil prices" OR petrol'

# Free tier caps `max` at 10 per request. Bump this if the user upgrades.
MAX_ARTICLES = 10

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "news.json"


def fetch_articles() -> list[dict]:
    url = "https://gnews.io/api/v4/search?" + urllib.parse.urlencode({
        "q": QUERY,
        "lang": "en",
        "max": MAX_ARTICLES,
        "apikey": GNEWS_API_KEY,
    })
    req = urllib.request.Request(url, headers={"User-Agent": "gas-prices/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        sys.exit(f"GNews returned HTTP {e.code}: {body}")

    return payload.get("articles", [])


def slim(article: dict) -> dict:
    # Keep only the fields the frontend renders. Drops the long `content`
    # field (~5 KB per article) so committed JSON stays small.
    return {
        "title": article.get("title"),
        "description": article.get("description"),
        "url": article.get("url"),
        "image": article.get("image"),
        "publishedAt": article.get("publishedAt"),
        "source": {"name": (article.get("source") or {}).get("name")},
    }


def main() -> int:
    articles = fetch_articles()
    if not articles:
        sys.exit("GNews returned 0 articles — refusing to overwrite data/news.json with empty list.")

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "GNews",
        "source_url": "https://gnews.io/",
        "query": QUERY,
        "articles": [slim(a) for a in articles],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUTPUT_PATH} ({len(payload['articles'])} articles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
