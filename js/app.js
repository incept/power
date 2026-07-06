/* US Power Outage Map — renders data/outages.json onto a state choropleth
 * with a synchronized stat row and table view. No build step; d3 and
 * topojson-client are vendored in js/vendor/. */
(function () {
  "use strict";

  var DATA_URL = "data/outages.json";
  var TOPO_URL = "data/us-states-albers-10m.json";
  var TOPO_COUNTIES_URL = "data/us-counties-albers-10m.json";
  var REFRESH_MS = 5 * 60 * 1000;

  // County counts are an order of magnitude smaller than state totals, so the
  // drill-down uses its own (absolute) class boundaries. There is no reliable
  // per-county denominator, so counties are always shown as absolute counts.
  var COUNTY_THRESHOLDS = [250, 1000, 5000, 25000];
  var COUNTY_LEGEND = ["0", "< 250", "250 – 1k", "1k – 5k", "5k – 25k", "≥ 25k"];

  // Class boundaries per metric. Zero gets the neutral fill; the five ramp
  // classes use --seq-1 … --seq-5 (dark mode re-anchors them via CSS).
  var METRICS = {
    out: {
      label: "Customers out",
      thresholds: [5000, 25000, 100000, 250000],
      legendLabels: ["0", "< 5k", "5k – 25k", "25k – 100k", "100k – 250k", "≥ 250k"],
      value: function (d) { return d.customers_out; },
      format: function (v) { return d3.format(",")(v); }
    },
    pct: {
      label: "% of customers out",
      thresholds: [0.005, 0.015, 0.03, 0.06],
      legendLabels: ["0", "< 0.5%", "0.5% – 1.5%", "1.5% – 3%", "3% – 6%", "≥ 6%"],
      value: function (d) {
        return d.customers_tracked > 0 ? d.customers_out / d.customers_tracked : 0;
      },
      format: function (v) { return formatPct(v); }
    }
  };

  var state = {
    metric: "out",
    outages: null,          // state fips -> record
    counties: null,         // county fips5 -> record
    generatedAt: null,
    source: null,
    sort: { key: "customers_out", dir: "desc" },
    paths: null,            // d3 selection of state paths
    stateNames: {},         // state fips -> name
    countyByState: null,    // state fips -> [county features]
    countyPath: null,       // shared d3.geoPath
    countyLayer: null,      // <g> the drill-down renders into
    activeState: null       // fips of the state currently exploded, or null
  };

  var fmtCount = d3.format(",");

  function formatPct(v) {
    if (v === 0) return "0%";
    if (v < 0.001) return "< 0.1%";
    return d3.format(".1~%")(v);
  }

  function classFill(value, thresholds) {
    if (value <= 0) return "var(--zero-fill)";
    var i = 0;
    while (i < thresholds.length && value >= thresholds[i]) i++;
    return "var(--seq-" + (i + 1) + ")";
  }

  function fillFor(record, metric) {
    if (!record) return "var(--surface-1)"; // no data: recedes to the card surface
    return classFill(METRICS[metric].value(record), METRICS[metric].thresholds);
  }

  function fillForCounty(record) {
    if (!record) return "var(--surface-1)";
    return classFill(record.customers_out, COUNTY_THRESHOLDS);
  }

  // ---- map ----

  var mapEl = document.getElementById("map");
  var tooltip = document.getElementById("tooltip");
  var card = mapEl.closest(".card");

  function buildMap(topo, countyTopo) {
    var states = topojson.feature(topo, topo.objects.states);
    var path = d3.geoPath(); // geometry is pre-projected (Albers USA)

    var svg = d3.select(mapEl).append("svg")
      .attr("viewBox", "0 0 975 610")
      .attr("role", "img")
      .attr("aria-label", "Choropleth map of the United States shaded by power outages per state. Hover or focus a state to reveal its counties.")
      // Leaving the map entirely closes any open drill-down. (State-to-state
      // and state-to-empty transitions are handled by the layer/enter events.)
      .on("pointerleave", hideCounties);

    states.features.forEach(function (d) { state.stateNames[d.id] = d.properties.name; });

    state.paths = svg.append("g")
      .selectAll("path")
      .data(states.features)
      .join("path")
      .attr("class", "state")
      .attr("d", path)
      .attr("tabindex", 0)
      .on("pointermove", function (event, d) {
        if (state.activeState === d.id) return; // counties own the tooltip now
        d3.select(this).raise(); // hover outline paints above neighbors
        showTooltip(event, d);
      })
      .on("pointerenter", function (event, d) { showCounties(d); })
      .on("pointerleave", hideTooltip)
      .on("focus", function (event, d) {
        d3.select(this).raise();
        showCounties(d);
        showTooltipAtCentroid(this, d);
      })
      .on("blur", hideTooltip);

    // County drill-down layer, always above the states. Empty until a hover.
    if (countyTopo && countyTopo.objects && countyTopo.objects.counties) {
      var counties = topojson.feature(countyTopo, countyTopo.objects.counties).features;
      var byState = {};
      counties.forEach(function (f) {
        var sf = String(f.id).slice(0, 2);
        (byState[sf] || (byState[sf] = [])).push(f);
      });
      state.countyByState = byState;
      state.countyPath = path;
      state.countyLayer = svg.append("g")
        .attr("class", "county-layer")
        .on("pointerleave", hideCounties);
    }
  }

  // ---- county drill-down ----

  function showCounties(stateFeature) {
    if (!state.countyLayer || state.activeState === stateFeature.id) return;
    state.activeState = stateFeature.id;
    var feats = state.countyByState[stateFeature.id] || [];

    // A transparent backing of the whole state keeps the layer hole-free, so
    // the pointer never falls through a county border onto the state beneath
    // (which would bounce the reveal). Its own pointerleave bounds the state.
    var layer = state.countyLayer;
    layer.selectAll("path.county-backing")
      .data([stateFeature], function (d) { return d.id; })
      .join("path")
      .attr("class", "county-backing")
      .attr("d", state.countyPath);

    layer.selectAll("path.county")
      .data(feats, function (f) { return f.id; })
      .join("path")
      .attr("class", "county")
      .attr("d", state.countyPath)
      .style("fill", function (f) { return fillForCounty(county(f.id)); })
      .classed("county--nodata", function (f) { return !county(f.id); })
      .on("pointermove", function (event, f) {
        d3.select(this).raise();
        showCountyTooltip(event, f);
      });

    renderLegend();
  }

  function hideCounties() {
    if (!state.countyLayer || state.activeState === null) return;
    state.activeState = null;
    state.countyLayer.selectAll("path").remove();
    hideTooltip();
    renderLegend();
  }

  function county(fips) {
    return state.counties && state.counties[fips];
  }

  function showCountyTooltip(event, f) {
    var rec = county(f.id);
    tooltip.replaceChildren();
    var title = document.createElement("div");
    title.className = "tooltip-title";
    title.textContent = f.properties.name +
      " · " + (state.stateNames[String(f.id).slice(0, 2)] || "");
    tooltip.appendChild(title);

    var value = document.createElement("div");
    value.className = "tooltip-value";
    value.textContent = rec ? fmtCount(rec.customers_out) + " out" : "No data";
    tooltip.appendChild(value);
    placeTooltip(event.clientX, event.clientY);
  }

  function paintMap() {
    if (!state.paths || !state.outages) return;
    var metric = state.metric;
    state.paths
      .style("fill", function (d) { return fillFor(state.outages[d.id], metric); })
      .classed("state--nodata", function (d) { return !state.outages[d.id]; })
      .attr("aria-label", function (d) {
        var rec = state.outages[d.id];
        if (!rec) return d.properties.name + ": no data";
        return rec.name + ": " + fmtCount(rec.customers_out) +
          " customers without power (" + formatPct(METRICS.pct.value(rec)) + " of tracked)";
      });
  }

  function tooltipContent(d) {
    var rec = state.outages && state.outages[d.id];
    tooltip.replaceChildren();
    var title = document.createElement("div");
    title.className = "tooltip-title";
    title.textContent = rec ? rec.name : d.properties.name;
    tooltip.appendChild(title);

    var value = document.createElement("div");
    value.className = "tooltip-value";
    value.textContent = rec ? fmtCount(rec.customers_out) + " out" : "No data";
    tooltip.appendChild(value);

    if (rec) {
      var sub = document.createElement("div");
      sub.className = "tooltip-sub";
      sub.textContent = formatPct(METRICS.pct.value(rec)) + " of " +
        (rec.tracked_estimated ? "~" : "") +
        fmtCount(rec.customers_tracked) + " tracked customers";
      tooltip.appendChild(sub);
    }
  }

  function placeTooltip(x, y) {
    tooltip.hidden = false;
    var cardRect = card.getBoundingClientRect();
    var tipRect = tooltip.getBoundingClientRect();
    var left = x - cardRect.left + 14;
    var top = y - cardRect.top + 14;
    if (left + tipRect.width > cardRect.width - 8) left = x - cardRect.left - tipRect.width - 14;
    if (top + tipRect.height > cardRect.height - 8) top = y - cardRect.top - tipRect.height - 14;
    tooltip.style.left = Math.max(8, left) + "px";
    tooltip.style.top = Math.max(8, top) + "px";
  }

  function showTooltip(event, d) {
    tooltipContent(d);
    placeTooltip(event.clientX, event.clientY);
  }

  function showTooltipAtCentroid(node, d) {
    tooltipContent(d);
    var box = node.getBoundingClientRect();
    placeTooltip(box.left + box.width / 2, box.top + box.height / 2);
  }

  function hideTooltip() {
    tooltip.hidden = true;
  }

  // ---- legend ----

  function renderLegend() {
    var legend = document.getElementById("legend");
    legend.replaceChildren();
    var countyMode = state.activeState !== null && state.activeState !== undefined;

    if (countyMode) {
      var srec = state.outages && state.outages[state.activeState];
      var note = document.createElement("span");
      note.className = "legend-note";
      note.textContent = (state.stateNames[state.activeState] || "State") +
        " · " + (srec ? fmtCount(srec.customers_out) + " out statewide" : "no state data") +
        " · counties (customers out):";
      legend.appendChild(note);
    }

    var labels = countyMode ? COUNTY_LEGEND : METRICS[state.metric].legendLabels;
    var entries = labels.map(function (label, i) {
      return { label: label, fill: i === 0 ? "var(--zero-fill)" : "var(--seq-" + i + ")" };
    });
    var reported = Object.keys(state.outages || {}).length;
    var partial = state.paths && reported < state.paths.size();
    if (countyMode || partial) {
      entries.unshift({ label: "No data", fill: "var(--surface-1)" });
    }
    entries.forEach(function (entry) {
      var item = document.createElement("span");
      item.className = "legend-item";
      var swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.background = entry.fill;
      var text = document.createElement("span");
      text.textContent = entry.label;
      item.appendChild(swatch);
      item.appendChild(text);
      legend.appendChild(item);
    });
  }

  // ---- stats ----

  function renderStats() {
    var records = Object.values(state.outages);
    var totalOut = d3.sum(records, function (d) { return d.customers_out; });
    var totalTracked = d3.sum(records, function (d) { return d.customers_tracked; });
    var affected = records.filter(function (d) { return d.customers_out > 0; }).length;

    document.getElementById("stat-total").textContent = fmtCount(totalOut);
    document.getElementById("stat-share").textContent =
      totalTracked > 0 ? formatPct(totalOut / totalTracked) : "–";
    document.getElementById("stat-states").textContent =
      affected + " of " + (state.paths ? state.paths.size() : records.length);
    document.getElementById("stat-updated").textContent = state.generatedAt
      ? new Date(state.generatedAt).toLocaleString(undefined,
          { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
      : "–";
    document.getElementById("source-note").textContent =
      state.source ? "Source: " + state.source + "." : "";
  }

  // ---- table ----

  function renderTable() {
    var tbody = document.querySelector("#state-table tbody");
    var records = Object.values(state.outages).map(function (d) {
      return Object.assign({ pct: METRICS.pct.value(d) }, d);
    });
    var key = state.sort.key, dir = state.sort.dir === "asc" ? 1 : -1;
    records.sort(function (a, b) {
      var cmp = key === "name"
        ? d3.ascending(a.name, b.name)
        : d3.ascending(a[key], b[key]);
      return cmp * dir;
    });

    tbody.replaceChildren();
    records.forEach(function (d) {
      var tr = document.createElement("tr");
      [d.name, fmtCount(d.customers_out), formatPct(d.pct),
       (d.tracked_estimated ? "~" : "") + fmtCount(d.customers_tracked)]
        .forEach(function (text, i) {
          var td = document.createElement("td");
          if (i > 0) td.className = "num";
          td.textContent = text;
          tr.appendChild(td);
        });
      tbody.appendChild(tr);
    });

    document.querySelectorAll("#state-table th button").forEach(function (btn) {
      if (btn.dataset.sort === state.sort.key) btn.dataset.dir = state.sort.dir;
      else delete btn.dataset.dir;
    });
  }

  document.querySelectorAll("#state-table th button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort = { key: key, dir: key === "name" ? "asc" : "desc" };
      }
      renderTable();
    });
  });

  // ---- metric toggle ----

  document.querySelectorAll("#metric-toggle button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (btn.dataset.metric === state.metric) return;
      state.metric = btn.dataset.metric;
      document.querySelectorAll("#metric-toggle button").forEach(function (b) {
        b.setAttribute("aria-checked", String(b === btn));
      });
      paintMap();
      renderLegend();
    });
  });

  // ---- data loading ----

  function applyData(doc) {
    hideCounties(); // reset any open drill-down before data swaps under it
    var byFips = {};
    doc.states.forEach(function (s) { byFips[s.fips] = s; });
    state.outages = byFips;

    var byCounty = {};
    (doc.counties || []).forEach(function (c) { byCounty[c.fips] = c; });
    state.counties = byCounty;

    state.generatedAt = doc.generated_at;
    state.source = doc.source;
    paintMap();
    renderLegend();
    renderStats();
    renderTable();
  }

  function showError(message) {
    var existing = document.querySelector(".error-banner");
    if (existing) existing.remove();
    var banner = document.createElement("div");
    banner.className = "error-banner";
    banner.textContent = message;
    document.querySelector(".stat-row").before(banner);
  }

  function refresh() {
    mapEl.classList.add("refreshing"); // hold previous render, dimmed
    return fetch(DATA_URL + "?t=" + Date.now())
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (doc) {
        var stale = document.querySelector(".error-banner");
        if (stale) stale.remove();
        applyData(doc);
      })
      .catch(function (err) {
        showError("Could not refresh outage data (" + err.message +
          "). Showing the last successful load.");
      })
      .finally(function () {
        mapEl.classList.remove("refreshing");
      });
  }

  function fetchJson(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  fetchJson(TOPO_URL)
    .then(function (topo) {
      // County geometry is optional — without it the map still works, just
      // with no hover drill-down.
      return fetchJson(TOPO_COUNTIES_URL)
        .catch(function () { return null; })
        .then(function (countyTopo) {
          buildMap(topo, countyTopo);
          return refresh();
        });
    })
    .then(function () {
      setInterval(refresh, REFRESH_MS);
    })
    .catch(function (err) {
      showError("Failed to load map geometry (" + err.message + ").");
    });
})();
