#!/usr/bin/env python3
"""
Slice 4, step 1: can we get past Cloudflare and load a GasBuddy page?

GasBuddy sits behind Cloudflare's bot protection, so plain `urllib.request`
or `requests` will get blocked. The fix is to drive a *real* Chromium
browser via Playwright — Cloudflare sees a normal browser fingerprint and
(usually) lets us through.

This is the make-or-break experiment. If this script prints a real page
title like "New York Gas Prices" we're in business and can move on to
parsing station data. If it prints "Just a moment..." or similar, we have
a Cloudflare problem to solve before anything else.

Setup (once):
    pip install playwright
    playwright install chromium

Run:
    python3 scripts/scrape_gasbuddy.py

Watch the browser window that pops up. The HTML of whatever loads will be
saved to scrape_debug.html in the project root so we can grep for the
station-card selectors next.
"""

from playwright.sync_api import sync_playwright

# Pick one city to start. Once we know the pattern, this becomes a list.
TARGET = "https://www.gasbuddy.com/gasprices/new-york/new-york"

with sync_playwright() as p:
    # headless=False = a visible browser window. Two reasons:
    #   1. Easier to see what's going on while we're debugging.
    #   2. Cloudflare is more suspicious of headless browsers than visible
    #      ones, so a visible window has a better chance of passing.
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print(f"Loading {TARGET} ...")
    page.goto(TARGET, wait_until="domcontentloaded", timeout=60000)

    # Cloudflare's "checking your browser" interstitial usually clears
    # within a few seconds. Give it 6 to be safe before we read the page.
    page.wait_for_timeout(6000)

    title = page.title()
    print(f"Page title: {title!r}")

    html = page.content()
    with open("scrape_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved {len(html):,} bytes of HTML to scrape_debug.html")

    # Keep the window open so you can scroll the page and inspect with
    # devtools. Hit Enter in the terminal when you're done looking.
    input("Press Enter to close the browser ...")
    browser.close()
