# US Power Outage Map

An interactive choropleth map of electric power outages across the United
States: customers without power by state, summary stat tiles, a color-by
toggle (absolute count vs. share of tracked customers), hover/keyboard
tooltips, and a sortable table view. **Hover (or keyboard-focus) a state to
reveal its counties**, shaded by their own outage counts. Light and dark
mode are both supported.

## County drill-down

The base map is state-level. When you hover or focus a state it "explodes"
into its counties, each colored by its own `customers_out` (an absolute
scale — ODIN reports no per-county denominator, so there is no county
percentage view), with a per-county tooltip and a legend that swaps to the
county scale while showing the statewide total. Moving off the state
collapses it back. Counties with no reported outage show as unfilled
outlines, same as states in the base view.

County figures come from the `counties` array in `data/outages.json`; if
that array is absent or the county geometry fails to load, the map still
works — it just won't drill down. A state's per-county numbers need not sum
to its state total: ODIN incidents that can't be resolved to a county still
count toward the state (the legend note always shows the statewide total).

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

## Hosting & embedding

The site deploys itself to GitHub Pages via
`.github/workflows/deploy.yml`: every push to `main` redeploys, and a
20-minute schedule refreshes `data/outages.json` from ODIN and redeploys.
One-time setup: in the repo's **Settings → Pages**, set **Source: GitHub
Actions**. The site then lives at:

```
https://<owner>.github.io/power/
```

(Note this is the `github.io` Pages domain — `github.com/<owner>/power`
is the code repository and only shows source files.)

To embed in WordPress (or any CMS), add a Custom HTML block:

```html
<iframe
  src="https://<owner>.github.io/power/"
  title="US Power Outage Map"
  loading="lazy"
  style="width:100%; height:1500px; border:0; overflow:hidden;">
</iframe>
```

The scheduled refresh only runs from the default branch, so it starts
once the workflow file lands on `main`.

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

# Live data from ODIN (DOE/ORNL) — free, no API key
python3 scripts/fetch_outages.py --source odin

# Pull from any endpoint that already returns the schema above
python3 scripts/fetch_outages.py --source url --url https://example.com/outages.json
```

### ODIN (the free live source)

The [Outage Data Initiative Nationwide](https://odin.ornl.gov) is a
DOE/ORNL program in which utilities report standardized outage data in
near-real time. ORNL republishes it as a public dataset on their
[OpenEnergyHub portal](https://openenergyhub.ornl.gov/explore/dataset/odin-real-time-outages-county/),
which the `odin` source reads via the portal's Opendatasoft exports API
(no key required).

The dataset is **incident-level** — one record per outage incident with a
`metersaffected` count, a `state`, and a `statuskind`. The adapter drops
incidents whose status marks them finished (restored / closed / resolved
/ canceled), de-duplicates repeated incident ids, sums the rest by state,
and prints the status distribution it saw so you can sanity-check a run.

Two caveats, both visible in the UI:

- **Coverage is participating utilities only.** States with no reporting
  utility are omitted from the output and render as **"No data"** (an
  unfilled outline) rather than zero.
- ODIN reports no served-customer denominators, so the percentage view
  divides by a population-based estimate, flagged as
  `"tracked_estimated": true` and shown with a `~` prefix in the app.

Portals occasionally rename columns; if the adapter can't map a record it
prints the actual field names so you can extend `ODIN_FIELDS` in
`scripts/fetch_outages.py`. Use `--odin-base` / `--odin-dataset` if the
dataset moves.

### Other real feeds

- **[PowerOutage.us](https://poweroutage.us/products)** (commercial API) —
  aggregates ~3,000 utilities into state and county rollups, refreshed
  about every 10 minutes; the most complete coverage available.
- **State feeds** — e.g. [Cal OES county outages](https://gis.data.ca.gov/datasets/439afad071eb4754903906aff1946719_2/api)
  (ArcGIS, 15-minute refresh) and [MEMA's Massachusetts town-level map](https://www.mass.gov/info-details/power-outages).
- **Per-utility endpoints** — most large utilities' outage maps are backed
  by vendor JSON endpoints (e.g. Kubra StormCenter, scrapeable via the
  [`kubra`](https://pypi.org/project/kubra/) package). Undocumented;
  check terms of service.

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
