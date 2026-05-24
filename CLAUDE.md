
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
3. **Other countries (GlobalPetrolPrices)** — Click any country → weekly price. *Hetzner scraper runs weekly, caches to JSON. ToS-grey, somewhat fragile.*
4. **US county/city (GasBuddy)** — Click anywhere in the US → nearest station price. *Hetzner headless-browser scraper (Playwright/Puppeteer), behind Cloudflare, ongoing maintenance. The most ambitious slice — defer until earlier ones are solid.*

Currently in: **Slice 4 in progress** — GasBuddy scraper + ~570 station dots are shipping; scheduled refreshes for all four pre-baked sources are wired via GitHub Actions (see `.github/workflows/`). After slice 4: **Planned features** below. **Planned feature 2 (price heatmap) is implemented as the default map style** — see note under it.

## Planned features (after slice 4)

Cross-cutting UI work, not new data sources. Build after the four data slices feel stable.

1. **Country/state search bar** in the header — single autocomplete across every clickable shape (US states + EU countries + world countries). On select: pan/zoom to the polygon's bounds and fire its existing click handler so the price popup opens. Reuses every existing fetch path, no new data wiring. Once the news page ships, a search result should also surface recent gas/oil articles mentioning the selected place.

2. **Price heatmap (default)** — Every clickable polygon (US state, EU country, world country) is colored by its current gasoline price on a single global USD/litre scale: green = cheap, yellow ≈ global avg, red = expensive (same convention as the GasBuddy station dots). All borders are white so the heat colors carry the signal uncontested. A legend sits in the bottom-left of the map with min/mid/max labels in the user's selected currency, so "Belgium is orange" actually means something. No opt-in toggle — this is the default appearance.

   **Implementation notes (pending in-browser smoke test):**
   - `scripts/fetch_us_prices.py` resolves all 50 states + DC to a per-state USD/gallon via 14 EIA series (9 state + 5 PADD fallback), writes `data/us-prices.json`. `.github/workflows/refresh-us-prices.yml` runs it Tuesday mornings UTC.
   - `index.html` exposes `priceColor(usdPerLitre)` (HSL green→yellow→red, clamped to [$0.20, $2.20] USD/L) and `paintHeatmap()` which keys US states by name and EU/world by iso2. `paintHeatmap()` is called after each polygon layer's GeoJSON finishes loading, and again from `applyTheme()` so a light/dark flip doesn't wipe colors.
   - Fallback polygons (no matching price entry) keep their per-layer theme fill from `stateStyleFor` / `euStyleFor` / `worldStyleFor`, which now also use the shared `POLYGON_BORDER` (white) and `POLYGON_REST_OPACITY` (0.65) so the look is consistent with priced polygons. Hover bumps opacity to `POLYGON_HOVER_OPACITY` (0.85).
   - Smoke test before declaring done: `python3 -m http.server 8000`, open `http://localhost:8000`, eyeball that (a) US/EU/world all recolor on first paint, (b) borders are white, (c) the bottom-left legend reads sensibly and re-labels when the currency dropdown changes, (d) a light/dark toggle doesn't wipe the colors, (e) GasBuddy station dots still appear past zoom 7. If everything looks blandly yellow, tighten the [MIN,MAX] range; if too much red, widen it.

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

## About the user
- Beginner — this is their second project (first was a personal site)
- Comfortable with: plain HTML/CSS/JS, basic Git/GitHub workflow
- New to: `fetch()` / async-await, JSON APIs, charting libraries, map libraries

## How to help
- Explain new concepts in plain English the first time they appear
- When the user makes a mistake, explain *why* it didn't work — don't just fix it silently
- No frameworks, no bundlers, no npm — everything via CDN
- Keep changes small and reviewable; ship one working slice at a time rather than a complete-but-overwhelming change
