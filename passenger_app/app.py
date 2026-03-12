import json
import sys
from pathlib import Path
from typing import Dict, List

import streamlit as st
import streamlit.components.v1 as components

# --- 1. SETUP ---
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

# --- 2. HTML BUILDER ---
def build_map_html(routes_geojson: dict, live_buses: list, supabase_url: str, supabase_key: str) -> str:
    geojson_str  = json.dumps(routes_geojson)
    colors_str   = json.dumps(ROUTE_COLORS)
    buses_str    = json.dumps(live_buses)
    legend_items = json.dumps([{"name": k.replace("_", " "), "color": v} for k, v in ROUTE_COLORS.items()])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:100%; height:100%; background:#080d14; overflow:hidden; font-family:sans-serif; }}
#map {{ width:100%; height:100vh; }}

/* NEW CYAN TARGET BUTTON */
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

.card {{ background:rgba(10,16,26,0.88); backdrop-filter:blur(16px); border:1px solid rgba(255,255,255,0.1); border-radius:14px; color:#e2eaf4; }}
#top-panel {{ position:absolute; top:14px; left:50%; transform:translateX(-50%); z-index:1000; width:min(520px,92vw); padding:12px 14px; display:flex; flex-direction:column; gap:8px; }}
.row {{ display:flex; align-items:center; gap:8px; }}
.pick-btn {{ flex:1; padding:7px; border-radius:8px; border:1.5px solid; font-size:12px; font-weight:700; cursor:pointer; background:transparent; color:#fff; }}
.pick-btn.green {{ border-color:#22c55e; }}
.pick-btn.green.on {{ background:#22c55e; color:#000; }}
.pick-btn.red {{ border-color:#ef4444; }}
.pick-btn.red.on {{ background:#ef4444; color:#fff; }}
.coord-box {{ flex:2; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.13); border-radius:8px; padding:7px; color:#fff; font-size:11px; }}
</style>
</head>
<body>
<div id="map"></div>
<button id="recenter-btn" onclick="useMyLocation()"></button>

<div id="top-panel" class="card">
  <div class="row">
    <button class="pick-btn green" id="btn-o" onclick="setMode('origin')">📍 Origin</button>
    <input class="coord-box" id="inp-o" placeholder="Origin Lat,Lon"/>
  </div>
  <div class="row">
    <button class="pick-btn red" id="btn-d" onclick="setMode('dest')">🏁 Destination</button>
    <input class="coord-box" id="inp-d" placeholder="Dest Lat,Lon"/>
  </div>
</div>

<script>
const map = L.map('map').setView([{DEFAULT_CENTER[0]}, {DEFAULT_CENTER[1]}], {DEFAULT_ZOOM});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

let mode = '';
let ptO = null, ptD = null;

function setMode(m) {{
    mode = m;
    document.getElementById('btn-o').classList.toggle('on', mode==='origin');
    document.getElementById('btn-d').classList.toggle('on', mode==='dest');
}}

map.on('click', e => {{
    if(!mode) return;
    const lat = e.latlng.lat, lon = e.latlng.lng;
    
    if(mode === 'origin') {{
        ptO = {{lat, lon}};
        document.getElementById('inp-o').value = lat.toFixed(5) + "," + lon.toFixed(5);
        // THE AUTO-FLOW: Switch to destination mode automatically
        setMode('dest');
    }} else if(mode === 'dest') {{
        ptD = {{lat, lon}};
        document.getElementById('inp-d').value = lat.toFixed(5) + "," + lon.toFixed(5);
        setMode(''); // End picking
        console.log("Route ready from " + ptO.lat + " to " + ptD.lat);
    }}
}});

function useMyLocation() {{
    navigator.geolocation.getCurrentPosition(pos => {{
        const lat = pos.coords.latitude, lon = pos.coords.longitude;
        ptO = {{lat, lon}};
        document.getElementById('inp-o').value = lat.toFixed(5) + "," + lon.toFixed(5);
        map.setView([lat, lon], 16);
        setMode('dest'); // Auto-switch even after GPS
    }});
}}
</script>
</body>
</html>"""

def main():
    # Placeholder for route loading and live bus fetching
    components.html(build_map_html({{}}, [], "", ""), height=900, scrolling=False)

if __name__ == "__main__":
    main()
