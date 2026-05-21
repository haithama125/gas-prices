# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
A US gas prices dashboard the user is building as their second coding project. Three pages planned:
- `index.html` (home) — Leaflet map; click a state → current price + 12-month trend
- `news/index.html` — recent gas/oil news via NewsAPI (v2)
- `dashboard/index.html` — national average, top/bottom states, charts via Chart.js (v2)

The eventual "click anywhere in the world" vision needs a small backend service — the user rents Hetzner servers and is willing to host one. The plan is to ship US-only first as a pure static page (browser → EIA directly), then layer in a backend for international coverage and finer-grain US data. See **Roadmap** below.

## Roadmap (build in slices)

Ship one working slice at a time — don't try to build the whole vision before anything works in the browser.

1. **US states + metros (EIA)** — Click a state shape → state-level or PADD regional retail gasoline price. Click one of ~10 metro pins (Boston, Chicago, Cleveland, Denver, Houston, LA, Miami, NYC, SF, Seattle) → city retail price. *No backend — direct browser fetch from EIA v2 API.*
2. **EU countries (Oil Bulletin)** — Click an EU country → weekly retail price. *Currently a pre-baked static JSON in `data/eu-prices.json`, refreshed by running `python3 scripts/fetch_eu_prices.py` (needs `pip install openpyxl`). The eventual Hetzner version would just be that same script behind a weekly cron.*
3. **Other countries (GlobalPetrolPrices)** — Click any country → latest price. *Pre-baked static JSON in `data/world-prices.json`, refreshed by running `python3 scripts/fetch_world_prices.py`. Turned out GPP serves the chart as plain HTML, so a single `urllib` GET + regex parse is enough — no headless browser, no Hetzner needed. ToS-grey but not actively blocked. Country polygons in `data/world-countries.geojson` (Natural Earth 110m, filtered to exclude US + EU members + Antarctica so layers don't overlap).*
4. **US county/city (GasBuddy)** — Click anywhere in the US → nearest station price. *Headless-browser scraper via Playwright. Two scripts so far: `scripts/scrape_gasbuddy.py` is the one-page Cloudflare check (saves `scrape_debug.html` for inspection); `scripts/scrape_gasbuddy_cities.py` loops the 10 metros and writes `data/us-city-prices.json`. Cloudflare lets a real Chromium through without extra tricks. The Hetzner cron version would just run the same script daily.*

Currently in: **Slice 4 scraper working locally, frontend integration next.**

### Slice 4 implementation notes (read before touching the scraper)

- GasBuddy ships a `window.__APOLLO_STATE__` JSON blob inside the page HTML. It has every station's `id`, `name`, `brand`, structured address, and `latitude`/`longitude` — but **not** the current price (prices load via a follow-up GraphQL fetch that fills the DOM). So the scraper does both: pull metadata from Apollo state, pull current price from the DOM, merge them by station id.
- CSS classes are CSS-modules with a build-time hash suffix, e.g. `StationDisplay-module__stationNameHeader___1A2q8`. The hash will change on every deploy, so use Playwright's `[class*="<stable-prefix>"]` selector form, not exact-match. Stable prefixes worth knowing:
  - `GenericStationListItem-module__stationListItem` — one station card
  - `StationDisplay-module__stationNameHeader` — wraps `<a href="/station/<id>">Brand</a>` (use the href to get the station id)
  - `StationDisplay-module__address` — street address text
  - `StationDisplayPrice-module__price___` — the `$X.XX` text (the trailing `___` matters — without it you'd also match `priceContainer`/`priceCard`, which are different elements)
- Price text is normally `"$3.85"` but can be `"—"` when no recent report exists. Parse only the `$N.NN` case; leave `price_usd_per_gallon` as `null` otherwise and keep the raw `price_text` for debugging.
- **Headless mode requires `playwright-stealth`.** Plain headless Chromium gets stuck at Cloudflare's interstitial and every page times out (verified — 32/56 failures in a row before we killed it). The fix is wrapping the Playwright context with `Stealth().use_sync(sync_playwright())`, which patches navigator.webdriver, plugins, UA, etc. so the headless fingerprint stops looking like a bot. With stealth on, `headless=True` works and the New York test page returns `$3.85` cleanly.
- **Stealth alone isn't enough at scale — also rotate contexts.** In a single stealth context Cloudflare still flips to block mode after ~32 fast page loads (verified: first 32 cities succeeded, next 25 in a row failed). Mitigations baked into the scraper: rotate the browser every `BATCH_SIZE=12` cities (close and re-launch), randomized 3–7s pause between cities, 25–45s cooldown between batches. Combined, these keep us under Cloudflare's threshold for a 56-city run.
- **Output is written incrementally** after every city via an atomic temp-file rename, and the script auto-resumes on re-run: any city already present and non-empty in `data/us-city-prices.json` is skipped. So if a run gets partway and dies, just re-run — it picks up where it left off and only retries the failed/missing cities. To force a full re-scrape, delete the JSON file.
- The cities to scrape live in the `CITIES` list at the top of `scripts/scrape_gasbuddy_cities.py` — currently ~55 major US metros spread across all regions. To add a city: copy whatever's after `/gasprices/` in the URL. If it has a slash, use a 2-tuple (e.g. `("oregon", "eugene")` for `gasprices/oregon/eugene`). If it doesn't (rare — DC is the example), use a bare string (`"washington-dc"` for `gasprices/washington-dc`). Bad slugs fail gracefully via the per-city `try/except` — they show up as an empty list in the JSON, and the next run will retry just those.

## Stack
- Plain HTML, CSS, vanilla JavaScript — no frameworks, no build tools, no `package.json`
- Libraries loaded from CDN in `<head>`: Leaflet (map), Chart.js will be added for charts
- Inline `<style>` and `<script>` blocks inside each HTML file — the user prefers everything in one place

## Data sources
- US prices: [EIA Open Data API](https://www.eia.gov/opendata/) — free, requires per-user API key
- News: [NewsAPI.org](https://newsapi.org) free tier (100 req/day)

API keys live in browser code for now (personal project, free APIs with low-stakes keys). If the project ever moves beyond personal use, proxy calls through a tiny backend rather than committing keys.

## Running, building, testing
No build, no tests, no lint, no install. Preview by opening `index.html` with the VS Code "Live Server" extension (right-click → Open with Live Server). Note: the frontend fetches `data/*.json`, so you do need a server (Live Server, `python3 -m http.server`, etc.) — opening the file with `file://` will fail those fetches due to browser CORS rules.

To refresh EU prices: `pip install openpyxl` once, then `python3 scripts/fetch_eu_prices.py`. The script downloads the latest EU Weekly Oil Bulletin XLSX, parses it, and overwrites `data/eu-prices.json`. The bulletin updates Thursdays.

To refresh world prices: `python3 scripts/fetch_world_prices.py` (no extra deps — stdlib only). The script fetches globalpetrolprices.com + the Natural Earth country polygons and overwrites `data/world-prices.json` and `data/world-countries.geojson`. GPP updates weekly on Mondays.

To refresh US city prices: `pip install playwright playwright-stealth && playwright install chromium` once, then `python3 scripts/scrape_gasbuddy_cities.py`. The script launches headless Chromium with `playwright-stealth` patches applied (`Stealth().use_sync(sync_playwright())`), visits each metro in the `CITIES` list (~55 cities currently, ~6 min total because of a 2.5s polite pause between requests), and overwrites `data/us-city-prices.json`. The stealth wrapper is load-bearing — plain headless Chromium without it gets stuck at Cloudflare's interstitial and every page times out at 30s. There's also `scripts/test_stealth.py` for a one-page sanity check if you ever need to verify Cloudflare still lets us through.

## About the user
- Beginner — this is their second project (first was a personal site)
- Comfortable with: plain HTML/CSS/JS, basic Git/GitHub workflow
- New to: `fetch()` / async-await, JSON APIs, charting libraries, map libraries

## How to help
- Explain new concepts in plain English the first time they appear
- When the user makes a mistake, explain *why* it didn't work — don't just fix it silently
- No frameworks, no bundlers, no npm — everything via CDN
- Keep changes small and reviewable; ship one working slice at a time rather than a complete-but-overwhelming change
