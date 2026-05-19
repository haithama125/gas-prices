"""
fetch_world_prices.py
=====================

Downloads the latest gasoline prices from globalpetrolprices.com (~170
countries) and emits two artefacts for the frontend:

    data/world-prices.json       — { iso2: { name, gasoline_usd_per_l } }
    data/world-countries.geojson — country polygons keyed by iso2,
                                    excluding US + EU members (covered by
                                    their own layers) and Antarctica.

Run from the project root:

    python3 scripts/fetch_world_prices.py

No third-party dependencies — just the Python standard library.

Re-run to refresh; later, the same script can live on a server with a cron.

Sources:
  - GlobalPetrolPrices: https://www.globalpetrolprices.com/gasoline_prices/
  - Natural Earth Vector (110m countries):
      github.com/nvkelso/natural-earth-vector @ master
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GPP_URL = "https://www.globalpetrolprices.com/gasoline_prices/"

# Low-res world borders (~250 KB). Tiny countries like Singapore, Monaco,
# Malta, Andorra, and most Caribbean islands aren't represented at 110m —
# we still record their prices in world-prices.json (in case we later swap
# in a higher-res file), but they won't have a clickable polygon for now.
NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson"
)

# GPP-display-name -> ISO 3166-1 alpha-2.
# Most GPP names match Natural Earth's NAME / NAME_LONG directly, so we
# only need to alias the abbreviations, old names, and unique spellings.
GPP_NAME_ALIASES = {
    "Bahrain": "BH",
    "UAE": "AE",
    "Maldives": "MV",
    "Trinidad & Tobago": "TT",
    "DR Congo": "CD",
    "USA": "US",
    "Saint Lucia": "LC",
    "Mauritius": "MU",
    "Aruba": "AW",
    "Grenada": "GD",
    "Curacao": "CW",
    "Dom. Rep.": "DO",
    "Dominica": "DM",
    "Burma": "MM",       # NE calls this Myanmar
    "Swaziland": "SZ",   # officially renamed Eswatini in 2018
    "Malta": "MT",
    "Cape Verde": "CV",  # NE uses "Cabo Verde"
    "N. Maced.": "MK",
    "Seychelles": "SC",
    "Cayman Islands": "KY",
    "Bosnia & Herz.": "BA",
    "San Marino": "SM",
    "Barbados": "BB",
    "C. Afr. Rep.": "CF",
    "Andorra": "AD",
    "Wallis and Futuna": "WF",
    "UK": "GB",
    "Mayotte": "YT",
    "Monaco": "MC",
    "Singapore": "SG",
    "Liechtenstein": "LI",
    "Hong Kong": "HK",
    "Ivory Coast": "CI",  # NE uses "Côte d'Ivoire"
}

# Countries we cover with a dedicated layer already, plus Antarctica.
# These are dropped from world-countries.geojson so the world layer doesn't
# overlap (and visually fight with) the US states / EU bulletin layers.
EXCLUDED_FROM_WORLD_GEOJSON = {
    "US",  # US states + EIA city pins handle these
    "AQ",  # Antarctica — no data, takes a quarter of the map
    # EU Weekly Oil Bulletin (27 members):
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = PROJECT_ROOT / "data" / "world-prices.json"
GEOJSON_PATH = PROJECT_ROOT / "data" / "world-countries.geojson"


# ----- HTTP ---------------------------------------------------------------

def http_get(url: str) -> bytes:
    print(f"downloading {url}")
    # GPP returns 403 to bare urllib/curl UAs. Any normal browser-shaped UA
    # works — we're not pretending to be a specific browser, just not a bot.
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; gas-prices/0.1)"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


# ----- GPP parser ---------------------------------------------------------

# GPP renders the chart as plain HTML — no JSON, no JS-driven chart. Each
# country gets:
#   1. A label div outside the bar (because every bar is short enough that
#      its label wouldn't fit inside).
#   2. A price div positioned at top:2px inside the bar's outer container.
# Both lists appear in price-ascending order, so we zip them by index.
COUNTRY_RE = re.compile(
    r"<div class=\"outsideTitle outsideTitleElement\" id=\"hl\d+\"[^>]*>\s*"
    r"<a href='/[^']+/gasoline_prices/' class='graph_outside_link'>([^<]+)</a>"
)
PRICE_RE = re.compile(
    r'<div style="position: absolute; top: 2px;[^>]*>(\d\.\d{3})</div>'
)


def parse_gpp(html: str) -> list[tuple[str, float]]:
    raw_names = COUNTRY_RE.findall(html)
    prices = PRICE_RE.findall(html)
    if len(raw_names) != len(prices):
        sys.exit(
            f"GPP parse mismatch: {len(raw_names)} names vs {len(prices)} "
            "prices — the page layout may have changed."
        )
    rows = []
    for raw, price in zip(raw_names, prices):
        # &nbsp; appears after most names; "*" marks the date footnote.
        name = raw.replace("&nbsp;", "").replace("*", "").strip()
        rows.append((name, float(price)))
    return rows


# ----- Natural Earth helpers ---------------------------------------------

def build_name_to_iso2(ne_geojson: dict) -> dict[str, str]:
    """NE NAME / NAME_LONG -> ISO2.

    We deliberately ignore SOVEREIGNT / ADMIN because they encode political
    ownership (e.g. New Caledonia's SOVEREIGNT is "France"), which would
    overwrite the real France->FR entry. setdefault() means the first match
    wins, so the natural NAME entry always beats any later NAME_LONG.
    """
    out: dict[str, str] = {}
    for f in ne_geojson["features"]:
        p = f["properties"]
        iso2 = (p.get("ISO_A2_EH") or p.get("ISO_A2") or "").strip()
        if not iso2 or iso2 == "-99":
            continue
        for nf in ("NAME", "NAME_LONG"):
            n = p.get(nf)
            if n:
                out.setdefault(n.strip(), iso2)
    return out


def resolve_iso2(gpp_name: str, ne_lookup: dict[str, str]) -> str | None:
    # Aliases take priority over the NE lookup so that e.g. "USA" goes to
    # "US" even though NE happens to know the long name "United States".
    if gpp_name in GPP_NAME_ALIASES:
        return GPP_NAME_ALIASES[gpp_name]
    return ne_lookup.get(gpp_name)


def filter_geojson(ne: dict) -> dict:
    """Drop excluded countries and normalize each feature to {name, iso2}.

    The frontend joins on iso2; the display name comes from this property.
    """
    features = []
    for f in ne["features"]:
        p = f["properties"]
        iso2 = (p.get("ISO_A2_EH") or p.get("ISO_A2") or "").strip()
        if not iso2 or iso2 == "-99":
            continue
        if iso2 in EXCLUDED_FROM_WORLD_GEOJSON:
            continue
        name = p.get("NAME") or p.get("NAME_LONG") or iso2
        # NE writes "eSwatini"; title-case it for the popup.
        if iso2 == "SZ":
            name = "Eswatini"
        features.append({
            "type": "Feature",
            "properties": {"name": name, "iso2": iso2},
            "geometry": f["geometry"],
        })
    return {"type": "FeatureCollection", "features": features}


# ----- main ---------------------------------------------------------------

def main() -> int:
    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)

    html = http_get(GPP_URL).decode("utf-8", errors="replace")
    ne = json.loads(http_get(NE_URL))

    name_to_iso2 = build_name_to_iso2(ne)

    rows = parse_gpp(html)
    print(f"parsed {len(rows)} price rows from GPP")

    countries: dict[str, dict] = {}
    unresolved: list[str] = []
    for name, price in rows:
        iso2 = resolve_iso2(name, name_to_iso2)
        if not iso2:
            unresolved.append(name)
            continue
        countries[iso2] = {
            "name": name,
            "gasoline_usd_per_l": round(price, 3),
        }
    if unresolved:
        print(f"warning: no ISO2 mapping for {unresolved} — add to GPP_NAME_ALIASES")

    prices_payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "GlobalPetrolPrices.com (gasoline_prices)",
        "source_url": GPP_URL,
        "currency": "USD",
        "unit": "per_litre",
        "countries": countries,
    }

    geo = filter_geojson(ne)

    PRICES_PATH.write_text(json.dumps(prices_payload, indent=2))
    GEOJSON_PATH.write_text(json.dumps(geo))
    print(f"wrote {PRICES_PATH} ({len(countries)} countries)")
    print(f"wrote {GEOJSON_PATH} ({len(geo['features'])} polygons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
