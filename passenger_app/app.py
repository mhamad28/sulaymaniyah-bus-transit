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

    geojson_str  = json.dumps(routes_geojson)
    colors_str   = json.dumps(ROUTE_COLORS)
    origin_str   = json.dumps(origin)
    dest_str     = json.dumps(destination)
    buses_str    = json.dumps(live_buses)
    legend_items = json.dumps([
        {"name": k.replace("_", " "), "color": v}
        for k, v in ROUTE_COLORS.items()
    ])


    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Naskh+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:100%; height:100%; background:#080d14; overflow:hidden;
  font-family: 'Noto Naskh Arabic', system-ui, sans-serif; }}
#map {{ width:100%; height:100vh; }}

/* glass card base */
.card {{
  background: rgba(10,16,26,0.88);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  color: #e2eaf4;
}}

/* ── TOP PANEL ── */
#top-panel {{
  position: absolute; top: 14px; left: 50%;
  transform: translateX(-50%);
  z-index: 1000; width: min(500px, 92vw);
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px;
}}
.row {{ display:flex; align-items:center; gap:8px; }}
.dot {{ width:11px; height:11px; border-radius:50%; flex-shrink:0;
  border:2px solid rgba(255,255,255,.5); }}
.pick-btn {{
  flex-shrink:0; padding:6px 13px; border-radius:8px; border:1.5px solid;
  font-size:12px; font-weight:700; cursor:pointer; background:transparent;
  transition:all .15s; white-space:nowrap;
}}
.pick-btn:hover {{ filter:brightness(1.2); transform:translateY(-1px); }}
.pick-btn.green {{ border-color:#22c55e; color:#4ade80; }}
.pick-btn.green.on {{ background:#22c55e; color:#000;
  box-shadow:0 0 12px rgba(34,197,94,.5); }}
.pick-btn.red {{ border-color:#ef4444; color:#f87171; }}
.pick-btn.red.on {{ background:#ef4444; color:#fff;
  box-shadow:0 0 12px rgba(239,68,68,.5); }}
.coord-box {{
  flex:1; min-width:0;
  background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.13);
  border-radius:8px; padding:7px 10px;
  font-size:12px; font-family:monospace; color:#e2eaf4;
  outline:none; transition:border-color .15s;
  direction: ltr;  /* coords are always LTR (numbers) */
}}
.coord-box::placeholder {{ color:#475569; direction: rtl; font-family: 'Noto Naskh Arabic', sans-serif; }}
.coord-box:focus {{ border-color:#00d4ff; }}
.x-btn {{
  flex-shrink:0; width:24px; height:24px; border-radius:50%;
  border:1px solid rgba(255,255,255,.15); background:rgba(255,255,255,.06);
  color:#64748b; font-size:12px; cursor:pointer; line-height:1;
  transition:all .15s;
}}
.x-btn:hover {{ background:rgba(255,255,255,.18); color:#e2eaf4; }}
.hr {{ height:1px; background:rgba(255,255,255,.08); }}
.reset-btn {{
  background:transparent; border:1px solid rgba(148,163,184,.3);
  border-radius:7px; color:#94a3b8; font-size:11px; font-weight:600;
  padding:4px 14px; cursor:pointer; margin-left:auto; transition:all .15s;
}}
.reset-btn:hover {{ background:rgba(148,163,184,.15); color:#e2eaf4; }}

/* crosshair when picking */
.picking {{ cursor:crosshair !important; }}

/* ── RESULT CARD ── */
#result-card {{
  position:absolute; bottom:20px; left:50%;
  transform:translateX(-50%) translateY(300px);
  transition:transform .4s cubic-bezier(.34,1.56,.64,1);
  z-index:1000; width:min(460px, 92vw);
  padding:14px 16px; pointer-events:none;
}}
#result-card.show {{
  transform:translateX(-50%) translateY(0);
  pointer-events:all;
}}
.summary {{
  text-align:center; font-size:13px; font-weight:700;
  padding:7px 12px; border-radius:8px; margin-bottom:10px;
}}
.summary.ok  {{ background:rgba(34,197,94,.15); border:1px solid rgba(34,197,94,.3); color:#4ade80; }}
.summary.xfr {{ background:rgba(251,191,36,.13); border:1px solid rgba(251,191,36,.3); color:#fbbf24; }}
.summary.err {{ background:rgba(239,68,68,.13);  border:1px solid rgba(239,68,68,.3);  color:#f87171; }}
.steps {{ display:flex; flex-direction:column; gap:6px; }}
.step {{
  display:flex; align-items:flex-start; gap:10px;
  padding:8px 10px; border-radius:8px;
  background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.07);
}}
.si {{ font-size:15px; flex-shrink:0; line-height:1.5; }}
.sb {{ display:flex; flex-direction:column; gap:2px; }}
.sm {{ font-size:13px; color:#e2eaf4; font-weight:500; }}
.ss {{ font-size:11px; color:#64748b; }}
.pill {{
  display:inline-block; font-size:11px; font-weight:700;
  padding:1px 8px; border-radius:12px;
}}

/* ── LEGEND ── */
#leg-btn {{
  position:absolute; top:14px; right:14px; z-index:1001;
  width:38px; height:38px; border-radius:10px;
  background:rgba(10,16,26,.88); backdrop-filter:blur(14px);
  border:1px solid rgba(255,255,255,.10); color:#e2eaf4;
  font-size:18px; cursor:pointer;
  display:flex; align-items:center; justify-content:center;
  box-shadow:0 4px 16px rgba(0,0,0,.4);
}}
#leg-panel {{
  position:absolute; top:60px; right:14px; z-index:1000;
  width:190px; max-height:55vh; overflow-y:auto;
  padding:10px 12px; display:none; flex-direction:column; gap:5px;
}}
#leg-panel.open {{ display:flex; }}
.li {{ display:flex; align-items:center; gap:7px; font-size:12px; color:#e2eaf4; }}
.ld {{ width:9px; height:9px; border-radius:50%; flex-shrink:0; }}

/* ── LIVE BADGE ── */
#live-badge {{
  position:absolute; bottom:20px; right:14px; z-index:1000;
  padding:5px 13px; border-radius:20px; font-size:11px; font-weight:600;
  color:#4ade80; border:1px solid rgba(34,197,94,.3);
  background:rgba(10,16,26,.88); backdrop-filter:blur(14px);
  display:flex; align-items:center; gap:6px;
}}
.ld-dot {{ width:7px; height:7px; border-radius:50%; background:#22c55e;
  animation:blink 1.4s infinite; }}
@keyframes blink {{ 0%,100%{{opacity:1;}} 50%{{opacity:.2;}} }}

/* leaflet zoom */
.leaflet-control-zoom {{ border:none !important; }}
.leaflet-control-zoom a {{
  background:rgba(10,16,26,.88) !important; color:#e2eaf4 !important;
  border:1px solid rgba(255,255,255,.10) !important;
}}
</style>
</head>
<body>
<div id="map"></div>

<!-- TOP PANEL -->
<div id="top-panel" class="card" dir="rtl" lang="ckb">
  <div class="row">
    <span class="dot" style="background:#22c55e"></span>
    <button class="pick-btn green" id="btn-o" onclick="toggleMode('origin')">📍 هەڵبژێرە</button>
    <input class="coord-box" id="inp-o" placeholder="بنکە — کۆدینەیت لە گووگڵ مەپ لێرە بنووسە"
           oninput="onCoordInput('origin', this.value)"/>
    <button class="x-btn" onclick="clearPt('origin')">✕</button>
  </div>
  <div class="hr"></div>
  <div class="row">
    <span class="dot" style="background:#ef4444"></span>
    <button class="pick-btn red" id="btn-d" onclick="toggleMode('dest')">🏁 هەڵبژێرە</button>
    <input class="coord-box" id="inp-d" placeholder="مەودا — کۆدینەیت لە گووگڵ مەپ لێرە بنووسە"
           oninput="onCoordInput('dest', this.value)"/>
    <button class="x-btn" onclick="clearPt('dest')">✕</button>
  </div>
  <div class="hr"></div>
  <div class="row"><button class="reset-btn" onclick="resetAll()">↺ ڕەستکردنەوە</button></div>
</div>

<!-- LEGEND -->
<button id="leg-btn" onclick="toggleLeg()">🗺</button>
<div id="leg-panel" class="card">
  <div style="font-size:9px;font-weight:700;letter-spacing:.05em;color:#475569;
    margin-bottom:4px;">هێڵەکانی بەس</div>
</div>

<!-- RESULT -->
<div id="result-card" class="card" dir="rtl" lang="ckb"><div id="result-inner"></div></div>

<!-- LIVE BADGE -->
<div id="live-badge" dir="rtl" lang="ckb"><span class="ld-dot"></span><span id="bus-ct">٠ بەس</span></div>

<script>
const COLORS   = {colors_str};
const GEOJSON  = {geojson_str};
const LEGEND   = {legend_items};
const INIT_O   = {origin_str};
const INIT_D   = {dest_str};
const BUSES    = {buses_str};
const SUPA_URL = "{supabase_url}";
const SUPA_KEY = "{supabase_key}";
const MAX_WALK = {MAX_WALK_KM};

// ── Map ───────────────────────────────────────────────────────────────────────
const map = L.map('map',{{center:[{DEFAULT_CENTER[0]},{DEFAULT_CENTER[1]}],
  zoom:{DEFAULT_ZOOM},minZoom:10,maxZoom:19}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{attribution:'© OpenStreetMap',maxZoom:19}}).addTo(map);

// ── Route layer (re-drawn on highlight change) ────────────────────────────────
let routeLayer = null;
function drawRoutes(active) {{
  if (routeLayer) map.removeLayer(routeLayer);
  routeLayer = L.geoJSON(GEOJSON, {{
    style: f => {{
      const n = (f.properties && f.properties.layer) || '';
      const c = COLORS[n] || '#3388ff';
      if (active && active.size > 0)
        return active.has(n)
          ? {{color:c, weight:7, opacity:1.0}}
          : {{color:c, weight:2, opacity:0.13}};
      return {{color:c, weight:4, opacity:0.88}};
    }},
    onEachFeature:(f,l) => l.bindTooltip(
      (f.properties&&f.properties.layer)||'Route', {{sticky:true}})
  }}).addTo(map);
}}
drawRoutes(null);

// ── Legend ────────────────────────────────────────────────────────────────────
const legPanel = document.getElementById('leg-panel');
LEGEND.forEach(item => {{
  const d = document.createElement('div');
  d.className = 'li';
  d.innerHTML = `<span class="ld" style="background:${{item.color}}"></span>${{item.name}}`;
  legPanel.appendChild(d);
}});
function toggleLeg() {{ legPanel.classList.toggle('open'); }}

// ── Markers ───────────────────────────────────────────────────────────────────
function pinIcon(color) {{
  return L.divIcon({{
    html:`<div style="width:16px;height:16px;border-radius:50%;
      background:${{color}};border:3px solid #fff;
      box-shadow:0 0 8px ${{color}}"></div>`,
    iconSize:[16,16], iconAnchor:[8,8], className:''
  }});
}}
let mO=null, mD=null;
function placeO(lat,lon) {{
  if(mO) map.removeLayer(mO);
  mO = L.marker([lat,lon],{{icon:pinIcon('#22c55e')}}).bindTooltip('Origin').addTo(map);
}}
function placeD(lat,lon) {{
  if(mD) map.removeLayer(mD);
  mD = L.marker([lat,lon],{{icon:pinIcon('#ef4444')}}).bindTooltip('Destination').addTo(map);
}}
if(INIT_O) {{ placeO(INIT_O.lat,INIT_O.lon); }}
if(INIT_D) {{ placeD(INIT_D.lat,INIT_D.lon); }}

// ── Live buses ────────────────────────────────────────────────────────────────
const busM = {{}};
function busIcon(color,num) {{
  return L.divIcon({{
    html:`<div style="background:${{color}};color:#fff;font-size:9px;font-weight:700;
      padding:3px 7px;border-radius:6px;border:2px solid #fff;
      box-shadow:0 0 8px ${{color}};white-space:nowrap;">${{num}}</div>`,
    className:'', iconAnchor:[20,12]
  }});
}}
function placeBus(b) {{
  const c = COLORS[b.bus_line]||'#00d4ff';
  const tip = b.bus_number+' · '+(b.bus_line||'').replace(/_/g,' ')+' · '+Math.round(b.speed_kmh||0)+' km/h';
  if(busM[b.bus_number]) {{ busM[b.bus_number].setLatLng([b.lat,b.lon]); busM[b.bus_number].setTooltipContent(tip); }}
  else busM[b.bus_number]=L.marker([b.lat,b.lon],{{icon:busIcon(c,b.bus_number),zIndexOffset:500}}).bindTooltip(tip).addTo(map);
  document.getElementById('bus-ct').textContent=Object.keys(busM).length+' بەس زیندوو';
}}
BUSES.forEach(placeBus);
if(SUPA_URL&&SUPA_KEY) {{
  const {{createClient}}=supabase;
  const sb=createClient(SUPA_URL,SUPA_KEY,{{auth:{{persistSession:false}}}});
  sb.channel('buses').on('postgres_changes',{{event:'*',schema:'public',table:'active_locations'}},p=>{{
    const b=p.new; if(!b) return;
    if(b.is_active) placeBus(b);
    else if(busM[b.bus_number]) {{ map.removeLayer(busM[b.bus_number]); delete busM[b.bus_number]; }}
  }}).subscribe();
}}

// ══════════════════════════════════════════════════════════════════════════════
//  ROUTING ENGINE
//
//  Real Sulaymaniyah bus model:
//  • No fixed stops — wave down the bus anywhere along its road
//  • Tell the driver where to drop you off
//  • Transfer = the two route lines physically share the same road
//               (any point on line A within XFER_THRESH of any point on line B)
//  • If lines share a road → drop off there, board next bus on same road (0m walk)
//  • If closest approach is 50–200m → short walk between the two roads
//  • If lines never come close → impossible transfer, not suggested
// ══════════════════════════════════════════════════════════════════════════════

const XFER_MAX_KM = 0.05;   // 50 m — max gap between lines to consider a valid transfer
const XFER_SAME   = 0.015;  // 15 m — within this = literally same road, no walking

// Build per-route point arrays  routeName → [{{lat,lon}}, ...]
const ROUTE_PTS = Object.create(null);
for (const f of GEOJSON.features||[]) {{
  const name = (f.properties&&f.properties.layer)||'';
  if(!name) continue;
  if(!ROUTE_PTS[name]) ROUTE_PTS[name]=[];
  const geom = f.geometry||{{}};
  const segs = geom.type==='LineString'      ? [geom.coordinates]
             : geom.type==='MultiLineString' ?  geom.coordinates : [];
  for (const seg of segs)
    for (const c of seg)
      if(Array.isArray(c)&&c.length>=2)
        ROUTE_PTS[name].push({{lat:c[1], lon:c[0]}});
}}
const ROUTE_NAMES = Object.keys(ROUTE_PTS);

// ── Haversine km ─────────────────────────────────────────────────────────────
function hav(la1,lo1,la2,lo2) {{
  const R=6371, r=Math.PI/180;
  const dla=(la2-la1)*r, dlo=(lo2-lo1)*r;
  const a=Math.sin(dla/2)**2+Math.cos(la1*r)*Math.cos(la2*r)*Math.sin(dlo/2)**2;
  return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

// Nearest point on a named route to (lat,lon) — returns {{km, pt}}
function nearestOnRoute(lat, lon, name) {{
  let best=Infinity, bestPt=null;
  for (const p of (ROUTE_PTS[name]||[])) {{
    const d=hav(lat,lon,p.lat,p.lon);
    if(d<best){{best=d; bestPt=p;}}
  }}
  return {{km:best, pt:bestPt}};
}}

// All routes reachable on foot within maxKm, sorted by distance
function nearbyRoutes(lat, lon, maxKm) {{
  const out=[];
  for (const name of ROUTE_NAMES) {{
    const {{km,pt}}=nearestOnRoute(lat,lon,name);
    if(km<=maxKm) out.push({{name,km,boardPt:pt}});
  }}
  return out.sort((a,b)=>a.km-b.km);
}}

// ── Transfer geometry ─────────────────────────────────────────────────────────
// True closest approach — scans ALL point pairs between two routes.
// 13 routes × ~200 pts each → ~78 pairs × 40k comparisons = ~3M ops, < 50ms.
function closestApproach(nameA, nameB) {{
  const ptsA = ROUTE_PTS[nameA]||[];
  const ptsB = ROUTE_PTS[nameB]||[];
  if(!ptsA.length||!ptsB.length) return {{gapKm:Infinity,ptA:null,ptB:null}};

  let best=Infinity, ptA=ptsA[0], ptB=ptsB[0];
  for (let i=0; i<ptsA.length; i++) {{
    const la=ptsA[i].lat, lo=ptsA[i].lon;
    for (let j=0; j<ptsB.length; j++) {{
      const d = hav(la,lo,ptsB[j].lat,ptsB[j].lon);
      if(d<best){{ best=d; ptA=ptsA[i]; ptB=ptsB[j]; }}
    }}
  }}
  return {{gapKm:best, ptA, ptB}};
}}

// Pre-compute approach table at startup (once, cached)
const APPROACH = Object.create(null);
for (const a of ROUTE_NAMES) {{
  APPROACH[a] = Object.create(null);
  for (const b of ROUTE_NAMES) {{
    if(a!==b) APPROACH[a][b] = closestApproach(a,b);
  }}
}}

// ── State ────────────────────────────────────────────────────────────────────
let ptO = INIT_O ? {{lat:INIT_O.lat,lon:INIT_O.lon}} : null;
let ptD = INIT_D ? {{lat:INIT_D.lat,lon:INIT_D.lon}} : null;

// Transfer map layers
let _dropMarker=null, _boardMarker=null, _walkLine=null, _walkLine2=null;
function clearXferLayers() {{
  [_dropMarker,_boardMarker,_walkLine,_walkLine2].forEach(l=>{{if(l)map.removeLayer(l);}});
  _dropMarker=_boardMarker=_walkLine=_walkLine2=null;
}}

// ── Main compute ─────────────────────────────────────────────────────────────
function compute() {{
  clearXferLayers();
  if(!ptO||!ptD) {{ hideResult(); return; }}

  const atO = nearbyRoutes(ptO.lat, ptO.lon, MAX_WALK);
  const atD = nearbyRoutes(ptD.lat, ptD.lon, MAX_WALK);

  if(!atO.length) {{
    showErr('دەستپێکردنت زیاتر لە '+Math.round(MAX_WALK*1000)+' م دوورە لە هیچ هێڵێک'); return;
  }}
  if(!atD.length) {{
    showErr('مەوداکەت زیاتر لە '+Math.round(MAX_WALK*1000)+' م دوورە لە هیچ هێڵێک'); return;
  }}

  const namesAtD = new Set(atD.map(r=>r.name));

  // ── CASE 1: Direct ────────────────────────────────────────────────────────
  const directs = atO.filter(r=>namesAtD.has(r.name));
  if(directs.length>0) {{
    // Pick the one that minimises total walk (origin walk + destination walk)
    let best=null, bestTotal=Infinity;
    for (const r of directs) {{
      const wD = atD.find(x=>x.name===r.name).km;
      const t = r.km+wD;
      if(t<bestTotal){{bestTotal=t;best=r;}}
    }}
    const walkD = atD.find(r=>r.name===best.name).km;
    const alts  = directs.filter(r=>r.name!==best.name);

    // Board point marker on origin route
    _dropMarker = pulseMarker(best.boardPt.lat, best.boardPt.lon, '#22c55e', 'سەر پاسەکە کەوە');
    // Drop-off point marker on destination side
    const dropPt = nearestOnRoute(ptD.lat, ptD.lon, best.name).pt;
    _boardMarker = pulseMarker(dropPt.lat, dropPt.lon, '#22c55e', 'بڵێ: دابەزین هەیە');

    drawRoutes(new Set(directs.map(r=>r.name)));
    showDirect({{
      lineO:   best.name,
      labelO:  best.name.replace(/_/g,' '),
      colorO:  COLORS[best.name]||'#888',
      walkO_m: Math.round(best.km*1000),
      walkD_m: Math.round(walkD*1000),
      boardPt: best.boardPt,
      dropPt,
      alts,
    }});
    return;
  }}

  // ── CASE 2: 1 transfer — lines physically cross ───────────────────────────
  // Find the pair (lineA from atO, lineB from atD) with:
  //   1. A valid crossing (gapKm ≤ XFER_MAX_KM)
  //   2. Minimum score = walkO + gapKm + walkD
  let bestT=null, bestScore=Infinity;
  for (const rO of atO) {{
    for (const rD of atD) {{
      const app = APPROACH[rO.name]&&APPROACH[rO.name][rD.name];
      if(!app||app.gapKm>XFER_MAX_KM) continue;
      const score = rO.km + app.gapKm + rD.km;
      if(score<bestScore){{bestScore=score; bestT={{rO,rD,app}};}}
    }}
  }}

  if(bestT) {{
    const {{rO,rD,app}}=bestT;
    const sameRoad = app.gapKm<=XFER_SAME;
    const xferWalk_m = Math.round(app.gapKm*1000);

    drawRoutes(new Set([rO.name,rD.name]));

    // Drop-off circle on line A (pulsing yellow)
    _dropMarker = pulseMarker(app.ptA.lat, app.ptA.lon, '#fbbf24',
      'بڵێ: دابەزین هەیە — شوێنی گۆڕین');

    // Board circle on line B (pulsing blue)
    _boardMarker = pulseMarker(app.ptB.lat, app.ptB.lon, '#60a5fa',
      'سەر پاسی '+rD.name.replace(/_/g,' ')+' کەوە');

    // Dashed walking line between them (only if gap > ~10m)
    if(!sameRoad && app.gapKm>0.01) {{
      _walkLine = L.polyline(
        [[app.ptA.lat,app.ptA.lon],[app.ptB.lat,app.ptB.lon]],
        {{color:'#fbbf24', weight:2, dashArray:'6 5', opacity:0.8}}
      ).addTo(map);
    }}

    showTransfer({{
      lineO:   rO.name, labelO: rO.name.replace(/_/g,' '), colorO: COLORS[rO.name]||'#888',
      lineD:   rD.name, labelD: rD.name.replace(/_/g,' '), colorD: COLORS[rD.name]||'#888',
      walkO_m: Math.round(rO.km*1000),
      walkD_m: Math.round(rD.km*1000),
      xferWalk_m, sameRoad,
      dropPt:  app.ptA, boardPt: app.ptB,
      viaBazaar: false,
    }});
    return;
  }}

  // ── CASE 3: Via Bazaar hub ────────────────────────────────────────────────
  // Every route is named X_Bazar — all lines terminate at / pass through the
  // Bazaar city-centre terminal. When lines don't cross, the passenger rides
  // Line A to the Bazaar, walks within the terminal area, boards Line B.
  //
  // We compute the Bazaar point for each line as the endpoint of the polyline
  // that is closest to the centroid of ALL route endpoints (the terminal cluster).

  // Step 1: collect all endpoint candidates (first + last point of each route)
  const allEnds = [];
  for (const name of ROUTE_NAMES) {{
    const pts = ROUTE_PTS[name];
    if(pts.length) {{
      allEnds.push({{name, pt:pts[0],       end:'first'}});
      allEnds.push({{name, pt:pts[pts.length-1], end:'last'}});
    }}
  }}
  // Step 2: centroid of all endpoints → this is roughly the Bazaar
  const centLat = allEnds.reduce((s,e)=>s+e.pt.lat,0)/allEnds.length;
  const centLon = allEnds.reduce((s,e)=>s+e.pt.lon,0)/allEnds.length;

  // Step 3: for each route, its "Bazaar point" = whichever endpoint is closer
  //         to the centroid
  function bazaarPt(name) {{
    const pts = ROUTE_PTS[name];
    if(!pts.length) return null;
    const first=pts[0], last=pts[pts.length-1];
    return hav(first.lat,first.lon,centLat,centLon)
         < hav(last.lat, last.lon, centLat,centLon)
         ? first : last;
  }}

  // Step 4: find best (lineA, lineB) pair via Bazaar
  // score = walkO(lineA) + walkBazaar(dropBazaarA → boardBazaarB) + walkD(lineB)
  let bestB=null, bestBScore=Infinity;
  for (const rO of atO) {{
    const bzA = bazaarPt(rO.name);
    if(!bzA) continue;
    for (const rD of atD) {{
      if(rD.name===rO.name) continue;
      const bzB = bazaarPt(rD.name);
      if(!bzB) continue;
      const bazaarWalk = hav(bzA.lat,bzA.lon,bzB.lat,bzB.lon);
      const score = rO.km + bazaarWalk + rD.km;
      if(score<bestBScore){{
        bestBScore=score;
        bestB={{rO,rD,bzA,bzB,bazaarWalk}};
      }}
    }}
  }}

  if(bestB) {{
    const {{rO,rD,bzA,bzB,bazaarWalk}}=bestB;
    const bazaarWalk_m = Math.round(bazaarWalk*1000);

    drawRoutes(new Set([rO.name,rD.name]));

    // Green dot = board Line A
    _dropMarker  = pulseMarker(rO.boardPt.lat, rO.boardPt.lon, '#22c55e',
      'سەر پاسی '+rO.name.replace(/_/g,' ')+' کەوە');
    // Yellow dot = drop off at Bazaar from Line A
    _boardMarker = pulseMarker(bzA.lat, bzA.lon, '#fbbf24',
      'پاسەکە لە بازاڕ دەوەستێت بە خۆی');
    // Blue dot = board Line B at Bazaar
    _walkLine    = pulseMarker(bzB.lat, bzB.lon, '#60a5fa',
      'سەر پاسی '+rD.name.replace(/_/g,' ')+' کەوە');
    // Dashed walk between the two Bazaar points
    if(bazaarWalk>0.01) {{
      _walkLine2 = L.polyline(
        [[bzA.lat,bzA.lon],[bzB.lat,bzB.lon]],
        {{color:'#fbbf24', weight:2, dashArray:'6 5', opacity:0.8}}
      ).addTo(map);
    }}

    showTransfer({{
      lineO:   rO.name, labelO: rO.name.replace(/_/g,' '), colorO: COLORS[rO.name]||'#888',
      lineD:   rD.name, labelD: rD.name.replace(/_/g,' '), colorD: COLORS[rD.name]||'#888',
      walkO_m: Math.round(rO.km*1000),
      walkD_m: Math.round(rD.km*1000),
      xferWalk_m: bazaarWalk_m,
      sameRoad: bazaarWalk<=XFER_SAME,
      dropPt:  bzA, boardPt: bzB,
      viaBazaar: true,
    }});
    return;
  }}

  // ── CASE 4: Truly unreachable ─────────────────────────────────────────────
  showErr('هیچ هێڵێک نەدۆزرایەوە.');
}}

// ── Pulsing circle marker ─────────────────────────────────────────────────────
function pulseMarker(lat, lon, color, tip) {{
  const icon = L.divIcon({{
    html: `<div style="
      width:18px;height:18px;border-radius:50%;
      background:${{color}};border:3px solid #fff;
      box-shadow:0 0 0 0 ${{color}}88;
      animation:ripple 1.4s infinite;"></div>`,
    iconSize:[18,18], iconAnchor:[9,9], className:''
  }});
  return L.marker([lat,lon],{{icon,zIndexOffset:900}})
    .bindTooltip(tip,{{permanent:false,direction:'top'}})
    .addTo(map);
}}

// Inject ripple keyframe once
if(!document.getElementById('ripple-style')) {{
  const s=document.createElement('style');
  s.id='ripple-style';
  s.textContent=`@keyframes ripple{{
    0%{{box-shadow:0 0 0 0 rgba(255,255,255,.6);}}
    70%{{box-shadow:0 0 0 10px rgba(255,255,255,0);}}
    100%{{box-shadow:0 0 0 0 rgba(255,255,255,0);}}
  }}`;
  document.head.appendChild(s);
}}

// ── Result renderers ──────────────────────────────────────────────────────────
function pill(label,color) {{
  return `<span class="pill" style="background:${{color}}22;color:${{color}};border:1px solid ${{color}}55">${{label}}</span>`;
}}

function fmtCoord(pt) {{
  return pt ? '('+pt.lat.toFixed(5)+', '+pt.lon.toFixed(5)+')' : '';
}}

function showDirect(r) {{
  const altHtml = r.alts.length
    ? `<div class="ss" style="margin-top:4px;">هەروەها دەگنجێت: `
        +r.alts.map(a=>pill(a.name.replace(/_/g,' '),COLORS[a.name]||'#888')).join(' ')
        +`</div>`
    : '';

  document.getElementById('result-inner').innerHTML =
    `<div class="summary ok">✅ ڕاستەوخۆ — گۆڕین پێویست نیە</div>`+
    `<div class="steps">`+
      step('🚶',
        `پێویستە <strong>${{r.walkO_m}} م</strong> بە پێ بڕۆی`,
        `بڕۆ بۆ شەقامی بەسی <strong>${{r.labelO}}</strong> `+altHtml)+
      step('🚌',
        `دەست ڕاگرە لە پاسەکە`,
        `شوفێر دەوەستێت ئەگەر ڕێگا هەبێت`)+
      step('🟢',
        `سەر پاسەکە بکەوە بە تاوەکو خاڵی سەوز لەسەر نەخشەکە`,
        `کاتێک گەیشتیت بە ناوچەکە، بڵێ:`)+
      step('🗣️',
        `بڵێ: <em>"دابەزین هەیە"</em>`,
        `ناوی شوێنەکە بڵێ یان بیشارەوە لەسەر نەخشەکە`)+
      step('🚶',
        `پێویستە <strong>${{r.walkD_m}} م</strong> بە پێ بڕۆی بۆ مەوداکەت`,
        `گەیشتیت!`)+
    `</div>`;
  document.getElementById('result-card').classList.add('show');
}}

function showTransfer(r) {{
  const xferLine = r.sameRoad
    ? `هەمان شەقام — پیاسەکردن پێویست نیە`
    : `پێویستە <strong>${{r.xferWalk_m}} م</strong> بە پێ بڕۆی بۆ شەقامی <strong>${{r.viaBazaar?'پاسی دواتر':r.labelD}}</strong>`;

  // At terminal endpoints (Bazaar) the bus stops by default — no need to ask
  const transferInstruction = r.viaBazaar
    ? `پاسەکە لە بازاڕ دەوەستێت بە خۆی`
    : `بڵێ: <em>"دابەزین هەیە"</em> — لە شەقامی ${{r.labelD}}`;

  const dropSub = r.viaBazaar
    ? `🟡 خاڵی زەرد = دابەزین لە بازاڕ — دەوەستێت بە خۆی`
    : `🟡 خاڵی زەرد = شوێنی دابەزین`;

  const boardSub = r.viaBazaar
    ? `🔵 خاڵی شین = سەر پاسی ${{r.labelD}} کەوە لە بازاڕ`
    : `🔵 خاڵی شین = شوێنی سەرکەوتن لە ${{r.labelD}}`;

  const header = r.viaBazaar
    ? `🔁 یەک گۆڕین — لە ڕێگای بازاڕ`
    : `🔁 یەک گۆڕین — لە کەنارەی شەقام`;

  document.getElementById('result-inner').innerHTML =
    `<div class="summary xfr">${{header}}</div>`+
    `<div class="steps">`+
      step('🚶',
        `پێویستە <strong>${{r.walkO_m}} م</strong> بە پێ بڕۆی بۆ کنارەی شەقام`,
        `بڕۆ بۆ شەقامی بەسی <strong>${{r.labelO}}</strong> — 🟢 خاڵی سەوز لەسەر نەخشەکە`)+
      step('🚌',
        `دەست ڕاگرە لە پاسەکە`,
        `شوفێر دەوەستێت ئەگەر ڕێگا هەبێت`)+
      step('🟡',
        `سەر پاسەکە بکەوە بە تاوەکو خاڵی زەرد لەسەر نەخشەکە`,
        `کاتێک گەیشتیت بە شوێنی گۆڕین، بڵێ:`)+
      step('🗣️', transferInstruction, dropSub)+
      step('🚶', xferLine, boardSub)+
      step('🚌',
        `دەست ڕاگرە لە پاسەکە — سەر پاسی <strong>${{r.labelD}}</strong> کەوە`,
        `شوفێر دەوەستێت ئەگەر ڕێگا هەبێت`)+
      step('🔵',
        `سەر پاسەکە بکەوە بە تاوەکو خاڵی شین لەسەر نەخشەکە`,
        `کاتێک گەیشتیت بە ناوچەکە، بڵێ:`)+
      step('🗣️',
        `بڵێ: <em>"دابەزین هەیە"</em>`,
        `داوای وەستانی نزیک مەوداکەت بکە`)+
      step('🚶',
        `پێویستە <strong>${{r.walkD_m}} م</strong> بە پێ بڕۆی بۆ مەوداکەت`,
        `گەیشتیت!`)+
    `</div>`;
  document.getElementById('result-card').classList.add('show');
}}

function step(icon, main, sub) {{
  return `<div class="step">`+
    `<span class="si">${{icon}}</span>`+
    `<div class="sb"><div class="sm">${{main}}</div><div class="ss">${{sub}}</div></div>`+
    `</div>`;
}}

function showErr(msg) {{
  document.getElementById('result-inner').innerHTML=`<div class="summary err">⚠️ ${{msg}}</div>`;
  document.getElementById('result-card').classList.add('show');
}}
function hideResult() {{
  clearXferLayers();
  document.getElementById('result-card').classList.remove('show');
  drawRoutes(null);
}}

// Run on load if session already has both points
if(ptO&&ptD) compute();

// ── Mode (pick by clicking map) ───────────────────────────────────────────────
let mode = '';
function toggleMode(m) {{
  mode = (mode===m) ? '' : m;
  document.getElementById('btn-o').classList.toggle('on', mode==='origin');
  document.getElementById('btn-d').classList.toggle('on', mode==='dest');
  map.getContainer().classList.toggle('picking', mode!=='');
}}

map.on('click', e => {{
  if(!mode) return;
  const lat=e.latlng.lat, lon=e.latlng.lng;
  const fmt = lat.toFixed(6)+', '+lon.toFixed(6);
  if(mode==='origin') {{
    ptO={{lat,lon}}; placeO(lat,lon);
    document.getElementById('inp-o').value=fmt;
    postPt('set_origin',lat,lon);
    mode='dest';
    document.getElementById('btn-o').classList.remove('on');
    document.getElementById('btn-d').classList.add('on');
  }} else {{
    ptD={{lat,lon}}; placeD(lat,lon);
    document.getElementById('inp-d').value=fmt;
    postPt('set_destination',lat,lon);
    mode='';
    document.getElementById('btn-d').classList.remove('on');
    map.getContainer().classList.remove('picking');
  }}
  compute();
}});

// ── Manual coordinate input ───────────────────────────────────────────────────
function parseCoord(raw) {{
  // Accept: "35.566340, 45.394819" or "35.566340 45.394819" or "35.566340,45.394819"
  const s = raw.trim().replace(/\s*,\s*/g, ',');
  const parts = s.includes(',') ? s.split(',') : s.split(/\s+/);
  if(parts.length<2) return null;
  const la=parseFloat(parts[0]), lo=parseFloat(parts[1]);
  return (isNaN(la)||isNaN(lo)) ? null : {{lat:la,lon:lo}};
}}

function onCoordInput(which, val) {{
  // Try to parse on every keystroke — fire when we have a valid coord
  const c = parseCoord(val);
  if(!c) return;
  if(which==='origin') {{
    ptO=c; placeO(c.lat,c.lon);
    map.setView([c.lat,c.lon], map.getZoom()<14?14:map.getZoom());
    postPt('set_origin',c.lat,c.lon);
  }} else {{
    ptD=c; placeD(c.lat,c.lon);
    map.setView([c.lat,c.lon], map.getZoom()<14?14:map.getZoom());
    postPt('set_destination',c.lat,c.lon);
  }}
  compute();
}}

function clearPt(which) {{
  if(which==='origin') {{
    ptO=null; if(mO){{map.removeLayer(mO);mO=null;}}
    document.getElementById('inp-o').value='';
  }} else {{
    ptD=null; if(mD){{map.removeLayer(mD);mD=null;}}
    document.getElementById('inp-d').value='';
  }}
  postPt('clear_'+which);
  hideResult();
}}

function resetAll() {{
  ptO=null; ptD=null;
  if(mO){{map.removeLayer(mO);mO=null;}} if(mD){{map.removeLayer(mD);mD=null;}}
  document.getElementById('inp-o').value='';
  document.getElementById('inp-d').value='';
  mode='';
  document.getElementById('btn-o').classList.remove('on');
  document.getElementById('btn-d').classList.remove('on');
  map.getContainer().classList.remove('picking');
  postPt('reset');
  hideResult();
}}

// Pre-fill inputs if coming from session state
if(INIT_O) document.getElementById('inp-o').value=INIT_O.lat.toFixed(6)+', '+INIT_O.lon.toFixed(6);
if(INIT_D) document.getElementById('inp-d').value=INIT_D.lat.toFixed(6)+', '+INIT_D.lon.toFixed(6);

// ── postMessage to Streamlit (session persistence only) ───────────────────────
function postPt(type,lat,lon) {{
  let v=type;
  if(lat!==undefined) v+=':'+lat.toFixed(6)+'_'+lon.toFixed(6);
  v+='|'+Date.now();
  window.parent.postMessage({{type:'map_action',payload:{{raw:v}}}},'*');
}}

// ── Resize iframe to window height ────────────────────────────────────────────
function resize() {{
  const h = window.innerHeight||900;
  window.parent.postMessage({{type:'resize_map',height:h}},'*');
}}
resize();
window.addEventListener('resize', resize);
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
