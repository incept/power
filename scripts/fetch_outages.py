#!/usr/bin/env python3
"""Produce data/outages.json for the US power outage map.

Sources:
  sample (default)  Deterministic, realistic demo snapshot (no network needed).
  url               Fetch a JSON document that already matches the outages
                    schema from --url (e.g. an internal aggregator endpoint).

Schema written to data/outages.json:
  {
    "generated_at": "2026-07-06T17:00:00Z",   # UTC, ISO-8601
    "source": "sample",
    "states": [
      {
        "fips": "48",                # 2-digit state FIPS, keys the map
        "abbr": "TX",
        "name": "Texas",
        "customers_out": 412000,
        "customers_tracked": 14640000
      },
      ...
    ]
  }

Real-data integrations (both map cleanly onto this schema):
  * PowerOutage.us API (paid)  https://poweroutage.us/products — county and
    state rollups of ~3,000 utilities, refreshed every 10 minutes.
  * DOE/ORNL EAGLE-I           https://eagle-i.doe.gov — federal outage
    aggregation; historical snapshots are public.
Point --source url at any endpoint that returns the schema above, or add a
new build_* function here that maps a provider's response into it.
"""

import argparse
import json
import random
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "outages.json"

# (fips, abbr, name, approx population in millions). Electric-customer counts
# are estimated as pop * 0.48 (~163M US customers / ~338M people); a real feed
# replaces these entirely.
STATES = [
    ("01", "AL", "Alabama", 5.16), ("02", "AK", "Alaska", 0.74),
    ("04", "AZ", "Arizona", 7.58), ("05", "AR", "Arkansas", 3.09),
    ("06", "CA", "California", 39.03), ("08", "CO", "Colorado", 5.96),
    ("09", "CT", "Connecticut", 3.63), ("10", "DE", "Delaware", 1.05),
    ("11", "DC", "District of Columbia", 0.68), ("12", "FL", "Florida", 23.00),
    ("13", "GA", "Georgia", 11.13), ("15", "HI", "Hawaii", 1.44),
    ("16", "ID", "Idaho", 2.00), ("17", "IL", "Illinois", 12.55),
    ("18", "IN", "Indiana", 6.90), ("19", "IA", "Iowa", 3.21),
    ("20", "KS", "Kansas", 2.94), ("21", "KY", "Kentucky", 4.56),
    ("22", "LA", "Louisiana", 4.57), ("23", "ME", "Maine", 1.40),
    ("24", "MD", "Maryland", 6.18), ("25", "MA", "Massachusetts", 7.03),
    ("26", "MI", "Michigan", 10.04), ("27", "MN", "Minnesota", 5.77),
    ("28", "MS", "Mississippi", 2.94), ("29", "MO", "Missouri", 6.20),
    ("30", "MT", "Montana", 1.13), ("31", "NE", "Nebraska", 1.99),
    ("32", "NV", "Nevada", 3.22), ("33", "NH", "New Hampshire", 1.40),
    ("34", "NJ", "New Jersey", 9.29), ("35", "NM", "New Mexico", 2.11),
    ("36", "NY", "New York", 19.68), ("37", "NC", "North Carolina", 10.84),
    ("38", "ND", "North Dakota", 0.78), ("39", "OH", "Ohio", 11.79),
    ("40", "OK", "Oklahoma", 4.05), ("41", "OR", "Oregon", 4.24),
    ("42", "PA", "Pennsylvania", 12.97), ("44", "RI", "Rhode Island", 1.10),
    ("45", "SC", "South Carolina", 5.37), ("46", "SD", "South Dakota", 0.92),
    ("47", "TN", "Tennessee", 7.13), ("48", "TX", "Texas", 30.50),
    ("49", "UT", "Utah", 3.42), ("50", "VT", "Vermont", 0.65),
    ("51", "VA", "Virginia", 8.72), ("53", "WA", "Washington", 7.79),
    ("54", "WV", "West Virginia", 1.77), ("55", "WI", "Wisconsin", 5.93),
    ("56", "WY", "Wyoming", 0.58),
]

CUSTOMERS_PER_CAPITA = 0.48

# Demo scenario: a Gulf Coast hurricane remnant plus a Midwest derecho.
# Values are the fraction of tracked customers without power.
SAMPLE_EVENT_RATES = {
    "LA": 0.062, "MS": 0.035, "MO": 0.041, "AR": 0.026, "TX": 0.018,
    "TN": 0.021, "OK": 0.015, "IL": 0.012, "AL": 0.010, "KY": 0.009,
    "IN": 0.006, "GA": 0.004, "FL": 0.003,
}


def build_sample():
    rng = random.Random(20260706)  # deterministic output
    states = []
    for fips, abbr, name, pop_m in STATES:
        tracked = int(pop_m * 1_000_000 * CUSTOMERS_PER_CAPITA)
        base_rate = rng.uniform(0.00002, 0.0008)  # everyday background outages
        rate = SAMPLE_EVENT_RATES.get(abbr, 0) + base_rate
        out = int(tracked * rate)
        if rng.random() < 0.10 and abbr not in SAMPLE_EVENT_RATES:
            out = 0  # a few states report fully clean
        states.append({
            "fips": fips, "abbr": abbr, "name": name,
            "customers_out": out, "customers_tracked": tracked,
        })
    return states


def build_from_url(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        doc = json.load(resp)
    states = doc["states"] if isinstance(doc, dict) else doc
    for s in states:
        for key in ("fips", "name", "customers_out", "customers_tracked"):
            if key not in s:
                raise ValueError(f"feed entry missing '{key}': {s}")
        s["fips"] = str(s["fips"]).zfill(2)
    return states


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=["sample", "url"], default="sample")
    parser.add_argument("--url", help="endpoint returning the outages schema (required with --source url)")
    parser.add_argument("--out", default=str(OUT_PATH), help=f"output path (default {OUT_PATH})")
    args = parser.parse_args()

    if args.source == "url":
        if not args.url:
            parser.error("--source url requires --url")
        states = build_from_url(args.url)
    else:
        states = build_sample()

    doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": args.source if args.source != "url" else args.url,
        "states": sorted(states, key=lambda s: s["fips"]),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1) + "\n")

    total_out = sum(s["customers_out"] for s in states)
    print(f"wrote {out_path} — {len(states)} states, {total_out:,} customers out", file=sys.stderr)


if __name__ == "__main__":
    main()
