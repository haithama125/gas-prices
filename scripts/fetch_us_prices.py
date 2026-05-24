"""
fetch_us_prices.py
==================

Pulls the latest weekly retail gasoline price for every US state + DC from
EIA and writes data/us-prices.json for the frontend to read on page load.

Why this exists: the map's per-state click handler already lazy-fetches one
price per click, which works fine for "click to learn". The heatmap toggle
needs all 51 prices on screen at once, and firing 51 EIA requests from
every visitor's browser is wasteful — better to pre-bake here once a week.

Run from the project root:

    python3 scripts/fetch_us_prices.py

No dependencies (stdlib only). Reads the EIA API key from the EIA_API_KEY
env var, falling back to the same low-stakes key shipped in index.html so
the script works zero-config locally.

The state→series and state→PADD mappings below mirror the ones in
index.html. If you add a new state-level EIA series there, mirror it here.
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

# Same key that ships in index.html — free, rate-limited, and already
# public in the repo, so no point pretending it's a secret.
DEFAULT_EIA_KEY = "xcUs1Wmv2tgVjJBIRvMJYd6NCYvo5JTdVkJPHSjE"
EIA_API_KEY = os.environ.get("EIA_API_KEY", DEFAULT_EIA_KEY)

# State name -> 2-letter postal code. The frontend's GeoJSON labels each
# state by its full name, so we publish the full name too.
STATE_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# States with their own EIA weekly retail series.
STATE_EIA_CODES = {
    "CA": "SCA", "CO": "SCO", "FL": "SFL", "MA": "SMA", "MN": "SMN",
    "NY": "SNY", "OH": "SOH", "TX": "STX", "WA": "SWA",
}

# Everyone else falls back to their PADD regional average.
STATE_TO_PADD = {
    "CT": "R10", "DE": "R10", "DC": "R10", "FL": "R10", "GA": "R10", "ME": "R10",
    "MD": "R10", "MA": "R10", "NH": "R10", "NJ": "R10", "NY": "R10", "NC": "R10",
    "PA": "R10", "RI": "R10", "SC": "R10", "VT": "R10", "VA": "R10", "WV": "R10",
    "IL": "R20", "IN": "R20", "IA": "R20", "KS": "R20", "KY": "R20", "MI": "R20",
    "MN": "R20", "MO": "R20", "NE": "R20", "ND": "R20", "OH": "R20", "OK": "R20",
    "SD": "R20", "TN": "R20", "WI": "R20",
    "AL": "R30", "AR": "R30", "LA": "R30", "MS": "R30", "NM": "R30", "TX": "R30",
    "CO": "R40", "ID": "R40", "MT": "R40", "UT": "R40", "WY": "R40",
    "AK": "R50", "AZ": "R50", "CA": "R50", "HI": "R50", "NV": "R50", "OR": "R50", "WA": "R50",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "us-prices.json"


def fetch_latest(duoarea: str) -> dict | None:
    """Fetch the most recent weekly retail regular gasoline price for one
    EIA region code. Returns {value, period} (USD/gallon, ISO date) or None.
    """
    params = {
        "frequency": "weekly",
        "data[0]": "value",
        "facets[duoarea][]": duoarea,
        "facets[product][]": "EPMR",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": "0",
        "length": "1",
        "api_key": EIA_API_KEY,
    }
    url = "https://api.eia.gov/v2/petroleum/pri/gnd/data/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "gas-prices/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"  fetch failed for {duoarea}: {e}", file=sys.stderr)
        return None
    rows = payload.get("response", {}).get("data", [])
    if not rows:
        return None
    row = rows[0]
    return {"value": float(row["value"]), "period": row["period"]}


def main() -> int:
    # All distinct EIA region codes we need to hit (9 state series + 5 PADDs).
    region_codes = sorted(set(STATE_EIA_CODES.values()) | set(STATE_TO_PADD.values()))
    print(f"fetching {len(region_codes)} EIA series")

    region_prices: dict[str, dict] = {}
    for code in region_codes:
        result = fetch_latest(code)
        if result is None:
            print(f"  {code}: no data")
            continue
        region_prices[code] = result
        print(f"  {code}: ${result['value']:.3f}/gal (week of {result['period']})")

    # Resolve every state to its best-available price. State-level series
    # wins; fall back to PADD. We publish a `source` field so the frontend
    # can show "State average" vs "PADD 3 regional average" without having
    # to know about the mapping.
    states: dict[str, dict] = {}
    latest_period: str | None = None
    for code, name in STATE_NAME.items():
        series = STATE_EIA_CODES.get(code)
        padd = STATE_TO_PADD.get(code)
        price = region_prices.get(series) if series else None
        source_kind = "state"
        if price is None and padd:
            price = region_prices.get(padd)
            source_kind = "padd"
        if price is None:
            print(f"  warning: no price resolved for {code}")
            continue
        states[code] = {
            "name": name,
            "gasoline_usd_per_gallon": round(price["value"], 3),
            "period": price["period"],
            "source": source_kind,
            "region": series if source_kind == "state" else padd,
        }
        if latest_period is None or price["period"] > latest_period:
            latest_period = price["period"]

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "week_of": latest_period,
        "source": "EIA Weekly Retail Gasoline Prices (regular grade)",
        "source_url": "https://www.eia.gov/petroleum/gasdiesel/",
        "currency": "USD",
        "unit": "per_gallon",
        "states": states,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUTPUT_PATH} ({len(states)} states, week of {payload['week_of']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
