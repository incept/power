#!/usr/bin/env python3
"""Produce data/outages.json for the US power outage map.

Sources:
  sample (default)  Deterministic, realistic demo snapshot (no network needed).
  odin              DOE/ORNL Outage Data Initiative Nationwide — free public
                    county-level feed (https://odin.ornl.gov), aggregated here
                    to state level. Covers participating utilities only;
                    states with no reporting utility are omitted and render
                    as "No data" on the map.
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
    ],
    "counties": [                    # optional; drives the hover drill-down
      {
        "fips": "48201",             # 5-digit county FIPS (state prefix = 48)
        "name": "Harris",
        "customers_out": 120000
      },
      ...
    ]
  }

The map reveals a state's counties on hover. Counties carry no reliable
served-customer denominator, so the county layer shows absolute counts only.
A state's per-county figures need not sum to its state total: ODIN incidents
that can't be resolved to a county still count toward the state.

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

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = DATA_DIR / "outages.json"
COUNTY_TOPO_PATH = DATA_DIR / "us-counties-albers-10m.json"

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

# ---- ODIN (DOE/ORNL Outage Data Initiative Nationwide) ----
# ORNL republishes ODIN on an Opendatasoft portal; the exports endpoint
# streams every record without pagination and needs no API key.
ODIN_BASE = "https://ornl.opendatasoft.com"
ODIN_DATASET = "odin-real-time-outages-county"

# The dataset is INCIDENT-level: one record per outage incident, with
# `metersaffected` customers out, a `state`, a `statuskind`, and no
# served-customers denominator. Portals rename columns occasionally, so map
# by candidate lists (matched case-insensitively, in order). If nothing
# matches, the adapter prints the record's actual field names so the right
# candidate can be added here.
ODIN_FIELDS = {
    "fips": ["county_fips", "fips", "fips_code", "fipscode", "geoid",
             "county_fips_code", "cnty_fips"],
    "out": ["metersaffected", "meters_affected", "customers_out",
            "customersout", "cust_out", "customers_affected",
            "customersaffected", "outage_count", "num_out",
            "sum_customers_out", "customersoutnow", "out"],
    "served": ["customers_served", "customersserved", "cust_served",
               "customers_tracked", "total_customers", "customer_count",
               "served"],
    "state": ["state", "state_abbr", "state_code", "st", "state_name"],
    "status": ["statuskind", "status_kind", "status", "outagestatus",
               "incident_status"],
    "incident": ["incident", "incident_id", "incidentid"],
    "utility": ["utility_id", "utilityid", "utility"],
    "location": ["county", "communitydescriptor", "incident_location",
                 "geo_point_2d"],
    # For county allocation only. communitydescriptor holds a FIPS *or* a ZIP
    # depending on location_kind, so it is used solely with the kind guard and
    # a state-prefix cross-check below — never to resolve the state itself.
    "descriptor": ["communitydescriptor", "community_descriptor",
                   "county_fips", "fips", "geoid"],
    "location_kind": ["incident_location_kind", "location_kind",
                      "locationkind"],
    "county_name": ["county", "countyname", "county_name"],
}

# location_kind substrings meaning the descriptor is NOT a county FIPS.
ODIN_NONCOUNTY_KINDS = ("zip", "postal", "point", "lat", "lon", "coord",
                        "address", "street")

# statuskind values marking incidents that are over; anything else (Active,
# Assigned, EnRoute, unknown, ...) counts as an ongoing outage.
ODIN_INACTIVE_MARKERS = ("restor", "clos", "complet", "resolv", "cancel",
                         "inactive", "fals")  # "fals": boolean-style actives

# Demo scenario: a Gulf Coast hurricane remnant plus a Midwest derecho.
# Values are the fraction of tracked customers without power.
SAMPLE_EVENT_RATES = {
    "LA": 0.062, "MS": 0.035, "MO": 0.041, "AR": 0.026, "TX": 0.018,
    "TN": 0.021, "OK": 0.015, "IL": 0.012, "AL": 0.010, "KY": 0.009,
    "IN": 0.006, "GA": 0.004, "FL": 0.003,
}


def build_sample(county_ref=None):
    rng = random.Random(20260706)  # deterministic output
    names, by_state, _ = county_ref or ({}, {}, {})
    states, counties = [], []
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
        # Scatter the state's outage across a handful of its counties so the
        # hover drill-down has something to show. Sums back to the state total.
        state_counties = by_state.get(fips, [])
        if out > 0 and state_counties:
            k = min(len(state_counties), rng.randint(3, 12))
            chosen = rng.sample(state_counties, k)
            weights = [rng.random() for _ in chosen]
            wsum = sum(weights) or 1.0
            allocated = 0
            for i, cf in enumerate(chosen):
                share = out - allocated if i == len(chosen) - 1 \
                    else int(out * weights[i] / wsum)
                allocated += share
                if share > 0:
                    counties.append({"fips": cf, "name": names.get(cf, cf),
                                     "customers_out": share})
    return states, counties


def _pick_field(record_lc, candidates):
    for name in candidates:
        if name in record_lc and record_lc[name] is not None:
            return record_lc[name]
    return None


def _to_int(value):
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _norm_county(name):
    """Normalize a county name for matching (drop the type suffix + punctuation)."""
    s = str(name).lower().strip()
    for suffix in (" county", " parish", " borough", " census area",
                   " municipality", " city and borough", " municipio"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return "".join(ch for ch in s if ch.isalnum())


def load_county_reference(path=COUNTY_TOPO_PATH):
    """Read the vendored county TopoJSON into lookups shared by both sources.

    Returns (names, by_state, by_state_name):
      names        {fips5: display name}
      by_state     {state_fips2: [fips5, ...]}  (map render order)
      by_state_name {(state_fips2, normalized name): fips5}
    """
    topo = json.loads(Path(path).read_text())
    geometries = topo["objects"]["counties"]["geometries"]
    names, by_state, by_state_name = {}, {}, {}
    for g in geometries:
        fips = str(g["id"]).zfill(5)
        name = g.get("properties", {}).get("name", fips)
        names[fips] = name
        by_state.setdefault(fips[:2], []).append(fips)
        by_state_name[(fips[:2], _norm_county(name))] = fips
    return names, by_state, by_state_name


def _resolve_county(rec_lc, state_fips, county_ref):
    """Resolve an incident to a 5-digit county FIPS, or None if not county-coded.

    communitydescriptor may carry a ZIP rather than a FIPS, so it is trusted
    only when location_kind doesn't say otherwise, the value is a real county
    code, and its 2-digit prefix matches the already-resolved state (which
    kills ZIP-as-FIPS collisions). Falls back to a (state, county-name) join.
    """
    names, _, by_state_name = county_ref
    kind = _pick_field(rec_lc, ODIN_FIELDS["location_kind"])
    kind_s = str(kind).lower() if kind is not None else ""
    if not any(k in kind_s for k in ODIN_NONCOUNTY_KINDS):
        desc = _pick_field(rec_lc, ODIN_FIELDS["descriptor"])
        if desc is not None:
            digits = str(desc).split(".")[0].strip().zfill(5)
            if len(digits) == 5 and digits in names and digits[:2] == state_fips:
                return digits
    cname = _pick_field(rec_lc, ODIN_FIELDS["county_name"])
    if cname is not None:
        return by_state_name.get((state_fips, _norm_county(cname)))
    return None


def build_from_odin(base, dataset, county_ref=None):
    url = f"{base.rstrip('/')}/api/explore/v2.1/catalog/datasets/{dataset}/exports/json"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        records = json.load(resp)
    if isinstance(records, dict):  # some portals wrap the array
        records = records.get("results") or records.get("records") or []
    if not records:
        raise RuntimeError(f"ODIN export returned no records ({url})")

    by_fips = {fips: (abbr, name) for fips, abbr, name, _ in STATES}
    by_abbr = {abbr: fips for fips, abbr, _, _ in STATES}
    by_name = {name.lower(): fips for fips, _, name, _ in STATES}
    estimates = {fips: int(pop_m * 1_000_000 * CUSTOMERS_PER_CAPITA)
                 for fips, _, _, pop_m in STATES}

    out_sum = {}
    served_sum = {}
    served_complete = {}
    county_out = {}
    allocated_to_county = 0
    state_only = 0
    skipped = 0
    inactive = 0
    duplicates = 0
    status_counts = {}
    seen_incidents = set()
    for rec in records:
        rec_lc = {k.lower(): v for k, v in rec.items()}

        status = _pick_field(rec_lc, ODIN_FIELDS["status"])
        status_key = str(status).strip() if status is not None else "(none)"
        status_counts[status_key] = status_counts.get(status_key, 0) + 1
        if any(m in status_key.lower() for m in ODIN_INACTIVE_MARKERS):
            inactive += 1
            continue

        # A multi-county incident legitimately appears as one row per county
        # sharing the same incident id, so the dedupe key must include the
        # location — only a re-exported row for the same place is a duplicate.
        incident = _pick_field(rec_lc, ODIN_FIELDS["incident"])
        utility = _pick_field(rec_lc, ODIN_FIELDS["utility"])
        if incident is not None:
            location = _pick_field(rec_lc, ODIN_FIELDS["location"])
            key = (str(utility), str(incident), str(location))
            if key in seen_incidents:
                duplicates += 1
                continue
            seen_incidents.add(key)

        state_fips = None
        county_fips = _pick_field(rec_lc, ODIN_FIELDS["fips"])
        if county_fips is not None:
            digits = str(county_fips).split(".")[0].zfill(5)
            if digits[:2] in by_fips:
                state_fips = digits[:2]
        if state_fips is None:
            state_val = _pick_field(rec_lc, ODIN_FIELDS["state"])
            if state_val is not None:
                s = str(state_val).strip()
                state_fips = (by_abbr.get(s.upper())
                              or by_name.get(s.lower())
                              or (s.zfill(2) if s.zfill(2) in by_fips else None))
        out = _to_int(_pick_field(rec_lc, ODIN_FIELDS["out"]))
        if state_fips is None or out is None:
            skipped += 1
            if skipped == 1:
                print("odin: could not map a record; its fields are: "
                      + ", ".join(sorted(rec.keys()))
                      + " — extend ODIN_FIELDS if these look right",
                      file=sys.stderr)
            continue
        out_sum[state_fips] = out_sum.get(state_fips, 0) + out
        served = _to_int(_pick_field(rec_lc, ODIN_FIELDS["served"]))
        if served is None:
            served_complete[state_fips] = False
        else:
            served_complete.setdefault(state_fips, True)
            served_sum[state_fips] = served_sum.get(state_fips, 0) + served

        county_fips5 = _resolve_county(rec_lc, state_fips, county_ref) \
            if county_ref else None
        if county_fips5:
            county_out[county_fips5] = county_out.get(county_fips5, 0) + out
            allocated_to_county += 1
        else:
            state_only += 1

    print("odin: incident statuses: "
          + ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
          + f" (excluded {inactive} finished, {duplicates} duplicates)",
          file=sys.stderr)
    if duplicates > 0.2 * len(records):
        print("odin: WARNING — dedupe dropped more than 20% of records; the "
              "rows may be distinct outages that share a key. Inspect a few "
              "records before trusting these totals.", file=sys.stderr)
    if not out_sum:
        raise RuntimeError(
            f"odin: no active records could be mapped (of {len(records)}); "
            "see the field-name hint above and extend ODIN_FIELDS")
    if skipped:
        print(f"odin: skipped {skipped} of {len(records)} unmappable records",
              file=sys.stderr)

    if county_ref:
        print(f"odin: {allocated_to_county} incidents mapped to a county, "
              f"{state_only} state-only (no county drill-down for those)",
              file=sys.stderr)

    states = []
    for state_fips, out in sorted(out_sum.items()):
        abbr, name = by_fips[state_fips]
        # Prefer the utilities' own served-customer counts; fall back to the
        # population-based estimate when any county lacked one.
        if served_complete.get(state_fips) and served_sum.get(state_fips, 0) >= out:
            tracked, tracked_estimated = served_sum[state_fips], False
        else:
            tracked, tracked_estimated = max(estimates[state_fips], out), True
        states.append({
            "fips": state_fips, "abbr": abbr, "name": name,
            "customers_out": out, "customers_tracked": tracked,
            "tracked_estimated": tracked_estimated,
        })

    county_names = county_ref[0] if county_ref else {}
    counties = [{"fips": cf, "name": county_names.get(cf, cf),
                 "customers_out": out}
                for cf, out in sorted(county_out.items())]
    return states, counties


def build_from_url(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        doc = json.load(resp)
    states = doc["states"] if isinstance(doc, dict) else doc
    for s in states:
        for key in ("fips", "name", "customers_out", "customers_tracked"):
            if key not in s:
                raise ValueError(f"feed entry missing '{key}': {s}")
        s["fips"] = str(s["fips"]).zfill(2)
    counties = doc.get("counties", []) if isinstance(doc, dict) else []
    for c in counties:
        c["fips"] = str(c["fips"]).zfill(5)
    return states, counties


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=["sample", "odin", "url"], default="sample")
    parser.add_argument("--url", help="endpoint returning the outages schema (required with --source url)")
    parser.add_argument("--odin-base", default=ODIN_BASE,
                        help=f"Opendatasoft portal hosting the ODIN dataset (default {ODIN_BASE})")
    parser.add_argument("--odin-dataset", default=ODIN_DATASET,
                        help=f"ODIN dataset id on the portal (default {ODIN_DATASET})")
    parser.add_argument("--out", default=str(OUT_PATH), help=f"output path (default {OUT_PATH})")
    args = parser.parse_args()

    try:
        county_ref = load_county_reference()
    except (OSError, KeyError, ValueError) as err:
        print(f"note: county geometry unavailable ({err}); "
              "writing state data only, no hover drill-down", file=sys.stderr)
        county_ref = None

    if args.source == "url":
        if not args.url:
            parser.error("--source url requires --url")
        states, counties = build_from_url(args.url)
        source_label = args.url
    elif args.source == "odin":
        states, counties = build_from_odin(args.odin_base, args.odin_dataset,
                                           county_ref)
        source_label = "ODIN (DOE/ORNL), participating utilities only"
    else:
        states, counties = build_sample(county_ref)
        source_label = "sample"

    doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source_label,
        "states": sorted(states, key=lambda s: s["fips"]),
        "counties": sorted(counties, key=lambda c: c["fips"]),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1) + "\n")

    total_out = sum(s["customers_out"] for s in states)
    print(f"wrote {out_path} — {len(states)} states, "
          f"{len(counties)} counties, {total_out:,} customers out",
          file=sys.stderr)


if __name__ == "__main__":
    main()
