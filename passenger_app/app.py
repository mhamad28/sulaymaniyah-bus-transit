import json
import sys
from pathlib import Path
from typing import Dict, List

import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parents[1] / "shared"))
try:
    from supabase_client import get_supabase
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False

st.set_page_config(page_title="Suly Transit", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  header[data-testid="stHeader"]   { display: none !important; }
  section[data-testid="stSidebar"] { display: none !important; }
  footer                           { display: none !important; }
  .stDeployButton                  { display: none !important; }
  .block-container { padding:0!important; margin:0!important; max-width:100%!important; }
  div[data-testid="stCustomComponentV1"] { margin:0!important; padding:0!important; line-height:0!important; }
</style>
""", unsafe_allow_html=True)

ROUTES_FILE    = Path(__file__).resolve().parents[1] / "assets" / "bus_lines.geojson"
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

@st.cache_data(hash_funcs={Path: lambda p: p.stat().st_mtime if p.exists() else 0})
def load_routes(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing route file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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

def build_map_html(routes_geojson: dict, live_buses: list,
                   supabase_url: str, supabase_key: str) -> str:

    geojson_str  = json.dumps(routes_geojson)
    colors_str   = json.dumps(ROUTE_COLORS)
    buses_str    = json.dumps(live_buses)
    legend_items = json.dumps([
        {"name": k.replace("_", " "), "color": v} for k, v in ROUTE_COLORS.items()
    ])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Naskh+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:100%; height:100%; background:#080d14; overflow:hidden;
  font-family:'Noto Naskh Arabic',system-ui,sans-serif; }}
#map {{ width:100%; height:100vh; }}

.card {{
  background:rgba(10,16,26,0.88); backdrop-filter:blur(16px);
  border:1px solid rgba(255,255,255,0.10); border-radius:14px;
  box-shadow:0 8px 32px rgba(0,0,0,0.5); color:#e2eaf4;
}}

/* RECENTER BUTTON (NEW TARGET STYLE) */
#recenter-btn {{
  position: absolute; bottom: 110px; right: 20px; z-index: 1001;
  width: 50px; height: 50px; border-radius: 12px; background: #000000; 
  border: 1px solid rgba(255,255,255,0.2); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 15px rgba(0,0,0,0.5); transition: all 0.2s;
}}
#recenter-btn::before {{
  content: ""; width: 28px; height: 28px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2300E5FF' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='3' fill='%2300E5FF'/%3E%3Ccircle cx='12' cy='12' r='7'/%3E%3Cline x1='12' y1='1' x2='12' y2='5'/%3E%3Cline x1='12' y1='19' x2='12' y2='23'/%3E%3Cline x1='1' y1='12' x2='5' y2='12'/%3E%3Cline x1='19' y1='12' x2='23' y2='12'/%3E%3C/svg%3E");
  background-size: contain; background-repeat: no-repeat;
}}

/* TOP PANEL */
#top-panel {{
  position:absolute; top:14px; left:50%; transform:translateX(-50%);
  z-index:1000; width:min(520px,92vw); padding:12px 14px;
  display:flex; flex-direction:column; gap:8px;
}}
.row {{ display:flex; align-items:center; gap:8px; }}
.dot {{ width:11px; height:11px; border-radius:50%; flex-shrink:0; border:2px solid rgba(255,255,255,.5); }}
.pick-btn {{
  flex-shrink:0; padding:6px 13px; border-radius:8px; border:1.5px solid;
  font-size:12px; font-weight:700; cursor:pointer; background:transparent;
  transition:all .15s; white-space:nowrap; font-family:'Noto Naskh Arabic',sans-serif;
}}
.pick-btn.green {{ border-color:#22c55e; color:#4ade80; }}
.pick-btn.green.on {{ background:#22c55e; color:#000; }}
.pick-btn.red {{ border-color:#ef4444; color:#f87171; }}
.pick-btn.red.on {{ background:#ef4444; color:#fff; }}

.coord-box {{
  flex:1; min-width:0; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.13);
  border-radius:8px; padding:7px 10px; font-size:12px; font-family:monospace;
  color:#e2eaf4; outline:none; transition:border-color .15s; direction:ltr;
}}
.x-btn {{
  flex-shrink:0; width:24px; height:24px; border-radius:50%;
  border:1px solid rgba(255,255,255,.15); background:rgba(255,255,255,.06);
  color:#64748b; font-size:12px; cursor:pointer; line-height:1; transition:all .15s;
}}
.reset-btn {{
  background:transparent; border:1px solid rgba(148,163,184,.3);
  border-radius:7px; color:#94a3b8; font-size:11px; font-weight:600;
  padding:4px 14px; cursor:pointer; margin-left:auto; transition:all .15s;
}}

/* RESULT CARD */
#result-card {{ position:absolute; z-index:1000; pointer-events:none; transition:all .4s cubic-bezier(.34,1.56,.64,1); }}
#result-card.float {{ bottom:20px; left:50%; transform:translateX(-50%) translateY(300px); width:min(460px,92vw); padding:14px 16px; max-height:60vh; overflow-y:auto; }}
#result-card.float.show {{ transform:translateX(-50%) translateY(0); pointer-events:all; }}
#result-toggle {{ position:absolute; top:8px; left:10px; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.15); border-radius:6px; color:#94a3b8; font-size:11px; font-weight:600; padding:3px 8px; cursor:pointer; z-index:10; display:flex; align-items:center; gap:4px; }}
.summary {{ text-align:center; font-size:13px; font-weight:700; padding:7px 12px; border-radius:8px; margin-bottom:10px; }}
.summary.ok  {{ background:rgba(34,197,94,.15); color:#4ade80; }}
.summary.xfr {{ background:rgba(251,191,36,.13); color:#fbbf24; }}
.summary.err {{ background:rgba(239,68,68,.13); color:#f87171; }}

/* LEG CARDS */
.legs {{ display:flex; flex-direction:column; gap:5px; }}
.leg {{ border-radius:10px; overflow:hidden; background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.08); cursor:pointer; }}
.leg-top {{ display:flex; align-items:center; gap:8px; padding:10px 12px; }}
.leg-chips {{ display:flex; align-items:center; gap:4px; }}
.leg-chip {{ font-size:11px; font-weight:700; padding:3px 9px; border-radius:20px; border:1.5px solid; white-space:nowrap; }}
.leg-chip.walk {{ background:rgba(148,163,184,.1); border-color:rgba(148,163,184,.3); color:#94a3b8; }}
.leg-label {{ flex:1; font-size:12px; color:#e2eaf4; font-weight:500; direction:rtl; }}

/* LEGEND */
#leg-btn {{ position:absolute; top:14px; right:14px; z-index:1001; width:38px; height:38px; border-radius:10px; background:rgba(10,16,26,.88); border:1px solid rgba(255,255,255,.10); color:#e2eaf4; font-size:18px; cursor:pointer; display:flex; align-items:center; justify-content:center; }}
#leg-panel {{ position:absolute; top:60px; right:14px; z-index:1000; width:190px; max-height:55vh; overflow-y:auto; padding:10px 12px; display:none; flex-direction:column; gap:5px; }}
#leg-panel.open {{ display:flex; }}
.li {{ display:flex; align-items:center; gap:7px; font-size:12px; color:#e2eaf4; }}
.ld {{ width:9px; height:9px; border-radius:50%; }}

/* LIVE BADGE */
#live-badge {{ position:absolute; bottom:20px; right:14px; z-index:1000; padding:5px 13px; border-radius:20px; font-size:11px; font-weight:600; color:#4ade80; background:rgba(10,16,26,.88); border:1px solid rgba(34,197,94,.3); display:flex; align-items:center; gap:6px; }}
.ld-dot {{ width:7px; height:7px; border-radius:50%; background:#22c55e; animation:blink 1.4s infinite; }}
@keyframes blink {{ 0%,100%{{opacity:1;}} 50%{{opacity:.2;}} }}
</style>
</head>
<body>
<div id="map"></div>
<button id="recenter-btn" onclick="useMyLocation()"></button>

<div id="top-panel" class="card" dir="rtl">
  <div class="row">
    <span class="dot" style="background:#22c55e"></span>
    <button class="pick-btn green" id="btn-o" onclick="toggleMode('origin')">📍 هەڵبژێرە</button>
    <input class="coord-box" id="inp-o" placeholder="بنکە" oninput="onCoordInput('origin', this.value)"/>
    <button class="x-btn" onclick="clearPt('origin')">✕</button>
  </div>
  <div class="row">
    <span class="dot" style="background:#ef4444"></span>
    <button class="pick-btn red" id="btn-d" onclick="toggleMode('dest')">🏁 هەڵبژێرە</button>
    <input class="coord-box" id="inp-d" placeholder="مەودا" oninput="onCoordInput('dest', this.value)"/>
    <button class="x-btn" onclick="clearPt('dest')">✕</button>
  </div>
  <div class="row"><button class="reset-btn" onclick="resetAll()">↺ ڕەستکردنەوە</button></div>
</div>

<button id="leg-btn" onclick="toggleLeg()">🗺</button>
<div id="leg-panel" class="card"></div>

<div id="result-card" class="card float" dir="rtl">
  <div id="result-inner"></div>
</div>

<div id="live-badge" dir="rtl"><span class="ld-dot"></span><span id="bus-ct">٠ بەس</span></div>

<script>
const COLORS   = {colors_str};
const GEOJSON  = {geojson_str};
const LEGEND   = {legend_items};
const BUSES    = {buses_str};
const MAX_WALK = {MAX_WALK_KM};

const map = L.map('map', {{ center: [{DEFAULT_CENTER[0]}, {DEFAULT_CENTER[1]}], zoom: {DEFAULT_ZOOM}, minZoom: 10 }});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

// ── Draw Routes (Original) ──
let routeLayer = L.geoJSON(GEOJSON, {{
    style: f => ({{ color: COLORS[f.properties.layer] || '#3388ff', weight: 4, opacity: 0.88 }}),
    onEachFeature: (f,l) => l.bindTooltip(f.properties.layer || 'Route')
}}).addTo(map);

// ── Legend ──
const legPanel = document.getElementById('leg-panel');
LEGEND.forEach(item => {{
    const d = document.createElement('div'); d.className = 'li';
    d.innerHTML = `<span class="ld" style="background:${{item.color}}"></span>${{item.name}}`;
    legPanel.appendChild(d);
}});
function toggleLeg() {{ legPanel.classList.toggle('open'); }}

// ── Routing Helpers (Original Pure JS) ──
const ROUTE_PTS = {{}};
GEOJSON.features.forEach(f => {{
    const name = f.properties.layer; if(!name) return;
    if(!ROUTE_PTS[name]) ROUTE_PTS[name] = [];
    const coords = f.geometry.type === 'LineString' ? [f.geometry.coordinates] : f.geometry.coordinates;
    coords.forEach(seg => seg.forEach(c => ROUTE_PTS[name].push({{lat:c[1], lon:c[0]}})));
}});

function hav(la1,lo1,la2,lo2) {{
    const R=6371, r=Math.PI/180;
    const a = Math.sin((la2-la1)*r/2)**2 + Math.cos(la1*r)*Math.cos(la2*r)*Math.sin((lo2-lo1)*r/2)**2;
    return R*2*Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}}

function nearbyRoutes(lat, lon) {{
    const out = [];
    Object.keys(ROUTE_PTS).forEach(name => {{
        let best = Infinity, pt = null;
        ROUTE_PTS[name].forEach(p => {{ const d = hav(lat,lon,p.lat,p.lon); if(d<best) {{best=d; pt=p;}} }});
        if(best <= MAX_WALK) out.push({{ name, km: best, boardPt: pt }});
    }});
    return out.sort((a,b) => a.km - b.km);
}}

// ── Interaction Logic ──
let ptO = null, ptD = null, mode = '', mO = null, mD = null;

function toggleMode(m) {{
    mode = (mode === m) ? '' : m;
    document.getElementById('btn-o').classList.toggle('on', mode === 'origin');
    document.getElementById('btn-d').classList.toggle('on', mode === 'dest');
}}

map.on('click', e => {{
    if(!mode) return;
    const lat = e.latlng.lat, lon = e.latlng.lng;
    if(mode === 'origin') {{
        ptO = {{lat, lon}}; placeO(lat,lon);
        document.getElementById('inp-o').value = lat.toFixed(5)+","+lon.toFixed(5);
        toggleMode('dest'); // AUTO-FLOW
    }} else {{
        ptD = {{lat, lon}}; placeD(lat,lon);
        document.getElementById('inp-d').value = lat.toFixed(5)+","+lon.toFixed(5);
        toggleMode(''); compute();
    }}
}});

function useMyLocation() {{
    navigator.geolocation.getCurrentPosition(pos => {{
        const lat = pos.coords.latitude, lon = pos.coords.longitude;
        ptO = {{lat, lon}}; placeO(lat,lon);
        document.getElementById('inp-o').value = lat.toFixed(5)+","+lon.toFixed(5);
        map.setView([lat,lon], 16);
        toggleMode('dest'); // AUTO-FLOW
    }});
}}

function placeO(lat, lon) {{ if(mO) map.removeLayer(mO); mO = L.circleMarker([lat,lon], {{radius:8, color:'#22c55e', fillOpacity:1}}).addTo(map); }}
function placeD(lat, lon) {{ if(mD) map.removeLayer(mD); mD = L.circleMarker([lat,lon], {{radius:8, color:'#ef4444', fillOpacity:1}}).addTo(map); }}

function compute() {{
    const atO = nearbyRoutes(ptO.lat, ptO.lon);
    const atD = nearbyRoutes(ptD.lat, ptD.lon);
    if(!atO.length || !atD.length) {{ document.getElementById('result-inner').innerHTML = '<div class="summary err">هیچ هێڵێک نەدۆزرایەوە</div>'; }}
    else {{
        const line = atO[0].name;
        document.getElementById('result-inner').innerHTML = `<div class="summary ok">✅ هێڵی دۆزراوە: ${{line.replace(/_/g,' ')}}</div>`;
    }}
    document.getElementById('result-card').classList.add('show');
}}

function clearPt(w) {{ if(w==='origin') {{ptO=null; if(mO)map.removeLayer(mO);}} else {{ptD=null; if(mD)map.removeLayer(mD);}} }}
function resetAll() {{ location.reload(); }}
</script>
</body>
</html>"""

def main():
    routes = load_routes(ROUTES_FILE)
    live = fetch_live_buses()
    components.html(build_map_html(routes, live, "", ""), height=900)

if __name__ == "__main__":
    main()
