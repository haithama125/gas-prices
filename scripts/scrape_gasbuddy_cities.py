#!/usr/bin/env python3
"""
Slice 4, step 2: scrape current GasBuddy prices for a list of US cities.

How this works (and why):

  GasBuddy sits behind Cloudflare, so we load each page with a real
  Chromium browser via Playwright. Once a page is loaded, two useful
  things end up in the HTML:

  1. A big JSON blob assigned to `window.__APOLLO_STATE__`. This is the
     React app's preloaded data — it includes every station's id, name,
     brand, structured address, and latitude/longitude. The blob is
     stable across builds, so it's safe to parse.

     What it does NOT include: the current price. GasBuddy fetches
     prices in a follow-up GraphQL request after first paint.

  2. The rendered station cards in the DOM. By the time we read the
     page, the prices have been filled in. We grab them from the DOM
     and match them back to the Apollo entries by station id (the id
     appears in the `/station/85502` link on each card).

  We use Playwright's `[class*="..."]` selectors so we match on stable
  class-name prefixes rather than the build-time hash suffixes (e.g.
  `StationDisplay-module__stationNameHeader___1A2q8` -> we match on
  the prefix and ignore the `___1A2q8`).

Anti-bot defense (learned the hard way):

  * Use `playwright-stealth` so the headless fingerprint doesn't scream
    "I'm a bot." Without this every page times out at Cloudflare.
  * Rotate the browser context every BATCH_SIZE cities. Empirically,
    Cloudflare starts blocking after ~32 fast page loads in one session.
  * Randomized per-city pauses + a longer cooldown between batches so
    we don't look like a metronome.

Resume:

  The output JSON is written after every successful city. On startup,
  any city already present (non-empty) is skipped, so re-running the
  script just retries the ones that failed last time. Delete the JSON
  file to force a full re-scrape.

Setup (once):
    pip install playwright playwright-stealth
    playwright install chromium

Run:
    python3 scripts/scrape_gasbuddy_cities.py

Output:
    data/us-city-prices.json
"""

import json
import random
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


# Rotate the browser context every N cities. In a single context, Cloudflare
# starts blocking us after ~32 fast page loads in a row. 12 keeps us well
# under that threshold and gives ~4-5 contexts per full run.
BATCH_SIZE = 12

# Per-city pause range (ms). Randomized so we don't look like a metronome
# hitting the same gap between requests every time.
PAUSE_MIN_MS = 3000
PAUSE_MAX_MS = 7000

# Cooldown between context rotations (seconds). Longer than the per-city
# pause — it's the "human steps away for a sec" between batches.
COOLDOWN_MIN_S = 25
COOLDOWN_MAX_S = 45


# Each entry is either:
#   - a (state-slug, city-slug) tuple → https://www.gasbuddy.com/gasprices/<state>/<city>
#   - or a single slug string         → https://www.gasbuddy.com/gasprices/<slug>
# Most metros follow the two-segment <state>/<city> form. A few one-off
# locations (DC, etc.) live at single-segment URLs on GasBuddy. To add a
# city: open the gasbuddy.com page in a browser and copy whatever comes
# after `/gasprices/` — if it has a slash, use a tuple; if not, use a
# string. Bad entries fail gracefully (empty list in the JSON, retry on
# next run).
CITIES = [
    ("alabama", "birmingham"),
    ("alaska", "anchorage"),
    ("arizona", "phoenix"),
    ("arizona", "tucson"),
    ("california", "los-angeles"),
    ("california", "sacramento"),
    ("california", "san-diego"),
    ("california", "san-francisco"),
    ("california", "san-jose"),
    ("colorado", "denver"),
    ("connecticut", "hartford"),
    "washington-dc",
    ("florida", "jacksonville"),
    ("florida", "miami"),
    ("florida", "orlando"),
    ("florida", "tampa"),
    ("georgia", "atlanta"),
    ("hawaii", "honolulu"),
    ("illinois", "chicago"),
    ("indiana", "indianapolis"),
    ("kentucky", "louisville"),
    ("louisiana", "new-orleans"),
    ("maryland", "baltimore"),
    ("massachusetts", "boston"),
    ("michigan", "detroit"),
    ("minnesota", "minneapolis"),
    ("missouri", "kansas-city"),
    ("missouri", "st-louis"),
    ("nebraska", "omaha"),
    ("nevada", "las-vegas"),
    ("new-jersey", "newark"),
    ("new-mexico", "albuquerque"),
    ("new-york", "buffalo"),
    ("new-york", "new-york"),
    ("north-carolina", "charlotte"),
    ("north-carolina", "raleigh"),
    ("ohio", "cincinnati"),
    ("ohio", "cleveland"),
    ("ohio", "columbus"),
    ("oklahoma", "oklahoma-city"),
    ("oklahoma", "tulsa"),
    ("oregon", "portland"),
    ("pennsylvania", "philadelphia"),
    ("pennsylvania", "pittsburgh"),
    ("rhode-island", "providence"),
    ("tennessee", "memphis"),
    ("tennessee", "nashville"),
    ("texas", "austin"),
    ("texas", "dallas"),
    ("texas", "fort-worth"),
    ("texas", "houston"),
    ("texas", "san-antonio"),
    ("utah", "salt-lake-city"),
    ("virginia", "richmond"),
    ("virginia", "virginia-beach"),
    ("washington", "seattle"),
    ("wisconsin", "milwaukee"),
]

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "us-city-prices.json"


def url_for(entry):
    """Build the GasBuddy URL for a CITIES entry (tuple or string)."""
    if isinstance(entry, tuple):
        state, city = entry
        return f"https://www.gasbuddy.com/gasprices/{state}/{city}"
    return f"https://www.gasbuddy.com/gasprices/{entry}"


def key_for(entry):
    """Dict-key for a CITIES entry — last URL segment, used as the
    per-city slot in `data/us-city-prices.json`."""
    if isinstance(entry, tuple):
        return entry[1]
    return entry


def parse_apollo_state(html):
    """Pull the window.__APOLLO_STATE__ JSON blob out of the page HTML and
    return a dict of station-id -> metadata.
    """
    m = re.search(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        return {}
    state = json.loads(m.group(1))
    stations = {}
    for key, val in state.items():
        if not key.startswith("Station:"):
            continue
        sid = key.split(":", 1)[1]
        brands = val.get("brands") or []
        addr = val.get("address") or {}
        stations[sid] = {
            "id": sid,
            "name": val.get("name"),
            "brand": brands[0]["name"] if brands else None,
            "address": addr.get("line1"),
            "city": addr.get("locality"),
            "state": addr.get("region"),
            "postal": addr.get("postalCode"),
            "lat": val.get("latitude"),
            "lng": val.get("longitude"),
        }
    return stations


def scrape_city(page, url):
    print(f"  -> {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Wait until at least one price has rendered. The trailing `___`
    # in the selector guards against accidentally matching
    # `priceContainer` / `priceCard`, which are different elements.
    page.wait_for_selector(
        '[class*="StationDisplayPrice-module__price___"]',
        timeout=30000,
    )

    html = page.content()
    meta = parse_apollo_state(html)

    cards = page.query_selector_all(
        '[class*="GenericStationListItem-module__stationListItem"]'
    )
    results = []
    for card in cards:
        # Station id lives in the `/station/<id>` href on the name link.
        link = card.query_selector(
            '[class*="StationDisplay-module__stationNameHeader"] a'
        )
        href = link.get_attribute("href") if link else None
        sid = href.rsplit("/", 1)[-1] if href else None
        if not sid or sid not in meta:
            continue

        price_el = card.query_selector(
            '[class*="StationDisplayPrice-module__price___"]'
        )
        price_text = price_el.inner_text().strip() if price_el else None

        # Price text is normally like "$3.85", but can be "—" if the
        # station hasn't been reported recently. Parse only the numeric
        # case; leave price=None otherwise.
        price = None
        if price_text and price_text.startswith("$"):
            try:
                price = float(price_text[1:])
            except ValueError:
                pass

        record = dict(meta[sid])
        record["price_usd_per_gallon"] = price
        record["price_text"] = price_text
        results.append(record)

    return results


def load_previous():
    """Resume support: read whatever's already on disk so we keep good
    data from past runs and only retry empty cities. Delete the JSON
    file to force a full re-scrape."""
    if not OUT_PATH.exists():
        return {"updated": int(time.time()), "cities": {}}
    try:
        return json.loads(OUT_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"updated": int(time.time()), "cities": {}}


def save(out):
    """Atomic-ish write: write to a temp file then rename, so a crash
    mid-write can't leave a half-written JSON file."""
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2))
    tmp.replace(OUT_PATH)


def main():
    # Print line-buffered so progress shows up live when piped to a file
    # (Python defaults to block buffering for non-tty stdout).
    sys.stdout.reconfigure(line_buffering=True)

    out = load_previous()

    # Drop stale keys from previous runs (e.g. an entry was removed from
    # CITIES, or its slug changed). Keeps the JSON in sync with the
    # current CITIES list.
    current_keys = {key_for(e) for e in CITIES}
    stale = [k for k in list(out["cities"].keys()) if k not in current_keys]
    for k in stale:
        del out["cities"][k]
    if stale:
        print(f"Dropped stale city keys: {stale}")

    # Only scrape cities that don't already have data. An empty list
    # counts as "failed last time, retry now".
    todo = [e for e in CITIES if not out["cities"].get(key_for(e))]
    skipped = len(CITIES) - len(todo)
    print(
        f"{len(todo)} cities to scrape, {skipped} already done. "
        f"(Delete {OUT_PATH.name} to force full re-scrape.)"
    )
    if not todo:
        return

    # `Stealth().use_sync(...)` wraps the Playwright API so every new
    # browser context automatically gets the stealth patches applied
    # (navigator.webdriver=false, realistic plugins/UA, etc.). Without
    # this, Cloudflare flags headless Chromium and the price selector
    # never renders.
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for i, entry in enumerate(todo):
                key = key_for(entry)
                url = url_for(entry)

                # Rotate the browser between batches so Cloudflare sees
                # a fresh fingerprint/cookies instead of one session
                # hammering them N times.
                if i > 0 and i % BATCH_SIZE == 0:
                    cooldown = random.uniform(COOLDOWN_MIN_S, COOLDOWN_MAX_S)
                    print(f"  ~~ rotating browser context, cooldown {cooldown:.1f}s")
                    browser.close()
                    time.sleep(cooldown)
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()

                print(f"[{i + 1}/{len(todo)}] {key} ...")
                try:
                    stations = scrape_city(page, url)
                    out["cities"][key] = stations
                    print(f"     got {len(stations)} stations")
                except Exception as e:
                    # One flaky city shouldn't kill the run — empty list
                    # is our "try again next time" marker.
                    print(f"     FAILED: {str(e).splitlines()[0]}")
                    out["cities"][key] = []

                # Write after every city so a crash/block partway through
                # doesn't lose what we already scraped.
                out["updated"] = int(time.time())
                save(out)

                # Randomized polite pause.
                page.wait_for_timeout(random.randint(PAUSE_MIN_MS, PAUSE_MAX_MS))
        finally:
            browser.close()

    total = sum(len(s) for s in out["cities"].values())
    filled = sum(1 for s in out["cities"].values() if s)
    print(f"\nWrote {total} stations across {filled}/{len(out['cities'])} cities to {OUT_PATH}")


if __name__ == "__main__":
    main()
