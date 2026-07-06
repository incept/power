# US Power Outage Map

An interactive choropleth map of electric power outages across the United
States: customers without power by state, summary stat tiles, a color-by
toggle (absolute count vs. share of tracked customers), hover/keyboard
tooltips, and a sortable table view. Light and dark mode are both supported.

The app is a fully static site — no build step, no runtime dependencies
beyond a vendored copy of [D3](https://d3js.org) and
[topojson-client](https://github.com/topojson/topojson-client).

## Running it

Serve the repository root over HTTP (the app fetches JSON, so `file://`
won't work):

```sh
python3 -m http.server 8000
# then open http://localhost:8000
```

Any static host (GitHub Pages, Netlify, S3, nginx) works the same way.

## Data

The map renders whatever is in `data/outages.json`:

```json
{
  "generated_at": "2026-07-06T17:00:00Z",
  "source": "sample",
  "states": [
    {
      "fips": "48",
      "abbr": "TX",
      "name": "Texas",
      "customers_out": 412000,
      "customers_tracked": 14640000
    }
  ]
}
```

- `fips` — 2-digit state FIPS code; keys the record to the map geometry.
- `customers_out` — customers currently without power.
- `customers_tracked` — customers covered by the reporting utilities, used
  for the percentage view.

The app polls this file every 5 minutes, so updating the file in place is
all a live deployment needs.

### Generating data

`scripts/fetch_outages.py` writes `data/outages.json`:

```sh
# Deterministic demo snapshot (a Gulf Coast + Midwest storm scenario)
python3 scripts/fetch_outages.py

# Pull from any endpoint that already returns the schema above
python3 scripts/fetch_outages.py --source url --url https://example.com/outages.json
```

### Hooking up a real feed

There is no free, official nationwide live outage API, but two established
sources map directly onto this schema:

- **[PowerOutage.us](https://poweroutage.us/products)** (commercial API) —
  aggregates ~3,000 utilities into state and county rollups, refreshed
  about every 10 minutes.
- **[DOE/ORNL EAGLE-I](https://eagle-i.doe.gov)** — the federal outage
  aggregation program; historical snapshots are publicly released.

To integrate one, add a `build_<provider>` function to
`scripts/fetch_outages.py` that maps the provider's response into the
schema, and run it on a schedule (cron, GitHub Actions) that rewrites
`data/outages.json`.

## Repository layout

```
index.html                     app shell
css/styles.css                 design tokens (light/dark) + layout
js/app.js                      map, legend, stats, table, refresh loop
js/vendor/                     vendored d3 + topojson-client
data/us-states-albers-10m.json pre-projected US state geometry (us-atlas)
data/outages.json              the outage snapshot the app renders
scripts/fetch_outages.py       data generator / feed adapter
```
