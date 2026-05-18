# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
A US gas prices dashboard the user is building as their second coding project. Three pages planned:
- `index.html` (home) — Leaflet map; click a state → current price + 12-month trend
- `news/index.html` — recent gas/oil news via NewsAPI (v2)
- `dashboard/index.html` — national average, top/bottom states, charts via Chart.js (v2)

The eventual "click anywhere in the world" vision is gated on finding free international price data, which doesn't really exist. **Start US-only**, structure code so other countries can plug in later.

## Stack
- Plain HTML, CSS, vanilla JavaScript — no frameworks, no build tools, no `package.json`
- Libraries loaded from CDN in `<head>`: Leaflet (map), Chart.js will be added for charts
- Inline `<style>` and `<script>` blocks inside each HTML file — the user prefers everything in one place

## Data sources
- US prices: [EIA Open Data API](https://www.eia.gov/opendata/) — free, requires per-user API key
- News: [NewsAPI.org](https://newsapi.org) free tier (100 req/day)

API keys live in browser code for now (personal project, free APIs with low-stakes keys). If the project ever moves beyond personal use, proxy calls through a tiny backend rather than committing keys.

## Running, building, testing
No build, no tests, no lint, no install. Preview by opening `index.html` with the VS Code "Live Server" extension (right-click → Open with Live Server).

## About the user
- Beginner — this is their second project (first was a personal site)
- Comfortable with: plain HTML/CSS/JS, basic Git/GitHub workflow
- New to: `fetch()` / async-await, JSON APIs, charting libraries, map libraries

## How to help
- Explain new concepts in plain English the first time they appear
- When the user makes a mistake, explain *why* it didn't work — don't just fix it silently
- No frameworks, no bundlers, no npm — everything via CDN
- Keep changes small and reviewable; ship one working slice at a time rather than a complete-but-overwhelming change
