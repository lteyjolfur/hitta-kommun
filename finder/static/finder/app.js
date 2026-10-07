"use strict";

// Sequential blue ramp, light -> dark = weaker -> stronger match (5 quantile bins).
const BINS = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"];
const NO_DATA = "#d9d8d4";
const TOP_N = 15;

const dimensions = JSON.parse(document.getElementById("dimensions-data").textContent);
const form = document.getElementById("weights");
const rankingEl = document.getElementById("ranking");
const statusEl = document.getElementById("status");

// No background tiles: the kommun shapes cover all of Sweden, and the län
// outlines drawn on top give the map its structure and coastline.
const map = L.map("map", { zoomSnap: 0.25, maxZoom: 10, attributionControl: false }).setView([62.5, 16.5], 4.75);
const css = getComputedStyle(document.documentElement);
const KOMMUN_LINE = css.getPropertyValue("--map-kommun-line").trim();
const LAN_LINE = css.getPropertyValue("--map-lan-line").trim();
const HOVER_LINE = css.getPropertyValue("--ink").trim();

let layer = null;
let byCode = new Map(); // code -> result from /api/rank
let thresholds = [];

function fmt(value, digits = 1) {
  return value == null ? "–" : value.toLocaleString("sv-SE", { maximumFractionDigits: digits });
}

function binFor(score) {
  if (score == null) return -1;
  let i = 0;
  while (i < thresholds.length && score > thresholds[i]) i++;
  return i;
}

function computeThresholds(scores) {
  const sorted = scores.filter((s) => s != null).sort((a, b) => a - b);
  if (!sorted.length) return [];
  return [0.2, 0.4, 0.6, 0.8].map((q) => sorted[Math.floor(q * (sorted.length - 1))]);
}

function style(feature) {
  const r = byCode.get(feature.properties.code);
  const bin = binFor(r ? r.score : null);
  return {
    fillColor: bin < 0 ? NO_DATA : BINS[bin],
    fillOpacity: 1,
    color: KOMMUN_LINE,
    weight: 0.6,
  };
}

function tooltipHtml(code, name) {
  const r = byCode.get(code);
  if (!r || r.score == null) return `<strong>${name}</strong><br>Ingen data för valda kriterier`;
  const sections = dimensions
    .filter((dim) => dim.has_data)
    .map((dim) => {
      const part = r.parts[dim.slug];
      const head = `<span class="tt-dim">${dim.name}${part == null ? "" : ` · ${fmt(part * 100, 0)}/100`}</span>`;
      const rows = dim.indicators
        .filter((ind) => ind.has_data)
        .map((ind) => `${ind.name}: ${fmt(r.values[ind.slug])}`);
      return [head, ...rows].join("<br>");
    });
  return `<strong>${r.rank}. ${name}</strong> · matchning ${fmt(r.score * 100, 0)}/100<br>${sections.join("<br>")}`;
}

function renderLegend() {
  const legend = document.getElementById("legend");
  legend.innerHTML =
    '<span class="legend__label">Sämre</span>' +
    BINS.map((c) => `<span class="legend__swatch" style="background:${c}"></span>`).join("") +
    '<span class="legend__label">Bättre</span>' +
    `<span class="legend__swatch legend__swatch--nodata" style="background:${NO_DATA}"></span>` +
    '<span class="legend__label">Ingen data</span>';
}

function renderRanking(results) {
  rankingEl.innerHTML = "";
  results
    .filter((r) => r.score != null)
    .slice(0, TOP_N)
    .forEach((r) => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      const name = document.createElement("span");
      name.textContent = r.name;
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = fmt(r.score * 100, 0);
      button.append(name, score);
      button.addEventListener("click", () => focusKommun(r.code));
      li.appendChild(button);
      rankingEl.appendChild(li);
    });
}

function focusKommun(code) {
  if (!layer) return;
  layer.eachLayer((l) => {
    if (l.feature.properties.code === code) {
      map.fitBounds(l.getBounds(), { maxZoom: 8 });
      l.openTooltip();
    }
  });
}

function updateOutputs() {
  dimensions.forEach((dim) => {
    const input = document.getElementById(`w_${dim.slug}`);
    const out = document.getElementById(`o_${dim.slug}`);
    if (input && out) out.textContent = dim.has_data ? input.value : "";
  });
}

let pending = null;
async function refresh() {
  updateOutputs();
  const params = new URLSearchParams();
  dimensions
    .filter((dim) => dim.has_data)
    .forEach((dim) => params.set(`w_${dim.slug}`, document.getElementById(`w_${dim.slug}`).value));

  if (pending) pending.abort();
  pending = new AbortController();
  let data;
  try {
    const res = await fetch(`${window.RANK_URL}?${params}`, { signal: pending.signal });
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    data = await res.json();
  } catch (err) {
    if (err.name !== "AbortError") statusEl.textContent = `Kunde inte hämta rangordningen: ${err.message}`;
    return;
  }

  byCode = new Map();
  data.results.forEach((r, i) => byCode.set(r.code, { ...r, rank: i + 1 }));
  thresholds = computeThresholds(data.results.map((r) => r.score));
  const scored = data.results.filter((r) => r.score != null).length;
  statusEl.textContent = scored ? "" : "Dra i minst ett reglage för att rangordna kommunerna.";

  renderRanking(data.results);
  if (layer) {
    layer.setStyle(style);
    layer.eachLayer((l) => l.setTooltipContent(tooltipHtml(l.feature.properties.code, l.feature.properties.name)));
  }
}

async function init() {
  renderLegend();
  const [geojson, lanGeojson] = await Promise.all(
    [window.KOMMUN_GEOJSON_URL, window.LAN_GEOJSON_URL].map(async (url) => (await fetch(url)).json()),
  );
  layer = L.geoJSON(geojson, {
    style,
    onEachFeature: (feature, l) => {
      l.bindTooltip(tooltipHtml(feature.properties.code, feature.properties.name), { sticky: true });
      l.on("mouseover", () => l.setStyle({ weight: 2, color: HOVER_LINE }));
      l.on("mouseout", () => layer.resetStyle(l));
    },
  }).addTo(map);
  // Län borders on top; non-interactive so hover still reaches the kommuner.
  L.geoJSON(lanGeojson, {
    interactive: false,
    style: { fill: false, color: LAN_LINE, weight: 1.4, lineJoin: "round" },
  }).addTo(map);
  map.fitBounds(layer.getBounds(), { padding: [8, 8] });
  await refresh();
}

let debounce = null;
form.addEventListener("input", () => {
  updateOutputs();
  clearTimeout(debounce);
  debounce = setTimeout(refresh, 150);
});

init();
