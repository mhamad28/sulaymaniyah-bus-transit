import json
import sys
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

# --- 1. SETUP & CONFIG ---
st.set_page_config(page_title="Suly Transit – Driver", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  header[data-testid="stHeader"]   { display:none!important; }
  section[data-testid="stSidebar"] { display:none!important; }
  footer                            { display:none!important; }
  .stDeployButton                   { display:none!important; }
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
DEFAULT_CENTER = [35.56, 45.43]
DEFAULT_ZOOM   = 13

# --- 2. HTML/JS/CSS BUILDER ---
def build_html(supa_url, supa_key, line_names, route_colors):
    lines_json  = json.dumps(line_names)
    colors_json = json.dumps(route_colors)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Noto+Naskh+Arabic:wght@400;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{width:100%;height:100%;background:#080d14;overflow:hidden;font-family:'Inter',sans-serif;}}
#map{{width:100%;height:100vh;}}

.glass{{
  background:rgba(10,16,26,.92);backdrop-filter:blur(18px);
  border:1px solid rgba(255,255,255,.10);border-radius:16px;
  box-shadow:0 8px 32px rgba(0,0,0,.55);color:#e2eaf4;
}}

#recenter-btn {{
  position: absolute; bottom: 110px; right: 20px; z-index: 1001;
  width: 50px; height: 50px; border-radius: 12px; background: #000;
  border: 1px solid rgba(255,255,255,0.2); cursor: pointer;
  display: none; align-items: center; justify-content: center;
}}
#recenter-btn::before {{
  content: ""; width: 28px; height: 28px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2300E5FF' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='3' fill='%2300E5FF'/%3E%3Ccircle cx='12' cy='12' r='7'/%3E%3Cline x1='12' y1='1' x2='12' y2='5'/%3E%3Cline x1='12' y1='19' x2='12' y2='23'/%3E%3Cline x1='1' y1='12' x2='5' y2='12'/%3E%3Cline x1='19' y1='12' x2='23' y2='12'/%3E%3C/svg%3E");
  background-size: contain; background-repeat: no-repeat;
}}

#login-screen{{
  position:absolute;inset:0;z-index:2000;
  display:flex;align-items:center;justify-content:center;
  background:rgba(8,13,20,.96);
}}
#login-card{{width:min(380px,90vw);padding:28px 24px;display:flex;flex-direction:column;gap:16px;}}
.inp, .sel{{
  width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.13);
  border-radius:10px;padding:11px 14px;font-size:14px;color:#e2eaf4;outline:none;
}}
.go-btn{{
  width:100%;padding:13px;border-radius:10px;border:none;
  background:linear-gradient(135deg,#22c55e,#16a34a);
  color:#fff;font-size:15px;font-weight:700;cursor:pointer;
}}
.go-btn:disabled{{background:#1e293b;color:#475569;}}

#status-bar{{position:absolute;top:14px;left:50%;transform:translateX(-50%);z-index:1000;width:min(480px,92vw);padding:10px 16px;display:none;align-items:center;gap:10px;}}
.s-dot.green{{width:10px;height:10px;border-radius:50%;background:#22c55e;animation:blink 1.4s infinite;}}
@keyframes blink{{0%,100%{{opacity:1;}}50%{{opacity:.3;}}}}
.stop-btn{{padding:6px 14px;border-radius:8px;border:1.5px solid #ef4444;background:rgba(239,68,68,.12);color:#f87171;cursor:pointer;}}

#stats-strip{{position:absolute;bottom:20px;left:50%;transform:translateX(-50%);z-index:1000;width:min(480px,92vw);padding:10px 16px;display:none;}}
.stat{{flex:1;text-align:center;}}
.sv{{font-size:20px;font-weight:700;}}
</style>
</head>
<body>
<div id="map"></div>
<button id="recenter-btn" onclick="recenterMap()"></button>

<div id="login-screen">
  <div id="login-card" class="glass">
    <div class="login-title">Suly Transit — Driver Portal</div>
    <input class="inp" id="inp-plate" placeholder="Plate Number" oninput="checkForm()"/>
    <input class="inp" id="inp-name" placeholder="Driver Name" oninput="checkForm()"/>
    <select class="sel" id="sel-line" onchange="checkForm()"><option value="">— Choose Line —</option></select>
    <button class="go-btn" id="go-btn" onclick="startSession()" disabled>🟢 Start Shift</button>
  </div>
</div>

<div id="status-bar" class="glass">
  <span class="s-dot green"></span>
  <div style="flex:1"><div id="s-name" style="font-weight:700"></div><div id="s-detail" style="font-size:11px;color:#64748b">GPS Active</div></div>
  <button class="stop-btn" onclick="stopSession()">⏹ Stop</button>
</div>

<div id="stats-strip" class="glass" style="display:none; gap:10px; justify-content:space-around;">
  <div class="stat"><div class="sv" id="sv-spd">0</div><div style="font-size:10px">km/h</div></div>
  <div class="stat"><div class="sv" id="sv-dst">0.0</div><div style="font-size:10px">km</div></div>
  <div class="stat"><div class="sv" id="sv-dur">00:00</div><div style="font-size:10px">duration</div></div>
</div>

<script>
const SUPA_URL = "{supa_url}";
const SUPA_KEY = "{supa_key}";
const LINE_NAMES = {lines_json};
const COLORS = {colors_json};

let sb = supabase.createClient(SUPA_URL, SUPA_KEY, {{auth:{{persistSession:false}}}});

const sel = document.getElementById('sel-line');
LINE_NAMES.forEach(name => {{
  const o = document.createElement('option');
  o.value = name;
  o.textContent = name.replace(/_/g,' ');
  sel.appendChild(o);
}});

function checkForm() {{
  const ok = document.getElementById('inp-plate').value.trim() &&
             document.getElementById('inp-name').value.trim() &&
             document.getElementById('sel-line').value;
  document.getElementById('go-btn').disabled = !ok;
}}

const map = L.map('map',{{center:[{DEFAULT_CENTER[0]},{DEFAULT_CENTER[1]}],zoom:13}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

let session=null, watchId=null, busMarker=null, trailLine=null;
let trailPts=[], totalDist=0, lastPt=null, timerInt=null;

function hav(la1,lo1,la2,lo2) {{
  const R=6371,r=Math.PI/180;
  const a=Math.sin((la2-la1)*r/2)**2+Math.cos(la1*r)*Math.cos(la2*r)*Math.sin((lo2-lo1)*r/2)**2;
  return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

function busIcon(color, plate) {{
  return L.divIcon({{
    html:`<div style="background:${{color}};color:#fff;font-size:10px;font-weight:700;padding:4px 9px;border-radius:8px;border:2px solid #fff;">${{plate}}</div>`,
    className:'', iconAnchor:[32,14]
  }});
}}

function recenterMap() {{ if(lastPt) map.setView(lastPt, 16); }}

// --- FIXED PERSISTENCE LOGIC ---
function startSession(existingSession = null) {{
  if (existingSession) {{
    session = existingSession;
  }} else {{
    const plate = document.getElementById('inp-plate').value.trim().toUpperCase();
    const name = document.getElementById('inp-name').value.trim();
    const lineId = document.getElementById('sel-line').value;
    const color = COLORS[lineId] || '#00d4ff';
    session = {{plate, name, lineId, color, startTime: Date.now()}};
    localStorage.setItem('bus_session', JSON.stringify(session));
  }}

  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('status-bar').style.display = 'flex';
  document.getElementById('stats-strip').style.display = 'flex';
  document.getElementById('recenter-btn').style.display = 'flex';
  document.getElementById('s-name').textContent = session.plate + ' · ' + session.name;
  
  timerInt = setInterval(tickTimer, 1000);
  watchId = navigator.geolocation.watchPosition(onGPS, null, {{enableHighAccuracy:true}});
}}

async function onGPS(pos) {{
  const lat = pos.coords.latitude, lon = pos.coords.longitude;
  const spd = pos.coords.speed != null ? +(pos.coords.speed * 3.6).toFixed(1) : 0;
  const now = new Date().toISOString();
  trailPts.push([lat, lon]);
  if(lastPt) totalDist += hav(lastPt[0], lastPt[1], lat, lon);
  lastPt = [lat, lon];
  
  if(!busMarker) {{
    busMarker = L.marker([lat,lon], {{icon:busIcon(session.color, session.plate)}}).addTo(map);
    map.setView([lat,lon], 15);
  }} else {{
    busMarker.setLatLng([lat,lon]);
  }}
  
  document.getElementById('sv-spd').textContent = Math.round(spd);
  document.getElementById('sv-dst').textContent = totalDist.toFixed(2);
  
  sb.from('active_locations').upsert({{
    bus_number:session.plate, 
    bus_line:session.lineId, 
    lat, lon, 
    speed_kmh:spd, 
    updated_at:now, 
    is_active:true
  }}, {{onConflict:'bus_number'}}).then();
}}

function tickTimer() {{
  if(!session) return;
  const s = Math.round((Date.now() - session.startTime) / 1000);
  document.getElementById('sv-dur').textContent = String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
}}

async function stopSession() {{
  navigator.geolocation.clearWatch(watchId);
  clearInterval(timerInt);
  if(sb && session) await sb.from('active_locations').delete().eq('bus_number', session.plate);
  localStorage.removeItem('bus_session');
  location.reload();
}}

// AUTO-RESUME CHECK
window.onload = () => {{
  const saved = localStorage.getItem('bus_session');
  if (saved) {{
    const parsed = JSON.parse(saved);
    // Resume if session is less than 12 hours old
    if (Date.now() - parsed.startTime < 43200000) {{
       startSession(parsed);
    }} else {{
       localStorage.removeItem('bus_session');
    }}
  }}
}};
</script>
</body>
</html>"""

def main():
    components.html(build_html(SUPA_URL, SUPA_KEY, LINE_NAMES, ROUTE_COLORS), height=900, scrolling=False)

if __name__ == "__main__":
    main()
