import json
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# --- 1. SETUP & CONFIG ---
st.set_page_config(page_title="Suly Transit – Driver", layout="wide", initial_sidebar_state="collapsed")

# Hide Streamlit UI elements for full-screen map experience
st.markdown("""
<style>
  header[data-testid="stHeader"]   { display:none!important; }
  section[data-testid="stSidebar"] { display:none!important; }
  footer                           { display:none!important; }
  .block-container { padding:0!important; margin:0!important; max-width:100%!important; }
  div[data-testid="stCustomComponentV1"] { margin:0!important; padding:0!important; line-height:0!important; }
</style>
""", unsafe_allow_html=True)

SUPA_URL = st.secrets.get("SUPABASE_URL", "")
SUPA_KEY = st.secrets.get("SUPABASE_ANON_KEY", "")

ROUTE_COLORS = {
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
LINE_NAMES = list(ROUTE_COLORS.keys())

# --- 2. HTML/JS/CSS BUILDER ---
def build_html(supa_url, supa_key, line_names, route_colors):
    lines_json  = json.dumps(line_names)
    colors_json = json.dumps(route_colors)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{width:100%;height:100%;background:#080d14;overflow:hidden;font-family:sans-serif;}}
#map{{width:100%;height:100vh;}}

.glass{{
  background:rgba(10,16,26,.92);backdrop-filter:blur(18px);
  border:1px solid rgba(255,255,255,.10);border-radius:16px;
  box-shadow:0 8px 32px rgba(0,0,0,.55);color:#e2eaf4;
}}

/* RECENTER BUTTON */
.gps-fab {{
  position:absolute; bottom:100px; right:20px; z-index:1001;
  width:50px; height:50px; border-radius:50%; background:#22c55e;
  border:2px solid #fff; color:white; font-size:22px; cursor:pointer;
  display:none; align-items:center; justify-content:center;
  box-shadow:0 4px 15px rgba(0,0,0,0.4); transition: transform 0.2s;
}}
.gps-fab:active {{ transform: scale(0.9); }}

/* OTHER UI ELEMENTS */
#login-screen{{position:absolute;inset:0;z-index:2000;display:flex;align-items:center;justify-content:center;background:rgba(8,13,20,.96);}}
#login-card{{width:min(380px,90vw);padding:28px 24px;display:flex;flex-direction:column;gap:16px;}}
.inp, .sel {{width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.13);border-radius:10px;padding:12px;color:#fff;}}
.go-btn{{width:100%;padding:14px;border-radius:10px;border:none;background:#22c55e;color:#fff;font-weight:700;cursor:pointer;}}
#status-bar{{position:absolute;top:14px;left:50%;transform:translateX(-50%);z-index:1000;width:92%;padding:10px;display:none;align-items:center;gap:10px;}}
#stats-strip{{position:absolute;bottom:20px;left:50%;transform:translateX(-50%);z-index:1000;width:92%;padding:10px;display:none;flex-direction:row;}}
.stat{{flex:1;text-align:center;border-right:1px solid rgba(255,255,255,.1);}}
.stat:last-child{{border-right:none;}}
.sv{{font-size:20px;font-weight:700;}}
.sl{{font-size:10px;color:#64748b;}}
</style>
</head>
<body>
<div id="map"></div>

<button class="gps-fab" id="recenter-btn" onclick="recenterMap()">🎯</button>

<div id="login-screen">
  <div id="login-card" class="glass">
    <h2 style="text-align:center">🚌 Suly Transit</h2>
    <input class="inp" id="inp-plate" placeholder="Plate Number"/>
    <input class="inp" id="inp-name" placeholder="Driver Name"/>
    <select class="sel" id="sel-line"><option value="">Select Line</option></select>
    <button class="go-btn" id="go-btn" onclick="startSession()">Start Shift</button>
  </div>
</div>

<div id="status-bar" class="glass">
  <div style="width:10px;height:10px;background:#22c55e;border-radius:50%"></div>
  <div id="s-name" style="flex:1;font-size:13px;font-weight:700"></div>
  <button onclick="stopSession()" style="background:none;border:1px solid red;color:red;padding:4px 8px;border-radius:5px">Stop</button>
</div>

<div id="stats-strip" class="glass">
  <div class="stat"><div class="sv" id="sv-spd">0</div><div class="sl">km/h</div></div>
  <div class="stat"><div class="sv" id="sv-dst">0.0</div><div class="sl">km</div></div>
  <div class="stat"><div class="sv" id="sv-pts">0</div><div class="sl">pts</div></div>
  <div class="stat"><div class="sv" id="sv-dur">00:00</div><div class="sl">min</div></div>
</div>

<script>
const SUPA_URL = "{supa_url}";
const SUPA_KEY = "{supa_key}";
const COLORS = {colors_json};
const LINE_NAMES = {lines_json};

let sb = supabase.createClient(SUPA_URL, SUPA_KEY);
let session=null, watchId=null, busMarker=null, trailLine=null;
let trailPts=[], totalDist=0, lastPt=null, pointCount=0;

// RECENTER LOGIC
function recenterMap() {{
    if(lastPt) map.setView(lastPt, 16);
}}

// Initialize Map
const map = L.map('map',{{center:[35.56, 45.43],zoom:13}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

// Populate lines
const sel = document.getElementById('sel-line');
LINE_NAMES.forEach(n => {{ let o=document.createElement('option'); o.value=n; o.textContent=n.replace(/_/g,' '); sel.appendChild(o); }});

function startSession() {{
    const plate = document.getElementById('inp-plate').value.toUpperCase();
    const name = document.getElementById('inp-name').value;
    const lineId = document.getElementById('sel-line').value;
    if(!plate || !name || !lineId) return;

    session = {{plate, name, lineId, startTime: Date.now()}};
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('status-bar').style.display = 'flex';
    document.getElementById('stats-strip').style.display = 'flex';
    document.getElementById('recenter-btn').style.display = 'flex';
    document.getElementById('s-name').textContent = plate + ' | ' + lineId;

    watchId = navigator.geolocation.watchPosition(onGPS, null, {{enableHighAccuracy:true}});
    setInterval(tickTimer, 1000);
}}

async function onGPS(pos) {{
    const lat = pos.coords.latitude, lon = pos.coords.longitude;
    const spd = pos.coords.speed ? pos.coords.speed * 3.6 : 0;
    const now = new Date().toISOString();

    lastPt = [lat, lon];
    trailPts.push(lastPt);
    pointCount++;

    // Marker & Trail logic
    if(!busMarker) {{
        busMarker = L.marker(lastPt).addTo(map);
        map.setView(lastPt, 16);
    }} else {{
        busMarker.setLatLng(lastPt);
    }}
    
    if(trailLine) map.removeLayer(trailLine);
    trailLine = L.polyline(trailPts, {{color:'#22c55e', weight:4}}).addTo(map);

    // Update UI
    document.getElementById('sv-spd').textContent = Math.round(spd);
    document.getElementById('sv-pts').textContent = pointCount;

    // Supabase pushes
    sb.from('live_bus_data').upsert({{plate_number:session.plate, driver_name:session.name, lat, lon, line_id:session.lineId, last_ping:now}}, {{onConflict:'plate_number'}}).then();
    sb.from('bus_location_history').insert({{plate_number:session.plate, lat, lon, line_id:session.lineId, recorded_at:now}}).then();
}}

function tickTimer() {{
    if(!session) return;
    const sec = Math.floor((Date.now() - session.startTime)/1000);
    document.getElementById('sv-dur').textContent = Math.floor(sec/60).toString().padStart(2,'0') + ':' + (sec%60).toString().padStart(2,'0');
}}

async function stopSession() {{
    navigator.geolocation.clearWatch(watchId);
    if(session) await sb.from('live_bus_data').delete().eq('plate_number', session.plate);
    location.reload();
}}
</script>
</body>
</html>"""

def main():
    components.html(build_html(SUPA_URL, SUPA_KEY, LINE_NAMES, ROUTE_COLORS), height=800)

if __name__ == "__main__":
    main()
