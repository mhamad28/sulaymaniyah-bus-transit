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
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:100%; height:100%; background:#080d14; overflow:hidden;
  font-family: system-ui, sans-serif; }}
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
}}
.coord-box::placeholder {{ color:#475569; }}
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
<div id="top-panel" class="card">
  <div class="row">
    <span class="dot" style="background:#22c55e"></span>
    <button class="pick-btn green" id="btn-o" onclick="toggleMode('origin')">📍 Pick</button>
    <input class="coord-box" id="inp-o" placeholder="Origin — paste lat, lon from Google Maps"
           oninput="onCoordInput('origin', this.value)"/>
    <button class="x-btn" onclick="clearPt('origin')">✕</button>
  </div>
  <div class="hr"></div>
  <div class="row">
    <span class="dot" style="background:#ef4444"></span>
    <button class="pick-btn red" id="btn-d" onclick="toggleMode('dest')">🏁 Pick</button>
    <input class="coord-box" id="inp-d" placeholder="Destination — paste lat, lon from Google Maps"
           oninput="onCoordInput('dest', this.value)"/>
    <button class="x-btn" onclick="clearPt('dest')">✕</button>
  </div>
  <div class="hr"></div>
  <div class="row"><button class="reset-btn" onclick="resetAll()">↺ Reset</button></div>
</div>

<!-- LEGEND -->
<button id="leg-btn" onclick="toggleLeg()">🗺</button>
<div id="leg-panel" class="card">
  <div style="font-size:9px;font-weight:700;letter-spacing:.12em;color:#475569;
    text-transform:uppercase;margin-bottom:4px;">Bus Lines</div>
</div>

<!-- RESULT -->
<div id="result-card" class="card"><div id="result-inner"></div></div>

<!-- LIVE BADGE -->
<div id="live-badge"><span class="ld-dot"></span><span id="bus-ct">0 buses</span></div>

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
  document.getElementById('bus-ct').textContent=Object.keys(busM).length+' bus'+(Object.keys(busM).length!==1?'es':'')+' live';
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

// ── Routing (fully in JS) ─────────────────────────────────────────────────────
const PTS = [];
for (const f of GEOJSON.features||[]) {{
  const name = (f.properties&&f.properties.layer)||'';
  const geom = f.geometry||{{}};
  const lines = geom.type==='LineString' ? [geom.coordinates]
              : geom.type==='MultiLineString' ? geom.coordinates : [];
  for (const line of lines)
    for (const c of line)
      if(Array.isArray(c)&&c.length>=2) PTS.push({{lat:c[1],lon:c[0],name}});
}}

function hav(la1,lo1,la2,lo2) {{
  const R=6371, d2r=Math.PI/180;
  const dLa=(la2-la1)*d2r, dLo=(lo2-lo1)*d2r;
  const a=Math.sin(dLa/2)**2+Math.cos(la1*d2r)*Math.cos(la2*d2r)*Math.sin(dLo/2)**2;
  return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

function nearest(lat,lon) {{
  let best=null, bd=Infinity;
  for(const p of PTS) {{ const d=hav(lat,lon,p.lat,p.lon); if(d<bd){{bd=d;best=p;}} }}
  return best ? {{name:best.name, km:bd}} : null;
}}

// State
let ptO = INIT_O ? {{lat:INIT_O.lat,lon:INIT_O.lon}} : null;
let ptD = INIT_D ? {{lat:INIT_D.lat,lon:INIT_D.lon}} : null;

function compute() {{
  if(!ptO||!ptD) {{ hideResult(); return; }}
  const nO=nearest(ptO.lat,ptO.lon);
  const nD=nearest(ptD.lat,ptD.lon);
  if(!nO||!nD) {{ showErr('Could not match any route.'); return; }}
  if(nO.km>MAX_WALK) {{ showErr('Origin is '+Math.round(nO.km*1000)+' m from nearest route — too far (max '+Math.round(MAX_WALK*1000)+' m).'); return; }}
  if(nD.km>MAX_WALK) {{ showErr('Destination is '+Math.round(nD.km*1000)+' m from nearest route — too far (max '+Math.round(MAX_WALK*1000)+' m).'); return; }}

  const same = nO.name===nD.name;
  const cO=COLORS[nO.name]||'#888', cD=COLORS[nD.name]||'#888';
  const lO=nO.name.replace(/_/g,' '), lD=nD.name.replace(/_/g,' ');
  drawRoutes(new Set(same?[nO.name]:[nO.name,nD.name]));

  const pill=(label,color)=>`<span class="pill" style="background:${{color}}22;color:${{color}};border:1px solid ${{color}}55">${{label}}</span>`;

  const steps = [
    `<div class="step"><span class="si">🚶</span><div class="sb">
      <div class="sm">Walk <strong>${{Math.round(nO.km*1000)}} m</strong> to the nearest stop</div>
      <div class="ss">to board ${{pill(lO,cO)}}</div></div></div>`,
    `<div class="step"><span class="si">🚌</span><div class="sb">
      <div class="sm">Board ${{pill(lO,cO)}}</div>
      <div class="ss">${{same?'Ride directly to your stop':'Ride to the transfer stop'}}</div></div></div>`,
  ];
  if(!same) steps.push(
    `<div class="step"><span class="si">🔁</span><div class="sb">
      <div class="sm">Transfer to ${{pill(lD,cD)}}</div>
      <div class="ss">where the two routes intersect</div></div></div>`);
  steps.push(
    `<div class="step"><span class="si">📍</span><div class="sb">
      <div class="sm">Walk <strong>${{Math.round(nD.km*1000)}} m</strong> to your destination</div>
      <div class="ss">You've arrived!</div></div></div>`);

  document.getElementById('result-inner').innerHTML =
    `<div class="summary ${{same?'ok':'xfr'}}">${{same?'✅ Direct — no transfer needed':'🔁 1 transfer required'}}</div>`+
    `<div class="steps">${{steps.join('')}}</div>`;
  document.getElementById('result-card').classList.add('show');
}}

function showErr(msg) {{
  document.getElementById('result-inner').innerHTML=`<div class="summary err">⚠️ ${{msg}}</div>`;
  document.getElementById('result-card').classList.add('show');
}}
function hideResult() {{
  document.getElementById('result-card').classList.remove('show');
  drawRoutes(null);
}}

// Run on load if both already set (page reload)
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
