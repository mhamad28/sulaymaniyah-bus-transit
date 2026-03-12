import json
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parents[1] / "shared"))

st.set_page_config(page_title="Suly Transit – Driver", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
  header[data-testid="stHeader"]   { display:none!important; }
  section[data-testid="stSidebar"] { display:none!important; }
  footer                           { display:none!important; }
  .block-container { padding:0!important; margin:0!important; max-width:100%!important; }
  div[data-testid="stCustomComponentV1"] { margin:0!important; padding:0!important; line-height:0!important; }
</style>
""", unsafe_allow_html=True)

SUPA_URL = st.secrets.get("SUPABASE_URL", "")      if hasattr(st, "secrets") else ""
SUPA_KEY = st.secrets.get("SUPABASE_ANON_KEY", "") if hasattr(st, "secrets") else ""

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

/* RECENTER BUTTON */
#recenter-btn {{
  position:absolute; bottom:110px; right:20px; z-index:1001;
  width:48px; height:48px; border-radius:50%; background:#22c55e;
  border:2px solid #fff; color:white; font-size:20px; cursor:pointer;
  display:none; align-items:center; justify-content:center;
  box-shadow:0 4px 15px rgba(0,0,0,0.4); transition: transform 0.2s;
}}
#recenter-btn:active {{ transform: scale(0.9); }}

/* LOGIN */
#login-screen{{
  position:absolute;inset:0;z-index:2000;
  display:flex;align-items:center;justify-content:center;
  background:rgba(8,13,20,.96);
}}
#login-card{{width:min(380px,90vw);padding:28px 24px;display:flex;flex-direction:column;gap:16px;}}
.logo{{text-align:center;font-size:32px;}}
.login-title{{text-align:center;font-size:17px;font-weight:700;color:#e2eaf4;}}
.login-sub{{text-align:center;font-size:12px;color:#64748b;margin-top:-8px;
  font-family:'Noto Naskh Arabic',sans-serif;}}
.lbl{{font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;
  letter-spacing:.06em;margin-bottom:4px;}}
.inp{{
  width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.13);
  border-radius:10px;padding:11px 14px;font-size:14px;font-family:'Inter',sans-serif;
  color:#e2eaf4;outline:none;transition:border-color .15s;
}}
.inp:focus{{border-color:#00d4ff;}}
.sel{{
  width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.13);
  border-radius:10px;padding:11px 14px;font-size:13px;
  color:#e2eaf4;outline:none;cursor:pointer;appearance:none;
}}
.sel option{{background:#0f172a;color:#e2eaf4;}}
.go-btn{{
  width:100%;padding:13px;border-radius:10px;border:none;
  background:linear-gradient(135deg,#22c55e,#16a34a);
  color:#fff;font-size:15px;font-weight:700;cursor:pointer;
  transition:all .2s;font-family:'Inter',sans-serif;
}}
.go-btn:hover{{transform:translateY(-1px);box-shadow:0 4px 20px rgba(34,197,94,.4);}}
.go-btn:disabled{{background:#1e293b;color:#475569;cursor:not-allowed;transform:none;box-shadow:none;}}

/* STATUS BAR */
#status-bar{{
  position:absolute;top:14px;left:50%;transform:translateX(-50%);
  z-index:1000;width:min(480px,92vw);padding:10px 16px;
  display:none;align-items:center;gap:10px;
}}
.s-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0;}}
.s-dot.green{{background:#22c55e;animation:blink 1.4s infinite;}}
.s-dot.yellow{{background:#fbbf24;animation:blink 1.4s infinite;}}
.s-dot.red{{background:#ef4444;}}
@keyframes blink{{0%,100%{{opacity:1;}}50%{{opacity:.3;}}}}
.s-info{{flex:1;min-width:0;}}
.s-name{{font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.s-detail{{font-size:11px;color:#64748b;margin-top:1px;}}
.stop-btn{{
  flex-shrink:0;padding:6px 14px;border-radius:8px;
  border:1.5px solid #ef4444;background:rgba(239,68,68,.12);
  color:#f87171;font-size:12px;font-weight:700;cursor:pointer;transition:all .15s;
}}
.stop-btn:hover{{background:rgba(239,68,68,.25);}}

/* STATS */
#stats-strip{{
  position:absolute;bottom:20px;left:50%;transform:translateX(-50%);
  z-index:1000;width:min(480px,92vw);padding:10px 16px;
  display:none;flex-direction:row;gap:0;
}}
.stat{{flex:1;text-align:center;padding:4px 8px;border-right:1px solid rgba(255,255,255,.08);}}
.stat:last-child{{border-right:none;}}
.sv{{font-size:20px;font-weight:700;color:#e2eaf4;}}
.sl{{font-size:10px;color:#64748b;margin-top:2px;text-transform:uppercase;letter-spacing:.04em;}}

#toast{{
  position:absolute;bottom:90px;left:50%;transform:translateX(-50%);
  z-index:1001;padding:8px 18px;border-radius:10px;
  background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.3);
  color:#f87171;font-size:12px;display:none;white-space:nowrap;
}}
.leaflet-control-zoom{{border:none!important;}}
.leaflet-control-zoom a{{
  background:rgba(10,16,26,.88)!important;color:#e2eaf4!important;
  border:1px solid rgba(255,255,255,.10)!important;
}}
</style>
</head>
<body>
<div id="map"></div>

<button id="recenter-btn" onclick="recenterMap()">🎯</button>

<div id="login-screen">
  <div id="login-card" class="glass">
    <div class="logo">🚌</div>
    <div class="login-title">Suly Transit — Driver Portal</div>
    <div class="login-sub">پۆرتاڵی شوفێر</div>

    <div>
      <div class="lbl">Plate Number — ژمارەی سەر پلەیت</div>
      <input class="inp" id="inp-plate" placeholder="e.g. 12 A 3456" autocomplete="off" oninput="checkForm()"/>
    </div>
    <div>
      <div class="lbl">Driver Name — ناوی شوفێر</div>
      <input class="inp" id="inp-name" placeholder="Your name" autocomplete="off" oninput="checkForm()"/>
    </div>
    <div>
      <div class="lbl">Bus Line — هێڵی پاس</div>
      <select class="sel" id="sel-line" onchange="checkForm()">
        <option value="">— Choose your line —</option>
      </select>
    </div>

    <button class="go-btn" id="go-btn" onclick="startSession()" disabled>
      🟢 &nbsp;Start Shift — دەستپێکردنی گەشتەکە
    </button>
  </div>
</div>

<div id="status-bar" class="glass">
  <span class="s-dot green" id="s-dot"></span>
  <div class="s-info">
    <div class="s-name" id="s-name">—</div>
    <div class="s-detail" id="s-detail">Acquiring GPS…</div>
  </div>
  <button class="stop-btn" onclick="stopSession()">⏹ Stop</button>
</div>

<div id="stats-strip" class="glass">
  <div class="stat"><div class="sv" id="sv-spd">0</div><div class="sl">km/h</div></div>
  <div class="stat"><div class="sv" id="sv-dst">0.0</div><div class="sl">km total</div></div>
  <div class="stat"><div class="sv" id="sv-pts">0</div><div class="sl">points</div></div>
  <div class="stat"><div class="sv" id="sv-dur">00:00</div><div class="sl">duration</div></div>
</div>

<div id="toast"></div>

<script>
const SUPA_URL   = "{supa_url}";
const SUPA_KEY   = "{supa_key}";
const LINE_NAMES = {lines_json};
const COLORS     = {colors_json};

// Supabase
let sb = null;
if(SUPA_URL && SUPA_KEY) {{
  sb = supabase.createClient(SUPA_URL, SUPA_KEY, {{auth:{{persistSession:false}}}});
}}

// Populate line dropdown
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

// Map
const map = L.map('map',{{center:[{DEFAULT_CENTER[0]},{DEFAULT_CENTER[1]}],zoom:{DEFAULT_ZOOM},minZoom:10,maxZoom:19}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap',maxZoom:19}}).addTo(map);

// Session state
let session=null, watchId=null, busMarker=null, trailLine=null;
let trailPts=[], totalDist=0, lastPt=null, pointCount
