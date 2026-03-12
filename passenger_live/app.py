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
  footer                            { display: none !important; }
  .stDeployButton                   { display: none !important; }
  .block-container { padding:0!important; margin:0!important; max-width:100%!important; }
  div[data-testid="stCustomComponentV1"] { margin:0!important; padding:0!important; line-height:0!important; }
</style>
""", unsafe_allow_html=True)

ROUTES_FILE    = Path(__file__).resolve().parents[1] / "assets" / "bus_lines.geojson"
DEFAULT_CENTER = [35.56, 45.43]
DEFAULT_ZOOM   = 13
MAX_WALK_KM    = 0.70

ROUTE_COLORS: Dict[str, str] = {
    "Bakrajo_Bazar":    "#e41a1c",
    "Chwarchra_Bazar":  "#377eb8",
    "FarmanBaran_Bazar": "#4daf4a",
    "HawaryShar_Bazar":  "#984ea3",
    "Kazywa_Bazar":      "#ff7f00",
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
                .select("bus_line,bus_number,lat,lon,speed_kmh,updated_at,is_active") \
                .eq("is_active", True).execute()
        return res.data or []
    except Exception:
        return []

def build_map_html(routes_geojson: dict, live_buses: list,
                    supabase_url: str, supabase_key: str) -> str:

    geojson_str  = json.dumps(routes_geojson)
    colors_str   = json.dumps(ROUTE_COLORS)
    buses_initial = {b['bus_number']: b for b in live_buses}
    buses_str    = json.dumps(buses_initial)
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

/* UI Panels */
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
.pick-btn.green.on {{ background:#22c55e; color:#000; }}
.pick-btn.red.on {{ background:#ef4444; color:#fff; }}
.coord-box {{
  flex:1; min-width:0; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.13);
  border-radius:8px; padding:7px 10px; font-size:12px; color:#e2eaf4; outline:none; direction:ltr;
}}
.hr {{ height:1px; background:rgba(255,255,255,.08); }}

/* Result Card */
#result-card {{
  position:absolute; z-index:1000; pointer-events:none;
  transition:all .4s cubic-bezier(.34,1.56,.64,1);
}}
#result-card.float {{
  bottom:20px; left:50%; transform:translateX(-50%) translateY(300px);
  width:min(500px,92vw); padding:14px 16px; max-height:60vh; overflow-y:auto;
}}
#result-card.float.show {{ transform:translateX(-50%) translateY(0); pointer-events:all; }}
.summary {{ text-align:center; font-size:14px; font-weight:700; padding:10px 12px; border-radius:10px; margin-bottom:10px; }}
.summary.ok  {{ background:rgba(34,197,94,.12);  border:1px solid rgba(34,197,94,.28);  color:#86efac; }}
.summary.err {{ background:rgba(239,68,68,.12);  border:1px solid rgba(239,68,68,.28);  color:#fca5a5; }}

/* Legend & Buttons */
#recenter-btn, #home-btn {{
  position: absolute; right: 20px; z-index: 1001;
  width: 50px; height: 50px; border-radius: 12px; background: #000;
  border: 1px solid rgba(255,255,255,0.2); cursor: pointer;
}}
#recenter-btn {{ bottom: 110px; }}
#home-btn {{ bottom: 170px; }}

.leg {{ border-radius:12px; background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.08); margin-bottom:5px; }}
.leg-top {{ display:flex; align-items:center; gap:8px; padding:12px; }}
.leg-label {{ flex:1; font-size:13px; color:#e2eaf4; direction:rtl; }}
.eta-badge {{ background: #22c55e; color: #000; font-weight: 800; padding: 2px 6px; border-radius: 4px; font-size: 11px; }}

#live-badge {{
  position:absolute; bottom:20px; right:14px; z-index:1000;
  padding:5px 13px; border-radius:20px; font-size:11px; color:#4ade80;
  border:1px solid rgba(34,197,94,.3); background:rgba(10,16,26,.88);
}}
.ld-dot {{ display:inline-block; width:7px; height:7px; border-radius:50%; background:#22c55e; margin-left:6px; animation:blink 1.4s infinite; }}
@keyframes blink {{ 0%,100%{{opacity:1;}} 50%{{opacity:.2;}} }}
</style>
</head>
<body>
<div id="map"></div>
<button id="home-btn" onclick="goDefaultView()"></button>
<button id="recenter-btn" onclick="useMyLocation()"></button>

<div id="top-panel" class="card" dir="rtl" lang="ckb">
  <div class="row">
    <span class="dot" style="background:#22c55e"></span>
    <button class="pick-btn green" id="btn-o" onclick="toggleMode('origin')">هەڵبژێرە</button>
    <input class="coord-box" id="inp-o" placeholder="بنکە"/>
    <button onclick="clearPt('origin')">✕</button>
  </div>
  <div class="hr"></div>
  <div class="row">
    <span class="dot" style="background:#ef4444"></span>
    <button class="pick-btn red" id="btn-d" onclick="toggleMode('dest')">هەڵبژێرە</button>
    <input class="coord-box" id="inp-d" placeholder="مەودا"/>
    <button onclick="clearPt('dest')">✕</button>
  </div>
</div>

<div id="result-card" class="card float" dir="rtl" lang="ckb">
  <div id="result-inner"></div>
</div>

<div id="live-badge" dir="rtl" lang="ckb"><span class="ld-dot"></span><span id="bus-ct">٠ بەس</span></div>

<script>
const COLORS   = {colors_str};
const GEOJSON  = {geojson_str};
const BUSES    = {buses_str}; // This is now an object mapping number -> bus
let BUSES_BY_LINE = {{}};

const map = L.map('map', {{
  center: [{DEFAULT_CENTER[0]}, {DEFAULT_CENTER[1]}],
  zoom: {DEFAULT_ZOOM}
}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

// --- Realtime Lookup Logic ---
function updateBusLookup() {{
    BUSES_BY_LINE = {{}};
    Object.values(BUSES).forEach(b => {{
        if (b.is_active) {{
            if (!BUSES_BY_LINE[b.bus_line]) BUSES_BY_LINE[b.bus_line] = [];
            BUSES_BY_LINE[b.bus_line].push(b);
        }}
    }});
    document.getElementById('bus-ct').textContent = Object.keys(busM).length + ' بەس زیندوو';
}}

// --- Markers Management ---
const busM = {{}};
function busIcon(color, num) {{
  return L.divIcon({{
    html: `<div style="background:${{color}};color:#fff;font-size:9px;font-weight:700;padding:3px 7px;border-radius:6px;border:2px solid #fff;">${{num}}</div>`,
    className:'', iconAnchor:[20,12]
  }});
}}

function placeBus(b) {{
  const c = COLORS[b.bus_line] || '#00d4ff';
  if(busM[b.bus_number]) {{
    busM[b.bus_number].setLatLng([b.lat,b.lon]);
  }} else {{
    busM[b.bus_number] = L.marker([b.lat,b.lon], {{icon:busIcon(c,b.bus_number)}}).addTo(map);
  }}
}}

// Initialize
Object.values(BUSES).forEach(placeBus);
updateBusLookup();

// Supabase Listener
if ("{supabase_url}" && "{supabase_key}") {{
  const sb = supabase.createClient("{supabase_url}", "{supabase_key}");
  sb.channel('buses').on('postgres_changes', {{event:'*', schema:'public', table:'active_locations'}}, p => {{
      const b = p.new; if(!b) return;
      if(b.is_active) {{
          BUSES[b.bus_number] = b;
          placeBus(b);
      }} else if(busM[b.bus_number]) {{
          map.removeLayer(busM[b.bus_number]);
          delete busM[b.bus_number];
          delete BUSES[b.bus_number];
      }}
      updateBusLookup();
      // If result card is showing, re-compute to update ETAs live
      if(ptO && ptD) compute(); 
  }}).subscribe();
}}

// --- Routing Engine ---
function hav(la1, lo1, la2, lo2) {{
  const R = 6371, r = Math.PI / 180;
  const dla = (la2 - la1) * r, dlo = (lo2 - lo1) * r;
  const a = Math.sin(dla/2)**2 + Math.cos(la1*r) * Math.cos(la2*r) * Math.sin(dlo/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}}

const ROUTE_PTS = {{}};
GEOJSON.features.forEach(f => {{
    const name = f.properties.layer;
    if(!ROUTE_PTS[name]) ROUTE_PTS[name] = [];
    const coords = f.geometry.type === 'LineString' ? [f.geometry.coordinates] : f.geometry.coordinates;
    coords.forEach(seg => seg.forEach(c => ROUTE_PTS[name].push({{lat:c[1], lon:c[0]}})));
}});

function calculateETA(uLat, uLon, lineName) {{
    const buses = BUSES_BY_LINE[lineName] || [];
    if (buses.length === 0) return null;
    let minD = Infinity;
    buses.forEach(b => {{
        const d = hav(uLat, uLon, b.lat, b.lon);
        if (d < minD) minD = d;
    }});
    const mins = Math.round((minD / 25) * 60);
    return mins < 1 ? "خەریکە دەگات" : mins + " خولەک";
}}

function compute() {{
    if(!ptO || !ptD) return;
    
    // Check for direct routes
    const atO = [];
    for(let name in ROUTE_PTS) {{
        let best = Infinity, bestPt = null;
        ROUTE_PTS[name].forEach(p => {{
            const d = hav(ptO.lat, ptO.lon, p.lat, p.lon);
            if(d < best) {{ best = d; bestPt = p; }}
        }});
        if(best <= {MAX_WALK_KM}) atO.push({{name, km:best, pt:bestPt}});
    }}

    const atD = [];
    for(let name in ROUTE_PTS) {{
        let best = Infinity;
        ROUTE_PTS[name].forEach(p => {{
            const d = hav(ptD.lat, ptD.lon, p.lat, p.lon);
            if(d < best) best = d;
        }});
        if(best <= {MAX_WALK_KM}) atD.push({{name, km:best}});
    }}

    const directs = atO.filter(o => atD.some(d => d.name === o.name));
    
    // --- LIVE FILTERING ---
    const liveDirects = directs.filter(d => BUSES_BY_LINE[d.name] && BUSES_BY_LINE[d.name].length > 0);

    if (directs.length > 0 && liveDirects.length === 0) {{
        showErr("هیچ بەسێک لەم هێڵەدا ئێستا ئیش ناکات");
        return;
    }}

    if (liveDirects.length > 0) {{
        showDirect(liveDirects[0]);
    }} else {{
        showErr("هیچ ڕێگایەکی ڕاستەوخۆ نییە یان بەسەکان وەستاون");
    }}
}}

function showDirect(r) {{
    const eta = calculateETA(ptO.lat, ptO.lon, r.name);
    const color = COLORS[r.name];
    document.getElementById('result-inner').innerHTML = `
        <div class="summary ok">هێڵی ڕاستەوخۆ دۆزرایەوە</div>
        <div class="leg">
            <div class="leg-top">
                <span class="eta-badge">${{eta}}</span>
                <div class="leg-label">هێڵی <strong>${{r.name.replace(/_/g,' ')}}</strong></div>
                <div style="width:12px;height:12px;border-radius:50%;background:${{color}}"></div>
            </div>
            <div style="padding:0 12px 12px; font-size:12px; color:#aaa;">
                دووری تا پاسەکە: ${{Math.round(r.km * 1000)}} مەتر پیاسە
            </div>
        </div>
    `;
    document.getElementById('result-card').classList.add('show');
}}

function showErr(msg) {{
    document.getElementById('result-inner').innerHTML = `<div class="summary err">${{msg}}</div>`;
    document.getElementById('result-card').classList.add('show');
}}

// --- UI Interaction (Simplified for brevity, same as your logic) ---
let ptO = null, ptD = null, mode = '';
function toggleMode(m) {{ mode = m; }}
map.on('click', e => {{
    if(!mode) return;
    if(mode==='origin') {{ ptO = e.latlng; document.getElementById('inp-o').value = e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5); mode='dest'; }}
    else {{ ptD = e.latlng; document.getElementById('inp-d').value = e.latlng.lat.toFixed(5)+','+e.latlng.lng.toFixed(5); mode=''; compute(); }}
}});
function goDefaultView() {{ map.setView([{DEFAULT_CENTER[0]}, {DEFAULT_CENTER[1]}], {DEFAULT_ZOOM}); }}
function clearPt(w) {{ if(w==='origin') ptO=null; else ptD=null; document.getElementById('result-card').classList.remove('show'); }}
</script>
</body>
</html>"""

def main():
    try:
        routes_geojson = load_routes(ROUTES_FILE)
    except Exception as e:
        st.error(f"Failed to load route file: {e}")
        return

    live_buses = fetch_live_buses()
    supa_url = st.secrets.get("SUPABASE_URL", "") if hasattr(st, "secrets") else ""
    supa_key = st.secrets.get("SUPABASE_ANON_KEY", "") if hasattr(st, "secrets") else ""

    components.html(
        build_map_html(routes_geojson, live_buses, supa_url, supa_key),
        height=900,
        scrolling=False
    )

if __name__ == "__main__":
    main()
