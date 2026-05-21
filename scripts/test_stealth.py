#!/usr/bin/env python3
"""
One-off test: can playwright-stealth + headless=True get past Cloudflare?

If page title comes back with "Gas Prices" in it, stealth works and we
can flip the city scraper to headless. If we get "Just a moment..." or
"Attention Required", stealth isn't enough on its own.
"""
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TARGET = "https://www.gasbuddy.com/gasprices/new-york/new-york"

with Stealth().use_sync(sync_playwright()) as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    print(f"Loading {TARGET} (headless+stealth) ...")
    page.goto(TARGET, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    title = page.title()
    print(f"Page title: {title!r}")
    # Did the price selector ever render?
    price_el = page.query_selector('[class*="StationDisplayPrice-module__price___"]')
    print(f"Price element found: {price_el is not None}")
    if price_el:
        print(f"First price text: {price_el.inner_text().strip()!r}")
    browser.close()
