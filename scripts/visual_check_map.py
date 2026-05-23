#!/usr/bin/env python3
"""
Visual smoke test for Slice 4: drives index.html with Playwright at a few
zoom levels and saves screenshots so we can eyeball whether the GasBuddy
station pins show up at the right times.

Requires:
  * A local server at http://localhost:8765 serving the repo root
    (python3 -m http.server 8765)

The map instance lives inside a const inside the page script, so this
script can't access it directly. We patch L.map() via an init script
that runs before Leaflet loads — the patched factory stashes every map
it creates on window.__map. Pure-test-side hack, no source changes.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("/tmp/gp-shots")
OUT.mkdir(exist_ok=True)
BASE = "http://localhost:8765/"


def set_view(page, lat, lng, zoom):
    """Programmatically pan + zoom the Leaflet map, then wait for tiles."""
    page.evaluate(
        "([lat, lng, z]) => window.__map.setView([lat, lng], z, {animate: false})",
        [lat, lng, zoom],
    )
    # Give the map a beat to redraw tiles + show/hide the station layer.
    page.wait_for_timeout(1500)


def count_stations(page):
    """How many station circle-markers are currently in the DOM?
    Leaflet renders circleMarkers as <path> elements with class
    'leaflet-interactive' inside an SVG, but so do other clickables.
    We narrow it down by fill color (the violet from --station-fill)."""
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('path.leaflet-interactive'))"
        ".filter(p => /8b5cf6/i.test(p.getAttribute('fill') || '')).length"
    )


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    # Intercept the assignment to window.L (when leaflet.js loads) and
    # wrap L.map so every Map it returns is also stashed on window.__map.
    # A setter is the only thing that runs synchronously between
    # Leaflet's UMD script and the page's inline `const map = L.map(...)`.
    page.add_init_script(
        """
        (() => {
          let _L;
          Object.defineProperty(window, 'L', {
            configurable: true,
            get() { return _L; },
            set(v) {
              _L = v;
              if (v && typeof v.map === 'function' && !v.map.__patched) {
                const orig = v.map;
                v.map = function (...args) {
                  const m = orig.apply(this, args);
                  window.__map = m;
                  return m;
                };
                v.map.__patched = true;
              }
            },
          });
        })();
        """
    )

    print(f"Loading {BASE}")
    page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
    # Wait for the station JSON fetch to finish and the layer to be built.
    page.wait_for_function("() => window.__map", timeout=10000)
    page.wait_for_timeout(3000)  # JSON fetches + first tile paint

    # --- 1. Default zoom (4) — country view, NO stations expected ---
    set_view(page, 39.8283, -98.5795, 4)
    n = count_stations(page)
    print(f"[zoom 4] station markers in DOM: {n}")
    page.screenshot(path=str(OUT / "01_zoom4_country.png"))

    # --- 2. Just below threshold (zoom 6, centered on NYC) ---
    set_view(page, 40.7128, -74.0060, 6)
    n = count_stations(page)
    print(f"[zoom 6, NYC] station markers in DOM: {n}")
    page.screenshot(path=str(OUT / "02_zoom6_nyc.png"))

    # --- 3. Just AT threshold (zoom 7, NYC) — stations should appear ---
    set_view(page, 40.7128, -74.0060, 7)
    n = count_stations(page)
    print(f"[zoom 7, NYC] station markers in DOM: {n}")
    page.screenshot(path=str(OUT / "03_zoom7_nyc.png"))

    # --- 4. Closer in (zoom 10, NYC) ---
    set_view(page, 40.7128, -74.0060, 10)
    n = count_stations(page)
    print(f"[zoom 10, NYC] station markers in DOM: {n}")
    page.screenshot(path=str(OUT / "04_zoom10_nyc.png"))

    # --- 5. Click a station marker, screenshot the popup ---
    # Grab the first violet circle and click it.
    page.evaluate(
        """() => {
            const dot = Array.from(document.querySelectorAll('path.leaflet-interactive'))
              .find(p => /8b5cf6/i.test(p.getAttribute('fill') || ''));
            if (dot) dot.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        }"""
    )
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT / "05_zoom10_popup.png"))

    # --- 6. Light-mode check ---
    page.click("#theme-toggle")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "06_zoom10_light.png"))

    browser.close()
    print(f"\nScreenshots in {OUT}")
