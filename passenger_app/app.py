"""
Suly Transit – Passenger App  (fullscreen edition)
• Map fills 100 % of the viewport — zero Streamlit chrome
• All UI floats over the map inside the Leaflet iframe
• Origin / destination: click on map  OR  type lat,lon manually
• Route result card slides up from the bottom
• Bus legend collapsible panel top-right
• Live buses via Supabase Realtime
"""

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ── allow importing shared/ whether running as passenger_app/app.py or directly
sys.path.append(str(Path(__file__).resolve().parents[1] / "shared"))
try:
    from supabase_client import get_supabase
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False

st.set_page_config(
    page_title="Suly Transit",
    layout="wide",
    initial_sidebar_state="collapsed",   # hide sidebar completely
)

# ── Kill ALL Streamlit chrome — simple reliable fullscreen ───────────────────
st.markdown("""
<style>
  header[data-testid="stHeader"]   { display: none !important; }
  section[data-testid="stSidebar"] { display: none !important; }
  footer                           { display: none !important; }
  .stDeployButton                  { display: none !important; }
  div[data-testid="stTextInput"]   { display: none !important; }
  .block-container {
    padding: 0 !important;
    margin: 0 !important;
    max-width: 100% !important;
  }
  /* Remove all spacing around the iframe */
  div[data-testid="stCustomComponentV1"] {
    margin: 0 !important;
    padding: 0 !important;
    line-height: 0 !important;
  }
</style>
""", unsafe_allow_html=True)

BASE_DIR     = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ASSETS_DIR   = PROJECT_ROOT / "assets"
ROUTES_FILE  = ASSETS_DIR / "bus_lines.geojson"

DEFAULT_CENTER = [35.56, 45.43]
DEFAULT_ZOOM   = 13
MAX_WALK_KM    = 0.70

ROUTE_COLORS: Dict[str, str] = {
    "Bakrajo_Bazar":      "#e41a1c",
    "Chwarchra_Bazar":    "#377eb8",
    "FarmanBaran_Bazar":  "#4daf4a",
    "HawaryShar_Bazar":   "#984ea3",
    "Kazywa_Bazar":       "#ff7f00",
    "Kshtukal_Bazar":     "#a65628",
    "Qrgra_Bazar":        "#f781bf",
    "Raparin_Bazar":      "#999999",
    "Rzgary Bazar":       "#66c2a5",
    "Shakraka_Bazar":     "#fc8d62",
    "TwiMalik_Bazar":     "#8da0cb",
    "Xabat_Bazar":        "#ffd92f",
    "ZargatayTaza_Bazar": "#1b9e77",
}


# ── Data ──────────────────────────────────────────────────────────────────────

@st.cache_data(hash_funcs={Path: lambda p: p.stat().st_mtime if p.exists() else 0})
def load_routes(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing route file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def extract_route_points(routes_geojson: dict) -> pd.DataFrame:
    rows: List[dict] = []
    for feature in routes_geojson.get("features", []):
        route_name = feature.get("properties", {}).get("layer", "Unknown Route")
        geometry   = feature.get("geometry", {})
        geom_type  = geometry.get("type")
        coords     = geometry.get("coordinates", [])
        line_sets  = [coords] if geom_type == "LineString" else (
            coords if geom_type == "MultiLineString" else []
        )
        for line in line_sets:
            for idx, coord in enumerate(line):
                if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                    rows.append({"route_name": route_name, "point_order": idx,
                                 "lat": coord[1], "lon": coord[0]})
    return pd.DataFrame(rows, columns=["route_name", "point_order", "lat", "lon"])


# ── Routing ───────────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lats2, lons2):
    r = 6371.0
    rl1 = math.radians(lat1)
    rl2, rn2 = np.radians(lats2), np.radians(lons2)
    dl = rl2 - rl1
    dn = rn2 - math.radians(lon1)
    a  = np.sin(dl/2)**2 + np.cos(rl1) * np.cos(rl2) * np.sin(dn/2)**2
    return r * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def nearest_route(lat, lon, df) -> Optional[dict]:
    clean = df.dropna(subset=["lat", "lon"])
    if clean.empty:
        return None
    dists = haversine_km(lat, lon, clean["lat"].to_numpy(), clean["lon"].to_numpy())
    if dists.size == 0 or np.isnan(dists).all():
        return None
    idx = int(np.nanargmin(dists))
    row = clean.iloc[idx].to_dict()
    row["distance_km"] = float(dists[idx])
    return row


def compute_trip(df) -> Tuple[Optional[dict], List[str]]:
    o = st.session_state.get("origin")
    d = st.session_state.get("destination")
    if not o or not d:
        return None, []
    or_ = nearest_route(o["lat"], o["lon"], df)
    dr_ = nearest_route(d["lat"], d["lon"], df)
    if not or_ or not dr_:
        return {"error": "Could not find nearby routes."}, []
    if or_["distance_km"] > MAX_WALK_KM:
        return {"error": f"Origin is too far from any bus route ({or_['distance_km']:.2f} km away)."}, []
    if dr_["distance_km"] > MAX_WALK_KM:
        return {"error": f"Destination is too far from any bus route ({dr_['distance_km']:.2f} km away)."}, []
    result = {"origin_route": or_, "destination_route": dr_}
    if or_["route_name"] == dr_["route_name"]:
        return result, [or_["route_name"]]
    return result, [or_["route_name"], dr_["route_name"]]


def fetch_live_buses() -> list:
    if not _SUPABASE_AVAILABLE:
        return []
    try:
        sb  = get_supabase()
        res = sb.table("active_locations") \
                .select("bus_line,bus_number,lat,lon,speed_kmh,updated_at") \
                .eq("is_active", True).execute()
        return res.data or []
    except Exception:
        return []


# ── Result JSON for the in-map result card ────────────────────────────────────

def trip_result_json(trip_result) -> str:
    if trip_result is None:
        return "null"
    if "error" in trip_result:
        return json.dumps({"error": trip_result["error"]})
    o = trip_result["origin_route"]
    d = trip_result["destination_route"]
    same = o["route_name"] == d["route_name"]
    o_color = ROUTE_COLORS.get(o["route_name"], "#888")
    d_color = ROUTE_COLORS.get(d["route_name"], "#888")
    return json.dumps({
        "origin_route":   o["route_name"],
        "origin_label":   o["route_name"].replace("_", " "),
        "origin_color":   o_color,
        "origin_walk_m":  round(o["distance_km"] * 1000),
        "dest_route":     d["route_name"],
        "dest_label":     d["route_name"].replace("_", " "),
        "dest_color":     d_color,
        "dest_walk_m":    round(d["distance_km"] * 1000),
        "same_route":     same,
    })


# ── Fullscreen Leaflet HTML ───────────────────────────────────────────────────

def build_map_html(routes_geojson: dict, highlight: List[str],
                   origin, destination,
                   trip_result,
                   live_buses: list,
                   supabase_url: str, supabase_key: str) -> str:

    geojson_str   = json.dumps(routes_geojson)
    colors_str    = json.dumps(ROUTE_COLORS)
    highlight_str = json.dumps(highlight)
    origin_str    = json.dumps(origin)
    dest_str      = json.dumps(destination)
    buses_str     = json.dumps(live_buses)
    result_str    = trip_result_json(trip_result)
    legend_items  = json.dumps([
        {"name": k.replace("_", " "), "color": v}
        for k, v in ROUTE_COLORS.items()
    ])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
:root{{
  --glass: rgba(8,13,22,0.82);
  --glass-border: rgba(255,255,255,0.10);
  --accent: #00d4ff;
  --green: #22c55e;
  --red: #ef4444;
  --text: #e2eaf4;
  --muted: #64748b;
  --font: 'Inter', system-ui, sans-serif;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:100%; height:100%; font-family: var(--font); overflow:hidden; }}
#map {{ width:100%; height:100vh; }}

/* ── glass card mixin ── */
.card {{
  background: var(--glass);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.45);
  color: var(--text);
}}

/* ═══════════════════════════════════════════
   TOP CENTRE — origin / destination inputs
═══════════════════════════════════════════ */
#top-panel {{
  position: absolute;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  width: min(520px, 94vw);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}}

.point-row {{
  display: flex;
  align-items: center;
  gap: 8px;
}}

.point-dot {{
  width: 12px; height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 2px solid rgba(255,255,255,0.6);
}}

.point-btn {{
  flex-shrink: 0;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1.5px solid;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s;
  background: transparent;
  white-space: nowrap;
}}
.point-btn:hover {{ filter: brightness(1.2); transform: translateY(-1px); }}
.point-btn.origin  {{ border-color: var(--green); color: #4ade80; }}
.point-btn.origin.active  {{ background: var(--green); color:#000; box-shadow: 0 0 12px rgba(34,197,94,.5); }}
.point-btn.dest    {{ border-color: var(--red);   color: #f87171; }}
.point-btn.dest.active    {{ background: var(--red);   color:#fff; box-shadow: 0 0 12px rgba(239,68,68,.5); }}

.coord-input {{
  flex: 1;
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.13);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text);
  outline: none;
  transition: border-color .15s;
  min-width: 0;
}}
.coord-input::placeholder {{ color: var(--muted); }}
.coord-input:focus {{ border-color: var(--accent); }}
.coord-input.has-val {{ border-color: rgba(255,255,255,0.25); }}

.clear-btn {{
  flex-shrink: 0;
  width: 24px; height: 24px;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.15);
  background: rgba(255,255,255,0.06);
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all .15s;
}}
.clear-btn:hover {{ background: rgba(255,255,255,0.15); color: var(--text); }}

.divider {{ height: 1px; background: var(--glass-border); margin: 2px 0; }}

.reset-row {{
  display: flex;
  justify-content: flex-end;
}}
.reset-btn {{
  background: transparent;
  border: 1px solid rgba(148,163,184,.35);
  border-radius: 7px;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 12px;
  cursor: pointer;
  transition: all .15s;
  letter-spacing: .03em;
}}
.reset-btn:hover {{ background: rgba(148,163,184,.15); color: var(--text); }}

/* crosshair when picking */
.leaflet-container.picking {{ cursor: crosshair !important; }}

/* ═══════════════════════════════════════════
   BOTTOM CENTRE — result card  (slides up)
═══════════════════════════════════════════ */
#result-card {{
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%) translateY(300px);
  z-index: 1000;
  width: min(480px, 92vw);
  padding: 14px 16px;
  transition: transform .4s cubic-bezier(.34,1.56,.64,1);
  pointer-events: none;
}}
#result-card.visible {{
  transform: translateX(-50%) translateY(0);
  pointer-events: all;
}}

.result-summary {{
  font-size: 13px;
  font-weight: 700;
  padding: 7px 12px;
  border-radius: 8px;
  margin-bottom: 10px;
  text-align: center;
  letter-spacing: .02em;
}}
.result-summary.success {{
  background: rgba(34,197,94,.15);
  border: 1px solid rgba(34,197,94,.3);
  color: #4ade80;
}}
.result-summary.transfer {{
  background: rgba(251,191,36,.12);
  border: 1px solid rgba(251,191,36,.3);
  color: #fbbf24;
}}
.result-summary.error {{
  background: rgba(239,68,68,.13);
  border: 1px solid rgba(239,68,68,.3);
  color: #f87171;
}}

.steps {{ display: flex; flex-direction: column; gap: 6px; }}
.step {{
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  background: rgba(255,255,255,0.05);
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.07);
}}
.step-icon {{ font-size: 16px; flex-shrink: 0; line-height: 1.4; }}
.step-body {{ display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
.step-main {{ font-size: 13px; color: var(--text); font-weight: 500; }}
.step-sub  {{ font-size: 11px; color: var(--muted); }}
.line-pill {{
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 12px;
  white-space: nowrap;
}}

/* ═══════════════════════════════════════════
   TOP RIGHT — legend toggle + panel
═══════════════════════════════════════════ */
#legend-btn {{
  position: absolute;
  top: 14px;
  right: 14px;
  z-index: 1001;
  width: 38px; height: 38px;
  border-radius: 10px;
  border: 1px solid var(--glass-border);
  background: var(--glass);
  backdrop-filter: blur(14px);
  color: var(--text);
  font-size: 18px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 16px rgba(0,0,0,.35);
  transition: background .15s;
}}
#legend-btn:hover {{ background: rgba(8,13,22,0.95); }}

#legend-panel {{
  position: absolute;
  top: 60px;
  right: 14px;
  z-index: 1000;
  width: 200px;
  max-height: 60vh;
  overflow-y: auto;
  padding: 12px 14px;
  display: none;
  flex-direction: column;
  gap: 6px;
}}
#legend-panel.open {{ display: flex; }}
.legend-item {{
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text);
}}
.legend-dot {{
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}}
#legend-panel::-webkit-scrollbar {{ width: 3px; }}
#legend-panel::-webkit-scrollbar-thumb {{ background: var(--glass-border); border-radius:2px; }}

/* ═══════════════════════════════════════════
   BOTTOM RIGHT — live bus badge
═══════════════════════════════════════════ */
#live-badge {{
  position: absolute;
  bottom: 24px;
  right: 14px;
  z-index: 1000;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  color: #4ade80;
  border: 1px solid rgba(34,197,94,.3);
  display: flex; align-items: center; gap: 6px;
  letter-spacing: .03em;
}}
.live-dot {{
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #22c55e;
  animation: blink 1.4s infinite;
}}
@keyframes blink {{ 0%,100%{{opacity:1;}} 50%{{opacity:.2;}} }}

/* Leaflet zoom control */
.leaflet-control-zoom {{ border: none !important; }}
.leaflet-control-zoom a {{
  background: var(--glass) !important;
  backdrop-filter: blur(14px) !important;
  color: var(--text) !important;
  border: 1px solid var(--glass-border) !important;
  box-shadow: none !important;
}}
.leaflet-control-zoom a:hover {{ background: rgba(8,13,22,.95) !important; }}
</style>
</head>
<body>
<div id="map"></div>

<!-- ═══ TOP PANEL ═══ -->
<div id="top-panel" class="card">
  <!-- Origin row -->
  <div class="point-row">
    <span class="point-dot" style="background:#22c55e"></span>
    <button class="point-btn origin" id="btn-origin" onclick="toggleMode('set_origin')">
      📍 Pick
    </button>
    <input class="coord-input" id="input-origin"
           placeholder="Origin  lat, lon  e.g. 35.5612, 45.4320"
           onchange="applyManual('origin', this.value)"
           oninput="this.classList.toggle('has-val', this.value.length>0)"/>
    <button class="clear-btn" onclick="clearPoint('origin')" title="Clear">✕</button>
  </div>

  <div class="divider"></div>

  <!-- Destination row -->
  <div class="point-row">
    <span class="point-dot" style="background:#ef4444"></span>
    <button class="point-btn dest" id="btn-dest" onclick="toggleMode('set_destination')">
      🏁 Pick
    </button>
    <input class="coord-input" id="input-dest"
           placeholder="Destination  lat, lon  e.g. 35.5480, 45.4150"
           onchange="applyManual('destination', this.value)"
           oninput="this.classList.toggle('has-val', this.value.length>0)"/>
    <button class="clear-btn" onclick="clearPoint('destination')" title="Clear">✕</button>
  </div>

  <div class="divider"></div>
  <div class="reset-row">
    <button class="reset-btn" onclick="resetAll()">↺ Reset</button>
  </div>
</div>

<!-- ═══ LEGEND ═══ -->
<button id="legend-btn" onclick="toggleLegend()" title="Bus lines">🗺</button>
<div id="legend-panel" class="card">
  <div style="font-size:10px;font-weight:700;letter-spacing:.12em;
    color:var(--muted);text-transform:uppercase;margin-bottom:4px;">Bus Lines</div>
</div>

<!-- ═══ RESULT CARD ═══ -->
<div id="result-card" class="card">
  <div id="result-inner"></div>
</div>

<!-- ═══ LIVE BADGE ═══ -->
<div id="live-badge" class="card">
  <span class="live-dot"></span>
  <span id="bus-count">0 buses</span>
</div>

<script>
// ── Data ─────────────────────────────────────────────────────────────────────
const COLORS      = {colors_str};
const HIGHLIGHT   = new Set({highlight_str});
const geojson     = {geojson_str};
const INIT_ORIGIN = {origin_str};
const INIT_DEST   = {dest_str};
const INIT_BUSES  = {buses_str};
const INIT_RESULT = {result_str};
const LEGEND      = {legend_items};
const SUPA_URL    = "{supabase_url}";
const SUPA_KEY    = "{supabase_key}";

// ── Map ───────────────────────────────────────────────────────────────────────
const map = L.map('map', {{
  center: [{DEFAULT_CENTER[0]}, {DEFAULT_CENTER[1]}],
  zoom: {DEFAULT_ZOOM},
  minZoom: 11,
  maxZoom: 19,
  zoomControl: true,
}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19,
}}).addTo(map);

// ── Routes — managed via updateRouteHighlight() ───────────────────────────────
let activeHighlight = new Set();
// Initial draw with no highlights; replaced whenever points change
function updateRouteHighlight(names) {{
  activeHighlight = new Set(names);
  if (window._routeLayer) map.removeLayer(window._routeLayer);
  window._routeLayer = L.geoJSON(geojson, {{
    style: f => {{
      const n = (f.properties && f.properties.layer) || '';
      const c = COLORS[n] || '#3388ff';
      if (activeHighlight.size > 0) {{
        const active = activeHighlight.has(n);
        return {{ color: c, weight: active ? 7 : 2, opacity: active ? 1.0 : 0.15 }};
      }}
      return {{ color: c, weight: 4, opacity: 0.88 }};
    }},
    onEachFeature: (f, l) => {{
      const n = (f.properties && f.properties.layer) || 'Route';
      l.bindTooltip(n, {{ sticky: true }});
    }}
  }}).addTo(map);
}}
updateRouteHighlight([]);

// ── Legend ────────────────────────────────────────────────────────────────────
const legendPanel = document.getElementById('legend-panel');
LEGEND.forEach(item => {{
  const div = document.createElement('div');
  div.className = 'legend-item';
  div.innerHTML = `<span class="legend-dot" style="background:${{item.color}}"></span>${{item.name}}`;
  legendPanel.appendChild(div);
}});
function toggleLegend() {{ legendPanel.classList.toggle('open'); }}

// ── Markers ───────────────────────────────────────────────────────────────────
const pinIcon = (color, label) => L.divIcon({{
  html: `<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
    <div style="width:16px;height:16px;border-radius:50%;background:${{color}};
      border:3px solid #fff;box-shadow:0 0 8px ${{color}}"></div>
  </div>`,
  iconSize: [16, 16], iconAnchor: [8, 8], className: ''
}});

let originMarker = null, destMarker = null;

function setOriginMarker(lat, lon) {{
  if (originMarker) map.removeLayer(originMarker);
  originMarker = L.marker([lat, lon], {{ icon: pinIcon('#22c55e') }})
    .bindTooltip('Origin').addTo(map);
}}
function setDestMarker(lat, lon) {{
  if (destMarker) map.removeLayer(destMarker);
  destMarker = L.marker([lat, lon], {{ icon: pinIcon('#ef4444') }})
    .bindTooltip('Destination').addTo(map);
}}

if (INIT_ORIGIN) setOriginMarker(INIT_ORIGIN.lat, INIT_ORIGIN.lon);
if (INIT_DEST)   setDestMarker(INIT_DEST.lat,   INIT_DEST.lon);
if (jsOrigin && jsDest) computeAndShow();

// ── Live buses ────────────────────────────────────────────────────────────────
const busMarkers = {{}};
const busIcon = (color, num) => L.divIcon({{
  html: `<div style="background:${{color}};color:#fff;font-size:9px;font-weight:700;
    padding:3px 7px;border-radius:6px;border:2px solid #fff;
    box-shadow:0 0 8px ${{color}};white-space:nowrap;">${{num}}</div>`,
  className: '', iconAnchor: [20, 12]
}});
function placeBus(b) {{
  const color = COLORS[b.bus_line] || '#00d4ff';
  const tip   = `${{b.bus_number}} · ${{(b.bus_line||'').replace(/_/g,' ')}} · ${{Math.round(b.speed_kmh||0)}} km/h`;
  if (busMarkers[b.bus_number]) {{
    busMarkers[b.bus_number].setLatLng([b.lat, b.lon]);
    busMarkers[b.bus_number].setTooltipContent(tip);
  }} else {{
    busMarkers[b.bus_number] = L.marker([b.lat, b.lon], {{
      icon: busIcon(color, b.bus_number), zIndexOffset: 500
    }}).bindTooltip(tip).addTo(map);
  }}
  document.getElementById('bus-count').textContent =
    Object.keys(busMarkers).length + ' bus' + (Object.keys(busMarkers).length !== 1 ? 'es' : '') + ' live';
}}
INIT_BUSES.forEach(placeBus);

if (SUPA_URL && SUPA_KEY) {{
  const {{ createClient }} = supabase;
  const sb = createClient(SUPA_URL, SUPA_KEY, {{ auth: {{ persistSession: false }} }});
  sb.channel('live-buses')
    .on('postgres_changes', {{ event: '*', schema: 'public', table: 'active_locations' }},
      payload => {{
        const b = payload.new;
        if (!b) return;
        if (b.is_active) {{
          placeBus(b);
        }} else if (busMarkers[b.bus_number]) {{
          map.removeLayer(busMarkers[b.bus_number]);
          delete busMarkers[b.bus_number];
        }}
      }})
    .subscribe();
}}

// ── Result card ───────────────────────────────────────────────────────────────
function showResult(r) {{
  const card  = document.getElementById('result-card');
  const inner = document.getElementById('result-inner');
  inner.innerHTML = '';

  if (!r) {{ card.classList.remove('visible'); return; }}

  if (r.error) {{
    inner.innerHTML = `<div class="result-advice error">⚠️  ${{r.error}}</div>`;
    card.classList.add('visible');
    return;
  }}

  const steps = [];

  // Step 1: walk to origin bus stop
  steps.push(`
    <div class="step">
      <div class="step-icon">🚶</div>
      <div class="step-body">
        <div class="step-main">Walk <strong>${{r.origin_walk_m}} m</strong> to the nearest stop</div>
        <div class="step-sub">on <span class="line-pill" style="background:${{r.origin_color}}22;color:${{r.origin_color}};border:1px solid ${{r.origin_color}}55">${{r.origin_label}}</span></div>
      </div>
    </div>`);

  // Step 2: board the bus
  steps.push(`
    <div class="step">
      <div class="step-icon">🚌</div>
      <div class="step-body">
        <div class="step-main">Board <span class="line-pill" style="background:${{r.origin_color}}22;color:${{r.origin_color}};border:1px solid ${{r.origin_color}}55">${{r.origin_label}}</span></div>
        <div class="step-sub">${{r.same_route ? 'Ride to your destination stop' : 'Ride to the transfer stop'}}</div>
      </div>
    </div>`);

  // Step 3: transfer if needed
  if (!r.same_route) {{
    steps.push(`
      <div class="step">
        <div class="step-icon">🔁</div>
        <div class="step-body">
          <div class="step-main">Transfer to <span class="line-pill" style="background:${{r.dest_color}}22;color:${{r.dest_color}};border:1px solid ${{r.dest_color}}55">${{r.dest_label}}</span></div>
          <div class="step-sub">at the intersection of both routes</div>
        </div>
      </div>`);
  }}

  // Step 4: walk to destination
  steps.push(`
    <div class="step">
      <div class="step-icon">📍</div>
      <div class="step-body">
        <div class="step-main">Walk <strong>${{r.dest_walk_m}} m</strong> to your destination</div>
        <div class="step-sub">You've arrived!</div>
      </div>
    </div>`);

  const summary = r.same_route
    ? `<div class="result-summary success">✅ Direct route — no transfer needed</div>`
    : `<div class="result-summary transfer">🔁 1 transfer required</div>`;

  inner.innerHTML = summary + `<div class="steps">${{steps.join('')}}</div>`;
  card.classList.add('visible');
}}

// ── JS Routing engine (runs entirely in browser, no Streamlit rerun needed) ──
// Extract all route points from the geojson once at startup
const ROUTE_POINTS = [];   // {{lat, lon, name}}
const MAX_WALK_KM  = {MAX_WALK_KM};

(function buildRoutePoints() {{
  for (const feature of geojson.features || []) {{
    const name = (feature.properties && feature.properties.layer) || 'Unknown';
    const geom = feature.geometry || {{}};
    const type = geom.type;
    const coords = geom.coordinates || [];
    const lines = type === 'LineString' ? [coords]
                : type === 'MultiLineString' ? coords : [];
    for (const line of lines) {{
      for (const coord of line) {{
        if (Array.isArray(coord) && coord.length >= 2) {{
          ROUTE_POINTS.push({{ lat: coord[1], lon: coord[0], name }});
        }}
      }}
    }}
  }}
}})();

function haversineKm(lat1, lon1, lat2, lon2) {{
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2)**2
    + Math.cos(lat1 * Math.PI/180) * Math.cos(lat2 * Math.PI/180)
    * Math.sin(dLon/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}}

function nearestRoute(lat, lon) {{
  let best = null, bestDist = Infinity;
  for (const p of ROUTE_POINTS) {{
    const d = haversineKm(lat, lon, p.lat, p.lon);
    if (d < bestDist) {{ bestDist = d; best = p; }}
  }}
  return best ? {{ name: best.name, distKm: bestDist }} : null;
}}

// Current origin/dest state (managed fully in JS)
let jsOrigin = INIT_ORIGIN ? {{ lat: INIT_ORIGIN.lat, lon: INIT_ORIGIN.lon }} : null;
let jsDest   = INIT_DEST   ? {{ lat: INIT_DEST.lat,   lon: INIT_DEST.lon   }} : null;

function computeAndShow() {{
  if (!jsOrigin || !jsDest) {{ showResult(null); return; }}

  const oRoute = nearestRoute(jsOrigin.lat, jsOrigin.lon);
  const dRoute = nearestRoute(jsDest.lat,   jsDest.lon);

  if (!oRoute || !dRoute) {{
    showResult({{ error: 'Could not find nearby routes.' }}); return;
  }}
  if (oRoute.distKm > MAX_WALK_KM) {{
    showResult({{ error: `Origin is ${{(oRoute.distKm * 1000).toFixed(0)}} m from the nearest bus route — too far to walk (${{(MAX_WALK_KM*1000).toFixed(0)}} m max).` }}); return;
  }}
  if (dRoute.distKm > MAX_WALK_KM) {{
    showResult({{ error: `Destination is ${{(dRoute.distKm * 1000).toFixed(0)}} m from the nearest bus route — too far to walk (${{(MAX_WALK_KM*1000).toFixed(0)}} m max).` }}); return;
  }}

  const same = oRoute.name === dRoute.name;
  const oColor = COLORS[oRoute.name] || '#888';
  const dColor = COLORS[dRoute.name] || '#888';

  // Highlight the relevant routes on the map
  updateRouteHighlight(same ? [oRoute.name] : [oRoute.name, dRoute.name]);

  showResult({{
    origin_route:  oRoute.name,
    origin_label:  oRoute.name.replace(/_/g, ' '),
    origin_color:  oColor,
    origin_walk_m: Math.round(oRoute.distKm * 1000),
    dest_route:    dRoute.name,
    dest_label:    dRoute.name.replace(/_/g, ' '),
    dest_color:    dColor,
    dest_walk_m:   Math.round(dRoute.distKm * 1000),
    same_route:    same,
  }});
}}

// ── Click / manual input mode ─────────────────────────────────────────────────
let mode = 'idle';

function toggleMode(m) {{
  mode = (mode === m) ? 'idle' : m;
  document.getElementById('btn-origin').classList.toggle('active', mode === 'set_origin');
  document.getElementById('btn-dest').classList.toggle('active',   mode === 'set_destination');
  map.getContainer().classList.toggle('picking', mode !== 'idle');
}}

map.on('click', e => {{
  if (mode === 'idle') return;
  const lat = e.latlng.lat, lon = e.latlng.lng;
  const type = mode;

  // Update input box
  const inputId = type === 'set_origin' ? 'input-origin' : 'input-dest';
  const inp = document.getElementById(inputId);
  inp.value = lat.toFixed(6) + ', ' + lon.toFixed(6);
  inp.classList.add('has-val');

  // Update marker + JS state
  if (type === 'set_origin') {{
    setOriginMarker(lat, lon);
    jsOrigin = {{ lat, lon }};
  }} else {{
    setDestMarker(lat, lon);
    jsDest = {{ lat, lon }};
  }}

  // Compute route instantly — no rerun needed
  computeAndShow();

  // Relay to Streamlit (for session state persistence only)
  postAction(type, lat, lon);

  // Auto-advance origin → destination
  mode = (type === 'set_origin') ? 'set_destination' : 'idle';
  document.getElementById('btn-origin').classList.toggle('active', mode === 'set_origin');
  document.getElementById('btn-dest').classList.toggle('active',   mode === 'set_destination');
  map.getContainer().classList.toggle('picking', mode !== 'idle');
}});

// Parse "lat, lon" string from manual input
function applyManual(type, raw) {{
  const parts = raw.split(',').map(s => s.trim());
  if (parts.length !== 2) return;
  const lat = parseFloat(parts[0]), lon = parseFloat(parts[1]);
  if (isNaN(lat) || isNaN(lon)) return;
  if (type === 'origin') {{
    setOriginMarker(lat, lon);
    jsOrigin = {{ lat, lon }};
    postAction('set_origin', lat, lon);
  }} else {{
    setDestMarker(lat, lon);
    jsDest = {{ lat, lon }};
    postAction('set_destination', lat, lon);
  }}
  map.setView([lat, lon], map.getZoom());
  computeAndShow();
}}

function clearPoint(type) {{
  if (type === 'origin') {{
    if (originMarker) {{ map.removeLayer(originMarker); originMarker = null; }}
    document.getElementById('input-origin').value = '';
    document.getElementById('input-origin').classList.remove('has-val');
    jsOrigin = null;
  }} else {{
    if (destMarker) {{ map.removeLayer(destMarker); destMarker = null; }}
    document.getElementById('input-dest').value = '';
    document.getElementById('input-dest').classList.remove('has-val');
    jsDest = null;
  }}
  postAction('clear_' + type);
  updateRouteHighlight([]);
  showResult(null);
}}

function resetAll() {{
  if (originMarker) {{ map.removeLayer(originMarker); originMarker = null; }}
  if (destMarker)   {{ map.removeLayer(destMarker);   destMarker   = null; }}
  document.getElementById('input-origin').value = '';
  document.getElementById('input-dest').value   = '';
  document.getElementById('input-origin').classList.remove('has-val');
  document.getElementById('input-dest').classList.remove('has-val');
  jsOrigin = null; jsDest = null;
  mode = 'idle';
  document.getElementById('btn-origin').classList.remove('active');
  document.getElementById('btn-dest').classList.remove('active');
  map.getContainer().classList.remove('picking');
  updateRouteHighlight([]);
  showResult(null);
  postAction('reset');
}}

// ── postMessage to Streamlit ──────────────────────────────────────────────────
function postAction(type, lat, lon) {{
  let val = type;
  if (lat !== undefined) val += ':' + lat.toFixed(6) + '_' + lon.toFixed(6);
  val += '|' + Date.now();
  window.parent.postMessage({{ type: 'map_action', payload: {{ raw: val }} }}, '*');
}}

// Populate inputs from existing state
if (INIT_ORIGIN) {{
  const i = document.getElementById('input-origin');
  i.value = INIT_ORIGIN.lat.toFixed(6) + ', ' + INIT_ORIGIN.lon.toFixed(6);
  i.classList.add('has-val');
}}
if (INIT_DEST) {{
  const i = document.getElementById('input-dest');
  i.value = INIT_DEST.lat.toFixed(6) + ', ' + INIT_DEST.lon.toFixed(6);
  i.classList.add('has-val');
}}

// Tell parent to resize this iframe to fill the viewport
function resizeIframe() {{
  const h = window.innerHeight || document.documentElement.clientHeight || 900;
  window.parent.postMessage({{ type: 'resize_map', height: h }}, '*');
}}
resizeIframe();
window.addEventListener('resize', resizeIframe);
</script>
</body>
</html>"""


# ── Session + relay ───────────────────────────────────────────────────────────

def init_state():
    st.session_state.setdefault("origin", None)
    st.session_state.setdefault("destination", None)
    st.session_state.setdefault("last_action", None)
    st.session_state.setdefault("highlight_routes", [])


def main():
    init_state()

    try:
        routes_geojson = load_routes(ROUTES_FILE)
    except Exception as e:
        st.error(f"Failed to load route file: {e}"); return

    route_points_df = extract_route_points(routes_geojson)
    if route_points_df.empty:
        st.error("No route points found in bus_lines.geojson."); return

    trip_result, highlight_routes = compute_trip(route_points_df)
    # Only update highlights when they actually change — avoid infinite rerun loop
    if set(highlight_routes) != set(st.session_state.highlight_routes):
        st.session_state.highlight_routes = highlight_routes
        # Don't rerun here — pass highlights directly to the map below

    live_buses = fetch_live_buses()
    supa_url   = st.secrets.get("SUPABASE_URL", "")   if hasattr(st, "secrets") else ""
    supa_key   = st.secrets.get("SUPABASE_ANON_KEY", "") if hasattr(st, "secrets") else ""

    # ── Fullscreen map (100 vh) ───────────────────────────────────────────────
    html = build_map_html(
        routes_geojson,
        highlight_routes,                  # use freshly computed, not stale session value
        st.session_state.origin,
        st.session_state.destination,
        trip_result,
        live_buses,
        supa_url,
        supa_key,
    )
    components.html(html, height=900, scrolling=False)

    # ── postMessage relay ─────────────────────────────────────────────────────
    relay_js = """
    <script>
    window.addEventListener('message', function(e) {
        if (!e.data) return;

        // Resize the map iframe to fill viewport
        if (e.data.type === 'resize_map') {
            const iframes = window.parent.document.querySelectorAll('iframe');
            iframes.forEach(function(f) {
                // target the map iframe (the large one)
                if (f.getAttribute('height') && parseInt(f.getAttribute('height')) > 100) {
                    const h = e.data.height;
                    f.style.height = h + 'px';
                    f.style.minHeight = h + 'px';
                    f.setAttribute('height', h);
                }
            });
            return;
        }

        if (e.data.type !== 'map_action') return;
        const raw = e.data.payload.raw;
        const inputs = window.parent.document.querySelectorAll(
            'input[data-testid="stTextInput"] input');
        if (inputs.length > 0) {
            const el = inputs[inputs.length - 1];
            el.value = raw;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    });
    </script>
    """
    components.html(relay_js, height=0)
    action_val = st.text_input("r", key="action_relay", label_visibility="collapsed")

    if action_val and action_val != st.session_state.last_action:
        st.session_state.last_action = action_val
        raw = action_val.split("|")[0]

        if raw == "reset" or raw == "clear_origin" or raw == "clear_destination":
            if raw in ("reset", "clear_origin"):
                st.session_state.origin = None
            if raw in ("reset", "clear_destination"):
                st.session_state.destination = None
            st.session_state.highlight_routes = []
            st.rerun()

        elif raw.startswith("set_origin:"):
            la, lo = raw[len("set_origin:"):].split("_")
            st.session_state.origin = {"lat": float(la), "lon": float(lo)}
            st.rerun()

        elif raw.startswith("set_destination:"):
            la, lo = raw[len("set_destination:"):].split("_")
            st.session_state.destination = {"lat": float(la), "lon": float(lo)}
            st.rerun()


if __name__ == "__main__":
    main()
